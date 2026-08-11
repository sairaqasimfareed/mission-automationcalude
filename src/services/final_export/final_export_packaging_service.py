from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import UUID

from src.models.final_export import FinalExportPackage
from src.models.seo import SEOPackage
from src.models.thumbnail import ThumbnailArtifact


class FinalExportPackagingService:
    """
    Build the on-disk export directory and produce one FinalExportPackage.

    Directory strategy:

        exports/<project_id>/
            video/final_video<ext>
            thumbnail/thumbnail<ext>
            metadata/seo.json
            metadata/project.json
            metadata/export_manifest.json

    A source path that is a URI-scheme placeholder (for example a
    dry-run provider's output) or that does not exist on disk is
    referenced directly rather than copied, with a warning recorded on
    the resulting package - this keeps the full SEO -> thumbnail ->
    export pipeline composable end to end in dry-run mode.
    """

    def __init__(self, *, export_root: str | Path) -> None:
        self.export_root = Path(export_root).expanduser().resolve()

    def package(
        self,
        *,
        video_job_id: UUID,
        project_id: str,
        final_video_source_path: str,
        resolution: str,
        frame_rate: int,
        duration_seconds: int,
        seo_package: SEOPackage,
        thumbnail_artifact: ThumbnailArtifact,
    ) -> FinalExportPackage:
        """Build the export directory and return the resulting package."""

        normalized_project_id = self._sanitize_identifier(project_id)

        project_directory = self.export_root / normalized_project_id

        video_directory = project_directory / "video"
        thumbnail_directory = project_directory / "thumbnail"
        metadata_directory = project_directory / "metadata"

        for directory in (
            video_directory,
            thumbnail_directory,
            metadata_directory,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        warnings: list[str] = []

        video_extension = self._extension_of(final_video_source_path, ".mp4")

        final_video_path = self._register_file(
            final_video_source_path,
            video_directory / f"final_video{video_extension}",
            warnings=warnings,
        )

        thumbnail_extension = self._extension_of(
            thumbnail_artifact.file_path,
            ".png",
        )

        thumbnail_path = self._register_file(
            thumbnail_artifact.file_path,
            thumbnail_directory / f"thumbnail{thumbnail_extension}",
            warnings=warnings,
        )

        registered_thumbnail_artifact = thumbnail_artifact.model_copy(
            update={"file_path": thumbnail_path},
        )

        self._write_json(
            metadata_directory / "seo.json",
            json.loads(seo_package.model_dump_json()),
        )

        self._write_json(
            metadata_directory / "project.json",
            {
                "video_job_id": str(video_job_id),
                "project_id": normalized_project_id,
                "resolution": resolution,
                "frame_rate": frame_rate,
                "duration_seconds": duration_seconds,
            },
        )

        package = FinalExportPackage(
            video_job_id=video_job_id,
            project_id=normalized_project_id,
            final_video_path=final_video_path,
            resolution=resolution,
            frame_rate=frame_rate,
            duration_seconds=duration_seconds,
            seo_package=seo_package,
            thumbnail_artifact=registered_thumbnail_artifact,
            export_directory=str(project_directory),
            warnings=warnings,
        )

        manifest_path = metadata_directory / "export_manifest.json"

        self._write_json(
            manifest_path,
            json.loads(package.model_dump_json()),
        )

        return package.model_copy(update={"manifest_path": str(manifest_path)})

    @staticmethod
    def _register_file(
        source_path: str,
        destination: Path,
        *,
        warnings: list[str],
    ) -> str:
        if "://" in source_path:
            warnings.append(
                f"Source '{source_path}' is a placeholder path and was "
                "referenced without copying a real file."
            )

            return source_path

        source_file = Path(source_path).expanduser().resolve()

        if not source_file.exists():
            warnings.append(
                f"Source file does not exist and was referenced without "
                f"copying: {source_file}"
            )

            return str(source_file)

        shutil.copy2(str(source_file), str(destination))

        return str(destination)

    @staticmethod
    def _extension_of(path: str, default: str) -> str:
        if "://" in path:
            return default

        suffix = Path(path).suffix.lower()

        return suffix or default

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _sanitize_identifier(value: str) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError("Project ID cannot be empty.")

        safe_value = "".join(
            character if (character.isalnum() or character in {"-", "_"}) else "_"
            for character in normalized
        )

        return safe_value.strip("_") or "project"
