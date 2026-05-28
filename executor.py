# executor.py — eksekusi order ke MT5

import MetaTrader5 as mt5
from datetime import datetime
from config import SYMBOL, MAGIC_NUMBER
from signal_engine import TradeSignal


def place_order(signal: TradeSignal, comment: str = "EA-XAUUSD") -> dict:
    """
    Place market order berdasarkan TradeSignal.

    Returns:
        dict dengan status, ticket, dan detail hasil
    """
    if not signal.is_actionable():
        return {"success": False, "msg": "Signal tidak actionable"}

    # Tentukan order type
    if signal.signal_type == "BUY":
        order_type = mt5.ORDER_TYPE_BUY
        price      = mt5.symbol_info_tick(SYMBOL).ask
    elif signal.signal_type == "SELL":
        order_type = mt5.ORDER_TYPE_SELL
        price      = mt5.symbol_info_tick(SYMBOL).bid
    else:
        return {"success": False, "msg": f"Signal type tidak dikenal: {signal.signal_type}"}

    # Validasi SL dan TP tidak nol
    if signal.sl_price == 0 or signal.tp_price == 0:
        return {"success": False, "msg": "SL atau TP tidak valid (0)"}

    request = {
        "action":    mt5.TRADE_ACTION_DEAL,
        "symbol":    SYMBOL,
        "volume":    signal.lot,
        "type":      order_type,
        "price":     price,
        "sl":        round(signal.sl_price, 2),
        "tp":        round(signal.tp_price, 2),
        "deviation": 20,          # max slippage 20 pip
        "magic":     MAGIC_NUMBER,
        "comment":   f"{comment}-{signal.grade}-{signal.mode[:3]}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)

    if result is None:
        error = mt5.last_error()
        return {
            "success": False,
            "msg":     f"order_send gagal: {error}",
            "request": request,
        }

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return {
            "success":  False,
            "retcode":  result.retcode,
            "msg":      f"Order ditolak: {result.comment}",
            "request":  request,
            "result":   result._asdict(),
        }

    return {
        "success":   True,
        "ticket":    result.order,
        "volume":    result.volume,
        "price":     result.price,
        "sl":        request["sl"],
        "tp":        request["tp"],
        "signal":    signal.signal_type,
        "grade":     signal.grade,
        "mode":      signal.mode,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "msg":       "Order berhasil",
    }


def close_position(ticket: int) -> dict:
    """Tutup posisi berdasarkan ticket number."""
    position = None
    positions = mt5.positions_get(symbol=SYMBOL)
    if positions:
        for p in positions:
            if p.ticket == ticket:
                position = p
                break

    if position is None:
        return {"success": False, "msg": f"Posisi {ticket} tidak ditemukan"}

    if position.type == mt5.ORDER_TYPE_BUY:
        order_type = mt5.ORDER_TYPE_SELL
        price      = mt5.symbol_info_tick(SYMBOL).bid
    else:
        order_type = mt5.ORDER_TYPE_BUY
        price      = mt5.symbol_info_tick(SYMBOL).ask

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       SYMBOL,
        "volume":       position.volume,
        "type":         order_type,
        "position":     ticket,
        "price":        price,
        "deviation":    20,
        "magic":        MAGIC_NUMBER,
        "comment":      "EA-close",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        return {
            "success": False,
            "msg":     f"Gagal close: {mt5.last_error()}",
        }

    return {
        "success": True,
        "ticket":  ticket,
        "msg":     "Posisi berhasil ditutup",
    }


def get_position_info(ticket: int) -> dict:
    """Ambil info lengkap sebuah posisi."""
    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        return {}

    for p in positions:
        if p.ticket == ticket:
            return {
                "ticket":     p.ticket,
                "type":       "BUY" if p.type == 0 else "SELL",
                "volume":     p.volume,
                "open_price": p.price_open,
                "sl":         p.sl,
                "tp":         p.tp,
                "profit_usd": p.profit,
                "profit_idr": p.profit * 17800,
                "open_time":  datetime.fromtimestamp(p.time).strftime("%H:%M:%S"),
            }
    return {}


def print_order_result(result: dict):
    """Print hasil eksekusi order."""
    print(f"\n{'─'*52}")
    if result["success"]:
        print(f"  ORDER BERHASIL")
        print(f"  Ticket  : #{result['ticket']}")
        print(f"  Type    : {result['signal']}")
        print(f"  Volume  : {result['volume']}")
        print(f"  Price   : {result['price']}")
        print(f"  SL      : {result['sl']}")
        print(f"  TP      : {result['tp']}")
        print(f"  Grade   : {result['grade']} | Mode: {result['mode']}")
        print(f"  Waktu   : {result['timestamp']}")
    else:
        print(f"  ORDER GAGAL: {result['msg']}")
    print(f"{'─'*52}")