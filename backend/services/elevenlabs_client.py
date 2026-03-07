"""
ElevenLabs TTS client — converts text to speech and plays it.

Usage:
    from services.elevenlabs_client import tts

    tts.speak("That's Sarah, your granddaughter.")
    tts.speak("You're in your living room.", voice_id="different_voice_id")
"""

import io
import threading
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

    def speak(self, text: str, voice_id: str | None = None, blocking: bool = False) -> None:
        """
        Convert text to speech and play it through the speakers.

        Args:
            text: The text to speak.
            voice_id: Override the default voice (useful for family-cloned voices).
            blocking: If True, wait for playback to finish before returning.
        """
        if not text:
            return

        def _play() -> None:
            audio = self._client.text_to_speech.convert(
                voice_id=voice_id or self._default_voice_id,
                text=text,
                model_id="eleven_turbo_v2",  # lowest latency
                voice_settings=VoiceSettings(
                    stability=0.6,
                    similarity_boost=0.85,
                    style=0.2,
                    use_speaker_boost=True,
                ),
            )
            # audio is a generator of bytes — collect it
            audio_bytes = b"".join(audio)
            sound = pygame.mixer.Sound(io.BytesIO(audio_bytes))
            sound.play()
            if blocking:
                while pygame.mixer.get_busy():
                    pygame.time.wait(50)

        if blocking:
            _play()
        else:
            threading.Thread(target=_play, daemon=True).start()

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
