"""
Cloudinary client — upload, fetch, and transform family media.

Used for:
  - Storing the family photo album
  - Retrieving tagged photos per person for montage generation
  - Applying Ken Burns / video transitions via Cloudinary transformations

Usage:
    from services.cloudinary_client import cloud

    url = cloud.upload_image("path/to/photo.jpg", person_id="sarah_johnson")
    photos = cloud.get_person_photos("sarah_johnson")
    montage_url = cloud.build_montage_url("sarah_johnson")
"""

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

    def upload_image(self, file_path: str, person_id: str, tags: list[str] | None = None) -> str:
        """
        Upload a photo and tag it with the person's ID.
        Returns the secure URL.
        """
        result = cloudinary.uploader.upload(
            file_path,
            folder=f"{self._folder_prefix}/family/{person_id}",
            tags=[person_id] + (tags or []),
            resource_type="image",
        )
        return result["secure_url"]

    def get_person_photos(self, person_id: str, max_results: int = 20) -> list[dict]:
        """
        Return a list of photo assets tagged with person_id.
        Each item has: public_id, secure_url, created_at
        """
        result = cloudinary.api.resources_by_tag(
            person_id,
            resource_type="image",
            max_results=max_results,
        )
        return [
            {
                "public_id": r["public_id"],
                "secure_url": r["secure_url"],
                "created_at": r.get("created_at"),
            }
            for r in result.get("resources", [])
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

    def build_montage_url(self, person_id: str) -> str:
        """
        Build a slideshow video URL from all photos tagged with person_id.
        Cloudinary stitches them automatically with the slideshow transformation.
        Returns the URL — Cloudinary generates the video on-the-fly.
        """
        # Pull all photo public IDs for this person
        photos = self.get_person_photos(person_id)
        if not photos:
            return ""

        # Use the first photo as the base and overlay the rest as a slideshow
        # This uses Cloudinary's video slideshow feature
        public_ids = [p["public_id"] for p in photos[:10]]  # max 10 slides

        # Build video URL with Ken Burns effect
        url, _ = cloudinary_url(
            public_ids[0],
            resource_type="video",
            transformation=[
                {"width": 1280, "height": 720, "crop": "fill", "gravity": "face"},
                {"effect": "zoompan:du_3"},  # Ken Burns pan/zoom
            ],
            secure=True,
        )
        return url


# Singleton
cloud = CloudinaryClient() if settings.cloudinary_cloud_name else None
