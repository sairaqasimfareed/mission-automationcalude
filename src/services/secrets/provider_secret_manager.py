from __future__ import annotations

from typing import Protocol
from uuid import uuid4

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class SecretStore(Protocol):
    """Storage interface for provider secrets."""

    def save(
        self,
        secret_reference: str,
        secret_value: str,
    ) -> None:
        """Store one secret value."""
        ...

    def get(
        self,
        secret_reference: str,
    ) -> str:
        """Return one stored secret value."""
        ...

    def delete(
        self,
        secret_reference: str,
    ) -> None:
        """Delete one stored secret value."""
        ...

    def contains(
        self,
        secret_reference: str,
    ) -> bool:
        """Return whether a secret exists."""
        ...


class InMemorySecretStore:
    """In-memory secret storage for tests and development."""

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def save(
        self,
        secret_reference: str,
        secret_value: str,
    ) -> None:
        self._secrets[secret_reference] = secret_value

    def get(
        self,
        secret_reference: str,
    ) -> str:
        if secret_reference not in self._secrets:
            raise KeyError(
                f"Secret reference was not found: "
                f"{secret_reference}"
            )

        return self._secrets[secret_reference]

    def delete(
        self,
        secret_reference: str,
    ) -> None:
        if secret_reference not in self._secrets:
            raise KeyError(
                f"Secret reference was not found: "
                f"{secret_reference}"
            )

        del self._secrets[secret_reference]

    def contains(
        self,
        secret_reference: str,
    ) -> bool:
        return secret_reference in self._secrets


class ProviderSecretResult(MissionBaseModel):
    """Safe result returned after storing or updating a secret."""

    secret_reference: str

    masked_value: str = Field(
        min_length=4,
    )

    created: bool = False
    replaced: bool = False


class ProviderSecretManager:
    """Creates and manages provider secrets safely."""

    def __init__(
        self,
        secret_store: SecretStore,
    ) -> None:
        self.secret_store = secret_store

    def create_secret(
        self,
        *,
        profile_id: str,
        secret_value: str,
    ) -> ProviderSecretResult:
        """Create and store a new provider secret."""

        normalized_profile_id = self._clean_profile_id(
            profile_id
        )

        normalized_secret = self._validate_secret(
            secret_value
        )

        secret_reference = (
            "secret://providers/"
            f"{normalized_profile_id}/"
            f"{uuid4()}"
        )

        self.secret_store.save(
            secret_reference,
            normalized_secret,
        )

        return ProviderSecretResult(
            secret_reference=secret_reference,
            masked_value=self.mask_secret(
                normalized_secret
            ),
            created=True,
        )

    def replace_secret(
        self,
        *,
        secret_reference: str,
        new_secret_value: str,
    ) -> ProviderSecretResult:
        """Replace an existing provider secret."""

        normalized_reference = (
            self._validate_reference(
                secret_reference
            )
        )

        if not self.secret_store.contains(
            normalized_reference
        ):
            raise KeyError(
                "Cannot replace a secret that does not exist."
            )

        normalized_secret = self._validate_secret(
            new_secret_value
        )

        self.secret_store.save(
            normalized_reference,
            normalized_secret,
        )

        return ProviderSecretResult(
            secret_reference=normalized_reference,
            masked_value=self.mask_secret(
                normalized_secret
            ),
            replaced=True,
        )

    def resolve_secret(
        self,
        secret_reference: str,
    ) -> str:
        """
        Return a secret for provider execution.

        This method must only be used inside trusted backend code.
        """

        normalized_reference = (
            self._validate_reference(
                secret_reference
            )
        )

        return self.secret_store.get(
            normalized_reference
        )

    def delete_secret(
        self,
        secret_reference: str,
    ) -> None:
        """Delete one provider secret."""

        normalized_reference = (
            self._validate_reference(
                secret_reference
            )
        )

        self.secret_store.delete(
            normalized_reference
        )

    def secret_exists(
        self,
        secret_reference: str,
    ) -> bool:
        """Return whether a secret reference exists."""

        normalized_reference = (
            self._validate_reference(
                secret_reference
            )
        )

        return self.secret_store.contains(
            normalized_reference
        )

    def get_masked_secret(
        self,
        secret_reference: str,
    ) -> str:
        """Return a masked representation of a stored secret."""

        secret_value = self.resolve_secret(
            secret_reference
        )

        return self.mask_secret(secret_value)

    @staticmethod
    def mask_secret(
        secret_value: str,
    ) -> str:
        """Return a safely masked secret string."""

        normalized_secret = secret_value.strip()

        if len(normalized_secret) <= 4:
            return "•" * len(normalized_secret)

        visible_prefix_length = min(
            4,
            max(1, len(normalized_secret) // 4),
        )

        visible_suffix_length = min(
            4,
            max(1, len(normalized_secret) // 4),
        )

        hidden_length = (
            len(normalized_secret)
            - visible_prefix_length
            - visible_suffix_length
        )

        return (
            normalized_secret[:visible_prefix_length]
            + ("•" * hidden_length)
            + normalized_secret[-visible_suffix_length:]
        )

    @staticmethod
    def _validate_secret(
        secret_value: str,
    ) -> str:
        normalized_secret = secret_value.strip()

        if not normalized_secret:
            raise ValueError(
                "Secret value cannot be empty."
            )

        if len(normalized_secret) < 8:
            raise ValueError(
                "Secret value must contain at least "
                "8 characters."
            )

        return normalized_secret

    @staticmethod
    def _validate_reference(
        secret_reference: str,
    ) -> str:
        normalized_reference = secret_reference.strip()

        if not normalized_reference:
            raise ValueError(
                "Secret reference cannot be empty."
            )

        if not normalized_reference.startswith(
            "secret://"
        ):
            raise ValueError(
                "Invalid provider secret reference."
            )

        return normalized_reference

    @staticmethod
    def _clean_profile_id(
        profile_id: str,
    ) -> str:
        normalized_profile_id = profile_id.strip()

        if not normalized_profile_id:
            raise ValueError(
                "Provider profile ID cannot be empty."
            )

        return normalized_profile_id