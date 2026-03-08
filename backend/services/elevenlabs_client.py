"""
ElevenLabs TTS client — converts text to speech and plays it.

Playback is serialized: only one message plays at a time.
If a new message arrives while one is playing, the current one is
interrupted and the new one takes over.

Usage:
    from services.elevenlabs_client import tts

    tts.speak("That's Sarah, your granddaughter.")
    tts.speak("You're in your living room.", voice_id="different_voice_id")
"""

from __future__ import annotations

import io
import queue
import threading
import time

import pygame
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings
from config import settings


class ElevenLabsClient:
    def __init__(self) -> None:
        if not settings.elevenlabs_api_key:
            raise ValueError("ELEVENLABS_API_KEY is not set in .env")
        self._client = ElevenLabs(api_key=settings.elevenlabs_api_key)
        self._default_voice_id = settings.elevenlabs_voice_id

        # Init pygame mixer for audio playback
        pygame.mixer.init()

        # Serialized playback — one message at a time
        self._play_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
        self._playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._playback_thread.start()

        # Tracks when the last TTS playback actually finished (not when it was requested)
        self.last_playback_end: float = 0.0

    def speak(self, text: str, voice_id: str | None = None, blocking: bool = False) -> None:
        """
        Convert text to speech and play it through the speakers.

        Non-blocking by default. If another message is already playing,
        it is interrupted and replaced by this one.
        """
        if not text:
            return

        # Clear any queued messages — only the latest matters
        while not self._play_queue.empty():
            try:
                self._play_queue.get_nowait()
            except queue.Empty:
                break

        # Stop whatever is currently playing
        pygame.mixer.stop()

        if blocking:
            self._do_play(text, voice_id)
        else:
            self._play_queue.put((text, voice_id))

    def _playback_loop(self) -> None:
        """Background thread: plays one TTS message at a time."""
        while True:
            try:
                text, voice_id = self._play_queue.get()
                self._do_play(text, voice_id)
            except Exception as e:
                print(f"[ElevenLabs] Playback error: {e}")

    def _do_play(self, text: str, voice_id: str | None) -> None:
        """Generate and play TTS audio, blocking until playback finishes."""
        try:
            audio = self._client.text_to_speech.convert(
                voice_id=voice_id or self._default_voice_id,
                text=text,
                model_id="eleven_turbo_v2",
                voice_settings=VoiceSettings(
                    stability=0.6,
                    similarity_boost=0.85,
                    style=0.2,
                    use_speaker_boost=True,
                ),
            )
            audio_bytes = b"".join(audio)
            sound = pygame.mixer.Sound(io.BytesIO(audio_bytes))
            sound.play()

            # Wait for playback to finish
            while pygame.mixer.get_busy():
                pygame.time.wait(50)

            # Mark when playback actually ended
            self.last_playback_end = time.time()
        except Exception as e:
            print(f"[ElevenLabs] TTS error: {e}")

    def is_playing(self) -> bool:
        """Return True if audio is currently playing."""
        return pygame.mixer.get_busy()

    def save(self, text: str, path: str, voice_id: str | None = None) -> None:
        """Save TTS audio to a file instead of playing it."""
        audio = self._client.text_to_speech.convert(
            voice_id=voice_id or self._default_voice_id,
            text=text,
            model_id="eleven_turbo_v2",
        )
        with open(path, "wb") as f:
            for chunk in audio:
                f.write(chunk)


# Singleton
tts = ElevenLabsClient() if settings.elevenlabs_api_key else None
