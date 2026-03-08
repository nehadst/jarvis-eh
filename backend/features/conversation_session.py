"""
Conversation Session Manager — tracks full conversations per person visit.

When a person is recognized (FACE_DETECTED), a session starts and continuously
accumulates transcript from the audio sensor.  When the person leaves
(FACE_DEPARTED), the session ends, an LLM summary is generated, and the full
transcript + summary are stored in memory.

Next time the person returns, _get_last_encounter_context can pull the
conversation summary for a richer, more personal greeting.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from config import settings
from services.backboard_client import memory
from services.gemini_client import gemini


@dataclass
class ConversationSession:
    person_id: str
    name: str
    relationship: str
    start_time: float
    transcript_parts: list[dict] = field(default_factory=list)
    last_consumed_time: float = 0.0


class ConversationSessionManager:
    """Manages per-person conversation sessions from face arrival to departure."""

    def __init__(self) -> None:
        self._active_sessions: dict[str, ConversationSession] = {}
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    def start_session(self, person_id: str, name: str, relationship: str) -> None:
        """Start recording conversation for a person. Idempotent if already active."""
        with self._lock:
            if person_id in self._active_sessions:
                return
            session = ConversationSession(
                person_id=person_id,
                name=name,
                relationship=relationship,
                start_time=time.time(),
                last_consumed_time=time.time(),
            )
            self._active_sessions[person_id] = session
        print(f"[ConversationSession] Started for {name} ({person_id})")

    def end_session(self, person_id: str) -> dict | None:
        """
        End session, generate summary, store in memory.
        Returns the conversation record or None if session was too short / empty.
        """
        with self._lock:
            session = self._active_sessions.pop(person_id, None)

        if session is None:
            return None

        duration = time.time() - session.start_time
        full_transcript = " ".join(p["text"] for p in session.transcript_parts).strip()

        print(f"[ConversationSession] Ended for {session.name} — "
              f"{duration:.0f}s, {len(session.transcript_parts)} chunks, "
              f"{len(full_transcript)} chars")

        # Skip if too short or no meaningful transcript
        if duration < settings.conversation_min_duration:
            print(f"[ConversationSession] Skipped — duration {duration:.0f}s "
                  f"< minimum {settings.conversation_min_duration:.0f}s")
            return None

        if not full_transcript or len(full_transcript) < 20:
            print("[ConversationSession] Skipped — transcript too short")
            return None

        # Generate LLM summary
        summary = self._generate_summary(session, full_transcript)

        # Store in memory
        record = {
            "timestamp": time.time(),
            "start_time": session.start_time,
            "end_time": time.time(),
            "duration_seconds": round(duration, 1),
            "person_id": person_id,
            "name": session.name,
            "relationship": session.relationship,
            "transcript": full_transcript,
            "summary": summary,
        }
        memory.append(f"conversations_{person_id}", record)

        print(f"[ConversationSession] Saved — summary: {summary[:100]}...")
        return record

    def accumulate_transcript(self, world: dict[str, Any]) -> None:
        """
        Pull new transcript entries from world state into all active sessions.
        Called every agent tick.
        """
        entries = world.get("transcript_entries", [])
        if not entries:
            return

        with self._lock:
            for session in self._active_sessions.values():
                new_entries = [
                    e for e in entries
                    if e["time"] > session.last_consumed_time
                ]
                if new_entries:
                    session.transcript_parts.extend(new_entries)
                    session.last_consumed_time = new_entries[-1]["time"]
                    new_text = " ".join(e["text"] for e in new_entries)
                    total = len(session.transcript_parts)
                    elapsed = int(time.time() - session.start_time)
                    print(f"[ConversationSession] {session.name} +{len(new_entries)} chunk(s) "
                          f"| total: {total} chunks, {elapsed}s elapsed "
                          f"| \"{new_text[:80]}\"")

            # Check for sessions that exceeded max duration
            self._check_max_duration()

    def has_active_session(self, person_id: str) -> bool:
        with self._lock:
            return person_id in self._active_sessions

    def get_active_person_ids(self) -> list[str]:
        with self._lock:
            return list(self._active_sessions.keys())

    # ── Context retrieval for face greetings ──────────────────────────────────

    @staticmethod
    def get_conversation_context(person_id: str, limit: int = 3) -> str:
        """
        Get past conversation summaries for a person.
        Returns a context string for use in face whisper generation.
        """
        convos = memory.get_events(f"conversations_{person_id}", limit=limit)
        if not convos:
            return ""

        parts = []
        for c in convos:
            ts = c.get("timestamp", c.get("end_time", 0))
            ago = time.time() - ts

            if ago < 60:
                time_ago = "just now"
            elif ago < 3600:
                time_ago = f"{int(ago // 60)} minutes ago"
            elif ago < 86400:
                hours = int(ago // 3600)
                time_ago = f"{hours} hour{'s' if hours != 1 else ''} ago"
            else:
                days = int(ago // 86400)
                time_ago = "yesterday" if days == 1 else f"{days} days ago"

            summary = c.get("summary", "")
            duration = c.get("duration_seconds", 0)
            if summary:
                parts.append(f"Conversation {time_ago} ({duration:.0f}s): {summary}")

        return " | ".join(parts)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _check_max_duration(self) -> None:
        """Auto-end sessions that exceed max duration. Called under lock."""
        now = time.time()
        max_dur = settings.conversation_max_duration
        expired = [
            pid for pid, s in self._active_sessions.items()
            if now - s.start_time > max_dur
        ]
        for person_id in expired:
            session = self._active_sessions.pop(person_id)
            print(f"[ConversationSession] Auto-ending {session.name} "
                  f"(exceeded {max_dur:.0f}s max)")
            # Run end logic outside lock
            threading.Thread(
                target=self._finalize_session,
                args=(session,),
                daemon=True,
            ).start()

    def _finalize_session(self, session: ConversationSession) -> None:
        """Finalize an auto-ended session (runs in background thread)."""
        full_transcript = " ".join(p["text"] for p in session.transcript_parts).strip()
        duration = time.time() - session.start_time

        if not full_transcript or len(full_transcript) < 20:
            return

        summary = self._generate_summary(session, full_transcript)
        record = {
            "timestamp": time.time(),
            "start_time": session.start_time,
            "end_time": time.time(),
            "duration_seconds": round(duration, 1),
            "person_id": session.person_id,
            "name": session.name,
            "relationship": session.relationship,
            "transcript": full_transcript,
            "summary": summary,
        }
        memory.append(f"conversations_{session.person_id}", record)
        print(f"[ConversationSession] Auto-saved for {session.name}")

    @staticmethod
    def _generate_summary(session: ConversationSession, transcript: str) -> str:
        """Generate an LLM summary of the conversation."""
        if not gemini:
            # Fallback: first 200 chars of transcript
            return transcript[:200]

        # Truncate very long transcripts to fit in context
        truncated = transcript[:3000]
        if len(transcript) > 3000:
            truncated += "... [truncated]"

        prompt = f"""You are summarizing a conversation between {settings.patient_name} \
(a person with dementia) and {session.name} (their {session.relationship}).

Duration: {time.time() - session.start_time:.0f} seconds

Transcript:
{truncated}

Write a concise 2-3 sentence summary that captures:
- The main topics discussed
- Any important details, promises, or plans mentioned
- The emotional tone of the conversation

This summary will be used to remind {settings.patient_name} about this conversation \
next time they see {session.name}. Keep it warm and simple.

Only output the summary text."""

        try:
            return gemini.generate(prompt)
        except Exception as e:
            print(f"[ConversationSession] Summary generation failed: {e}")
            return transcript[:200]
