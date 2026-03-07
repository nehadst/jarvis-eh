"""
Backboard.io client — persistent multi-agent memory and context store.

Used for:
  - Storing family profiles and interaction history across sessions
  - Retrieving recent activity context for grounding
  - Saving and loading active caregiver tasks
  - Conversation history for the Copilot feature

Falls back to a local JSON file store if BACKBOARD_API_KEY is not configured
so the project works without the sponsor API during local dev.

Usage:
    from services.backboard_client import memory

    memory.store("last_interaction_sarah", {"date": "2026-03-07", "summary": "Watched a movie"})
    data = memory.retrieve("last_interaction_sarah")
"""

from __future__ import annotations

import json
from pathlib import Path
import requests
from config import settings


_FALLBACK_PATH = Path(__file__).parent.parent / "data" / "memory_fallback.json"


class BackboardClient:
    BASE_URL = "https://api.backboard.io/v1"

    def __init__(self) -> None:
        self._use_api = bool(settings.backboard_api_key and settings.backboard_project_id)
        self._headers = {
            "Authorization": f"Bearer {settings.backboard_api_key}",
            "Content-Type": "application/json",
        }
        self._project_id = settings.backboard_project_id

        # Ensure fallback store exists
        _FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not _FALLBACK_PATH.exists():
            _FALLBACK_PATH.write_text("{}")

    # ── Public interface ──────────────────────────────────────────────────────

    def store(self, key: str, value: dict | str | list) -> bool:
        """Persist a value under a key, scoped to this project."""
        if self._use_api:
            return self._api_store(key, value)
        return self._local_store(key, value)

    def retrieve(self, key: str) -> dict | str | list | None:
        """Retrieve a previously stored value by key. Returns None if not found."""
        if self._use_api:
            return self._api_retrieve(key)
        return self._local_retrieve(key)

    def append(self, key: str, item: dict) -> bool:
        """Append an item to a stored list (creates the list if needed)."""
        existing = self.retrieve(key) or []
        if not isinstance(existing, list):
            existing = [existing]
        existing.append(item)
        # Keep last 50 entries to avoid unbounded growth
        return self.store(key, existing[-50:])

    # ── Backboard API calls ───────────────────────────────────────────────────

    def _api_store(self, key: str, value) -> bool:
        try:
            resp = requests.post(
                f"{self.BASE_URL}/projects/{self._project_id}/memory",
                headers=self._headers,
                json={"key": key, "value": value},
                timeout=5,
            )
            return resp.ok
        except requests.RequestException as e:
            print(f"[Backboard] Store failed, using local fallback: {e}")
            return self._local_store(key, value)

    def _api_retrieve(self, key: str):
        try:
            resp = requests.get(
                f"{self.BASE_URL}/projects/{self._project_id}/memory/{key}",
                headers=self._headers,
                timeout=5,
            )
            if resp.ok:
                return resp.json().get("value")
            return None
        except requests.RequestException as e:
            print(f"[Backboard] Retrieve failed, using local fallback: {e}")
            return self._local_retrieve(key)

    # ── Local JSON fallback ───────────────────────────────────────────────────

    def _load_local(self) -> dict:
        return json.loads(_FALLBACK_PATH.read_text())

    def _local_store(self, key: str, value) -> bool:
        data = self._load_local()
        data[key] = value
        _FALLBACK_PATH.write_text(json.dumps(data, indent=2))
        return True

    def _local_retrieve(self, key: str):
        return self._load_local().get(key)


# Singleton
memory = BackboardClient()
