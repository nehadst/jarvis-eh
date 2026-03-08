"""
Tests for MontageBuilder — cooldown guard, profile loading, graceful
degradation when Gemini / ElevenLabs / Cloudinary are unavailable.
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from features.memory_montage.builder import MontageBuilder, MONTAGE_COOLDOWN_SECONDS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _builder(profile_dir: Path, events: list | None = None) -> MontageBuilder:
    captured = [] if events is None else events
    b = MontageBuilder(on_event=captured.append)
    return b


def _patch_profile_path(profile_dir: Path):
    """Context manager that redirects FAMILY_PROFILES_PATH to tmp dir."""
    return patch("features.memory_montage.builder.FAMILY_PROFILES_PATH", profile_dir)


# ---------------------------------------------------------------------------
# Profile loading
# ---------------------------------------------------------------------------

class TestProfileLoading:
    def test_returns_none_for_missing_profile(self, tmp_profile_dir: Path):
        b = _builder(tmp_profile_dir)
        with _patch_profile_path(tmp_profile_dir):
            result = b._load_profile("nonexistent_person")
        assert result is None

    def test_loads_valid_profile(self, tmp_profile_dir: Path, sample_profile: dict):
        (tmp_profile_dir / "sarah_johnson.json").write_text(json.dumps(sample_profile))
        b = _builder(tmp_profile_dir)
        with _patch_profile_path(tmp_profile_dir):
            result = b._load_profile("sarah_johnson")
        assert result is not None
        assert result["name"] == "Sarah Johnson"

    def test_returns_none_for_corrupt_json(self, tmp_profile_dir: Path):
        (tmp_profile_dir / "bad.json").write_text("{not valid json}")
        b = _builder(tmp_profile_dir)
        with _patch_profile_path(tmp_profile_dir):
            result = b._load_profile("bad")
        assert result is None


# ---------------------------------------------------------------------------
# build() — cooldown
# ---------------------------------------------------------------------------

class TestBuildCooldown:
    def test_build_returns_none_within_cooldown(self, tmp_profile_dir: Path, sample_profile: dict):
        (tmp_profile_dir / "sarah_johnson.json").write_text(json.dumps(sample_profile))
        events = []
        b = _builder(tmp_profile_dir, events)
        # Mark as recently built
        b._last_built["sarah_johnson"] = time.time()

        with _patch_profile_path(tmp_profile_dir), \
             patch("features.memory_montage.builder.gemini", None), \
             patch("features.memory_montage.builder.cloud", None), \
             patch("features.memory_montage.builder.tts", None):
            result = b.build("sarah_johnson", force=False)

        assert result is None
        assert events == []

    def test_force_bypasses_cooldown(self, tmp_profile_dir: Path, sample_profile: dict):
        (tmp_profile_dir / "sarah_johnson.json").write_text(json.dumps(sample_profile))
        events = []
        b = _builder(tmp_profile_dir, events)
        b._last_built["sarah_johnson"] = time.time()  # would normally block

        with _patch_profile_path(tmp_profile_dir), \
             patch("features.memory_montage.builder.gemini", None), \
             patch("features.memory_montage.builder.cloud", None), \
             patch("features.memory_montage.builder.tts", None):
            result = b.build("sarah_johnson", force=True)

        assert result is not None
        assert result["type"] == "montage_ready"

    def test_build_allowed_after_cooldown_expires(self, tmp_profile_dir: Path, sample_profile: dict):
        (tmp_profile_dir / "sarah_johnson.json").write_text(json.dumps(sample_profile))
        events = []
        b = _builder(tmp_profile_dir, events)
        b._last_built["sarah_johnson"] = time.time() - MONTAGE_COOLDOWN_SECONDS - 1

        with _patch_profile_path(tmp_profile_dir), \
             patch("features.memory_montage.builder.gemini", None), \
             patch("features.memory_montage.builder.cloud", None), \
             patch("features.memory_montage.builder.tts", None):
            result = b.build("sarah_johnson", force=False)

        assert result is not None


# ---------------------------------------------------------------------------
# build() — missing profile short-circuit
# ---------------------------------------------------------------------------

class TestBuildMissingProfile:
    def test_returns_none_when_profile_missing(self, tmp_profile_dir: Path):
        events = []
        b = _builder(tmp_profile_dir, events)
        with _patch_profile_path(tmp_profile_dir), \
             patch("features.memory_montage.builder.gemini", None), \
             patch("features.memory_montage.builder.cloud", None), \
             patch("features.memory_montage.builder.tts", None):
            result = b.build("ghost_person", force=True)
        assert result is None
        assert events == []


# ---------------------------------------------------------------------------
# build() — graceful degradation (no external services)
# ---------------------------------------------------------------------------

class TestBuildGracefulDegradation:
    def test_fires_event_even_without_cloud(self, tmp_profile_dir: Path, sample_profile: dict):
        (tmp_profile_dir / "sarah_johnson.json").write_text(json.dumps(sample_profile))
        events = []
        b = _builder(tmp_profile_dir, events)

        with _patch_profile_path(tmp_profile_dir), \
             patch("features.memory_montage.builder.gemini", None), \
             patch("features.memory_montage.builder.cloud", None), \
             patch("features.memory_montage.builder.tts", None):
            result = b.build("sarah_johnson", force=True)

        assert result is not None
        assert len(events) == 1
        assert events[0]["type"] == "montage_ready"

    def test_event_has_fallback_narration_when_no_gemini(self, tmp_profile_dir: Path, sample_profile: dict):
        (tmp_profile_dir / "sarah_johnson.json").write_text(json.dumps(sample_profile))
        events = []
        b = _builder(tmp_profile_dir, events)

        with _patch_profile_path(tmp_profile_dir), \
             patch("features.memory_montage.builder.gemini", None), \
             patch("features.memory_montage.builder.cloud", None), \
             patch("features.memory_montage.builder.tts", None):
            result = b.build("sarah_johnson", force=True)

        assert "Sarah Johnson" in result["narration"]
        assert "granddaughter" in result["narration"]

    def test_event_fields_present(self, tmp_profile_dir: Path, sample_profile: dict):
        (tmp_profile_dir / "sarah_johnson.json").write_text(json.dumps(sample_profile))
        events = []
        b = _builder(tmp_profile_dir, events)

        with _patch_profile_path(tmp_profile_dir), \
             patch("features.memory_montage.builder.gemini", None), \
             patch("features.memory_montage.builder.cloud", None), \
             patch("features.memory_montage.builder.tts", None):
            result = b.build("sarah_johnson", force=True)

        for field in ("type", "person_id", "person", "relationship", "montage_url", "narration"):
            assert field in result, f"Missing field: {field}"

    def test_montage_url_empty_without_cloud(self, tmp_profile_dir: Path, sample_profile: dict):
        (tmp_profile_dir / "sarah_johnson.json").write_text(json.dumps(sample_profile))
        b = _builder(tmp_profile_dir)

        with _patch_profile_path(tmp_profile_dir), \
             patch("features.memory_montage.builder.gemini", None), \
             patch("features.memory_montage.builder.cloud", None), \
             patch("features.memory_montage.builder.tts", None):
            result = b.build("sarah_johnson", force=True)

        assert result["montage_url"] == ""

    def test_gemini_narration_used_when_available(self, tmp_profile_dir: Path, sample_profile: dict):
        (tmp_profile_dir / "sarah_johnson.json").write_text(json.dumps(sample_profile))
        events = []
        b = _builder(tmp_profile_dir, events)

        mock_gemini = MagicMock()
        mock_gemini.build_montage_narration_prompt.return_value = "prompt text"
        mock_gemini.generate.return_value = "Here is a beautiful Gemini narration."

        with _patch_profile_path(tmp_profile_dir), \
             patch("features.memory_montage.builder.gemini", mock_gemini), \
             patch("features.memory_montage.builder.cloud", None), \
             patch("features.memory_montage.builder.tts", None):
            result = b.build("sarah_johnson", force=True)

        assert result["narration"] == "Here is a beautiful Gemini narration."

    def test_tag_filter_passed_through_to_event(self, tmp_profile_dir: Path, sample_profile: dict):
        (tmp_profile_dir / "sarah_johnson.json").write_text(json.dumps(sample_profile))
        b = _builder(tmp_profile_dir)

        with _patch_profile_path(tmp_profile_dir), \
             patch("features.memory_montage.builder.gemini", None), \
             patch("features.memory_montage.builder.cloud", None), \
             patch("features.memory_montage.builder.tts", None):
            result = b.build("sarah_johnson", tag_filter="christmas", force=True)

        assert result["tag_filter"] == "christmas"

    def test_cooldown_recorded_after_successful_build(self, tmp_profile_dir: Path, sample_profile: dict):
        (tmp_profile_dir / "sarah_johnson.json").write_text(json.dumps(sample_profile))
        b = _builder(tmp_profile_dir)
        before = time.time()

        with _patch_profile_path(tmp_profile_dir), \
             patch("features.memory_montage.builder.gemini", None), \
             patch("features.memory_montage.builder.cloud", None), \
             patch("features.memory_montage.builder.tts", None):
            b.build("sarah_johnson", force=True)

        assert b._last_built.get("sarah_johnson", 0) >= before
