# snr_detector.py — deteksi zona SNR otomatis berbasis struktur market

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List, Tuple
from config import FIBO_LEVELS, FIBO_ZONE


@dataclass
class SNRZone:
    price:      float
    upper:      float
    lower:      float
    zone_type:  str
    strength:   int
    timeframe:  str
    last_touch: pd.Timestamp

    @property
    def width_pip(self) -> float:
        return (self.upper - self.lower) * 10

    def __repr__(self):
        return (f"SNR({self.zone_type[:3].upper()} "
                f"{self.lower:.2f}–{self.upper:.2f} "
                f"str={self.strength} tf={self.timeframe})")


@dataclass
class FiboLevel:
    level:      float
    price:      float
    swing_high: float
    swing_low:  float
    direction:  str

    def __repr__(self):
        return f"Fibo({self.level:.3f} @ {self.price:.2f} {self.direction})"


def detect_swing_points(df: pd.DataFrame, lookback: int = 5) -> Tuple[List, List]:
    highs = df["high"].values
    lows  = df["low"].values
    swing_highs, swing_lows = [], []

    for i in range(lookback, len(df) - lookback):
        if highs[i] == max(highs[i - lookback: i + lookback + 1]):
            swing_highs.append((df.index[i], highs[i]))
        if lows[i] == min(lows[i - lookback: i + lookback + 1]):
            swing_lows.append((df.index[i], lows[i]))

    return swing_highs, swing_lows


def detect_snr_zones(df: pd.DataFrame, timeframe: str,
                     zone_tolerance: float = 0.3,
                     min_touches: int = 2) -> List[SNRZone]:
    swing_highs, swing_lows = detect_swing_points(df)
    current_price = df["close"].iloc[-1]

    resistance_zones = _cluster_levels(
        [(t, p) for t, p in swing_highs], zone_tolerance,
        df, "resistance", timeframe, min_touches)

    support_zones = _cluster_levels(
        [(t, p) for t, p in swing_lows], zone_tolerance,
        df, "support", timeframe, min_touches)

    zones = resistance_zones + support_zones
    relevant = [z for z in zones
                if abs(z.price - current_price) / current_price * 100 <= 5.0]
    relevant.sort(key=lambda z: z.strength, reverse=True)
    return relevant


def _cluster_levels(points, tolerance, df, zone_type, timeframe, min_touches):
    if not points:
        return []

    prices = [p for _, p in points]
    times  = [t for t, _ in points]
    used   = [False] * len(prices)
    zones  = []

    for i in range(len(prices)):
        if used[i]:
            continue
        cluster_prices = [prices[i]]
        cluster_times  = [times[i]]
        used[i] = True

        for j in range(i + 1, len(prices)):
            if used[j]:
                continue
            if abs(prices[j] - prices[i]) / prices[i] * 100 <= tolerance:
                cluster_prices.append(prices[j])
                cluster_times.append(times[j])
                used[j] = True

        if len(cluster_prices) < min_touches:
            continue

        avg_price  = np.mean(cluster_prices)
        std_price  = np.std(cluster_prices) if len(cluster_prices) > 1 else avg_price * 0.001
        zone_width = max(std_price * 2, avg_price * 0.001)

        zones.append(SNRZone(
            price      = avg_price,
            upper      = avg_price + zone_width,
            lower      = avg_price - zone_width,
            zone_type  = zone_type,
            strength   = len(cluster_prices),
            timeframe  = timeframe,
            last_touch = max(cluster_times),
        ))

    return zones


def calculate_fibonacci(df: pd.DataFrame, lookback: int = 50) -> List[FiboLevel]:
    if df is None or len(df) < 2:
        return []
    window = df.tail(lookback).dropna(subset=["high", "low"])
    if len(window) < 2:
        return []
    swing_high_price = window["high"].max()
    swing_low_price  = window["low"].min()
    if swing_high_price == swing_low_price:
        return []
    idx_high = window["high"].idxmax()
    idx_low  = window["low"].idxmin()

    if idx_low > idx_high:
        direction  = "bearish"
        fib_range  = swing_high_price - swing_low_price
        base_price = swing_high_price
        sign       = -1
    else:
        direction  = "bullish"
        fib_range  = swing_high_price - swing_low_price
        base_price = swing_low_price
        sign       = 1

    return [
        FiboLevel(
            level      = lvl,
            price      = base_price + sign * fib_range * lvl,
            swing_high = swing_high_price,
            swing_low  = swing_low_price,
            direction  = direction,
        )
        for lvl in FIBO_LEVELS
    ]


def find_confluences(snr_zones: List[SNRZone],
                     fibo_levels: List[FiboLevel],
                     current_price: float,
                     tolerance_pip: float = 15.0) -> List[dict]:
    """
    Cari confluence SNR + Fibonacci.
    tolerance_pip dinaikkan ke 15 pip supaya lebih sensitif untuk gold.
    Juga tangkap kasus Fibo dekat harga meski belum ada zona SNR tepat di sana.
    """
    confluences = []
    tolerance_price = tolerance_pip * 0.1

    # ── Case 1: Fibo bertemu zona SNR ──────────────────────────
    for zone in snr_zones:
        for fib in fibo_levels:
            fib_in_zone   = zone.lower <= fib.price <= zone.upper
            fib_near_zone = abs(fib.price - zone.price) <= tolerance_price

            if fib_in_zone or fib_near_zone:
                is_golden = fib.level in FIBO_ZONE
                dist_pip  = abs(current_price - fib.price) * 10

                signal = _determine_signal_type(zone, fib, current_price)
                confluences.append({
                    "price":        fib.price,
                    "zone":         zone,
                    "fibo":         fib,
                    "strength":     zone.strength + (2 if is_golden else 1),
                    "distance_pip": dist_pip,
                    "signal_type":  signal,
                    "source":       "snr+fibo",
                })

    # ── Case 2: Fibo dekat harga saat ini (≤ 20 pip) tanpa SNR ──
    # Ini tangkap setup seperti output kamu tadi (0.382 @ 4537, 5 pip dari harga)
    for fib in fibo_levels:
        dist_pip = abs(current_price - fib.price) * 10
        if dist_pip <= 20.0:
            # Cek apakah sudah ada di confluences
            already = any(abs(c["price"] - fib.price) < 0.5 for c in confluences)
            if not already:
                signal = _signal_from_fibo_only(fib, current_price)
                is_golden = fib.level in FIBO_ZONE
                confluences.append({
                    "price":        fib.price,
                    "zone":         None,
                    "fibo":         fib,
                    "strength":     1 + (2 if is_golden else 0),
                    "distance_pip": dist_pip,
                    "signal_type":  signal,
                    "source":       "fibo_only",
                })

    # Sort: dekat harga dulu, lalu terkuat
    confluences.sort(key=lambda x: (x["distance_pip"], -x["strength"]))
    return confluences


def _determine_signal_type(zone: SNRZone, fib: FiboLevel,
                            current_price: float) -> str:
    """
    Logic yang diperbaiki:
    - Harga mendekati resistance dari bawah → SELL
    - Harga mendekati support dari atas      → BUY
    - Fibo bearish + resistance               → perkuat SELL
    - Fibo bullish + support                  → perkuat BUY
    """
    price_below_zone = current_price < zone.price
    price_above_zone = current_price > zone.price

    # Harga di bawah resistance → mendekat untuk di-sell
    if zone.zone_type == "resistance" and price_below_zone:
        return "SELL"

    # Harga di atas support → mendekat untuk di-buy
    if zone.zone_type == "support" and price_above_zone:
        return "BUY"

    # Harga sudah menembus zona — cek apakah retest
    if zone.zone_type == "resistance" and price_above_zone:
        # Harga di atas resistance → resistance bisa jadi support baru → BUY retest
        return "BUY"

    if zone.zone_type == "support" and price_below_zone:
        # Harga di bawah support → support jadi resistance → SELL retest
        return "SELL"

    return "NEUTRAL"


def _signal_from_fibo_only(fib: FiboLevel, current_price: float) -> str:
    """Tentukan signal hanya dari Fibonacci tanpa zona SNR."""
    price_at_fibo = abs(current_price - fib.price) * 10 <= 10  # dalam 10 pip

    if not price_at_fibo:
        return "NEUTRAL"

    # Bearish retracement + harga di level fibo → setup SELL
    if fib.direction == "bearish":
        return "SELL"

    # Bullish retracement + harga di level fibo → setup BUY
    if fib.direction == "bullish":
        return "BUY"

    return "NEUTRAL"


def grade_setup(confluences: List[dict], has_volume_confirm: bool = False,
                in_session: bool = True) -> str:
    """
    A+ → confluence SNR+Fibo, golden zone, strength ≥ 3, volume, session
    A  → confluence SNR+Fibo atau Fibo dekat, strength ≥ 2, session
    B  → ada confluence tapi kurang sempurna
    """
    if not confluences:
        return "NONE"

    # Filter yang punya sinyal jelas dulu
    actionable = [c for c in confluences if c["signal_type"] in ("BUY", "SELL")]
    if not actionable:
        return "NONE"

    best       = actionable[0]
    is_golden  = best["fibo"].level in FIBO_ZONE
    strength   = best["strength"]
    has_snr    = best["source"] == "snr+fibo"

    if has_snr and is_golden and strength >= 3 and has_volume_confirm and in_session:
        return "A+"
    elif has_snr and strength >= 2 and in_session:
        return "A"
    elif strength >= 1 and in_session:
        return "B"
    else:
        return "NONE"


def get_sl_price(signal_type: str, zone: SNRZone,
                 current_price: float, buffer_pip: float = 3.0) -> float:
    """
    Hitung harga SL berbasis struktur SNR (bukan fixed pip).
    Buffer 3 pip di luar zona supaya tidak kena spike.
    """
    buffer = buffer_pip * 0.1

    if zone is None:
        # Fallback ke fixed pip kalau tidak ada zona
        if signal_type == "BUY":
            return current_price - 2.0  # 20 pip
        else:
            return current_price + 2.0

    if signal_type == "BUY":
        return zone.lower - buffer   # SL di bawah support
    elif signal_type == "SELL":
        return zone.upper + buffer   # SL di atas resistance
    else:
        return 0.0


def get_tp_price(signal_type: str, current_price: float,
                 sl_price: float, rr: float = 2.0) -> float:
    """Hitung TP berdasarkan RR dari SL aktual."""
    risk = abs(current_price - sl_price)
    if signal_type == "BUY":
        return current_price + risk * rr
    elif signal_type == "SELL":
        return current_price - risk * rr
    return 0.0


def print_snr_summary(zones: List[SNRZone], confluences: List[dict],
                      current_price: float):
    print(f"\n{'─'*52}")
    print(f"  SNR Analysis — Current: {current_price:.2f}")
    print(f"{'─'*52}")

    print(f"\n  Zona SNR terdeteksi ({len(zones)}):")
    for z in zones[:6]:
        dist = (z.price - current_price) * 10
        marker = "▲" if z.zone_type == "support" else "▼"
        print(f"  {marker} {z.zone_type:10} {z.lower:.2f}–{z.upper:.2f}  "
              f"str={z.strength}  dist={dist:+.1f}pip  [{z.timeframe}]")

    actionable = [c for c in confluences if c["signal_type"] in ("BUY", "SELL")]
    if actionable:
        print(f"\n  Confluence actionable ({len(actionable)}):")
        for c in actionable[:4]:
            src = c["source"]
            print(f"  ★ {c['signal_type']:4} @ {c['price']:.2f}  "
                  f"fibo={c['fibo'].level:.3f}  "
                  f"str={c['strength']}  "
                  f"dist={c['distance_pip']:.1f}pip  [{src}]")
    else:
        print("\n  Tidak ada confluence actionable saat ini.")
    print(f"{'─'*52}")


def is_price_at_zone(current_price: float, confluence: dict,
                     entry_tolerance_pip: float = 15.0) -> bool:
    """
    Cek apakah harga sudah cukup dekat dengan zona confluence untuk entry.
    Hanya return True kalau harga dalam entry_tolerance_pip dari zona.
    """
    dist_pip = abs(current_price - confluence["price"]) * 10
    return dist_pip <= entry_tolerance_pip


def filter_ready_confluences(confluences: list, current_price: float,
                              entry_tolerance_pip: float = 15.0) -> list:
    """
    Filter confluences — hanya yang harganya sudah dekat (siap entry).
    Sisanya masuk watchlist (harga belum sampai).
    """
    ready     = []
    watchlist = []

    for c in confluences:
        if c["signal_type"] not in ("BUY", "SELL"):
            continue
        dist_pip = abs(current_price - c["price"]) * 10
        if dist_pip <= entry_tolerance_pip:
            ready.append(c)
        else:
            watchlist.append(c)

    return ready, watchlist