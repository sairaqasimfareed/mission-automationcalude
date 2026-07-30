from __future__ import annotations

from pydantic import field_validator, model_validator

from src.models.asset_state import AssetCandidate
from src.models.base import MissionBaseModel
from src.models.media_strategy import SceneSourceType
from src.models.scene import Scene


class StockAcquisitionRequest(MissionBaseModel):
    """
    Request contract for acquiring one approved stock candidate.

    This model keeps stock selection separate from stock acquisition.
    """

    project_id: str
    scene: Scene
    candidate: AssetCandidate

    @field_validator("project_id")
    @classmethod
    def clean_project_id(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError(
                "Stock acquisition project ID cannot be empty."
            )

        return normalized

    @model_validator(mode="after")
    def validate_acquisition_request(
        self,
    ) -> StockAcquisitionRequest:
        if (
            self.scene.source_type
            != SceneSourceType.STOCK_FOOTAGE
        ):
            raise ValueError(
                "Stock acquisition requires a stock-footage scene."
            )

        if (
            self.candidate.source_type
            != SceneSourceType.STOCK_FOOTAGE
        ):
            raise ValueError(
                "Stock acquisition requires a stock-footage candidate."
            )

        if not self.candidate.approved:
            raise ValueError(
                "Stock acquisition requires an approved candidate."
            )

        if (
            self.candidate.source_url is None
            or not self.candidate.source_url.strip()
        ):
            raise ValueError(
                "Approved stock candidate requires a source URL."
            )

        return self