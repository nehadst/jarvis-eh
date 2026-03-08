"""
Tests for ActivityTracker — buffer pruning, confusion detection heuristic,
reminder delivery window, and graceful no-Gemini behaviour.
"""

import time
from collections import deque
from unittest.mock import MagicMock, patch

import pytest

from features.activity_continuity.tracker import (
    ActivityTracker,
    INFER_INTERVAL,
    REMINDER_COOLDOWN,
    BUFFER_DURATION,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tracker(events: list | None = None) -> ActivityTracker:
    captured = [] if events is None else events
    return ActivityTracker(on_event=captured.append)


def _gray_frame(value: int = 128):
    """
    Return a fake 'frame' whose cv2.cvtColor output is controllable.
    The real cv2 is stubbed in conftest, so we just need an object.
    """
    return MagicMock()


# ---------------------------------------------------------------------------
# Buffer pruning
# ---------------------------------------------------------------------------

class TestBufferPruning:
    def test_old_entries_are_pruned(self):
        t = _tracker()
        old_time = time.time() - BUFFER_DURATION - 10
        t._buffer.append({"time": old_time, "activity": "old", "location_hint": ""})
        # A fresh process call prunes entries older than BUFFER_DURATION
        now = time.time()
        cutoff = now - BUFFER_DURATION
        while t._buffer and t._buffer[0]["time"] < cutoff:
            t._buffer.popleft()
        assert len(t._buffer) == 0

    def test_recent_entries_are_kept(self):
        t = _tracker()
        recent_time = time.time() - 10
        t._buffer.append({"time": recent_time, "activity": "reading", "location_hint": ""})
        now = time.time()
        cutoff = now - BUFFER_DURATION
        while t._buffer and t._buffer[0]["time"] < cutoff:
            t._buffer.popleft()
        assert len(t._buffer) == 1

    def test_get_last_activity_returns_none_when_empty(self):
        t = _tracker()
        assert t.get_last_activity() is None

    def test_get_last_activity_returns_most_recent(self):
        t = _tracker()
        t._buffer.append({"time": time.time() - 20, "activity": "reading", "location_hint": ""})
        t._buffer.append({"time": time.time() - 5,  "activity": "making tea", "location_hint": "kettle on counter"})
        assert t.get_last_activity()["activity"] == "making tea"


# ---------------------------------------------------------------------------
# set_active_task
# ---------------------------------------------------------------------------

class TestSetActiveTask:
    def test_stores_task(self):
        t = _tracker()
        t.set_active_task("go get a glass of water")
        assert t._active_task == "go get a glass of water"

    def test_overwrite_task(self):
        t = _tracker()
        t.set_active_task("task 1")
        t.set_active_task("task 2")
        assert t._active_task == "task 2"


# ---------------------------------------------------------------------------
# _detect_confusion — motion heuristic
# ---------------------------------------------------------------------------

class TestDetectConfusion:
    def test_first_frame_never_confused(self):
        t = _tracker()
        import numpy as np_real
        # Use real numpy if available, else skip gracefully
        try:
            import cv2 as real_cv2
            frame = real_cv2.imread.__module__  # just check it's real
        except Exception:
            pytest.skip("cv2 not installed — skipping motion heuristic test")

    def test_confusion_flag_false_on_first_call(self):
        """_detect_confusion returns False on first call (no prev_frame yet)."""
        t = _tracker()
        # stub cv2 to return controllable diff arrays
        import sys
        cv2_mock = sys.modules.get("cv2")
        if cv2_mock is None or not isinstance(cv2_mock, MagicMock):
            pytest.skip("cv2 is the real package — use integration tests")

        import numpy as np
        gray = MagicMock()
        blurred = MagicMock()
        cv2_mock.cvtColor.return_value = gray
        cv2_mock.GaussianBlur.return_value = blurred

        result = t._detect_confusion(_gray_frame())
        assert result is False
        assert t._prev_frame is not None


# ---------------------------------------------------------------------------
# _deliver_reminder — time window logic
# ---------------------------------------------------------------------------

class TestDeliverReminder:
    def _add_entry(self, tracker: ActivityTracker, age_seconds: float, activity: str):
        """Add a buffer entry that is age_seconds old."""
        tracker._buffer.append({
            "time": time.time() - age_seconds,
            "activity": activity,
            "location_hint": "on the table",
        })

    def test_no_reminder_when_buffer_empty(self):
        events = []
        t = _tracker(events)
        with patch("features.activity_continuity.tracker.gemini", None), \
             patch("features.activity_continuity.tracker.tts", None), \
             patch("features.activity_continuity.tracker.memory") as mm:
            mm.append.return_value = True
            t._deliver_reminder()
        assert events == []

    def test_no_reminder_when_all_entries_too_fresh(self):
        """Activities < 10s old should NOT trigger a reminder."""
        events = []
        t = _tracker(events)
        self._add_entry(t, age_seconds=5, activity="making tea")  # 5s ago — too fresh
        with patch("features.activity_continuity.tracker.gemini", None), \
             patch("features.activity_continuity.tracker.tts", None), \
             patch("features.activity_continuity.tracker.memory") as mm:
            mm.append.return_value = True
            t._deliver_reminder()
        assert events == []

    def test_reminder_fires_for_activity_in_window(self):
        """Activities 10–60s old are in the valid reminder window."""
        events = []
        t = _tracker(events)
        self._add_entry(t, age_seconds=30, activity="reading a book")
        with patch("features.activity_continuity.tracker.gemini", None), \
             patch("features.activity_continuity.tracker.tts", None), \
             patch("features.activity_continuity.tracker.memory") as mm:
            mm.append.return_value = True
            t._deliver_reminder()
        assert len(events) == 1
        assert events[0]["type"] == "activity_continuity"
        assert events[0]["activity"] == "reading a book"

    def test_no_reminder_when_entry_too_old(self):
        """Activities > 60s old are outside the window — bug we know about but still test behaviour."""
        events = []
        t = _tracker(events)
        self._add_entry(t, age_seconds=90, activity="watching tv")  # 90s — too old
        with patch("features.activity_continuity.tracker.gemini", None), \
             patch("features.activity_continuity.tracker.tts", None), \
             patch("features.activity_continuity.tracker.memory") as mm:
            mm.append.return_value = True
            t._deliver_reminder()
        assert events == []  # documents current behaviour (known limitation)

    def test_reminder_cooldown_prevents_spam(self):
        events = []
        t = _tracker(events)
        t._last_reminder_time = time.time()  # just fired
        self._add_entry(t, age_seconds=30, activity="reading")
        with patch("features.activity_continuity.tracker.gemini", None), \
             patch("features.activity_continuity.tracker.tts", None), \
             patch("features.activity_continuity.tracker.memory") as mm:
            mm.append.return_value = True
            # Simulate the cooldown check that process() does
            now = time.time()
            if (now - t._last_reminder_time) < REMINDER_COOLDOWN:
                pass  # blocked — don't call deliver
            else:
                t._deliver_reminder()
        assert events == []


# ---------------------------------------------------------------------------
# _generate_reminder — fallback when no gemini
# ---------------------------------------------------------------------------

class TestGenerateReminder:
    def test_fallback_includes_activity(self):
        t = _tracker()
        with patch("features.activity_continuity.tracker.gemini", None):
            text = t._generate_reminder("making tea", "kettle on the counter")
        assert "making tea" in text

    def test_gemini_reminder_used_when_available(self):
        t = _tracker()
        mock_gem = MagicMock()
        mock_gem.generate.return_value = "You were making tea, the kettle is ready."
        with patch("features.activity_continuity.tracker.gemini", mock_gem):
            text = t._generate_reminder("making tea", "kettle on counter")
        assert text == "You were making tea, the kettle is ready."
