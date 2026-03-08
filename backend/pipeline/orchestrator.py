"""
Orchestrator — main processing loop.

Pulls frames from the screen, runs them through each active feature module,
and fires an event_callback for every result so main.py can broadcast to
the dashboard + play audio.

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
from features.face_recognition.recognizer import FaceRecognizer
from features.situation_grounding.grounder import SituationGrounder
from features.activity_continuity.tracker import ActivityTracker
from features.wandering_guardian.guardian import WanderingGuardian

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
    def __init__(self, event_callback: Callable[[dict], None] | None = None) -> None:
        self.event_callback = event_callback or (lambda e: None)
        self.is_running = False
        self.active_task: str | None = None
        self._latest_frame = None
        self._frame_lock = threading.Lock()
        self.frame_id: int = 0
        self._ai_queue: Queue = Queue(maxsize=2)
        self._ai_thread: threading.Thread | None = None

        # Feature modules
        self.face_recognizer = FaceRecognizer(on_event=self.event_callback)
        self.grounder = SituationGrounder(on_event=self.event_callback)
        self.tracker = ActivityTracker(on_event=self.event_callback)
        self.guardian = WanderingGuardian(on_event=self.event_callback)

        # Capture source
        self._capture = None
        if settings.capture_mode == "glasses" and GlassesCapture is not None:
            self._capture = GlassesCapture(
                host=settings.glasses_ws_host,
                port=settings.glasses_ws_port,
            )
        elif settings.capture_mode in ("webcam", "video") and MockCapture is not None:
            self._capture = MockCapture()
        elif FrameCapture is not None:
            self._capture = FrameCapture()

        if self._capture is None:
            logger.warning(
                "No capture backend available for mode=%s — "
                "capture will not start until the required packages are installed.",
                settings.capture_mode,
            )

    # ── Public API ────────────────────────────────────────────────────────────

    def set_active_task(self, task: str, set_by: str = "caregiver") -> None:
        """Called when a caregiver sets a task via the dashboard."""
        self.active_task = task
        self.grounder.set_active_task(task, set_by)
        self.tracker.set_active_task(task)

    def clear_active_task(self) -> None:
        """Remove the current task (caregiver marks it done or cancels it)."""
        self.active_task = None
        self.grounder.clear_active_task()

    def trigger_manual_grounding(self) -> None:
        """Grab a fresh frame and force a grounding message immediately."""
        if self._capture is None:
            logger.warning("trigger_manual_grounding called but no capture backend")
            return
        frame = self._capture.grab_once()
        self.grounder.trigger_manual(frame)

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
        """Background thread: pulls frames from the queue and runs AI features."""
        print("[Orchestrator] AI worker started.")
        frame_count = 0

        while self.is_running:
            try:
                frame = self._ai_queue.get(timeout=0.5)
            except Empty:
                continue

            frame_count += 1

            # ── Face Recognition (every AI frame) ────────────────────────
            self.face_recognizer.process(frame)

            # ── Situation Grounding (every 10th AI frame) ────────────────
            if frame_count % 10 == 0:
                self.grounder.process(frame)

            # ── Activity Continuity (every AI frame) ─────────────────────
            self.tracker.process(frame)

            # ── Wandering Guardian (every 10th AI frame) ─────────────────
            if frame_count % 10 == 0:
                self.guardian.process(frame)

        print("[Orchestrator] AI worker stopped.")

    def get_latest_jpeg(self) -> bytes | None:
        """Return the latest frame as JPEG bytes with face overlay (thread-safe)."""
        if not _cv2_available:
            return None
        # Glasses mode (H.264): get decoded numpy frame directly
        if self._capture is not None and hasattr(self._capture, 'get_latest_frame'):
            frame = self._capture.get_latest_frame()
        else:
            # Screen/webcam/video: read from orchestrator's own buffer
            with self._frame_lock:
                frame = self._latest_frame
        if frame is None:
            return None
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buf.tobytes()

    def wait_for_frame(self, timeout: float = 0.1) -> bool:
        """Block until a new frame arrives from the capture source."""
        if self._capture is not None and hasattr(self._capture, 'wait_for_frame'):
            return self._capture.wait_for_frame(timeout)
        return True  # screen capture: just return immediately

    @property
    def stream_frame_id(self) -> int:
        """Frame ID that updates the instant a new frame arrives (not gated by AI queue)."""
        if self._capture is not None and hasattr(self._capture, 'frame_id'):
            return self._capture.frame_id
        return self.frame_id

    def stop(self) -> None:
        self.is_running = False
        if self._capture is not None:
            self._capture.stop()
