# config.py — semua parameter EA di sini

# ── Kredensial MT5 ──────────────────────────────────────────
MT5_LOGIN    = 123210126      # ganti dengan nomor akun demo kamu
MT5_PASSWORD = "HEHEHEHE"  # ganti dengan password akun demo
MT5_SERVER   = "HEHEHEHE"  # cek nama server di MT5 kamu

# ── Instrument ──────────────────────────────────────────────
SYMBOL       = "XAUUSDm"      # Exness pakai suffix 'm', cek di MT5 kamu
MAGIC_NUMBER = 20250521       # ID unik EA ini, jangan diubah

EA_MODE = "auto"

MODE_CONFIG = {
    "scalp": {
        "timeframe_entry":   "M5",
        "timeframe_confirm": "M15",
        "sl_pip":            5,
        "tp_rr":             1.0,    # RR 1:1 untuk scalp
        "max_trades_per_day": 12,
        "pa_required":       False,  # entry langsung di zona, tanpa PA confirmation
        "min_grade":         "B",    # grade B boleh
    },
    "intraday": {
        "timeframe_entry":   "H1",
        "timeframe_confirm": "H4",
        "sl_pip":            40,
        "tp_rr":             2.0,
        "max_trades_per_day": 2,
        "pa_required":       True,   # wajib PA confirmation
        "min_grade":         "A",    # minimal grade A
    },
    "swing": {
        "timeframe_entry":   "H4",
        "timeframe_confirm": "D1",
        "sl_pip":            100,
        "tp_rr":             3.0,
        "max_trades_per_day": 1,
        "pa_required":       True,   # wajib PA confirmation
        "min_grade":         "A",    # minimal grade A
    },
}

LOT_GRADE = {
    "A+": 0.03,   # semua konfluensi terpenuhi
    "A":  0.02,   # sebagian besar konfluensi
    "B":  0.01,   # konfluensi minimum
}

MAX_DAILY_LOSS_IDR  = 50_000   
MAX_DAILY_LOSS_USD  = 10.0     
MAX_OPEN_POSITIONS  = 1        
RISK_PER_TRADE_PCT  = 2.0      

# ── Session filter (WIB = UTC+7) ────────────────────────────
SESSIONS = {
    "asian":      {"start": "06:00", "end": "09:00"},   # Asian breakout
    "pre_london": {"start": "09:00", "end": "14:00"},   # Pre-London (valid untuk scalp)
    "london":     {"start": "14:00", "end": "18:00"},   # London kill zone
    "ny":         {"start": "19:00", "end": "23:00"},   # NY kill zone
    "late_ny":    {"start": "23:00", "end": "02:00"},   # Late NY (hindari)
}

# ── Fibonacci levels ─────────────────────────────────────────
FIBO_LEVELS = [0.382, 0.5, 0.618, 0.786]
FIBO_ZONE   = (0.5, 0.618)  

USD_IDR = 17_850
