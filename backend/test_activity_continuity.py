r"""
Minimal Activity Continuity test — no glasses, no screen capture, no API keys needed.

Usage:
    cd c:\University\Hackathons\Hack Canada\jarvis-eh
    python test_activity_continuity.py

This simulates:
1. Person doing stuff (random motion) for 20s
2. System infers activities: "watching TV", "reading", etc.
3. Person stops and stays still for 10s → confusion detected
4. Activity reminder fires based on the inferred activity
"""

import sys
import time
import numpy as np
import cv2
from unittest.mock import patch

# Mock time.time() to match simulated frame time
_simulated_time = 0.0

def mock_time():
    return _simulated_time

# Add backend to path
sys.path.insert(0, ".")

# Patch time.time() BEFORE importing tracker
import features.activity_continuity.tracker as tracker_module
tracker_module.time.time = mock_time

# CRITICAL: Mock Gemini and TTS BEFORE importing tracker
class MockGemini:
    def analyze_image(self, frame, prompt):
        """Return a fake activity."""
        activities = [
            "watching TV | remote on the table",
            "reading a book | book on the armchair",
            "making tea | kettle on the counter",
            "sitting and thinking | couch cushions",
        ]
        return activities[int(_simulated_time * 2) % len(activities)]
    
    def generate(self, prompt):
        """Return a fake reminder."""
        return "That's what you were doing. Let's get back to it."

class MockTTS:
    def speak(self, text, **kwargs):
        print(f"\n[SPEAKER] {text}\n")

# Patch the modules BEFORE importing tracker
tracker_module.gemini = MockGemini()
tracker_module.tts = MockTTS()

from features.activity_continuity.tracker import ActivityTracker

def generate_frame(frame_num: int, total_frames: int, motion_intensity: float = 1.0) -> np.ndarray:
    """Generate a synthetic BGR frame with controlled motion."""
    # Base frame (blank gray)
    frame = np.full((480, 640, 3), 128, dtype=np.uint8)
    
    # Add motion based on intensity: 
    # High intensity: draw rectangle that moves around
    # Low intensity: static rectangle (no change = no motion in diff)
    if motion_intensity > 0.5:
        motion = int(np.sin(frame_num * 0.1) * 50 * motion_intensity)
        x = 320 + motion
        y = 240 + motion
        cv2.rectangle(frame, (x - 30, y - 30), (x + 30, y + 30), (200, 150, 100), -1)
        # Add timestamp text only during active motion
        text = f"Frame {frame_num} ({frame_num * 0.5:.1f}s)"
        cv2.putText(frame, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    else:
        # Stillness: rectangle stays exactly in place, NO TEXT
        # This creates identical frames so motion detection returns 0
        cv2.rectangle(frame, (290, 210), (350, 270), (200, 150, 100), -1)
    
    return frame

def main():
    global _simulated_time
    print("=" * 70)
    print("ACTIVITY CONTINUITY TEST — Simulating live frames")
    print("=" * 70)
    print()
    print("Phase 1 (0-20s): Person is active (moving around, doing stuff)")
    print("Phase 2 (20-40s): Person stops and stays still -> confusion detected")
    print("Phase 3 (40+s): Activity reminder fires")
    print()
    
    # Create tracker with a callback to print events
    def on_event(event):
        print(f"\n[EVENT] {event['type'].upper()}")
        if event.get('message'):
            print(f"   Message: {event['message']}")
        if event.get('activity'):
            print(f"   Activity: {event['activity']}")
        print()
    
    tracker = ActivityTracker(on_event=on_event)
    
    # Simulate caregiver setting a task
    tracker.set_active_task("watch TV and relax")
    
    # Phase 1: Active (high motion)
    print("\n[PHASE 1] Simulating active motion (0-20s)...")
    for frame_num in range(40):  # 40 frames @ 2 FPS = 20 seconds
        frame = generate_frame(frame_num, 40, motion_intensity=1.0)
        tracker.process(frame)
        _simulated_time += 0.5  # Increment simulated time (2 FPS = 0.5s per frame)
        time.sleep(0.05)  # Faster than real time for testing
        if frame_num % 10 == 0:
            print(f"  {frame_num * 0.5:.1f}s: Moving normally...")
    
    # Phase 2: Stillness (low motion → confusion)
    print("\n[PHASE 2] Simulating stillness (20-70s)...")
    for frame_num in range(40, 140):  # 100 more frames = 50 seconds still (past 45s cooldown)
        frame = generate_frame(frame_num, 140, motion_intensity=0.01)  # Almost no motion
        tracker.process(frame)
        _simulated_time += 0.5  # Increment simulated time
        time.sleep(0.002)  # Much faster
        if frame_num % 10 == 0:
            elapsed = (frame_num - 40) * 0.5
            print(f"  Still for {elapsed:.1f}s | confusion_count={tracker._confusion_count} | buffer={len(tracker._buffer)}")
    
    print("\n[RESULT] Test complete!")
    print(f"\nFinal state:")
    print(f"  Confusion count: {tracker._confusion_count}")
    print(f"  Simulated time: {_simulated_time:.1f}s")
    print(f"  Last reminder time: {tracker._last_reminder_time}")
    
    print(f"\nActivity buffer ({len(tracker._buffer)} entries):")
    if tracker._buffer:
        for ts, activity in [(e["time"], e["activity"]) for e in tracker._buffer]:
            age = _simulated_time - ts
            print(f"  ~{age:.1f}s ago: {activity}")
    else:
        print("  (empty)")
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    main()
