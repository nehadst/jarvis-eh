"""
Standalone runner for Feature 3 — Situation Grounding.

Useful for demoing or testing the feature without starting the full FastAPI server.

Usage:
    # Force an immediate grounding message (manual trigger):
    python backend/features/situation_grounding/run.py --manual

    # Run the detection loop for 30 seconds (fires when confusion is detected):
    python backend/features/situation_grounding/run.py

Run from the repo root so that relative imports resolve correctly.
"""

import argparse
import json
import sys
import time
from pathlib import Path

# ── Make backend/ importable ────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from capture.frame_capture import FrameCapture
from features.situation_grounding.grounder import SituationGrounder


def on_event(event: dict) -> None:
    print("\n[EVENT]", json.dumps(event, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Situation Grounding standalone runner")
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Force a grounding message immediately (skips confusion detection)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=30,
        help="How many seconds to run the detection loop (default: 30)",
    )
    args = parser.parse_args()

    grounder = SituationGrounder(on_event=on_event)
    capture = FrameCapture()

    if args.manual:
        print("[run.py] Grabbing frame and triggering grounding message...")
        frame = capture.grab_once()
        grounder.trigger_manual(frame)
        print("[run.py] Done.")
        return

    print(f"[run.py] Running detection loop for {args.duration}s at 2 FPS. Press Ctrl+C to stop.")
    deadline = time.time() + args.duration
    try:
        for frame in capture.frames():
            grounder.process(frame)
            if time.time() >= deadline:
                break
    except KeyboardInterrupt:
        pass
    finally:
        capture.stop()
    print("[run.py] Loop ended.")


if __name__ == "__main__":
    main()
