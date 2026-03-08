"""
Orchestrator — main processing loop.

Pulls frames from the capture source, runs them through sensors,
and ticks the Jarvis agent for centralized decision-making.

Usage (from main.py):
    orch = Orchestrator(event_callback=_on_event)
    thread = threading.Thread(target=orch.run, daemon=True)
    thread.start()
"""

from __future__ import annotations

import logging
import threading
from queue import Queue, Empty, Full
from typing import Callable

from config import settings
from features.encounter_recording.recorder import EncounterRecorder

from agent.signal_bus import Signal, SignalBus, SignalType, Priority
from agent.confusion_detector import ConfusionDetector
from agent.jarvis import JarvisAgent
from sensors.face_sensor import FaceSensor
from sensors.motion_sensor import MotionSensor
from sensors.scene_sensor import SceneSensor
from sensors.activity_sensor import ActivitySensor

try:
    from sensors.audio_sensor import AudioSensor
    _audio_available = True
except ImportError:
    AudioSensor = None  # type: ignore[misc,assignment]
    _audio_available = False

logger = logging.getLogger(__name__)

# Lazy-import heavy native packages (cv2, numpy, capture modules).
# The server starts cleanly even when these are not installed; capture
# simply won't work until the packages are available.
try:
    import cv2
    import numpy as np
    _cv2_available = True
except ImportError:
    cv2 = None  # type: ignore[assignment]
    np = None   # type: ignore[assignment]
    _cv2_available = False
    logger.warning("cv2/numpy not available — capture & MJPEG disabled")

try:
    from capture.frame_capture import FrameCapture
except ImportError:
    FrameCapture = None  # type: ignore[misc,assignment]

try:
    from capture.glasses_capture import GlassesCapture
except ImportError:
    GlassesCapture = None  # type: ignore[misc,assignment]

try:
    from capture.mock_capture import MockCapture
except ImportError:
    MockCapture = None  # type: ignore[misc,assignment]


class Orchestrator:
    def __init__(self, event_callback: Callable[[dict], None] | None = None, capture=None) -> None:
        self.event_callback = event_callback or (lambda e: None)
        self.is_running = False
        self._latest_frame = None
        self._frame_lock = threading.Lock()
        self.frame_id: int = 0
        self._ai_queue: Queue = Queue(maxsize=2)
        self._ai_thread: threading.Thread | None = None

        # ── Signal bus (shared state) ─────────────────────────────────────
        self._bus = SignalBus()

        # ── Encounter recorder (frame-level, stays in orchestrator) ───────
        self.encounter_recorder = EncounterRecorder(on_event=self.event_callback)

        # ── Sensors ───────────────────────────────────────────────────────
        self.face_sensor = FaceSensor(self._bus)
        self.motion_sensor = MotionSensor(self._bus)
        self.scene_sensor = SceneSensor(self._bus)
        self.activity_sensor = ActivitySensor(self._bus)

        # ── Audio Sensor (optional — requires sounddevice + openai)
        self.audio_sensor = AudioSensor(self._bus) if _audio_available else None

        # ── Confusion Detector (tiered: aggregates motion + scene + activity + audio)
        self._confusion_detector = ConfusionDetector(self._bus)

        # ── Jarvis Agent ──────────────────────────────────────────────────
        self._agent = JarvisAgent(
            self._bus,
            event_callback=self.event_callback,
            encounter_callback=self.encounter_recorder.start_recording,
        )

        # ── Capture source — allow explicit override (used by tests/VideoFileCapture)
        if capture is not None:
            self._capture = capture
        elif settings.capture_mode == "glasses" and GlassesCapture is not None:
            self._capture = GlassesCapture(
                host=settings.glasses_ws_host,
                port=settings.glasses_ws_port,
            )
        elif settings.capture_mode in ("webcam", "video") and MockCapture is not None:
            self._capture = MockCapture()
        elif FrameCapture is not None:
            self._capture = FrameCapture()
        else:
            self._capture = None

        if self._capture is None:
            logger.warning(
                "No capture backend available for mode=%s — "
                "capture will not start until the required packages are installed.",
                settings.capture_mode,
            )

    # ── Backward-compat aliases for main.py ───────────────────────────────────

    @property
    def face_recognizer(self) -> FaceSensor:
        """Alias so main.py can still call orchestrator.face_recognizer.rebuild_embeddings()."""
        return self.face_sensor

    @property
    def active_task(self) -> str | None:
        """Read active task from the signal bus world state."""
        return self._bus.get_world().get("active_task")

    # ── Public API ────────────────────────────────────────────────────────────

    def set_active_task(self, task: str, set_by: str = "caregiver") -> None:
        """Called when a caregiver sets a task via the dashboard."""
        self._bus.update_world("active_task", task)
        self._bus.update_world("active_task_set_by", set_by)
        from services.backboard_client import memory
        memory.store("active_patient_task", {"task": task, "set_by": set_by})

    def clear_active_task(self) -> None:
        """Remove the current task (caregiver marks it done or cancels it)."""
        self._bus.update_world("active_task", None)
        self._bus.update_world("active_task_set_by", None)

    def trigger_manual_grounding(self) -> None:
        """Emit a MANUAL_GROUNDING signal for the agent to handle."""
        self._bus.emit(Signal(
            type=SignalType.MANUAL_GROUNDING,
            priority=Priority.HIGH,
        ))

    def run(self) -> None:
        """
        Main blocking loop. Call from a daemon thread.
        Ingests frames at full speed for the MJPEG stream.
        AI processing runs on a separate background thread so it never blocks display.
        """
        if self._capture is None:
            logger.error("Cannot start capture — no backend available")
            return

        self.is_running = True
        print("[Orchestrator] Capture loop started.")

        # Start audio sensor (mic + transcription)
        if self.audio_sensor:
            self.audio_sensor.start()
        else:
            print("[Orchestrator] WARNING: Audio sensor not available — "
                  "conversation recording will not work!")

        # Start AI worker in a separate thread
        self._ai_thread = threading.Thread(target=self._ai_worker, daemon=True)
        self._ai_thread.start()

        for frame in self._capture.frames():
            if not self.is_running:
                break

            # Store frame for MJPEG stream — full speed, no blocking
            with self._frame_lock:
                self._latest_frame = frame
                self.frame_id += 1

            # Feed encounter recorder (throttled internally to target fps)
            self.encounter_recorder.feed_frame(frame)

            # Queue frame for AI processing (drop oldest if full)
            if self._ai_queue.full():
                try:
                    self._ai_queue.get_nowait()
                except Empty:
                    pass
            try:
                self._ai_queue.put_nowait(frame)
            except Full:
                pass

        print("[Orchestrator] Capture loop stopped.")

    def _ai_worker(self) -> None:
        """Background thread: pulls frames from the queue, runs sensors, ticks agent."""
        print("[Orchestrator] AI worker started.")
        frame_count = 0

        while self.is_running:
            try:
                frame = self._ai_queue.get(timeout=0.5)
            except Empty:
                continue

            frame_count += 1

            # ── Face Sensor (every AI frame) ──────────────────────────────
            self.face_sensor.process(frame)

            # ── Motion Sensor (every AI frame) ────────────────────────────
            self.motion_sensor.process(frame)

            # ── Scene Sensor (every 10th AI frame) ────────────────────────
            if frame_count % 10 == 0:
                self.scene_sensor.process(frame)

            # ── Activity Sensor (every AI frame — has internal timer) ─────
            self.activity_sensor.process(frame)

            # ── Confusion Detector tick (aggregates evidence, emits CONFUSION)
            self._confusion_detector.tick()

            # ── Jarvis Agent tick ─────────────────────────────────────────
            self._agent.tick()

        print("[Orchestrator] AI worker stopped.")

    def get_latest_jpeg(self) -> bytes | None:
        """Return the latest frame as JPEG bytes (thread-safe)."""
        if not _cv2_available:
            return None
        if hasattr(self._capture, 'get_latest_frame'):
            frame = self._capture.get_latest_frame()
        else:
            with self._frame_lock:
                frame = self._latest_frame
        if frame is None:
            return None
        frame = self.face_recognizer.draw_overlay(frame)
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buf.tobytes()

    def wait_for_frame(self, timeout: float = 0.1) -> bool:
        """Block until a new frame arrives from the capture source."""
        if hasattr(self._capture, 'wait_for_frame'):
            return self._capture.wait_for_frame(timeout)
        return True

    @property
    def stream_frame_id(self) -> int:
        """Frame ID that updates the instant a new frame arrives."""
        if hasattr(self._capture, 'frame_id'):
            return self._capture.frame_id
        return self.frame_id

    def stop(self) -> None:
        self.is_running = False
        self.encounter_recorder.stop()
        if self.audio_sensor:
            self.audio_sensor.stop()
        if self._capture:
            self._capture.stop()

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _count_faces(frame) -> int:
        """Fast haar-cascade face count for conversation detection."""
        if not _cv2_available:
            return 0
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        faces = cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
        )
        return len(faces)
