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
        Detect faces and emit FACE_DETECTED signal instead of handling inline.
        """
        if not self._family_embeddings:
            return

        faces = self._app.get(frame)
        if not faces:
            return

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

            # Cooldown
            now = time.time()
            last = self._last_identified.get(best_person_id, 0)
            if now - last < settings.face_cooldown_seconds:
                continue
            self._last_identified[best_person_id] = now

            profile = self._profiles.get(best_person_id)
            if not profile:
                continue

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

            # Set overlay immediately (visual feedback shouldn't wait for agent)
            name = profile.get("name", best_person_id)
            relationship = profile.get("relationship", "person")
            with self._overlay_lock:
                self._overlay = {
                    "name": name,
                    "relationship": relationship,
                    "confidence": round(best_score, 3),
                    "bbox": bbox_xywh,
                    "expires": time.time() + 5,
                }

            break  # handle one face per frame

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

        cv2.rectangle(out, (x, y), (x + w, y + h), (138, 112, 255), 2)
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
