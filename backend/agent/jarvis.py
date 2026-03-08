"""
Jarvis Agent — central decision-maker.

Evaluates signals from sensors, applies suppression/cooldowns,
dispatches to deterministic handlers, generates LLM text, and
owns the ONLY tts.speak() call in the system.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from typing import Any, Callable

from agent.signal_bus import Priority, Signal, SignalBus, SignalType
from config import settings, FAMILY_PROFILES_PATH
from services.gemini_client import gemini
from services.elevenlabs_client import tts
from services.backboard_client import memory


# ── Suppression / cooldown constants ──────────────────────────────────────────

MIN_TTS_GAP = 8          # seconds between any TTS output
FACE_COOLDOWN = 30        # per-person cooldown for face whispers
GROUNDING_COOLDOWN = 60   # grounding message cooldown
WANDERING_COOLDOWN = 120  # wandering redirect cooldown
ACTIVITY_COOLDOWN = 45    # activity reminder cooldown
CONVERSATION_COOLDOWN = 20  # conversation assist cooldown


class JarvisAgent:
    def __init__(
        self,
        bus: SignalBus,
        event_callback: Callable[[dict], None] | None = None,
        encounter_callback: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self._bus = bus
        self._event_callback = event_callback or (lambda e: None)
        self._encounter_callback = encounter_callback

        # Per-signal-type cooldown tracking
        self._last_face_spoken: dict[str, float] = {}  # person_id -> timestamp
        self._last_grounding_time = 0.0
        self._last_wandering_time = 0.0
        self._last_activity_time = 0.0
        self._last_conversation_time = 0.0

        # Dispatch map: signal type -> handler
        self._dispatch_map: dict[SignalType, Callable] = {
            SignalType.SCENE_UNSAFE: self._handle_wandering,
            SignalType.FACE_DETECTED: self._handle_face,
            SignalType.MANUAL_GROUNDING: self._handle_grounding,
            SignalType.STILLNESS: self._handle_confusion,
            SignalType.OSCILLATING_MOTION: self._handle_confusion,
            SignalType.CONVERSATION_LOOP: self._handle_conversation,
            SignalType.CONVERSATION_TOPIC: self._handle_conversation,
        }

    # ── Main tick (called each AI worker cycle) ───────────────────────────────

    def tick(self) -> None:
        """
        Read pending signals, apply suppression, dispatch the highest-priority
        actionable signal. Only handles one action per tick.
        """
        signals = self._bus.get_pending_signals()
        if not signals:
            return

        world = self._bus.get_world()
        now = time.time()
        last_spoken = world.get("last_spoken_time", 0.0)
        in_suppression = (now - last_spoken) < MIN_TTS_GAP

        for signal in signals:
            # During suppression, only CRITICAL signals pass
            if in_suppression and signal.priority != Priority.CRITICAL:
                continue

            # Check per-signal-type cooldown
            if not self._check_cooldown(signal, now):
                self._bus.consume(signal)
                continue

            handler = self._dispatch_map.get(signal.type)
            if handler is None:
                self._bus.consume(signal)
                continue

            # Dispatch and consume
            self._bus.consume(signal)
            handler(signal, world)
            return  # one action per tick

    # ── Cooldown checks ───────────────────────────────────────────────────────

    def _check_cooldown(self, signal: Signal, now: float) -> bool:
        """Return True if this signal is allowed past its cooldown."""
        if signal.type == SignalType.FACE_DETECTED:
            person_id = signal.data.get("person_id", "")
            return (now - self._last_face_spoken.get(person_id, 0)) >= FACE_COOLDOWN

        if signal.type == SignalType.SCENE_UNSAFE:
            return (now - self._last_wandering_time) >= WANDERING_COOLDOWN

        if signal.type in (SignalType.MANUAL_GROUNDING,):
            return True  # manual grounding always passes

        if signal.type in (SignalType.STILLNESS, SignalType.OSCILLATING_MOTION):
            return (now - self._last_grounding_time) >= GROUNDING_COOLDOWN

        if signal.type == SignalType.ACTIVITY_INFERRED:
            return (now - self._last_activity_time) >= ACTIVITY_COOLDOWN

        if signal.type in (SignalType.CONVERSATION_LOOP, SignalType.CONVERSATION_TOPIC):
            return (now - self._last_conversation_time) >= CONVERSATION_COOLDOWN

        return True

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _handle_wandering(self, signal: Signal, world: dict) -> None:
        """Generate wandering redirect, speak, fire event."""
        scene = signal.data.get("scene", "outside")
        self._last_wandering_time = time.time()

        redirect_text = self._generate_wandering_redirect(scene)
        self._speak_and_record(redirect_text, "wandering")

        memory.append("wandering_events", {
            "timestamp": time.time(),
            "scene": scene,
            "message": redirect_text,
        })

        self._event_callback({
            "type": "wandering_detected",
            "scene": scene,
            "message": redirect_text,
            "severity": "gentle",
        })

    def _handle_face(self, signal: Signal, world: dict) -> None:
        """Generate face whisper, speak, fire event, trigger encounter recording."""
        data = signal.data
        person_id = data["person_id"]
        profile = data["profile"]
        similarity = data["similarity"]
        bbox = data["bbox"]
        frame_shape = data["frame_shape"]

        self._last_face_spoken[person_id] = time.time()

        name = profile.get("name", person_id)
        relationship = profile.get("relationship", "person")
        confidence = round(similarity, 3)

        # Generate whisper
        whisper_text = self._generate_face_whisper(person_id, profile)
        self._speak_and_record(whisper_text, "face")

        # Persist interaction
        memory.append(f"interactions_{person_id}", {
            "timestamp": time.time(),
            "event": "face_recognized",
            "whisper": whisper_text,
        })
        self._update_last_interaction(person_id, whisper_text)

        # Fire event with same shape as before
        self._event_callback({
            "type": "face_recognized",
            "person_id": person_id,
            "person": name,
            "relationship": relationship,
            "confidence": confidence,
            "whisper": whisper_text,
            "bbox": {"x": bbox[0], "y": bbox[1], "w": bbox[2], "h": bbox[3]},
            "frame_size": {"w": frame_shape[1], "h": frame_shape[0]},
        })

        # Trigger encounter recording
        if self._encounter_callback:
            self._encounter_callback(person_id, name, relationship)

    def _handle_confusion(self, signal: Signal, world: dict) -> None:
        """
        Checks world state to pick grounding vs. activity reminder (not both).
        If a recent activity exists, deliver activity reminder.
        Otherwise, deliver grounding message.
        """
        self._last_grounding_time = time.time()

        # Check if there's a recent activity to remind about
        last_activity = world.get("last_activity")
        if last_activity and isinstance(last_activity, dict):
            age = time.time() - last_activity.get("time", 0)
            if 10 <= age <= 90:
                self._deliver_activity_reminder(last_activity, world)
                return

        # Fall back to grounding
        self._deliver_grounding(signal, world)

    def _handle_grounding(self, signal: Signal, world: dict) -> None:
        """Manual grounding — always deliver grounding message."""
        self._last_grounding_time = time.time()
        self._deliver_grounding(signal, world)

    def _handle_conversation(self, signal: Signal, world: dict) -> None:
        """Speak whisper from audio analysis."""
        self._last_conversation_time = time.time()
        whisper = signal.data.get("whisper", "")
        subject = signal.data.get("subject", "")

        if whisper:
            self._speak_and_record(whisper, "conversation")
            self._event_callback({
                "type": "conversation_assist",
                "whisper": whisper,
                "subject": subject,
            })

    # ── Delivery helpers ──────────────────────────────────────────────────────

    def _deliver_grounding(self, signal: Signal, world: dict) -> None:
        """Build and deliver a grounding message."""
        scene = world.get("last_scene", "a familiar room")
        now_dt = datetime.now()
        time_str = now_dt.strftime("%A, %B %d · %I:%M %p").replace(" 0", " ")
        household_context = memory.retrieve("household_context") or {}

        recent_context = memory.query(
            f"In 2-3 brief facts, what has {settings.patient_name} been doing "
            "in the last hour? Include any visitors, activities, and tasks."
        )

        active_task = world.get("active_task")
        grounding_text = self._generate_grounding_message(
            scene, time_str, household_context, recent_context, active_task
        )
        self._speak_and_record(grounding_text, "grounding")

        memory.append("grounding_events", {
            "timestamp": time.time(),
            "scene": scene,
            "message": grounding_text,
        })

        self._event_callback({
            "type": "situation_grounding",
            "scene": scene,
            "time": time_str,
            "task": active_task,
            "message": grounding_text,
        })

    def _deliver_activity_reminder(self, activity_entry: dict, world: dict) -> None:
        """Generate and deliver an activity continuity reminder."""
        activity = activity_entry.get("activity", "something")
        location_hint = activity_entry.get("location_hint", "")
        active_task = world.get("active_task")

        reminder_text = self._generate_activity_reminder(activity, location_hint, active_task)
        self._speak_and_record(reminder_text, "activity")

        memory.append("continuity_reminders", {
            "timestamp": time.time(),
            "activity": activity,
            "message": reminder_text,
        })

        self._event_callback({
            "type": "activity_continuity",
            "activity": activity,
            "location_hint": location_hint,
            "message": reminder_text,
        })

    # ── THE ONLY tts.speak() call in the system ──────────────────────────────

    def _speak_and_record(self, text: str, action_type: str) -> None:
        """Single point of TTS output. Updates last_spoken_time in world state."""
        if tts and text:
            tts.speak(text)
        self._bus.update_world("last_spoken_time", time.time())
        print(f"[Jarvis] [{action_type}] {text[:80]}{'...' if len(text) > 80 else ''}")

    # ── LLM generation methods ────────────────────────────────────────────────

    def _generate_face_whisper(self, person_id: str, profile: dict) -> str:
        """Generate a warm face recognition whisper via LLM."""
        name = profile.get("name", person_id)
        relationship = profile.get("relationship", "person")
        personal_detail = profile.get("personal_detail", "")
        last_interaction = self._get_last_interaction(person_id, profile)

        if not gemini:
            return f"That's {name}, your {relationship}."

        try:
            prompt = gemini.build_whisper_prompt(
                name=name,
                relationship=relationship,
                last_interaction=last_interaction,
                personal_detail=personal_detail,
                patient_name=settings.patient_name,
            )
            return gemini.generate(prompt)
        except Exception as e:
            print(f"[Jarvis] Face whisper error: {e}")
            return f"That's {name}, your {relationship}."

    def _generate_grounding_message(
        self, scene: str, time_str: str, household_context: dict,
        recent_context: str = "", active_task: str | None = None,
    ) -> str:
        """Generate a calm grounding message via LLM."""
        who_is_home = household_context.get("who_is_home", "")
        task_line = f"\nCurrent task they should be doing: {active_task}" if active_task else ""
        context_line = f"\nRecent events: {recent_context}" if recent_context else ""

        if not gemini:
            base = f"You're at home in the {scene}. It's {time_str}."
            if active_task:
                base += f" You were going to {active_task}."
            return base

        prompt = f"""You are a gentle AI assistant helping a person with dementia feel calm and oriented.

Current scene: {scene}
Current time: {time_str}
Who is home: {who_is_home if who_is_home else "unknown"}{task_line}{context_line}
Patient's name: {settings.patient_name}

Write a calm, grounding message (1-3 sentences) that:
- Tells them where they are
- Tells them what time / day it is
- If there's a task, gently reminds them what they were going to do
- If someone is home, mentions them
- Sounds warm and natural, NOT robotic
- Is under 40 words

Only output the message text."""

        try:
            return gemini.generate(prompt)
        except Exception:
            return f"You're in the {scene}. It's {time_str}. Everything is okay."

    def _generate_activity_reminder(
        self, activity: str, location_hint: str, active_task: str | None = None,
    ) -> str:
        """Generate a natural activity continuity reminder."""
        location_line = f" ({location_hint})" if location_hint else ""

        if not gemini:
            return f"You were {activity}.{location_line}"

        prompt = f"""A person with dementia has become confused and stopped what they were doing.

Last known activity: {activity}{location_line}
Active caregiver task: {active_task or "none"}
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

    def _generate_wandering_redirect(self, scene: str) -> str:
        """Generate a gentle wandering redirect."""
        if not gemini:
            return f"Hey {settings.patient_name}, let's head back home."

        try:
            prompt = f"""A person with dementia ({settings.patient_name}) is outside and appears to be wandering.
Current scene: {scene}

Write one short, warm, de-escalating sentence that:
- Sounds like a caring family member
- Gently redirects them back home
- Does NOT use an alarm, panic, or be commanding
- Is under 15 words

Only output the sentence."""
            return gemini.generate(prompt)
        except Exception:
            return f"Hey {settings.patient_name}, let's head back home."

    # ── Memory helpers (moved from recognizer.py) ─────────────────────────────

    def _get_last_interaction(self, person_id: str, profile: dict) -> str:
        """Check Backboard for recent interactions, fall back to static profile."""
        interactions = memory.retrieve(f"interactions_{person_id}")
        if isinstance(interactions, list) and interactions:
            latest = interactions[-1]
            ts = latest.get("timestamp", 0)
            ago = time.time() - ts
            if ago < 3600:
                time_ago = f"{int(ago // 60)} minutes ago"
            elif ago < 86400:
                time_ago = f"{int(ago // 3600)} hours ago"
            else:
                time_ago = f"{int(ago // 86400)} days ago"
            if latest.get("whisper", ""):
                return f"You saw them {time_ago}"
        return profile.get("last_interaction", {}).get(
            "summary", "you haven't seen them in a while"
        )

    def _update_last_interaction(self, person_id: str, whisper_text: str) -> None:
        """Write the new last_interaction back to the profile JSON."""
        # Load fresh profiles to avoid stale data
        profiles = {}
        if FAMILY_PROFILES_PATH.exists():
            for f in FAMILY_PROFILES_PATH.glob("*.json"):
                try:
                    profile = json.loads(f.read_text())
                    pid = profile.get("id", f.stem)
                    profiles[pid] = profile
                except Exception:
                    pass

        profile = profiles.get(person_id)
        if not profile:
            return
        profile["last_interaction"] = {
            "date": date.today().isoformat(),
            "summary": whisper_text[:120] if whisper_text else "seen today",
        }
        path = FAMILY_PROFILES_PATH / f"{person_id}.json"
        try:
            path.write_text(json.dumps(profile, indent=2))
        except Exception as e:
            print(f"[Jarvis] Could not update profile {person_id}: {e}")


