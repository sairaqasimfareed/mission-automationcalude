from __future__ import annotations

from src.models.provider_preferences import (
    ProviderPreference,
)
from src.models.provider_profile import (
    ProviderCategory,
)
from src.services.budget.provider_budget_service import (
    ProviderBudgetService,
)
from src.services.factory.provider_factory import (
    BaseProvider,
    ProviderFactory,
)
from src.services.registry.provider_registry import (
    ProviderRegistry,
)
from src.services.selection.provider_selection_service import (
    ProviderSelectionRequest,
    ProviderSelectionService,
)


class ProviderManager:
    """Coordinates provider selection and creation."""

    def __init__(
        self,
        registry: ProviderRegistry,
        selection_service: ProviderSelectionService,
        budget_service: ProviderBudgetService,
        factory: ProviderFactory,
    ) -> None:

        self.registry = registry
        self.selection_service = selection_service
        self.budget_service = budget_service
        self.factory = factory

    def get_provider(
        self,
        *,
        category: ProviderCategory,
        estimated_cost_usd: float = 0.0,
        required_capability: str | None = None,
        preference: ProviderPreference | None = None,
    ) -> BaseProvider:
        """
        Select, validate budget and create one provider.
        """

        selection = self.selection_service.select(
            ProviderSelectionRequest(
                category=category,
                required_capability=required_capability,
                preference=preference,
            )
        )

        profile = selection.selected_profile

        budget = self.budget_service.check_request(
            profile.profile_id,
            estimated_cost_usd,
        )

        if not budget.allowed:
            raise ValueError(budget.reason)

        return self.factory.create(
            profile.profile_id,
        )
