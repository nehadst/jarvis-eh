"""
Encounter Recorder — capture a 10-second clip + 3 snapshot photos of a real encounter.

When face recognition identifies a family member, this module:
  1. Flushes a 3-second pre-buffer (ring buffer at 10fps) so the clip starts before recognition
  2. Continues recording for the remaining seconds (total = 10s)
  3. Extracts 3 snapshots at t=0s, t=5s, t=10s
  4. Uploads the MP4 + 3 JPEG snapshots to Cloudinary in a background thread
  5. Fires events so the dashboard can display/play them

Thread-safe with a concurrent guard — only one recording at a time.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from collections import deque
from typing import Callable

import cv2
import numpy as np

from config import settings
from services.cloudinary_client import cloud
from services.backboard_client import memory


class EncounterRecorder:
    def __init__(self, on_event: Callable[[dict], None] | None = None) -> None:
        self.on_event = on_event or (lambda e: None)

        self._fps = settings.encounter_record_fps
        self._duration = settings.encounter_record_duration
        self._pre_buffer_seconds = settings.encounter_pre_buffer_seconds
        self._snapshot_count = settings.encounter_snapshot_count

        # Pre-buffer: ring buffer holding last N seconds at target fps
        max_pre_frames = int(self._pre_buffer_seconds * self._fps)
        self._pre_buffer: deque[np.ndarray] = deque(maxlen=max_pre_frames)

        # Recording state
        self._recording = False
        self._recording_lock = threading.Lock()
        self._writer: cv2.VideoWriter | None = None
        self._tmp_path: str = ""
        self._recorded_frames: list[np.ndarray] = []
        self._total_target_frames: int = int(self._duration * self._fps)
        self._frame_count: int = 0
        self._person_id: str = ""
        self._person_name: str = ""
        self._relationship: str = ""

        # Throttle feed_frame to target fps
        self._last_feed_time: float = 0.0
        self._feed_interval: float = 1.0 / self._fps

    def feed_frame(self, frame: np.ndarray) -> None:
        """Called every frame from the capture loop. Throttled to target fps."""
        now = time.time()
        if now - self._last_feed_time < self._feed_interval:
            return
        self._last_feed_time = now

        with self._recording_lock:
            if self._recording:
                self._recorded_frames.append(frame.copy())
                self._frame_count += 1

                # Check if we've captured enough frames
                pre_count = len([f for f in self._recorded_frames if f is not None])
                if pre_count >= self._total_target_frames:
                    self._recording = False
                    threading.Thread(
                        target=self._finalize,
                        daemon=True,
                    ).start()
            else:
                # Feed into pre-buffer
                self._pre_buffer.append(frame.copy())

    def start_recording(self, person_id: str, name: str, relationship: str) -> bool:
        """
        Start an encounter recording. Returns False if already recording.
        Called by face recognition when a family member is identified.
        """
        with self._recording_lock:
            if self._recording:
                print(f"[EncounterRecorder] Already recording, skipping {person_id}")
                return False

            self._person_id = person_id
            self._person_name = name
            self._relationship = relationship
            self._recorded_frames = list(self._pre_buffer)
            self._frame_count = len(self._recorded_frames)
            self._recording = True

        print(f"[EncounterRecorder] Recording started for {name} ({person_id}), "
              f"pre-buffer: {len(self._recorded_frames)} frames")

        # Fire recording started event
        self.on_event({
            "type": "encounter_recording_started",
            "person_id": person_id,
            "person": name,
            "relationship": relationship,
        })

        return True

    @property
    def is_recording(self) -> bool:
        return self._recording

    def _finalize(self) -> None:
        """Encode the recorded frames to MP4, extract snapshots, upload all."""
        frames = self._recorded_frames
        person_id = self._person_id
        person_name = self._person_name
        relationship = self._relationship

        if not frames:
            print("[EncounterRecorder] No frames to finalize")
            return

        print(f"[EncounterRecorder] Finalizing {len(frames)} frames for {person_id}")

        # Determine frame dimensions from first frame
        h, w = frames[0].shape[:2]

        # Write MP4 to temp file
        tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        tmp_path = tmp.name
        tmp.close()

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(tmp_path, fourcc, self._fps, (w, h))

        for frame in frames:
            # Resize if dimensions don't match (shouldn't happen but be safe)
            if frame.shape[:2] != (h, w):
                frame = cv2.resize(frame, (w, h))
            writer.write(frame)

        writer.release()

        # Extract snapshots at beginning, middle, end
        snapshot_indices = []
        total = len(frames)
        if total >= 3:
            snapshot_indices = [0, total // 2, total - 1]
        elif total == 2:
            snapshot_indices = [0, 1]
        elif total == 1:
            snapshot_indices = [0]

        snapshots = [frames[i] for i in snapshot_indices]

        # Upload to Cloudinary
        clip_url = ""
        snapshot_urls = []

        if cloud:
            try:
                result = cloud.upload_video(tmp_path, person_id)
                clip_url = result.get("secure_url", "")
                print(f"[EncounterRecorder] Clip uploaded: {clip_url[:80]}...")
            except Exception as e:
                print(f"[EncounterRecorder] Clip upload failed: {e}")

            for idx, snap_frame in enumerate(snapshots):
                try:
                    _, buf = cv2.imencode(".jpg", snap_frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                    result = cloud.upload_encounter_snapshot(buf.tobytes(), person_id, idx)
                    snapshot_urls.append(result.get("secure_url", ""))
                except Exception as e:
                    print(f"[EncounterRecorder] Snapshot {idx} upload failed: {e}")

        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

        # Store encounter metadata in memory
        memory.append(f"encounter_clips_{person_id}", {
            "timestamp": time.time(),
            "clip_url": clip_url,
            "snapshots": snapshot_urls,
            "frame_count": total,
            "duration_seconds": total / self._fps,
        })

        # Fire clip ready event
        self.on_event({
            "type": "encounter_clip_ready",
            "person_id": person_id,
            "person": person_name,
            "relationship": relationship,
            "clip_url": clip_url,
            "snapshots": snapshot_urls,
            "duration_seconds": round(total / self._fps, 1),
            "frame_count": total,
        })

        print(f"[EncounterRecorder] Done — {total} frames, {len(snapshot_urls)} snapshots")

    def stop(self) -> None:
        """Finalize any in-progress recording on shutdown."""
        with self._recording_lock:
            if self._recording:
                self._recording = False
                self._finalize()
