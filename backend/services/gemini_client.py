"""
Gemini API client — wraps google-generativeai for text and vision tasks.

Usage:
    from services.gemini_client import gemini

    text = gemini.generate("Write a warm greeting for Sarah.")
    text = gemini.analyze_image(frame_bgr, "What room is this?")
"""

import base64
import cv2
import numpy as np
import google.generativeai as genai
from config import settings


class GeminiClient:
    def __init__(self) -> None:
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not set in .env")
        genai.configure(api_key=settings.gemini_api_key)
        self._text_model = genai.GenerativeModel("gemini-2.0-flash")
        self._vision_model = genai.GenerativeModel("gemini-2.0-flash")

    def generate(self, prompt: str) -> str:
        """Send a text-only prompt and return the response string."""
        response = self._text_model.generate_content(prompt)
        return response.text.strip()

    def analyze_image(self, frame: np.ndarray, prompt: str) -> str:
        """
        Send a BGR frame + prompt to Gemini Vision.
        Returns the model's text response.
        """
        # Encode frame to JPEG bytes
        _, buffer = cv2.imencode(".jpg", frame)
        image_bytes = buffer.tobytes()

        image_part = {
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(image_bytes).decode("utf-8"),
            }
        }
        response = self._vision_model.generate_content([image_part, prompt])
        return response.text.strip()

    def build_whisper_prompt(
        self,
        name: str,
        relationship: str,
        last_interaction: str,
        personal_detail: str,
        patient_name: str,
    ) -> str:
        return f"""You are a gentle AI assistant helping a person with dementia recognize someone in front of them.

Person recognized: {name}
Their relationship: {relationship}
Last interaction: {last_interaction}
A personal detail: {personal_detail}
Patient's name: {patient_name}

Write a warm, calm, 1-2 sentence whisper that:
- Tells the patient who they're looking at
- Mentions one memorable fact to spark connection
- Sounds natural, NOT robotic
- Is under 30 words

Only output the whisper text. Nothing else."""

    def build_montage_narration_prompt(
        self,
        name: str,
        relationship: str,
        notes: list[str],
        last_interaction: str,
        personal_detail: str,
        patient_name: str,
        tag_filter: str | None = None,
    ) -> str:
        """
        Generate a warm 30-second narration script for the memory montage video.
        The narration plays over the Ken Burns photo slideshow.
        """
        notes_text = "\n".join(f"- {n}" for n in notes) if notes else "- No specific notes provided"
        theme_line = f"Focus on memories related to: {tag_filter}" if tag_filter else ""

        return f"""You are writing the narration for a short memory montage video for {patient_name}, \
who has dementia. The video shows old family photos of {name}, their {relationship}.

Family notes about {name}:
{notes_text}

Last interaction: {last_interaction}
Personal detail: {personal_detail}
{theme_line}

Write a warm, gentle narration of 3-5 sentences (spoken aloud in ~25 seconds) that:
- Opens by gently naming who is in the photos
- Mentions 1-2 real shared memories to spark emotional recognition
- Uses simple, calm language — no medical terms, no past tense that implies loss
- Ends with a warm, reassuring line
- Sounds like a loving family member speaking softly, NOT a formal narrator

Only output the narration text. No titles, no stage directions, nothing else."""


# Singleton — import this everywhere
gemini = GeminiClient() if settings.gemini_api_key else None
