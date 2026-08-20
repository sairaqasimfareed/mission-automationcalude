from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.models.asset_index import (
    AssetIndex,
    IndexedAsset,
    IndexedAssetSource,
    IndexedAssetType,
)


@dataclass(slots=True, frozen=True)
class AssetLibraryStatistics:
    """Summary information for the local asset library."""

    registered_directories: int
    indexed_assets: int

    videos: int
    images: int
    music: int
    sound_effects: int

    total_file_size_bytes: int


class LocalAssetLibrary:
    """Scans local folders and maintains a searchable asset index."""

    VIDEO_EXTENSIONS = {
        ".mp4",
        ".mov",
        ".mkv",
        ".webm",
        ".avi",
        ".m4v",
    }

    IMAGE_EXTENSIONS = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".bmp",
        ".gif",
    }

    MUSIC_EXTENSIONS = {
        ".mp3",
        ".wav",
        ".flac",
        ".aac",
        ".m4a",
        ".ogg",
    }

    SOUND_EFFECT_EXTENSIONS = {
        ".sfx.mp3",
        ".sfx.wav",
    }

    SOUND_EFFECT_FOLDER_NAMES = {
        "sfx",
        "sound_effect",
        "sound_effects",
        "sound-effects",
        "soundeffects",
    }

    def __init__(
        self,
        directories: list[str | Path] | None = None,
    ) -> None:
        self._directories: list[Path] = []
        self._index = AssetIndex()

        for directory in directories or []:
            self.register_directory(directory)

    @property
    def index(self) -> AssetIndex:
        """Return the current in-memory asset index."""

        return self._index

    @property
    def registered_directories(self) -> list[Path]:
        """Return a copy of registered asset directories."""

        return list(self._directories)

    def register_directory(
        self,
        directory: str | Path,
    ) -> Path:
        """Register one directory for recursive asset scanning."""

        normalized_directory = Path(directory).expanduser().resolve()

        if not normalized_directory.exists():
            raise FileNotFoundError(
                "Local asset directory does not exist: " f"{normalized_directory}"
            )

        if not normalized_directory.is_dir():
            raise NotADirectoryError(
                "Local asset path is not a directory: " f"{normalized_directory}"
            )

        if normalized_directory not in self._directories:
            self._directories.append(normalized_directory)

        return normalized_directory

    def unregister_directory(
        self,
        directory: str | Path,
    ) -> bool:
        """Remove one registered directory."""

        normalized_directory = Path(directory).expanduser().resolve()

        if normalized_directory not in self._directories:
            return False

        self._directories.remove(normalized_directory)

        return True

    def clear_directories(self) -> None:
        """Remove all registered directories."""

        self._directories.clear()

    def refresh(self) -> AssetIndex:
        """Rebuild the complete local asset index."""

        rebuilt_index = AssetIndex()
        seen_paths: set[str] = set()

        for directory in self._directories:
            for file_path in self._iter_supported_files(directory):
                normalized_path = str(file_path.resolve())

                if normalized_path in seen_paths:
                    continue

                seen_paths.add(normalized_path)

                asset = self._build_indexed_asset(file_path)

                if asset is not None:
                    rebuilt_index.add(asset)

        self._index = rebuilt_index

        return self._index

    def search(
        self,
        *,
        query: str | None = None,
        asset_type: IndexedAssetType | None = None,
        limit: int | None = None,
    ) -> list[IndexedAsset]:
        """Search indexed local assets."""

        if limit is not None and limit < 1:
            raise ValueError("Local asset search limit must be at least 1.")

        normalized_query = query.strip() if query is not None else None

        results = self._index.search(
            asset_type=asset_type,
            query=normalized_query or None,
        )

        ranked_results = self._rank_results(
            results=results,
            query=normalized_query,
        )

        if limit is not None:
            return ranked_results[:limit]

        return ranked_results

    def find_by_path(
        self,
        file_path: str | Path,
    ) -> IndexedAsset | None:
        """Return one indexed asset by absolute file path."""

        normalized_path = str(Path(file_path).expanduser().resolve())

        for asset in self._index.assets:
            if asset.file_path == normalized_path:
                return asset

        return None

    def statistics(self) -> AssetLibraryStatistics:
        """Return current library statistics."""

        video_count = 0
        image_count = 0
        music_count = 0
        sound_effect_count = 0
        total_file_size_bytes = 0

        for asset in self._index.assets:
            total_file_size_bytes += asset.file_size_bytes

            if asset.asset_type == IndexedAssetType.VIDEO:
                video_count += 1

            elif asset.asset_type == IndexedAssetType.IMAGE:
                image_count += 1

            elif asset.asset_type == IndexedAssetType.MUSIC:
                music_count += 1

            elif asset.asset_type == IndexedAssetType.SOUND_EFFECT:
                sound_effect_count += 1

        return AssetLibraryStatistics(
            registered_directories=(len(self._directories)),
            indexed_assets=(len(self._index.assets)),
            videos=video_count,
            images=image_count,
            music=music_count,
            sound_effects=sound_effect_count,
            total_file_size_bytes=(total_file_size_bytes),
        )

    def _iter_supported_files(
        self,
        directory: Path,
    ) -> list[Path]:
        """Return supported files recursively."""

        files: list[Path] = []

        for path in directory.rglob("*"):
            if not path.is_file():
                continue

            if self._detect_asset_type(path) is not None:
                files.append(path)

        return sorted(
            files,
            key=lambda path: str(path).lower(),
        )

    def _build_indexed_asset(
        self,
        file_path: Path,
    ) -> IndexedAsset | None:
        """Build one IndexedAsset from a local file."""

        asset_type = self._detect_asset_type(file_path)

        if asset_type is None:
            return None

        stat = file_path.stat()

        title = self._build_title(file_path)

        tags = self._build_tags(file_path)

        keywords = list(tags)

        return IndexedAsset(
            asset_type=asset_type,
            source=(IndexedAssetSource.LOCAL_LIBRARY),
            file_path=str(file_path.resolve()),
            title=title,
            file_size_bytes=stat.st_size,
            tags=tags,
            keywords=keywords,
            metadata={
                "extension": (file_path.suffix.lower()),
                "parent_directory": (file_path.parent.name),
                "modified_timestamp": str(int(stat.st_mtime)),
            },
        )

    @classmethod
    def _detect_asset_type(
        cls,
        file_path: Path,
    ) -> IndexedAssetType | None:
        """Map a local file to an indexed asset type."""

        lower_name = file_path.name.lower()
        extension = file_path.suffix.lower()

        if extension in cls.VIDEO_EXTENSIONS:
            return IndexedAssetType.VIDEO

        if extension in cls.IMAGE_EXTENSIONS:
            return IndexedAssetType.IMAGE

        if extension in cls.MUSIC_EXTENSIONS:
            parent_parts = {part.lower() for part in file_path.parent.parts}

            is_named_sound_effect = any(
                lower_name.endswith(suffix) for suffix in (cls.SOUND_EFFECT_EXTENSIONS)
            )

            is_in_sound_effect_folder = bool(
                parent_parts & cls.SOUND_EFFECT_FOLDER_NAMES
            )

            if is_named_sound_effect or is_in_sound_effect_folder:
                return IndexedAssetType.SOUND_EFFECT

            return IndexedAssetType.MUSIC

        return None

    @staticmethod
    def _build_title(
        file_path: Path,
    ) -> str:
        """Create a readable title from a filename."""

        return file_path.stem.replace("_", " ").replace("-", " ").strip()

    @staticmethod
    def _build_tags(
        file_path: Path,
    ) -> list[str]:
        """Build searchable tags from name and folders."""

        raw_values = [
            file_path.stem,
            *[part for part in (file_path.parent.parts[-3:])],
        ]

        tags: list[str] = []

        for raw_value in raw_values:
            normalized_value = raw_value.replace("_", " ").replace("-", " ").lower()

            for token in normalized_value.split():
                cleaned_token = token.strip()

                if cleaned_token and cleaned_token not in tags:
                    tags.append(cleaned_token)

        return tags

    @staticmethod
    def _rank_results(
        *,
        results: list[IndexedAsset],
        query: str | None,
    ) -> list[IndexedAsset]:
        """Rank basic local search results by relevance."""

        if not query:
            return sorted(
                results,
                key=lambda asset: (
                    asset.title.lower(),
                    asset.file_path.lower(),
                ),
            )

        query_tokens = {token for token in query.lower().split() if token}

        def score(
            asset: IndexedAsset,
        ) -> tuple[int, int, str]:
            searchable_values = {
                asset.title.lower(),
                *[tag.lower() for tag in asset.tags],
                *[keyword.lower() for keyword in (asset.keywords)],
            }

            searchable_text = " ".join(searchable_values)

            token_matches = sum(1 for token in query_tokens if token in searchable_text)

            exact_title_match = int(query.lower() in asset.title.lower())

            return (
                exact_title_match,
                token_matches,
                asset.title.lower(),
            )

        return sorted(
            results,
            key=score,
            reverse=True,
        )
