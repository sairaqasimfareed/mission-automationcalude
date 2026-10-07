"""
Subtitles on any render, at any stage (2026-10-07). The render keeps its subtitle lines;
this burns them onto a COPY of the main render, the render with its title card, or an
export variant - shifted past the title card when there is one - without re-rendering.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shutil  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402

from src.models.absolute_subtitle_cue import AbsoluteSubtitleCue  # noqa: E402
from src.models.enums import Platform  # noqa: E402
from src.models.export_variant import (
    ExportVariant,
    ExportVariantCollection,
)  # noqa: E402
from src.models.media_technical_validation import (  # noqa: E402
    MediaTechnicalValidationResult,
)
from src.models.render_result import RenderResult, RenderStatus  # noqa: E402
from src.models.specification_enums import AspectRatio  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from src.services.subtitle_burn_action_service import (  # noqa: E402
    SubtitleBurnActionService,
    _shifted_within,
)
from src.services.subtitle_burn_targets import subtitle_burn_targets  # noqa: E402
from src.services.title_card_offset import title_card_seconds  # noqa: E402


def _cues() -> list[AbsoluteSubtitleCue]:
    return [
        AbsoluteSubtitleCue(text="Honey can help.", start_seconds=0.5, end_seconds=2.0),
        AbsoluteSubtitleCue(
            text="Use two to five ml.", start_seconds=2.5, end_seconds=4.5
        ),
    ]


def _job(tmp_path: Path, *, cues: bool = True, burned: bool = False) -> VideoJob:
    main = tmp_path / "final_video.mp4"
    main.write_bytes(b"main")
    job = VideoJob(
        project_name="Remedy", channel_name="C", niche="health", topic="Honey"
    )
    job.render_result = RenderResult(
        success=True,
        output_file=str(main),
        render_engine="ffmpeg",
        duration_seconds=60,
        status=RenderStatus.COMPLETED,
        subtitle_cues=_cues() if cues else [],
        subtitles_burned=burned,
    )

    return job


class _Probe:
    """Reports a length per file name."""

    def __init__(self, lengths: dict[str, float], *, has_audio: bool = True) -> None:
        self._lengths = lengths
        self._has_audio = has_audio

    def validate(self, file_path: Path) -> MediaTechnicalValidationResult:
        seconds = self._lengths.get(file_path.name)

        if seconds is None:
            return MediaTechnicalValidationResult(is_readable=False, issues=["missing"])

        return MediaTechnicalValidationResult(
            is_readable=True,
            duration_seconds=seconds,
            has_audio_stream=self._has_audio,
        )


class _Burner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def burn(self, **kwargs: Any) -> RenderResult:
        self.calls.append(kwargs)

        return RenderResult(
            success=True,
            output_file=kwargs["output_file"],
            render_engine="ffmpeg",
            status=RenderStatus.COMPLETED,
        )


def _service(lengths: dict[str, float]) -> tuple[SubtitleBurnActionService, _Burner]:
    burner = _Burner()

    return (
        SubtitleBurnActionService(
            burn_service=burner,  # type: ignore[arg-type]
            media_validation_service=_Probe(lengths),  # type: ignore[arg-type]
        ),
        burner,
    )


# --------------------------------------------------------------- availability


def test_subtitles_need_a_render_with_stored_lines(tmp_path: Path) -> None:
    unavailable = SubtitleBurnActionService.unavailable_reason

    assert unavailable(_job(tmp_path)) is None
    assert "stored for this render" in (unavailable(_job(tmp_path, cues=False)) or "")
    assert "Render the video first" in (
        unavailable(VideoJob(project_name="x", channel_name="c", niche="n", topic="t"))
        or ""
    )


# ------------------------------------------------------------------ the shift


def test_the_lines_move_past_the_title_card_and_stay_inside_the_video() -> None:
    shifted = _shifted_within(_cues(), 3.0, 7.0)

    assert [(c.start_seconds, c.end_seconds) for c in shifted] == [
        (3.5, 5.0),
        (5.5, 7.0),
    ]


def test_a_line_that_starts_after_the_video_ends_is_dropped() -> None:
    shifted = _shifted_within(_cues(), 3.0, 5.0)

    assert [c.text for c in shifted] == ["Honey can help."]
    assert shifted[0].end_seconds == 5.0


# -------------------------------------------------------------------- burning


def test_burning_uses_the_stored_lines_and_writes_a_copy_next_to_the_original(
    tmp_path: Path,
) -> None:
    job = _job(tmp_path)
    source = job.render_result.output_file  # type: ignore[union-attr]
    service, burner = _service({"final_video.mp4": 60.0})

    result = service.burn(
        job=job, source_file=source, output_file=service.output_file_for(source)
    )

    assert result.success is True
    call = burner.calls[0]
    assert call["output_file"].endswith("final_video_subtitled.mp4")
    assert call["input_video_file"] == source
    assert call["video_duration_seconds"] == 60.0
    assert call["has_audio"] is True
    assert [c.text for c in call["cues"]] == ["Honey can help.", "Use two to five ml."]
    assert call["cues"][0].start_seconds == 0.5  # no title card, no shift


def test_a_video_with_a_title_card_gets_the_lines_after_the_card(
    tmp_path: Path,
) -> None:
    job = _job(tmp_path)
    with_card = tmp_path / "final_video_with_title_card.mp4"
    with_card.write_bytes(b"card")
    service, burner = _service(
        {"final_video.mp4": 60.0, "final_video_with_title_card.mp4": 63.0}
    )

    offset = service.offset_seconds(job, str(with_card))
    service.burn(
        job=job,
        source_file=str(with_card),
        output_file=service.output_file_for(str(with_card)),
        offset_seconds=offset,
    )

    assert offset == pytest.approx(3.0)
    assert burner.calls[0]["cues"][0].start_seconds == pytest.approx(3.5)


def test_the_main_render_has_no_title_card_offset(tmp_path: Path) -> None:
    job = _job(tmp_path)
    service, _burner = _service({"final_video.mp4": 60.0})

    assert service.offset_seconds(job, job.render_result.output_file) == 0.0  # type: ignore[union-attr]


def test_an_unreadable_video_is_refused_with_its_name(tmp_path: Path) -> None:
    job = _job(tmp_path)
    service, burner = _service({})

    with pytest.raises(ValueError, match="could not be read"):
        service.burn(job=job, source_file="C:/x/missing.mp4", output_file="C:/x/o.mp4")

    assert burner.calls == []


def test_a_job_without_stored_lines_is_refused(tmp_path: Path) -> None:
    job = _job(tmp_path, cues=False)
    service, _burner = _service({"final_video.mp4": 60.0})

    with pytest.raises(ValueError, match="No subtitle lines"):
        service.burn(
            job=job,
            source_file=job.render_result.output_file,  # type: ignore[union-attr]
            output_file="o.mp4",
        )


# ----------------------------------------------------------- title card length


def test_title_card_seconds_is_the_difference_to_the_card_free_render(
    tmp_path: Path,
) -> None:
    job = _job(tmp_path)
    probe = _Probe({"final_video.mp4": 60.0})
    other = tmp_path / "with_card.mp4"
    other.write_bytes(b"x")

    assert title_card_seconds(job, str(other), 63.0, probe) == pytest.approx(3.0)
    assert title_card_seconds(job, str(other), 60.2, probe) == 0.0  # too small
    assert title_card_seconds(job, str(other), 100.0, probe) == 0.0  # not a card


# --------------------------------------------------------------------- targets


def test_the_three_renders_are_offered_and_each_is_a_real_file(tmp_path: Path) -> None:
    job = _job(tmp_path)
    with_card = tmp_path / "with_card.mp4"
    with_card.write_bytes(b"x")
    variant_file = tmp_path / "variant.mp4"
    variant_file.write_bytes(b"x")
    effective = RenderResult(
        success=True,
        output_file=str(with_card),
        render_engine="ffmpeg",
        status=RenderStatus.COMPLETED,
    )
    variants = ExportVariantCollection(
        variants=[
            ExportVariant(
                orientation=AspectRatio.PORTRAIT,
                platform=Platform.TIKTOK,
                output_file=str(variant_file),
            ),
            ExportVariant(  # a file that no longer exists is not offered
                orientation=AspectRatio.LANDSCAPE,
                output_file=str(tmp_path / "gone.mp4"),
            ),
        ]
    )

    targets = subtitle_burn_targets(job, effective, variants)

    assert [t.label for t in targets] == [
        "Main render",
        "Render with the opening title card",
        "Export variant 9:16 - tiktok",
    ]
    assert [t.after_title_card for t in targets] == [False, True, True]


def test_nothing_is_offered_when_the_render_already_has_subtitles(
    tmp_path: Path,
) -> None:
    assert subtitle_burn_targets(_job(tmp_path, burned=True), None, None) == []


def test_a_title_card_render_that_is_the_main_render_is_not_listed_twice(
    tmp_path: Path,
) -> None:
    job = _job(tmp_path)

    targets = subtitle_burn_targets(job, job.render_result, None)

    assert [t.label for t in targets] == ["Main render"]


# ------------------------------------------------------ real FFmpeg, end to end


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="needs ffmpeg",
)
def test_subtitles_really_appear_after_the_title_card_in_a_real_video(
    tmp_path: Path,
) -> None:
    """A 5 s video whose first 2 s are a 'title card'; a cue stored for the card-free
    render at 0.5-1.5 s must show at 2.5-3.5 s in the video with the card, and not before.
    Checked on real pixels: the cue's text box makes the bottom of the frame darker."""

    from src.models.absolute_subtitle_cue import AbsoluteSubtitleCue
    from src.services.media_technical_validation_service import (
        MediaTechnicalValidationService,
    )

    base = tmp_path / "final_video.mp4"
    with_card = tmp_path / "final_video_with_title_card.mp4"

    def make(path: Path, seconds: int, colour: str) -> None:
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", f"color=c={colour}:size=640x360:rate=25:duration={seconds}",
                "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
            ],
            check=True,
        )  # fmt: skip

    make(base, 3, "gray")
    make(with_card, 5, "gray")

    job = VideoJob(project_name="x", channel_name="c", niche="n", topic="t")
    job.render_result = RenderResult(
        success=True,
        output_file=str(base),
        render_engine="ffmpeg",
        duration_seconds=3,
        status=RenderStatus.COMPLETED,
        subtitle_cues=[
            AbsoluteSubtitleCue(text="HELLO WORLD", start_seconds=0.5, end_seconds=1.5)
        ],
    )
    service = SubtitleBurnActionService(
        media_validation_service=MediaTechnicalValidationService()
    )
    offset = service.offset_seconds(job, str(with_card))
    result = service.burn(
        job=job,
        source_file=str(with_card),
        output_file=service.output_file_for(str(with_card)),
        offset_seconds=offset,
    )

    assert offset == pytest.approx(2.0, abs=0.15)
    assert result.success is True, result.error_message

    def duration(path: str) -> float:
        return float(
            subprocess.run(
                [
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nw=1:nk=1", path,
                ],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )  # fmt: skip

    # burning only adds the text: the copy runs exactly as long as the video it came from
    assert duration(result.output_file or "") == pytest.approx(
        duration(str(with_card)), abs=0.1
    )

    out = Path(result.output_file or "")

    def bright_pixels(at: float) -> int:
        raw = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-ss", f"{at}", "-i", str(out), "-frames:v", "1",
                "-vf", "crop=640:140:0:220,format=gray", "-f", "rawvideo", "-",
            ],
            capture_output=True,
            check=True,
        ).stdout  # fmt: skip

        return sum(1 for value in raw if value > 200 or value < 60)

    # the grey background is ~128; text and its box push pixels far from it
    assert bright_pixels(0.9) < 200  # inside the card's seconds: no subtitle yet
    assert bright_pixels(2.9) > 500  # 0.5-1.5 s of the render, shifted by the card


# ------------------------------------------------------------ the Packaging card


def _packaging_view(tmp_path: Path, action_service: Any):  # type: ignore[no-untyped-def]
    from src.desktop.job_store import InMemoryJobStore
    from src.desktop.views.packaging_view import PackagingView
    from src.services.final_export.final_export_service import FinalExportService

    return PackagingView(
        job_store=InMemoryJobStore(),
        seo_package_service=None,  # type: ignore[arg-type]
        thumbnail_package_service=None,  # type: ignore[arg-type]
        final_export_service=FinalExportService(export_root=tmp_path / "exports"),
        on_change=lambda: None,
        subtitle_burn_action_service=action_service,
    )


def _card_texts(view) -> list[str]:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QLabel, QPushButton

    return [w.text() for w in view.findChildren(QLabel)] + [
        b.text() for b in view.findChildren(QPushButton)
    ]


class _FakeActions:
    """Stands in for SubtitleBurnActionService: records what the card asked for."""

    unavailable_reason = staticmethod(SubtitleBurnActionService.unavailable_reason)
    output_file_for = staticmethod(SubtitleBurnActionService.output_file_for)

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail = fail

    def offset_seconds(self, job: VideoJob, file: str) -> float:
        return 0.0

    def burn(self, **kwargs: Any) -> RenderResult:
        self.calls.append(kwargs)

        if self._fail:
            raise ValueError("boom")

        return RenderResult(
            success=True,
            output_file=kwargs["output_file"],
            render_engine="ffmpeg",
            status=RenderStatus.COMPLETED,
        )


def _wait(view, qapp) -> None:  # type: ignore[no-untyped-def]
    import time

    deadline = time.monotonic() + 30

    while view._subtitle_threads or view._burning_subtitle_job_ids:  # noqa: SLF001
        assert time.monotonic() < deadline, "the burn never finished"
        qapp.processEvents()
        time.sleep(0.01)

    assert view.wait_for_pending_generations(timeout_ms=10_000)


def test_the_card_explains_when_there_is_nothing_to_burn(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view = _packaging_view(tmp_path, _FakeActions())
    job = VideoJob(project_name="x", channel_name="c", niche="n", topic="t")
    view._job_store.add(job)  # noqa: SLF001
    view.set_job(job.id)

    view.refresh(job)

    assert "Render the video first." in _card_texts(view)
    assert "Burn subtitles onto this video" not in _card_texts(view)


def test_the_card_lists_the_main_render_and_burns_a_copy(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QComboBox, QPushButton

    actions = _FakeActions()
    view = _packaging_view(tmp_path, actions)
    job = _job(tmp_path)
    view._job_store.add(job)  # noqa: SLF001
    view.set_job(job.id)

    view.refresh(job)

    combo = next(
        c
        for c in view.findChildren(QComboBox)
        if c.count() and "Main render" in c.itemText(0)
    )
    assert combo.itemText(0) == "Main render"

    next(
        b
        for b in view.findChildren(QPushButton)
        if b.text() == "Burn subtitles onto this video"
    ).click()
    _wait(view, qapp)

    assert len(actions.calls) == 1
    assert actions.calls[0]["source_file"] == job.render_result.output_file  # type: ignore[union-attr]
    assert actions.calls[0]["output_file"].endswith("final_video_subtitled.mp4")
    assert actions.calls[0]["offset_seconds"] == 0.0
    assert any("Subtitles burned into a copy" in t for t in _card_texts(view))


def test_a_failed_burn_says_why_on_the_card(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    view = _packaging_view(tmp_path, _FakeActions(fail=True))
    job = _job(tmp_path)
    view._job_store.add(job)  # noqa: SLF001
    view.set_job(job.id)
    view.refresh(job)

    next(
        b
        for b in view.findChildren(QPushButton)
        if b.text() == "Burn subtitles onto this video"
    ).click()
    _wait(view, qapp)

    assert any("Subtitles were not burned: boom" in t for t in _card_texts(view))


def test_a_render_that_already_has_subtitles_says_so(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view = _packaging_view(tmp_path, _FakeActions())
    job = _job(tmp_path, burned=True)
    view._job_store.add(job)  # noqa: SLF001
    view.set_job(job.id)

    view.refresh(job)

    assert any("already has subtitles burned in" in t for t in _card_texts(view))
    assert "Burn subtitles onto this video" not in _card_texts(view)


# --------------------------- the button inside the title card and variants sections


def _store_render(view, job: VideoJob, render: RenderResult) -> None:  # type: ignore[no-untyped-def]
    """Put `render` in the view's job store as the project's finished render. Built
    without the job's full cross-validation (that needs a whole timeline) - the card only
    reads the render's file."""

    from src.models.enums import JobStatus, WorkflowStage
    from src.models.render_orchestration_result import RenderOrchestrationResult

    view._job_store.set_render_result(  # noqa: SLF001
        job.id,
        RenderOrchestrationResult.model_construct(
            success=True,
            status=JobStatus.COMPLETED,
            current_stage=WorkflowStage.READY_FOR_UPLOAD,
            job=job,
            render_result=render,
        ),
    )


def _button_texts(view) -> list[str]:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    return [b.text() for b in view.findChildren(QPushButton)]


def _click(view, text: str) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    next(b for b in view.findChildren(QPushButton) if b.text() == text).click()


def test_the_title_card_section_burns_subtitles_onto_the_render_with_the_card(
    qapp,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    actions = _FakeActions()
    view = _packaging_view(tmp_path, actions)
    job = _job(tmp_path)
    job.title_card_enabled = True
    with_card = tmp_path / "final_video_with_title_card.mp4"
    with_card.write_bytes(b"card")
    view._job_store.add(job)  # noqa: SLF001
    _store_render(
        view,
        job,
        RenderResult(
            success=True,
            output_file=str(with_card),
            render_engine="ffmpeg",
            status=RenderStatus.COMPLETED,
        ),
    )
    view.set_job(job.id)
    view.refresh(job)

    assert "Burn subtitles onto the render with the title card" in _button_texts(view)

    _click(view, "Burn subtitles onto the render with the title card")
    _wait(view, qapp)

    assert len(actions.calls) == 1
    assert actions.calls[0]["source_file"] == str(with_card)
    assert actions.calls[0]["output_file"].endswith(
        "final_video_with_title_card_subtitled.mp4"
    )
    assert any("Subtitles burned into a copy" in t for t in _card_texts(view))


def test_the_title_card_section_says_what_to_do_first_when_there_is_no_card_video(
    qapp,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    view = _packaging_view(tmp_path, _FakeActions())
    job = _job(tmp_path)
    job.title_card_enabled = True
    view._job_store.add(job)  # noqa: SLF001
    view.set_job(job.id)
    view.refresh(job)

    assert "Burn subtitles onto the render with the title card" not in _button_texts(
        view
    )
    assert any("Add the title card to the render first" in t for t in _card_texts(view))


def test_the_export_variants_section_burns_subtitles_onto_a_variant(
    qapp,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    actions = _FakeActions()
    view = _packaging_view(tmp_path, actions)
    job = _job(tmp_path)
    variant_file = tmp_path / "variant_tiktok.mp4"
    variant_file.write_bytes(b"variant")
    view._job_store.add(job)  # noqa: SLF001
    _store_render(view, job, job.render_result)  # type: ignore[arg-type]
    view._job_store.set_export_variants(  # noqa: SLF001
        job.id,
        ExportVariantCollection(
            variants=[
                ExportVariant(
                    orientation=AspectRatio.PORTRAIT,
                    platform=Platform.TIKTOK,
                    output_file=str(variant_file),
                )
            ]
        ),
    )
    view.set_job(job.id)
    view.refresh(job)

    assert "Burn subtitles onto this variant" in _button_texts(view)

    _click(view, "Burn subtitles onto this variant")
    _wait(view, qapp)

    assert len(actions.calls) == 1
    assert actions.calls[0]["source_file"] == str(variant_file)
    assert actions.calls[0]["output_file"].endswith("variant_tiktok_subtitled.mp4")


def test_the_export_variants_section_asks_for_a_variant_first(
    qapp,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    view = _packaging_view(tmp_path, _FakeActions())
    job = _job(tmp_path)
    view._job_store.add(job)  # noqa: SLF001
    _store_render(view, job, job.render_result)  # type: ignore[arg-type]
    view.set_job(job.id)
    view.refresh(job)

    assert "Burn subtitles onto this variant" not in _button_texts(view)
    assert any("Generate a variant first" in t for t in _card_texts(view))


from tests.test_packaging_view_title_card_generation import (  # noqa: E402
    qapp as qapp,  # noqa: PLC0414 - fixture
)
