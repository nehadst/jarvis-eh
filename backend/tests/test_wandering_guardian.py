"""
Tests for WanderingGuardian — scene classification logic, escalation tiers,
cooldown, and episode reset. All external dependencies (Gemini, ElevenLabs,
Backboard) are patched out so no real API calls are made.
"""

import time
from collections import deque
from unittest.mock import MagicMock, patch

import pytest

# conftest stubs cv2/numpy before any import, so this is safe
from features.wandering_guardian.guardian import (
    WanderingGuardian,
    DEFAULT_SAFE_ZONES,
    UNSAFE_THRESHOLD,
    ALERT_COOLDOWN,
    EPISODE_RESET_SECONDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _frame():
    """Return a dummy frame object (numpy not needed for guardian unit tests)."""
    return MagicMock()


def _guardian_no_apis(events: list | None = None) -> WanderingGuardian:
    """
    Return a WanderingGuardian whose external services are all None/mocked.
    Captured events are appended to the provided list.
    """
    captured = [] if events is None else events
    g = WanderingGuardian(on_event=captured.append)
    return g


# ---------------------------------------------------------------------------
# DEFAULT_SAFE_ZONES
# ---------------------------------------------------------------------------

class TestDefaultSafeZones:
    def test_is_a_set(self):
        assert isinstance(DEFAULT_SAFE_ZONES, set)

    def test_contains_common_rooms(self):
        for room in ("kitchen", "living room", "bedroom", "bathroom"):
            assert room in DEFAULT_SAFE_ZONES

    def test_all_lowercase(self):
        for z in DEFAULT_SAFE_ZONES:
            assert z == z.lower()


# ---------------------------------------------------------------------------
# _load_safe_zones — merges custom zones from memory
# ---------------------------------------------------------------------------

class TestLoadSafeZones:
    def test_returns_defaults_when_memory_empty(self):
        g = _guardian_no_apis()
        with patch("features.wandering_guardian.guardian.memory") as mock_mem:
            mock_mem.retrieve.return_value = None
            zones = g._load_safe_zones()
        assert DEFAULT_SAFE_ZONES.issubset(zones)

    def test_merges_custom_zones(self):
        g = _guardian_no_apis()
        with patch("features.wandering_guardian.guardian.memory") as mock_mem:
            mock_mem.retrieve.return_value = ["sunroom", "garden"]
            zones = g._load_safe_zones()
        assert "sunroom" in zones
        assert "garden" in zones
        assert "kitchen" in zones  # default still there

    def test_custom_zones_normalised_lowercase(self):
        g = _guardian_no_apis()
        with patch("features.wandering_guardian.guardian.memory") as mock_mem:
            mock_mem.retrieve.return_value = ["SUNROOM", "Garden"]
            zones = g._load_safe_zones()
        assert "sunroom" in zones
        assert "garden" in zones


# ---------------------------------------------------------------------------
# _classify_scene — returns empty string when gemini is None
# ---------------------------------------------------------------------------

class TestClassifyScene:
    def test_returns_empty_when_no_gemini(self):
        g = _guardian_no_apis()
        with patch("features.wandering_guardian.guardian.gemini", None):
            result = g._classify_scene(_frame())
        assert result == ""

    def test_returns_gemini_response(self):
        g = _guardian_no_apis()
        mock_gemini = MagicMock()
        mock_gemini.analyze_image.return_value = "  Kitchen at home  "
        with patch("features.wandering_guardian.guardian.gemini", mock_gemini):
            result = g._classify_scene(_frame())
        assert result == "kitchen at home"

    def test_returns_empty_on_gemini_exception(self):
        g = _guardian_no_apis()
        mock_gemini = MagicMock()
        mock_gemini.analyze_image.side_effect = RuntimeError("network error")
        with patch("features.wandering_guardian.guardian.gemini", mock_gemini):
            result = g._classify_scene(_frame())
        assert result == ""


# ---------------------------------------------------------------------------
# process — safe scene tracking
# ---------------------------------------------------------------------------

class TestProcessSafeScene:
    def test_safe_scene_updates_last_safe_scene(self):
        events = []
        g = _guardian_no_apis(events)
        with patch("features.wandering_guardian.guardian.gemini") as mock_gem, \
             patch("features.wandering_guardian.guardian.memory") as mock_mem, \
             patch("features.wandering_guardian.guardian.tts", None):
            mock_gem.analyze_image.return_value = "kitchen at home"
            mock_mem.retrieve.return_value = None
            g.process(_frame())
        assert g._last_safe_scene == "kitchen at home"
        assert events == []  # no alert fired

    def test_safe_reading_does_not_fire_event(self):
        events = []
        g = _guardian_no_apis(events)
        with patch("features.wandering_guardian.guardian.gemini") as mock_gem, \
             patch("features.wandering_guardian.guardian.memory") as mock_mem, \
             patch("features.wandering_guardian.guardian.tts", None):
            mock_gem.analyze_image.return_value = "living room"
            mock_mem.retrieve.return_value = None
            for _ in range(5):
                g.process(_frame())
        assert events == []

    def test_empty_scene_returns_early(self):
        events = []
        g = _guardian_no_apis(events)
        with patch("features.wandering_guardian.guardian.gemini", None):
            g.process(_frame())
        assert events == []
        assert len(g._scene_history) == 0


# ---------------------------------------------------------------------------
# process — unsafe scene triggers alert after UNSAFE_THRESHOLD readings
# ---------------------------------------------------------------------------

class TestProcessUnsafeScene:
    def _run_unsafe(self, g, n=UNSAFE_THRESHOLD):
        """Push n unsafe readings through process(), patching all externals."""
        with patch("features.wandering_guardian.guardian.gemini") as mock_gem, \
             patch("features.wandering_guardian.guardian.memory") as mock_mem, \
             patch("features.wandering_guardian.guardian.tts", None):
            mock_gem.analyze_image.return_value = "street corner outside"
            mock_gem.generate.return_value = "Let's head home, Dad."
            mock_mem.retrieve.return_value = None
            mock_mem.append.return_value = True
            for _ in range(n):
                g.process(_frame())

    def test_no_alert_before_threshold(self):
        events = []
        g = _guardian_no_apis(events)
        self._run_unsafe(g, n=UNSAFE_THRESHOLD - 1)
        assert events == []

    def test_alert_fires_at_threshold(self):
        events = []
        g = _guardian_no_apis(events)
        self._run_unsafe(g, n=UNSAFE_THRESHOLD)
        assert len(events) >= 1
        assert events[0]["type"] == "wandering_detected"

    def test_event_contains_scene(self):
        events = []
        g = _guardian_no_apis(events)
        self._run_unsafe(g, n=UNSAFE_THRESHOLD)
        assert events[0]["scene"] == "street corner outside"

    def test_event_contains_alert_count(self):
        events = []
        g = _guardian_no_apis(events)
        self._run_unsafe(g, n=UNSAFE_THRESHOLD)
        assert events[0]["alert_count"] == 1

    def test_event_contains_last_safe_scene(self):
        events = []
        g = _guardian_no_apis(events)
        g._last_safe_scene = "bedroom"
        self._run_unsafe(g, n=UNSAFE_THRESHOLD)
        assert events[0]["last_safe_scene"] == "bedroom"


# ---------------------------------------------------------------------------
# Escalation tiers
# ---------------------------------------------------------------------------

class TestEscalation:
    def _fire_n_alerts(self, g, n: int):
        """Bypass cooldown and fire n escalating alerts directly."""
        for i in range(n):
            g._last_alert_time = 0  # reset cooldown between calls
            with patch("features.wandering_guardian.guardian.gemini") as mock_gem, \
                 patch("features.wandering_guardian.guardian.memory") as mock_mem, \
                 patch("features.wandering_guardian.guardian.tts", None):
                mock_gem.generate.return_value = "Let's go home."
                mock_mem.append.return_value = True
                g._trigger_redirect("park outside")

    def test_first_two_alerts_are_gentle(self):
        events = []
        g = _guardian_no_apis(events)
        self._fire_n_alerts(g, 2)
        gentle = [e for e in events if e["type"] == "wandering_detected"]
        assert len(gentle) == 2
        for e in gentle:
            assert e["severity"] == "gentle"

    def test_third_alert_fires_escalated_event(self):
        events = []
        g = _guardian_no_apis(events)
        self._fire_n_alerts(g, 3)
        escalated = [e for e in events if e["type"] == "wandering_escalated"]
        assert len(escalated) >= 1

    def test_escalated_event_severity_is_urgent(self):
        events = []
        g = _guardian_no_apis(events)
        self._fire_n_alerts(g, 3)
        escalated = [e for e in events if e["type"] == "wandering_escalated"]
        assert escalated[0]["severity"] == "urgent"

    def test_alert_count_increments(self):
        g = _guardian_no_apis()
        self._fire_n_alerts(g, 3)
        assert g._alert_count == 3


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------

class TestCooldown:
    def test_second_alert_blocked_within_cooldown(self):
        events = []
        g = _guardian_no_apis(events)
        with patch("features.wandering_guardian.guardian.gemini") as mock_gem, \
             patch("features.wandering_guardian.guardian.memory") as mock_mem, \
             patch("features.wandering_guardian.guardian.tts", None):
            mock_gem.generate.return_value = "Go home."
            mock_mem.append.return_value = True
            g._trigger_redirect("park")  # alert 1
            g._trigger_redirect("park")  # should be blocked
        assert g._alert_count == 1

    def test_alert_fires_after_cooldown_expires(self):
        events = []
        g = _guardian_no_apis(events)
        with patch("features.wandering_guardian.guardian.gemini") as mock_gem, \
             patch("features.wandering_guardian.guardian.memory") as mock_mem, \
             patch("features.wandering_guardian.guardian.tts", None):
            mock_gem.generate.return_value = "Go home."
            mock_mem.append.return_value = True
            g._trigger_redirect("park")           # alert 1
            g._last_alert_time = time.time() - ALERT_COOLDOWN - 1  # expire cooldown
            g._trigger_redirect("park")           # should fire
        assert g._alert_count == 2


# ---------------------------------------------------------------------------
# Episode reset
# ---------------------------------------------------------------------------

class TestEpisodeReset:
    def test_alert_count_resets_after_safe_period(self):
        g = _guardian_no_apis()
        g._alert_count = 5
        g._last_unsafe_time = time.time() - EPISODE_RESET_SECONDS - 1

        with patch("features.wandering_guardian.guardian.gemini") as mock_gem, \
             patch("features.wandering_guardian.guardian.memory") as mock_mem, \
             patch("features.wandering_guardian.guardian.tts", None):
            mock_gem.analyze_image.return_value = "living room"
            mock_mem.retrieve.return_value = None
            g.process(_frame())

        assert g._alert_count == 0

    def test_alert_count_not_reset_before_episode_timeout(self):
        g = _guardian_no_apis()
        g._alert_count = 5
        g._last_unsafe_time = time.time() - 10  # only 10s ago — too recent

        with patch("features.wandering_guardian.guardian.gemini") as mock_gem, \
             patch("features.wandering_guardian.guardian.memory") as mock_mem, \
             patch("features.wandering_guardian.guardian.tts", None):
            mock_gem.analyze_image.return_value = "living room"
            mock_mem.retrieve.return_value = None
            g.process(_frame())

        assert g._alert_count == 5  # unchanged
