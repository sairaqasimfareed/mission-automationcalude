from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Protocol

from pydantic import TypeAdapter

from src.models.voice_provider_mapping import VoiceProviderVoiceMapping

_MAPPING_LIST_ADAPTER = TypeAdapter(list[VoiceProviderVoiceMapping])


class VoiceProviderMappingRepository(Protocol):
    """Durable storage interface for real voice-provider mappings."""

    def load_all(self) -> list[VoiceProviderVoiceMapping]:
        """Return every stored voice-provider mapping."""
        ...

    def save_all(
        self,
        mappings: list[VoiceProviderVoiceMapping],
    ) -> None:
        """Replace stored voice-provider mappings with the given set."""
        ...


class JsonVoiceProviderMappingRepository:
    """
    JSON-file-backed voice-provider mapping storage.

    Mirrors JsonProviderProfileRepository's atomic-write discipline
    exactly: the new content is written to a temp file in the same
    directory, flushed and fsynced, then moved into place with
    Path.replace(), so a crash or power loss mid-write can never leave
    a truncated or half-written mappings file behind.
    """

    def __init__(
        self,
        storage_path: Path,
    ) -> None:
        self._storage_path = storage_path

    def load_all(self) -> list[VoiceProviderVoiceMapping]:
        if not self._storage_path.exists():
            return []

        raw_text = self._storage_path.read_text(encoding="utf-8")

        if not raw_text.strip():
            return []

        try:
            return _MAPPING_LIST_ADAPTER.validate_json(raw_text)
        except Exception as exc:
            raise RuntimeError(
                "Voice provider mapping storage is corrupt or invalid: "
                f"{self._storage_path}"
            ) from exc

    def save_all(
        self,
        mappings: list[VoiceProviderVoiceMapping],
    ) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)

        ordered = sorted(mappings, key=lambda mapping: mapping.key)
        payload = _MAPPING_LIST_ADAPTER.dump_json(ordered, indent=2)

        descriptor, temp_path_str = tempfile.mkstemp(
            dir=self._storage_path.parent,
            prefix=f".{self._storage_path.name}.",
            suffix=".tmp",
        )
        temp_path = Path(temp_path_str)

        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())

            temp_path.replace(self._storage_path)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise


class InMemoryVoiceProviderMappingRepository:
    """In-memory voice-provider mapping storage for tests and development."""

    def __init__(
        self,
        mappings: list[VoiceProviderVoiceMapping] | None = None,
    ) -> None:
        self._mappings = [mapping.model_copy() for mapping in (mappings or [])]

    def load_all(self) -> list[VoiceProviderVoiceMapping]:
        return [mapping.model_copy() for mapping in self._mappings]

    def save_all(
        self,
        mappings: list[VoiceProviderVoiceMapping],
    ) -> None:
        self._mappings = [mapping.model_copy() for mapping in mappings]
