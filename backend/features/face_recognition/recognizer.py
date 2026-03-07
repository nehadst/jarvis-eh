"""
Feature 1 — Face Recognition (Maaz)

Matches a live frame against the family face database using DeepFace.
Fires an event when a known person is identified.

Face DB structure:
    backend/data/face_db/
        sarah_johnson/
            img1.jpg
            img2.jpg
        david_smith/
            img1.jpg

Each subfolder name must match the person's id field in their profile JSON.
"""

import json
import os
import threading
import time
import tempfile
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from deepface import DeepFace

from config import settings, FACE_DB_PATH, FAMILY_PROFILES_PATH
from services.gemini_client import gemini
from services.elevenlabs_client import tts
from services.backboard_client import memory


class FaceRecognizer:
    def __init__(self, on_event: Callable[[dict], None] | None = None) -> None:
        self.on_event = on_event or (lambda e: None)
        self._last_identified: dict[str, float] = {}  # person_id → last timestamp
        self._profiles: dict[str, dict] = self._load_profiles()

        # Lazy-import to avoid circular deps; builder is created once on first use
        self._montage_builder = None

    # ── Public ────────────────────────────────────────────────────────────────

    def process(self, frame: np.ndarray) -> None:
        """
        Run face detection + recognition on a frame.
        If a known person is found (and cooldown has passed), fire an event.
        """
        if not FACE_DB_PATH.exists() or not any(FACE_DB_PATH.iterdir()):
            return  # no face DB yet

        # Quick face presence check before running the expensive model
        if not self._face_is_present(frame):
            return

        # Save frame to a temp file — DeepFace.find expects a path
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            cv2.imwrite(tmp.name, frame)
            tmp_path = tmp.name

        try:
            results = DeepFace.find(
                img_path=tmp_path,
                db_path=str(FACE_DB_PATH),
                model_name=settings.face_model,
                detector_backend=settings.face_detector,
                distance_metric="cosine",
                enforce_detection=True,
                silent=True,
            )
        except Exception:
            return
        finally:
            os.unlink(tmp_path)

        if not results or results[0].empty:
            return

        df = results[0].sort_values("distance")
        best = df.iloc[0]

        if best["distance"] > settings.face_distance_threshold:
            return  # below confidence threshold

        # Extract person_id from the matched path (the subfolder name)
        matched_path = Path(best["identity"])
        person_id = matched_path.parent.name

        # Cooldown — don't repeat for the same person within N seconds
        now = time.time()
        last = self._last_identified.get(person_id, 0)
        if now - last < settings.face_cooldown_seconds:
            return
        self._last_identified[person_id] = now

        profile = self._profiles.get(person_id)
        if not profile:
            return

        self._handle_recognition(person_id, profile, float(best["distance"]))

    # ── Private ───────────────────────────────────────────────────────────────

    def _handle_recognition(self, person_id: str, profile: dict, distance: float) -> None:
        """Generate the whisper and fire the event."""
        name = profile.get("name", person_id)
        relationship = profile.get("relationship", "person")
        last_interaction = profile.get("last_interaction", {}).get(
            "summary", "you haven't seen them in a while"
        )
        personal_detail = profile.get("personal_detail", "")

        # Generate warm whisper via Gemini
        whisper_text = ""
        if gemini:
            try:
                prompt = gemini.build_whisper_prompt(
                    name=name,
                    relationship=relationship,
                    last_interaction=last_interaction,
                    personal_detail=personal_detail,
                    patient_name=settings.patient_name,
                )
                whisper_text = gemini.generate(prompt)
            except Exception as e:
                print(f"[FaceRecognizer] Gemini error: {e}")
                whisper_text = f"That's {name}, your {relationship}."

        # Play the whisper through speakers
        if tts and whisper_text:
            tts.speak(whisper_text)

        # Persist the interaction to memory
        memory.append(f"interactions_{person_id}", {
            "timestamp": time.time(),
            "event": "face_recognized",
            "whisper": whisper_text,
        })

        # Fire the dashboard event
        self.on_event({
            "type": "face_recognized",
            "person_id": person_id,
            "person": name,
            "relationship": relationship,
            "confidence": round(1 - distance, 3),
            "whisper": whisper_text,
        })

        # Trigger a memory montage in the background (non-blocking)
        # The builder has its own cooldown so rapid re-recognitions are no-ops.
        threading.Thread(
            target=self._trigger_montage,
            args=(person_id,),
            daemon=True,
        ).start()

    def _trigger_montage(self, person_id: str) -> None:
        """
        Runs in a daemon thread. Builds the memory montage and fires a
        montage_ready event through on_event (which broadcasts to the dashboard).
        """
        try:
            builder = self._get_montage_builder()
            if builder:
                builder.build(person_id, force=False)
        except Exception as e:
            print(f"[FaceRecognizer] Montage build error for '{person_id}': {e}")

    def _get_montage_builder(self):
        """Lazily initialise MontageBuilder to avoid circular imports at module load."""
        if self._montage_builder is None:
            try:
                from features.memory_montage.builder import MontageBuilder
                self._montage_builder = MontageBuilder(on_event=self.on_event)
            except Exception as e:
                print(f"[FaceRecognizer] Could not initialise MontageBuilder: {e}")
        return self._montage_builder

    def _face_is_present(self, frame: np.ndarray) -> bool:
        """Fast check using OpenCV haar cascade before running DeepFace."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
        return len(faces) > 0

    def _load_profiles(self) -> dict[str, dict]:
        profiles: dict[str, dict] = {}
        if not FAMILY_PROFILES_PATH.exists():
            return profiles
        for f in FAMILY_PROFILES_PATH.glob("*.json"):
            try:
                profile = json.loads(f.read_text())
                person_id = profile.get("id", f.stem)
                profiles[person_id] = profile
            except Exception:
                pass
        return profiles

    def reload_profiles(self) -> None:
        """Hot-reload profiles without restarting (call after dashboard upload)."""
        self._profiles = self._load_profiles()
