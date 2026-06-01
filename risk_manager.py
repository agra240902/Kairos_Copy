# risk_manager.py — proteksi modal sebelum setiap eksekusi

import MetaTrader5 as mt5
from datetime import datetime, date
from currency import get_usd_idr
from config import (
    SYMBOL, MAGIC_NUMBER,
    MAX_DAILY_LOSS_IDR, MAX_OPEN_POSITIONS,
    RISK_PER_TRADE_PCT, USD_IDR
)

# ── Maksimal loss per hari dalam USD (hardcoded safety) ──────
MAX_DAILY_LOSS_USD = 2.0   # $2/hari — ~18% dari balance $11 cent


def get_open_positions() -> list:
    """Semua posisi terbuka — EA maupun manual, untuk ditampilkan di dashboard."""
    positions = mt5.positions_get(symbol=SYMBOL)
    if positions is None:
        return []
    return list(positions)


def get_ea_positions() -> list:
    """Hanya posisi milik EA (untuk risk guard max open positions)."""
    positions = mt5.positions_get(symbol=SYMBOL)
    if positions is None:
        return []
    return [p for p in positions if p.magic == MAGIC_NUMBER]


def count_open_positions() -> int:
    """Hitung posisi EA yang masih terbuka."""
    return len(get_ea_positions())


def get_daily_pnl_usd() -> float:
    """Total PnL hari ini — semua deal termasuk manual close."""
    today = datetime.combine(date.today(), datetime.min.time())
    deals = mt5.history_deals_get(today, datetime.now())
    if deals is None:
        return 0.0
    # Hitung semua deal di symbol ini, termasuk manual
    symbol_deals = [d for d in deals
                    if d.symbol == SYMBOL and d.entry == 1]  # entry=1 = close deal
    return sum(d.profit for d in symbol_deals)


def get_daily_pnl_idr() -> float:
    return get_daily_pnl_usd() * get_usd_idr()


def get_daily_stats() -> dict:
    """
    Statistik trade hari ini — wins, losses, total dari semua deal
    termasuk close manual maupun kena TP/SL otomatis.
    """
    today = datetime.combine(date.today(), datetime.min.time())
    deals = mt5.history_deals_get(today, datetime.now())
    if deals is None:
        return {"wins": 0, "losses": 0, "total": 0, "pnl_usd": 0.0}

    close_deals = [d for d in deals
                   if d.symbol == SYMBOL and d.entry == 1]

    wins   = sum(1 for d in close_deals if d.profit > 0)
    losses = sum(1 for d in close_deals if d.profit < 0)
    pnl    = sum(d.profit for d in close_deals)

    return {
        "wins":    wins,
        "losses":  losses,
        "total":   wins + losses,
        "pnl_usd": round(pnl, 2),
    }


def get_current_spread_pip() -> float:
    info = mt5.symbol_info(SYMBOL)
    if info is None:
        return 999.0
    return info.spread / 10.0


def check_all_guards(sl_pip: float, max_spread_pip: float = 35.0) -> dict:
    """
    Cek semua perlindungan sebelum entry.
    """
    guards = {}

    # 1. Max open positions — hanya hitung posisi EA, bukan manual
    open_count = count_open_positions()
    # Turunkan ke 1 — EA tidak boleh buka 2 posisi sekaligus
    max_pos = 1
    guards["open_positions"] = {
        "value":  open_count,
        "limit":  max_pos,
        "passed": open_count < max_pos,
        "msg":    f"{open_count}/{max_pos} posisi EA terbuka",
    }

    # 2. Daily loss limit — bisa di-override manual
    daily_pnl_usd = get_daily_pnl_usd()
    try:
        import ea_state as st
        override = st.get_state().override_daily_loss
    except Exception:
        override = False

    guards["daily_loss"] = {
        "value":  daily_pnl_usd,
        "limit":  -MAX_DAILY_LOSS_USD,
        "passed": override or (daily_pnl_usd > -MAX_DAILY_LOSS_USD),
        "msg":    f"PnL hari ini: ${daily_pnl_usd:.2f} (limit: -${MAX_DAILY_LOSS_USD})"
                  + (" [OVERRIDE]" if override else ""),
    }

    # 3. Spread guard
    spread = get_current_spread_pip()
    guards["spread"] = {
        "value":  spread,
        "limit":  max_spread_pip,
        "passed": spread <= max_spread_pip,
        "msg":    f"Spread: {spread:.1f} pip (max: {max_spread_pip})",
    }

    # 4. SL minimum 5 point
    guards["sl_size"] = {
        "value":  sl_pip,
        "limit":  5.0,
        "passed": sl_pip >= 5.0,
        "msg":    f"SL: {sl_pip:.1f} point (min: 5) = ${sl_pip * 0.50:.2f}",
    }

    all_passed = all(g["passed"] for g in guards.values())
    guards["_all_passed"] = all_passed
    return guards


def print_guards(guards: dict):
    print("\n  Risk Guards:")
    for key, g in guards.items():
        if key.startswith("_"):
            continue
        icon = "✓" if g["passed"] else "✗"
        print(f"  {icon} {g['msg']}")
    print(f"  → {'LANJUT' if guards['_all_passed'] else 'BLOCKED'}")