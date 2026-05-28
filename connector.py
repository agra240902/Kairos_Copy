# connector.py — koneksi MT5, output ke ea_state bukan print

import MetaTrader5 as mt5
from config import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, SYMBOL


def connect() -> bool:
    try:
        import ea_state as state
        _log = state.add_log
    except ImportError:
        _log = lambda msg, lvl="INFO": print(f"[{lvl}] {msg}")

    if not mt5.initialize():
        _log(f"MT5 initialize gagal: {mt5.last_error()}", "ERROR")
        return False

    if not mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        _log(f"MT5 login gagal: {mt5.last_error()}", "ERROR")
        mt5.shutdown()
        return False

    info = mt5.account_info()
    _log(f"Terhubung ke MT5 — Akun {info.login} ({info.name})", "INFO")
    _log(f"Balance: ${info.balance:.2f} | Server: {info.server}", "INFO")
    return True


def disconnect():
    mt5.shutdown()
    try:
        import ea_state as state
        state.add_log("Koneksi MT5 ditutup", "INFO")
    except ImportError:
        pass


def check_symbol() -> bool:
    try:
        import ea_state as state
        _log = state.add_log
    except ImportError:
        _log = lambda msg, lvl="INFO": print(f"[{lvl}] {msg}")

    info = mt5.symbol_info(SYMBOL)
    if info is None:
        _log(f"Symbol {SYMBOL} tidak ditemukan", "ERROR")
        return False

    if not info.visible:
        if not mt5.symbol_select(SYMBOL, True):
            _log(f"Tidak bisa aktifkan {SYMBOL}", "ERROR")
            return False

    _log(f"Symbol {SYMBOL} aktif | Spread: {info.spread/10:.1f} pip", "INFO")
    return True


def get_account_info() -> dict:
    info = mt5.account_info()
    if info is None:
        return {}
    return {
        "balance":      info.balance,
        "equity":       info.equity,
        "margin":       info.margin,
        "free_margin":  info.margin_free,
        "profit":       info.profit,
        "currency":     info.currency,
    }


def is_connected() -> bool:
    return mt5.terminal_info() is not None