"""
Cloudinary client — upload, fetch, and transform family media.

Used for:
  - Storing the family photo album (tagged by person_id)
  - Uploading ElevenLabs narration audio
  - Building a Ken Burns slideshow video from tagged photos with an audio overlay
  - Eager-rendering the montage so playback is instant (not lazy on first request)

Cloudinary transformation strategy per montage:
  Each photo is individually turned into a 3-second zoompan (Ken Burns) clip,
  then all clips are concatenated via fl_splice. The ElevenLabs narration mp3
  is overlaid as an audio layer on the final video.

Usage:
    from services.cloudinary_client import cloud

    url = cloud.upload_photo("path/to/photo.jpg", person_id="sarah_johnson")
    audio_id = cloud.upload_audio("path/to/narration.mp3")
    montage_url = cloud.build_montage_url(
        person_id="sarah_johnson",
        audio_public_id=audio_id,   # optional
        tag_filter=None,            # pass e.g. "christmas" to filter by theme
    )
"""

import os
import tempfile
from typing import Optional

import cloudinary
import cloudinary.uploader
import cloudinary.api
from cloudinary.utils import cloudinary_url
from config import settings


class CloudinaryClient:
    # Seconds each photo is shown in the slideshow
    SLIDE_DURATION = 3
    # Max photos per montage (keeps video under ~30s)
    MAX_SLIDES = 8

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
        Returns the public_id (needed to overlay as audio on the montage video).
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

    # ── Montage builder ────────────────────────────────────────────────────────

    def build_montage_url(
        self,
        person_id: str,
        audio_public_id: Optional[str] = None,
        tag_filter: Optional[str] = None,
    ) -> str:
        """
        Build and return a Cloudinary video URL that plays a Ken Burns slideshow
        of all photos tagged with person_id, with an optional narration audio track.

        Each photo gets:
          - fill crop at 1280x720, face-gravity centering
          - e_zoompan:du_3  (3-second Ken Burns pan/zoom)
          - fps_24 for smooth playback

        All clips are spliced together. If audio_public_id is supplied, the
        narration is overlaid as an audio layer.

        The URL is eager-rendered (pre-generated) so the caregiver dashboard
        can play it immediately without waiting for on-the-fly transcoding.

        Returns the final mp4 URL, or "" if no photos are found.
        """
        photos = self.get_person_photos(person_id, tag_filter=tag_filter)
        if not photos:
            return ""

        public_ids = [p["public_id"] for p in photos[: self.MAX_SLIDES]]

        # ── Build the transformation chain ────────────────────────────────────
        # Cloudinary concatenation pattern:
        #   Start with photo[0], apply zoompan.
        #   For each subsequent photo: splice it in as an overlay layer, then
        #   apply zoompan to that slice, then fl_layer_apply.
        # Simpler approach that Cloudinary supports directly:
        #   Use the `multi` / slideshow approach with a manifest, OR
        #   use the video concatenation (fl_splice) with image layers.
        #
        # We use the fl_splice + l_ layer approach which works server-side.

        transformation: list[dict] = []

        # Base clip — first photo
        transformation.append({
            "width": 1280,
            "height": 720,
            "crop": "fill",
            "gravity": "face",
            "effect": f"zoompan:du_{self.SLIDE_DURATION}",
            "fps": 24,
        })

        # Splice in remaining photos
        for pid in public_ids[1:]:
            # Escape slashes in public_id for Cloudinary layer syntax
            escaped = pid.replace("/", ":")
            transformation.append({"overlay": escaped, "resource_type": "image"})
            transformation.append({
                "width": 1280,
                "height": 720,
                "crop": "fill",
                "gravity": "face",
                "effect": f"zoompan:du_{self.SLIDE_DURATION}",
                "fps": 24,
                "flags": "splice",
            })
            transformation.append({"flags": "layer_apply"})

        # Overlay narration audio if provided
        if audio_public_id:
            escaped_audio = audio_public_id.replace("/", ":")
            transformation.append({"overlay": f"video:{escaped_audio}"})
            transformation.append({"flags": "layer_apply"})

        url, _ = cloudinary_url(
            public_ids[0],
            resource_type="video",
            format="mp4",
            transformation=transformation,
            secure=True,
        )

        # Eager-render: kick off server-side generation immediately
        self._eager_render(public_ids[0], transformation)

        return url

    def _eager_render(self, public_id: str, transformation: list[dict]) -> None:
        """
        Tell Cloudinary to pre-generate the transformed video now rather than
        on first playback request. Fires-and-forgets — errors are non-fatal.
        """
        try:
            cloudinary.uploader.explicit(
                public_id,
                type="upload",
                resource_type="video",
                eager=transformation,
                eager_async=True,
            )
        except Exception as e:
            print(f"[Cloudinary] Eager render warning (non-fatal): {e}")


# Singleton — import this everywhere
cloud: Optional[CloudinaryClient] = (
    CloudinaryClient() if settings.cloudinary_cloud_name else None
)
