"""
Signal Bus — shared in-memory state for the Jarvis agent architecture.

Sensors emit typed signals. The agent reads and consumes them.
World state provides cross-feature awareness (last scene, activity, motion, etc.).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any


class SignalType(Enum):
    FACE_DETECTED = "face_detected"
    STILLNESS = "stillness"
    OSCILLATING_MOTION = "oscillating_motion"
    SCENE_CLASSIFIED = "scene_classified"
    SCENE_UNSAFE = "scene_unsafe"
    ACTIVITY_INFERRED = "activity_inferred"
    MANUAL_GROUNDING = "manual_grounding"
    TASK_SET = "task_set"
    CONVERSATION_LOOP = "conversation_loop"
    CONVERSATION_TOPIC = "conversation_topic"


class Priority(IntEnum):
    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4


# Default TTL per signal type (seconds)
_DEFAULT_TTL: dict[SignalType, float] = {
    SignalType.FACE_DETECTED: 10.0,
    SignalType.STILLNESS: 5.0,
    SignalType.OSCILLATING_MOTION: 5.0,
    SignalType.SCENE_CLASSIFIED: 30.0,
    SignalType.SCENE_UNSAFE: 15.0,
    SignalType.ACTIVITY_INFERRED: 30.0,
    SignalType.MANUAL_GROUNDING: 10.0,
    SignalType.TASK_SET: 60.0,
    SignalType.CONVERSATION_LOOP: 10.0,
    SignalType.CONVERSATION_TOPIC: 10.0,
}

# Priority mapping per signal type
SIGNAL_PRIORITY: dict[SignalType, Priority] = {
    SignalType.SCENE_UNSAFE: Priority.CRITICAL,
    SignalType.FACE_DETECTED: Priority.HIGH,
    SignalType.MANUAL_GROUNDING: Priority.HIGH,
    SignalType.STILLNESS: Priority.NORMAL,
    SignalType.OSCILLATING_MOTION: Priority.NORMAL,
    SignalType.ACTIVITY_INFERRED: Priority.LOW,
    SignalType.SCENE_CLASSIFIED: Priority.LOW,
    SignalType.CONVERSATION_LOOP: Priority.LOW,
    SignalType.CONVERSATION_TOPIC: Priority.LOW,
    SignalType.TASK_SET: Priority.LOW,
}


@dataclass
class Signal:
    type: SignalType
    priority: Priority
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)
    ttl: float = 0.0  # 0 = use default
    consumed: bool = False

    def __post_init__(self) -> None:
        if self.ttl == 0.0:
            self.ttl = _DEFAULT_TTL.get(self.type, 10.0)

    @property
    def expired(self) -> bool:
        return time.time() > self.timestamp + self.ttl


class SignalBus:
    """Thread-safe signal bus + world state for the Jarvis agent architecture."""

    def __init__(self) -> None:
        self._signals: list[Signal] = []
        self._lock = threading.Lock()

        self._world: dict[str, Any] = {
            "last_scene": "unknown",
            "last_activity": None,
            "motion_level": 0,
            "last_spoken_time": 0.0,
            "active_task": None,
            "active_task_set_by": None,
        }
        self._world_lock = threading.Lock()

    # ── Sensor writes ──────────────────────────────────────────────────────

    def emit(self, signal: Signal) -> None:
        """Sensors call this to publish a new signal."""
        with self._lock:
            self._signals.append(signal)

    def update_world(self, key: str, value: Any) -> None:
        """Sensors update persistent world state."""
        with self._world_lock:
            self._world[key] = value

    # ── Agent reads ────────────────────────────────────────────────────────

    def get_pending_signals(self) -> list[Signal]:
        """Return unconsumed, non-expired signals sorted by priority (lowest int = highest priority)."""
        with self._lock:
            # Prune expired and consumed signals
            self._signals = [s for s in self._signals if not s.expired and not s.consumed]
            pending = [s for s in self._signals if not s.consumed]
            return sorted(pending, key=lambda s: (s.priority, s.timestamp))

    def consume(self, signal: Signal) -> None:
        """Mark a signal as handled."""
        signal.consumed = True

    def get_world(self) -> dict[str, Any]:
        """Return a snapshot of the current world state."""
        with self._world_lock:
            return dict(self._world)
