from src.services.secrets.provider_secret_manager import (
    InMemorySecretStore,
    ProviderSecretManager,
)

store = InMemorySecretStore()
manager = ProviderSecretManager(store)


created_result = manager.create_secret(
    profile_id="openai-main",
    secret_value="sk-test-secret-123456",
)

print(
    "Secret reference:",
    created_result.secret_reference,
)
print(
    "Masked secret:",
    created_result.masked_value,
)

assert created_result.created is True
assert created_result.replaced is False

assert created_result.secret_reference.startswith("secret://providers/openai-main/")

assert manager.secret_exists(created_result.secret_reference)

resolved_secret = manager.resolve_secret(created_result.secret_reference)

assert resolved_secret == "sk-test-secret-123456"

assert manager.get_masked_secret(created_result.secret_reference) != resolved_secret

assert "123456" not in created_result.masked_value


replaced_result = manager.replace_secret(
    secret_reference=(created_result.secret_reference),
    new_secret_value="new-secret-value-987654",
)

print(
    "Replaced masked secret:",
    replaced_result.masked_value,
)

assert replaced_result.created is False
assert replaced_result.replaced is True

assert (
    manager.resolve_secret(created_result.secret_reference) == "new-secret-value-987654"
)


manager.delete_secret(created_result.secret_reference)

assert not manager.secret_exists(created_result.secret_reference)


try:
    manager.resolve_secret(created_result.secret_reference)
except KeyError:
    print("Deleted secret successfully blocked.")
else:
    raise AssertionError("Deleted secret should not be available.")


try:
    manager.create_secret(
        profile_id="voice-main",
        secret_value="",
    )
except ValueError:
    print("Empty secret successfully blocked.")
else:
    raise AssertionError("Empty secret should fail.")


try:
    manager.create_secret(
        profile_id="voice-main",
        secret_value="short",
    )
except ValueError:
    print("Short secret successfully blocked.")
else:
    raise AssertionError("Short secret should fail.")


try:
    manager.get_masked_secret("invalid-reference")
except ValueError:
    print("Invalid secret reference successfully blocked.")
else:
    raise AssertionError("Invalid secret reference should fail.")


masked = ProviderSecretManager.mask_secret("abcdefgh12345678")

print("Standalone masked secret:", masked)

assert masked.startswith("abcd")
assert masked.endswith("5678")
assert masked != "abcdefgh12345678"


# Real bug fix, 2026-09-23: create_secret() called again for the SAME
# profile_id must reuse the exact same reference and overwrite the
# stored value in place, not mint a new one - the real, expected case
# every time an app restart rebuilds its runtime configuration from
# the same .env API keys. Previously this accumulated a brand-new
# Windows Credential Manager entry on every single app launch/test
# run with no cleanup, eventually exhausting the real OS credential
# store (see windows_credential_store_exhaustion memory).
reuse_store = InMemorySecretStore()
reuse_manager = ProviderSecretManager(reuse_store)

first_result = reuse_manager.create_secret(
    profile_id="provider.llm.openai",
    secret_value="sk-first-secret-key-1",
)

assert first_result.created is True
assert first_result.replaced is False

second_result = reuse_manager.create_secret(
    profile_id="provider.llm.openai",
    secret_value="sk-second-secret-key-2",
)

assert second_result.secret_reference == first_result.secret_reference
assert second_result.created is False
assert second_result.replaced is True

assert (
    reuse_manager.resolve_secret(first_result.secret_reference)
    == "sk-second-secret-key-2"
)

print("Repeated create_secret() for the same profile_id reuses one reference.")


# Real bug fix, 2026-09-23: replace_secret() must self-heal rather than
# hard-fail when the underlying store entry no longer exists (e.g. a
# durably-persisted ProviderProfile's secret_reference outliving an
# externally-deleted Windows Credential Manager entry) - the normal
# "re-enter your API key" recovery path goes through replace_secret(),
# so it must not raise here.
healing_store = InMemorySecretStore()
healing_manager = ProviderSecretManager(healing_store)

missing_reference = "secret://providers/voice/does-not-exist-anymore"

healed_result = healing_manager.replace_secret(
    secret_reference=missing_reference,
    new_secret_value="sk-recovered-secret-key",
)

assert healed_result.secret_reference == missing_reference
assert healed_result.created is True
assert healed_result.replaced is False
assert healing_manager.resolve_secret(missing_reference) == "sk-recovered-secret-key"

print("replace_secret() self-heals a missing reference instead of raising.")


print("Provider Secret Manager tests completed successfully.")
