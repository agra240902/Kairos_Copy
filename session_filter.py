# session_filter.py — session filter yang lebih lengkap

from datetime import datetime, time
from config import SESSIONS


def get_current_session(now: datetime = None) -> str:
    """
    Tentukan sesi trading saat ini (WIB).

    Returns:
        "overlap"     → 19:00–18:00 (London+NY, paling volatil)
        "london"      → 14:00–18:00
        "ny"          → 19:00–23:00
        "asian"       → 06:00–09:00
        "pre_london"  → 09:00–14:00  ← jam 10 kamu masuk sini
        "late_ny"     → 23:00–02:00
        "off"         → 02:00–06:00 (dini hari, skip)
    """
    if now is None:
        now = datetime.now()

    h = now.hour
    m = now.minute
    t = h * 60 + m  # menit dari tengah malam

    # Overlap London + NY (19:00–18:00, edge case)
    if (19*60 <= t <= 18*60) or (t >= 19*60):
        pass  # ditangani di bawah

    if 19*60 <= t <= 23*60:
        return "ny"
    if 14*60 <= t < 18*60:
        # Cek overlap
        if 19*60 <= t:
            return "overlap"
        return "london"
    if 9*60 <= t < 14*60:
        return "pre_london"
    if 6*60 <= t < 9*60:
        return "asian"
    if 23*60 <= t or t < 2*60:
        return "late_ny"
    # 02:00–06:00 → off
    return "off"


def is_in_killzone(now: datetime = None) -> bool:
    """True kalau di London, NY, atau overlap — sesi paling aktif."""
    return get_current_session(now) in ("london", "ny", "overlap")


def is_tradable_session(now: datetime = None) -> bool:
    """
    True kalau session yang valid untuk trading.
    Pre-London termasuk — jam 09:00–14:00 WIB tetap valid untuk scalp.
    Off hanya jam 02:00–06:00 dini hari.
    """
    return get_current_session(now) not in ("off", "late_ny")


def get_session_multiplier(session: str) -> float:
    """
    Bobot kualitas sesi untuk grading sinyal.
    Semakin tinggi = semakin bagus untuk entry.
    """
    return {
        "overlap":    1.5,
        "london":     1.3,
        "ny":         1.2,
        "asian":      1.0,
        "pre_london": 0.9,   # valid tapi prioritas lebih rendah
        "late_ny":    0.5,
        "off":        0.0,
    }.get(session, 1.0)


def session_status() -> dict:
    """Info lengkap tentang status sesi saat ini."""
    now     = datetime.now()
    session = get_current_session(now)
    return {
        "now":         now.strftime("%H:%M:%S WIB"),
        "session":     session,
        "in_killzone": is_in_killzone(now),
        "tradable":    is_tradable_session(now),
        "multiplier":  get_session_multiplier(session),
    }