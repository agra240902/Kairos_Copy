# signal_engine.py — otak EA dengan semua fix

from dataclasses import dataclass
from typing import Optional
import MetaTrader5 as mt5

from snr_detector import (
    detect_snr_zones, calculate_fibonacci, find_confluences,
    filter_ready_confluences, get_sl_price, get_tp_price
)
from session_filter import get_current_session, is_in_killzone
from volume_analyzer import get_volume_strength, get_price_action_confirmation
from config import MODE_CONFIG, FIBO_ZONE

# Risk per trade: 2% dari balance
RISK_PCT      = 0.02
PIP_VALUE_001 = 1.0    # USD per point untuk lot 0.01 di XAUUSDm Exness
MAX_SL_POINT  = 25.0   # SL maksimal 25 point = $25 per trade (lot 0.01)
MIN_SL_POINT  = 5.0    # SL minimal 5 point — otomatis diperlebar kalau struktur terlalu sempit


@dataclass
class TradeSignal:
    action:       str
    signal_type:  str
    grade:        str
    entry_price:  float
    sl_price:     float
    tp_price:     float
    lot:          float
    risk_pip:     float
    reward_pip:   float
    risk_usd:     float
    mode:         str
    reasons:      list
    rejections:   list
    session:      str
    confluence:   Optional[dict] = None

    def is_actionable(self) -> bool:
        return self.action == "ENTRY"


def _calc_lot(balance_usd: float, sl_pip: float) -> float:
    """
    Hitung lot berdasarkan 2% risk dari balance.
    Formula: lot = (balance × 0.02) / (sl_pip × pip_value_per_lot)
    Untuk XAUUSD: pip_value per 0.01 lot = $0.01, per 1 lot = $1
    """
    if sl_pip <= 0:
        return 0.01
    risk_usd = balance_usd * RISK_PCT
    # XAUUSDm Exness: 1 pip = $1 untuk lot 0.01 (verified dari trade aktual)
    # Formula: lot = risk_usd / (sl_pip × dollar_per_pip_per_001_lot)
    raw_lot  = risk_usd / (sl_pip * PIP_VALUE_001)
    lot      = round(raw_lot / 0.01) * 0.01
    return max(0.01, min(0.10, lot))


def _get_balance() -> float:
    """Ambil balance saat ini dari MT5."""
    info = mt5.account_info()
    if info is None:
        return 50.0  # fallback
    return info.balance


def analyze(mtf_data: dict, current_price: float,
            mode: str = "scalp", now=None) -> TradeSignal:

    reasons, rejections = [], []

    # ── 1. Session filter ──────────────────────────────────────
    session  = get_current_session(now)
    in_kz    = is_in_killzone(now)
    tradable = session not in ("off", "late_ny")

    if not tradable:
        return _empty_signal("SKIP", current_price, mode, session,
                              [f"Sesi {session} — tidak trading jam 02:00–06:00 WIB"])
    elif in_kz:
        reasons.append(f"Sesi {session} (kill zone)")
    elif session == "pre_london":
        reasons.append("Sesi pre-London (09:00–14:00 WIB)")
    elif session == "asian":
        reasons.append("Sesi Asian (06:00–09:00 WIB)")
    else:
        reasons.append(f"Sesi {session}")

    # ── 2. Timeframe setup ─────────────────────────────────────
    cfg        = MODE_CONFIG[mode]
    tf_entry   = cfg["timeframe_entry"]
    tf_confirm = cfg["timeframe_confirm"]
    df_entry   = mtf_data.get(tf_entry)
    df_confirm = mtf_data.get(tf_confirm)

    if df_entry is None or df_confirm is None:
        return _empty_signal("SKIP", current_price, mode, session,
                              ["Data timeframe tidak lengkap"])

    # ── 3. SNR zones — prioritaskan dari entry TF ─────────────
    # Untuk SL yang sempit, zona dari TF kecil lebih relevan
    entry_zones  = detect_snr_zones(df_entry, timeframe=tf_entry, min_touches=2)
    confirm_zones = detect_snr_zones(df_confirm, timeframe=tf_confirm, min_touches=2)
    all_zones    = entry_zones + confirm_zones

    # Tambah higher TF untuk bias saja (bukan untuk SL)
    for tf, df in mtf_data.items():
        if tf not in (tf_entry, tf_confirm):
            all_zones.extend(detect_snr_zones(df, timeframe=tf, min_touches=3))

    if not all_zones:
        return _empty_signal("SKIP", current_price, mode, session,
                              ["Tidak ada zona SNR terdeteksi"])

    # ── 4. Fibonacci ───────────────────────────────────────────
    fibo_levels = calculate_fibonacci(df_confirm, lookback=50)

    # ── 5. Confluence ──────────────────────────────────────────
    confluences      = find_confluences(all_zones, fibo_levels, current_price)
    ready, watchlist = filter_ready_confluences(confluences, current_price,
                                                entry_tolerance_pip=15.0)

    if not ready:
        if watchlist:
            return _empty_signal("WAIT", current_price, mode, session,
                                  [f"Harga belum di zona. {len(watchlist)} setup menunggu."])
        return _empty_signal("SKIP", current_price, mode, session,
                              ["Tidak ada confluence valid"])

    best   = ready[0]
    signal = best["signal_type"]
    zone   = best["zone"]

    if signal not in ("BUY", "SELL"):
        return _empty_signal("SKIP", current_price, mode, session,
                              ["Signal type tidak jelas"])

    # ── 6. PA confirmation — sesuai mode config ────────────────
    pa_required = cfg.get("pa_required", True)
    df_m5       = mtf_data.get("M5", df_entry)
    pa_info     = get_price_action_confirmation(df_m5, signal)

    if pa_required and not pa_info["confirmed"]:
        return _empty_signal("WAIT", current_price, mode, session,
                              ["Menunggu konfirmasi candle (rejection/engulfing)"])

    if pa_info["confirmed"]:
        patterns = []
        if pa_info["rejection_candle"]: patterns.append("rejection")
        if pa_info["engulfing"]:        patterns.append("engulfing")
        reasons.append(f"PA: {', '.join(patterns)}")
    else:
        reasons.append("PA: langsung entry di zona")

    # ── 7. Volume confirmation ─────────────────────────────────
    vol_info = get_volume_strength(df_entry, lookback=20)
    has_vol  = vol_info["is_spike"]
    reasons.append(f"Vol {vol_info['status']} ({vol_info['ratio']}x)")

    # ── 8. Grading — sesuai min_grade per mode ─────────────────
    is_golden = best["fibo"].level in FIBO_ZONE
    strength  = best["strength"]
    has_snr   = best["source"] == "snr+fibo"
    min_grade = cfg.get("min_grade", "A")

    if has_snr and is_golden and strength >= 3 and has_vol and in_kz:
        grade = "A+"
    elif has_snr and strength >= 2 and in_kz:
        grade = "A"
    elif has_snr and strength >= 2 and not in_kz:
        grade = "A" if (is_golden and has_vol) else "NONE"
    elif has_snr and strength >= 1 and min_grade == "B":
        # Grade B hanya untuk mode yang mengizinkan (scalp)
        grade = "B"
    else:
        grade = "NONE"

    if grade == "NONE":
        return _empty_signal("SKIP", current_price, mode, session,
                              [f"Grade tidak memenuhi minimum ({min_grade})"])

    # Kalau mode butuh minimal A tapi cuma dapat B → skip
    grade_order = {"B": 1, "A": 2, "A+": 3}
    if grade_order.get(grade, 0) < grade_order.get(min_grade, 2):
        return _empty_signal("SKIP", current_price, mode, session,
                              [f"Grade {grade} di bawah minimum {min_grade}"])

    # ── 9. SL dari zona entry TF — supaya sempit dan presisi ───
    # Prioritas: zona dari entry_zones dulu, baru confirm_zones
    entry_zone = None
    for z in entry_zones:
        dist = abs(z.price - current_price) * 10
        if dist <= 20:
            entry_zone = z
            break
    if entry_zone is None:
        entry_zone = zone  # fallback ke zona confluence

    sl_price = get_sl_price(signal, entry_zone, current_price, buffer_pip=6.0)
    risk_point = abs(current_price - sl_price)  # dalam point

    # Guard: SL maksimal 25 point, minimal 1 point
    if risk_point < MIN_SL_POINT:
        if signal == "BUY":
            sl_price = current_price - MIN_SL_POINT
        else:
            sl_price = current_price + MIN_SL_POINT
        risk_point = MIN_SL_POINT
        reasons.append(f"SL diperlebar ke {MIN_SL_POINT} point minimum")

    if risk_point > MAX_SL_POINT:
        return _empty_signal("SKIP", current_price, mode, session,
                              [f"SL terlalu lebar ({risk_point:.1f} point > {MAX_SL_POINT:.0f})"])

    # ── 10. Lot dan TP ─────────────────────────────────────────
    balance    = _get_balance()
    lot        = 0.01  # fixed lot — 1 point = $1
    tp_price   = get_tp_price(signal, current_price, sl_price, rr=cfg["tp_rr"])
    risk_usd   = risk_point * lot * PIP_VALUE_001
    reward_usd = abs(tp_price - current_price) * lot * PIP_VALUE_001
    risk_pip   = risk_point  # untuk display di dashboard
    reward_pip = abs(tp_price - current_price)

    reasons.append(f"SL {risk_point:.1f} pt (${risk_usd:.2f}) | TP {reward_pip:.1f} pt (${reward_usd:.2f})")

    return TradeSignal(
        action      = "ENTRY",
        signal_type = signal,
        grade       = grade,
        entry_price = current_price,
        sl_price    = sl_price,
        tp_price    = tp_price,
        lot         = lot,
        risk_pip    = risk_pip,
        reward_pip  = reward_pip,
        risk_usd    = risk_usd,
        mode        = mode,
        reasons     = reasons,
        rejections  = rejections,
        session     = session,
        confluence  = best,
    )


def _empty_signal(action, price, mode, session, rejections):
    return TradeSignal(
        action=action, signal_type="", grade="NONE",
        entry_price=price, sl_price=0, tp_price=0,
        lot=0, risk_pip=0, reward_pip=0, risk_usd=0,
        mode=mode, reasons=[], rejections=rejections,
        session=session, confluence=None,
    )


def print_signal(sig: TradeSignal):
    print(f"\n{'═'*52}")
    print(f"  TRADE SIGNAL — {sig.mode.upper()} | {sig.session.upper()}")
    print(f"{'═'*52}")
    print(f"  Action : {sig.action}")
    if sig.action == "ENTRY":
        print(f"  Grade  : {sig.grade}")
        print(f"  Signal : {sig.signal_type}")
        print(f"  Lot    : {sig.lot}  (2% risk)")
        print(f"  Entry  : {sig.entry_price:.2f}")
        print(f"  SL     : {sig.sl_price:.2f}  ({sig.risk_pip:.0f} pip | ${sig.risk_usd:.2f})")
        print(f"  TP     : {sig.tp_price:.2f}  ({sig.reward_pip:.0f} pip)")
        print(f"  RR     : 1:{sig.reward_pip/max(sig.risk_pip,1):.1f}")
        for r in sig.reasons:
            print(f"    + {r}")
    else:
        for r in sig.rejections:
            print(f"    → {r}")
    print(f"{'═'*52}")