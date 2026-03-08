"""
Backboard.io client — persistent semantic memory for REWIND.

Architecture:
  - SQLite (local): thread-safe structured storage with precise timestamps.
    Used for fast reads on the hot path (face cooldowns, activity lookups).
  - Backboard API (cloud): semantic memory that persists across sessions
    and enables cross-feature context retrieval.

Both are written to on every event. SQLite handles store/retrieve (fast).
Backboard handles intelligent query() for semantic cross-feature context.

Usage:
    from services.backboard_client import memory

    memory.store("last_activity", {"activity": "making tea"})
    data = memory.retrieve("last_activity")                    # fast local read
    context = memory.query("What has Dad been doing today?")   # semantic search
    events = memory.get_events("interactions_ronaldo", since=time.time() - 3600)
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import requests
from config import settings


_DB_PATH = Path(__file__).parent.parent / "data" / "rewind.db"
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

        # SQLite local storage (thread-safe)
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        self._db_lock = threading.Lock()
        self._init_db()
        self._migrate_json()

        # Auto-create Backboard assistant if needed
        if self._use_api and not self._assistant_id:
            self._auto_create_assistant()
        elif self._use_api:
            print(f"[Backboard] Connected — assistant {self._assistant_id[:12]}...")

    # ── Database setup ─────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._db_lock:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS kv (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    timestamp REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_key_ts
                    ON events(key, timestamp);
            """)

    def _migrate_json(self) -> None:
        """One-time migration from old JSON fallback to SQLite."""
        if not _FALLBACK_PATH.exists():
            return
        try:
            data = json.loads(_FALLBACK_PATH.read_text())
            if not data:
                return
            with self._db_lock:
                for key, value in data.items():
                    if isinstance(value, list):
                        for item in value:
                            ts = (
                                item.get("timestamp", item.get("time", time.time()))
                                if isinstance(item, dict)
                                else time.time()
                            )
                            self._db.execute(
                                "INSERT INTO events (key, value, timestamp) VALUES (?, ?, ?)",
                                (key, json.dumps(item), ts),
                            )
                    else:
                        self._db.execute(
                            "INSERT OR REPLACE INTO kv (key, value, updated_at) VALUES (?, ?, ?)",
                            (key, json.dumps(value), time.time()),
                        )
                self._db.commit()
            _FALLBACK_PATH.rename(_FALLBACK_PATH.with_suffix(".json.bak"))
            print("[Memory] Migrated JSON data to SQLite")
        except Exception as e:
            print(f"[Memory] JSON migration failed (non-fatal): {e}")

    # ── Public interface (backward-compatible) ─────────────────────────────

    def store(self, key: str, value: dict | str | list) -> bool:
        """Store a single value locally + push to Backboard."""
        self._local_store(key, value)
        if self._use_api and self._assistant_id and not isinstance(value, list):
            threading.Thread(
                target=self._push_memory,
                args=(key, value),
                daemon=True,
            ).start()
        return True

    def retrieve(self, key: str) -> dict | str | list | None:
        """Fast local read. Returns list for append-style keys, dict/str for store-style."""
        return self._local_retrieve(key)

    def append(self, key: str, item: dict) -> bool:
        """Append an event locally + push to Backboard."""
        self._local_append(key, item)
        if self._use_api and self._assistant_id:
            threading.Thread(
                target=self._push_memory,
                args=(key, item),
                daemon=True,
            ).start()
        return True

    def get_events(self, key: str, since: float | None = None, limit: int = 50) -> list[dict]:
        """
        Get events for a key with optional time filter. Returns newest first.
        Use for precise queries like 'all Ronaldo appearances in the last hour'.
        """
        with self._db_lock:
            if since:
                rows = self._db.execute(
                    "SELECT value, timestamp FROM events WHERE key = ? AND timestamp > ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (key, since, limit),
                ).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT value, timestamp FROM events WHERE key = ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (key, limit),
                ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def query(self, question: str) -> str:
        """
        Semantic query across all stored memories via Backboard.
        Creates a thread, sends the question with memory="Auto",
        returns the AI response enriched with recalled memories.
        """
        if not self._use_api or not self._assistant_id:
            return ""
        try:
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
        """Add a memory to the Backboard assistant (background thread)."""
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

    # ── SQLite local storage ───────────────────────────────────────────────

    def _local_store(self, key: str, value) -> bool:
        with self._db_lock:
            self._db.execute(
                "INSERT OR REPLACE INTO kv (key, value, updated_at) VALUES (?, ?, ?)",
                (key, json.dumps(value), time.time()),
            )
            self._db.commit()
        return True

    def _local_retrieve(self, key: str):
        with self._db_lock:
            # Check events table first (for append-style keys)
            rows = self._db.execute(
                "SELECT value FROM events WHERE key = ? ORDER BY timestamp ASC",
                (key,),
            ).fetchall()
            if rows:
                return [json.loads(r[0]) for r in rows]

            # Fall back to kv table (for single-value keys)
            row = self._db.execute(
                "SELECT value FROM kv WHERE key = ?",
                (key,),
            ).fetchone()
            if row:
                return json.loads(row[0])
            return None

    def _local_append(self, key: str, item: dict) -> bool:
        with self._db_lock:
            ts = (
                item.get("timestamp", item.get("time", time.time()))
                if isinstance(item, dict)
                else time.time()
            )
            self._db.execute(
                "INSERT INTO events (key, value, timestamp) VALUES (?, ?, ?)",
                (key, json.dumps(item), ts),
            )
            # Prune: keep last 50 entries per key
            self._db.execute(
                "DELETE FROM events WHERE key = ? AND id NOT IN ("
                "  SELECT id FROM events WHERE key = ? ORDER BY timestamp DESC LIMIT 50"
                ")",
                (key, key),
            )
            self._db.commit()
        return True


# Singleton
memory = BackboardClient()
