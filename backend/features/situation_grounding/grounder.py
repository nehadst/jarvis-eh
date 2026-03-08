"""
Feature 3 — Situation Grounding (Nehad)

Monitors the egocentric camera feed (patient wears Meta glasses) for signs of
confusion or task drift, and responds with gentle audio check-ins — never
assuming confusion, always asking.

Two parallel monitors:
  A. Confusion check-in: egocentric scan pattern (optical flow) + LLM scene
     assessment → if both signal confusion, plays "are you doing okay?"
  B. Task monitoring: if a caregiver task is set, silently checks whether the
     patient's view is relevant to the task. If off-task too long → gentle reminder.

Full grounding messages (orienting speech) are caregiver-manual only via
POST /api/grounding/trigger → trigger_manual().
"""

from __future__ import annotations

import json
import time
from collections import deque
from datetime import datetime
from enum import Enum
from typing import Callable

import cv2
import numpy as np

from config import settings
from services.gemini_client import gemini
from services.elevenlabs_client import tts
from services.backboard_client import memory


# ── State machine ─────────────────────────────────────────────────────────────

class _State(Enum):
    NORMAL = "normal"
    CHECKING_IN = "checking_in"    # cooldown after confusion check-in
    TASK_REMINDING = "task_remind" # cooldown after task reminder


# ── Constants ─────────────────────────────────────────────────────────────────

# How often (seconds) the manual grounding message can repeat
GROUNDING_COOLDOWN = 60

# Egocentric scan pattern: direction reversals in SCAN_WINDOW frames = scanning
SCAN_DIRECTION_CHANGES = 5
SCAN_WINDOW = 10

# LLM confidence → suspicion score weight
CONFIDENCE_WEIGHTS: dict[str, int] = {"low": 0, "medium": 1, "high": 2}

# Weighted score (scan + LLM) needed before check-in fires
CHECKIN_THRESHOLD = 3

# Seconds before confusion check-in can repeat
CHECKIN_COOLDOWN = 120

# Seconds patient can be off-task before reminder fires
TASK_DRIFT_LIMIT = 60

# Seconds before task reminder can repeat
TASK_REMINDER_COOLDOWN = 90


class SituationGrounder:
    def __init__(self, on_event: Callable[[dict], None] | None = None) -> None:
        self.on_event = on_event or (lambda e: None)
        self._last_grounded = 0.0
        self._active_task: str | None = None
        self._active_task_set_by: str = "caregiver"

        # State machine
        self._state: _State = _State.NORMAL
        self._suspicion_score: int = 0
        self._last_checkin: float = 0.0

        # Task drift tracking
        self._last_on_task_time: float = time.time()
        self._last_task_reminder: float = 0.0

        # Egocentric scan tracking (optical flow)
        self._prev_gray: np.ndarray | None = None
        self._direction_history: deque = deque(maxlen=SCAN_WINDOW)

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
        self._last_on_task_time = time.time()  # reset drift clock
        self._last_task_reminder = 0.0          # allow reminder soon after task is set
        memory.store("active_patient_task", {"task": task, "set_by": set_by})

    def clear_active_task(self) -> None:
        """Mark the current task as done and remove it."""
        self._active_task = None
        self._active_task_set_by = "caregiver"
        memory.store("active_patient_task", {})

    def process(self, frame: np.ndarray) -> None:
        """
        Two parallel monitors:
          B (higher priority): task engagement check when a task is active
          A: confusion scan pattern + LLM egocentric assessment
        Fires gentle audio check-ins only — never assumes confusion, never auto-grounds.
        """
        now = time.time()

        # ── Monitor B: Task Engagement ────────────────────────────────────────
        if self._active_task and self._state == _State.NORMAL:
            on_task = self._check_task_engagement(frame)
            if on_task:
                self._last_on_task_time = now
            elif now - self._last_on_task_time >= TASK_DRIFT_LIMIT:
                if now - self._last_task_reminder >= TASK_REMINDER_COOLDOWN:
                    self._do_task_reminder()
                    self._last_task_reminder = now
                    self._last_on_task_time = now  # reset drift clock
                    self._state = _State.TASK_REMINDING

        # ── Monitor A: Confusion Check-In ─────────────────────────────────────
        if self._state == _State.NORMAL:
            scan_active = self._detect_scan_pattern(frame)
            assessment = self._assess_confusion_egocentric(frame)
            confused_llm = assessment.get("confused", False)
            weight = CONFIDENCE_WEIGHTS.get(assessment.get("confidence", "low"), 0) if confused_llm else 0
            signal_weight = weight if (scan_active and confused_llm) else 0

            if signal_weight > 0:
                self._suspicion_score += signal_weight
                if self._suspicion_score >= CHECKIN_THRESHOLD:
                    self._do_checkin()
                    self._state = _State.CHECKING_IN
                    self._last_checkin = now
                    self._suspicion_score = 0
            else:
                self._suspicion_score = max(0, self._suspicion_score - 1)

        # ── Cooldown exits ────────────────────────────────────────────────────
        elif self._state == _State.CHECKING_IN:
            if now - self._last_checkin >= CHECKIN_COOLDOWN:
                self._state = _State.NORMAL
                self._suspicion_score = 0

        elif self._state == _State.TASK_REMINDING:
            if now - self._last_task_reminder >= TASK_REMINDER_COOLDOWN:
                self._state = _State.NORMAL

    def trigger_manual(self, frame: np.ndarray) -> None:
        """Caregiver manually triggers a full grounding message from the dashboard."""
        self._trigger_grounding(frame, force=True)

    # ── Monitor A helpers ─────────────────────────────────────────────────────

    def _detect_scan_pattern(self, frame: np.ndarray) -> bool:
        """
        Detect repeated left-right scanning from the egocentric camera using
        horizontal optical flow. Returns True if direction has reversed
        SCAN_DIRECTION_CHANGES times in the last SCAN_WINDOW frames.
        Clinically validated: high turn rate = wandering/confusion indicator.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (160, 90))  # small for speed

        if self._prev_gray is None:
            self._prev_gray = gray
            return False

        flow = cv2.calcOpticalFlowFarneback(
            self._prev_gray, gray, None,
            pyr_scale=0.5, levels=3, winsize=15,
            iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
        )
        self._prev_gray = gray

        mean_x = float(np.mean(flow[..., 0]))
        if abs(mean_x) < 0.3:  # ignore micro-jitter
            return False

        self._direction_history.append(mean_x > 0)  # True=right, False=left

        if len(self._direction_history) < SCAN_WINDOW:
            return False

        reversals = sum(
            1 for i in range(1, len(self._direction_history))
            if self._direction_history[i] != self._direction_history[i - 1]
        )
        return reversals >= SCAN_DIRECTION_CHANGES

    def _assess_confusion_egocentric(self, frame: np.ndarray) -> dict:
        """
        Ask the LLM to assess the egocentric frame for confusion context cues:
        transitional spaces, aimless framing, no task engagement.
        Returns {"confused": bool, "confidence": "low"|"medium"|"high"}.
        """
        if not gemini:
            return {"confused": False, "confidence": "low"}
        try:
            prompt = (
                "This is a first-person camera view worn by a dementia patient on their glasses.\n"
                "Assess whether the scene suggests the wearer might be confused or disoriented.\n\n"
                "Look for:\n"
                "- Camera is in a doorway, hallway, or junction (no clear destination visible)\n"
                "- No clear task engagement (no hands on objects, no food prep, no TV)\n"
                "- Scene appears aimless — just open space, not oriented toward anything\n\n"
                "Respond with ONLY valid JSON (no markdown, no explanation):\n"
                "{\"confused\": true or false, \"confidence\": \"low\" or \"medium\" or \"high\"}"
            )
            raw = gemini.analyze_image(frame, prompt)
            clean = raw.strip().strip("```json").strip("```").strip()
            return json.loads(clean)
        except Exception as e:
            print(f"[Grounder] Egocentric assessment failed: {e}")
            return {"confused": False, "confidence": "low"}

    def _do_checkin(self) -> None:
        """Play a gentle 'are you okay?' — no grounding, no assumptions."""
        name = settings.patient_name.split()[0]
        msg = f"Hey {name}, are you doing okay? Do you need any help?"
        if tts:
            tts.speak(msg)
        print("[Grounder] Confusion check-in played.")
        self.on_event({"type": "confusion_checkin", "message": msg})

    # ── Monitor B helpers ─────────────────────────────────────────────────────

    def _check_task_engagement(self, frame: np.ndarray) -> bool:
        """
        Silently ask the LLM whether the first-person view is relevant to
        the active task. Returns True (on-task or uncertain), False (clearly
        off-task at medium/high confidence). Fails safe to True.
        """
        if not gemini or not self._active_task:
            return True
        try:
            prompt = (
                f"The patient has been asked to: \"{self._active_task}\"\n\n"
                "This is their first-person camera view (they wear the camera on glasses).\n"
                "Is what they're currently looking at relevant to completing this task?\n"
                "Consider: relevant objects, locations, or actions that would help them do it.\n\n"
                "Respond with ONLY valid JSON (no markdown):\n"
                "{\"on_task\": true or false, \"confidence\": \"low\" or \"medium\" or \"high\"}"
            )
            raw = gemini.analyze_image(frame, prompt)
            clean = raw.strip().strip("```json").strip("```").strip()
            result = json.loads(clean)
            if not result.get("on_task", True) and result.get("confidence", "low") in ("medium", "high"):
                return False
            return True
        except Exception as e:
            print(f"[Grounder] Task engagement check failed: {e}")
            return True  # fail safe: don't remind if unsure

    def _do_task_reminder(self) -> None:
        """Play a gentle task reminder that also asks if they need help."""
        name = settings.patient_name.split()[0]
        setter = self._active_task_set_by
        task = self._active_task
        msg = f"Hey {name}, {setter} asked you to {task}. Are you still working on that? Do you need any help?"
        if tts:
            tts.speak(msg)
        print("[Grounder] Task reminder played.")
        self.on_event({"type": "task_reminder", "task": task, "message": msg})

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
- If "Current task" is set, gently remind them of ONLY that task using the name of who set it ("Dr. Chen asked you to...")
- Do NOT mention tasks or reminders from "Recent events" — that is background context only
- Sounds like a caring family member speaking softly — warm and natural, never robotic or clinical
- Never mentions dementia, memory, or confusion
- Is under 45 words

Only output the message text. Nothing else."""

        try:
            return gemini.generate(prompt)
        except Exception:
            return f"You're in the {scene}. It's {time_str}. Everything is okay."
