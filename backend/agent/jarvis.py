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
from features.conversation_session import ConversationSessionManager
from services.gemini_client import gemini
from services.elevenlabs_client import tts
from services.backboard_client import memory


# ── Suppression / cooldown constants ──────────────────────────────────────────

MIN_TTS_GAP = 8           # seconds between any TTS output
FACE_COOLDOWN = 15        # per-person cooldown for face whispers
GROUNDING_COOLDOWN = 30   # grounding message cooldown
WANDERING_COOLDOWN = 60   # wandering redirect cooldown
ACTIVITY_COOLDOWN = 22    # activity reminder cooldown
CONVERSATION_COOLDOWN = 10  # conversation assist cooldown
CONFUSION_COOLDOWN = 30   # confusion detection cooldown


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

        # Conversation session manager — tracks full conversations per person visit
        self._session_manager = ConversationSessionManager()

        # Per-signal-type cooldown tracking
        self._last_face_spoken: dict[str, float] = {}  # person_id -> timestamp
        self._last_grounding_time = 0.0
        self._last_wandering_time = 0.0
        self._last_activity_time = 0.0
        self._last_conversation_time = 0.0

        self._last_confusion_time = 0.0

        # Task completion tracking
        self._last_task_check_time = 0.0   # when we last checked task engagement
        self._last_seen_activity: str | None = None  # track activity changes

        # Dispatch map: signal type -> handler
        # NOTE: STILLNESS and OSCILLATING_MOTION are no longer dispatched here.
        # They are now inputs to the ConfusionDetector which emits CONFUSION signals.
        self._dispatch_map: dict[SignalType, Callable] = {
            SignalType.SCENE_UNSAFE: self._handle_wandering,
            SignalType.FACE_DETECTED: self._handle_face,
            SignalType.FACE_DEPARTED: self._handle_face_departed,
            SignalType.MANUAL_GROUNDING: self._handle_grounding,
            SignalType.CONFUSION: self._handle_confusion,
            SignalType.CONVERSATION_LOOP: self._handle_conversation,
            SignalType.CONVERSATION_TOPIC: self._handle_conversation,
            SignalType.VOICE_COMMAND: self._handle_voice_command,
            SignalType.TASK_SET: self._handle_task_set,
        }

    # ── Main tick (called each AI worker cycle) ───────────────────────────────

    def tick(self) -> None:
        """
        Read pending signals, apply suppression, dispatch the highest-priority
        actionable signal. Only handles one action per tick.
        Also monitors task completion when a task is active.
        """
        world = self._bus.get_world()

        # Accumulate transcript into active conversation sessions every tick
        self._session_manager.accumulate_transcript(world)

        # ── Task completion monitoring (runs every tick, independent of signals)
        if world.get("active_task"):
            self._monitor_task_completion(world)

        signals = self._bus.get_pending_signals()
        if not signals:
            return

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

        if signal.type == SignalType.FACE_DEPARTED:
            return True  # departure signals always pass

        if signal.type in (SignalType.MANUAL_GROUNDING, SignalType.VOICE_COMMAND, SignalType.TASK_SET):
            return True  # explicit user/caregiver requests always pass

        if signal.type == SignalType.CONFUSION:
            return (now - self._last_confusion_time) >= CONFUSION_COOLDOWN

        if signal.type in (SignalType.STILLNESS, SignalType.OSCILLATING_MOTION):
            return False  # handled by ConfusionDetector now, not directly

        if signal.type == SignalType.ACTIVITY_INFERRED:
            return (now - self._last_activity_time) >= ACTIVITY_COOLDOWN

        if signal.type in (SignalType.CONVERSATION_LOOP, SignalType.CONVERSATION_TOPIC):
            return (now - self._last_conversation_time) >= CONVERSATION_COOLDOWN

        return True

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _handle_task_set(self, signal: Signal, world: dict) -> None:
        """Immediately announce a newly set task to the patient."""
        task = signal.data.get("task", "")
        set_by = signal.data.get("set_by", "caregiver")
        if not task:
            return

        # Reset completion tracking
        self._last_seen_activity = None

        # Generate and speak the task announcement
        scene = world.get("last_scene", "")
        is_home = self._is_in_safe_zone(scene)
        prior = world.get("prior_activity")
        prior_desc = ""
        if prior and isinstance(prior, dict):
            prior_desc = prior.get("activity", "")

        announcement = self._generate_task_announcement(task, set_by, prior_desc, is_home)
        self._speak_and_record(announcement, "task_set")

        self._event_callback({
            "type": "task_set",
            "task": task,
            "set_by": set_by,
            "message": announcement,
        })

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

        # Start conversation session FIRST — must not depend on anything below
        self._session_manager.start_session(person_id, name, relationship)

        # Build rich encounter context (activity + transcript + snapshots)
        context, snapshots = self._get_last_encounter_context(person_id, profile)

        # Generate whisper with enriched context
        whisper_text = self._generate_face_whisper(
            person_id, profile, last_interaction=context,
        )
        self._speak_and_record(whisper_text, "face")

        # Persist interaction (timestamp only — conversation content comes from
        # ConversationSessionManager, NOT from recent_transcript which captures
        # TTS echo from the speakers and creates a hallucination feedback loop)
        memory.append(f"interactions_{person_id}", {
            "timestamp": time.time(),
            "event": "face_recognized",
        })
        self._update_last_interaction(person_id)

        # Fire event with encounter snapshots for the dashboard
        self._event_callback({
            "type": "face_recognized",
            "person_id": person_id,
            "person": name,
            "relationship": relationship,
            "confidence": confidence,
            "whisper": whisper_text,
            "bbox": {"x": bbox[0], "y": bbox[1], "w": bbox[2], "h": bbox[3]},
            "frame_size": {"w": frame_shape[1], "h": frame_shape[0]},
            "last_snapshots": snapshots,
        })

        # Trigger encounter recording
        if self._encounter_callback:
            self._encounter_callback(person_id, name, relationship)

    def _handle_face_departed(self, signal: Signal, world: dict) -> None:
        """End conversation session when a person leaves the frame."""
        person_id = signal.data.get("person_id", "")
        name = signal.data.get("name", person_id)

        if not self._session_manager.has_active_session(person_id):
            return

        record = self._session_manager.end_session(person_id)
        if record:
            self._event_callback({
                "type": "conversation_session_ended",
                "person_id": person_id,
                "person": name,
                "duration_seconds": record["duration_seconds"],
                "summary": record["summary"],
                "transcript_length": len(record["transcript"]),
            })

    def _handle_confusion(self, signal: Signal, world: dict) -> None:
        """
        Tiered confusion response: task > activity > grounding.

        Priority order:
        1. If caregiver set an active task → remind them of the task
        2. If there's a recent observed activity → remind what they were doing
        3. Otherwise → full grounding (location, time, who's home)

        Triggered by the ConfusionDetector (HIGH or MEDIUM confidence).
        """
        self._last_confusion_time = time.time()
        self._last_grounding_time = time.time()

        confidence = signal.data.get("confidence", "high")
        reason = signal.data.get("reason", "unknown")
        print(f"[Jarvis] Confusion handler: {confidence}/{reason}")

        # 1. Active task takes priority — caregiver explicitly set it
        active_task = world.get("active_task")
        if active_task:
            self._deliver_task_reminder(active_task, world)
            return

        # 2. Recent observed activity (10-120s old)
        last_activity = world.get("last_activity")
        if last_activity and isinstance(last_activity, dict):
            age = time.time() - last_activity.get("time", 0)
            if 10 <= age <= 120:
                self._deliver_activity_reminder(last_activity, world)
                return

        # 3. Fall back to grounding
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

    def _handle_voice_command(self, signal: Signal, world: dict) -> None:
        """Handle voice commands from AudioSensor (LLM-routed intent detection)."""
        command = signal.data.get("command", "")
        raw_text = signal.data.get("raw_text", "")
        print(f'[Jarvis] Voice command: {command} (heard: "{raw_text}")')

        # ── Identify person (LLM: identify_person, legacy: who_is_this)
        if command in ("identify_person", "who_is_this"):
            last_face = world.get("last_detected_face")
            if last_face and (time.time() - last_face.get("time", 0)) < 30:
                person_id = last_face["person_id"]
                profile = last_face["profile"]
                context, snapshots = self._get_last_encounter_context(person_id, profile)
                whisper = self._generate_face_whisper(
                    person_id, profile, last_interaction=context,
                )
                self._speak_and_record(whisper, "voice_command")
                self._event_callback({
                    "type": "voice_command_response",
                    "command": command,
                    "response": whisper,
                    "last_snapshots": snapshots,
                })
            else:
                self._speak_and_record(
                    f"I don't see anyone I recognize right now, {settings.patient_name}.",
                    "voice_command",
                )

        # ── Ground location (LLM: ground_location, legacy: where_am_i)
        elif command in ("ground_location", "where_am_i"):
            self._deliver_grounding(signal, world)

        # ── Remind activity (LLM: remind_activity, legacy: what_was_i_doing)
        elif command in ("remind_activity", "what_was_i_doing"):
            # Use same priority as confusion: task > activity > grounding
            active_task = world.get("active_task")
            if active_task:
                self._deliver_task_reminder(active_task, world)
                return

            last_activity = world.get("last_activity")
            if last_activity and isinstance(last_activity, dict):
                age = time.time() - last_activity.get("time", 0)
                if age < 300:
                    self._deliver_activity_reminder(last_activity, world)
                    return
            # No task or activity — fall back to grounding
            self._deliver_grounding(signal, world)

        # ── Free response (LLM generated a direct reply)
        elif command == "free_response":
            response_text = signal.data.get("response", "")
            if response_text:
                self._speak_and_record(response_text, "voice_command")
                self._event_callback({
                    "type": "voice_command_response",
                    "command": command,
                    "response": response_text,
                })

    # ── Delivery helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _is_in_safe_zone(scene: str) -> bool:
        """Check if the scene is a known safe zone."""
        from sensors.scene_sensor import DEFAULT_SAFE_ZONES
        if not scene or scene == "unknown":
            return False
        scene_lower = scene.lower()
        zones = DEFAULT_SAFE_ZONES.copy()
        stored = memory.retrieve("safe_zones")
        if isinstance(stored, list):
            zones = zones | {z.lower() for z in stored}
        excluded = memory.retrieve("excluded_safe_zones")
        if isinstance(excluded, list):
            zones = zones - {z.lower() for z in excluded}
        return any(zone in scene_lower for zone in zones)

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
        scene = world.get("last_scene", "")

        reminder_text = self._generate_activity_reminder(activity, location_hint, active_task, scene)
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

    def _deliver_task_reminder(self, task: str, world: dict) -> None:
        """Generate and deliver a task reminder (caregiver-set task takes priority)."""
        scene = world.get("last_scene", "a familiar room")
        is_home = self._is_in_safe_zone(scene)

        if not gemini:
            reminder = f"{settings.patient_name}, you were going to {task}."
        else:
            home_instruction = (
                "\n- They are at home — do NOT suggest going home or heading home"
                if is_home else ""
            )
            try:
                prompt = f"""A person with dementia needs a gentle reminder about their task.

Task: {task}
Current scene: {scene}
Patient's name: {settings.patient_name}

Write a gentle 1-2 sentence reminder that:
- Tells them what they should be doing (the task)
- If helpful, mentions where they are
- Is warm, calm, and encouraging{home_instruction}
- Under 25 words

Only output the reminder text."""
                reminder = gemini.generate(prompt)
            except Exception:
                reminder = f"{settings.patient_name}, you were going to {task}."

        self._speak_and_record(reminder, "task_reminder")

        self._event_callback({
            "type": "activity_continuity",
            "activity": f"Task: {task}",
            "location_hint": scene,
            "message": reminder,
        })

    # ── Task completion monitoring ──────────────────────────────────────────

    # How often to check task engagement (seconds)
    _TASK_CHECK_INTERVAL = 1

    def _monitor_task_completion(self, world: dict) -> None:
        """Check if the patient's current activity matches the active task.

        Runs every _TASK_CHECK_INTERVAL seconds. A single confirmed match
        from Gemini is enough to declare the task done — no streak needed,
        the LLM check is already reliable.
        """
        now = time.time()
        if (now - self._last_task_check_time) < self._TASK_CHECK_INTERVAL:
            return
        self._last_task_check_time = now

        task = world.get("active_task")
        if not task:
            return

        last_activity = world.get("last_activity")
        if not last_activity or not isinstance(last_activity, dict):
            return

        activity_text = last_activity.get("activity", "unknown")
        if activity_text == "unknown":
            return

        # Don't re-check the exact same activity text we already evaluated
        if activity_text == self._last_seen_activity:
            return
        self._last_seen_activity = activity_text

        # Ask Gemini (text-only, cheap) if the activity matches the task
        if self._activity_matches_task(activity_text, task):
            print(f"[Jarvis] Task matched: '{activity_text}' completes '{task}'")
            self._complete_task(task, world)

    def _activity_matches_task(self, activity: str, task: str) -> bool:
        """Ask Gemini whether the observed activity is completing the given task."""
        if not gemini:
            # Simple keyword overlap fallback
            task_words = set(task.lower().split())
            activity_words = set(activity.lower().split())
            return len(task_words & activity_words) >= 2

        try:
            prompt = (
                f"Task assigned: \"{task}\"\n"
                f"Current observed activity: \"{activity}\"\n\n"
                "Is the person currently doing or completing this task? "
                "Be lenient — if the activity is clearly related to the task, say YES. "
                "Answer with only YES or NO."
            )
            answer = gemini.generate(prompt).strip().upper()
            return answer.startswith("YES")
        except Exception:
            return False

    def _complete_task(self, task: str, world: dict) -> None:
        """Task is done — announce completion, clear it, redirect to prior activity."""
        prior = world.get("prior_activity")
        prior_desc = ""
        if prior and isinstance(prior, dict):
            prior_desc = prior.get("activity", "")

        # Generate completion message
        completion_msg = self._generate_task_completion(task, prior_desc)
        self._speak_and_record(completion_msg, "task_completed")

        # Clear task state
        self._bus.update_world("active_task", None)
        self._bus.update_world("active_task_set_by", None)
        self._bus.update_world("prior_activity", None)
        memory.store("active_patient_task", {})

        # Reset tracking
        self._last_seen_activity = None

        self._event_callback({
            "type": "task_completed",
            "task": task,
            "returning_to": prior_desc or None,
            "message": completion_msg,
        })
        print(f"[Jarvis] Task completed: '{task}'")

    # ── THE ONLY tts.speak() call in the system ──────────────────────────────

    def _speak_and_record(self, text: str, action_type: str) -> None:
        """Single point of TTS output. Updates last_spoken_time in world state."""
        # Set last_spoken_time BEFORE speak() so the audio sensor starts
        # suppressing immediately, even while TTS audio is being generated.
        self._bus.update_world("last_spoken_time", time.time())
        if tts and text:
            tts.speak(text)
        print(f"[Jarvis] [{action_type}] {text[:80]}{'...' if len(text) > 80 else ''}")

    # ── LLM generation methods ────────────────────────────────────────────────

    def _generate_face_whisper(
        self, person_id: str, profile: dict,
        last_interaction: str | None = None,
    ) -> str:
        """Generate a warm face recognition whisper via LLM."""
        name = profile.get("name", person_id)
        relationship = profile.get("relationship", "person")
        personal_detail = profile.get("personal_detail", "")
        if last_interaction is None:
            last_interaction = "you haven't seen them in a while"

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
        is_home = self._is_in_safe_zone(scene)

        if not gemini:
            base = f"You're at home in the {scene}. It's {time_str}."
            if active_task:
                base += f" You were going to {active_task}."
            return base

        home_instruction = (
            "\n- They are ALREADY at home — do NOT suggest going home or heading home"
            if is_home else ""
        )

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
- Sounds warm and natural, NOT robotic{home_instruction}
- Is under 40 words

Only output the message text."""

        try:
            return gemini.generate(prompt)
        except Exception:
            return f"You're in the {scene}. It's {time_str}. Everything is okay."

    def _generate_activity_reminder(
        self, activity: str, location_hint: str, active_task: str | None = None,
        scene: str = "",
    ) -> str:
        """Generate a natural activity continuity reminder."""
        location_line = f" ({location_hint})" if location_hint else ""

        if not gemini:
            return f"You were {activity}.{location_line}"

        is_home = self._is_in_safe_zone(scene) if scene else True
        home_instruction = (
            "\n- They are at home — do NOT suggest going home or heading home"
            if is_home else ""
        )

        prompt = f"""A person with dementia has paused and may need a gentle reminder.

Last known activity: {activity}{location_line}
Active caregiver task: {active_task or "none"}
Patient's name: {settings.patient_name}

Write a gentle 1-2 sentence reminder that:
- Reminds them what they were doing
- If there's a location hint, tells them where the object is
- Is warm, calm, and natural{home_instruction}
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

    def _generate_task_announcement(
        self, task: str, set_by: str, prior_activity: str, is_home: bool,
    ) -> str:
        """Generate a warm announcement when a new task is set."""
        name = settings.patient_name.split()[0]

        if not gemini:
            if prior_activity:
                return f"Hey {name}, {set_by} would like you to {task}. You can get back to {prior_activity} after."
            return f"Hey {name}, {set_by} would like you to {task}."

        prior_line = f"\nThey were just doing: {prior_activity}" if prior_activity else ""
        home_instruction = (
            "\n- They are at home — do NOT suggest going home"
            if is_home else ""
        )

        try:
            prompt = f"""Write a warm, gentle message for {name}, a person with dementia.

Their caregiver ({set_by}) has just asked them to: {task}{prior_line}

The message should:
- Tell them what {set_by} would like them to do
- If they were doing something before, acknowledge it and say they can return to it after
- Sound like a caring family member, warm and encouraging
- Be 1-2 sentences, under 30 words{home_instruction}

Only output the message text."""
            return gemini.generate(prompt)
        except Exception:
            if prior_activity:
                return f"Hey {name}, {set_by} would like you to {task}. You can get back to {prior_activity} after."
            return f"Hey {name}, {set_by} would like you to {task}."

    def _generate_task_completion(self, task: str, prior_activity: str) -> str:
        """Generate a warm completion message with optional redirect to prior activity."""
        name = settings.patient_name.split()[0]

        if not gemini:
            if prior_activity:
                return f"Great job, {name}! Now you can get back to {prior_activity}."
            return f"Well done, {name}!"

        prior_line = f"\nBefore the task, they were: {prior_activity}" if prior_activity else ""

        try:
            prompt = f"""Write a warm, encouraging message for {name}, a person with dementia.

They just finished: {task}{prior_line}

The message should:
- Briefly praise them for completing the task
- If they had a prior activity, gently remind them they can go back to it
- Be warm, encouraging, under 20 words

Only output the message text."""
            return gemini.generate(prompt)
        except Exception:
            if prior_activity:
                return f"Great job, {name}! Now you can get back to {prior_activity}."
            return f"Well done, {name}!"

    # ── Memory helpers (moved from recognizer.py) ─────────────────────────────

    def _get_last_encounter_context(
        self, person_id: str, profile: dict,
    ) -> tuple[str, list[str]]:
        """
        Build rich context about the last encounter with this person.
        Returns (context_string, snapshot_urls).
        """
        interactions = memory.get_events(f"interactions_{person_id}", limit=5)

        if not interactions:
            summary = profile.get("last_interaction", {}).get(
                "summary", "you haven't seen them in a while"
            )
            personal = profile.get("personal_detail", "")
            if personal:
                summary = f"First time seeing them. Detail: {personal}"
            return summary, []

        prev = interactions[0]
        prev_ts = prev.get("timestamp", 0)
        ago = time.time() - prev_ts

        if ago < 60:
            time_ago = "just now"
        elif ago < 3600:
            time_ago = f"{int(ago // 60)} minutes ago"
        elif ago < 86400:
            hours = int(ago // 3600)
            time_ago = f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            days = int(ago // 86400)
            time_ago = "yesterday" if days == 1 else f"{days} days ago"

        # Find activity around that time (±90 second window)
        activity_context = ""
        if prev_ts > 0:
            window = 90
            activity_events = memory.get_events(
                "activity_log", since=prev_ts - window, limit=10,
            )
            nearby = [
                a for a in activity_events
                if abs(a.get("time", a.get("timestamp", 0)) - prev_ts) <= window
            ]
            if nearby:
                best = nearby[0]
                activity = best.get("activity", "")
                location_hint = best.get("location_hint", "")
                if activity and activity != "unknown":
                    activity_context = activity
                    if location_hint:
                        activity_context += f" near {location_hint}"

        # Check for full conversation summary first, then fall back to transcript snippet
        conversation_context = ConversationSessionManager.get_conversation_context(
            person_id, limit=2,
        )
        transcript_context = prev.get("transcript", "")

        # Get snapshot URLs from most recent encounter clip
        snapshot_urls = []
        clips = memory.get_events(f"encounter_clips_{person_id}", limit=1)
        if clips:
            snapshot_urls = clips[0].get("snapshots", [])

        # Compose context string
        parts = []
        if activity_context:
            parts.append(f"Last time ({time_ago}), you were {activity_context}")
        else:
            parts.append(f"You saw them {time_ago}")

        # Prefer conversation summary over raw transcript snippet
        if conversation_context:
            parts.append(conversation_context)
        elif transcript_context:
            snippet = transcript_context[:100].strip()
            if snippet:
                parts.append(f"You were talking about: {snippet}")

        return ". ".join(parts), snapshot_urls

    def _update_last_interaction(self, person_id: str) -> None:
        """Write a factual last_interaction timestamp back to the profile JSON.

        NOTE: We only store the date — NOT the LLM whisper text.
        Storing whisper text here created a hallucination feedback loop where
        the LLM's invented details (e.g. "pancakes") would be fed back as
        "facts" on the next encounter.  Conversation summaries (from
        ConversationSessionManager) are the proper source of interaction context.
        """
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
            "summary": "seen today",
        }
        path = FAMILY_PROFILES_PATH / f"{person_id}.json"
        try:
            path.write_text(json.dumps(profile, indent=2))
        except Exception as e:
            print(f"[Jarvis] Could not update profile {person_id}: {e}")


