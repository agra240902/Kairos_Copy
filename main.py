
from api_server import run_server

if __name__ == "__main__":
    print("=" * 52)
    print("  XAUUSD EA — Starting...")
    print("  Dashboard: http://127.0.0.1:8000")
    print("  Tekan Ctrl+C untuk berhenti")
    print("=" * 52)
    run_server(host="127.0.0.1", port=8000)

  