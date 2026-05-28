# ea_state.py — shared state antara EA core dan API server

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import threading


@dataclass
class EAState:
    """
    Satu-satunya sumber kebenaran untuk seluruh sistem.
    EA core menulis, API membaca, dashboard menampilkan.
    """
    # ── Status EA ──────────────────────────────────────────────
    running:        bool   = False
    paused:         bool   = False
    mode:           str    = "auto"     # auto / scalp / intraday / swing
    scan_count:     int    = 0
    last_scan:      str    = ""
    uptime_start:   str    = ""

    # ── Market info ────────────────────────────────────────────
    current_price:  float  = 0.0
    bid:            float  = 0.0
    ask:            float  = 0.0
    spread_pip:     float  = 0.0
    session:        str    = "off"
    in_killzone:    bool   = False

    # ── Sinyal terakhir per mode ────────────────────────────────
    last_signals:   dict   = field(default_factory=dict)
    # format: {"scalp": {...}, "intraday": {...}, "swing": {...}}

    # ── Posisi terbuka ──────────────────────────────────────────
    open_positions: list   = field(default_factory=list)
    open_count:     int    = 0

    # ── PnL ────────────────────────────────────────────────────
    daily_pnl_usd:  float  = 0.0
    daily_pnl_idr:  float  = 0.0
    balance_usd:    float  = 0.0
    equity_usd:     float  = 0.0

    # ── Log aktivitas (50 entry terakhir) ──────────────────────
    activity_log:   list   = field(default_factory=list)

    # ── Kurs IDR real time ──────────────────────────────────────
    usd_idr:        float  = 17_800.0

    # ── Override flags ──────────────────────────────────────────
    override_daily_loss: bool = False  # bypass daily loss guard

    # ── Watchlist — setup yang menunggu harga ──────────────────
    watchlist:      list   = field(default_factory=list)

    # ── Trade history hari ini ─────────────────────────────────
    trades_today:   list   = field(default_factory=list)
    wins_today:     int    = 0
    losses_today:   int    = 0

    # ── Error terakhir ─────────────────────────────────────────
    last_error:     str    = ""


# Singleton state — satu instance untuk seluruh aplikasi
_state = EAState()
_lock  = threading.Lock()


def get_state() -> EAState:
    return _state


def update_state(**kwargs):
    """Update field state secara thread-safe."""
    with _lock:
        for key, value in kwargs.items():
            if hasattr(_state, key):
                setattr(_state, key, value)


def add_log(message: str, level: str = "INFO"):
    """Tambah entry ke activity log (max 50)."""
    with _lock:
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = {"time": timestamp, "level": level, "msg": message}
        _state.activity_log.append(entry)
        if len(_state.activity_log) > 50:
            _state.activity_log.pop(0)


def add_trade(trade: dict):
    """Tambah trade ke history hari ini."""
    with _lock:
        _state.trades_today.append(trade)
        if trade.get("profit_idr", 0) >= 0:
            _state.wins_today += 1
        else:
            _state.losses_today += 1


def to_dict() -> dict:
    """Convert state ke dict untuk JSON response."""
    with _lock:
        s = _state
        win_rate = 0
        total = s.wins_today + s.losses_today
        if total > 0:
            win_rate = round(s.wins_today / total * 100, 1)

        return {
            "status": {
                "running":      s.running,
                "paused":       s.paused,
                "mode":         s.mode,
                "scan_count":   s.scan_count,
                "last_scan":    s.last_scan,
                "uptime_start": s.uptime_start,
                "last_error":   s.last_error,
            },
            "market": {
                "price":      s.current_price,
                "bid":        s.bid,
                "ask":        s.ask,
                "spread_pip": s.spread_pip,
                "session":    s.session,
                "in_killzone": s.in_killzone,
            },
            "account": {
                "balance_usd":   s.balance_usd,
                "equity_usd":    s.equity_usd,
                "daily_pnl_usd": round(s.daily_pnl_usd, 2),
                "daily_pnl_idr": round(s.daily_pnl_idr, 0),
                "open_count":    s.open_count,
                "usd_idr":       s.usd_idr,
            },
            "performance": {
                "wins":      s.wins_today,
                "losses":    s.losses_today,
                "win_rate":  win_rate,
                "total":     total,
            },
            "signals":    s.last_signals,
            "watchlist":  s.watchlist,
            "positions":  s.open_positions,
            "log":        s.activity_log[-20:],
            "trades":     s.trades_today[-10:],
        }