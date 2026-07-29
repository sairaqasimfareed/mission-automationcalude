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


print("Provider Secret Manager tests completed successfully.")
