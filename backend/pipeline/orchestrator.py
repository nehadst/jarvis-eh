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

import time
from typing import Callable

from capture.frame_capture import FrameCapture
from features.face_recognition.recognizer import FaceRecognizer
from features.situation_grounding.grounder import SituationGrounder
from features.activity_continuity.tracker import ActivityTracker
from features.wandering_guardian.guardian import WanderingGuardian


class Orchestrator:
    def __init__(self, event_callback: Callable[[dict], None] | None = None, capture=None) -> None:
        self.event_callback = event_callback or (lambda e: None)
        self.is_running = False
        self.active_task: str | None = None

        # Feature modules
        self.face_recognizer = FaceRecognizer(on_event=self.event_callback)
        self.grounder = SituationGrounder(on_event=self.event_callback)
        self.tracker = ActivityTracker(on_event=self.event_callback)
        self.guardian = WanderingGuardian(on_event=self.event_callback)

        self._capture = capture if capture is not None else FrameCapture()

    # ── Public API ────────────────────────────────────────────────────────────

    def set_active_task(self, task: str, set_by: str = "caregiver") -> None:
        """Called when a caregiver sets a task via the dashboard."""
        self.active_task = task
        self.grounder.set_active_task(task, set_by)
        self.tracker.set_active_task(task)

    def run(self) -> None:
        """
        Main blocking loop. Call from a daemon thread.
        Captures frames at 2 FPS and routes them through each feature.
        """
        self.is_running = True
        print("[Orchestrator] Capture loop started.")

        frame_count = 0
        for frame in self._capture.frames():
            if not self.is_running:
                break

            frame_count += 1

            # ── Feature 1: Face Recognition (every frame) ─────────────────
            self.face_recognizer.process(frame)

            # ── Feature 3: Situation Grounding (every 10 frames ≈ 5s) ──────
            if frame_count % 10 == 0:
                self.grounder.process(frame)

            # ── Feature 4: Activity Continuity (every frame for buffer) ────
            self.tracker.process(frame)

            # ── Feature 9: Wandering Guardian (every 10 frames) ─────────────
            if frame_count % 10 == 0:
                self.guardian.process(frame)

        print("[Orchestrator] Capture loop stopped.")

    def stop(self) -> None:
        self.is_running = False
        self._capture.stop()
