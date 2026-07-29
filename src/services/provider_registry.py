from __future__ import annotations

from src.models.provider_profile import (
    ProviderCategory,
    ProviderProfile,
)


class ProviderRegistry:
    """Stores and retrieves configured provider profiles."""

    def __init__(
        self,
        profiles: list[ProviderProfile] | None = None,
    ) -> None:
        self._profiles: dict[str, ProviderProfile] = {}

        for profile in profiles or []:
            self.register(profile)

    def register(
        self,
        profile: ProviderProfile,
        *,
        replace: bool = False,
    ) -> None:
        """Register one provider profile."""

        existing = self._profiles.get(profile.profile_id)

        if existing is not None and not replace:
            raise ValueError(
                "Provider profile already exists: "
                f"{profile.profile_id}"
            )

        self._profiles[profile.profile_id] = profile

    def unregister(
        self,
        profile_id: str,
    ) -> ProviderProfile:
        """Remove and return one registered profile."""

        normalized_id = profile_id.strip()

        if normalized_id not in self._profiles:
            raise KeyError(
                f"Provider profile is not registered: "
                f"{normalized_id}"
            )

        return self._profiles.pop(normalized_id)

    def get(
        self,
        profile_id: str,
    ) -> ProviderProfile:
        """Return one profile by its unique ID."""

        normalized_id = profile_id.strip()

        if normalized_id not in self._profiles:
            raise KeyError(
                f"Provider profile is not registered: "
                f"{normalized_id}"
            )

        return self._profiles[normalized_id]

    def contains(
        self,
        profile_id: str,
    ) -> bool:
        """Return whether a profile is registered."""

        return profile_id.strip() in self._profiles

    def list_all(self) -> list[ProviderProfile]:
        """Return all profiles ordered by priority and name."""

        return sorted(
            self._profiles.values(),
            key=lambda profile: (
                profile.priority,
                profile.display_name.lower(),
                profile.profile_id,
            ),
        )

    def list_by_category(
        self,
        category: ProviderCategory,
        *,
        enabled_only: bool = False,
        usable_only: bool = False,
    ) -> list[ProviderProfile]:
        """Return profiles from one provider category."""

        profiles = [
            profile
            for profile in self._profiles.values()
            if profile.category == category
        ]

        if usable_only:
            profiles = [
                profile
                for profile in profiles
                if profile.usable
            ]
        elif enabled_only:
            profiles = [
                profile
                for profile in profiles
                if profile.enabled
            ]

        return sorted(
            profiles,
            key=lambda profile: (
                profile.priority,
                profile.display_name.lower(),
                profile.profile_id,
            ),
        )

    def find_supporting(
        self,
        category: ProviderCategory,
        capability: str,
        *,
        usable_only: bool = True,
    ) -> list[ProviderProfile]:
        """Return profiles supporting a required capability."""

        profiles = self.list_by_category(
            category,
            usable_only=usable_only,
        )

        return [
            profile
            for profile in profiles
            if profile.supports(capability)
        ]

    @property
    def count(self) -> int:
        """Return the total number of registered profiles."""

        return len(self._profiles)