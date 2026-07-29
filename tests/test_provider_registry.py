from src.providers.base_provider import BaseProvider
from src.providers.registry import ProviderRegistry


class HealthyProvider(BaseProvider):

    @property
    def provider_name(self) -> str:
        return "HealthyProvider"

    def health_check(self) -> bool:
        return True


class UnhealthyProvider(BaseProvider):

    @property
    def provider_name(self) -> str:
        return "UnhealthyProvider"

    def health_check(self) -> bool:
        return False


registry = ProviderRegistry()

healthy_provider = HealthyProvider()
unhealthy_provider = UnhealthyProvider()

registry.register(healthy_provider)
registry.register(unhealthy_provider)

print(
    "Healthy registered:",
    registry.is_registered("HealthyProvider"),
)
print(
    "Unhealthy registered:",
    registry.is_registered("UnhealthyProvider"),
)
print(
    "Selected provider:",
    registry.get("HealthyProvider").provider_name,
)
print(
    "Healthy providers:",
    registry.healthy_providers(),
)

assert registry.is_registered("HealthyProvider") is True
assert registry.is_registered("MissingProvider") is False
assert registry.get("HealthyProvider") is healthy_provider
assert registry.healthy_providers() == ["HealthyProvider"]

try:
    registry.get("MissingProvider")
except KeyError as error:
    print("Missing provider correctly blocked:", error)
else:
    raise AssertionError(
        "Missing provider should have raised KeyError."
    )

print("Provider Registry tests completed successfully.")