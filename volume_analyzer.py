# volume_analyzer.py — analisis volume untuk konfirmasi entry

import pandas as pd
import numpy as np


def is_volume_spike(df: pd.DataFrame, lookback: int = 20,
                    threshold: float = 1.5) -> bool:
    """
    Deteksi apakah candle terakhir punya volume di atas rata-rata.

    Args:
        lookback  : berapa candle untuk hitung rata-rata
        threshold : minimal berapa kali rata-rata untuk dianggap spike (1.5 = 150%)

    Returns:
        True kalau volume candle terakhir > threshold × rata-rata
    """
    if len(df) < lookback + 1:
        return False

    recent_volumes = df["volume"].tail(lookback + 1)
    avg_volume     = recent_volumes.iloc[:-1].mean()  # exclude candle terakhir
    last_volume    = recent_volumes.iloc[-1]

    if avg_volume == 0:
        return False

    return last_volume >= avg_volume * threshold


def get_volume_strength(df: pd.DataFrame, lookback: int = 20) -> dict:
    """
    Detail kekuatan volume candle terakhir.

    Returns:
        dict dengan ratio, status, dan klasifikasi
    """
    if len(df) < lookback + 1:
        return {"ratio": 0, "status": "insufficient_data", "is_spike": False}

    recent_volumes = df["volume"].tail(lookback + 1)
    avg_volume     = recent_volumes.iloc[:-1].mean()
    last_volume    = recent_volumes.iloc[-1]

    if avg_volume == 0:
        return {"ratio": 0, "status": "no_data", "is_spike": False}

    ratio = last_volume / avg_volume

    if ratio >= 2.0:
        status = "very_strong"
    elif ratio >= 1.5:
        status = "strong"
    elif ratio >= 1.0:
        status = "normal"
    else:
        status = "weak"

    return {
        "ratio":       round(ratio, 2),
        "status":      status,
        "is_spike":    ratio >= 1.5,
        "last_volume": int(last_volume),
        "avg_volume":  int(avg_volume),
    }


def detect_rejection_candle(df: pd.DataFrame, direction: str) -> bool:
    """
    Deteksi candle rejection (pin bar / hammer / shooting star)
    sebagai konfirmasi entry.

    Args:
        direction: "BUY" → cari hammer/bullish rejection
                   "SELL" → cari shooting star/bearish rejection

    Returns:
        True kalau candle terakhir adalah rejection yang valid
    """
    if len(df) < 2:
        return False

    last = df.iloc[-1]
    open_, high, low, close = last["open"], last["high"], last["low"], last["close"]

    body        = abs(close - open_)
    upper_wick  = high - max(open_, close)
    lower_wick  = min(open_, close) - low
    total_range = high - low

    if total_range == 0:
        return False

    if direction == "BUY":
        # Hammer / bullish pin: lower wick panjang, body kecil di atas
        return (
            lower_wick >= 2 * body and       # wick bawah min 2x body
            upper_wick <= body and           # wick atas pendek
            lower_wick / total_range >= 0.6  # wick bawah ≥ 60% total range
        )

    elif direction == "SELL":
        # Shooting star / bearish pin: upper wick panjang, body kecil di bawah
        return (
            upper_wick >= 2 * body and
            lower_wick <= body and
            upper_wick / total_range >= 0.6
        )

    return False


def detect_engulfing(df: pd.DataFrame, direction: str) -> bool:
    """
    Deteksi bullish/bearish engulfing pattern.
    Candle terakhir "menelan" candle sebelumnya.
    """
    if len(df) < 2:
        return False

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    if direction == "BUY":
        # Bullish engulfing: prev bearish, curr bullish & lebih besar
        prev_bearish = prev["close"] < prev["open"]
        curr_bullish = curr["close"] > curr["open"]
        engulfs      = (curr["open"] <= prev["close"] and
                        curr["close"] >= prev["open"])
        return prev_bearish and curr_bullish and engulfs

    elif direction == "SELL":
        # Bearish engulfing
        prev_bullish = prev["close"] > prev["open"]
        curr_bearish = curr["close"] < curr["open"]
        engulfs      = (curr["open"] >= prev["close"] and
                        curr["close"] <= prev["open"])
        return prev_bullish and curr_bearish and engulfs

    return False


def get_price_action_confirmation(df: pd.DataFrame, direction: str) -> dict:
    """
    Cek semua price action pattern sebagai konfirmasi.

    Returns:
        dict dengan flag tiap pattern dan kesimpulan
    """
    rejection = detect_rejection_candle(df, direction)
    engulfing = detect_engulfing(df, direction)

    return {
        "rejection_candle": rejection,
        "engulfing":        engulfing,
        "confirmed":        rejection or engulfing,
        "patterns_found":   sum([rejection, engulfing]),
    }