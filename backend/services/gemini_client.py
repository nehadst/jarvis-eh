"""
AI client — uses OpenAI (primary) with Gemini as fallback.

The interface stays the same so all feature modules keep importing:
    from services.gemini_client import gemini

    text = gemini.generate("Write a warm greeting for Sarah.")
    text = gemini.analyze_image(frame_bgr, "What room is this?")
"""

import base64
import cv2
import numpy as np
from config import settings


# ── OpenAI backend ────────────────────────────────────────────────────────────

class OpenAIClient:
    def __init__(self) -> None:
        from openai import OpenAI
        self._client = OpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model

    def generate(self, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
        )
        return resp.choices[0].message.content.strip()

    def analyze_image(self, frame: np.ndarray, prompt: str) -> str:
        _, buffer = cv2.imencode(".jpg", frame)
        b64 = base64.b64encode(buffer.tobytes()).decode("utf-8")

        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
            max_tokens=200,
        )
        return resp.choices[0].message.content.strip()


# ── Gemini backend ────────────────────────────────────────────────────────────

class GeminiClient:
    def __init__(self) -> None:
        import google.generativeai as genai
        genai.configure(api_key=settings.gemini_api_key)
        self._model = genai.GenerativeModel("gemini-2.0-flash")

    def generate(self, prompt: str) -> str:
        response = self._model.generate_content(prompt)
        return response.text.strip()

    def analyze_image(self, frame: np.ndarray, prompt: str) -> str:
        _, buffer = cv2.imencode(".jpg", frame)
        image_part = {
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(buffer.tobytes()).decode("utf-8"),
            }
        }
        response = self._model.generate_content([image_part, prompt])
        return response.text.strip()


# ── Unified wrapper (OpenAI primary, Gemini fallback) ─────────────────────────

class AIClient:
    def __init__(self) -> None:
        self._primary = None
        self._fallback = None
        self._primary_name = None
        self._fallback_name = None

        if settings.openai_api_key:
            try:
                self._primary = OpenAIClient()
                self._primary_name = "OpenAI"
                print("[AI] Primary: OpenAI")
            except Exception as e:
                print(f"[AI] OpenAI init failed: {e}")

        if settings.gemini_api_key:
            try:
                fb = GeminiClient()
                if self._primary:
                    self._fallback = fb
                    self._fallback_name = "Gemini"
                    print("[AI] Fallback: Gemini")
                else:
                    self._primary = fb
                    self._primary_name = "Gemini"
                    print("[AI] Primary: Gemini (no OpenAI key)")
            except Exception as e:
                print(f"[AI] Gemini init failed: {e}")

        if not self._primary:
            raise ValueError("No AI keys configured. Set OPENAI_API_KEY or GEMINI_API_KEY in .env")

    def generate(self, prompt: str) -> str:
        try:
            return self._primary.generate(prompt)
        except Exception as e:
            if self._fallback:
                print(f"[AI] {self._primary_name} failed ({e}), falling back to {self._fallback_name}")
                return self._fallback.generate(prompt)
            raise

    def analyze_image(self, frame: np.ndarray, prompt: str) -> str:
        try:
            return self._primary.analyze_image(frame, prompt)
        except Exception as e:
            if self._fallback:
                print(f"[AI] {self._primary_name} vision failed ({e}), falling back to {self._fallback_name}")
                return self._fallback.analyze_image(frame, prompt)
            raise

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
# Name kept as `gemini` so nothing else needs to change
try:
    gemini = AIClient() if (settings.openai_api_key or settings.gemini_api_key) else None
except Exception as e:
    print(f"[AI] Could not initialize: {e}")
    gemini = None
