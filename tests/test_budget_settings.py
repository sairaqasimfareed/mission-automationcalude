from pydantic import ValidationError

from src.models.budget_settings import BudgetSettings

settings = BudgetSettings()

print(settings.total_budget_usd)
print(settings.available_budget)

assert settings.total_budget_usd == 10.0
assert settings.available_budget == 9.0


custom = BudgetSettings(
    total_budget_usd=25,
    reserve_budget_usd=5,
)

assert custom.available_budget == 20


try:
    BudgetSettings(
        total_budget_usd=5,
        reserve_budget_usd=10,
    )
except ValidationError:
    print("Reserve validation passed.")
else:
    raise AssertionError


serialized = settings.model_dump_json()

restored = BudgetSettings.model_validate_json(serialized)

assert restored == settings

print("Budget Settings tests completed successfully.")
