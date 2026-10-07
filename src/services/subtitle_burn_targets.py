"""Which finished videos subtitles can be burned onto, for the Packaging tab's card.

The three renders the operator ends up with: the main render, the render with the opening
title card added, and each export variant (CTA / watermark / reformat). A video that
already has the subtitles in its picture is not offered.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.models.export_variant import ExportVariantCollection
from src.models.render_result import RenderResult
from src.models.video_job import VideoJob


@dataclass(frozen=True)
class SubtitleBurnTarget:
    label: str
    file: str
    # True when the video starts with whatever the effective render starts with (a title
    # card), so the subtitles are shifted past it. The main render has none.
    after_title_card: bool


def subtitle_burn_targets(
    job: VideoJob,
    effective_render: RenderResult | None,
    variants: ExportVariantCollection | None,
) -> list[SubtitleBurnTarget]:
    base = job.render_result

    if base is None or not base.success or not base.output_file:
        return []

    if base.subtitles_burned:
        # Everything made from this render has them too.
        return []

    targets: list[SubtitleBurnTarget] = []
    seen: set[str] = set()

    def add(label: str, file: str | None, *, after_title_card: bool) -> None:
        if not file or file in seen or not Path(file).is_file():
            return

        seen.add(file)
        targets.append(SubtitleBurnTarget(label, file, after_title_card))

    add("Main render", base.output_file, after_title_card=False)

    if (
        effective_render is not None
        and effective_render.success
        and effective_render.output_file
        and Path(effective_render.output_file).resolve()
        != Path(base.output_file).resolve()
    ):
        add(
            "Render with the opening title card",
            effective_render.output_file,
            after_title_card=True,
        )

    for variant in variants.variants if variants is not None else []:
        platform = variant.platform.value if variant.platform is not None else None
        shape = variant.orientation.value
        label = f"Export variant {shape}" + (f" - {platform}" if platform else "")
        add(label, variant.output_file, after_title_card=True)

    return targets
