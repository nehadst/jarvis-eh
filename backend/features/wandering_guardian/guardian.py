"""
Feature 9 — Wandering Guardian

Detects if the wearer has left a known safe zone (home interior) by
classifying the scene with Gemini Vision. If an outdoor / unknown
environment is detected with no known destination, a gentle redirect
is played using a family member's voice (via ElevenLabs).

Safe zones are set by the caregiver via the dashboard and stored in memory.
Default safe zones: kitchen, living room, bedroom, hallway, bathroom, porch.

POC flow:
  1. Every 10 frames, classify the scene with Gemini
  2. If scene is "outside" / "street" / "unknown" for N consecutive checks → wandering
  3. Play: "Hey Dad, let's head back home."
  4. Alert the dashboard
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

# Cooldown between alerts
ALERT_COOLDOWN = 120


class WanderingGuardian:
    def __init__(self, on_event: Callable[[dict], None] | None = None) -> None:
        self.on_event = on_event or (lambda e: None)
        self._scene_history: deque = deque(maxlen=UNSAFE_THRESHOLD)
        self._last_alert_time = 0.0
        self._safe_zones = self._load_safe_zones()

    # ── Public ────────────────────────────────────────────────────────────────

    def process(self, frame: np.ndarray) -> None:
        """Classify the current scene and check for wandering."""
        scene = self._classify_scene(frame)
        if not scene:
            return

        is_safe = any(zone in scene.lower() for zone in self._safe_zones)
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

        redirect_text = self._generate_redirect(scene)

        # Play in a familiar/calm voice
        if tts and redirect_text:
            tts.speak(redirect_text)

        memory.append("wandering_events", {
            "timestamp": now,
            "scene": scene,
            "message": redirect_text,
        })

        self.on_event({
            "type": "wandering_detected",
            "scene": scene,
            "message": redirect_text,
            "severity": "gentle",
        })

        # Reset scene history so we don't fire again immediately
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

    def _generate_redirect(self, scene: str) -> str:
        if not gemini:
            return f"Hey {settings.patient_name}, let's head back home."
        try:
            prompt = f"""A person with dementia ({settings.patient_name}) is outside and appears to be wandering.
Current scene: {scene}

Write one short, warm, de-escalating sentence that:
- Sounds like a caring family member
- Gently redirects them back home
- Does NOT use an alarm, panic, or be commanding
- Is under 15 words

Only output the sentence."""
            return gemini.generate(prompt)
        except Exception:
            return f"Hey {settings.patient_name}, let's head back home."

    def _load_safe_zones(self) -> set[str]:
        stored = memory.retrieve("safe_zones")
        if isinstance(stored, list):
            return DEFAULT_SAFE_ZONES | set(stored)
        return DEFAULT_SAFE_ZONES
