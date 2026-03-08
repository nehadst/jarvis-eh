"""
REWIND — FastAPI backend entry point.

Endpoints:
  GET  /health                          — liveness check
  GET  /api/family                      — list all family profiles
  GET  /api/family/{id}                 — get one profile
  POST /api/family/{id}                 — create / update a profile
  POST /api/family/{id}/photos          — upload face photos
  DELETE /api/family/{id}               — remove a family member
  POST /api/tasks                       — caregiver adds a task for the patient
  GET  /api/tasks                       — get current active task
  DELETE /api/tasks                     — clear current task
  POST /api/household                   — set who is currently home
  GET  /api/household                   — get current household context
  POST /api/grounding/trigger           — manually trigger a grounding message
  GET  /api/events                      — recent event log
  POST /api/capture/start               — start the live frame-capture loop
  POST /api/capture/stop                — stop the loop
  GET  /api/stream                      — live MJPEG view of the glasses feed
  POST /api/montage/{person_id}         — on-demand memory montage (optional ?tag=christmas)
  GET  /api/safezones                   — get current safe zone list
  POST /api/safezones                   — update safe zone list
  DELETE /api/safezones/{zone}          — remove a zone (custom or default)
  GET  /api/context                     — get current situational context
  POST /api/context                     — set situational context (where patient is expected to be)
  POST /api/encounter/{person_id}/record — manually trigger an encounter recording
  GET  /api/encounters/{person_id}      — list encounter clips + snapshots for a person
  GET  /api/encounters                  — list recent encounters across all people
  GET  /api/encounter/status            — check if recording in progress
  WS   /ws                              — real-time event stream to the dashboard
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from config import settings, FACE_DB_PATH, FAMILY_PROFILES_PATH
from pipeline.orchestrator import Orchestrator
from services.backboard_client import memory
from features.wandering_guardian.guardian import DEFAULT_SAFE_ZONES


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
    global orchestrator, _main_loop
    _main_loop = asyncio.get_running_loop()
    orchestrator = Orchestrator(event_callback=_on_event)
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
    # Hot-reload so the running recognizer sees the new/updated profile
    # without requiring a server restart.
    if orchestrator:
        orchestrator.face_recognizer.reload_profiles()
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


@app.get("/api/webcams")
async def list_webcams():
    """Enumerate available webcam devices by probing OpenCV indices."""
    try:
        import cv2
        import subprocess
    except ImportError:
        return {"webcams": []}

    # Try to get real device names via macOS system_profiler
    device_names: dict[int, str] = {}
    try:
        result = subprocess.run(
            ["system_profiler", "SPCameraDataType", "-json"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            import json as _json
            data = _json.loads(result.stdout)
            for idx, cam in enumerate(data.get("SPCameraDataType", [])):
                device_names[idx] = cam.get("_name", f"Camera {idx}")
    except Exception:
        pass

    # Probe indices 0-9 using AVFoundation backend (macOS native)
    devices = []
    for i in range(10):
        cap = cv2.VideoCapture(i, cv2.CAP_AVFOUNDATION)
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            name = device_names.get(i, f"Camera {i}")
            devices.append({"index": i, "label": f"{name} ({w}x{h})"})
            cap.release()
        else:
            cap.release()
    return {"webcams": devices}


@app.post("/api/capture/start")
async def start_capture(body: dict | None = None):
    global orchestrator, capture_thread

    # Allow the dashboard to override capture mode at start time
    mode = (body or {}).get("mode")
    webcam_index = (body or {}).get("webcam_index")
    if mode and mode in ("glasses", "webcam", "video", "screen"):
        settings.capture_mode = mode
    if webcam_index is not None:
        settings.webcam_index = int(webcam_index)
    if mode or webcam_index is not None:
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


# ─── Encounter Recording ─────────────────────────────────────────────────

@app.post("/api/encounter/{person_id}/record")
async def trigger_encounter_recording(person_id: str):
    """Manually trigger an encounter recording for a family member."""
    path = FAMILY_PROFILES_PATH / f"{person_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Person not found")

    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    profile = json.loads(path.read_text())
    name = profile.get("name", person_id)
    relationship = profile.get("relationship", "person")

    started = orchestrator.encounter_recorder.start_recording(person_id, name, relationship)
    if not started:
        return {"ok": False, "message": "Recording already in progress"}

    return {
        "ok": True,
        "message": f"Recording started for {name}",
        "person_id": person_id,
    }


@app.get("/api/encounters/{person_id}")
async def get_encounters(person_id: str):
    """List encounter clips + snapshots for a person."""
    clips = memory.retrieve(f"encounter_clips_{person_id}")
    if not clips:
        clips = []
    if not isinstance(clips, list):
        clips = [clips]
    return {"person_id": person_id, "encounters": clips}


@app.get("/api/encounters")
async def get_all_encounters():
    """List recent encounters across all family members."""
    encounters = []
    for f in FAMILY_PROFILES_PATH.glob("*.json"):
        try:
            profile = json.loads(f.read_text())
            person_id = profile.get("id", f.stem)
            clips = memory.retrieve(f"encounter_clips_{person_id}")
            if isinstance(clips, list):
                for clip in clips:
                    clip["person_id"] = person_id
                    clip["person"] = profile.get("name", person_id)
                    encounters.append(clip)
        except Exception:
            pass
    # Sort by timestamp descending
    encounters.sort(key=lambda e: e.get("timestamp", 0), reverse=True)
    return {"encounters": encounters[:50]}


@app.get("/api/encounter/status")
async def get_encounter_status():
    """Check if an encounter recording is currently in progress."""
    if not orchestrator:
        return {"recording": False}
    return {"recording": orchestrator.encounter_recorder.is_recording}


# ─── Memory Montage ──────────────────────────────────────────────────────

@app.post("/api/montage/{person_id}")
async def trigger_montage(person_id: str, tag: str = Query(None)):
    """On-demand memory montage for a family member. Optional ?tag=christmas."""
    path = FAMILY_PROFILES_PATH / f"{person_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Person not found")

    try:
        from features.memory_montage.builder import MontageBuilder
    except ImportError:
        raise HTTPException(status_code=503, detail="Montage service not available")

    builder = MontageBuilder()

    # Run in a background thread so the HTTP response returns immediately
    def _run():
        result = builder.build(person_id, tag_filter=tag, force=True)
        if result:
            _on_event(result)

    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "message": f"Montage building for {person_id}"}


# ─── Safe Zones ──────────────────────────────────────────────────────────

@app.get("/api/safezones")
async def get_safezones():
    """
    Return the current safe zone list (defaults + custom, minus excluded).
    """
    stored = memory.retrieve("safe_zones")
    excluded_stored = memory.retrieve("excluded_safe_zones")
    custom: list[str] = stored if isinstance(stored, list) else []
    excluded: list[str] = excluded_stored if isinstance(excluded_stored, list) else []
    all_zones = sorted(
        (DEFAULT_SAFE_ZONES | {z.lower() for z in custom}) - {z.lower() for z in excluded}
    )
    return {"safe_zones": all_zones, "custom_zones": custom, "excluded_zones": excluded}


@app.delete("/api/safezones/{zone}")
async def remove_safezone(zone: str):
    """
    Remove a safe zone by name. Works for both custom zones and built-in defaults.
    Custom zones are removed from the stored list; default zones are added to an
    excluded list so they are subtracted at runtime.
    """
    zone = zone.lower().strip()

    # Remove from custom list if present
    stored = memory.retrieve("safe_zones")
    custom: list[str] = stored if isinstance(stored, list) else []
    if zone in custom:
        custom = [z for z in custom if z != zone]
        memory.store("safe_zones", custom)

    # If it's a default zone, track it as excluded
    if zone in DEFAULT_SAFE_ZONES:
        excluded_stored = memory.retrieve("excluded_safe_zones")
        excluded: list[str] = excluded_stored if isinstance(excluded_stored, list) else []
        if zone not in excluded:
            excluded = sorted(excluded + [zone])
            memory.store("excluded_safe_zones", excluded)

    return {"ok": True, "removed": zone}


@app.get("/api/context")
async def get_context():
    """Return the current caregiver-provided situational context."""
    return memory.retrieve("situational_context") or {"description": ""}


@app.post("/api/context")
async def set_context(body: dict):
    """
    Set background context so the wandering guardian knows where the patient is supposed to be.
    Example body: {"description": "at a church community event until 3pm"}
    Send an empty description to clear the context.
    """
    description = body.get("description", "").strip()
    if description:
        memory.store("situational_context", {"description": description})
    else:
        memory.store("situational_context", {"description": ""})
    return {"ok": True, "description": description}


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
    incoming = {z.lower().strip() for z in zones if z.strip()}
    # Persist only the custom additions (deduplicated, lowercased)
    custom = sorted(incoming - DEFAULT_SAFE_ZONES)
    memory.store("safe_zones", custom)
    # Un-exclude any default zones that are being re-added
    re_added_defaults = incoming & DEFAULT_SAFE_ZONES
    if re_added_defaults:
        excluded_stored = memory.retrieve("excluded_safe_zones")
        excluded: list[str] = excluded_stored if isinstance(excluded_stored, list) else []
        excluded = sorted(z for z in excluded if z not in re_added_defaults)
        memory.store("excluded_safe_zones", excluded)
    return {"ok": True, "safe_zones": custom}


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
