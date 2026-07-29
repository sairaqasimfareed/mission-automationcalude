from src.models.provider_profile import (
    ProviderCategory,
    ProviderProfile,
)
from src.services.budget.provider_budget_service import (
    ProviderBudgetService,
)
from src.services.registry.provider_registry import (
    ProviderRegistry,
)


limited_profile = ProviderProfile(
    profile_id="video-main",
    display_name="Video Main",
    provider_name="Video Provider",
    category=ProviderCategory.VIDEO,
    daily_budget_usd=10.0,
    daily_spent_usd=2.0,
    monthly_budget_usd=100.0,
    monthly_spent_usd=20.0,
    per_request_budget_usd=5.0,
)

unlimited_profile = ProviderProfile(
    profile_id="stock-unlimited",
    display_name="Stock Unlimited",
    provider_name="Stock Provider",
    category=ProviderCategory.STOCK_VIDEO,
)

registry = ProviderRegistry(
    profiles=[
        limited_profile,
        unlimited_profile,
    ]
)

service = ProviderBudgetService(registry)


allowed_result = service.check_request(
    profile_id="video-main",
    estimated_cost_usd=3.0,
)

print("Allowed:", allowed_result.allowed)
print("Reason:", allowed_result.reason)
print(
    "Remaining daily:",
    allowed_result.remaining_daily_budget_usd,
)
print(
    "Remaining monthly:",
    allowed_result.remaining_monthly_budget_usd,
)

assert allowed_result.allowed is True
assert allowed_result.remaining_daily_budget_usd == 8.0
assert allowed_result.remaining_monthly_budget_usd == 80.0


per_request_result = service.check_request(
    profile_id="video-main",
    estimated_cost_usd=6.0,
)

assert per_request_result.allowed is False
assert "per-request" in per_request_result.reason


reserved_profile = service.reserve(
    profile_id="video-main",
    estimated_cost_usd=3.0,
)

print(
    "Daily spent after reservation:",
    reserved_profile.daily_spent_usd,
)
print(
    "Monthly spent after reservation:",
    reserved_profile.monthly_spent_usd,
)

assert reserved_profile.daily_spent_usd == 5.0
assert reserved_profile.monthly_spent_usd == 23.0

assert service.remaining_daily_budget(
    "video-main"
) == 5.0

assert service.remaining_monthly_budget(
    "video-main"
) == 77.0


released_profile = service.release(
    profile_id="video-main",
    reserved_cost_usd=1.0,
)

assert released_profile.daily_spent_usd == 4.0
assert released_profile.monthly_spent_usd == 22.0


adjusted_profile = service.adjust_reserved_cost(
    profile_id="video-main",
    reserved_cost_usd=2.0,
    actual_cost_usd=1.5,
)

assert adjusted_profile.daily_spent_usd == 3.5
assert adjusted_profile.monthly_spent_usd == 21.5


assert service.is_budget_available(
    profile_id="video-main",
    estimated_cost_usd=2.0,
) is True

assert service.is_budget_available(
    profile_id="video-main",
    estimated_cost_usd=7.0,
) is False


unlimited_result = service.check_request(
    profile_id="stock-unlimited",
    estimated_cost_usd=500.0,
)

assert unlimited_result.allowed is True
assert unlimited_result.remaining_daily_budget_usd is None
assert unlimited_result.remaining_monthly_budget_usd is None


try:
    service.check_request(
        profile_id="video-main",
        estimated_cost_usd=-1.0,
    )
except ValueError:
    print("Negative estimated cost successfully blocked.")
else:
    raise AssertionError(
        "Negative estimated cost should fail."
    )


try:
    service.release(
        profile_id="video-main",
        reserved_cost_usd=100.0,
    )
except ValueError:
    print("Invalid budget release successfully blocked.")
else:
    raise AssertionError(
        "Releasing more than recorded spending should fail."
    )


print(
    "Provider Budget Service tests completed successfully."
)