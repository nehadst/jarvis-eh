"""
Face Sensor — real-time face detection + recognition.

Refactored from features/face_recognition/recognizer.py.
Keeps: InsightFace init, embedding management, overlay drawing.
Removes: TTS, LLM generation, montage triggering, memory helpers.
Instead emits FACE_DETECTED signals for the Jarvis agent to handle.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from insightface.app import FaceAnalysis

from agent.signal_bus import Signal, SignalBus, SignalType, Priority
from config import settings, FACE_DB_PATH, FAMILY_PROFILES_PATH


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class FaceSensor:
    def __init__(self, bus: SignalBus) -> None:
        self._bus = bus
        self._last_identified: dict[str, float] = {}
        self._profiles: dict[str, dict] = self._load_profiles()

        # Presence tracking — when was each person last seen in frame
        self._present_persons: dict[str, float] = {}

        # Overlay state — drawn on the live stream by the orchestrator
        self._overlay_lock = threading.Lock()
        self._overlay: dict | None = None

        # ── InsightFace initialization ────────────────────────────────────
        det_size = settings.face_det_size
        print(f"[FaceSensor] Loading InsightFace model '{settings.face_model}' "
              f"(det_size={det_size})...")

        self._app = FaceAnalysis(
            name=settings.face_model,
            allowed_modules=["detection", "recognition"],
            providers=["CPUExecutionProvider"],
        )
        self._app.prepare(ctx_id=-1, det_size=(det_size, det_size))
        print("[FaceSensor] InsightFace ready.")

        # ── Pre-compute embeddings for all family photos ──────────────────
        self._family_embeddings: dict[str, list[tuple[np.ndarray, str]]] = {}
        self._build_embeddings()

    # ── Public ────────────────────────────────────────────────────────────────

    def process(self, frame: np.ndarray) -> None:
        """
        Detect faces, emit FACE_DETECTED signal, track presence,
        and emit FACE_DEPARTED when a person leaves the frame.
        """
        if self._family_embeddings:
            faces = self._app.get(frame)
            if faces:
                self._process_faces(faces, frame)

        # Always check for departures (even when no faces detected this frame)
        self._check_departures()

    def _process_faces(self, faces, frame: np.ndarray) -> None:
        """Match detected faces against family embeddings."""
        for face in faces:
            if face.det_score < 0.5:
                continue

            best_person_id: str | None = None
            best_score: float = 0.0
            query_emb = face.normed_embedding

            for person_id, ref_list in self._family_embeddings.items():
                for ref_emb, _ in ref_list:
                    score = float(np.dot(query_emb, ref_emb))
                    if score > best_score:
                        best_score = score
                        best_person_id = person_id

            if best_person_id is None or best_score < settings.face_similarity_threshold:
                continue

            profile = self._profiles.get(best_person_id)
            if not profile:
                continue

            # Track presence — update last-seen time for this person
            self._present_persons[best_person_id] = time.time()

            # Always update world state so voice commands know who's in frame
            self._bus.update_world("last_detected_face", {
                "person_id": best_person_id,
                "profile": profile,
                "time": time.time(),
                "similarity": round(best_score, 3),
            })

            # Cooldown — skip signal emission if recently identified
            now = time.time()
            last = self._last_identified.get(best_person_id, 0)
            if now - last < settings.face_cooldown_seconds:
                continue
            self._last_identified[best_person_id] = now

            # Convert bbox
            bbox = face.bbox.astype(int)
            bbox_xywh = (int(bbox[0]), int(bbox[1]),
                         int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1]))
            frame_shape = frame.shape[:2]  # (h, w)

            # Emit signal for the agent
            self._bus.emit(Signal(
                type=SignalType.FACE_DETECTED,
                priority=Priority.HIGH,
                data={
                    "person_id": best_person_id,
                    "profile": profile,
                    "similarity": best_score,
                    "bbox": bbox_xywh,
                    "frame_shape": frame_shape,
                },
            ))

            break  # handle one face per frame

    def _check_departures(self) -> None:
        """Emit FACE_DEPARTED for persons not seen within the grace period."""
        now = time.time()
        grace = settings.conversation_departure_grace
        departed = [
            pid for pid, last_seen in self._present_persons.items()
            if now - last_seen > grace
        ]
        for person_id in departed:
            del self._present_persons[person_id]
            profile = self._profiles.get(person_id, {})
            self._bus.emit(Signal(
                type=SignalType.FACE_DEPARTED,
                priority=Priority.LOW,
                data={
                    "person_id": person_id,
                    "profile": profile,
                    "name": profile.get("name", person_id),
                    "relationship": profile.get("relationship", "person"),
                },
            ))
            print(f"[FaceSensor] {profile.get('name', person_id)} departed "
                  f"(not seen for {grace:.0f}s)")

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
        """No-op — overlay removed. Returns the frame unchanged."""
        return frame

    # ── Embedding management ──────────────────────────────────────────────────

    def _build_embeddings(self) -> None:
        """Scan face_db/ and compute embeddings for every reference photo."""
        self._family_embeddings = {}

        if not FACE_DB_PATH.exists():
            print("[FaceSensor] No face_db directory found.")
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
                    print(f"[FaceSensor] Could not read: {img_path}")
                    continue

                faces = self._app.get(img)
                if not faces:
                    print(f"[FaceSensor] No face found in: {img_path.name}")
                    continue

                largest = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
                embeddings.append((largest.normed_embedding, str(img_path)))

            if embeddings:
                self._family_embeddings[person_id] = embeddings
                total += len(embeddings)
                print(f"[FaceSensor]   {person_id}: {len(embeddings)} photo(s) embedded")

        print(f"[FaceSensor] Ready — {len(self._family_embeddings)} people, {total} embeddings total")

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
