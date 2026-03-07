"""
Feature 12 — Conversation Copilot

Transcribes the audio from the WhatsApp call using Whisper STT, then
watches for:
  - Repeated questions (conversation looping)
  - Subject mentions (names, places, events) that match family memory
  - Topic confusion or no response

When triggered, generates a private whisper for the patient:
  "She's talking about the cottage trip last summer."

Audio capture:
  - On Windows: pyaudiowpatch (WASAPI loopback) captures system audio
  - On macOS/Linux: sounddevice or pyaudio with loopback
  - Fallback: microphone input if loopback is unavailable

The copilot can be enabled/disabled via the dashboard.
"""

import queue
import threading
import time
from collections import deque
from typing import Callable

from config import settings
from services.gemini_client import gemini
from services.elevenlabs_client import tts
from services.backboard_client import memory


WHISPER_MODEL_SIZE = "base"  # tiny/base/small — balance speed vs accuracy
TRANSCRIPTION_WINDOW = 30    # seconds of audio to keep in the rolling transcript
LOOP_DETECTION_THRESHOLD = 2  # same question repeated N times → trigger


class ConversationCopilot:
    def __init__(self, on_event: Callable[[dict], None] | None = None) -> None:
        self.on_event = on_event or (lambda e: None)
        self._is_active = False
        self._transcript: deque = deque(maxlen=50)  # rolling utterances
        self._last_assist_time = 0.0
        self._audio_thread: threading.Thread | None = None
        self._audio_queue: queue.Queue = queue.Queue()
        self._whisper_model = None  # loaded lazily

    # ── Public ────────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the audio capture + transcription loop."""
        if self._is_active:
            return
        self._is_active = True
        self._load_whisper()
        self._audio_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._audio_thread.start()
        print("[ConversationCopilot] Started.")

    def stop(self) -> None:
        self._is_active = False

    def get_transcript(self) -> list[dict]:
        return list(self._transcript)

    # ── Audio capture ─────────────────────────────────────────────────────────

    def _capture_loop(self) -> None:
        """
        Capture system audio in chunks and transcribe with Whisper.

        Uses sounddevice for cross-platform audio capture.
        For system audio loopback on Windows, install pyaudiowpatch
        and change the device to the loopback device.
        """
        try:
            import sounddevice as sd
            import numpy as np

            SAMPLE_RATE = 16000
            CHUNK_DURATION = 5  # seconds per chunk

            def _callback(indata, frames, t, status):
                self._audio_queue.put(indata.copy())

            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=SAMPLE_RATE * CHUNK_DURATION,
                callback=_callback,
            ):
                while self._is_active:
                    time.sleep(0.1)

        except ImportError:
            print("[ConversationCopilot] sounddevice not installed — audio capture disabled.")
            print("  Install with: pip install sounddevice")
        except Exception as e:
            print(f"[ConversationCopilot] Audio capture error: {e}")

    # ── Transcription & analysis ──────────────────────────────────────────────

    def _transcription_loop(self) -> None:
        """Pull audio chunks from the queue and transcribe them."""
        import numpy as np

        while self._is_active:
            try:
                chunk = self._audio_queue.get(timeout=1.0)
                if self._whisper_model is None:
                    continue

                # Transcribe
                audio_np = chunk.flatten()
                result = self._whisper_model.transcribe(audio_np, language="en", fp16=False)
                text = result.get("text", "").strip()

                if text:
                    utterance = {"time": time.time(), "text": text}
                    self._transcript.append(utterance)
                    self._analyse(text)

            except queue.Empty:
                continue
            except Exception as e:
                print(f"[ConversationCopilot] Transcription error: {e}")

    def _analyse(self, utterance: str) -> None:
        """
        Check for:
        1. Repeated questions / conversation loops
        2. Memory-triggering subjects (names, places)
        """
        now = time.time()
        if (now - self._last_assist_time) < 20:  # 20s cooldown between assists
            return

        recent_texts = [e["text"] for e in self._transcript][-10:]
        full_context = " | ".join(recent_texts)

        if not gemini:
            return

        try:
            analysis = gemini.generate(f"""Analyze this conversation transcript from someone with dementia.
Transcript (most recent last): {full_context}

Tasks:
1. Is there a repeated question or confusion about where they are / who someone is? (yes/no)
2. Is a specific family member, place, or memory event mentioned? If so, what?
3. If you detect confusion or a subject worth helping with, write a short private whisper (under 20 words) for the patient.

Respond in JSON like:
{{"confused": true, "subject": "cottage trip", "whisper": "She's talking about the cottage trip last summer."}}
If nothing to assist with: {{"confused": false}}""")

            import json
            data = json.loads(analysis)

            if data.get("confused") and data.get("whisper"):
                whisper = data["whisper"]
                subject = data.get("subject", "")

                # Enrich with memory if we have family context
                if subject:
                    related_memory = memory.retrieve(f"memory_{subject.lower().replace(' ', '_')}")
                    if related_memory and isinstance(related_memory, dict):
                        extra = related_memory.get("detail", "")
                        if extra:
                            whisper += f" {extra}"

                self._last_assist_time = now
                if tts:
                    tts.speak(whisper)

                self.on_event({
                    "type": "conversation_assist",
                    "subject": subject,
                    "whisper": whisper,
                    "transcript_snippet": recent_texts[-3:],
                })

        except Exception as e:
            print(f"[ConversationCopilot] Analysis error: {e}")

    # ── Whisper model ─────────────────────────────────────────────────────────

    def _load_whisper(self) -> None:
        try:
            import whisper
            print(f"[ConversationCopilot] Loading Whisper {WHISPER_MODEL_SIZE} model...")
            self._whisper_model = whisper.load_model(WHISPER_MODEL_SIZE)
            # Start transcription consumer thread
            threading.Thread(target=self._transcription_loop, daemon=True).start()
            print("[ConversationCopilot] Whisper ready.")
        except ImportError:
            print("[ConversationCopilot] openai-whisper not installed.")
            print("  Install with: pip install openai-whisper")
