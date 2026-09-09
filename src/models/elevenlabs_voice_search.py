from __future__ import annotations

from pydantic import Field

from src.models.base import MissionBaseModel


class ElevenLabsVoiceSearchResult(MissionBaseModel):
    """
    One real ElevenLabs voice returned by the real voice-search
    endpoint (GET /v2/voices) - verified directly against ElevenLabs'
    own current API documentation (2026-09-09), not assumed.

    Fields mirror the real response shape (a subset - only what a
    person needs to judge a candidate voice and register it):
    voice_id (the real id /v1/text-to-speech/{voice_id} accepts),
    name, category, labels (real, e.g. {"gender": "male",
    "accent": "american"}), description, and preview_url (a real,
    listenable sample - this app never plays audio itself, so the URL
    is surfaced for a person to open, not auto-played).
    """

    voice_id: str = Field(min_length=1)
    name: str = ""
    category: str = ""
    labels: dict[str, str] = Field(default_factory=dict)
    description: str = ""
    preview_url: str | None = None
