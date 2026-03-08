"""
Scene Sensor — unified scene classification.

Consolidates duplicate Gemini Vision calls from grounder.py and guardian.py
into a single sensor. One Gemini call per cycle instead of two.

Emits:
  - SCENE_CLASSIFIED with every classification result
  - SCENE_UNSAFE after 3 consecutive unsafe readings (wandering)
Updates:
  - world["last_scene"] with the classified scene name
"""

from __future__ import annotations

from collections import deque

import numpy as np

from agent.signal_bus import Signal, SignalBus, SignalType, Priority
from services.gemini_client import gemini
from services.backboard_client import memory


DEFAULT_SAFE_ZONES = {
    "kitchen", "living room", "bedroom", "hallway", "bathroom",
    "dining room", "office", "study", "porch", "garage",
}

# How many consecutive unsafe readings before triggering wandering
UNSAFE_THRESHOLD = 3


class SceneSensor:
    def __init__(self, bus: SignalBus) -> None:
        self._bus = bus
        self._scene_history: deque[bool] = deque(maxlen=UNSAFE_THRESHOLD)

    def process(self, frame: np.ndarray) -> None:
        """Classify the current scene via Gemini Vision."""
        scene = self._classify_scene(frame)
        if not scene:
            return

        # Update world state
        self._bus.update_world("last_scene", scene)

        # Emit classification signal
        self._bus.emit(Signal(
            type=SignalType.SCENE_CLASSIFIED,
            priority=Priority.LOW,
            data={"scene": scene},
        ))

        # Check safety — reload zones every time so caregiver edits apply instantly
        safe_zones = self._load_safe_zones()
        is_safe = any(zone in scene.lower() for zone in safe_zones)
        self._scene_history.append(is_safe)

        # Trigger wandering only when all recent readings are unsafe
        if (len(self._scene_history) == UNSAFE_THRESHOLD
                and not any(self._scene_history)):
            self._bus.emit(Signal(
                type=SignalType.SCENE_UNSAFE,
                priority=Priority.CRITICAL,
                data={"scene": scene},
            ))
            self._scene_history.clear()

    def _classify_scene(self, frame: np.ndarray) -> str:
        """Single Gemini Vision call that serves both grounding and wandering."""
        if not gemini:
            return "a familiar room"
        try:
            result = gemini.analyze_image(
                frame,
                "In 2-4 words, describe where this person is. "
                "Examples: kitchen at home, living room, sidewalk outside, "
                "street corner, park, store interior, parking lot. "
                "Only output the location, nothing else.",
            )
            return result.lower().strip()
        except Exception:
            return "a familiar room"

    def _load_safe_zones(self) -> set[str]:
        stored = memory.retrieve("safe_zones")
        excluded = memory.retrieve("excluded_safe_zones")
        zones = DEFAULT_SAFE_ZONES.copy()
        if isinstance(stored, list):
            zones = zones | {z.lower() for z in stored}
        if isinstance(excluded, list):
            zones = zones - {z.lower() for z in excluded}
        return zones
