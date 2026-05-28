# trade_manager.py — BE trigger dan trailing stop otomatis

import MetaTrader5 as mt5
import time
import threading
from datetime import datetime
from config import SYMBOL, MAGIC_NUMBER

# ── Konfigurasi ─────────────────────────────────────────────
CHECK_INTERVAL = 5  # cek setiap 5 detik

# Normal mode
NORMAL_BE_TRIGGER    = 10.0  # pindah BE setelah profit 10 point
NORMAL_TP_POINT      = 12.0  # TP di 12 point
NORMAL_TRAIL_STEP    = 2.0   # trailing stop setiap 2 point

# Extreme scalp mode (SL sempit ≤ 5 point)
SCALP_BE_TRIGGER     = 1.0   # pindah BE setelah profit 1 point
SCALP_TP_POINT       = 5.0   # TP di 5 point
SCALP_TRAIL_STEP     = 1.0   # trailing stop setiap 1 point

# Threshold untuk tentukan mode (berdasarkan SL awal)
SCALP_SL_THRESHOLD   = 8.0   # kalau SL ≤ 8 point → extreme scalp mode


def _get_ea_positions() -> list:
    """Ambil semua posisi EA yang terbuka."""
    positions = mt5.positions_get(symbol=SYMBOL)
    if positions is None:
        return []
    return [p for p in positions if p.magic == MAGIC_NUMBER]


def _modify_position(ticket: int, sl: float, tp: float) -> bool:
    """Modify SL dan TP posisi."""
    request = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "symbol":   SYMBOL,
        "position": ticket,
        "sl":       round(sl, 3),
        "tp":       round(tp, 3),
    }
    result = mt5.order_send(request)
    return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE


def _manage_position(position) -> str:
    """
    Kelola satu posisi — cek dan update BE/trailing stop.
    Returns: pesan log atau "" kalau tidak ada perubahan
    """
    ticket     = position.ticket
    open_price = position.price_open
    current_sl = position.sl
    current_tp = position.tp
    pos_type   = position.type  # 0=BUY, 1=SELL

    # Harga current
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return ""

    current_price = tick.bid if pos_type == 0 else tick.ask

    # Hitung profit dalam point
    if pos_type == 0:  # BUY
        profit_point = current_price - open_price
    else:  # SELL
        profit_point = open_price - current_price

    # Tentukan mode berdasarkan SL awal
    if pos_type == 0:  # BUY
        initial_sl_dist = open_price - current_sl
    else:  # SELL
        initial_sl_dist = current_sl - open_price

    is_scalp = initial_sl_dist <= SCALP_SL_THRESHOLD

    be_trigger  = SCALP_BE_TRIGGER  if is_scalp else NORMAL_BE_TRIGGER
    tp_point    = SCALP_TP_POINT    if is_scalp else NORMAL_TP_POINT
    trail_step  = SCALP_TRAIL_STEP  if is_scalp else NORMAL_TRAIL_STEP
    mode_label  = "scalp" if is_scalp else "normal"

    new_sl = current_sl
    new_tp = current_tp

    # ── BE trigger ─────────────────────────────────────────
    if profit_point >= be_trigger:
        if pos_type == 0:  # BUY — SL naik ke open price
            be_price = open_price + 0.1  # sedikit di atas entry (cover spread)
            if current_sl < be_price:
                new_sl = be_price
        else:  # SELL — SL turun ke open price
            be_price = open_price - 0.1
            if current_sl > be_price:
                new_sl = be_price

    # ── Trailing stop ───────────────────────────────────────
    if profit_point >= be_trigger + trail_step:
        # Hitung SL trailing yang ideal
        steps_done = int((profit_point - be_trigger) / trail_step)

        if pos_type == 0:  # BUY — trailing SL naik
            ideal_trail_sl = open_price + (steps_done * trail_step)
            if ideal_trail_sl > new_sl:
                new_sl = ideal_trail_sl
        else:  # SELL — trailing SL turun
            ideal_trail_sl = open_price - (steps_done * trail_step)
            if ideal_trail_sl < new_sl:
                new_sl = ideal_trail_sl

    # ── Auto TP ─────────────────────────────────────────────
    # Set TP kalau belum ada atau terlalu jauh
    if pos_type == 0:
        ideal_tp = open_price + tp_point
        if current_tp == 0 or abs(current_tp - ideal_tp) > 1.0:
            new_tp = ideal_tp
    else:
        ideal_tp = open_price - tp_point
        if current_tp == 0 or abs(current_tp - ideal_tp) > 1.0:
            new_tp = ideal_tp

    # ── Apply kalau ada perubahan ───────────────────────────
    sl_changed = abs(new_sl - current_sl) > 0.05
    tp_changed = abs(new_tp - current_tp) > 0.05

    if sl_changed or tp_changed:
        success = _modify_position(ticket, new_sl, new_tp)
        if success:
            msg = f"#{ticket} [{mode_label}] profit={profit_point:.1f}pt"
            if sl_changed:
                action = "BE" if abs(new_sl - open_price) < 0.5 else "TRAIL"
                msg += f" | {action} SL→{new_sl:.2f}"
            if tp_changed:
                msg += f" | TP→{new_tp:.2f}"
            return msg

    return ""


def _trade_manager_loop():
    """Loop utama trade manager — jalan di background thread."""
    import ea_state as state

    state.add_log("Trade Manager dimulai (BE + Trailing Stop aktif)", "INFO")

    while True:
        try:
            positions = _get_ea_positions()
            for pos in positions:
                msg = _manage_position(pos)
                if msg:
                    state.add_log(msg, "TRADE")
        except Exception as e:
            try:
                import ea_state as state
                state.add_log(f"Trade Manager error: {e}", "ERROR")
            except Exception:
                pass

        time.sleep(CHECK_INTERVAL)


# ── Public API ──────────────────────────────────────────────
_tm_thread: threading.Thread = None


def start_trade_manager():
    global _tm_thread
    if _tm_thread and _tm_thread.is_alive():
        return
    _tm_thread = threading.Thread(
        target=_trade_manager_loop,
        daemon=True,
        name="TradeManager"
    )
    _tm_thread.start()