from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.services.health.provider_health_service import (
    ProviderHealthService,
)
from src.services.registry.provider_registry import (
    ProviderRegistry,
)


class HealthyChecker:
    def check(
        self,
        profile: ProviderProfile,
    ) -> tuple[bool, str]:
        return True, "Connection successful."


class UnhealthyChecker:
    def check(
        self,
        profile: ProviderProfile,
    ) -> tuple[bool, str]:
        return False, "Provider is unavailable."


class FailingChecker:
    def check(
        self,
        profile: ProviderProfile,
    ) -> tuple[bool, str]:
        raise TimeoutError("Connection timed out.")


healthy_profile = ProviderProfile(
    profile_id="llm-main",
    display_name="LLM Main",
    provider_name="OpenAI",
    category=ProviderCategory.LLM,
    enabled=True,
    secret_reference="secret://llm-main",
)

disabled_profile = ProviderProfile(
    profile_id="voice-disabled",
    display_name="Voice Disabled",
    provider_name="Voice Provider",
    category=ProviderCategory.VOICE,
    enabled=False,
)

registry = ProviderRegistry(
    profiles=[
        healthy_profile,
        disabled_profile,
    ]
)

service = ProviderHealthService(registry)


healthy_result = service.check_profile(
    "llm-main",
    HealthyChecker(),
)

print("Healthy status:", healthy_result.status)
print("Healthy message:", healthy_result.message)

assert healthy_result.healthy is True
assert (
    healthy_result.status
    == ProviderHealthStatus.HEALTHY
)
assert (
    registry.get("llm-main").health_status
    == ProviderHealthStatus.HEALTHY
)


unhealthy_result = service.check_profile(
    "llm-main",
    UnhealthyChecker(),
)

print("Unhealthy status:", unhealthy_result.status)

assert unhealthy_result.healthy is False
assert (
    unhealthy_result.status
    == ProviderHealthStatus.UNHEALTHY
)
assert (
    registry.get("llm-main").health_status
    == ProviderHealthStatus.UNHEALTHY
)


failure_result = service.check_profile(
    "llm-main",
    FailingChecker(),
)

print("Failure status:", failure_result.status)
print("Failure metadata:", failure_result.metadata)

assert failure_result.healthy is False
assert (
    failure_result.status
    == ProviderHealthStatus.UNHEALTHY
)
assert (
    failure_result.metadata["error_type"]
    == "TimeoutError"
)


disabled_result = service.check_profile(
    "voice-disabled",
    HealthyChecker(),
)

print("Disabled status:", disabled_result.status)

assert disabled_result.healthy is False
assert (
    disabled_result.status
    == ProviderHealthStatus.DISABLED
)


degraded_result = service.mark_degraded(
    "llm-main",
    message="High latency detected.",
)

assert degraded_result.healthy is True
assert (
    degraded_result.status
    == ProviderHealthStatus.DEGRADED
)
assert (
    registry.get("llm-main").health_status
    == ProviderHealthStatus.DEGRADED
)


unknown_result = service.mark_unknown(
    "llm-main",
)

assert unknown_result.healthy is False
assert (
    unknown_result.status
    == ProviderHealthStatus.UNKNOWN
)
assert (
    registry.get("llm-main").health_status
    == ProviderHealthStatus.UNKNOWN
)


print(
    "Provider Health Service tests completed successfully."
)