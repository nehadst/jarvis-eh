"""
Feature 9 — Wandering Guardian

Detects if the wearer has left a known safe zone (home interior) by
classifying the scene with Gemini Vision. If an outdoor / unknown
environment is detected with no known destination, a gentle redirect
is played using ElevenLabs TTS.

Safe zones are set by the caregiver via the dashboard and stored in
Backboard memory. Default safe zones cover typical home rooms.

Detection flow:
  1. Every 10 frames, classify the scene with Gemini Vision
  2. Track the last N=3 readings; if ALL are unsafe → trigger redirect
  3. Escalation tiers (based on consecutive alert count per episode):
       Alert 1 — gentle redirect: "Hey Dad, let's head back home."
       Alert 2 — warmer / more direct (60s later, still wandering)
       Alert 3+ — urgent caregiver alert (wandering_escalated event)
                   in addition to the TTS redirect
  4. Safe zones are reloaded from memory on every trigger so caregiver
     changes take effect immediately without a restart.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Callable

import numpy as np

from config import settings
from services.gemini_client import gemini
from services.elevenlabs_client import tts
from services.backboard_client import memory


DEFAULT_SAFE_ZONES = {
    "kitchen", "living room", "bedroom", "hallway", "bathroom",
    "dining room", "office", "study", "porch", "garage",
}

# How many consecutive "unsafe" scene readings before triggering
UNSAFE_THRESHOLD = 3

# Seconds between repeated alerts within the same wandering episode
ALERT_COOLDOWN = 60

# After this many seconds without an unsafe reading, the episode resets
EPISODE_RESET_SECONDS = 180


class WanderingGuardian:
    def __init__(self, on_event: Callable[[dict], None] | None = None) -> None:
        self.on_event = on_event or (lambda e: None)
        self._scene_history: deque = deque(maxlen=UNSAFE_THRESHOLD)
        self._last_alert_time = 0.0
        self._last_unsafe_time = 0.0   # tracks episode duration
        self._alert_count = 0          # alerts fired in current episode
        self._last_safe_scene = ""     # last room they were safely in

    # ── Public ────────────────────────────────────────────────────────────────

    def process(self, frame: np.ndarray) -> None:
        """Classify the current scene and check for wandering."""
        scene = self._classify_scene(frame)
        if not scene:
            return

        safe_zones = self._load_safe_zones()
        is_safe = any(zone in scene.lower() for zone in safe_zones)

        if is_safe:
            self._last_safe_scene = scene
            # Reset episode if they've been safe long enough after a wandering episode
            if self._last_unsafe_time > 0 and time.time() - self._last_unsafe_time > EPISODE_RESET_SECONDS:
                self._alert_count = 0
                self._last_unsafe_time = 0.0  # anchor reset so next episode starts fresh
                self._scene_history.clear()
        else:
            self._last_unsafe_time = time.time()

        self._scene_history.append(is_safe)

        # Trigger only when all recent readings are unsafe
        if (len(self._scene_history) == UNSAFE_THRESHOLD
                and not any(self._scene_history)):
            self._trigger_redirect(scene)

    # ── Private ───────────────────────────────────────────────────────────────

    def _trigger_redirect(self, scene: str) -> None:
        now = time.time()
        if (now - self._last_alert_time) < ALERT_COOLDOWN:
            return
        self._last_alert_time = now
        self._alert_count += 1

        redirect_text = self._generate_redirect(scene, attempt=self._alert_count)

        if tts and redirect_text:
            tts.speak(redirect_text)

        memory.append("wandering_events", {
            "timestamp": now,
            "scene": scene,
            "message": redirect_text,
            "alert_count": self._alert_count,
        })

        # Base event for all alert tiers
        event = {
            "type": "wandering_detected",
            "scene": scene,
            "message": redirect_text,
            "severity": "gentle",
            "alert_count": self._alert_count,
            "last_safe_scene": self._last_safe_scene,
        }
        self.on_event(event)

        # Alert 3+ also fires an escalated event so the dashboard
        # renders a distinct urgent card
        if self._alert_count >= 3:
            self.on_event({
                "type": "wandering_escalated",
                "scene": scene,
                "message": redirect_text,
                "severity": "urgent",
                "alert_count": self._alert_count,
                "last_safe_scene": self._last_safe_scene,
            })

        # Reset history so we don't fire again on the very next check;
        # the cooldown timer handles re-evaluation
        self._scene_history.clear()

    def _classify_scene(self, frame: np.ndarray) -> str:
        if not gemini:
            return ""
        try:
            return gemini.analyze_image(
                frame,
                "In 2-4 words, describe where this person is. "
                "Examples: kitchen at home, living room, sidewalk outside, "
                "street corner, park, store interior, parking lot. "
                "Only output the location, nothing else.",
            ).lower().strip()
        except Exception:
            return ""

    def _generate_redirect(self, scene: str, attempt: int = 1) -> str:
        """Generate a de-escalating redirect. Tone scales with attempt number."""
        if not gemini:
            return f"Hey {settings.patient_name}, let's head back home."

        if attempt == 1:
            tone_instruction = (
                "This is the first gentle reminder. "
                "Be very warm and casual, like a loving family member."
            )
        elif attempt == 2:
            tone_instruction = (
                "This is a second attempt — they did not respond to the first. "
                "Be a little more direct but still warm and calm. "
                "You can reference going home more specifically."
            )
        else:
            tone_instruction = (
                "This is the third or more attempt — they are still wandering. "
                "Be clear and reassuring. Mention that someone is coming to help."
            )

        try:
            prompt = f"""A person with dementia named {settings.patient_name} is outside and appears to be wandering.
Current scene: {scene}
Last known safe location: {self._last_safe_scene or "home"}

{tone_instruction}

Write one short, warm sentence that:
- Sounds like a caring family member speaking
- Gently redirects them back home
- Does NOT use an alarm, panic, or be commanding
- Is under 15 words

Only output the sentence, nothing else."""
            return gemini.generate(prompt)
        except Exception:
            return f"Hey {settings.patient_name}, let's head back home."

    def _load_safe_zones(self) -> set[str]:
        """Reload safe zones from memory on every call so caregiver edits apply instantly."""
        stored = memory.retrieve("safe_zones")
        if isinstance(stored, list):
            return DEFAULT_SAFE_ZONES | {z.lower() for z in stored}
        return DEFAULT_SAFE_ZONES
