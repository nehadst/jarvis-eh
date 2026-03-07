"""
Frame capture module — grabs the WhatsApp call window from the screen.

Usage:
    from capture.frame_capture import FrameCapture

    cap = FrameCapture()
    for frame in cap.frames():   # generator, runs until cap.stop()
        process(frame)
"""

import time
import numpy as np
import cv2
import mss
import mss.tools
from config import settings


class FrameCapture:
    """
    Captures a fixed screen region at ~2 FPS using mss.
    The region should be set to the WhatsApp Desktop call window coordinates.

    Run  python capture/calibrate.py  to find the right values,
    then put them in .env as CAPTURE_LEFT / TOP / WIDTH / HEIGHT.
    """

    def __init__(
        self,
        left: int | None = None,
        top: int | None = None,
        width: int | None = None,
        height: int | None = None,
        fps: float = 2.0,
    ) -> None:
        self.region = {
            "left": left if left is not None else settings.capture_left,
            "top": top if top is not None else settings.capture_top,
            "width": width if width is not None else settings.capture_width,
            "height": height if height is not None else settings.capture_height,
        }
        self.interval = 1.0 / fps
        self._running = False

    def grab_once(self) -> np.ndarray:
        """Grab a single frame and return it as a BGR numpy array."""
        with mss.mss() as sct:
            screenshot = sct.grab(self.region)
            # mss returns BGRA — convert to BGR for OpenCV
            frame = np.array(screenshot)
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def frames(self):
        """
        Generator that yields BGR frames at the configured FPS.
        Call stop() from another thread to end the loop.
        """
        self._running = True
        with mss.mss() as sct:
            while self._running:
                t0 = time.time()
                screenshot = sct.grab(self.region)
                frame = np.array(screenshot)
                yield cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                elapsed = time.time() - t0
                sleep_time = self.interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

    def stop(self) -> None:
        self._running = False


class VideoFileCapture:
    """
    Replays a video file as a frame source, at a controlled FPS.
    Provides the same frames() / stop() interface as FrameCapture so the
    Orchestrator works identically with a video file or live screen capture.

    Usage:
        cap = VideoFileCapture("path/to/video.mp4", fps=2.0)
        for frame in cap.frames():
            process(frame)
    """

    def __init__(self, video_path: str, fps: float = 2.0) -> None:
        self.video_path = video_path
        self.interval = 1.0 / fps
        self._running = False

    def frames(self):
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise FileNotFoundError(f"Cannot open video file: {self.video_path}")

        video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / video_fps
        print(f"[VideoFileCapture] {self.video_path}")
        print(f"  {total_frames} frames @ {video_fps:.1f} fps = {duration:.1f}s video")
        print(f"  Sampling at {1/self.interval:.1f} FPS (every {video_fps//(1/self.interval):.0f} video frames)\n")

        # How many video frames to skip between each sample
        step = max(1, int(video_fps / (1.0 / self.interval)))

        self._running = True
        frame_idx = 0
        while self._running:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                break  # End of video
            yield frame
            frame_idx += step
            time.sleep(self.interval)

        cap.release()

    def stop(self) -> None:
        self._running = False
