from __future__ import annotations

from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # OpenAI (primary)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # Google Gemini (fallback)
    gemini_api_key: str = ""
    # Preferred Gemini model (update if older models are unavailable)
    gemini_model: str = "gemini-2.5-flash-lite"

    # ElevenLabs
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "EXAVITQu4vr4xnSDxMaL"  # default — swap for cloned family voice

    # Cloudinary
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""

    # Backboard.io
    backboard_api_key: str = ""
    backboard_assistant_id: str = ""

    # Capture source: "glasses" | "screen" | "webcam" | "video"
    capture_mode: str = "glasses"

    # Webcam device index (only used when capture_mode="webcam")
    webcam_index: int = 0

    # Video file path (only used when capture_mode="video")
    video_path: str = "data/test_clips/sample.mp4"

    # Screen capture region (only used when capture_mode="screen")
    capture_left: int = 0
    capture_top: int = 0
    capture_width: int = 1280
    capture_height: int = 720

    # Meta glasses WebSocket (only used when capture_mode="glasses")
    glasses_ws_host: str = "0.0.0.0"
    glasses_ws_port: int = 8765

    # Face recognition (InsightFace)
    face_db_path: str = "data/face_db"
    face_model: str = "buffalo_sc"       # "buffalo_sc" (fast) or "buffalo_l" (more accurate)
    face_det_size: int = 640             # detection input size — 640 is reliable, 320 is faster
    face_similarity_threshold: float = 0.4  # cosine similarity — higher = stricter (0.3-0.6 range)
    face_cooldown_seconds: int = 30

    # Encounter recording
    encounter_record_fps: int = 10
    encounter_record_duration: float = 10.0
    encounter_pre_buffer_seconds: float = 3.0
    encounter_snapshot_count: int = 3

    # Conversation sessions
    conversation_departure_grace: float = 15.0   # seconds before person considered gone
    conversation_min_duration: float = 30.0      # minimum session length to generate summary
    conversation_max_duration: float = 1800.0    # 30 min safety cap

    # App
    debug: bool = True
    port: int = 8000
    patient_name: str = "Dad"

    model_config = {"env_file": "../.env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()

# Resolved paths (relative to backend/)
BACKEND_DIR = Path(__file__).parent
FACE_DB_PATH = BACKEND_DIR / settings.face_db_path
FAMILY_PROFILES_PATH = BACKEND_DIR / "data" / "family_profiles"
