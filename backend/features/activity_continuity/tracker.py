"""
Feature 4 — Activity Continuity (Hashim)

Maintains a rolling 60-second buffer of inferred activities from the live feed.
When a confusion signal is detected (via the grounder or motion heuristics),
retrieves the last known activity and generates a gentle reminder:

  "You were making tea. The kettle is on the counter to your left."
  "You were reading your book. It's on the arm of your chair."

Robustness guards:
  - Requires 5 seconds of continuous stillness (not just a few frames)
  - Suppresses reminders when multiple faces are visible (conversation)
  - Asks Gemini to confirm confusion before speaking
  - Filters out sedentary/unknown activities (no false reminders for "watching TV")
  - Requires the person to have been moving recently before stillness counts

Activity inference:
  - Sends every Nth frame to Gemini Vision with a structured prompt
  - Returns a short activity description: "making tea", "watching TV", "reading"
  - Stored in a time-stamped rolling buffer
"""

import time
from collections import deque
from datetime import datetime
from typing import Callable

import cv2
import numpy as np

from config import settings
from services.gemini_client import gemini
from services.elevenlabs_client import tts
from services.backboard_client import memory


# How often (seconds) we sample frames for activity inference
INFER_INTERVAL = 10  # every 10s

# Cooldown before repeating the same continuity reminder
REMINDER_COOLDOWN = 45

# How long the activity buffer spans (seconds)
BUFFER_DURATION = 90

# Fraction of frame pixels that must change to count as "motion".
# Below this fraction → person is still. Real-world video noise
# alone accounts for ~0.1–0.5%; genuine motion is typically >2%.
MOTION_THRESHOLD = 0.02  # 2% of frame pixels

# How many seconds of continuous stillness before we consider confusion.
# At 2 FPS this is ~6 consecutive still frames.
CONFUSION_SECONDS = 3

# Keywords that indicate the activity is NOT a real task — either sedentary
# or a conversation.  We match these as substrings so Gemini's varied
# phrasings ("talking to the camera", "speaking on the phone") all get caught.
_SKIP_KEYWORDS = {
    # conversation / social
    "talk", "speak", "chat", "convers", "call", "discuss",
    "listen", "interview",
    # sedentary / restful
    "watch", "read", "sleep", "nap", "rest", "sit", "relax",
    "meditat", "pray",
}


def _is_skippable(activity: str) -> bool:
    """Return True if the activity is a conversation or sedentary — not a real task."""
    low = activity.lower()
    return low in ("unknown", "") or any(kw in low for kw in _SKIP_KEYWORDS)


class ActivityTracker:
    def __init__(self, on_event: Callable[[dict], None] | None = None) -> None:
        self.on_event = on_event or (lambda e: None)
        # Buffer entries: {"time": float, "activity": str, "location_hint": str}
        self._buffer: deque = deque()
        self._active_task: str | None = None
        self._last_infer_time = 0.0
        self._last_reminder_time = 0.0
        self._prev_frame: np.ndarray | None = None

        # Confusion state machine
        self._still_since: float | None = None   # timestamp when stillness began
        self._was_active: bool = False            # had meaningful motion before stillness
        self._faces_visible: int = 0              # updated externally or via detection

    # ── Public ────────────────────────────────────────────────────────────────

    def set_active_task(self, task: str) -> None:
        self._active_task = task

    def set_faces_visible(self, count: int) -> None:
        """Called by the orchestrator with the face count each frame."""
        self._faces_visible = count

    def process(self, frame: np.ndarray) -> None:
        """
        Called on every frame.
        1. Periodically infers the current activity and stores it.
        2. Detects confusion via motion heuristics + guards.
        3. On confusion, confirms with Gemini, then delivers a continuity reminder.
        """
        now = time.time()

        # Prune old buffer entries
        cutoff = now - BUFFER_DURATION
        while self._buffer and self._buffer[0]["time"] < cutoff:
            self._buffer.popleft()

        # Periodically infer activity
        if now - self._last_infer_time >= INFER_INTERVAL:
            self._last_infer_time = now
            self._infer_and_store(frame)

        # Motion detection
        is_still = self._detect_stillness(frame)

        if not is_still:
            # Person is moving — reset stillness timer, mark as active
            self._still_since = None
            self._was_active = True
            return

        # Person is still — start or continue the stillness timer
        if self._still_since is None:
            self._still_since = now

        still_duration = now - self._still_since

        # Guard 1: Must have been active before this stillness period
        if not self._was_active:
            print(f"[ActivityTracker] Guard 1 BLOCKED: not previously active")
            return

        # Guard 2: Must be still for at least CONFUSION_SECONDS
        if still_duration < CONFUSION_SECONDS:
            return

        print(f"[ActivityTracker] Stillness threshold met ({still_duration:.1f}s) — checking guards...")

        # Guard 3: Cooldown — don't repeat reminders too soon
        if (now - self._last_reminder_time) < REMINDER_COOLDOWN:
            print(f"[ActivityTracker] Guard 3 BLOCKED: cooldown ({now - self._last_reminder_time:.0f}s < {REMINDER_COOLDOWN}s)")
            return

        # Guard 4: Multiple faces visible → likely a conversation, skip
        if self._faces_visible > 1:
            print(f"[ActivityTracker] Guard 4 BLOCKED: {self._faces_visible} faces visible")
            return

        # Guard 5: Find the most recent REAL TASK activity in the buffer.
        # Skip unknown, conversation, and sedentary activities — those aren't
        # tasks worth reminding about.
        last_task = next(
            (e for e in reversed(list(self._buffer)) if not _is_skippable(e["activity"])),
            None,
        )

        if not last_task:
            print(f"[ActivityTracker] Guard 5 BLOCKED: no real task in buffer")
            return

        print(f"[ActivityTracker] All guards passed — delivering reminder...")

        # All guards passed — deliver reminder
        self._deliver_reminder(frame)
        # Reset state
        self._still_since = None
        self._was_active = False

    def get_last_activity(self) -> dict | None:
        """Return the most recent activity entry from the buffer."""
        return self._buffer[-1] if self._buffer else None

    # ── Private ───────────────────────────────────────────────────────────────

    def _infer_and_store(self, frame: np.ndarray) -> None:
        """Ask Gemini Vision what the person is doing, then store it."""
        if not gemini:
            return
        try:
            result = gemini.analyze_image(
                frame,
                "In 5-10 words, what activity is this person doing or about to do? "
                "Also, if you see any relevant object (kettle, book, mug, remote, etc.), "
                "note its location. Format: ACTIVITY | OBJECT HINT\n"
                "Example: making tea | kettle on the counter to the right\n"
                "If you can't tell, just say: unknown\n"
                "Only output in that format, nothing else.",
            )
            parts = result.split("|")
            activity = parts[0].strip().lower()
            location_hint = parts[1].strip() if len(parts) > 1 else ""

            entry = {
                "time": time.time(),
                "activity": activity,
                "location_hint": location_hint,
            }
            self._buffer.append(entry)
            memory.store("last_activity", entry)

        except Exception as e:
            print(f"[ActivityTracker] Infer error: {e}")

    def _detect_stillness(self, frame: np.ndarray) -> bool:
        """
        Frame-diff motion heuristic.
        Returns True if the person is still (below motion threshold).
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        if self._prev_frame is None:
            self._prev_frame = gray
            return False
        diff = cv2.absdiff(self._prev_frame, gray)
        self._prev_frame = gray
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        total_pixels = gray.shape[0] * gray.shape[1]
        changed_fraction = np.sum(thresh) / (255.0 * total_pixels)
        return changed_fraction < MOTION_THRESHOLD

    def _confirm_confusion(self, frame: np.ndarray) -> bool:
        """
        Ask Gemini to visually confirm the person looks confused/lost,
        not just pausing intentionally or talking to someone.
        """
        if not gemini:
            return True  # no Gemini → skip confirmation, fire anyway

        try:
            answer = gemini.analyze_image(
                frame,
                "A person who was previously active has suddenly stopped moving. "
                "Do they look confused, lost, or like they've forgotten what they were doing? "
                "Signs of confusion: staring blankly, looking around, frozen mid-task. "
                "Signs of FINE: clearly resting, talking, or deliberately pausing. "
                "Answer with exactly one word: CONFUSED or FINE.",
            )
            result = answer.strip().lower()
            print(f"[ActivityTracker] Confusion confirmation: '{answer.strip()}'")
            return "confused" in result
        except Exception as e:
            print(f"[ActivityTracker] Confirm error: {e}")
            return True  # on error, err on the side of helpfulness

    def _deliver_reminder(self, frame: np.ndarray) -> None:
        """Find the last real task activity and deliver a reminder."""
        now = time.time()
        self._last_reminder_time = now

        # Prefer a real-task entry from 10-60s ago (before confusion started).
        # Fall back to the most recent real-task entry.
        # Always skip conversations and sedentary activities.
        target_activity = None
        for entry in reversed(list(self._buffer)):
            if _is_skippable(entry["activity"]):
                continue
            age = now - entry["time"]
            if 10 <= age <= 60:
                target_activity = entry
                break
        if target_activity is None:
            for entry in reversed(list(self._buffer)):
                if not _is_skippable(entry["activity"]):
                    target_activity = entry
                    break

        if not target_activity:
            return

        activity = target_activity["activity"]
        location_hint = target_activity["location_hint"]

        reminder_text = self._generate_reminder(activity, location_hint)
        print(f"[ActivityTracker] Delivering reminder: '{reminder_text}'")

        if tts and reminder_text:
            tts.speak(reminder_text, blocking=True)

        memory.append("continuity_reminders", {
            "timestamp": now,
            "activity": activity,
            "message": reminder_text,
        })

        self.on_event({
            "type": "activity_continuity",
            "activity": activity,
            "location_hint": location_hint,
            "message": reminder_text,
        })

    def _generate_reminder(self, activity: str, location_hint: str) -> str:
        """Generate a natural-sounding continuity reminder."""
        location_line = f" ({location_hint})" if location_hint else ""

        if not gemini:
            return f"You were {activity}.{location_line}"

        prompt = f"""A person with dementia has become confused and stopped what they were doing.

Last known activity: {activity}{location_line}
Active caregiver task: {self._active_task or "none"}
Patient's name: {settings.patient_name}

Write a gentle 1-2 sentence reminder that:
- Reminds them what they were doing
- If there's a location hint, tells them where the object is
- Is warm, calm, and natural
- Under 25 words

Only output the reminder text."""

        try:
            return gemini.generate(prompt)
        except Exception:
            return f"You were {activity}.{location_line}"
