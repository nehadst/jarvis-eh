"""
Confusion Detector — tiered confusion detection.

Aggregates evidence from multiple sensors (motion, scene, activity, audio)
to detect confusion with HIGH / MEDIUM / LOW confidence tiers.

HIGH CONFIDENCE (act immediately):
  - Repeated question detected in transcript
  - 45s in same room with no activity change

MEDIUM CONFIDENCE (flag, wait 15s, then act):
  - Sundowning window (4-7pm) + 30s inactivity
  - Stillness + 30s in same room

LOW CONFIDENCE (don't act alone):
  - Stillness alone
  - Oscillating motion alone

Emits CONFUSION signal when confidence threshold is met.
"""

from __future__ import annotations

import re
import time
from collections import deque
from datetime import datetime

from agent.signal_bus import Priority, Signal, SignalBus, SignalType
from services.backboard_client import memory


# How often the detector runs its checks (seconds)
CHECK_INTERVAL = 5

# Minimum time between CONFUSION signals
CONFUSION_EMIT_COOLDOWN = 30

# HIGH confidence thresholds
HIGH_INACTIVITY_SCENE_SECS = 45     # 45s same room + no activity change
HIGH_INACTIVITY_ACTIVITY_SECS = 45

# When in a safe zone, require much longer inactivity before triggering
# (being still at home for a few minutes is perfectly normal)
SAFE_ZONE_HIGH_SECS = 180           # 3 minutes in a safe zone
SAFE_ZONE_MEDIUM_SECS = 120         # 2 minutes in a safe zone

# MEDIUM confidence thresholds
MEDIUM_INACTIVITY_SECS = 30         # 30s
MEDIUM_CONFIRM_WAIT = 15            # wait 15s before acting on medium

# Default safe zones (mirrors scene_sensor.py)
_SAFE_ZONES = {
    "kitchen", "living room", "bedroom", "hallway", "bathroom",
    "dining room", "office", "study", "porch", "garage",
}

# Sundowning window (4pm - 7pm)
SUNDOWN_START_HOUR = 16
SUNDOWN_END_HOUR = 19


class ConfusionDetector:
    def __init__(self, bus: SignalBus) -> None:
        self._bus = bus

        # Scene tracking
        self._current_scene: str | None = None
        self._scene_entered_at = 0.0

        # Activity tracking
        self._last_activity_text: str | None = None
        self._last_activity_change_time = 0.0

        # Medium confidence pending flag
        self._pending_medium: dict | None = None

        # Internal timing
        self._last_check_time = 0.0
        self._last_confusion_emit_time = 0.0

    def tick(self) -> None:
        """Called each AI worker cycle. Checks world state for confusion."""
        now = time.time()

        # Only check periodically
        if (now - self._last_check_time) < CHECK_INTERVAL:
            return
        self._last_check_time = now

        # Respect emit cooldown
        if (now - self._last_confusion_emit_time) < CONFUSION_EMIT_COOLDOWN:
            return

        world = self._bus.get_world()

        # ── Track scene duration ────────────────────────────────────────
        scene = world.get("last_scene", "unknown")
        if not self._is_similar(scene, self._current_scene):
            self._current_scene = scene
            self._scene_entered_at = now
            self._pending_medium = None  # reset on scene change
        scene_duration = now - self._scene_entered_at

        # ── Track activity staleness ────────────────────────────────────
        # Use fuzzy matching — "sitting at desk" vs "person at desk" should
        # NOT count as a change. Only truly different activities reset the timer.
        last_activity = world.get("last_activity")
        if last_activity and isinstance(last_activity, dict):
            activity_text = last_activity.get("activity", "unknown")
            if (activity_text != "unknown"
                    and not self._is_similar(activity_text, self._last_activity_text)):
                self._last_activity_text = activity_text
                self._last_activity_change_time = now
                self._pending_medium = None  # reset on activity change

        activity_age = (
            now - self._last_activity_change_time
            if self._last_activity_change_time
            else float("inf")
        )

        # ── Read motion state ───────────────────────────────────────────
        is_still = world.get("is_still", False)
        is_oscillating = world.get("is_oscillating", False)

        # ── Safe zone awareness ─────────────────────────────────────────
        # Being still/inactive at home is normal — use longer thresholds
        in_safe_zone = self._is_in_safe_zone(scene)
        high_threshold = SAFE_ZONE_HIGH_SECS if in_safe_zone else HIGH_INACTIVITY_SCENE_SECS
        medium_threshold = SAFE_ZONE_MEDIUM_SECS if in_safe_zone else MEDIUM_INACTIVITY_SECS

        # ══════════════════════════════════════════════════════════════════
        # HIGH CONFIDENCE — act immediately
        # ══════════════════════════════════════════════════════════════════

        # 1. Repeated question in recent transcript
        if self._detect_repeated_question(world):
            self._emit(now, "high", "repeated_question",
                       "Same question detected multiple times in conversation")
            return

        # 2. Extended time in same room with no meaningful activity change
        if (scene_duration >= high_threshold
                and activity_age >= high_threshold):
            self._emit(now, "high", "extended_inactivity",
                       f"In {scene} for {int(scene_duration)}s, "
                       f"no activity change for {int(activity_age)}s")
            return

        # ══════════════════════════════════════════════════════════════════
        # MEDIUM CONFIDENCE — flag, wait, then act
        # ══════════════════════════════════════════════════════════════════

        hour = datetime.now().hour
        is_sundowning = SUNDOWN_START_HOUR <= hour <= SUNDOWN_END_HOUR

        medium_triggered = False

        # 1. Sundowning + inactivity
        if (is_sundowning
                and scene_duration >= medium_threshold
                and activity_age >= medium_threshold):
            medium_triggered = True

        # 2. Stillness + extended time in same room
        if is_still and scene_duration >= medium_threshold:
            medium_triggered = True

        # 3. Oscillating motion + 1+ min in same room (pacing in a room)
        if is_oscillating and scene_duration >= 60:
            medium_triggered = True

        if medium_triggered:
            if self._pending_medium is None:
                # First time flagging — start the wait timer
                self._pending_medium = {"time": now}
                print(f"[ConfusionDetector] MEDIUM flagged — waiting {MEDIUM_CONFIRM_WAIT}s to confirm")
            elif (now - self._pending_medium["time"]) >= MEDIUM_CONFIRM_WAIT:
                # Waited long enough — act
                self._emit(now, "medium", "confirmed_inactivity",
                           f"In {scene} for {int(scene_duration)}s"
                           + (" (sundowning window)" if is_sundowning else "")
                           + (" + still" if is_still else "")
                           + (" + pacing" if is_oscillating else ""))
                self._pending_medium = None
            return

        # Conditions no longer met — clear pending flag
        if self._pending_medium and not medium_triggered:
            self._pending_medium = None

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _is_in_safe_zone(scene: str) -> bool:
        """Check if the current scene is a known safe zone (home interior)."""
        if not scene or scene == "unknown":
            return False
        scene_lower = scene.lower()
        # Load custom zones from memory
        stored = memory.retrieve("safe_zones")
        zones = _SAFE_ZONES.copy()
        if isinstance(stored, list):
            zones = zones | {z.lower() for z in stored}
        excluded = memory.retrieve("excluded_safe_zones")
        if isinstance(excluded, list):
            zones = zones - {z.lower() for z in excluded}
        return any(zone in scene_lower for zone in zones)

    @staticmethod
    def _is_similar(text_a: str | None, text_b: str | None) -> bool:
        """Check if two short descriptions are essentially the same.

        Uses word overlap — 'sitting at desk' vs 'person sitting at desk'
        should be considered similar (not a meaningful change).
        50% overlap threshold to be lenient.
        """
        if text_a is None or text_b is None:
            return False
        words_a = set(text_a.lower().split())
        words_b = set(text_b.lower().split())
        if not words_a or not words_b:
            return False
        overlap = len(words_a & words_b) / min(len(words_a), len(words_b))
        return overlap >= 0.5

    def _detect_repeated_question(self, world: dict) -> bool:
        """Check if the same question appears 2+ times in recent transcript."""
        entries = world.get("transcript_entries", [])
        if len(entries) < 2:
            return False

        now = time.time()
        # Only check entries from the last 2 minutes
        recent = [e["text"].lower().strip() for e in entries
                  if now - e.get("time", 0) < 120 and len(e.get("text", "")) > 10]

        if len(recent) < 2:
            return False

        # Check for high word overlap between any two recent utterances
        for i in range(len(recent)):
            for j in range(i + 1, len(recent)):
                words_i = set(recent[i].split())
                words_j = set(recent[j].split())
                if len(words_i) < 3 or len(words_j) < 3:
                    continue
                overlap = len(words_i & words_j) / min(len(words_i), len(words_j))
                if overlap >= 0.7:
                    return True
        return False

    def _emit(self, now: float, confidence: str, reason: str, details: str) -> None:
        """Emit a CONFUSION signal to the bus, then reset tracking.

        Resetting prevents the detector from immediately re-firing on
        the next tick (same conditions would still be true otherwise).
        It must see FRESH evidence of confusion to fire again.
        """
        self._last_confusion_emit_time = now

        # Reset tracking so we need NEW evidence to fire again
        self._scene_entered_at = now
        self._last_activity_change_time = now
        self._pending_medium = None

        priority = Priority.HIGH if confidence == "high" else Priority.NORMAL
        self._bus.emit(Signal(
            type=SignalType.CONFUSION,
            priority=priority,
            data={
                "confidence": confidence,
                "reason": reason,
                "details": details,
            },
        ))
        print(f"[ConfusionDetector] {confidence.upper()}: {reason} — {details}")
