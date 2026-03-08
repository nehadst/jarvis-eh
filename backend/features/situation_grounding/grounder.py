"""
Feature 3 — Situation Grounding (Nehad)

Detects signs of confusion or disorientation in the live feed and
plays a calm grounding message: "You're at home in your living room.
It's Thursday afternoon. David is in the kitchen making lunch."

Confusion signals detected:
  - Repeated head turning (motion heuristics via frame diff)
  - Slow / no movement for an extended period (stopped, looking lost)
  - Caregiver manually triggers via dashboard

Also handles caregiver-set tasks:
  "The patient should go to the fridge and grab an orange"
  → grounding message includes the task reminder
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


# How often (seconds) the same grounding message can repeat
GROUNDING_COOLDOWN = 60

# Motion delta threshold (sum of all 0/255 threshold pixels).
# np.sum(thresh) = changed_pixel_count × 255, so 75_000 ≈ ~300 changed pixels
# after a 21×21 Gaussian blur — below this the scene is essentially still.
MOTION_THRESHOLD = 75_000

# How many consecutive low-motion frames before we flag as "stopped/lost"
STILL_FRAME_LIMIT = 20  # ~10 seconds at 2 FPS

# How many above/below threshold transitions in the motion history = head-turning
OSCILLATION_TRANSITIONS = 4  # 4 transitions in 10 frames (~5s) = confused pacing


class SituationGrounder:
    def __init__(self, on_event: Callable[[dict], None] | None = None) -> None:
        self.on_event = on_event or (lambda e: None)
        self._prev_frame: np.ndarray | None = None
        self._still_frames = 0
        self._motion_history: deque = deque(maxlen=10)
        self._last_grounded = 0.0
        self._active_task: str | None = None
        self._active_task_set_by: str = "caregiver"

        # Restore any task that was set before a server restart
        saved = memory.retrieve("active_patient_task")
        if saved and isinstance(saved, dict) and saved.get("task"):
            self._active_task = saved["task"]
            self._active_task_set_by = saved.get("set_by", "caregiver")

    # ── Public ────────────────────────────────────────────────────────────────

    def set_active_task(self, task: str, set_by: str = "caregiver") -> None:
        """Called by the orchestrator when a caregiver adds a task via the dashboard."""
        self._active_task = task
        self._active_task_set_by = set_by
        memory.store("active_patient_task", {"task": task, "set_by": set_by})

    def clear_active_task(self) -> None:
        """Mark the current task as done and remove it."""
        self._active_task = None
        self._active_task_set_by = "caregiver"
        memory.store("active_patient_task", {})

    def process(self, frame: np.ndarray) -> None:
        """
        Analyse the frame for confusion/disorientation signals.
        Fires a grounding event if triggered.
        """
        confusion_detected = self._analyse_motion(frame)
        if confusion_detected:
            self._trigger_grounding(frame)

    def trigger_manual(self, frame: np.ndarray) -> None:
        """Caregiver manually triggers a grounding message from the dashboard."""
        self._trigger_grounding(frame, force=True)

    # ── Private ───────────────────────────────────────────────────────────────

    def _analyse_motion(self, frame: np.ndarray) -> bool:
        """
        Returns True when the heuristic detects a confusion-like motion pattern.
        Patterns:
          1. Very still for too long (person is stuck / lost)
          2. Rapid back-and-forth motion oscillation (head turning, pacing)
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if self._prev_frame is None:
            self._prev_frame = gray
            return False

        diff = cv2.absdiff(self._prev_frame, gray)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        motion_score = int(np.sum(thresh))

        self._motion_history.append(motion_score)
        self._prev_frame = gray

        # ── Signal 1: sustained stillness ────────────────────────────────
        if motion_score < MOTION_THRESHOLD:
            self._still_frames += 1
        else:
            self._still_frames = 0

        if self._still_frames >= STILL_FRAME_LIMIT:
            self._still_frames = 0  # reset so it doesn't fire every frame
            return True

        # ── Signal 2: oscillating motion (back-and-forth head turning) ───────
        # Count how many times the motion score crosses the threshold boundary.
        # e.g. still → moving → still → moving → still = 4 transitions = confused pacing.
        if len(self._motion_history) == 10:
            above = [s > MOTION_THRESHOLD for s in self._motion_history]
            transitions = sum(1 for i in range(1, len(above)) if above[i] != above[i - 1])
            if transitions >= OSCILLATION_TRANSITIONS:
                return True

        return False

    def _trigger_grounding(self, frame: np.ndarray, force: bool = False) -> None:
        """Build and deliver the grounding message."""
        now = time.time()
        if not force and (now - self._last_grounded) < GROUNDING_COOLDOWN:
            return
        self._last_grounded = now

        # Get scene context
        scene = self._classify_scene(frame)
        now_dt = datetime.now()
        time_str = now_dt.strftime("%A, %B %d · %I:%M %p").replace(" 0", " ")  # cross-platform
        # Retrieve any household context from memory
        household_context = memory.retrieve("household_context") or {}

        # Pull cross-feature context from Backboard semantic memory
        recent_context = memory.query(
            f"In 2-3 brief facts, what has {settings.patient_name} been doing "
            "in the last hour? Include any visitors, activities, and tasks."
        )

        # Build Gemini prompt
        grounding_text = self._generate_grounding_message(scene, time_str, household_context, recent_context)

        # Play via ElevenLabs
        if tts and grounding_text:
            tts.speak(grounding_text)

        # Persist event
        memory.append("grounding_events", {
            "timestamp": now,
            "scene": scene,
            "message": grounding_text,
        })

        self.on_event({
            "type": "situation_grounding",
            "scene": scene,
            "time": time_str,
            "task": self._active_task,
            "message": grounding_text,
        })

    def _classify_scene(self, frame: np.ndarray) -> str:
        """Ask Gemini Vision to classify the room / environment."""
        if not gemini:
            return "a familiar room"
        try:
            result = gemini.analyze_image(
                frame,
                "In one or two words, what room or environment is this? "
                "Examples: kitchen, living room, bedroom, hallway, outdoors, bathroom. "
                "Only output the room name, nothing else.",
            )
            return result.lower().strip()
        except Exception:
            return "a familiar room"

    def _generate_grounding_message(
        self, scene: str, time_str: str, household_context: dict, recent_context: str = ""
    ) -> str:
        """Generate a calm grounding message via Gemini."""
        who_is_home = household_context.get("who_is_home", "")
        if self._active_task:
            task_line = f"\nCurrent task set by {self._active_task_set_by}: {self._active_task}"
        else:
            task_line = ""
        context_line = f"\nRecent events: {recent_context}" if recent_context else ""

        if not gemini:
            base = f"You're at home in the {scene}. It's {time_str}."
            if self._active_task:
                base += f" {self._active_task_set_by} asked you to {self._active_task}."
            return base

        prompt = f"""You are a gentle, warm AI companion helping {settings.patient_name}, a person with dementia, feel calm and oriented.

Current scene: {scene}
Current time: {time_str}
Who is home: {who_is_home if who_is_home else "unknown"}{task_line}{context_line}

Write a calm, grounding message (1-3 sentences) that:
- Opens by warmly telling them where they are (use their name once)
- Tells them what time / day it is in natural language ("It's Thursday afternoon")
- If someone is home, mentions them naturally ("David is in the kitchen")
- If there's a task, gently reminds them using the name of who set it ("Your daughter Sarah asked you to...")
- Sounds like a caring family member speaking softly — warm and natural, never robotic or clinical
- Never mentions dementia, memory, or confusion
- Is under 45 words

Only output the message text. Nothing else."""

        try:
            return gemini.generate(prompt)
        except Exception:
            return f"You're in the {scene}. It's {time_str}. Everything is okay."
