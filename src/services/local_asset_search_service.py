from __future__ import annotations

from src.models.asset_index import (
    AssetIndex,
    IndexedAsset,
    IndexedAssetType,
)
from src.models.asset_state import AssetCandidate
from src.models.media_strategy import SceneSourceType
from src.models.scene import Scene
from src.services.local_asset_library import (
    LocalAssetLibrary,
)


class LocalAssetSearchService:
    """Searches the local asset library for scene-matching videos."""

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

    def __init__(
        self,
        asset_source: AssetIndex | LocalAssetLibrary,
    ) -> None:
        """
        Accept either the new LocalAssetLibrary or a legacy AssetIndex.

        Supporting AssetIndex preserves older tests and call sites.
        """

        self.asset_source = asset_source

    def search_for_scene(
        self,
        scene: Scene,
        *,
        maximum_results: int = 5,
    ) -> list[AssetCandidate]:
        """Return ranked local video candidates for one scene."""

        if maximum_results < 1:
            raise ValueError("Maximum local results must be at least 1.")

        search_terms = self._build_search_terms(scene)

        scored_assets: list[tuple[float, IndexedAsset]] = []

        for asset in self._video_assets():
            score = self._calculate_score(
                asset=asset,
                search_terms=search_terms,
            )

            if score >= self.MINIMUM_MATCH_SCORE:
                scored_assets.append(
                    (
                        score,
                        asset,
                    )
                )

        scored_assets.sort(
            key=lambda item: (
                item[0],
                item[1].title.lower(),
            ),
            reverse=True,
        )

        return [
            self._to_candidate(
                asset,
                score,
            )
            for score, asset in scored_assets[:maximum_results]
        ]

    def _video_assets(
        self,
    ) -> list[IndexedAsset]:
        """Return indexed local video assets."""

        if isinstance(
            self.asset_source,
            LocalAssetLibrary,
        ):
            return self.asset_source.search(
                asset_type=IndexedAssetType.VIDEO,
            )

        return self.asset_source.search(
            asset_type=IndexedAssetType.VIDEO,
        )

    @classmethod
    def _build_search_terms(
        cls,
        scene: Scene,
    ) -> set[str]:
        """Build useful search terms from scene content."""

        combined_text = " ".join(
            [
                scene.title,
                scene.visual_prompt,
                scene.narration,
                scene.stock_query or "",
            ]
        )

        normalized_text = (
            combined_text.lower()
            .replace(",", " ")
            .replace(".", " ")
            .replace("-", " ")
            .replace("_", " ")
        )

        return {
            word.strip()
            for word in normalized_text.split()
            if len(word.strip()) >= 3 and word.strip() not in cls.STOP_WORDS
        }

    @staticmethod
    def _calculate_score(
        asset: IndexedAsset,
        search_terms: set[str],
    ) -> float:
        """Calculate basic scene-to-asset relevance."""

        if not search_terms:
            return 0.0

        searchable_values = [
            asset.title,
            *asset.tags,
            *asset.keywords,
        ]

        searchable_text = " ".join(value.lower() for value in searchable_values)

        matched_terms = {term for term in search_terms if term in searchable_text}

        if not matched_terms:
            return 0.0

        base_score = len(matched_terms) / len(search_terms)

        title_matches = sum(1 for term in matched_terms if term in asset.title.lower())

        title_bonus = min(
            title_matches * 0.03,
            0.12,
        )

        resolution_bonus = 0.05 if asset.resolution else 0.0

        reuse_bonus = min(
            asset.usage_count * 0.01,
            0.05,
        )

        return round(
            min(
                base_score + title_bonus + resolution_bonus + reuse_bonus,
                1.0,
            ),
            4,
        )

    @staticmethod
    def _to_candidate(
        asset: IndexedAsset,
        score: float,
    ) -> AssetCandidate:
        """Convert an indexed asset into a UI candidate."""

        metadata = {
            "asset_id": str(asset.id),
        }

        if asset.content_hash is not None:
            metadata["content_hash"] = asset.content_hash

        return AssetCandidate(
            title=asset.title,
            source_type=(SceneSourceType.LOCAL_LIBRARY),
            file_path=asset.file_path,
            provider=(asset.provider or "Local Library"),
            license_type=(asset.license_type or "owned"),
            duration_seconds=(asset.duration_seconds),
            resolution=asset.resolution,
            aspect_ratio=asset.aspect_ratio,
            last_used_at=asset.last_used_at,
            usage_count=asset.usage_count,
            score=score,
            tags=list(asset.tags),
            metadata=metadata,
        )
