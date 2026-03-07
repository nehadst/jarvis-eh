"""
Feature 2 — Memory Montage (Abdullah)

Orchestrates the full montage pipeline:
  1. Load person profile from family_profiles/
  2. Ask Gemini to write a warm narration script from the profile data
  3. Synthesise the narration with ElevenLabs and upload the mp3 to Cloudinary
  4. Build the Cloudinary Ken Burns slideshow URL with the audio overlaid
  5. Trigger eager pre-render so the video is ready immediately
  6. Return a structured result dict that main.py broadcasts as a WS event

Trigger modes:
  - Automatic: called by FaceRecognizer immediately after a confident match
    (debounced — at most once per person per MONTAGE_COOLDOWN_SECONDS)
  - On-demand: called by the POST /api/montage/{person_id} route, with an
    optional tag_filter query param for themed montages ("christmas", etc.)

Usage:
    from features.memory_montage.builder import MontageBuilder

    builder = MontageBuilder()
    result = builder.build("sarah_johnson")
    # result = {
    #   "type": "montage_ready",
    #   "person_id": "sarah_johnson",
    #   "person": "Sarah Johnson",
    #   "relationship": "granddaughter",
    #   "montage_url": "https://res.cloudinary.com/...",
    #   "narration": "Here are some beautiful photos of Sarah...",
    #   "tag_filter": None,
    # }
"""

import json
import time
from pathlib import Path
from typing import Callable, Optional

from config import FAMILY_PROFILES_PATH
from services.cloudinary_client import cloud
from services.gemini_client import gemini
from services.elevenlabs_client import tts

# Only trigger a montage for the same person this often (seconds)
MONTAGE_COOLDOWN_SECONDS = 300  # 5 minutes


class MontageBuilder:
    def __init__(self, on_event: Callable[[dict], None] | None = None) -> None:
        self.on_event = on_event or (lambda e: None)
        self._last_built: dict[str, float] = {}  # person_id → epoch timestamp

    # ── Public API ─────────────────────────────────────────────────────────────

    def build(
        self,
        person_id: str,
        tag_filter: Optional[str] = None,
        force: bool = False,
    ) -> Optional[dict]:
        """
        Build a memory montage for person_id and fire an event.

        Args:
            person_id:  Must match a JSON file in data/family_profiles/.
            tag_filter: Optional Cloudinary tag to narrow the photo selection
                        (e.g. "christmas" shows only photos tagged 'christmas').
            force:      Skip the cooldown check — use for on-demand requests.

        Returns:
            The event dict that was broadcast, or None if skipped / failed.
        """
        # Cooldown guard (skip for on-demand / forced calls)
        if not force:
            now = time.time()
            last = self._last_built.get(person_id, 0)
            if now - last < MONTAGE_COOLDOWN_SECONDS:
                return None

        profile = self._load_profile(person_id)
        if not profile:
            print(f"[MontageBuilder] No profile found for '{person_id}'")
            return None

        name = profile.get("name", person_id)
        relationship = profile.get("relationship", "family member")
        notes: list[str] = profile.get("notes", [])
        personal_detail: str = profile.get("personal_detail", "")
        last_interaction: str = (
            profile.get("last_interaction", {}).get("summary", "a while ago")
        )

        # ── Step 1: Generate narration script via Gemini ──────────────────────
        narration_text = self._generate_narration(
            name=name,
            relationship=relationship,
            notes=notes,
            last_interaction=last_interaction,
            personal_detail=personal_detail,
            tag_filter=tag_filter,
        )

        # ── Step 2: Synthesise + upload narration audio ───────────────────────
        audio_public_id: Optional[str] = None
        if tts and cloud and narration_text:
            audio_public_id = self._synthesise_and_upload(
                text=narration_text,
                label=f"{person_id}_montage",
            )

        # ── Step 3: Build Cloudinary montage URL ──────────────────────────────
        montage_url = ""
        if cloud:
            montage_url = cloud.build_montage_url(
                person_id=person_id,
                audio_public_id=audio_public_id,
                tag_filter=tag_filter,
            )

        if not montage_url:
            print(
                f"[MontageBuilder] No photos found in Cloudinary for '{person_id}'"
                + (f" with tag '{tag_filter}'" if tag_filter else "")
            )
            # Still fire an event so the dashboard shows a useful message
            montage_url = ""

        # ── Step 4: Record cooldown + broadcast event ─────────────────────────
        self._last_built[person_id] = time.time()

        event = {
            "type": "montage_ready",
            "person_id": person_id,
            "person": name,
            "relationship": relationship,
            "montage_url": montage_url,
            "narration": narration_text,
            "tag_filter": tag_filter,
        }
        self.on_event(event)
        return event

    # ── Private helpers ────────────────────────────────────────────────────────

    def _load_profile(self, person_id: str) -> Optional[dict]:
        path = FAMILY_PROFILES_PATH / f"{person_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception as e:
            print(f"[MontageBuilder] Failed to parse profile '{person_id}': {e}")
            return None

    def _generate_narration(
        self,
        name: str,
        relationship: str,
        notes: list[str],
        last_interaction: str,
        personal_detail: str,
        tag_filter: Optional[str],
    ) -> str:
        """Ask Gemini to write the narration. Falls back to a simple default."""
        if not gemini:
            return f"Here are some beautiful photos of {name}, your {relationship}."

        try:
            from config import settings
            prompt = gemini.build_montage_narration_prompt(
                name=name,
                relationship=relationship,
                notes=notes,
                last_interaction=last_interaction,
                personal_detail=personal_detail,
                patient_name=settings.patient_name,
                tag_filter=tag_filter,
            )
            return gemini.generate(prompt)
        except Exception as e:
            print(f"[MontageBuilder] Gemini narration error: {e}")
            return f"Here are some beautiful photos of {name}, your {relationship}."

    def _synthesise_and_upload(self, text: str, label: str) -> Optional[str]:
        """
        Convert narration text to speech via ElevenLabs, then upload the mp3
        bytes directly to Cloudinary. Returns the Cloudinary public_id.
        """
        if not tts or not cloud:
            return None
        try:
            # Collect audio bytes using ElevenLabs client
            audio_iter = tts._client.text_to_speech.convert(
                voice_id=tts._default_voice_id,
                text=text,
                model_id="eleven_turbo_v2",
            )
            audio_bytes = b"".join(audio_iter)
            return cloud.upload_audio_bytes(audio_bytes, label=label)
        except Exception as e:
            print(f"[MontageBuilder] ElevenLabs/upload error: {e}")
            return None
