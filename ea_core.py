# ea_core.py — EA engine background thread

import time
import threading
from datetime import datetime

from connector import connect, disconnect, check_symbol, is_connected, get_account_info
from data_feed import get_current_price, get_multi_timeframe
from signal_engine import analyze
from risk_manager import (check_all_guards, get_daily_pnl_idr,
                          get_daily_pnl_usd, get_open_positions,
                          get_ea_positions, get_current_spread_pip,
                          get_daily_stats)
from executor import place_order
from session_filter import session_status
from trade_manager import start_trade_manager
import ea_state as state
from currency import get_usd_idr
from config import SYMBOL

SCAN_INTERVAL = 30
MODES         = ["scalp", "intraday", "swing"]

_ea_thread: threading.Thread = None


def _build_signal_dict(sig) -> dict:
    return {
        "action":      sig.action,
        "signal_type": sig.signal_type,
        "grade":       sig.grade,
        "entry":       sig.entry_price,
        "sl":          sig.sl_price,
        "tp":          sig.tp_price,
        "lot":         sig.lot,
        "risk_pip":    round(sig.risk_pip, 1),
        "reward_pip":  round(sig.reward_pip, 1),
        "risk_usd":    round(sig.risk_usd, 2),
        "reasons":     sig.reasons,
        "rejections":  sig.rejections,
        "session":     sig.session,
        "timestamp":   datetime.now().strftime("%H:%M:%S"),
    }


def _update_positions():
    """Update posisi di dashboard — tampilkan semua termasuk manual."""
    positions = get_open_positions()  # semua posisi
    pos_list  = []
    for p in positions:
        pos_list.append({
            "ticket":     p.ticket,
            "type":       "BUY" if p.type == 0 else "SELL",
            "volume":     p.volume,
            "open_price": p.price_open,
            "sl":         p.sl,
            "tp":         p.tp,
            "profit_usd": round(p.profit, 2),
            "profit_idr": round(p.profit * get_usd_idr(), 0),
            "open_time":  datetime.fromtimestamp(p.time).strftime("%H:%M:%S"),
            "is_ea":      p.magic == 20250521,  # tandai mana yang dari EA
        })
    state.update_state(open_positions=pos_list, open_count=len(get_ea_positions()))


def _scan():
    """Satu siklus scan penuh."""
    if not is_connected():
        state.add_log("Koneksi MT5 putus, reconnect...", "WARN")
        if not connect():
            state.update_state(last_error="Reconnect gagal")
            return
        state.add_log("Reconnect berhasil", "INFO")

    # Update account
    acc = get_account_info()
    if acc:
        from currency import get_usd_idr, get_rate_info
        rate_info = get_rate_info()
        state.update_state(
            balance_usd = acc["balance"],
            equity_usd  = acc["equity"],
            usd_idr     = rate_info["rate"],
        )

    # Update market info + spread
    price_info = get_current_price()
    if not price_info:
        return

    spread_pip = get_current_spread_pip()
    sess       = session_status()
    stats      = get_daily_stats()

    state.update_state(
        current_price = price_info["mid"],
        bid           = price_info["bid"],
        ask           = price_info["ask"],
        spread_pip    = round(spread_pip, 1),
        session       = sess["session"],
        in_killzone   = sess["in_killzone"],
        daily_pnl_usd = stats["pnl_usd"],
        daily_pnl_idr = stats["pnl_usd"] * get_usd_idr(),
        wins_today    = stats["wins"],
        losses_today  = stats["losses"],
        last_scan     = datetime.now().strftime("%H:%M:%S"),
    )

    # Update posisi terbuka
    _update_positions()

    # Ambil data semua timeframe
    mtf           = get_multi_timeframe(["M5", "M15", "H1", "H4", "D1"])
    current_price = price_info["mid"]

    # Tentukan mode dari state (bisa dioverride dari dashboard)
    s = state.get_state()
    if s.mode == "auto":
        modes = MODES
    else:
        modes = [s.mode]

    signals  = {}
    all_watchlist = []

    for mode in modes:
        sig     = analyze(mtf, current_price, mode=mode)
        signals[mode] = _build_signal_dict(sig)

        # Kumpulkan watchlist dari sinyal WAIT
        if sig.action == "WAIT" and sig.rejections:
            msg = sig.rejections[0] if sig.rejections else ""
            # Parse jumlah setup dari pesan
            import re
            m = re.search(r'(\d+) setup', msg)
            count = int(m.group(1)) if m else 0
            if count > 0:
                all_watchlist.append({
                    "mode":    mode,
                    "msg":     msg,
                    "count":   count,
                })

        if sig.action == "ENTRY" and not s.paused:
            state.add_log(
                f"[{mode.upper()}] {sig.signal_type} grade {sig.grade} "
                f"@ {current_price:.2f}", "SIGNAL"
            )

            guards = check_all_guards(sl_pip=sig.risk_pip)
            if guards["_all_passed"]:
                result = place_order(sig)
                if result["success"]:
                    state.add_log(
                        f"ORDER #{result['ticket']} {result['signal']} "
                        f"lot {result['volume']} @ {result['price']:.2f}", "TRADE"
                    )
                    state.add_trade({
                        "ticket":     result["ticket"],
                        "type":       result["signal"],
                        "lot":        result["volume"],
                        "price":      result["price"],
                        "sl":         result["sl"],
                        "tp":         result["tp"],
                        "grade":      result["grade"],
                        "mode":       result["mode"],
                        "time":       result["timestamp"],
                        "profit_idr": None,
                    })
                    # Cukup satu entry per scan
                    break
                else:
                    state.add_log(f"Order gagal: {result['msg']}", "ERROR")
            else:
                blocked = [k for k, v in guards.items()
                           if not k.startswith("_") and not v["passed"]]
                state.add_log(f"Diblok: {', '.join(blocked)}", "WARN")

        elif sig.action == "WAIT":
            pass  # tidak perlu spam log tiap 30 detik

    state.update_state(last_signals=signals, watchlist=all_watchlist)


def ea_loop():
    """Loop utama — jalan di background thread."""
    state.update_state(
        running      = True,
        paused       = False,
        uptime_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    state.add_log("EA dimulai", "INFO")

    if not connect():
        state.add_log("Koneksi MT5 gagal", "ERROR")
        state.update_state(running=False)
        return

    if not check_symbol():
        state.add_log("Symbol tidak valid", "ERROR")
        state.update_state(running=False)
        disconnect()
        return

    # Start trade manager (BE + trailing stop)
    start_trade_manager()
    state.add_log("Trade Manager aktif (BE + Trailing Stop)", "INFO")

    # Scan pertama langsung tanpa nunggu interval
    try:
        _scan()
    except Exception as e:
        state.add_log(f"Error scan awal: {e}", "ERROR")

    while state.get_state().running:
        time.sleep(SCAN_INTERVAL)
        if not state.get_state().running:
            break
        if not state.get_state().paused:
            s = state.get_state()
            state.update_state(scan_count=s.scan_count + 1)
            try:
                _scan()
            except Exception as e:
                state.add_log(f"Error scan: {e}", "ERROR")
                state.update_state(last_error=str(e))

    disconnect()
    state.add_log("EA dihentikan", "INFO")
    state.update_state(running=False)


# ── Public API ─────────────────────────────────────────────

def start_ea():
    global _ea_thread
    if state.get_state().running:
        return False, "EA sudah berjalan"
    _ea_thread = threading.Thread(target=ea_loop, daemon=True, name="EA-Core")
    _ea_thread.start()
    return True, "EA dimulai"


def stop_ea():
    state.update_state(running=False)
    state.add_log("EA dihentikan oleh user", "WARN")
    return True, "EA dihentikan"


def pause_ea():
    state.update_state(paused=True)
    state.add_log("EA di-pause", "WARN")
    return True, "EA di-pause"


def resume_ea():
    state.update_state(paused=False)
    state.add_log("EA di-resume", "INFO")
    return True, "EA di-resume"


def set_mode(mode: str):
    valid = ["auto", "scalp", "intraday", "swing"]
    if mode not in valid:
        return False, f"Mode tidak valid. Pilihan: {valid}"
    state.update_state(mode=mode)
    state.add_log(f"Mode diubah ke: {mode.upper()}", "INFO")
    return True, f"Mode: {mode}"