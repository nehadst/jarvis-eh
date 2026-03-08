"""
Mock capture — webcam or video file input for testing without Meta glasses.

Usage in .env:
    CAPTURE_MODE=webcam          # laptop webcam
    CAPTURE_MODE=video           # pre-recorded file
    VIDEO_PATH=data/test_clips/face_test.mp4
"""

from __future__ import annotations

import platform
import time
import cv2
import numpy as np
from config import settings

_IS_MACOS = platform.system() == "Darwin"


class MockCapture:
    """
    Drop-in replacement for GlassesCapture / FrameCapture.
    Reads from a webcam (index 0) or a video file.
    """

    def __init__(self, source=None, fps: float = 30.0) -> None:
        if source is None:
            source = settings.webcam_index if settings.capture_mode == "webcam" else settings.video_path
        self._source = source
        self._interval = 1.0 / fps
        self._running = False
        self._cap = None

    def _open_capture(self):
        """Open VideoCapture with AVFoundation on macOS for webcam sources."""
        if isinstance(self._source, int) and _IS_MACOS:
            return cv2.VideoCapture(self._source, cv2.CAP_AVFOUNDATION)
        return cv2.VideoCapture(self._source)

    def frames(self):
        self._running = True
        self._cap = self._open_capture()

        if not self._cap.isOpened():
            print(f"[MockCapture] Could not open source: {self._source}")
            return

        print(f"[MockCapture] Streaming from {'webcam idx=' + str(self._source) if isinstance(self._source, int) else self._source}")

        while self._running:
            t0 = time.time()
            ret, frame = self._cap.read()

            if not ret:
                # Video file ended — loop it
                if isinstance(self._source, str):
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                break

            yield frame

            elapsed = time.time() - t0
            sleep_time = self._interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        self._cap.release()
        print("[MockCapture] Stopped.")

    def grab_once(self) -> np.ndarray | None:
        cap = self._open_capture()
        ret, frame = cap.read()
        cap.release()
        return frame if ret else None

    def stop(self) -> None:
        self._running = False
