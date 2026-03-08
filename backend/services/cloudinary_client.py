"""
Cloudinary client — upload, fetch, and transform family media.

Used for:
  - Storing the family photo album (tagged by person_id)
  - Uploading ElevenLabs narration audio
  - Uploading encounter video clips and snapshot photos

Usage:
    from services.cloudinary_client import cloud

    url = cloud.upload_photo("path/to/photo.jpg", person_id="sarah_johnson")
    audio_id = cloud.upload_audio("path/to/narration.mp3")
    result = cloud.upload_video("path/to/clip.mp4", person_id="sarah_johnson")
"""

from __future__ import annotations

import os
import tempfile
import time
from typing import Optional

import cloudinary
import cloudinary.uploader
import cloudinary.api
from cloudinary.utils import cloudinary_url
from config import settings


class CloudinaryClient:
    def __init__(self) -> None:
        if not settings.cloudinary_cloud_name:
            raise ValueError("Cloudinary credentials are not set in .env")
        cloudinary.config(
            cloud_name=settings.cloudinary_cloud_name,
            api_key=settings.cloudinary_api_key,
            api_secret=settings.cloudinary_api_secret,
        )
        self._folder_prefix = "rewind"

    # ── Upload helpers ─────────────────────────────────────────────────────────

    def upload_photo(
        self,
        file_path: str,
        person_id: str,
        extra_tags: list[str] | None = None,
    ) -> str:
        """
        Upload a family photo and tag it with person_id (+ any extra tags like
        'christmas' or 'birthday') so it can be queried later.
        Returns the secure URL.
        """
        tags = [person_id] + (extra_tags or [])
        result = cloudinary.uploader.upload(
            file_path,
            folder=f"{self._folder_prefix}/family/{person_id}",
            tags=tags,
            resource_type="image",
        )
        return result["secure_url"]

    def upload_audio(self, file_path: str, label: str = "narration") -> str:
        """
        Upload an mp3 narration file to Cloudinary.
        Returns the public_id.
        """
        result = cloudinary.uploader.upload(
            file_path,
            folder=f"{self._folder_prefix}/audio",
            resource_type="video",  # Cloudinary treats audio as resource_type=video
            tags=["narration", label],
        )
        return result["public_id"]

    def upload_audio_bytes(self, audio_bytes: bytes, label: str = "narration") -> str:
        """
        Upload raw mp3 bytes (e.g. from ElevenLabs) without saving to disk first.
        Returns the public_id.
        """
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        try:
            return self.upload_audio(tmp_path, label=label)
        finally:
            os.unlink(tmp_path)

    # ── Asset retrieval ────────────────────────────────────────────────────────

    def get_person_photos(
        self,
        person_id: str,
        tag_filter: Optional[str] = None,
        max_results: int = 20,
    ) -> list[dict]:
        """
        Return photos tagged with person_id.
        Optionally narrow by an additional tag (e.g. 'christmas').
        Each item: { public_id, secure_url, created_at }
        """
        # Cloudinary doesn't support AND-tag queries directly; filter client-side
        result = cloudinary.api.resources_by_tag(
            person_id,
            resource_type="image",
            max_results=max_results,
        )
        resources = result.get("resources", [])

        if tag_filter:
            # Fetch tags for each resource to check membership
            filtered = []
            for r in resources:
                tags_resp = cloudinary.api.resource(r["public_id"])
                if tag_filter in tags_resp.get("tags", []):
                    filtered.append(r)
            resources = filtered

        return [
            {
                "public_id": r["public_id"],
                "secure_url": r["secure_url"],
                "created_at": r.get("created_at"),
            }
            for r in resources
        ]

    def get_face_crop_url(self, public_id: str, width: int = 300, height: int = 300) -> str:
        """Return a face-cropped thumbnail URL using Cloudinary's AI crop."""
        url, _ = cloudinary_url(
            public_id,
            width=width,
            height=height,
            gravity="face",
            crop="thumb",
            secure=True,
        )
        return url

    # ── Encounter recording uploads ──────────────────────────────────────────

    def upload_video(
        self,
        file_path: str,
        person_id: str,
        extra_tags: list[str] | None = None,
    ) -> dict:
        """
        Upload an encounter video clip (MP4) to Cloudinary.
        Returns { secure_url, public_id }.
        """
        tags = [person_id, "encounter"] + (extra_tags or [])
        result = cloudinary.uploader.upload(
            file_path,
            folder=f"{self._folder_prefix}/encounters/{person_id}",
            tags=tags,
            resource_type="video",
        )
        return {"secure_url": result["secure_url"], "public_id": result["public_id"]}

    def upload_encounter_snapshot(
        self,
        frame_bytes: bytes,
        person_id: str,
        index: int,
    ) -> dict:
        """
        Upload a JPEG snapshot from an encounter recording.
        Returns { secure_url, public_id }.
        """
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(frame_bytes)
            tmp_path = tmp.name
        try:
            tags = [person_id, "encounter", "snapshot"]
            result = cloudinary.uploader.upload(
                tmp_path,
                folder=f"{self._folder_prefix}/encounters/{person_id}",
                tags=tags,
                resource_type="image",
                public_id=f"snap_{index}_{int(time.time())}",
            )
            return {"secure_url": result["secure_url"], "public_id": result["public_id"]}
        finally:
            os.unlink(tmp_path)

    def get_encounter_clips(
        self,
        person_id: str,
        max_results: int = 20,
    ) -> list[dict]:
        """
        Query Cloudinary for encounter clips tagged with person_id.
        Returns list of { public_id, secure_url, created_at }.
        """
        try:
            result = cloudinary.api.resources_by_tag(
                person_id,
                resource_type="video",
                max_results=max_results,
            )
            resources = result.get("resources", [])
            return [
                {
                    "public_id": r["public_id"],
                    "secure_url": r["secure_url"],
                    "created_at": r.get("created_at"),
                }
                for r in resources
                if "encounter" in r.get("tags", []) or f"encounters/{person_id}" in r.get("public_id", "")
            ]
        except Exception as e:
            print(f"[Cloudinary] get_encounter_clips error: {e}")
            return []


# Singleton — import this everywhere
cloud: Optional[CloudinaryClient] = (
    CloudinaryClient() if settings.cloudinary_cloud_name else None
)
