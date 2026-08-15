from __future__ import annotations

from src.models.editorial_profile import (
    FormatProfile,
    FormatProfileResolutionResult,
)
from src.models.genre_profile import GenreProfileStatus, PacingSegment


class FormatProfileRegistryService:
    """
    Stores and resolves structural format profiles.

    Format is orthogonal to genre - the same genre (e.g. History) can
    be told in a documentary, investigation, or top10 structural
    format. Mirrors GenreProfileRegistryService's register/resolve
    shape so callers already familiar with genre resolution need no
    new mental model for format resolution.
    """

    DEFAULT_FORMAT_ID = "format.narrative"

    def __init__(self, profiles: list[FormatProfile] | None = None) -> None:
        self._profiles: dict[str, FormatProfile] = {}

        for profile in profiles or []:
            self.register(profile)

    def register(self, profile: FormatProfile, *, replace: bool = False) -> None:
        """Register one format profile."""

        existing = self._profiles.get(profile.format_id)

        if existing is not None and not replace:
            raise ValueError(
                f"Format profile is already registered: {profile.format_id}"
            )

        self._profiles[profile.format_id] = profile

    def unregister(self, format_id: str) -> FormatProfile:
        """Remove and return one registered profile."""

        normalized_id = self._normalize_format_id(format_id)

        if normalized_id not in self._profiles:
            raise KeyError(f"Format profile is not registered: {normalized_id}")

        if normalized_id == self.DEFAULT_FORMAT_ID:
            raise ValueError("The default format profile cannot be unregistered.")

        return self._profiles.pop(normalized_id)

    def get(self, format_id: str) -> FormatProfile:
        """Return one registered profile."""

        normalized_id = self._normalize_format_id(format_id)

        if normalized_id not in self._profiles:
            raise KeyError(f"Format profile is not registered: {normalized_id}")

        return self._profiles[normalized_id]

    def contains(self, format_id: str) -> bool:
        """Return whether one format profile exists."""

        return self._normalize_format_id(format_id) in self._profiles

    def list_all(self, *, active_only: bool = False) -> list[FormatProfile]:
        """Return all format profiles in stable order."""

        profiles = list(self._profiles.values())

        if active_only:
            profiles = [profile for profile in profiles if profile.usable]

        return sorted(
            profiles,
            key=lambda profile: (profile.display_name.lower(), profile.format_id),
        )

    def resolve(
        self, format_id: str, *, allow_fallback: bool = True
    ) -> FormatProfileResolutionResult:
        """Resolve one format profile, falling back to the default format."""

        normalized_id = self._normalize_format_id(format_id)

        exact_profile = self._profiles.get(normalized_id)

        if exact_profile is not None and exact_profile.usable:
            return FormatProfileResolutionResult(
                requested_format_id=normalized_id,
                resolved_format_id=exact_profile.format_id,
                profile=exact_profile,
                found_exact_match=True,
                used_fallback=False,
            )

        warning = self._build_unresolved_warning(
            format_id=normalized_id, profile=exact_profile
        )

        if not allow_fallback:
            return FormatProfileResolutionResult(
                requested_format_id=normalized_id, warning=warning
            )

        fallback_profile = self._profiles.get(self.DEFAULT_FORMAT_ID)

        if fallback_profile is None or not fallback_profile.usable:
            return FormatProfileResolutionResult(
                requested_format_id=normalized_id,
                warning=warning + " No usable fallback format profile is registered.",
            )

        return FormatProfileResolutionResult(
            requested_format_id=normalized_id,
            resolved_format_id=fallback_profile.format_id,
            profile=fallback_profile,
            found_exact_match=False,
            used_fallback=True,
            warning=(
                warning + f" Safe fallback '{fallback_profile.format_id}' was selected."
            ),
        )

    @classmethod
    def with_default_profiles(cls) -> FormatProfileRegistryService:
        """Create a registry with built-in format profiles."""

        return cls(profiles=cls._build_default_profiles())

    @staticmethod
    def _normalize_format_id(format_id: str) -> str:
        normalized = format_id.strip().lower()

        if not normalized.startswith("format."):
            raise ValueError("Format profile ID must start with 'format.'.")

        if normalized == "format.":
            raise ValueError("Format profile ID requires a name.")

        allowed_characters = set("abcdefghijklmnopqrstuvwxyz0123456789._-")

        if any(character not in allowed_characters for character in normalized):
            raise ValueError("Format profile ID contains unsupported characters.")

        return normalized

    @staticmethod
    def _build_unresolved_warning(
        *, format_id: str, profile: FormatProfile | None
    ) -> str:
        if profile is None:
            return f"Requested format profile is not registered: {format_id}."

        if profile.status == GenreProfileStatus.DISABLED:
            return f"Requested format profile is disabled: {format_id}."

        return f"Requested format profile is not active: {format_id}."

    @staticmethod
    def _build_default_profiles() -> list[FormatProfile]:
        """Return initial built-in structural format profiles."""

        return [
            FormatProfile(
                format_id="format.narrative",
                display_name="Narrative",
                description=(
                    "General-purpose narrative format with no structural "
                    "bias - the genre's own defaults apply unmodified."
                ),
            ),
            FormatProfile(
                format_id="format.documentary",
                display_name="Documentary",
                description=(
                    "Evidence-led expository format: context, evidence, "
                    "development, consequence - slower cutting, heavier "
                    "setup/reveal beats."
                ),
                narrative_architecture_hint=(
                    "Hook/contradiction -> central question -> context -> "
                    "evidence -> development -> complication -> discovery -> "
                    "consequence -> conclusion."
                ),
                beat_type_bias=["setup", "reveal", "escalation", "payoff"],
                scene_density_multiplier=0.85,
            ),
            FormatProfile(
                format_id="format.investigation",
                display_name="Investigation",
                description=(
                    "Mystery-driven investigative format: contradiction, "
                    "evidence, hidden connections, major reveal, "
                    "counterargument."
                ),
                narrative_architecture_hint=(
                    "Mystery -> known facts -> contradiction -> evidence -> "
                    "new question -> hidden connection -> major reveal -> "
                    "counterargument -> evidence evaluation -> conclusion."
                ),
                pacing_curve_override=[
                    PacingSegment(
                        progress_start=0.0,
                        progress_end=0.15,
                        information_density=45,
                        emotional_intensity=40,
                        reveal_probability=25,
                        tension_level=35,
                    ),
                    PacingSegment(
                        progress_start=0.15,
                        progress_end=0.45,
                        information_density=55,
                        emotional_intensity=45,
                        reveal_probability=35,
                        tension_level=45,
                    ),
                    PacingSegment(
                        progress_start=0.45,
                        progress_end=0.75,
                        information_density=60,
                        emotional_intensity=55,
                        reveal_probability=45,
                        tension_level=60,
                    ),
                    PacingSegment(
                        progress_start=0.75,
                        progress_end=0.90,
                        information_density=55,
                        emotional_intensity=75,
                        reveal_probability=70,
                        tension_level=80,
                    ),
                    PacingSegment(
                        progress_start=0.90,
                        progress_end=1.0,
                        information_density=40,
                        emotional_intensity=55,
                        reveal_probability=40,
                        tension_level=50,
                    ),
                ],
                beat_type_bias=[
                    "hook",
                    "reveal",
                    "re_hook",
                    "major_revelation",
                    "climax",
                    "payoff",
                ],
                scene_density_multiplier=1.0,
            ),
            FormatProfile(
                format_id="format.top10",
                display_name="Top 10",
                description=(
                    "Ranked-list format: repeated setup/reveal cycles, "
                    "escalating toward a #1 payoff - much higher scene and "
                    "reveal density than the genre default."
                ),
                narrative_architecture_hint=(
                    "Strong promise -> ranking setup -> #10 -> escalating "
                    "entries -> pattern interrupts -> increasingly strong "
                    "entries -> #1 payoff -> conclusion."
                ),
                beat_type_bias=["hook", "reveal", "escalation", "climax", "payoff"],
                scene_density_multiplier=1.6,
            ),
        ]
