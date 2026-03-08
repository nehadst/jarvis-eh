"""
Audio Sensor — microphone capture + speech-to-text + LLM intent routing.

Captures audio from the microphone, transcribes using the OpenAI Whisper API,
then routes the transcript through GPT-4o-mini with tool definitions to
determine user intent (replaces old regex pattern matching).

Emits:
  - VOICE_COMMAND when the LLM determines the person needs help
Updates:
  - world["recent_transcript"] with rolling transcript text
  - world["transcript_entries"] with individual timestamped entries

Requirements:
  pip install sounddevice openai
"""

from __future__ import annotations

import io
import json
import queue
import threading
import time
import wave
from collections import deque

from agent.signal_bus import Signal, SignalBus, SignalType, Priority
from config import settings


CHUNK_DURATION = 4        # seconds per audio chunk
SAMPLE_RATE = 16000
COMMAND_COOLDOWN = 8      # seconds between voice command signals
TTS_ECHO_SUPPRESS = 3    # seconds to mute mic AFTER TTS finishes playing

# Common Whisper hallucinations on silence
_HALLUCINATIONS = {
    "thank you", "thanks for watching", "you", "the", "bye",
    "thank you for watching", "thanks", ".", "",
    "subscribe", "like and subscribe",
}

# LLM intent routing tools (replaces COMMAND_PATTERNS regex)
INTENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "identify_person",
            "description": (
                "The person wants to know who someone is that they can see "
                "or who was just mentioned. Examples: 'who is that', "
                "'do I know her', 'tell me about that man'"
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ground_location",
            "description": (
                "The person is confused, disoriented, lost, or wants to know "
                "where they are, what time or day it is. Also for explicit "
                "confusion like 'I'm lost', 'I don't know where I am', "
                "'what's happening', 'I'm confused', 'help me'"
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remind_activity",
            "description": (
                "The person forgot what they were doing, what their task is, "
                "or what they should be doing next. Examples: 'what was I doing', "
                "'what should I do', 'what am I supposed to be doing'"
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "free_response",
            "description": (
                "The person is speaking directly to the assistant and needs "
                "a helpful, warm response. For emotional support, questions, "
                "or requests that don't fit other categories."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "response": {
                        "type": "string",
                        "description": "A warm, brief (under 20 words) spoken response",
                    }
                },
                "required": ["response"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "no_action",
            "description": (
                "Normal conversation with other people, background noise, "
                "TV/music, or speech that doesn't need assistant intervention. "
                "Use this when the person is just chatting, greeting someone, "
                "or talking to family/friends. This is the most common case."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


class AudioSensor:
    def __init__(self, bus: SignalBus) -> None:
        self._bus = bus
        self._is_active = False
        self._transcript: deque[dict] = deque(maxlen=100)
        self._audio_queue: queue.Queue = queue.Queue()
        self._openai_client = None
        self._last_command_time = 0.0
        self._capture_thread: threading.Thread | None = None
        self._transcribe_thread: threading.Thread | None = None

    # ── Public ────────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the audio capture + transcription loop."""
        if self._is_active:
            return

        if not settings.openai_api_key:
            print("[AudioSensor] No OPENAI_API_KEY — audio disabled.")
            return

        try:
            from openai import OpenAI
            self._openai_client = OpenAI(api_key=settings.openai_api_key)
        except ImportError:
            print("[AudioSensor] openai package not installed.")
            return

        self._is_active = True

        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

        self._transcribe_thread = threading.Thread(target=self._transcription_loop, daemon=True)
        self._transcribe_thread.start()

        print("[AudioSensor] Started — LLM-routed intent detection active.")

    def stop(self) -> None:
        self._is_active = False
        print("[AudioSensor] Stopped.")

    def get_recent_transcript(self, seconds: int = 60) -> str:
        """Return transcript text from the last N seconds."""
        cutoff = time.time() - seconds
        recent = [e["text"] for e in self._transcript if e["time"] > cutoff]
        return " ".join(recent)

    # ── Audio capture ─────────────────────────────────────────────────────────

    def _capture_loop(self) -> None:
        try:
            import sounddevice as sd

            def _callback(indata, frames, t, status):
                if status:
                    print(f"[AudioSensor] Audio status: {status}")
                self._audio_queue.put(indata.copy())

            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=SAMPLE_RATE * CHUNK_DURATION,
                callback=_callback,
            ):
                print("[AudioSensor] Microphone active.")
                while self._is_active:
                    time.sleep(0.1)

        except ImportError:
            print("[AudioSensor] sounddevice not installed — mic capture disabled.")
            print("  Install with: pip install sounddevice")
            self._is_active = False
        except Exception as e:
            print(f"[AudioSensor] Mic error: {e}")
            self._is_active = False

    # ── Transcription via OpenAI Whisper API ──────────────────────────────────

    def _transcription_loop(self) -> None:
        import numpy as np

        chunk_count = 0

        while self._is_active:
            try:
                chunk = self._audio_queue.get(timeout=1.0)
                if self._openai_client is None:
                    continue

                # Skip audio while TTS is playing or just finished — prevents
                # the mic from picking up the AI's own voice (feedback loop)
                from services.elevenlabs_client import tts as _tts
                if _tts and _tts.is_playing():
                    continue
                # Also suppress for a few seconds after playback ends
                if _tts and (time.time() - _tts.last_playback_end) < TTS_ECHO_SUPPRESS:
                    continue
                # Fallback: also check world state (covers the period between
                # speak() call and actual audio starting)
                world = self._bus.get_world()
                last_spoken = world.get("last_spoken_time", 0.0)
                if time.time() - last_spoken < 2:
                    continue

                # Convert float32 audio to WAV bytes for the API
                audio_np = chunk.flatten()

                # Skip near-silent chunks (RMS below threshold)
                rms = float(np.sqrt(np.mean(audio_np ** 2)))
                chunk_count += 1

                # Log every 5th chunk so user can see mic levels
                if chunk_count % 5 == 1:
                    print(f"[AudioSensor] Mic level: RMS={rms:.4f} "
                          f"(threshold=0.005, chunks={chunk_count})")

                if rms < 0.005:
                    continue

                wav_bytes = self._float32_to_wav(audio_np)

                # Call OpenAI Whisper API
                audio_file = io.BytesIO(wav_bytes)
                audio_file.name = "audio.wav"

                response = self._openai_client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="en",
                )
                text = response.text.strip()

                if not text or len(text) < 3:
                    continue

                # Skip hallucinations
                if text.lower().strip(".!?, ") in _HALLUCINATIONS:
                    continue

                now = time.time()
                self._transcript.append({"time": now, "text": text})
                print(f'[AudioSensor] Heard: "{text}"')

                # Update world state — both string and structured entries
                self._bus.update_world(
                    "recent_transcript",
                    self.get_recent_transcript(60),
                )
                self._bus.update_world(
                    "transcript_entries",
                    [{"time": e["time"], "text": e["text"]} for e in self._transcript],
                )

                # Route through LLM for intent detection
                self._route_with_llm(text, now)

            except queue.Empty:
                continue
            except Exception as e:
                print(f"[AudioSensor] Transcription error: {e}")

    @staticmethod
    def _float32_to_wav(audio: "np.ndarray") -> bytes:
        """Convert float32 numpy array to WAV bytes."""
        import numpy as np
        # Clamp and convert to int16
        audio = np.clip(audio, -1.0, 1.0)
        int16_audio = (audio * 32767).astype(np.int16)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(int16_audio.tobytes())
        return buf.getvalue()

    # ── LLM intent routing (replaces regex pattern matching) ──────────────────

    def _route_with_llm(self, text: str, now: float) -> None:
        """Use GPT-4o-mini to determine intent from transcribed speech."""
        # Global cooldown — don't spam voice commands
        if (now - self._last_command_time) < COMMAND_COOLDOWN:
            return

        try:
            response = self._openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"You are monitoring speech from a person with dementia "
                            f"named {settings.patient_name}. Determine if they need "
                            f"assistance based on what they just said. "
                            f"Most speech is normal conversation — use no_action for that. "
                            f"Only trigger a help tool if the person clearly needs it."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f'The person just said: "{text}"',
                    },
                ],
                tools=INTENT_TOOLS,
                tool_choice="required",
                max_tokens=100,
            )

            message = response.choices[0].message
            if not message.tool_calls:
                return

            tool_call = message.tool_calls[0]
            command = tool_call.function.name

            if command == "no_action":
                return

            self._last_command_time = now
            print(f"[AudioSensor] LLM routed: {command}")

            if command == "free_response":
                args = json.loads(tool_call.function.arguments)
                self._bus.emit(Signal(
                    type=SignalType.VOICE_COMMAND,
                    priority=Priority.HIGH,
                    data={
                        "command": "free_response",
                        "raw_text": text,
                        "response": args.get("response", ""),
                    },
                ))
            else:
                # identify_person, ground_location, remind_activity
                self._bus.emit(Signal(
                    type=SignalType.VOICE_COMMAND,
                    priority=Priority.HIGH,
                    data={"command": command, "raw_text": text},
                ))

        except Exception as e:
            print(f"[AudioSensor] LLM routing error: {e}")
