from __future__ import annotations

from src.models.asset_index import (
    AssetIndex,
    IndexedAsset,
    IndexedAssetType,
)
from src.models.asset_state import AssetCandidate
from src.models.media_strategy import SceneSourceType
from src.models.scene import Scene


class LocalAssetSearchService:
    """Searches the local asset index for scene-matching videos."""

    MINIMUM_MATCH_SCORE = 0.15

    STOP_WORDS = {
        "the",
        "and",
        "with",
        "from",
        "into",
        "this",
        "that",
        "scene",
        "video",
        "camera",
        "moves",
        "cinematic",
        "city",
    }

    def __init__(self, asset_index: AssetIndex) -> None:
        self.asset_index = asset_index

    def search_for_scene(
        self,
        scene: Scene,
        *,
        maximum_results: int = 5,
    ) -> list[AssetCandidate]:
        search_terms = self._build_search_terms(scene)

        scored_assets: list[tuple[float, IndexedAsset]] = []

        for asset in self.asset_index.assets:
            if asset.asset_type != IndexedAssetType.VIDEO:
                continue

            score = self._calculate_score(
                asset=asset,
                search_terms=search_terms,
            )

            if score >= self.MINIMUM_MATCH_SCORE:
                scored_assets.append((score, asset))

        scored_assets.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        return [
            self._to_candidate(asset, score)
            for score, asset in scored_assets[:maximum_results]
        ]

    @classmethod
    def _build_search_terms(
        cls,
        scene: Scene,
    ) -> set[str]:
        combined_text = " ".join(
            [
                scene.title,
                scene.visual_prompt,
                scene.narration,
            ]
        )

        normalized_text = (
            combined_text.lower()
            .replace(",", " ")
            .replace(".", " ")
            .replace("-", " ")
        )

        return {
            word
            for word in normalized_text.split()
            if len(word) >= 3
            and word not in cls.STOP_WORDS
        }

    @staticmethod
    def _calculate_score(
        asset: IndexedAsset,
        search_terms: set[str],
    ) -> float:
        if not search_terms:
            return 0.0

        searchable_values = [
            asset.title,
            *asset.tags,
            *asset.keywords,
        ]

        searchable_text = " ".join(
            value.lower()
            for value in searchable_values
        )

        matched_terms = {
            term
            for term in search_terms
            if term in searchable_text
        }

        if not matched_terms:
            return 0.0

        base_score = len(matched_terms) / len(search_terms)

        resolution_bonus = 0.05 if asset.resolution else 0.0
        reuse_bonus = min(asset.usage_count * 0.01, 0.05)

        return round(
            min(
                base_score
                + resolution_bonus
                + reuse_bonus,
                1.0,
            ),
            4,
        )

    @staticmethod
    def _to_candidate(
        asset: IndexedAsset,
        score: float,
    ) -> AssetCandidate:
        return AssetCandidate(
            title=asset.title,
            source_type=SceneSourceType.LOCAL_LIBRARY,
            file_path=asset.file_path,
            provider=asset.provider,
            license_type=asset.license_type,
            duration_seconds=asset.duration_seconds,
            resolution=asset.resolution,
            aspect_ratio=asset.aspect_ratio,
            last_used_at=asset.last_used_at,
            usage_count=asset.usage_count,
            score=score,
            tags=asset.tags,
            metadata={
                "asset_id": str(asset.id),
                "content_hash": asset.content_hash,
            },
        )