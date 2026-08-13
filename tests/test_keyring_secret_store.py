from __future__ import annotations

from src.services.secrets.keyring_secret_store import KeyringSecretStore


class FakeKeyringBackend:
    """In-memory stand-in for the OS credential vault, used for tests so
    KeyringSecretStore never touches the real Windows Credential Manager."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], str] = {}

    def set_password(
        self,
        service_name: str,
        username: str,
        password: str,
    ) -> None:
        self._entries[(service_name, username)] = password

    def get_password(
        self,
        service_name: str,
        username: str,
    ) -> str | None:
        return self._entries.get((service_name, username))

    def delete_password(
        self,
        service_name: str,
        username: str,
    ) -> None:
        del self._entries[(service_name, username)]


backend = FakeKeyringBackend()
store = KeyringSecretStore(service_name="mission-automation-tests", backend=backend)

reference = "secret://providers/llm-main/one"

assert not store.contains(reference)

store.save(reference, "sk-test-secret-123456")

assert store.contains(reference)
assert store.get(reference) == "sk-test-secret-123456"

# Stored directly on the fake vault, under this store's service name.
assert backend.get_password("mission-automation-tests", reference) == (
    "sk-test-secret-123456"
)

store.save(reference, "sk-replaced-secret-654321")

assert store.get(reference) == "sk-replaced-secret-654321"

store.delete(reference)

assert not store.contains(reference)

try:
    store.get(reference)
except KeyError:
    print("Missing secret successfully blocked on get().")
else:
    raise AssertionError("get() on a missing secret should raise KeyError.")

try:
    store.delete(reference)
except KeyError:
    print("Missing secret successfully blocked on delete().")
else:
    raise AssertionError("delete() on a missing secret should raise KeyError.")


other_store = KeyringSecretStore(
    service_name="mission-automation-tests-other", backend=backend
)

store.save(reference, "sk-isolated-secret-11111")

assert not other_store.contains(reference)


print("Keyring Secret Store tests completed successfully.")
