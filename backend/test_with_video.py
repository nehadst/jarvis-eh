r"""
Run the full REWIND pipeline against a prerecorded video file.

Usage:
    cd c:\University\Hackathons\Hack Canada\jarvis-eh\backend
    python test_with_video.py path/to/video.mp4

    # Optional: set a caregiver task
    python test_with_video.py path/to/video.mp4 --task "make tea"

All features run exactly as they would on the live glasses feed:
  - Face Recognition   (every frame)
  - Activity Continuity (every frame, infers every 10s)
  - Situation Grounding (every 10 frames ~5s)
  - Wandering Guardian  (every 10 frames)

Events are printed to the console as they fire.
Requires GEMINI_API_KEY and ELEVENLABS_API_KEY in ../.env
"""

import sys
import argparse
from datetime import datetime

sys.path.insert(0, ".")

from capture.frame_capture import VideoFileCapture
from pipeline.orchestrator import Orchestrator


def on_event(event: dict) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    etype = event.get("type", "unknown").upper()
    print(f"\n[{ts}] === {etype} ===")
    for key, value in event.items():
        if key != "type" and value:
            print(f"  {key}: {value}")


def main():
    parser = argparse.ArgumentParser(description="Test REWIND pipeline on a video file")
    parser.add_argument("video", help="Path to the input video file (mp4, avi, etc.)")
    parser.add_argument("--task", default=None, help="Active caregiver task (e.g. 'make tea')")
    parser.add_argument("--fps", type=float, default=2.0, help="Sample rate in FPS (default: 2.0)")
    args = parser.parse_args()

    print("=" * 60)
    print("REWIND — Video Pipeline Test")
    print("=" * 60)
    print(f"  Video : {args.video}")
    print(f"  Task  : {args.task or '(none set)'}")
    print(f"  FPS   : {args.fps}")
    print("=" * 60)
    print()
    print("Events will print as they fire. Press Ctrl+C to stop.\n")

    capture = VideoFileCapture(args.video, fps=args.fps)
    orch = Orchestrator(event_callback=on_event, capture=capture)

    if args.task:
        orch.set_active_task(args.task)

    try:
        orch.run()
    except KeyboardInterrupt:
        print("\n\n[Stopped by user]")
        orch.stop()

    print("\nDone.")


if __name__ == "__main__":
    main()
