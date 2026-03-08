from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # Google Gemini
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
    backboard_project_id: str = ""

    # Screen capture (WhatsApp call window region)
    capture_left: int = 0
    capture_top: int = 0
    capture_width: int = 1280
    capture_height: int = 720

    # Face recognition
    face_db_path: str = "data/face_db"
    face_model: str = "ArcFace"
    face_detector: str = "retinaface"
    face_distance_threshold: float = 0.4
    face_cooldown_seconds: int = 30

    # App
    debug: bool = True
    port: int = 8000
    patient_name: str = "Dad"

    model_config = {"env_file": "../.env", "env_file_encoding": "utf-8"}


settings = Settings()

# Resolved paths (relative to backend/)
BACKEND_DIR = Path(__file__).parent
FACE_DB_PATH = BACKEND_DIR / settings.face_db_path
FAMILY_PROFILES_PATH = BACKEND_DIR / "data" / "family_profiles"
