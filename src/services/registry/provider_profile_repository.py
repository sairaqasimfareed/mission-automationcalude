from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Protocol

from pydantic import TypeAdapter

from src.models.provider_profile import ProviderProfile

_PROFILE_LIST_ADAPTER = TypeAdapter(list[ProviderProfile])


class ProviderProfileRepository(Protocol):
    """Durable storage interface for provider profiles."""

    def load_all(self) -> list[ProviderProfile]:
        """Return every stored provider profile."""
        ...

    def save_all(
        self,
        profiles: list[ProviderProfile],
    ) -> None:
        """Replace stored provider profiles with the given set."""
        ...


class JsonProviderProfileRepository:
    """
    JSON-file-backed provider profile storage.

    Writes are atomic: the new content is written to a temp file in
    the same directory, flushed and fsynced, then moved into place
    with Path.replace(). A crash or power loss mid-write can then
    never leave a truncated or half-written profiles file behind -
    readers always see either the previous complete file or the new
    complete file.
    """

    def __init__(
        self,
        storage_path: Path,
    ) -> None:
        self._storage_path = storage_path

    def load_all(self) -> list[ProviderProfile]:
        if not self._storage_path.exists():
            return []

        raw_text = self._storage_path.read_text(encoding="utf-8")

        if not raw_text.strip():
            return []

        try:
            return _PROFILE_LIST_ADAPTER.validate_json(raw_text)
        except Exception as exc:
            raise RuntimeError(
                "Provider profile storage is corrupt or invalid: "
                f"{self._storage_path}"
            ) from exc

    def save_all(
        self,
        profiles: list[ProviderProfile],
    ) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)

        ordered = sorted(profiles, key=lambda profile: profile.profile_id)
        payload = _PROFILE_LIST_ADAPTER.dump_json(ordered, indent=2)

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


class InMemoryProviderProfileRepository:
    """In-memory provider profile storage for tests and development."""

    def __init__(
        self,
        profiles: list[ProviderProfile] | None = None,
    ) -> None:
        self._profiles = [profile.model_copy() for profile in (profiles or [])]

    def load_all(self) -> list[ProviderProfile]:
        return [profile.model_copy() for profile in self._profiles]

    def save_all(
        self,
        profiles: list[ProviderProfile],
    ) -> None:
        self._profiles = [profile.model_copy() for profile in profiles]
