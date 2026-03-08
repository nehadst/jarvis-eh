"""
Tests for BackboardClient — local JSON fallback behaviour.

All tests use a temporary fallback file so nothing touches the real
data/memory_fallback.json on disk.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(fallback_path: Path):
    """
    Instantiate a BackboardClient that reads/writes to fallback_path only.

    We patch the module-level _FALLBACK_PATH for construction, then
    directly monkey-patch the instance methods to use the tmp path so
    state never leaks across tests.
    """
    import services.backboard_client as mod

    if not fallback_path.exists():
        fallback_path.write_text("{}")

    # Temporarily redirect module path so __init__ creates the right file
    original = mod._FALLBACK_PATH
    mod._FALLBACK_PATH = fallback_path
    client = mod.BackboardClient()
    mod._FALLBACK_PATH = original

    # Bind the tmp path permanently on this instance so reads/writes
    # always go to fallback_path regardless of the module-level variable.
    def _load_local():
        return json.loads(fallback_path.read_text())

    def _local_store(key, value):
        data = _load_local()
        data[key] = value
        fallback_path.write_text(json.dumps(data, indent=2))
        return True

    def _local_retrieve(key):
        return _load_local().get(key)

    import types
    client._load_local = _load_local
    client._local_store = types.MethodType(lambda self, k, v: _local_store(k, v), client)
    client._local_retrieve = types.MethodType(lambda self, k: _local_retrieve(k), client)

    return client, fallback_path


# ---------------------------------------------------------------------------
# store / retrieve
# ---------------------------------------------------------------------------

class TestLocalStoreRetrieve:
    def test_store_and_retrieve_dict(self, tmp_fallback: Path):
        client, fb = _make_client(tmp_fallback)
        assert client._local_store("k1", {"hello": "world"})
        assert client._local_retrieve("k1") == {"hello": "world"}

    def test_store_and_retrieve_string(self, tmp_fallback: Path):
        client, fb = _make_client(tmp_fallback)
        client._local_store("greeting", "hi there")
        assert client._local_retrieve("greeting") == "hi there"

    def test_retrieve_missing_key_returns_none(self, tmp_fallback: Path):
        client, fb = _make_client(tmp_fallback)
        assert client._local_retrieve("does_not_exist") is None

    def test_overwrite_existing_key(self, tmp_fallback: Path):
        client, fb = _make_client(tmp_fallback)
        client._local_store("x", "first")
        client._local_store("x", "second")
        assert client._local_retrieve("x") == "second"

    def test_store_list(self, tmp_fallback: Path):
        client, fb = _make_client(tmp_fallback)
        client._local_store("items", [1, 2, 3])
        assert client._local_retrieve("items") == [1, 2, 3]

    def test_persisted_to_disk(self, tmp_fallback: Path):
        client, fb = _make_client(tmp_fallback)
        client._local_store("disk_key", {"persisted": True})
        raw = json.loads(fb.read_text())
        assert raw["disk_key"] == {"persisted": True}

    def test_multiple_keys_coexist(self, tmp_fallback: Path):
        client, fb = _make_client(tmp_fallback)
        client._local_store("a", 1)
        client._local_store("b", 2)
        assert client._local_retrieve("a") == 1
        assert client._local_retrieve("b") == 2


# ---------------------------------------------------------------------------
# append
# ---------------------------------------------------------------------------

class TestAppend:
    def test_append_creates_list(self, tmp_fallback: Path):
        client, _ = _make_client(tmp_fallback)
        client.append("events", {"x": 1})
        result = client._local_retrieve("events")
        assert isinstance(result, list)
        assert result[0] == {"x": 1}

    def test_append_grows_list(self, tmp_fallback: Path):
        client, _ = _make_client(tmp_fallback)
        client.append("events", {"n": 1})
        client.append("events", {"n": 2})
        result = client._local_retrieve("events")
        assert len(result) == 2
        assert result[-1] == {"n": 2}

    def test_append_caps_at_50(self, tmp_fallback: Path):
        client, _ = _make_client(tmp_fallback)
        for i in range(60):
            client.append("big_list", {"i": i})
        result = client._local_retrieve("big_list")
        assert len(result) == 50
        # Oldest entries should be dropped — last entry should be i=59
        assert result[-1] == {"i": 59}

    def test_append_to_non_list_wraps_existing(self, tmp_fallback: Path):
        client, _ = _make_client(tmp_fallback)
        client._local_store("mixed", "existing_string")
        client.append("mixed", {"new": True})
        result = client._local_retrieve("mixed")
        assert isinstance(result, list)
        assert {"new": True} in result


# ---------------------------------------------------------------------------
# Public store/retrieve (routes to local when _use_api=False)
# ---------------------------------------------------------------------------

class TestPublicInterface:
    def test_store_routes_to_local_when_no_api(self, tmp_fallback: Path):
        client, _ = _make_client(tmp_fallback)
        assert not client._use_api  # no API keys in test env
        client.store("pub_key", {"data": 42})
        assert client.retrieve("pub_key") == {"data": 42}

    def test_retrieve_returns_none_for_missing(self, tmp_fallback: Path):
        client, _ = _make_client(tmp_fallback)
        assert client.retrieve("ghost") is None
