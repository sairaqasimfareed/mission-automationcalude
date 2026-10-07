"""
Shot-to-shot colour matching (2026-10-07): generated clips come back with their own
exposure and colour (live: Remedy's bright daylight clip between dark, warm kitchen
ones). Each live-action clip gets a mild, bounded correction toward the video's typical
look, kept on the clip and applied at render when the project has it on.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from src.models.color_correction import (  # noqa: E402
    MAX_BRIGHTNESS_SHIFT,
    ColorCorrection,
)
from src.models.media_strategy import SceneSourceType  # noqa: E402
from src.models.scene import Scene  # noqa: E402
from src.models.video_clip import VideoClip  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from src.services.clip_color_matching_service import (  # noqa: E402
    ClipColorMatchingService,
    ClipColorStats,
    describe,
)
from src.services.reference_frame_selection_service import SampledFrame  # noqa: E402

# (blue, green, red) of a flat frame
_DARK_WARM = (25, 45, 70)
_BRIGHT_COOL = (200, 170, 150)


def _frame(colour: tuple[int, int, int]) -> SampledFrame:
    image = np.zeros((90, 160, 3), dtype=np.uint8)
    image[:, :] = colour

    return SampledFrame(index=0, time_seconds=0.0, image=image)


def _job(tmp_path: Path, colours: list[tuple[int, int, int]]) -> VideoJob:
    job = VideoJob(project_name="Remedy", channel_name="C", niche="n", topic="Honey")

    for number, _colour in enumerate(colours, start=1):
        path = tmp_path / f"clip_{number}.mp4"
        path.write_bytes(b"x")
        job.video_clips.append(
            VideoClip(
                scene_number=number,
                source_type=SceneSourceType.AI_GENERATE,
                duration_seconds=8,
                local_file=str(path),
            )
        )
        job.scenes.append(
            Scene(
                scene_number=number,
                title=f"Scene {number}",
                narration=f"Narration {number}.",
                visual_prompt=f"Visual {number}.",
                estimated_duration_seconds=8,
            )
        )

    return job


def _service(colours: list[tuple[int, int, int]]) -> ClipColorMatchingService:
    def sampler(path: str, count: int) -> list[SampledFrame]:
        number = int(Path(path).stem.split("_")[-1])

        return [_frame(colours[number - 1])] * count

    return ClipColorMatchingService(frame_sampler=sampler)


# ------------------------------------------------------------------ the model


def test_a_correction_cannot_exceed_its_limits() -> None:
    with pytest.raises(ValidationError):
        ColorCorrection(brightness=MAX_BRIGHTNESS_SHIFT + 0.05)

    with pytest.raises(ValidationError):
        ColorCorrection(saturation=2.0)

    with pytest.raises(ValidationError):
        ColorCorrection(red_gain=1.5)


def test_a_correction_that_changes_nothing_is_the_identity() -> None:
    assert ColorCorrection().is_identity is True
    assert ColorCorrection(brightness=0.002, saturation=1.005).is_identity is True
    assert ColorCorrection(brightness=-0.05).is_identity is False


def test_a_project_saved_before_corrections_existed_still_loads() -> None:
    clip = VideoClip(
        scene_number=1, source_type=SceneSourceType.AI_GENERATE, duration_seconds=8
    )
    data = clip.model_dump(mode="json")
    data.pop("color_correction")

    assert VideoClip.model_validate(data).color_correction is None
    assert (
        VideoJob(
            project_name="x", channel_name="c", niche="n", topic="t"
        ).color_matching_enabled
        is False
    )


# ----------------------------------------------------------------- the maths


def test_a_brighter_clip_is_darkened_toward_the_typical_look() -> None:
    target = ClipColorStats(brightness=70.0, saturation=150.0, warmth=40.0)
    bright = ClipColorStats(brightness=200.0, saturation=150.0, warmth=40.0)

    correction = ClipColorMatchingService.correction_for(bright, target)

    assert correction.brightness < 0
    assert correction.brightness == pytest.approx(-MAX_BRIGHTNESS_SHIFT)  # clamped


def test_a_clip_close_to_the_typical_look_is_left_alone() -> None:
    target = ClipColorStats(brightness=100.0, saturation=120.0, warmth=20.0)
    close = ClipColorStats(brightness=101.0, saturation=121.0, warmth=21.0)

    assert ClipColorMatchingService.correction_for(close, target).is_identity


def test_a_cooler_clip_is_warmed_and_a_warmer_one_cooled() -> None:
    target = ClipColorStats(brightness=100.0, saturation=120.0, warmth=40.0)
    cool = ClipColorStats(brightness=100.0, saturation=120.0, warmth=-40.0)
    warm = ClipColorStats(brightness=100.0, saturation=120.0, warmth=120.0)

    warmed = ClipColorMatchingService.correction_for(cool, target)
    cooled = ClipColorMatchingService.correction_for(warm, target)

    assert warmed.red_gain > 1.0 > warmed.blue_gain
    assert cooled.red_gain < 1.0 < cooled.blue_gain


def test_a_nearly_grey_clip_is_not_resaturated_wildly() -> None:
    target = ClipColorStats(brightness=100.0, saturation=150.0, warmth=0.0)
    grey = ClipColorStats(brightness=100.0, saturation=3.0, warmth=0.0)

    assert ClipColorMatchingService.correction_for(grey, target).saturation == 1.0


def test_the_correction_is_described_in_plain_words() -> None:
    text = describe(
        ColorCorrection(brightness=-0.09, saturation=0.9, red_gain=1.04, blue_gain=0.96)
    )

    assert text == "9% darker, a little less colourful, slightly warmer"


# ------------------------------------------------------------------- matching


def test_the_odd_bright_clip_out_is_brought_toward_the_others(tmp_path: Path) -> None:
    colours = [_DARK_WARM, _DARK_WARM, _DARK_WARM, _DARK_WARM, _BRIGHT_COOL]
    job = _job(tmp_path, colours)

    report = _service(colours).match(job)

    odd = next(c for c in job.video_clips if c.scene_number == 5)
    others = [c for c in job.video_clips if c.scene_number != 5]

    assert odd.color_correction is not None
    assert odd.color_correction.brightness < 0  # darkened
    assert odd.color_correction.red_gain > 1.0  # warmed
    assert all(c.color_correction is None for c in others)  # already typical
    assert report.measured == 5
    assert report.corrected_count == 1
    assert "Scene 5" in report.text()


def test_matching_again_replaces_the_earlier_corrections(tmp_path: Path) -> None:
    colours = [_DARK_WARM] * 4 + [_BRIGHT_COOL]
    job = _job(tmp_path, colours)
    service = _service(colours)
    service.match(job)
    job.video_clips[0].color_correction = ColorCorrection(brightness=0.1)  # stale

    service.match(job)

    assert job.video_clips[0].color_correction is None


def test_too_few_clips_to_say_what_typical_is(tmp_path: Path) -> None:
    colours = [_DARK_WARM, _BRIGHT_COOL]
    job = _job(tmp_path, colours)
    job.video_clips[0].color_correction = ColorCorrection(brightness=0.1)

    report = _service(colours).match(job)

    assert "needs at least 3" in report.text()
    assert all(c.color_correction is None for c in job.video_clips)  # cleared


def test_graphic_scenes_are_left_alone(tmp_path: Path) -> None:
    from src.models.visual_continuity import (
        ClipContinuityEntry,
        VisualContinuityBible,
        VisualState,
    )

    colours = [_DARK_WARM] * 4 + [_BRIGHT_COOL]
    job = _job(tmp_path, colours)
    job.visual_continuity_bible = VisualContinuityBible(
        script_lock_hash="a" * 64,
        clip_entries=[
            ClipContinuityEntry(
                scene_number=5,
                incoming_state=VisualState(),
                shot_action="An infographic overlay.",
                outgoing_state=VisualState(location="informational graphic/overlay"),
            )
        ],
    )

    report = _service(colours).match(job)

    assert report.skipped_graphic == 1
    assert (
        next(c for c in job.video_clips if c.scene_number == 5).color_correction is None
    )


def test_stock_and_manual_clips_are_not_measured(tmp_path: Path) -> None:
    colours = [_DARK_WARM] * 4 + [_BRIGHT_COOL]
    job = _job(tmp_path, colours)
    job.video_clips[4].source_type = SceneSourceType.MANUAL_UPLOAD

    report = _service(colours).match(job)

    assert report.measured == 4
    assert job.video_clips[4].color_correction is None


def test_corrections_measured_on_a_copy_come_back_to_the_real_job(
    tmp_path: Path,
) -> None:
    colours = [_DARK_WARM] * 4 + [_BRIGHT_COOL]
    job = _job(tmp_path, colours)
    copy = job.model_copy(deep=True)
    _service(colours).match(copy)

    ClipColorMatchingService.apply_to(job, copy)

    assert job.video_clips[4].color_correction is not None
    assert (
        job.video_clips[4].color_correction.brightness  # type: ignore[union-attr]
        == copy.video_clips[4].color_correction.brightness  # type: ignore[union-attr]
    )


# ------------------------------------------------------------------ the render


def _video_node(correction: dict[str, float] | None):  # type: ignore[no-untyped-def]
    from src.models.render_graph import RenderNode, RenderNodeStatus, RenderNodeType

    return RenderNode(
        node_type=RenderNodeType.VIDEO_CLIP,
        status=RenderNodeStatus.READY,
        scene_number=1,
        track_index=0,
        layer_index=0,
        start_time_seconds=0.0,
        end_time_seconds=8.0,
        duration_seconds=8.0,
        payload={"local_file": "scene_001.mp4", "color_correction": correction},
    )


def _filter_complex(correction: dict[str, float] | None) -> str:
    from src.models.ffmpeg_config import (
        FFmpegCapabilities,
        FFmpegConfig,
        FFmpegResolvedConfig,
    )
    from src.models.render_graph import (
        RenderGraph,
        RenderGraphStatus,
        RenderNode,
        RenderNodeStatus,
        RenderNodeType,
    )
    from src.services.filter_graph_builder_service import FilterGraphBuilderService

    def node(kind: RenderNodeType, **extra: object) -> RenderNode:
        return RenderNode(
            node_type=kind,
            status=RenderNodeStatus.READY,
            start_time_seconds=0.0,
            end_time_seconds=8.0,
            duration_seconds=8.0,
            **extra,  # type: ignore[arg-type]
        )

    nodes = [
        _video_node(correction),
        node(
            RenderNodeType.VIDEO_COMPOSITION,
            payload={"output_resolution": "1920x1080", "frame_rate": 30},
        ),
        node(RenderNodeType.AUDIO_MIX),
        node(RenderNodeType.OUTPUT),
    ]
    graph = RenderGraph(
        status=RenderGraphStatus.READY,
        nodes=nodes,
        edges=[],
        timeline_duration_seconds=8.0,
        scene_count=1,
        node_count=len(nodes),
        edge_count=0,
        ready_node_count=len(nodes),
        executed_node_count=0,
        failed_node_count=0,
        is_valid=True,
        is_render_ready=True,
        output_node_id=str(nodes[-1].id),
    )
    resolved = FFmpegResolvedConfig(
        config=FFmpegConfig(),
        capabilities=FFmpegCapabilities(
            ffmpeg_available=True,
            ffprobe_available=True,
            ffmpeg_path="ffmpeg",
            ffprobe_path="ffprobe",
            ffmpeg_version="9.0",
            ffprobe_version="9.0",
            encoders={"libx264", "aac"},
            filters={
                "scale",
                "fps",
                "format",
                "setpts",
                "concat",
                "null",
                "eq",
                "colorchannelmixer",
                "asetpts",
                "volume",
                "adelay",
                "anull",
                "amix",
            },
        ),
        selected_video_codec="libx264",
        selected_audio_codec="aac",
    )

    return (
        FilterGraphBuilderService()
        .build(render_graph=graph, resolved_config=resolved)
        .render_filter_complex()
    )


def test_a_corrected_clip_gets_the_correction_in_its_filter_chain() -> None:
    text = _filter_complex(
        {"brightness": -0.09, "saturation": 0.9, "red_gain": 1.04, "blue_gain": 0.96}
    )

    assert "eq=brightness=-0.09:saturation=0.9" in text
    assert "colorchannelmixer=rr=1.04:bb=0.96" in text
    assert text.index("setpts=PTS-STARTPTS") < text.index("eq=brightness")


def test_an_uncorrected_clip_gets_no_correction_filters() -> None:
    text = _filter_complex(None)

    assert "colorchannelmixer" not in text
    assert "color_matched" not in text


def test_the_render_stage_uses_the_jobs_corrections_only_when_matching_is_on(
    tmp_path: Path,
) -> None:
    from src.pipeline.render_stage import RenderPipelineStage
    from tests.test_render_stage import _staged_job_with_real_cues

    job = _staged_job_with_real_cues()
    job.video_clips[0].color_correction = ColorCorrection(brightness=-0.08)
    timeline = job.video_timeline
    assert timeline is not None

    off = RenderPipelineStage._with_color_corrections(job, timeline)  # noqa: SLF001

    assert off is timeline  # off: the very same timeline, untouched

    job.color_matching_enabled = True
    on = RenderPipelineStage._with_color_corrections(job, timeline)  # noqa: SLF001

    assert on is not timeline
    assert on.items[0].clip.color_correction is not None
    assert on.items[0].clip.color_correction.brightness == -0.08
    # a copy was made: the job's own timeline objects are not the ones changed
    assert on.items[0].clip is not timeline.items[0].clip


def test_the_render_stage_leaves_the_timeline_alone_without_any_corrections() -> None:
    from src.pipeline.render_stage import RenderPipelineStage
    from tests.test_render_stage import _staged_job_with_real_cues

    job = _staged_job_with_real_cues()
    job.color_matching_enabled = True
    timeline = job.video_timeline
    assert timeline is not None

    assert (
        RenderPipelineStage._with_color_corrections(job, timeline) is timeline
    )  # noqa: SLF001


def test_the_filters_are_valid_ffmpeg_and_really_darken_and_warm_the_picture() -> None:
    """The exact filter text the graph builds, run by a real FFmpeg on a flat grey
    frame: it must be accepted, darker, and warmer (more red than blue)."""

    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None:
        pytest.skip("needs ffmpeg")

    def mean_bgr(filter_text: str) -> tuple[float, float, float]:
        raw = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "color=c=0x808080:size=32x32:rate=1:duration=1",
                "-vf", f"{filter_text}format=bgr24", "-frames:v", "1",
                "-f", "rawvideo", "-",
            ],
            capture_output=True,
            check=True,
        ).stdout  # fmt: skip
        pixels = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)

        return tuple(float(v) for v in pixels.mean(axis=0))  # type: ignore[return-value]

    plain = mean_bgr("")
    corrected = mean_bgr(
        "eq=brightness=-0.09:saturation=0.9,colorchannelmixer=rr=1.04:bb=0.96,"
    )

    assert sum(corrected) < sum(plain)  # darker
    assert corrected[2] - corrected[0] > plain[2] - plain[0]  # redder than blue


# ------------------------------------------------------------------ the Clips tab


def test_the_clips_tab_offers_matching_and_saves_the_choice(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QCheckBox, QPushButton

    from src.models.video_provider import VideoProvider
    from tests.test_clip_workspace_clip_length_labels_gui import _view

    view, job = _view(VideoProvider.MUSE, narration=5.0)
    job.video_clips = [
        VideoClip(
            scene_number=1,
            source_type=SceneSourceType.AI_GENERATE,
            duration_seconds=5,
            local_file="C:/x/clip.mp4",
        )
    ]
    view.refresh(job)

    box = next(
        b
        for b in view.findChildren(QCheckBox)
        if b.text() == "Match colours between scenes when rendering"
    )
    assert box.isChecked() is False
    assert any(
        b.text() == "Measure clip colours" for b in view.findChildren(QPushButton)
    )

    box.setChecked(True)

    assert job.color_matching_enabled is True


from tests.test_clip_workspace_clip_length_labels_gui import (  # noqa: E402
    qapp as qapp,  # noqa: PLC0414 - fixture
)
