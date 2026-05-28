# data_feed.py — ambil data OHLCV dari MT5

import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
from config import SYMBOL

# Mapping nama timeframe ke konstanta MT5
TF_MAP = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
    "W1":  mt5.TIMEFRAME_W1,
}


def get_candles(timeframe: str, n: int = 200) -> pd.DataFrame:
    """
    Ambil n candle terakhir untuk timeframe tertentu.

    Args:
        timeframe : "M5", "M15", "H1", "H4", "D1", dll
        n         : jumlah candle yang diambil (default 200)

    Returns:
        DataFrame dengan kolom: time, open, high, low, close, volume
    """
    tf = TF_MAP.get(timeframe)
    if tf is None:
        raise ValueError(f"Timeframe '{timeframe}' tidak valid. Pilihan: {list(TF_MAP.keys())}")

    rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, n)
    if rates is None or len(rates) == 0:
        print(f"[ERROR] Gagal ambil data {timeframe}: {mt5.last_error()}")
        return pd.DataFrame()

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df[["time", "open", "high", "low", "close", "tick_volume"]].copy()
    df.rename(columns={"tick_volume": "volume"}, inplace=True)
    df.set_index("time", inplace=True)
    return df


def get_current_price() -> dict:
    """Ambil harga bid/ask terkini."""
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return {}
    return {
        "bid":  tick.bid,
        "ask":  tick.ask,
        "mid":  (tick.bid + tick.ask) / 2,
        "time": datetime.fromtimestamp(tick.time),
    }


def get_multi_timeframe(timeframes: list = None) -> dict:
    """
    Ambil data untuk beberapa timeframe sekaligus.
    Dipakai oleh mode detector dan SNR detector.

    Returns:
        dict: {"M15": DataFrame, "H1": DataFrame, "H4": DataFrame, ...}
    """
    if timeframes is None:
        timeframes = ["M5", "M15", "H1", "H4", "D1"]

    result = {}
    for tf in timeframes:
        df = get_candles(tf)
        if not df.empty:
            result[tf] = df
        else:
            print(f"[WARN] Data {tf} kosong, skip.")
    return result


def get_spread_pip() -> float:
    """Ambil spread saat ini dalam pip."""
    info = mt5.symbol_info(SYMBOL)
    if info is None:
        return 0.0
    return info.spread * info.point * 10  # konversi ke pip


def print_latest_candle(timeframe: str):
    """Helper untuk debug — print candle terakhir."""
    df = get_candles(timeframe, n=1)
    if df.empty:
        print(f"[ERROR] Tidak ada data {timeframe}")
        return
    c = df.iloc[-1]
    print(f"[{timeframe}] {df.index[-1]} | O:{c.open:.2f} H:{c.high:.2f} L:{c.low:.2f} C:{c.close:.2f} V:{c.volume}")