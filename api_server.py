# api_server.py — FastAPI backend untuk dashboard

import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import ea_state as state
import ea_core

app = FastAPI(title="XAUUSD EA Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (HTML dashboard)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── REST API endpoints ──────────────────────────────────────

@app.get("/api/state")
def get_state():
    return JSONResponse(state.to_dict())


@app.post("/api/ea/start")
def start():
    ok, msg = ea_core.start_ea()
    return {"success": ok, "message": msg}


@app.post("/api/ea/stop")
def stop():
    ok, msg = ea_core.stop_ea()
    return {"success": ok, "message": msg}


@app.post("/api/ea/pause")
def pause():
    ok, msg = ea_core.pause_ea()
    return {"success": ok, "message": msg}


@app.post("/api/ea/resume")
def resume():
    ok, msg = ea_core.resume_ea()
    return {"success": ok, "message": msg}


@app.post("/api/ea/reset-daily")
def reset_daily():
    import ea_state as state
    state.update_state(override_daily_loss=True)
    state.add_log("Daily loss limit di-override — EA bisa entry lagi hari ini", "WARN")
    return {"success": True, "message": "Daily loss override aktif"}


@app.post("/api/ea/mode/{mode}")
def set_mode(mode: str):
    ok, msg = ea_core.set_mode(mode)
    return {"success": ok, "message": msg}


# ── WebSocket untuk update real-time ───────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Kirim state awal langsung saat connect
        await websocket.send_json(state.to_dict())

        # Lanjut broadcast setiap 2 detik
        while True:
            await asyncio.sleep(2)
            await websocket.send_json(state.to_dict())
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ── Serve dashboard HTML ────────────────────────────────────

@app.get("/")
def dashboard():
    with open("static/dashboard.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


# ── Entry point ─────────────────────────────────────────────

def run_server(host: str = "127.0.0.1", port: int = 8000):
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    run_server()