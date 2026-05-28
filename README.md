# Kairos — XAUUSD Expert Advisor

> Algorithmic trading bot untuk XAUUSD (Gold) berbasis Python, MetaTrader 5, dan web dashboard real-time.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![MetaTrader5](https://img.shields.io/badge/MetaTrader-5-orange)
![FastAPI](https://img.shields.io/badge/FastAPI-latest-green)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)

---

## Tentang Kairos

Kairos adalah EA (Expert Advisor) trading otomatis untuk pair **XAUUSD (Gold vs US Dollar)** yang dibangun dengan Python. Berbeda dengan EA konvensional berbasis MQL5, Kairos menggunakan Python untuk fleksibilitas lebih tinggi dan web dashboard real-time yang bisa diakses dari browser maupun smartphone.

Strategi inti menggabungkan:
- **Support & Resistance (SNR)** otomatis dari swing high/low
- **Fibonacci Retracement** (zona golden 0.5–0.618)
- **Price Action Confirmation** (rejection candle & engulfing)
- **Volume Analysis** untuk konfirmasi momentum
- **Session Filter** (Asian, Pre-London, London, NY)

---

## Fitur Utama

- 🤖 **Auto Trading** — entry, SL, TP otomatis ke MT5
- 📊 **Web Dashboard** — real-time via WebSocket, responsive mobile
- 🎯 **Multi-Mode** — Scalp (M5/M15), Intraday (H1), Swing (H4)
- 📈 **Dynamic Grading** — A+, A, B berdasarkan kualitas confluence
- 🛡️ **Risk Management** — max 1 posisi, daily loss limit, SL berbasis struktur
- 🔄 **Trade Manager** — BE trigger & trailing stop otomatis (5 detik)
- 💱 **Kurs Real-time** — USD/IDR dari Frankfurter API
- ⏸️ **Full Control** — Start, Stop, Pause, Resume, Override dari dashboard

---

## Arsitektur

```
xauusd_ea/
├── main.py              # Entry point — jalankan server
├── config.py            # Semua parameter & konfigurasi
├── connector.py         # Koneksi ke MetaTrader 5
├── data_feed.py         # Ambil data OHLCV dari MT5
├── snr_detector.py      # Deteksi zona SNR & Fibonacci
├── volume_analyzer.py   # Analisis volume & price action
├── session_filter.py    # Filter sesi trading (WIB)
├── signal_engine.py     # Otak EA — generate sinyal entry
├── risk_manager.py      # Proteksi modal & risk guard
├── executor.py          # Place order ke MT5
├── trade_manager.py     # BE trigger & trailing stop
├── ea_core.py           # Loop utama EA (background thread)
├── ea_state.py          # Shared state antara EA & dashboard
├── api_server.py        # FastAPI server + WebSocket
├── currency.py          # Kurs USD/IDR real-time
├── backtest.py          # Framework backtest data historis
└── static/
    └── dashboard.html   # Web dashboard
```

---

## Requirement

- Windows 10/11 atau Windows Server
- Python 3.10+
- MetaTrader 5 (Exness atau broker lain)
- Akun trading (demo atau live)

---

## Instalasi

**1. Clone repository**
```bash
git clone https://github.com/username/kairos-ea.git
cd kairos-ea
```

**2. Install dependencies**
```bash
pip install MetaTrader5 pandas numpy fastapi uvicorn
```

**3. Konfigurasi akun**

Edit `config.py`:
```python
MT5_LOGIN    = 12345678        # nomor akun MT5
MT5_PASSWORD = "password"      # password akun
MT5_SERVER   = "Exness-MT5Trial"  # nama server broker
SYMBOL       = "XAUUSDm"       # nama symbol di broker kamu
```

**4. Jalankan**
```bash
python main.py
```

**5. Buka dashboard**

Buka browser ke `http://127.0.0.1:8000`

---

## Cara Pakai

### Start EA
1. Jalankan `python main.py` di terminal
2. Buka `http://127.0.0.1:8000` di browser
3. Klik **▶ Start** di dashboard
4. EA mulai scan market setiap 30 detik

### Mode Trading

| Mode | Timeframe | Grade | PA Required | RR |
|------|-----------|-------|-------------|-----|
| Scalp | M5/M15 | B, A, A+ | ❌ | 1:1 |
| Intraday | H1/H4 | A, A+ | ✅ | 1:2 |
| Swing | H4/D1 | A, A+ | ✅ | 1:3 |

### Session Trading (WIB)

| Jam | Sesi | Status |
|-----|------|--------|
| 02:00–06:00 | Off | ❌ Tidak trading |
| 06:00–09:00 | Asian | ✅ |
| 09:00–14:00 | Pre-London | ✅ |
| 14:00–18:00 | London | ✅ Kill zone |
| 19:00–23:00 | NY | ✅ Kill zone |
| 23:00–02:00 | Late NY | ❌ Tidak trading |

### Grading Sinyal

| Grade | Kondisi |
|-------|---------|
| A+ | SNR kuat + golden Fibo (0.5–0.618) + volume spike + PA + kill zone |
| A | SNR valid + PA confirmation + kill zone |
| B | SNR valid (scalp mode saja) |

---

## Risk Management

- **Max posisi EA**: 1 posisi sekaligus
- **Daily loss limit**: $10/hari (bisa di-override dari dashboard)
- **SL**: berbasis struktur SNR, minimal 5 point, maksimal 25 point
- **Lot**: 0.01 (fixed)
- **BE trigger**: profit 10 point → SL pindah ke break even
- **Trailing stop**: setiap 2 point profit tambahan, SL ikut bergerak

---

## Trade Manager

Trade manager berjalan setiap **5 detik** dan mengelola posisi EA yang terbuka:

**Normal mode** (SL > 8 point):
```
Profit 10 point → BE
Profit 12 point → Trailing setiap 2 point
TP otomatis di 12 point
```

**Extreme Scalp** (SL ≤ 8 point):
```
Profit 1 point → BE
Profit 2 point → Trailing setiap 1 point
TP otomatis di 5 point
```

---

## Backtest

```bash
python backtest.py
```

Backtest akan memproses 90 hari data historis untuk ketiga mode dan menampilkan:
- Win rate per grade (A+, A, B)
- Profit factor
- Max drawdown
- Expectancy per trade
- Verdict: layak live atau tidak

---

## Dashboard

Dashboard real-time dengan fitur:
- Harga XAUUSD + spread + sesi aktif
- Balance, equity, kurs USD/IDR real-time
- PnL hari ini (Rupiah & USD)
- Win/Loss counter dari MT5 history
- Sinyal terakhir per mode + watchlist
- Posisi terbuka (EA & manual)
- Activity log 50 entry terakhir
- Kontrol penuh: Start/Stop/Pause/Resume/Override/Mode

---

## Disclaimer

> Trading forex dan gold mengandung risiko tinggi. EA ini dibuat untuk tujuan edukasi dan penelitian. Selalu uji di akun demo sebelum live. Hasil backtest tidak menjamin profit di masa depan. Gunakan dengan bijak dan pahami risikonya.

---

## Tech Stack

- **Python 3.10+** — core logic
- **MetaTrader5** — koneksi broker & eksekusi order
- **FastAPI + Uvicorn** — backend API server
- **WebSocket** — update dashboard real-time
- **Pandas + NumPy** — analisis data market
- **Frankfurter API** — kurs USD/IDR real-time

---

*Built with ❤️ for learning algorithmic trading*
