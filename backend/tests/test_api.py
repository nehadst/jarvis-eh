"""
Integration tests for the FastAPI routes in main.py.

Uses FastAPI's TestClient (synchronous httpx) — no real server is started.
All feature modules (Orchestrator, MontageBuilder, memory) are patched so
no threads spin up and no files outside tmp_path are touched.
"""

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# We need to patch the heavy orchestrator/builder imports BEFORE main.py is
# imported so that module-level singletons don't fail.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def patched_app(tmp_path_factory):
    """
    Import main.py with all external singletons patched out.
    Returns (app, profile_dir, fallback_file).

    Strategy: conftest.py already stubs pipeline.orchestrator and
    features.memory_montage.builder as MagicMock modules, so main.py
    imports successfully.  After import we patch main.Orchestrator and
    main.MontageBuilder (i.e. the names as they live in main's namespace)
    so the lifespan factory never calls the real constructors.
    """
    profile_dir = tmp_path_factory.mktemp("profiles")
    fallback_file = tmp_path_factory.mktemp("data") / "memory_fallback.json"
    fallback_file.write_text("{}")

    # Remove stale main module so we get a clean import with our patches active
    if "main" in sys.modules:
        del sys.modules["main"]

    mock_orch_instance = MagicMock()
    mock_orch_instance.is_running = False
    mock_orch_instance.active_task = None

    mock_builder_instance = MagicMock()

    # Patch config paths and the singleton memory fallback path, then import main
    with patch("config.FAMILY_PROFILES_PATH", profile_dir), \
         patch("services.backboard_client._FALLBACK_PATH", fallback_file):

        import main as app_module

        # Now patch the names as they exist in main's namespace
        app_module.Orchestrator = MagicMock(return_value=mock_orch_instance)
        app_module.MontageBuilder = MagicMock(return_value=mock_builder_instance)

        # Manually set globals that lifespan would normally set (lifespan
        # doesn't run during TestClient construction in scope="module")
        app_module.orchestrator = mock_orch_instance
        app_module.montage_builder = mock_builder_instance
        app_module.event_log.clear()

        yield app_module.app, profile_dir, fallback_file


@pytest.fixture()
def client(patched_app):
    app, profile_dir, _ = patched_app
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def profile_dir(patched_app):
    _, pd, _ = patched_app
    return pd


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_returns_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_returns_ok_status(self, client):
        r = client.get("/health")
        assert r.json()["status"] == "ok"

    def test_returns_patient_name(self, client):
        r = client.get("/health")
        assert "patient" in r.json()


# ---------------------------------------------------------------------------
# GET /api/family
# ---------------------------------------------------------------------------

class TestListFamily:
    def test_empty_list_when_no_profiles(self, client, profile_dir):
        # Remove any profiles leftover from other tests
        for f in profile_dir.glob("*.json"):
            f.unlink()
        r = client.get("/api/family")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_profiles(self, client, profile_dir, sample_profile):
        for f in profile_dir.glob("*.json"):
            f.unlink()
        (profile_dir / "sarah_johnson.json").write_text(json.dumps(sample_profile))
        r = client.get("/api/family")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["name"] == "Sarah Johnson"


# ---------------------------------------------------------------------------
# GET /api/family/{id}
# ---------------------------------------------------------------------------

class TestGetFamilyMember:
    def test_returns_404_for_missing_member(self, client, profile_dir):
        for f in profile_dir.glob("*.json"):
            f.unlink()
        r = client.get("/api/family/ghost_person")
        assert r.status_code == 404

    def test_returns_profile_for_existing_member(self, client, profile_dir, sample_profile):
        for f in profile_dir.glob("*.json"):
            f.unlink()
        (profile_dir / "sarah_johnson.json").write_text(json.dumps(sample_profile))
        r = client.get("/api/family/sarah_johnson")
        assert r.status_code == 200
        assert r.json()["name"] == "Sarah Johnson"


# ---------------------------------------------------------------------------
# POST /api/family/{id}
# ---------------------------------------------------------------------------

class TestUpdateFamilyMember:
    def test_creates_new_profile(self, client, profile_dir, sample_profile):
        for f in profile_dir.glob("*.json"):
            f.unlink()
        r = client.post("/api/family/sarah_johnson", json=sample_profile)
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert (profile_dir / "sarah_johnson.json").exists()

    def test_profile_file_contains_posted_data(self, client, profile_dir, sample_profile):
        for f in profile_dir.glob("*.json"):
            f.unlink()
        client.post("/api/family/sarah_johnson", json=sample_profile)
        on_disk = json.loads((profile_dir / "sarah_johnson.json").read_text())
        assert on_disk["name"] == "Sarah Johnson"

    def test_update_overwrites_existing(self, client, profile_dir, sample_profile):
        for f in profile_dir.glob("*.json"):
            f.unlink()
        client.post("/api/family/sarah_johnson", json=sample_profile)
        updated = dict(sample_profile, name="Sarah Updated")
        client.post("/api/family/sarah_johnson", json=updated)
        on_disk = json.loads((profile_dir / "sarah_johnson.json").read_text())
        assert on_disk["name"] == "Sarah Updated"

    def test_reload_profiles_called_on_update(self, client, profile_dir, sample_profile, patched_app):
        app, pd, _ = patched_app
        import main as m
        m.orchestrator.face_recognizer = MagicMock()
        for f in profile_dir.glob("*.json"):
            f.unlink()
        client.post("/api/family/sarah_johnson", json=sample_profile)
        m.orchestrator.face_recognizer.reload_profiles.assert_called_once()


# ---------------------------------------------------------------------------
# GET/POST /api/tasks
# ---------------------------------------------------------------------------

class TestTasks:
    def test_get_task_returns_none_initially(self, client, patched_app):
        app, _, _ = patched_app
        import main as m
        m.orchestrator.active_task = None
        r = client.get("/api/tasks")
        assert r.status_code == 200
        assert r.json()["task"] is None

    def test_post_task_calls_orchestrator(self, client, patched_app):
        app, _, _ = patched_app
        import main as m
        r = client.post("/api/tasks", json={"task": "Get a glass of water", "set_by": "Sarah"})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        m.orchestrator.set_active_task.assert_called_with("Get a glass of water", "Sarah")


# ---------------------------------------------------------------------------
# GET/POST /api/household
# ---------------------------------------------------------------------------

class TestHousehold:
    def test_get_returns_empty_initially(self, client, patched_app):
        app, _, fallback = patched_app
        # Clear fallback so household_context key doesn't exist
        fallback.write_text("{}")
        r = client.get("/api/household")
        assert r.status_code == 200
        assert "who_is_home" in r.json()

    def test_post_stores_household(self, client):
        r = client.post("/api/household", json={"who_is_home": "David, Sarah"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_get_after_post_reflects_update(self, client):
        client.post("/api/household", json={"who_is_home": "David"})
        r = client.get("/api/household")
        assert r.json().get("who_is_home") == "David"


# ---------------------------------------------------------------------------
# GET /api/events
# ---------------------------------------------------------------------------

class TestEvents:
    def test_returns_list(self, client, patched_app):
        app, _, _ = patched_app
        import main as m
        m.event_log.clear()
        r = client.get("/api/events")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_returns_logged_events(self, client, patched_app):
        app, _, _ = patched_app
        import main as m
        m.event_log.clear()
        m.event_log.append({"type": "face_recognized", "person": "Sarah", "timestamp": "2026-01-01T00:00:00"})
        r = client.get("/api/events")
        assert len(r.json()) == 1
        assert r.json()[0]["type"] == "face_recognized"


# ---------------------------------------------------------------------------
# GET/POST /api/safezones
# ---------------------------------------------------------------------------

class TestSafeZones:
    def test_get_returns_safe_zones(self, client):
        r = client.get("/api/safezones")
        assert r.status_code == 200
        data = r.json()
        assert "safe_zones" in data
        assert isinstance(data["safe_zones"], list)

    def test_get_includes_defaults(self, client, patched_app):
        app, _, fallback = patched_app
        fallback.write_text("{}")  # clear custom zones
        r = client.get("/api/safezones")
        zones = r.json()["safe_zones"]
        assert "kitchen" in zones

    def test_post_stores_custom_zones(self, client, patched_app):
        app, _, fallback = patched_app
        fallback.write_text("{}")
        r = client.post("/api/safezones", json={"safe_zones": ["sunroom", "garden"]})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_post_bad_body_returns_422_or_400(self, client):
        r = client.post("/api/safezones", json={"safe_zones": "not-a-list"})
        assert r.status_code in (400, 422)

    def test_custom_zones_appear_in_get_after_post(self, client, patched_app):
        app, _, fallback = patched_app
        fallback.write_text("{}")
        client.post("/api/safezones", json={"safe_zones": ["conservatory"]})
        r = client.get("/api/safezones")
        assert "conservatory" in r.json()["safe_zones"]


# ---------------------------------------------------------------------------
# POST /api/capture/start and /stop
# ---------------------------------------------------------------------------

class TestCapture:
    def test_start_capture_returns_ok(self, client, patched_app):
        app, _, _ = patched_app
        import main as m
        m.orchestrator.is_running = False
        r = client.post("/api/capture/start")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_stop_capture_returns_ok(self, client, patched_app):
        app, _, _ = patched_app
        import main as m
        r = client.post("/api/capture/stop")
        assert r.status_code == 200
        assert r.json()["ok"] is True


# ---------------------------------------------------------------------------
# POST /api/montage/{person_id}
# ---------------------------------------------------------------------------

class TestMontageRoute:
    def test_returns_404_for_missing_person(self, client, profile_dir):
        for f in profile_dir.glob("*.json"):
            f.unlink()
        r = client.post("/api/montage/ghost_person")
        assert r.status_code == 404

    def test_returns_ok_for_existing_person(self, client, profile_dir, sample_profile):
        for f in profile_dir.glob("*.json"):
            f.unlink()
        (profile_dir / "sarah_johnson.json").write_text(json.dumps(sample_profile))
        r = client.post("/api/montage/sarah_johnson")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_tag_filter_reflected_in_response(self, client, profile_dir, sample_profile):
        for f in profile_dir.glob("*.json"):
            f.unlink()
        (profile_dir / "sarah_johnson.json").write_text(json.dumps(sample_profile))
        r = client.post("/api/montage/sarah_johnson?tag=christmas")
        assert r.json()["tag_filter"] == "christmas"
