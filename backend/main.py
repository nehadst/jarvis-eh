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
  GET  /api/stream                 — live MJPEG view of the glasses feed
  POST /api/montage/{person_id}    — manually trigger a memory montage
  WS   /ws                         — real-time event stream to the dashboard
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from config import settings, FACE_DB_PATH, FAMILY_PROFILES_PATH
from pipeline.orchestrator import Orchestrator
from services.backboard_client import memory
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
_main_loop: asyncio.AbstractEventLoop | None = None  # stored at startup


def _on_event(event: dict) -> None:
    """Called by the orchestrator whenever a feature fires. Thread-safe."""
    event["timestamp"] = datetime.utcnow().isoformat()
    event_log.append(event)
    if len(event_log) > 100:
        event_log.pop(0)
    # Schedule broadcast on the main event loop (safe from any thread)
    if _main_loop and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(manager.broadcast(event), _main_loop)


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global orchestrator, montage_builder, _main_loop
    _main_loop = asyncio.get_running_loop()
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
        return {"error": "not found"}, 404
    return json.loads(path.read_text())


@app.post("/api/family/{person_id}")
async def update_family_member(person_id: str, body: dict):
    """Create or update a family profile."""
    FAMILY_PROFILES_PATH.mkdir(parents=True, exist_ok=True)
    path = FAMILY_PROFILES_PATH / f"{person_id}.json"
    path.write_text(json.dumps(body, indent=2))
    return {"ok": True}


@app.post("/api/family/{person_id}/photos")
async def upload_face_photos(person_id: str, files: list[UploadFile] = File(...)):
    """
    Upload one or more face photos for a family member.
    Saves to data/face_db/{person_id}/ and clears the DeepFace embedding cache
    so the new photos are picked up on the next recognition cycle.
    """
    person_dir = FACE_DB_PATH / person_id
    person_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for f in files:
        # Sanitize filename
        safe_name = f.filename.replace("/", "_").replace("\\", "_")
        dest = person_dir / safe_name
        content = await f.read()
        dest.write_bytes(content)
        saved.append(safe_name)

    # Rebuild face embeddings so new photos are recognized immediately
    if orchestrator and hasattr(orchestrator, "face_recognizer"):
        orchestrator.face_recognizer.rebuild_embeddings()

    return {"ok": True, "person_id": person_id, "uploaded": saved}


@app.delete("/api/family/{person_id}")
async def delete_family_member(person_id: str):
    """Remove a family member's profile and their face photos."""
    import shutil
    profile_path = FAMILY_PROFILES_PATH / f"{person_id}.json"
    face_dir = FACE_DB_PATH / person_id

    if profile_path.exists():
        profile_path.unlink()
    if face_dir.exists():
        shutil.rmtree(face_dir)

    # Rebuild face embeddings
    if orchestrator and hasattr(orchestrator, "face_recognizer"):
        orchestrator.face_recognizer.rebuild_embeddings()

    return {"ok": True, "person_id": person_id}


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


@app.delete("/api/tasks")
async def clear_task():
    """Caregiver marks the current task as done or cancels it."""
    if orchestrator:
        orchestrator.clear_active_task()
        return {"ok": True}
    return {"ok": False}


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


@app.get("/api/capture/mode")
async def get_capture_mode():
    return {"mode": settings.capture_mode}


@app.post("/api/capture/start")
async def start_capture(body: dict | None = None):
    global orchestrator, capture_thread

    # Allow the dashboard to override capture mode at start time
    mode = (body or {}).get("mode")
    if mode and mode in ("glasses", "webcam", "video", "screen"):
        settings.capture_mode = mode
        # Rebuild orchestrator with the new capture source
        orchestrator = Orchestrator(event_callback=_on_event)

    if orchestrator and not orchestrator.is_running:
        capture_thread = threading.Thread(target=orchestrator.run, daemon=True)
        capture_thread.start()
        return {"ok": True, "message": f"Capture started ({settings.capture_mode})"}
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
        return {"error": "Person not found"}, 404

    if not montage_builder:
        return {"error": "Montage service not initialised"}, 503

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


# ─── Live Stream ─────────────────────────────────────────────────────────

def _mjpeg_generator():
    """Yield MJPEG frames the instant they arrive — no polling delay."""
    while orchestrator and orchestrator.is_running:
        # Block until a new frame arrives (up to 100ms timeout)
        orchestrator.wait_for_frame(timeout=0.1)
        jpeg = orchestrator.get_latest_jpeg()
        if jpeg:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            )


@app.get("/api/stream")
async def live_stream():
    """Open http://localhost:8000/api/stream in a browser to see the glasses feed."""
    if not orchestrator or not orchestrator.is_running:
        return {"error": "Capture not running. POST /api/capture/start first."}
    return StreamingResponse(
        _mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ─── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws/stream")
async def ws_stream(ws: WebSocket):
    """Push raw JPEG frames over WebSocket for smooth canvas rendering."""
    await ws.accept()
    last_frame_id = 0
    try:
        while True:
            if orchestrator and orchestrator.is_running:
                current_id = orchestrator.stream_frame_id
                if current_id > last_frame_id:
                    jpeg = orchestrator.get_latest_jpeg()
                    if jpeg:
                        await ws.send_bytes(jpeg)
                    last_frame_id = current_id
                await asyncio.sleep(0.005)
            else:
                await asyncio.sleep(0.1)  # wait for capture to start
    except WebSocketDisconnect:
        pass


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
