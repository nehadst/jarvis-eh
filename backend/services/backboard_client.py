"""
Backboard.io client — persistent semantic memory for REWIND.

Architecture:
  - Local JSON file: fast structured reads for hot-path lookups
    (face cooldowns, activity buffer, household context, etc.)
  - Backboard API: semantic memory that persists across sessions and enables
    cross-feature context retrieval (grounding can recall face recognition
    events, activity tracker data, etc.)

Both are written to on every event. Local JSON handles store/retrieve
(backward compat). Backboard handles intelligent query() for rich context.

Usage:
    from services.backboard_client import memory

    memory.store("last_activity", {"activity": "making tea"})
    data = memory.retrieve("last_activity")                    # fast local read
    context = memory.query("What has Dad been doing today?")   # semantic search
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path

import requests
from config import settings


_FALLBACK_PATH = Path(__file__).parent.parent / "data" / "memory_fallback.json"


class BackboardClient:
    API_BASE = "https://app.backboard.io/api"

    def __init__(self) -> None:
        self._api_key = settings.backboard_api_key
        self._assistant_id = settings.backboard_assistant_id
        self._use_api = bool(self._api_key)
        self._headers = {
            "X-API-Key": self._api_key,
            "Content-Type": "application/json",
        }

        # Local JSON (always used for fast structured reads)
        _FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not _FALLBACK_PATH.exists():
            _FALLBACK_PATH.write_text("{}")

        # Auto-create assistant if key exists but no assistant ID
        if self._use_api and not self._assistant_id:
            self._auto_create_assistant()
        elif self._use_api:
            print(f"[Backboard] Connected — assistant {self._assistant_id[:12]}...")

    # ── Public interface (backward-compatible) ─────────────────────────────

    def store(self, key: str, value: dict | str | list) -> bool:
        """Store structured data locally + push semantic memory to Backboard."""
        self._local_store(key, value)
        # Push non-list values to Backboard (lists are handled item-by-item via append)
        if self._use_api and self._assistant_id and not isinstance(value, list):
            threading.Thread(
                target=self._push_memory,
                args=(key, value),
                daemon=True,
            ).start()
        return True

    def retrieve(self, key: str) -> dict | str | list | None:
        """Fast local read for structured data."""
        return self._local_retrieve(key)

    def append(self, key: str, item: dict) -> bool:
        """Append to a local list + push the individual item to Backboard."""
        existing = self.retrieve(key) or []
        if not isinstance(existing, list):
            existing = [existing]
        existing.append(item)
        # Keep last 50 entries locally
        self._local_store(key, existing[-50:])
        # Push only the new item to Backboard (not the whole list)
        if self._use_api and self._assistant_id:
            threading.Thread(
                target=self._push_memory,
                args=(key, item),
                daemon=True,
            ).start()
        return True

    def query(self, question: str) -> str:
        """
        Semantic query across all stored memories via Backboard.

        Creates a thread, sends the question with memory="Auto",
        returns the AI response enriched with recalled memories.

        Use this for rich context retrieval — grounding, montage narration, etc.
        Falls back to empty string if Backboard is unavailable.
        """
        if not self._use_api or not self._assistant_id:
            return ""
        try:
            # Create a thread for this query
            resp = requests.post(
                f"{self.API_BASE}/assistants/{self._assistant_id}/threads",
                headers=self._headers,
                timeout=5,
            )
            if not resp.ok:
                print(f"[Backboard] Thread creation failed: {resp.status_code}")
                return ""

            thread_data = resp.json()
            thread_id = thread_data.get("id") or thread_data.get("thread_id")
            if not thread_id:
                print(f"[Backboard] No thread ID in response: {thread_data}")
                return ""

            # Send question with memory recall enabled
            resp = requests.post(
                f"{self.API_BASE}/threads/{thread_id}/messages",
                headers=self._headers,
                json={
                    "content": question,
                    "memory": "Auto",
                    "stream": False,
                },
                timeout=15,
            )
            if resp.ok:
                data = resp.json()
                content = (
                    data.get("content")
                    or data.get("message", {}).get("content", "")
                )
                return content if isinstance(content, str) else str(content)
            print(f"[Backboard] Query message failed: {resp.status_code}")
            return ""
        except Exception as e:
            print(f"[Backboard] Query failed: {e}")
            return ""

    # ── Backboard memory push ──────────────────────────────────────────────

    def _push_memory(self, key: str, value) -> None:
        """Add a memory to the Backboard assistant (runs in background thread)."""
        try:
            content = self._format_memory(key, value)
            if not content:
                return
            resp = requests.post(
                f"{self.API_BASE}/assistants/{self._assistant_id}/memories",
                headers=self._headers,
                json={"content": content},
                timeout=5,
            )
            if resp.ok:
                print(f"[Backboard] Memory stored: {key}")
            else:
                print(f"[Backboard] Memory store failed ({resp.status_code}): {resp.text[:200]}")
        except Exception as e:
            print(f"[Backboard] Memory push error: {e}")

    def _format_memory(self, key: str, value) -> str:
        """Convert structured data into natural language for semantic storage."""
        now = datetime.now().strftime("%I:%M %p on %B %d")
        patient = settings.patient_name

        if key.startswith("interactions_"):
            person_id = key.replace("interactions_", "")
            if isinstance(value, dict):
                whisper = value.get("whisper", "")
                return f"At {now}, {patient} recognized {person_id}. {whisper}"
            return f"At {now}, {patient} had an interaction with {person_id}."

        if key == "last_activity":
            if isinstance(value, dict):
                activity = value.get("activity", "unknown")
                hint = value.get("location_hint", "")
                loc = f" Nearby: {hint}." if hint else ""
                return f"At {now}, {patient} was {activity}.{loc}"

        if key == "continuity_reminders":
            if isinstance(value, dict):
                msg = value.get("message", "")
                activity = value.get("activity", "unknown")
                return f"At {now}, {patient} was reminded about {activity}: {msg}"

        if key == "household_context":
            if isinstance(value, dict):
                who = value.get("who_is_home", "")
                return f"Household update at {now}: {who} currently home."

        if key == "active_patient_task":
            if isinstance(value, dict):
                task = value.get("task", "")
                set_by = value.get("set_by", "caregiver")
                return f"{set_by} set a task for {patient}: {task}"

        if key == "grounding_events":
            if isinstance(value, dict):
                scene = value.get("scene", "")
                msg = value.get("message", "")
                return f"At {now}, grounding in {scene}: {msg}"

        if key == "wandering_events":
            if isinstance(value, dict):
                scene = value.get("scene", "")
                msg = value.get("message", "")
                return f"At {now}, wandering detected at {scene}. Redirect: {msg}"

        # Generic fallback
        if isinstance(value, dict):
            return f"[{key}] at {now}: {json.dumps(value)}"
        return f"[{key}] at {now}: {value}"

    # ── Auto-create assistant ──────────────────────────────────────────────

    def _auto_create_assistant(self) -> None:
        """Create a REWIND assistant on Backboard if none configured."""
        try:
            resp = requests.post(
                f"{self.API_BASE}/assistants",
                headers=self._headers,
                json={
                    "name": "REWIND - Dementia Companion",
                    "system_prompt": (
                        f"You are REWIND, an AI memory companion helping {settings.patient_name}, "
                        "a person living with dementia. You store and recall memories about their "
                        "daily life: who visited, what activities they did, where they are, and "
                        "what tasks caregivers have set. When asked for context, provide warm, "
                        "calm, concise summaries. Use simple language. Never mention dementia or "
                        "memory loss directly. Speak as a caring companion, not a medical device."
                    ),
                },
                timeout=10,
            )
            if resp.ok:
                data = resp.json()
                self._assistant_id = data.get("id") or data.get("assistant_id", "")
                if self._assistant_id:
                    print(f"[Backboard] Created assistant: {self._assistant_id}")
                    print(f"[Backboard] >>> Add to .env: BACKBOARD_ASSISTANT_ID={self._assistant_id}")
                else:
                    print(f"[Backboard] Assistant created but no ID returned: {data}")
                    self._use_api = False
            else:
                print(f"[Backboard] Could not create assistant: {resp.status_code} {resp.text[:200]}")
                self._use_api = False
        except Exception as e:
            print(f"[Backboard] Assistant creation failed: {e}")
            self._use_api = False

    # ── Local JSON (fast cache) ────────────────────────────────────────────

    def _load_local(self) -> dict:
        try:
            return json.loads(_FALLBACK_PATH.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _local_store(self, key: str, value) -> bool:
        data = self._load_local()
        data[key] = value
        _FALLBACK_PATH.write_text(json.dumps(data, indent=2))
        return True

    def _local_retrieve(self, key: str):
        return self._load_local().get(key)


# Singleton
memory = BackboardClient()
