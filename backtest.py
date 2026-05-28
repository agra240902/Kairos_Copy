# backtest.py — simulasi strategi di data historis

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Optional
import MetaTrader5 as mt5

from connector import connect, disconnect
from snr_detector import (detect_snr_zones, calculate_fibonacci,
                           find_confluences, filter_ready_confluences,
                           get_sl_price, get_tp_price)
from session_filter import get_current_session, is_in_killzone
from volume_analyzer import get_volume_strength, get_price_action_confirmation
from config import SYMBOL, LOT_GRADE, MODE_CONFIG, FIBO_ZONE


# ── Data structures ─────────────────────────────────────────

@dataclass
class BacktestTrade:
    """Satu trade dalam simulasi backtest."""
    entry_time:   datetime
    exit_time:    Optional[datetime]
    signal_type:  str           # BUY / SELL
    entry_price:  float
    sl_price:     float
    tp_price:     float
    exit_price:   float         = 0.0
    lot:          float         = 0.01
    grade:        str           = "B"
    mode:         str           = "scalp"
    result:       str           = ""    # WIN / LOSS / OPEN
    profit_pip:   float         = 0.0
    profit_usd:   float         = 0.0
    profit_idr:   float         = 0.0
    risk_pip:     float         = 0.0


@dataclass
class BacktestResult:
    """Hasil lengkap satu sesi backtest."""
    symbol:         str
    mode:           str
    start_date:     str
    end_date:       str
    timeframe:      str
    initial_balance: float
    trades:         List[BacktestTrade] = field(default_factory=list)

    @property
    def total_trades(self) -> int:
        return len(self.closed_trades)

    @property
    def closed_trades(self) -> List[BacktestTrade]:
        return [t for t in self.trades if t.result in ("WIN", "LOSS")]

    @property
    def wins(self) -> List[BacktestTrade]:
        return [t for t in self.closed_trades if t.result == "WIN"]

    @property
    def losses(self) -> List[BacktestTrade]:
        return [t for t in self.closed_trades if t.result == "LOSS"]

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return len(self.wins) / self.total_trades * 100

    @property
    def total_profit_usd(self) -> float:
        return sum(t.profit_usd for t in self.closed_trades)

    @property
    def total_profit_idr(self) -> float:
        return sum(t.profit_idr for t in self.closed_trades)

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.profit_usd for t in self.wins)
        gross_loss   = abs(sum(t.profit_usd for t in self.losses))
        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0.0
        return round(gross_profit / gross_loss, 2)

    @property
    def max_drawdown_usd(self) -> float:
        if not self.closed_trades:
            return 0.0
        balance     = self.initial_balance
        peak        = balance
        max_dd      = 0.0
        for t in self.closed_trades:
            balance += t.profit_usd
            peak     = max(peak, balance)
            dd       = peak - balance
            max_dd   = max(max_dd, dd)
        return round(max_dd, 2)

    @property
    def avg_win_pip(self) -> float:
        if not self.wins:
            return 0.0
        return round(sum(t.profit_pip for t in self.wins) / len(self.wins), 1)

    @property
    def avg_loss_pip(self) -> float:
        if not self.losses:
            return 0.0
        return round(sum(t.profit_pip for t in self.losses) / len(self.losses), 1)

    @property
    def expectancy_usd(self) -> float:
        """Expected value per trade dalam USD."""
        if self.total_trades == 0:
            return 0.0
        return round(self.total_profit_usd / self.total_trades, 3)

    @property
    def final_balance(self) -> float:
        return self.initial_balance + self.total_profit_usd


# ── Data loader ─────────────────────────────────────────────

def load_historical_data(timeframe: str, days: int = 90) -> pd.DataFrame:
    """
    Ambil data historis dari MT5.
    Default 90 hari — cukup untuk validasi awal.
    """
    tf_map = {
        "M5":  mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "H1":  mt5.TIMEFRAME_H1,
        "H4":  mt5.TIMEFRAME_H4,
        "D1":  mt5.TIMEFRAME_D1,
    }
    tf = tf_map.get(timeframe)
    if tf is None:
        raise ValueError(f"Timeframe tidak valid: {timeframe}")

    # Hitung jumlah candle yang dibutuhkan
    candles_per_day = {"M5": 288, "M15": 96, "H1": 24, "H4": 6, "D1": 1}
    n_candles = candles_per_day.get(timeframe, 96) * days + 500

    rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, n_candles)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"Gagal ambil data {timeframe}: {mt5.last_error()}")

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df[["time", "open", "high", "low", "close", "tick_volume"]].copy()
    df.rename(columns={"tick_volume": "volume"}, inplace=True)
    df.set_index("time", inplace=True)

    # Filter ke periode yang diminta
    cutoff = datetime.now() - timedelta(days=days)
    df     = df[df.index >= cutoff]

    print(f"[DATA] {timeframe}: {len(df)} candle "
          f"({df.index[0].strftime('%Y-%m-%d')} → "
          f"{df.index[-1].strftime('%Y-%m-%d')})")
    return df


# ── Signal detector untuk backtest ──────────────────────────

def detect_signal_at(df_entry: pd.DataFrame, df_confirm: pd.DataFrame,
                     df_higher: pd.DataFrame, idx: int,
                     mode: str = "scalp") -> Optional[dict]:
    """
    Jalankan signal detection di satu titik waktu (candle ke-idx).
    Hanya gunakan data yang tersedia SEBELUM candle tersebut (no lookahead).
    """
    if idx < 50:
        return None

    current_candle = df_entry.iloc[idx]
    current_price  = current_candle["close"]
    current_time   = df_entry.index[idx]

    # Slice entry — hanya data sebelum candle saat ini
    window_entry = df_entry.iloc[max(0, idx - 200):idx]
    if len(window_entry) < 20:
        return None

    # Sync confirm dan higher berdasarkan WAKTU
    window_confirm = df_confirm[df_confirm.index <= current_time].tail(200)
    window_higher  = df_higher[df_higher.index <= current_time].tail(200)

    if len(window_confirm) < 10 or len(window_higher) < 5:
        return None

    # Session — gunakan waktu candle historis (bukan now())
    session = get_current_session(current_time.to_pydatetime())
    in_kz   = is_in_killzone(current_time.to_pydatetime())

    # SNR dari semua timeframe
    all_zones = []
    for w, label in [(window_entry, "entry"), (window_confirm, "confirm"),
                     (window_higher, "higher")]:
        if len(w) >= 20:
            all_zones.extend(detect_snr_zones(w, timeframe=label,
                                               min_touches=2))

    if not all_zones:
        return None

    # Fibonacci dari confirm timeframe
    fibo_levels = calculate_fibonacci(window_confirm, lookback=50)
    if not fibo_levels:
        return None

    # Confluence — longgarkan tolerance ke 25 pip untuk backtest
    confluences      = find_confluences(all_zones, fibo_levels, current_price,
                                        tolerance_pip=25.0)
    ready, watchlist = filter_ready_confluences(confluences, current_price,
                                                entry_tolerance_pip=25.0)
    if not ready:
        return None

    best   = ready[0]
    signal = best["signal_type"]
    if signal not in ("BUY", "SELL"):
        return None

    zone = best["zone"]

    # Volume confirmation
    vol_info = get_volume_strength(window_entry, lookback=20)
    has_vol  = vol_info["is_spike"]

    # Price action confirmation
    pa_info = get_price_action_confirmation(window_entry, signal)

    # SL/TP berbasis struktur
    cfg      = MODE_CONFIG[mode]
    sl_price = get_sl_price(signal, zone, current_price)
    tp_price = get_tp_price(signal, current_price, sl_price, rr=cfg["tp_rr"])
    risk_pip = abs(current_price - sl_price) * 10

    # Guard SL — lebih longgar di backtest
    max_risk = cfg["sl_pip"] * 3.0
    if risk_pip > max_risk or risk_pip < 3:
        return None

    # Grading — di backtest tidak wajib in_kz untuk grade B
    is_golden = best["fibo"].level in FIBO_ZONE
    strength  = best["strength"]
    has_snr   = best["source"] == "snr+fibo"

    if has_snr and is_golden and strength >= 3 and has_vol and pa_info["confirmed"] and in_kz:
        grade = "A+"
    elif has_snr and strength >= 2 and (has_vol or pa_info["confirmed"]):
        grade = "A"
    elif has_snr and strength >= 1:
        grade = "B"
    elif best["source"] == "fibo_only" and is_golden:
        grade = "B"
    else:
        return None

    lot = LOT_GRADE.get(grade, 0.01)

    return {
        "time":        current_time,
        "signal_type": signal,
        "entry_price": current_price,
        "sl_price":    sl_price,
        "tp_price":    tp_price,
        "risk_pip":    risk_pip,
        "lot":         lot,
        "grade":       grade,
        "session":     session,
        "in_kz":       in_kz,
    }


def simulate_trade_outcome(signal: dict, df_future: pd.DataFrame,
                            max_candles: int = 200) -> BacktestTrade:
    """
    Simulasikan hasil trade — apakah SL atau TP yang kena duluan.

    Args:
        signal     : dict dari detect_signal_at
        df_future  : candle-candle setelah entry
        max_candles: batas waktu trade (candle timeout)
    """
    trade = BacktestTrade(
        entry_time  = signal["time"],
        exit_time   = None,
        signal_type = signal["signal_type"],
        entry_price = signal["entry_price"],
        sl_price    = signal["sl_price"],
        tp_price    = signal["tp_price"],
        lot         = signal["lot"],
        grade       = signal["grade"],
        risk_pip    = signal["risk_pip"],
    )

    pip_value = 0.01 * signal["lot"] * 100  # USD per pip untuk lot ini

    for i, (ts, candle) in enumerate(df_future.iterrows()):
        if i >= max_candles:
            # Timeout — close di harga close candle terakhir
            trade.exit_time  = ts
            trade.exit_price = candle["close"]
            trade.result     = "LOSS" if (
                (trade.signal_type == "BUY"  and candle["close"] < trade.entry_price) or
                (trade.signal_type == "SELL" and candle["close"] > trade.entry_price)
            ) else "WIN"
            pips = (trade.exit_price - trade.entry_price) * 10
            if trade.signal_type == "SELL":
                pips = -pips
            trade.profit_pip = round(pips, 1)
            trade.profit_usd = round(pips * pip_value / 100, 2)
            trade.profit_idr = round(trade.profit_usd * 17800, 0)
            break

        high = candle["high"]
        low  = candle["low"]

        if trade.signal_type == "BUY":
            if low <= trade.sl_price:
                trade.exit_time  = ts
                trade.exit_price = trade.sl_price
                trade.result     = "LOSS"
                trade.profit_pip = round((trade.sl_price - trade.entry_price) * 10, 1)
                trade.profit_usd = round(trade.profit_pip * pip_value / 100, 2)
                trade.profit_idr = round(trade.profit_usd * 17800, 0)
                break
            if high >= trade.tp_price:
                trade.exit_time  = ts
                trade.exit_price = trade.tp_price
                trade.result     = "WIN"
                trade.profit_pip = round((trade.tp_price - trade.entry_price) * 10, 1)
                trade.profit_usd = round(trade.profit_pip * pip_value / 100, 2)
                trade.profit_idr = round(trade.profit_usd * 17800, 0)
                break

        elif trade.signal_type == "SELL":
            if high >= trade.sl_price:
                trade.exit_time  = ts
                trade.exit_price = trade.sl_price
                trade.result     = "LOSS"
                trade.profit_pip = round((trade.entry_price - trade.sl_price) * 10, 1)
                trade.profit_usd = round(trade.profit_pip * pip_value / 100, 2)
                trade.profit_idr = round(trade.profit_usd * 17800, 0)
                break
            if low <= trade.tp_price:
                trade.exit_time  = ts
                trade.exit_price = trade.tp_price
                trade.result     = "WIN"
                trade.profit_pip = round((trade.entry_price - trade.tp_price) * 10, 1)
                trade.profit_usd = round(trade.profit_pip * pip_value / 100, 2)
                trade.profit_idr = round(trade.profit_usd * 17800, 0)
                break
    else:
        trade.result = "OPEN"

    return trade


# ── Main backtest runner ─────────────────────────────────────

def run_backtest(mode: str = "scalp", days: int = 90,
                 initial_balance: float = 50.0) -> BacktestResult:
    """
    Jalankan backtest lengkap untuk satu mode.

    Args:
        mode            : "scalp", "intraday", atau "swing"
        days            : berapa hari ke belakang
        initial_balance : balance awal simulasi (USD)
    """
    cfg        = MODE_CONFIG[mode]
    tf_entry   = cfg["timeframe_entry"]
    tf_confirm = cfg["timeframe_confirm"]

    # Tentukan higher timeframe
    tf_higher_map = {"M15": "H4", "H1": "D1", "H4": "D1"}
    tf_higher     = tf_higher_map.get(tf_entry, "D1")

    print(f"\n[BACKTEST] Mode: {mode.upper()} | "
          f"TF: {tf_entry}/{tf_confirm}/{tf_higher} | "
          f"Periode: {days} hari")
    print("─" * 60)

    # Load data
    df_entry   = load_historical_data(tf_entry,   days + 10)
    df_confirm = load_historical_data(tf_confirm, days + 10)
    df_higher  = load_historical_data(tf_higher,  days + 10)

    result = BacktestResult(
        symbol          = SYMBOL,
        mode            = mode,
        start_date      = df_entry.index[50].strftime("%Y-%m-%d"),
        end_date        = df_entry.index[-1].strftime("%Y-%m-%d"),
        timeframe       = tf_entry,
        initial_balance = initial_balance,
    )

    open_trade: Optional[BacktestTrade] = None
    last_entry_idx = -10
    total          = len(df_entry) - 51
    milestone      = max(1, total // 10)

    print(f"[SCAN] Memproses {len(df_entry)} candle... (ini mungkin 2–3 menit)")

    # Scan setiap candle
    for idx in range(50, len(df_entry) - 1):
        # Progress indicator setiap 10%
        done = idx - 50
        if done % milestone == 0:
            pct = done / total * 100
            trades_so_far = len([t for t in result.trades if t.result != "OPEN"])
            print(f"  {pct:5.0f}% | candle {idx}/{len(df_entry)} "
                  f"| trades: {trades_so_far}", end="\r")

        # Skip kalau masih ada trade terbuka
        if open_trade is not None:
            candle = df_entry.iloc[idx]
            if open_trade.signal_type == "BUY":
                if candle["low"] <= open_trade.sl_price:
                    open_trade.exit_time  = df_entry.index[idx]
                    open_trade.exit_price = open_trade.sl_price
                    open_trade.result     = "LOSS"
                    _finalize_trade(open_trade)
                    result.trades.append(open_trade)
                    open_trade = None
                elif candle["high"] >= open_trade.tp_price:
                    open_trade.exit_time  = df_entry.index[idx]
                    open_trade.exit_price = open_trade.tp_price
                    open_trade.result     = "WIN"
                    _finalize_trade(open_trade)
                    result.trades.append(open_trade)
                    open_trade = None
            elif open_trade.signal_type == "SELL":
                if candle["high"] >= open_trade.sl_price:
                    open_trade.exit_time  = df_entry.index[idx]
                    open_trade.exit_price = open_trade.sl_price
                    open_trade.result     = "LOSS"
                    _finalize_trade(open_trade)
                    result.trades.append(open_trade)
                    open_trade = None
                elif candle["low"] <= open_trade.tp_price:
                    open_trade.exit_time  = df_entry.index[idx]
                    open_trade.exit_price = open_trade.tp_price
                    open_trade.result     = "WIN"
                    _finalize_trade(open_trade)
                    result.trades.append(open_trade)
                    open_trade = None
            continue

        # Jangan entry terlalu sering — min 3 candle jeda (turun dari 5)
        if idx - last_entry_idx < 3:
            continue

        # Cek signal
        sig = detect_signal_at(df_entry, df_confirm, df_higher, idx, mode)
        if sig is None:
            continue

        # Buat trade baru
        trade = BacktestTrade(
            entry_time  = sig["time"],
            exit_time   = None,
            signal_type = sig["signal_type"],
            entry_price = sig["entry_price"],
            sl_price    = sig["sl_price"],
            tp_price    = sig["tp_price"],
            lot         = sig["lot"],
            grade       = sig["grade"],
            risk_pip    = sig["risk_pip"],
            mode        = mode,
        )
        open_trade    = trade
        last_entry_idx = idx

    # Tutup trade yang masih terbuka di akhir
    if open_trade is not None:
        open_trade.result = "OPEN"
        result.trades.append(open_trade)

    print(f"\n[DONE] Scan selesai. Total trade: {result.total_trades}")
    return result


def _finalize_trade(trade: BacktestTrade):
    """Hitung profit/loss setelah trade ditentukan WIN/LOSS."""
    pip_value = 0.01 * trade.lot * 100

    if trade.result == "WIN":
        if trade.signal_type == "BUY":
            pips = (trade.tp_price - trade.entry_price) * 10
        else:
            pips = (trade.entry_price - trade.tp_price) * 10
    else:  # LOSS
        if trade.signal_type == "BUY":
            pips = (trade.sl_price - trade.entry_price) * 10
        else:
            pips = (trade.entry_price - trade.sl_price) * 10

    trade.profit_pip = round(pips, 1)
    trade.profit_usd = round(pips * pip_value / 100, 2)
    trade.profit_idr = round(trade.profit_usd * 17800, 0)


# ── Report printer ───────────────────────────────────────────

def print_report(result: BacktestResult):
    """Print laporan backtest yang rapi."""
    print(f"\n{'═'*60}")
    print(f"  LAPORAN BACKTEST — {result.mode.upper()}")
    print(f"{'═'*60}")
    print(f"  Symbol      : {result.symbol}")
    print(f"  Periode     : {result.start_date} → {result.end_date}")
    print(f"  Timeframe   : {result.timeframe}")
    print(f"  Balance awal: ${result.initial_balance:.2f}")
    print(f"{'─'*60}")
    print(f"  Total trade : {result.total_trades}")
    print(f"  Win         : {len(result.wins)}  ({result.win_rate:.1f}%)")
    print(f"  Loss        : {len(result.losses)}")
    print(f"{'─'*60}")
    print(f"  Profit total: ${result.total_profit_usd:.2f}  "
          f"(Rp {result.total_profit_idr:,.0f})")
    print(f"  Balance akhir: ${result.final_balance:.2f}")
    print(f"  Profit factor: {result.profit_factor}")
    print(f"  Max drawdown : ${result.max_drawdown_usd:.2f}")
    print(f"  Expectancy  : ${result.expectancy_usd:.3f}/trade")
    print(f"{'─'*60}")
    print(f"  Avg win     : {result.avg_win_pip:.1f} pip")
    print(f"  Avg loss    : {result.avg_loss_pip:.1f} pip")

    # Grade breakdown
    grades = {}
    for t in result.closed_trades:
        grades[t.grade] = grades.get(t.grade, {"total": 0, "win": 0})
        grades[t.grade]["total"] += 1
        if t.result == "WIN":
            grades[t.grade]["win"] += 1

    if grades:
        print(f"{'─'*60}")
        print(f"  Win rate per grade:")
        for g in ["A+", "A", "B"]:
            if g in grades:
                wr = grades[g]["win"] / grades[g]["total"] * 100
                print(f"    {g:3} : {grades[g]['win']}/{grades[g]['total']} "
                      f"({wr:.0f}% WR)")

    # 5 trade terakhir
    if result.closed_trades:
        print(f"{'─'*60}")
        print(f"  5 trade terakhir:")
        for t in result.closed_trades[-5:]:
            icon = "✓" if t.result == "WIN" else "✗"
            print(f"  {icon} {t.entry_time.strftime('%m-%d %H:%M')} "
                  f"{t.signal_type:4} {t.grade:2} "
                  f"entry={t.entry_price:.2f} "
                  f"pip={t.profit_pip:+.1f} "
                  f"${t.profit_usd:+.2f}")

    print(f"{'═'*60}")

    # Verdict
    if result.win_rate >= 60 and result.profit_factor >= 1.5:
        print(f"  VERDICT: LAYAK LIVE ✓")
        print(f"  Win rate {result.win_rate:.0f}% + PF {result.profit_factor} sudah baik.")
    elif result.profit_factor >= 1.2:
        print(f"  VERDICT: PERLU OPTIMASI")
        print(f"  Profitable tapi belum konsisten.")
    else:
        print(f"  VERDICT: JANGAN LIVE dulu")
        print(f"  Strategi perlu diperbaiki sebelum live.")
    print(f"{'═'*60}")


# ── Entry point ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  XAUUSD EA — Backtest Framework")
    print("=" * 60)

    if not connect():
        print("[ERROR] Koneksi MT5 gagal")
        exit()

    # Jalankan backtest untuk setiap mode
    for mode in ["scalp", "intraday", "swing"]:
        try:
            result = run_backtest(mode=mode, days=90, initial_balance=50.0)
            print_report(result)
        except Exception as e:
            print(f"[ERROR] Backtest {mode} gagal: {e}")
            import traceback
            traceback.print_exc()

    disconnect()