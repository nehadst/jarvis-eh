"""
Feature 4 — Activity Continuity (Hashim)

Maintains a rolling 60-second buffer of inferred activities from the live feed.
When a confusion signal is detected (via the grounder or motion heuristics),
retrieves the last known activity and generates a gentle reminder:

  "You were making tea. The kettle is on the counter to your left."
  "You were reading your book. It's on the arm of your chair."

Activity inference:
  - Sends every Nth frame to Gemini Vision with a structured prompt
  - Returns a short activity description: "making tea", "watching TV", "reading"
  - Stored in a time-stamped rolling buffer

Object context (optional future improvement):
  - YOLOv8 can be added here for object detection to enrich descriptions
"""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime
from typing import Callable

import cv2
import numpy as np

from config import settings
from services.gemini_client import gemini
from services.elevenlabs_client import tts
from services.backboard_client import memory


# How often (seconds) we sample frames for activity inference
INFER_INTERVAL = 10  # every 10s

# Cooldown before repeating the same continuity reminder
REMINDER_COOLDOWN = 45

# How long the activity buffer spans (seconds)
BUFFER_DURATION = 90


class ActivityTracker:
    def __init__(self, on_event: Callable[[dict], None] | None = None) -> None:
        self.on_event = on_event or (lambda e: None)
        # Buffer entries: {"time": float, "activity": str, "location_hint": str}
        self._buffer: deque = deque()
        self._active_task: str | None = None
        self._last_infer_time = 0.0
        self._last_reminder_time = 0.0
        self._confusion_count = 0
        self._prev_frame: np.ndarray | None = None

    # ── Public ────────────────────────────────────────────────────────────────

    def set_active_task(self, task: str) -> None:
        self._active_task = task

    def process(self, frame: np.ndarray) -> None:
        """
        Called on every frame.
        1. Periodically infers the current activity and stores it.
        2. Detects confusion via motion heuristics.
        3. On confusion, delivers a continuity reminder.
        """
        now = time.time()

        # Prune old buffer entries
        cutoff = now - BUFFER_DURATION
        while self._buffer and self._buffer[0]["time"] < cutoff:
            self._buffer.popleft()

        # Periodically infer activity
        if now - self._last_infer_time >= INFER_INTERVAL:
            self._last_infer_time = now
            self._infer_and_store(frame)

        # Detect confusion via stillness
        if self._detect_confusion(frame):
            self._confusion_count += 1
            if self._confusion_count >= 3 and (now - self._last_reminder_time) >= REMINDER_COOLDOWN:
                self._confusion_count = 0
                self._deliver_reminder()
        else:
            self._confusion_count = max(0, self._confusion_count - 1)

    def get_last_activity(self) -> dict | None:
        """Return the most recent activity entry from the buffer."""
        return self._buffer[-1] if self._buffer else None

    # ── Private ───────────────────────────────────────────────────────────────

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

        except Exception as e:
            print(f"[ActivityTracker] Infer error: {e}")

    def _detect_confusion(self, frame: np.ndarray) -> bool:
        """
        Simple frame-diff motion heuristic.
        Extended still period → person is confused / lost.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        if self._prev_frame is None:
            self._prev_frame = gray
            return False
        diff = cv2.absdiff(self._prev_frame, gray)
        self._prev_frame = gray
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        return int(np.sum(thresh)) < 2000  # very still

    def _deliver_reminder(self) -> None:
        """Find the activity from ~10-30 seconds ago and deliver a reminder."""
        now = time.time()
        self._last_reminder_time = now

        # Look for an activity 10-30s ago (before confusion started)
        target_activity = None
        for entry in reversed(list(self._buffer)):
            age = now - entry["time"]
            if 10 <= age <= 60:
                target_activity = entry
                break

        if not target_activity:
            return

        activity = target_activity["activity"]
        location_hint = target_activity["location_hint"]

        reminder_text = self._generate_reminder(activity, location_hint)

        if tts and reminder_text:
            tts.speak(reminder_text)

        memory.append("continuity_reminders", {
            "timestamp": now,
            "activity": activity,
            "message": reminder_text,
        })

        self.on_event({
            "type": "activity_continuity",
            "activity": activity,
            "location_hint": location_hint,
            "message": reminder_text,
        })

    def _generate_reminder(self, activity: str, location_hint: str) -> str:
        """Generate a natural-sounding continuity reminder."""
        location_line = f" ({location_hint})" if location_hint else ""

        if not gemini:
            return f"You were {activity}.{location_line}"

        prompt = f"""A person with dementia has become confused and stopped what they were doing.

Last known activity: {activity}{location_line}
Active caregiver task: {self._active_task or "none"}
Patient's name: {settings.patient_name}

Write a gentle 1-2 sentence reminder that:
- Reminds them what they were doing
- If there's a location hint, tells them where the object is
- Is warm, calm, and natural
- Under 25 words

Only output the reminder text."""

        try:
            return gemini.generate(prompt)
        except Exception:
            return f"You were {activity}.{location_line}"
