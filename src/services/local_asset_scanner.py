from __future__ import annotations

import hashlib
from pathlib import Path

from src.models.asset_index import (
    AssetIndex,
    IndexedAsset,
    IndexedAssetSource,
    IndexedAssetType,
)


class LocalAssetScanner:
    """Scans local asset folders and builds an AssetIndex."""

    VIDEO_EXTENSIONS = {
        ".mp4",
        ".mov",
        ".mkv",
        ".avi",
        ".webm",
    }

    IMAGE_EXTENSIONS = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
    }

    MUSIC_EXTENSIONS = {
        ".mp3",
        ".wav",
        ".m4a",
        ".aac",
        ".flac",
    }

    SOUND_EFFECT_EXTENSIONS = {
        ".ogg",
    }

    def scan(
        self,
        root_folder: str | Path = "assets",
    ) -> AssetIndex:
        root_path = Path(root_folder)

        index = AssetIndex()

        if not root_path.exists():
            return index

        for file_path in root_path.rglob("*"):
            if not file_path.is_file():
                continue

            asset_type = self._detect_asset_type(file_path)

            if asset_type is None:
                continue

            relative_path = file_path.as_posix()

            index.add(
                IndexedAsset(
                    asset_type=asset_type,
                    source=IndexedAssetSource.LOCAL_LIBRARY,
                    file_path=relative_path,
                    title=file_path.stem.replace("_", " "),
                    provider="Local Library",
                    license_type="owned",
                    file_size_bytes=file_path.stat().st_size,
                    content_hash=self._calculate_hash(file_path),
                    tags=self._build_tags(file_path),
                    keywords=self._build_keywords(file_path),
                    metadata={
                        "extension": file_path.suffix.lower(),
                        "parent_folder": file_path.parent.name,
                    },
                )
            )

        return index

    def _detect_asset_type(
        self,
        file_path: Path,
    ) -> IndexedAssetType | None:
        extension = file_path.suffix.lower()

        if extension in self.VIDEO_EXTENSIONS:
            return IndexedAssetType.VIDEO

        if extension in self.IMAGE_EXTENSIONS:
            return IndexedAssetType.IMAGE

        if extension in self.SOUND_EFFECT_EXTENSIONS:
            return IndexedAssetType.SOUND_EFFECT

        if extension in self.MUSIC_EXTENSIONS:
            if "sfx" in {
                part.lower()
                for part in file_path.parts
            }:
                return IndexedAssetType.SOUND_EFFECT

            return IndexedAssetType.MUSIC

        return None

    @staticmethod
    def _calculate_hash(
        file_path: Path,
    ) -> str:
        hasher = hashlib.sha256()

        with file_path.open("rb") as file:
            while chunk := file.read(8192):
                hasher.update(chunk)

        return hasher.hexdigest()

    @staticmethod
    def _build_tags(
        file_path: Path,
    ) -> list[str]:
        tags = {
            file_path.stem.lower().replace("_", " "),
            file_path.parent.name.lower(),
        }

        return sorted(tags)

    @staticmethod
    def _build_keywords(
        file_path: Path,
    ) -> list[str]:
        words = (
            file_path.stem
            .lower()
            .replace("-", " ")
            .replace("_", " ")
            .split()
        )

        return sorted(set(words))