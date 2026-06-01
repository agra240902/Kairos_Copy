
from api_server import run_server

if __name__ == "__main__":
    print("=" * 52)
    print("  XAUUSD EA — Starting...")
    print("  Dashboard: http://100.110.205.107:8000")
    print("  Tekan Ctrl+C untuk berhenti")
    print("=" * 52)
    run_server(host="100.110.205.107", port=8000)