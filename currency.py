# currency.py — ambil kurs USD/IDR real time

import urllib.request
import json
from datetime import datetime

# Fallback kalau API tidak bisa diakses
FALLBACK_RATE = 17_800
_cached_rate  = FALLBACK_RATE
_last_updated = None


def get_usd_idr() -> float:
    """
    Ambil kurs USD/IDR terkini dari Frankfurter API.
    Cache 1 jam — tidak perlu fetch setiap scan.
    """
    global _cached_rate, _last_updated

    # Pakai cache kalau masih fresh (< 1 jam)
    if _last_updated is not None:
        elapsed = (datetime.now() - _last_updated).seconds
        if elapsed < 3600:
            return _cached_rate

    try:
        url = "https://api.frankfurter.app/latest?from=USD&to=IDR"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            rate = data["rates"]["IDR"]
            _cached_rate  = round(rate, 0)
            _last_updated = datetime.now()
            return _cached_rate
    except Exception:
        # Kalau gagal, pakai cache terakhir atau fallback
        return _cached_rate


def get_rate_info() -> dict:
    """Info lengkap kurs termasuk waktu update."""
    rate = get_usd_idr()
    return {
        "rate":         rate,
        "last_updated": _last_updated.strftime("%H:%M:%S") if _last_updated else "—",
        "source":       "Frankfurter API" if _last_updated else "Fallback",
    }