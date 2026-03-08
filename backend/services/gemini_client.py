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
        # Prefer model from settings but provide sensible fallbacks for new users
        preferred = getattr(settings, "gemini_model", "gemini-2.5-flash-lite")
        fallback_list = [preferred, "gemini-2.5-flash-lite", "gemini-2.1", "gemini-1.5", "gemini-1.0"]

        last_exc = None
        for model_name in fallback_list:
            try:
                self._text_model = genai.GenerativeModel(model_name)
                self._vision_model = genai.GenerativeModel(model_name)
                print(f"[GeminiClient] Using model: {model_name}")
                break
            except Exception as e:
                last_exc = e
                continue
        else:
            # If none of the models could be loaded, re-raise the last exception
            raise last_exc

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


# Singleton — import this everywhere
gemini = GeminiClient() if settings.gemini_api_key else None
