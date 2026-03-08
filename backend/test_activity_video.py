"""
Focused Activity Continuity test on a real video file.

Runs ONLY the ActivityTracker — no face recognition, no wandering guardian.
Prints per-frame motion level and confusion state so you can see when
the reminder fires and what guards are active.

Usage (from backend/):
    python test_activity_video.py "<path_to_video.mp4>"

    # With a caregiver task so the reminder is more specific:
    python test_activity_video.py "<path_to_video.mp4>" --task "writing a letter"
"""

import sys
import argparse
from datetime import datetime

import cv2
import numpy as np

sys.path.insert(0, ".")

from capture.frame_capture import VideoFileCapture
from features.activity_continuity.tracker import (
    ActivityTracker,
    MOTION_THRESHOLD,
    CONFUSION_SECONDS,
)


def motion_bar(fraction: float, width: int = 30) -> str:
    filled = int(min(fraction, 1.0) * width)
    bar = "#" * filled + "-" * (width - filled)
    marker = int(MOTION_THRESHOLD * width)
    bar = bar[:marker] + "|" + bar[marker + 1:]
    return f"[{bar}] {fraction:.4f}"


def on_event(event: dict) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    etype = event.get("type", "unknown").upper()
    print(f"\n{'=' * 60}")
    print(f"[{ts}] EVENT: {etype}")
    for key, value in event.items():
        if key != "type" and value:
            print(f"  {key}: {value}")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Activity Continuity test on a video")
    parser.add_argument("video", help="Path to video file")
    parser.add_argument("--task", default=None, help="Caregiver task (e.g. 'writing a letter')")
    args = parser.parse_args()

    print("=" * 60)
    print("Activity Continuity — Video Test")
    print("=" * 60)
    print(f"Video : {args.video}")
    print(f"Task  : {args.task or '(none)'}")
    print(f"Motion threshold : {MOTION_THRESHOLD:.0%} of frame pixels")
    print(f"Confusion trigger: {CONFUSION_SECONDS}s of stillness")
    print(f"  Frames below threshold = STILL")
    print(f"  Frames above threshold = ACTIVE")
    print("=" * 60)
    print()

    tracker = ActivityTracker(on_event=on_event)
    if args.task:
        tracker.set_active_task(args.task)

    capture = VideoFileCapture(args.video, fps=2.0)
    prev_gray = None

    frame_count = 0
    for frame in capture.frames():
        frame_count += 1

        # Compute motion fraction for display (same logic as the tracker)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        if prev_gray is not None:
            diff = cv2.absdiff(prev_gray, gray)
            _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
            total = gray.shape[0] * gray.shape[1]
            fraction = float(np.sum(thresh)) / (255.0 * total)
            is_still = fraction < MOTION_THRESHOLD
            status = "STILL" if is_still else "moving"

            # Show state machine info
            still_dur = ""
            if tracker._still_since is not None:
                import time as _t
                dur = _t.time() - tracker._still_since
                still_dur = f" still={dur:.1f}s"

            print(
                f"Frame {frame_count:3d} | {motion_bar(fraction)} | "
                f"{status:7s} | active={tracker._was_active}"
                f"{still_dur}"
            )
        prev_gray = gray

        tracker.process(frame)

    print()
    print("=" * 60)
    print(f"Done — processed {frame_count} frames")
    print(f"\nActivity buffer ({len(tracker._buffer)} entries):")
    for entry in tracker._buffer:
        print(f"  [{entry['activity']}] hint={entry['location_hint']!r}")
    print("=" * 60)


if __name__ == "__main__":
    main()