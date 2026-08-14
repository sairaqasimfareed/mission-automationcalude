from __future__ import annotations

from src.models.http_adapter_config import HttpResponseMode
from src.models.provider_profile import ProviderProfile
from src.services.http.http_provider_executor import HttpProviderExecutor
from src.services.stock_search_service import StockSearchRequest, StockSearchResponse


class GenericHttpStockProvider:
    """
    No-code StockProviderAdapter, driven entirely by a ProviderProfile's
    http_adapter_config.

    Structurally implements StockProviderAdapter (a Protocol, so no
    explicit base class is required). Unlike the single-file voice/
    music/sound-effect providers, a stock search response is a JSON
    array of results, mapped field-by-field via
    HttpAdapterConfig.response_field_mapping.
    """

    def __init__(
        self,
        *,
        profile: ProviderProfile,
        api_key: str,
        executor: HttpProviderExecutor | None = None,
    ) -> None:
        if profile.http_adapter_config is None:
            raise ValueError(
                f"Provider profile '{profile.profile_id}' has no "
                "http_adapter_config; GenericHttpStockProvider requires one."
            )

        if (
            profile.http_adapter_config.response_mode
            != HttpResponseMode.JSON_RESULT_LIST
        ):
            raise ValueError(
                f"Provider profile '{profile.profile_id}' has "
                f"response_mode={profile.http_adapter_config.response_mode.value}, "
                "but a stock provider must use json_result_list."
            )

        self._profile = profile
        self._config = profile.http_adapter_config
        self._api_key = api_key
        self._executor = executor or HttpProviderExecutor()

    @property
    def provider_name(self) -> str:
        return self._profile.provider_name

    def health_check(self) -> bool:
        return True

    def search(self, request: StockSearchRequest) -> StockSearchResponse:
        placeholders = {
            "query": request.query,
            "page": str(request.page),
            "per_page": str(request.per_page),
            "orientation": request.orientation or "",
            "min_duration": self._optional_str(request.minimum_duration_seconds),
            "max_duration": self._optional_str(request.maximum_duration_seconds),
            "min_width": self._optional_str(request.minimum_width),
            "min_height": self._optional_str(request.minimum_height),
        }

        response = self._executor.execute(
            self._config,
            placeholders=placeholders,
            api_key=self._api_key,
            base_url=self._profile.base_url,
            timeout_seconds=float(self._profile.timeout_seconds),
        )

        results = self._executor.extract_json_result_list(
            response,
            self._config,
            provider_name=self.provider_name,
            query=request.query,
        )

        return StockSearchResponse(
            provider=self.provider_name,
            query=request.query,
            results=results,
            page=request.page,
            per_page=request.per_page,
            total_results=len(results),
            has_more=False,
        )

    @staticmethod
    def _optional_str(value: float | int | None) -> str:
        return "" if value is None else str(value)
