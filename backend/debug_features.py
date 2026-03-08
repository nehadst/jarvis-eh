"""
Debug script to check if features are detecting anything in the video.
Runs in verbose mode to see what each feature is doing.
"""

import sys
import argparse
from datetime import datetime

sys.path.insert(0, ".")

from capture.frame_capture import VideoFileCapture
from features.face_recognition.recognizer import FaceRecognizer
from features.situation_grounding.grounder import SituationGrounder
from features.activity_continuity.tracker import ActivityTracker
from features.wandering_guardian.guardian import WanderingGuardian
from config import FACE_DB_PATH


def main():
    parser = argparse.ArgumentParser(description="Debug features on a video")
    parser.add_argument("video", help="Path to video file")
    args = parser.parse_args()

    print("=" * 60)
    print("Feature Debug Mode")
    print("=" * 60)
    print(f"Video: {args.video}")
    print(f"Face DB exists: {FACE_DB_PATH.exists()}")
    if FACE_DB_PATH.exists():
        subdirs = list(FACE_DB_PATH.iterdir())
        print(f"Face DB subdirs: {[d.name for d in subdirs if d.is_dir()]}")
    print("=" * 60)
    print()

    event_log = []

    def on_event(event: dict):
        ts = datetime.now().strftime("%H:%M:%S")
        etype = event.get("type", "unknown").upper()
        msg = f"[{ts}] {etype}"
        for key, value in event.items():
            if key != "type" and value:
                msg += f" | {key}={value}"
        print(msg)
        event_log.append(event)

    print("Processing video...\n")
    capture = VideoFileCapture(args.video, fps=2.0)
    
    recognizer = FaceRecognizer(on_event=on_event)
    grounder = SituationGrounder(on_event=on_event)
    tracker = ActivityTracker(on_event=on_event)
    guardian = WanderingGuardian(on_event=on_event)

    frame_count = 0
    for frame in capture.frames():
        frame_count += 1
        
        # Run all features
        recognizer.process(frame)
        if frame_count % 10 == 0:
            grounder.process(frame)
        tracker.process(frame)
        if frame_count % 10 == 0:
            guardian.process(frame)

    print()
    print("=" * 60)
    print(f"Processed {frame_count} frames")
    print(f"Total events: {len(event_log)}")
    if event_log:
        print("Events fired:")
        for evt in event_log:
            print(f"  - {evt}")
    
    # Show activity buffer contents
    if tracker._buffer:
        print(f"\nActivity buffer ({len(tracker._buffer)} entries):")
        for entry in list(tracker._buffer)[-5:]:  # Show last 5
            print(f"  - {entry}")
    else:
        print("\nActivity buffer: empty")
    
    print("=" * 60)


if __name__ == "__main__":
    main()
