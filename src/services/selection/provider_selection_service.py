from __future__ import annotations

from pydantic import Field

from src.models.base import MissionBaseModel
from src.models.provider_preferences import ProviderPreference
from src.models.provider_profile import (
    ProviderCategory,
    ProviderProfile,
)
from src.services.registry.provider_registry import (
    ProviderRegistry,
)


class ProviderSelectionRequest(MissionBaseModel):
    """Input required to select one provider profile."""

    category: ProviderCategory
    required_capability: str | None = None
    preference: ProviderPreference | None = None
    allow_fallback: bool = True


class ProviderSelectionResult(MissionBaseModel):
    """Result of one provider-selection operation."""

    selected_profile: ProviderProfile

    used_preferred_profile: bool = False
    used_fallback_profile: bool = False

    considered_profile_ids: list[str] = Field(
        default_factory=list,
    )

    warnings: list[str] = Field(
        default_factory=list,
    )


class ProviderSelectionService:
    """Selects the best usable provider for one operation."""

    def __init__(
        self,
        registry: ProviderRegistry,
    ) -> None:
        self.registry = registry

    def select(
        self,
        request: ProviderSelectionRequest,
    ) -> ProviderSelectionResult:
        """Select one provider using preference and fallback rules."""

        considered: list[str] = []
        warnings: list[str] = []

        preference = request.preference

        if preference is not None and preference.preferred_profile_id is not None:
            preferred_id = preference.preferred_profile_id.strip()

            preferred_profile = self._get_candidate(
                profile_id=preferred_id,
                category=request.category,
                required_capability=(request.required_capability),
                considered=considered,
            )

            if preferred_profile is not None:
                return ProviderSelectionResult(
                    selected_profile=preferred_profile,
                    used_preferred_profile=True,
                    considered_profile_ids=considered,
                    warnings=warnings,
                )

            warnings.append(
                "Preferred provider profile was unavailable "
                f"or incompatible: {preferred_id}"
            )

            if preference.lock_preferred_provider:
                raise ValueError(
                    "Locked preferred provider profile is "
                    "unavailable or incompatible."
                )

        if request.allow_fallback and preference is not None:
            for fallback_id in preference.fallback_profile_ids:
                fallback_profile = self._get_candidate(
                    profile_id=fallback_id,
                    category=request.category,
                    required_capability=(request.required_capability),
                    considered=considered,
                )

                if fallback_profile is not None:
                    return ProviderSelectionResult(
                        selected_profile=fallback_profile,
                        used_fallback_profile=True,
                        considered_profile_ids=considered,
                        warnings=warnings,
                    )

        candidates = self._list_candidates(
            category=request.category,
            required_capability=request.required_capability,
        )

        for candidate in candidates:
            if candidate.profile_id not in considered:
                considered.append(candidate.profile_id)

            return ProviderSelectionResult(
                selected_profile=candidate,
                considered_profile_ids=considered,
                warnings=warnings,
            )

        raise ValueError(
            "No usable provider profile was found for "
            f"category {request.category.value}."
        )

    def _get_candidate(
        self,
        *,
        profile_id: str,
        category: ProviderCategory,
        required_capability: str | None,
        considered: list[str],
    ) -> ProviderProfile | None:
        normalized_id = profile_id.strip()

        if normalized_id not in considered:
            considered.append(normalized_id)

        if not self.registry.contains(normalized_id):
            return None

        profile = self.registry.get(normalized_id)

        if profile.category != category:
            return None

        if not profile.usable:
            return None

        if required_capability is not None and not profile.supports(
            required_capability
        ):
            return None

        return profile

    def _list_candidates(
        self,
        *,
        category: ProviderCategory,
        required_capability: str | None,
    ) -> list[ProviderProfile]:
        if required_capability is not None:
            return self.registry.find_supporting(
                category=category,
                capability=required_capability,
                usable_only=True,
            )

        return self.registry.list_by_category(
            category=category,
            usable_only=True,
        )
