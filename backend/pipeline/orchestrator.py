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

import threading
from queue import Queue, Empty, Full
from typing import Callable

import cv2
import numpy as np

from config import settings
from capture.frame_capture import FrameCapture
from capture.glasses_capture import GlassesCapture
from features.face_recognition.recognizer import FaceRecognizer
from features.situation_grounding.grounder import SituationGrounder
from features.activity_continuity.tracker import ActivityTracker
from features.wandering_guardian.guardian import WanderingGuardian


class Orchestrator:
    def __init__(self, event_callback: Callable[[dict], None] | None = None) -> None:
        self.event_callback = event_callback or (lambda e: None)
        self.is_running = False
        self.active_task: str | None = None
        self._latest_frame: np.ndarray | None = None
        self._frame_lock = threading.Lock()
        self.frame_id: int = 0
        self._ai_queue: Queue[np.ndarray] = Queue(maxsize=2)
        self._ai_thread: threading.Thread | None = None

        # Feature modules
        self.face_recognizer = FaceRecognizer(on_event=self.event_callback)
        self.grounder = SituationGrounder(on_event=self.event_callback)
        self.tracker = ActivityTracker(on_event=self.event_callback)
        self.guardian = WanderingGuardian(on_event=self.event_callback)

        # Capture source — Meta glasses (WebSocket) or screen grab (mss)
        if settings.capture_mode == "glasses":
            self._capture = GlassesCapture(
                host=settings.glasses_ws_host,
                port=settings.glasses_ws_port,
            )
        else:
            self._capture = FrameCapture()

    # ── Public API ────────────────────────────────────────────────────────────

    def set_active_task(self, task: str, set_by: str = "caregiver") -> None:
        """Called when a caregiver sets a task via the dashboard."""
        self.active_task = task
        self.grounder.set_active_task(task, set_by)
        self.tracker.set_active_task(task)

    def trigger_manual_grounding(self) -> None:
        """Grab a fresh frame and force a grounding message immediately."""
        frame = self._capture.grab_once()
        self.grounder.trigger_manual(frame)

    def run(self) -> None:
        """
        Main blocking loop. Call from a daemon thread.
        Ingests frames at full speed for the MJPEG stream.
        AI processing runs on a separate background thread so it never blocks display.
        """
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
        """Return the latest frame as JPEG bytes (thread-safe). Used by the MJPEG stream."""
        # Glasses mode: return raw JPEG from iOS (no re-encoding!)
        if hasattr(self._capture, 'get_latest_jpeg'):
            return self._capture.get_latest_jpeg()
        # Screen capture fallback: encode from numpy
        with self._frame_lock:
            frame = self._latest_frame
        if frame is None:
            return None
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buf.tobytes()

    def wait_for_frame(self, timeout: float = 0.1) -> bool:
        """Block until a new frame arrives from the capture source."""
        if hasattr(self._capture, 'wait_for_frame'):
            return self._capture.wait_for_frame(timeout)
        return True  # screen capture: just return immediately

    @property
    def stream_frame_id(self) -> int:
        """Frame ID that updates the instant a new JPEG arrives (not gated by AI queue)."""
        if hasattr(self._capture, 'jpeg_id'):
            return self._capture.jpeg_id
        return self.frame_id

    def stop(self) -> None:
        self.is_running = False
        self._capture.stop()
