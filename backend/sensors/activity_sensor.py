"""
Activity Sensor — periodic activity inference.

Extracted from tracker.py. Periodically asks Gemini Vision what the person
is doing, maintains a 90-second rolling buffer, and emits ACTIVITY_INFERRED.

Updates:
  - world["last_activity"] with the latest activity entry
"""

from __future__ import annotations

import time
from collections import deque

import numpy as np

from agent.signal_bus import Signal, SignalBus, SignalType, Priority
from services.gemini_client import gemini
from services.backboard_client import memory


# How often (seconds) we sample frames for activity inference
INFER_INTERVAL = 10
# Faster inference when a task is active so completion is detected quickly
INFER_INTERVAL_TASK_ACTIVE = 3

# How long the activity buffer spans (seconds)
BUFFER_DURATION = 90


class ActivitySensor:
    def __init__(self, bus: SignalBus) -> None:
        self._bus = bus
        # Buffer entries: {"time": float, "activity": str, "location_hint": str}
        self._buffer: deque[dict] = deque()
        self._last_infer_time = 0.0

    def process(self, frame: np.ndarray) -> None:
        """Periodically infer activity and emit signal."""
        now = time.time()

        # Prune old buffer entries
        cutoff = now - BUFFER_DURATION
        while self._buffer and self._buffer[0]["time"] < cutoff:
            self._buffer.popleft()

        # Periodically infer activity (faster when a task is active)
        has_task = bool(self._bus.get_world().get("active_task"))
        interval = INFER_INTERVAL_TASK_ACTIVE if has_task else INFER_INTERVAL
        if now - self._last_infer_time >= interval:
            self._last_infer_time = now
            self._infer_and_store(frame)

    def get_recent_activity(self, min_age: float = 10, max_age: float = 60) -> dict | None:
        """Return the most recent activity entry within the given age range."""
        now = time.time()
        for entry in reversed(list(self._buffer)):
            age = now - entry["time"]
            if min_age <= age <= max_age:
                return entry
        return None

    def get_last_activity(self) -> dict | None:
        """Return the most recent activity entry from the buffer."""
        return self._buffer[-1] if self._buffer else None

    def _infer_and_store(self, frame: np.ndarray) -> None:
        """Ask Gemini Vision what the person is doing, then store it."""
        if not gemini:
            return
        try:
            result = gemini.analyze_image(
                frame,
                "In 5-10 words, what activity is this person doing or about to do? "
                "Also, if you see any relevant object (kettle, book, mug, remote, etc.), "
                "note its location. Format: ACTIVITY | OBJECT HINT\n"
                "Example: making tea | kettle on the counter to the right\n"
                "If you can't tell, just say: unknown\n"
                "Only output in that format, nothing else.",
            )
            parts = result.split("|")
            activity = parts[0].strip().lower()
            location_hint = parts[1].strip() if len(parts) > 1 else ""

            entry = {
                "time": time.time(),
                "activity": activity,
                "location_hint": location_hint,
            }
            self._buffer.append(entry)
            memory.store("last_activity", entry)
            memory.append("activity_log", entry)

            # Update world state
            self._bus.update_world("last_activity", entry)

            # Emit signal
            self._bus.emit(Signal(
                type=SignalType.ACTIVITY_INFERRED,
                priority=Priority.LOW,
                data=entry,
            ))

        except Exception as e:
            print(f"[ActivitySensor] Infer error: {e}")
