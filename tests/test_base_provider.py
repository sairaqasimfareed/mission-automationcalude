from src.providers.base_provider import BaseProvider


class DummyProvider(BaseProvider):

    @property
    def provider_name(self) -> str:
        return "Dummy"

    def health_check(self) -> bool:
        return True


provider = DummyProvider()

print("Provider:", provider.provider_name)
print("Healthy:", provider.health_check())

assert provider.provider_name == "Dummy"
assert provider.health_check() is True

print("Base Provider tests completed successfully.")