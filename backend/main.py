"""
REWIND — FastAPI backend entry point.

Endpoints:
  GET  /health                     — liveness check
  GET  /api/family                 — list all family profiles
  GET  /api/family/{id}            — get one profile
  POST /api/family/{id}            — create / update a profile
  POST /api/tasks                  — caregiver adds a task for the patient
  GET  /api/tasks                  — get current active task
  POST /api/household              — set who is currently home
  GET  /api/household              — get current household context
  POST /api/grounding/trigger      — manually trigger a grounding message
  GET  /api/tasks                  — get the current active task
  GET  /api/events                 — recent event log
  POST /api/capture/start          — start the live frame-capture loop
  POST /api/capture/stop           — stop the loop
  POST /api/montage/{person_id}    — on-demand memory montage (optional ?tag=christmas)
  GET  /api/safezones              — get current safe zone list
  POST /api/safezones              — update safe zone list
  WS   /ws                         — real-time event stream to the dashboard
"""

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware

from config import settings, FAMILY_PROFILES_PATH
from pipeline.orchestrator import Orchestrator
from services.backboard_client import memory
from features.wandering_guardian.guardian import DEFAULT_SAFE_ZONES
from features.memory_montage.builder import MontageBuilder


# ─── WebSocket connection manager ────────────────────────────────────────────

class ConnectionManager:
    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.active.remove(ws)

    async def broadcast(self, data: dict) -> None:
        message = json.dumps(data)
        for ws in list(self.active):
            try:
                await ws.send_text(message)
            except Exception:
                self.disconnect(ws)


manager = ConnectionManager()

# ─── Global state ─────────────────────────────────────────────────────────────

orchestrator: Orchestrator | None = None
montage_builder: MontageBuilder | None = None
capture_thread: threading.Thread | None = None
event_log: list[dict] = []  # keep the last 100 events in memory


def _on_event(event: dict) -> None:
    """Called by the orchestrator whenever a feature fires. Thread-safe."""
    event["timestamp"] = datetime.utcnow().isoformat()
    event_log.append(event)
    if len(event_log) > 100:
        event_log.pop(0)
    # Schedule broadcast on the event loop (orchestrator runs in its own thread)
    try:
        loop = asyncio.get_running_loop()
        asyncio.run_coroutine_threadsafe(manager.broadcast(event), loop)
    except RuntimeError:
        pass  # no running loop yet (startup phase)


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global orchestrator, montage_builder
    orchestrator = Orchestrator(event_callback=_on_event)
    montage_builder = MontageBuilder(on_event=_on_event)
    yield
    if orchestrator:
        orchestrator.stop()


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="REWIND API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "patient": settings.patient_name}


@app.get("/api/family")
async def list_family():
    profiles = []
    for f in FAMILY_PROFILES_PATH.glob("*.json"):
        profiles.append(json.loads(f.read_text()))
    return profiles


@app.get("/api/family/{person_id}")
async def get_family_member(person_id: str):
    path = FAMILY_PROFILES_PATH / f"{person_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Family member not found")
    return json.loads(path.read_text())


@app.post("/api/family/{person_id}")
async def update_family_member(person_id: str, body: dict):
    """Create or update a family profile."""
    FAMILY_PROFILES_PATH.mkdir(parents=True, exist_ok=True)
    path = FAMILY_PROFILES_PATH / f"{person_id}.json"
    path.write_text(json.dumps(body, indent=2))
    return {"ok": True}


@app.post("/api/tasks")
async def add_task(body: dict):
    """
    Caregiver adds an active task for the patient.
    Example body: {"task": "Go to the fridge and grab an orange", "set_by": "Sarah"}
    """
    if orchestrator:
        orchestrator.set_active_task(body.get("task", ""), body.get("set_by", "caregiver"))
    return {"ok": True}


@app.get("/api/tasks")
async def get_task():
    if orchestrator:
        return {"task": orchestrator.active_task}
    return {"task": None}


@app.post("/api/household")
async def set_household(body: dict):
    """
    Set who is currently home.
    Example body: {"who_is_home": "David, Sarah"}
    """
    memory.store("household_context", {"who_is_home": body.get("who_is_home", "")})
    return {"ok": True}


@app.get("/api/household")
async def get_household():
    return memory.retrieve("household_context") or {"who_is_home": ""}


@app.post("/api/grounding/trigger")
async def trigger_grounding():
    """Caregiver manually triggers an immediate grounding message."""
    if orchestrator:
        orchestrator.trigger_manual_grounding()
        return {"ok": True}
    return {"ok": False, "message": "Orchestrator not initialized"}


@app.get("/api/events")
async def get_events():
    return event_log


@app.post("/api/capture/start")
async def start_capture():
    global capture_thread
    if orchestrator and not orchestrator.is_running:
        capture_thread = threading.Thread(target=orchestrator.run, daemon=True)
        capture_thread.start()
        return {"ok": True, "message": "Capture started"}
    return {"ok": False, "message": "Already running or not initialized"}


@app.post("/api/capture/stop")
async def stop_capture():
    if orchestrator:
        orchestrator.stop()
        return {"ok": True, "message": "Capture stopped"}
    return {"ok": False}


@app.post("/api/montage/{person_id}")
async def trigger_montage(
    person_id: str,
    tag: str | None = Query(default=None, description="Optional tag filter, e.g. 'christmas'"),
):
    """
    Caregiver on-demand montage trigger.
    Runs the full pipeline (Gemini narration → ElevenLabs → Cloudinary) in a
    background thread and broadcasts a montage_ready event to all WS clients.

    Query params:
      ?tag=christmas  — narrows photo selection to photos also tagged 'christmas'
    """
    path = FAMILY_PROFILES_PATH / f"{person_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Person not found")

    if not montage_builder:
        raise HTTPException(status_code=503, detail="Montage service not initialised")

    # Run in a background thread so the HTTP response returns immediately
    def _run():
        montage_builder.build(person_id, tag_filter=tag, force=True)

    threading.Thread(target=_run, daemon=True).start()

    profile = json.loads(path.read_text())
    return {
        "ok": True,
        "message": f"Montage building for {profile.get('name')} — watch the dashboard",
        "person_id": person_id,
        "tag_filter": tag,
    }


@app.get("/api/safezones")
async def get_safezones():
    """
    Return the current safe zone list (caregiver-stored zones merged with
    the built-in defaults).
    """
    stored = memory.retrieve("safe_zones")
    custom: list[str] = stored if isinstance(stored, list) else []
    all_zones = sorted(DEFAULT_SAFE_ZONES | {z.lower() for z in custom})
    return {"safe_zones": all_zones, "custom_zones": custom}


@app.post("/api/safezones")
async def set_safezones(body: dict):
    """
    Update the caregiver-defined safe zone list.
    Body: {"safe_zones": ["garden", "sunroom"]}
    Only the *custom* (non-default) zones need to be stored; the guardian
    merges them with DEFAULT_SAFE_ZONES at runtime.
    """
    zones = body.get("safe_zones", [])
    if not isinstance(zones, list):
        raise HTTPException(status_code=400, detail="safe_zones must be a list")
    # Persist only the custom additions (deduplicated, lowercased)
    custom = sorted({z.lower().strip() for z in zones if z.strip()})
    memory.store("safe_zones", custom)
    return {"ok": True, "safe_zones": custom}


# ─── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    # Send recent events on connect so dashboard isn't blank
    for event in event_log[-20:]:
        await ws.send_text(json.dumps(event))
    try:
        while True:
            await ws.receive_text()  # keep-alive
    except WebSocketDisconnect:
        manager.disconnect(ws)


# ─── Dev runner ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=settings.debug)
