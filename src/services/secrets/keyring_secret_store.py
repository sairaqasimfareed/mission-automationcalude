from __future__ import annotations

from typing import Protocol

import keyring


class KeyringBackend(Protocol):
    """Interface for the OS credential vault operations this store needs."""

    def set_password(
        self,
        service_name: str,
        username: str,
        password: str,
    ) -> None: ...

    def get_password(
        self,
        service_name: str,
        username: str,
    ) -> str | None: ...

    def delete_password(
        self,
        service_name: str,
        username: str,
    ) -> None: ...


class _SystemKeyringBackend:
    """Thin wrapper over the keyring package's module-level functions."""

    def set_password(
        self,
        service_name: str,
        username: str,
        password: str,
    ) -> None:
        keyring.set_password(service_name, username, password)

    def get_password(
        self,
        service_name: str,
        username: str,
    ) -> str | None:
        return keyring.get_password(service_name, username)

    def delete_password(
        self,
        service_name: str,
        username: str,
    ) -> None:
        keyring.delete_password(service_name, username)


class KeyringSecretStore:
    """
    SecretStore implementation backed by the operating system credential
    vault (Windows Credential Manager, macOS Keychain, etc.) via the
    keyring package.

    Each secret_reference is stored as one credential entry under a
    single service name, with the reference itself as the username -
    this keeps every provider secret isolated per-reference while still
    grouping them under one identifiable vault entry for the app.
    """

    def __init__(
        self,
        *,
        service_name: str = "mission-automation",
        backend: KeyringBackend | None = None,
    ) -> None:
        self._service_name = service_name
        self._backend = backend if backend is not None else _SystemKeyringBackend()

    def save(
        self,
        secret_reference: str,
        secret_value: str,
    ) -> None:
        self._backend.set_password(
            self._service_name,
            secret_reference,
            secret_value,
        )

    def get(
        self,
        secret_reference: str,
    ) -> str:
        value = self._backend.get_password(
            self._service_name,
            secret_reference,
        )

        if value is None:
            raise KeyError(f"Secret reference was not found: " f"{secret_reference}")

        return value

    def delete(
        self,
        secret_reference: str,
    ) -> None:
        if not self.contains(secret_reference):
            raise KeyError(f"Secret reference was not found: " f"{secret_reference}")

        self._backend.delete_password(
            self._service_name,
            secret_reference,
        )

    def contains(
        self,
        secret_reference: str,
    ) -> bool:
        return (
            self._backend.get_password(
                self._service_name,
                secret_reference,
            )
            is not None
        )
