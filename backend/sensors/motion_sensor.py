"""
Motion Sensor — unified motion analysis.

Consolidates duplicate frame-diff code from grounder.py and tracker.py
into a single sensor with consistent thresholds.

Emits:
  - STILLNESS when the person has been still for 20+ frames
  - OSCILLATING_MOTION when back-and-forth pacing is detected
Updates:
  - world["motion_level"] with the current motion score
"""

from __future__ import annotations

from collections import deque

import cv2
import numpy as np

from agent.signal_bus import Signal, SignalBus, SignalType, Priority


# Unified threshold (was 3000 in grounder, 2000 in tracker)
MOTION_THRESHOLD = 2500

# How many consecutive low-motion frames before flagging stillness
STILL_FRAME_LIMIT = 20  # ~10 seconds at 2 FPS


class MotionSensor:
    def __init__(self, bus: SignalBus) -> None:
        self._bus = bus
        self._prev_frame: np.ndarray | None = None
        self._still_frames = 0
        self._motion_history: deque[int] = deque(maxlen=10)

    def process(self, frame: np.ndarray) -> None:
        """Analyze frame motion. Emit signals on stillness or oscillation."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if self._prev_frame is None:
            self._prev_frame = gray
            return

        diff = cv2.absdiff(self._prev_frame, gray)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        motion_score = int(np.sum(thresh))

        self._motion_history.append(motion_score)
        self._prev_frame = gray

        # Update world state
        self._bus.update_world("motion_level", motion_score)

        # ── Sustained stillness ───────────────────────────────────────────
        if motion_score < MOTION_THRESHOLD:
            self._still_frames += 1
        else:
            self._still_frames = 0

        if self._still_frames >= STILL_FRAME_LIMIT:
            self._still_frames = 0  # reset so it doesn't fire every frame
            self._bus.emit(Signal(
                type=SignalType.STILLNESS,
                priority=Priority.NORMAL,
                data={"motion_score": motion_score, "still_duration_frames": STILL_FRAME_LIMIT},
            ))

        # ── Oscillating motion (back-and-forth pacing) ────────────────────
        if len(self._motion_history) == 10:
            diffs = [
                abs(self._motion_history[i] - self._motion_history[i - 1])
                for i in range(1, 10)
            ]
            oscillations = sum(
                1 for i in range(1, len(diffs))
                if (diffs[i] > MOTION_THRESHOLD) != (diffs[i - 1] > MOTION_THRESHOLD)
            )
            if oscillations >= 5:
                self._bus.emit(Signal(
                    type=SignalType.OSCILLATING_MOTION,
                    priority=Priority.NORMAL,
                    data={"oscillations": oscillations},
                ))
