"""
Feature 1 — Face Recognition (Maaz)

Uses InsightFace (ONNX) for real-time face detection + recognition.
Single-pass pipeline: detect -> align -> embed -> match in ~30-50ms.

Old pipeline (DeepFace):  Haar cascade -> write temp file -> RetinaFace CNN
                          -> ArcFace embed -> compare  (~600-2000ms)

New pipeline (InsightFace): app.get(frame) -> cosine similarity  (~30-50ms)

Face DB structure:
    backend/data/face_db/
        sarah_johnson/
            img1.jpg
            img2.jpg
        david_smith/
            img1.jpg

Each subfolder name must match the person's id field in their profile JSON.

On startup, all reference photos are embedded once and stored in memory.
At runtime, only a single forward pass + vector comparison is needed.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from insightface.app import FaceAnalysis

from config import settings, FACE_DB_PATH, FAMILY_PROFILES_PATH
from services.gemini_client import gemini
from services.elevenlabs_client import tts
from services.backboard_client import memory


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class FaceRecognizer:
    def __init__(self, on_event: Callable[[dict], None] | None = None) -> None:
        self.on_event = on_event or (lambda e: None)
        self._last_identified: dict[str, float] = {}
        self._profiles: dict[str, dict] = self._load_profiles()

        # Montage builder (lazy init to avoid circular imports)
        self._montage_builder = None

        # Overlay state — drawn on the live stream by the orchestrator
        self._overlay_lock = threading.Lock()
        self._overlay: dict | None = None

        # ── InsightFace initialization ────────────────────────────────────
        det_size = settings.face_det_size
        print(f"[FaceRecognizer] Loading InsightFace model '{settings.face_model}' "
              f"(det_size={det_size})...")

        self._app = FaceAnalysis(
            name=settings.face_model,
            allowed_modules=["detection", "recognition"],
            providers=["CPUExecutionProvider"],
        )
        self._app.prepare(ctx_id=-1, det_size=(det_size, det_size))
        print("[FaceRecognizer] InsightFace ready.")

        # ── Pre-compute embeddings for all family photos ──────────────────
        # { person_id: [ (normed_embedding, photo_path_str), ... ] }
        self._family_embeddings: dict[str, list[tuple[np.ndarray, str]]] = {}
        self._build_embeddings()

    # ── Public ────────────────────────────────────────────────────────────────

    def process(self, frame: np.ndarray) -> None:
        """
        Detect faces in a frame and match against the family database.
        Single forward pass — no temp files, no two-stage detection.
        """
        if not self._family_embeddings:
            return

        # One call: detect all faces + compute their embeddings (~30-50ms)
        faces = self._app.get(frame)
        if not faces:
            return

        for face in faces:
            # Skip low-confidence detections
            if face.det_score < 0.5:
                continue

            # Compare this face's embedding against every stored family embedding
            best_person_id: str | None = None
            best_score: float = 0.0

            query_emb = face.normed_embedding

            for person_id, ref_list in self._family_embeddings.items():
                for ref_emb, _ in ref_list:
                    # Cosine similarity (both are L2-normalized, so dot product = cosine)
                    score = float(np.dot(query_emb, ref_emb))
                    if score > best_score:
                        best_score = score
                        best_person_id = person_id

            if best_person_id is None or best_score < settings.face_similarity_threshold:
                continue

            # Cooldown — don't re-identify the same person within N seconds
            now = time.time()
            last = self._last_identified.get(best_person_id, 0)
            if now - last < settings.face_cooldown_seconds:
                continue
            self._last_identified[best_person_id] = now

            profile = self._profiles.get(best_person_id)
            if not profile:
                continue

            # Convert InsightFace bbox [x1, y1, x2, y2] -> (x, y, w, h) for overlay
            bbox = face.bbox.astype(int)
            self._last_bbox = (int(bbox[0]), int(bbox[1]),
                               int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1]))

            self._handle_recognition(best_person_id, profile, best_score)
            break  # handle one face per frame to avoid spamming

    def rebuild_embeddings(self) -> None:
        """Recompute all embeddings + reload profiles. Called after photo upload/delete."""
        self._profiles = self._load_profiles()
        self._build_embeddings()

    def reload_profiles(self) -> None:
        """Backwards-compatible alias."""
        self.rebuild_embeddings()

    # ── Overlay (drawn on stream by orchestrator) ─────────────────────────────

    def get_overlay(self) -> dict | None:
        with self._overlay_lock:
            if self._overlay and time.time() < self._overlay["expires"]:
                return self._overlay
            self._overlay = None
            return None

    def draw_overlay(self, frame: np.ndarray) -> np.ndarray:
        """Draw face recognition box + label on a frame. Returns a copy."""
        overlay = self.get_overlay()
        if not overlay:
            return frame

        out = frame.copy()
        x, y, w, h = overlay["bbox"]
        name = overlay["name"]
        rel = overlay["relationship"]
        conf = overlay["confidence"]
        label = f"{name} ({rel}) {conf:.0%}"

        # Purple bounding box
        cv2.rectangle(out, (x, y), (x + w, y + h), (138, 112, 255), 2)

        # Label background + text
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        cv2.rectangle(out, (x, y - th - 12), (x + tw + 8, y), (138, 112, 255), -1)
        cv2.putText(out, label, (x + 4, y - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        return out

    # ── Embedding management ──────────────────────────────────────────────────

    def _build_embeddings(self) -> None:
        """Scan face_db/ and compute embeddings for every reference photo."""
        self._family_embeddings = {}

        if not FACE_DB_PATH.exists():
            print("[FaceRecognizer] No face_db directory found.")
            return

        total = 0
        for person_dir in sorted(FACE_DB_PATH.iterdir()):
            if not person_dir.is_dir():
                continue

            person_id = person_dir.name
            embeddings: list[tuple[np.ndarray, str]] = []

            for img_path in sorted(person_dir.iterdir()):
                if img_path.suffix.lower() not in IMAGE_EXTENSIONS:
                    continue

                img = cv2.imread(str(img_path))
                if img is None:
                    print(f"[FaceRecognizer] Could not read: {img_path}")
                    continue

                faces = self._app.get(img)
                if not faces:
                    print(f"[FaceRecognizer] No face found in: {img_path.name}")
                    continue

                # Use the largest face in the reference photo
                largest = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
                embeddings.append((largest.normed_embedding, str(img_path)))

            if embeddings:
                self._family_embeddings[person_id] = embeddings
                total += len(embeddings)
                print(f"[FaceRecognizer]   {person_id}: {len(embeddings)} photo(s) embedded")

        print(f"[FaceRecognizer] Ready — {len(self._family_embeddings)} people, {total} embeddings total")

    # ── Recognition handler ───────────────────────────────────────────────────

    def _handle_recognition(self, person_id: str, profile: dict, similarity: float) -> None:
        """Generate whisper, play TTS, set overlay, fire event."""
        name = profile.get("name", person_id)
        relationship = profile.get("relationship", "person")
        personal_detail = profile.get("personal_detail", "")
        confidence = round(similarity, 3)

        # Pull the most recent interaction from Backboard memory
        last_interaction = self._get_last_interaction(person_id, profile)

        # Generate warm whisper via AI (OpenAI primary, Gemini fallback)
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
                print(f"[FaceRecognizer] AI error: {e}")
                whisper_text = f"That's {name}, your {relationship}."

        # Play through speakers
        if tts and whisper_text:
            tts.speak(whisper_text)

        # Persist interaction to memory
        now = time.time()
        memory.append(f"interactions_{person_id}", {
            "timestamp": now,
            "event": "face_recognized",
            "whisper": whisper_text,
        })

        # Update profile's last_interaction
        self._update_last_interaction(person_id, whisper_text)

        # Set overlay for the live stream (visible for 5 seconds)
        bbox = getattr(self, "_last_bbox", (0, 0, 100, 100))
        with self._overlay_lock:
            self._overlay = {
                "name": name,
                "relationship": relationship,
                "confidence": confidence,
                "bbox": bbox,
                "expires": time.time() + 5,
            }

        # Fire dashboard event
        self.on_event({
            "type": "face_recognized",
            "person_id": person_id,
            "person": name,
            "relationship": relationship,
            "confidence": confidence,
            "whisper": whisper_text,
        })

        # Trigger memory montage in background
        threading.Thread(
            target=self._trigger_montage,
            args=(person_id,),
            daemon=True,
        ).start()

    # ── Memory helpers ────────────────────────────────────────────────────────

    def _get_last_interaction(self, person_id: str, profile: dict) -> str:
        """Check Backboard for recent interactions, fall back to static profile."""
        interactions = memory.retrieve(f"interactions_{person_id}")
        if isinstance(interactions, list) and interactions:
            latest = interactions[-1]
            ts = latest.get("timestamp", 0)
            ago = time.time() - ts
            if ago < 3600:
                time_ago = f"{int(ago // 60)} minutes ago"
            elif ago < 86400:
                time_ago = f"{int(ago // 3600)} hours ago"
            else:
                time_ago = f"{int(ago // 86400)} days ago"
            if latest.get("whisper", ""):
                return f"You saw them {time_ago}"
        return profile.get("last_interaction", {}).get(
            "summary", "you haven't seen them in a while"
        )

    def _update_last_interaction(self, person_id: str, whisper_text: str) -> None:
        """Write the new last_interaction back to the profile JSON."""
        from datetime import date
        profile = self._profiles.get(person_id)
        if not profile:
            return
        profile["last_interaction"] = {
            "date": date.today().isoformat(),
            "summary": whisper_text[:120] if whisper_text else "seen today",
        }
        path = FAMILY_PROFILES_PATH / f"{person_id}.json"
        try:
            path.write_text(json.dumps(profile, indent=2))
        except Exception as e:
            print(f"[FaceRecognizer] Could not update profile {person_id}: {e}")

    # ── Montage ───────────────────────────────────────────────────────────────

    def _trigger_montage(self, person_id: str) -> None:
        try:
            builder = self._get_montage_builder()
            if builder:
                builder.build(person_id, force=False)
        except Exception as e:
            print(f"[FaceRecognizer] Montage build error for '{person_id}': {e}")

    def _get_montage_builder(self):
        if self._montage_builder is None:
            try:
                from features.memory_montage.builder import MontageBuilder
                self._montage_builder = MontageBuilder(on_event=self.on_event)
            except Exception as e:
                print(f"[FaceRecognizer] Could not initialise MontageBuilder: {e}")
        return self._montage_builder

    # ── Profile loading ───────────────────────────────────────────────────────

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
