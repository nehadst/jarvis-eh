"""
Shared pytest fixtures for REWIND backend tests.

Design principles:
  - All tests run without ANY real API keys (Gemini, ElevenLabs, Cloudinary).
  - Every test that touches the filesystem uses a tmp_path so nothing bleeds
    into the real data/ directory.
  - Heavy imports (cv2, deepface, pygame, etc.) are patched at the module level
    before the module under test is imported, so the test suite runs even when
    those native packages are not installed in the current environment.
"""

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Stub heavy native packages that may not be installed in the test env
# ---------------------------------------------------------------------------

def _stub_module(name: str, **attrs) -> MagicMock:
    """Register a MagicMock as sys.modules[name] and return it."""
    mod = MagicMock()
    mod.__name__ = name
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# Only stub if not already the real package
for _name in [
    "cv2", "numpy", "deepface", "deepface.DeepFace",
    "pygame", "pygame.mixer",
    "google", "google.generativeai",
    "elevenlabs", "elevenlabs.client", "elevenlabs.VoiceSettings",
    "cloudinary", "cloudinary.uploader", "cloudinary.api", "cloudinary.utils",
    "mss", "PIL", "PIL.Image",
    "whisper", "sounddevice",
    # capture / pipeline stubs so test_api.py can import main.py cleanly
    # (these transitively import cv2 which is not installed)
    "capture", "capture.frame_capture",
    "pipeline", "pipeline.orchestrator",
]:
    if _name not in sys.modules:
        _stub_module(_name)

# Give the stub modules the classes that main.py imports from them
_orch_mod = sys.modules["pipeline.orchestrator"]
_orch_mod.Orchestrator = MagicMock

_builder_stub = _stub_module("features.memory_montage._builder_stub")
# NOTE: we do NOT stub features.* modules here — they import cleanly with
# only the native stubs above, and the feature test files need real classes.

# numpy needs a real-ish array interface for some tests
if not hasattr(sys.modules.get("numpy", MagicMock()), "ndarray"):
    sys.modules["numpy"] = _stub_module("numpy", ndarray=object)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_profile_dir(tmp_path: Path) -> Path:
    """An empty family_profiles directory under tmp_path."""
    d = tmp_path / "family_profiles"
    d.mkdir()
    return d


@pytest.fixture()
def sample_profile() -> dict:
    return {
        "id": "sarah_johnson",
        "name": "Sarah Johnson",
        "relationship": "granddaughter",
        "age": 28,
        "notes": ["Loves the cottage", "Plays piano"],
        "personal_detail": "She always wears a red hat.",
        "last_interaction": {"date": "2026-01-10", "summary": "Watched a movie together"},
        "calming_anchors": [],
        "face_folder": "",
        "cloudinary_folder": "",
        "voice_anchor_file": "",
    }


@pytest.fixture()
def profile_file(tmp_profile_dir: Path, sample_profile: dict) -> Path:
    """Write sample_profile to disk and return the path."""
    p = tmp_profile_dir / "sarah_johnson.json"
    p.write_text(json.dumps(sample_profile))
    return p


@pytest.fixture()
def tmp_fallback(tmp_path: Path) -> Path:
    """An empty memory_fallback.json file."""
    f = tmp_path / "memory_fallback.json"
    f.write_text("{}")
    return f
