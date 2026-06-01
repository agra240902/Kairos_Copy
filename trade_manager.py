# trade_manager.py — BE trigger dan trailing stop otomatis

import MetaTrader5 as mt5
import time
import threading
from config import SYMBOL, MAGIC_NUMBER

CHECK_INTERVAL     = 5      # cek setiap 5 detik
TRAIL_STEP_NORMAL  = 3.0    # trailing setiap 3 point (normal)
TRAIL_STEP_SCALP   = 1.0    # trailing setiap 1 point (scalp)
SCALP_SL_THRESHOLD = 8.0    # SL ≤ 8 point → scalp mode
BE_PCT             = 0.5    # BE di 50% dari jarak entry ke TP


def _get_ea_positions() -> list:
    positions = mt5.positions_get(symbol=SYMBOL)
    if positions is None:
        return []
    return [p for p in positions if p.magic == MAGIC_NUMBER]


def _modify_sl(ticket: int, sl: float, tp: float) -> bool:
    result = mt5.order_send({
        "action":   mt5.TRADE_ACTION_SLTP,
        "symbol":   SYMBOL,
        "position": ticket,
        "sl":       round(sl, 3),
        "tp":       round(tp, 3),
    })
    return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE


def _manage_position(position) -> str:
    ticket     = position.ticket
    open_price = position.price_open
    current_sl = position.sl
    current_tp = position.tp
    pos_type   = position.type  # 0=BUY, 1=SELL

    # Kalau tidak ada TP dari signal engine, skip
    if current_tp == 0:
        return ""

    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return ""

    current_price = tick.bid if pos_type == 0 else tick.ask

    # Profit dalam point
    if pos_type == 0:
        profit_point = current_price - open_price
        tp_dist      = current_tp - open_price      # jarak entry ke TP
    else:
        profit_point = open_price - current_price
        tp_dist      = open_price - current_tp      # jarak entry ke TP

    if tp_dist <= 0:
        return ""

    # Tentukan mode berdasarkan SL awal
    if pos_type == 0:
        sl_dist = open_price - current_sl
    else:
        sl_dist = current_sl - open_price

    is_scalp   = sl_dist <= SCALP_SL_THRESHOLD
    trail_step = TRAIL_STEP_SCALP if is_scalp else TRAIL_STEP_NORMAL
    mode_label = "scalp" if is_scalp else "normal"

    # BE trigger = 50% dari jarak TP
    be_trigger = tp_dist * BE_PCT

    new_sl = current_sl

    # ── BE trigger ──────────────────────────────────────────
    if profit_point >= be_trigger:
        if pos_type == 0:
            be_price = open_price + 0.1
            if current_sl < be_price:
                new_sl = be_price
        else:
            be_price = open_price - 0.1
            if current_sl > be_price:
                new_sl = be_price

    # ── Trailing stop ────────────────────────────────────────
    if profit_point >= be_trigger + trail_step:
        steps_done = int((profit_point - be_trigger) / trail_step)
        if pos_type == 0:
            ideal_trail = open_price + (steps_done * trail_step)
            if ideal_trail > new_sl:
                new_sl = ideal_trail
        else:
            ideal_trail = open_price - (steps_done * trail_step)
            if ideal_trail < new_sl:
                new_sl = ideal_trail

    # ── Apply kalau ada perubahan ────────────────────────────
    if abs(new_sl - current_sl) > 0.05:
        success = _modify_sl(ticket, new_sl, current_tp)
        if success:
            action = "BE" if abs(new_sl - open_price) < 0.5 else "TRAIL"
            return (f"#{ticket} [{mode_label}] profit={profit_point:.1f}pt "
                    f"BE@{be_trigger:.1f}pt | {action} SL→{new_sl:.2f}")

    return ""


def _trade_manager_loop():
    import ea_state as state
    state.add_log("Trade Manager aktif — BE 50% TP, Trailing 3pt", "INFO")

    while True:
        try:
            for pos in _get_ea_positions():
                msg = _manage_position(pos)
                if msg:
                    state.add_log(msg, "TRADE")
        except Exception as e:
            try:
                import ea_state as s
                s.add_log(f"Trade Manager error: {e}", "ERROR")
            except Exception:
                pass
        time.sleep(CHECK_INTERVAL)


_tm_thread = None


def start_trade_manager():
    global _tm_thread
    if _tm_thread and _tm_thread.is_alive():
        return
    _tm_thread = threading.Thread(
        target=_trade_manager_loop, daemon=True, name="TradeManager"
    )
    _tm_thread.start()