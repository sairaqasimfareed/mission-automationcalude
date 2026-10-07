"""
Reference frame selection (2026-10-05): a character's reference is the best
front-facing frame of the clip, not whatever the last frame shows - and no
reference at all when no frame is good enough.

The scoring and selection logic is tested with a stub detector; one test runs the
real YuNet model on real generated clips when they and the model are present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models.visual_continuity import (
    CanonicalEntityIdentity,
    CanonicalEntityType,
)
from src.services.reference_frame_selection_service import (
    REFERENCE_MIN_SCORE,
    DetectedFace,
    ReferenceFrameSelectionService,
    ReferenceKind,
    ReferenceSelectionStatus,
    SampledFrame,
    YuNetFaceDetector,
    default_model_directory,
    frontal_factor,
    no_reference_warning,
    pick_reference_frame,
    reference_kind_for,
    score_face,
    visibility_factor,
)


def _face(
    *,
    width: float = 120,
    frame_width: float = 640,
    score: float = 0.95,
    nose_offset: float = 0.0,
) -> DetectedFace:
    """Eyes 40px apart; `nose_offset` is how far the nose sits off-centre, as a
    fraction of that distance."""

    return DetectedFace(
        width=width,
        frame_width=frame_width,
        detection_score=score,
        right_eye_x=300,
        left_eye_x=340,
        nose_x=320 + nose_offset * 40,
    )


# ---- scoring -----------------------------------------------------------


def test_a_face_looking_straight_at_the_camera_is_fully_frontal() -> None:
    assert frontal_factor(_face(nose_offset=0.0)) == pytest.approx(1.0)


def test_a_turned_face_is_less_frontal_and_a_profile_is_not_at_all() -> None:
    assert 0.0 < frontal_factor(_face(nose_offset=0.3)) < 1.0
    assert frontal_factor(_face(nose_offset=0.6)) == 0.0
    assert frontal_factor(_face(nose_offset=1.2)) == 0.0


def test_the_nose_on_either_side_counts_the_same() -> None:
    assert frontal_factor(_face(nose_offset=0.3)) == pytest.approx(
        frontal_factor(_face(nose_offset=-0.3))
    )


def test_eyes_on_top_of_each_other_cannot_be_judged_frontal() -> None:
    face = DetectedFace(
        width=120,
        frame_width=640,
        detection_score=0.95,
        right_eye_x=300,
        left_eye_x=300.5,
        nose_x=300,
    )

    assert frontal_factor(face) == 0.0


def test_a_big_clear_frontal_face_scores_high() -> None:
    assert score_face(_face()) == pytest.approx(0.95)


def test_a_small_face_scores_lower_than_a_big_one() -> None:
    assert score_face(_face(width=30)) < score_face(_face(width=120))


def test_a_face_at_the_full_size_threshold_is_not_penalised_for_size() -> None:
    assert score_face(_face(width=0.12 * 640)) == pytest.approx(0.95)
    assert score_face(_face(width=0.5 * 640)) == pytest.approx(0.95)  # capped at 1


def test_a_profile_scores_zero_however_big() -> None:
    assert score_face(_face(width=300, nose_offset=1.0)) == 0.0


def test_a_zero_width_frame_scores_zero() -> None:
    assert score_face(_face(frame_width=0)) == 0.0


# ---- cropped faces ----------------------------------------------------


def _placed(x: float, y: float, w: float = 150, h: float = 170) -> DetectedFace:
    """A face with its box placed in a 640x360 frame."""

    return DetectedFace(
        width=w,
        frame_width=640,
        detection_score=0.95,
        right_eye_x=300,
        left_eye_x=340,
        nose_x=320,
        x=x,
        y=y,
        height=h,
        frame_height=360,
    )


def test_a_face_wholly_inside_the_frame_is_not_marked_down() -> None:
    assert visibility_factor(_placed(250, 60)) == 1.0


def test_a_face_cut_off_at_the_top_is_marked_down_hard() -> None:
    """Live, 2026-10-06: a frame of only a woman's mouth and chin (box at y=0)
    scored as a good reference."""

    cut = _placed(250, 0)

    assert visibility_factor(cut) == pytest.approx(0.35)
    assert score_face(cut) < REFERENCE_MIN_SCORE
    assert score_face(_placed(250, 60)) >= REFERENCE_MIN_SCORE


@pytest.mark.parametrize(
    "face",
    [
        _placed(0, 60),  # left edge
        _placed(490, 60),  # right edge (490 + 150 = 640)
        _placed(250, 190),  # bottom edge (190 + 170 = 360)
        _placed(-20, 60),  # partly outside
    ],
)
def test_a_face_touching_any_edge_counts_as_cropped(face: DetectedFace) -> None:
    assert visibility_factor(face) == pytest.approx(0.35)


def test_a_face_that_does_not_report_its_position_is_not_second_guessed() -> None:
    assert visibility_factor(_face()) == 1.0


def test_the_detector_confidence_is_set_high_enough_to_ignore_a_jar_label() -> None:
    """A decorated honey-jar label was reported as a face at 0.79 and 0.71; the
    real faces in the same project scored 0.89-0.91."""

    from src.services.reference_frame_selection_service import DETECTOR_CONFIDENCE

    assert 0.79 < DETECTOR_CONFIDENCE < 0.89


# ---- the service -------------------------------------------------------


class _Detector:
    """Looks a frame's image (an int) up in a table of faces."""

    def __init__(self, faces_by_image: dict[int, list[DetectedFace]]) -> None:
        self._faces = faces_by_image
        self.calls = 0

    def detect(self, frame: int) -> list[DetectedFace]:
        self.calls += 1

        return self._faces[frame]


def _service(
    faces_by_image: dict[int, list[DetectedFace]],
    *,
    available: bool = True,
    writer_ok: bool = True,
    **kwargs,  # type: ignore[no-untyped-def]
) -> tuple[ReferenceFrameSelectionService, _Detector]:
    detector = _Detector(faces_by_image)
    frames = [
        SampledFrame(index=i * 10, time_seconds=i * 0.5, image=i)
        for i in range(len(faces_by_image))
    ]

    def write(image: int, path: str) -> bool:
        if not writer_ok:
            return False

        Path(path).write_bytes(f"frame-{image}".encode())

        return True

    service = ReferenceFrameSelectionService(
        detector=detector,
        availability_check=lambda: available,
        frame_reader=lambda _path, _count: frames,
        image_writer=write,
        **kwargs,
    )

    return service, detector


def test_the_best_scoring_frame_is_chosen_and_written(tmp_path: Path) -> None:
    service, _ = _service(
        {
            0: [_face(nose_offset=0.5)],  # turned
            1: [_face()],  # clean, front-on
            2: [_face(width=40)],  # small
            3: [],  # nobody
        }
    )
    out = tmp_path / "ref.jpg"

    selection = service.select(video_path="clip.mp4", output_path=str(out))

    assert selection.status == ReferenceSelectionStatus.SELECTED
    assert out.read_bytes() == b"frame-1"
    assert selection.score == pytest.approx(0.95)
    assert selection.time_seconds == 0.5
    assert selection.frames_sampled == 4
    assert selection.frames_with_face == 3


def test_with_several_faces_the_best_one_in_the_frame_decides(tmp_path: Path) -> None:
    service, _ = _service({0: [_face(width=20), _face(nose_offset=1.0), _face()]})

    selection = service.select(video_path="c.mp4", output_path=str(tmp_path / "r.jpg"))

    assert selection.status == ReferenceSelectionStatus.SELECTED
    assert selection.score == pytest.approx(0.95)


def test_no_frame_good_enough_means_no_reference(tmp_path: Path) -> None:
    out = tmp_path / "ref.jpg"
    service, _ = _service({0: [_face(nose_offset=0.5)], 1: [_face(width=30)]})

    selection = service.select(video_path="c.mp4", output_path=str(out))

    assert selection.status == ReferenceSelectionStatus.NO_QUALIFYING_FACE
    assert not out.exists()
    assert selection.frames_with_face == 2
    assert 0 < selection.best_rejected_score < REFERENCE_MIN_SCORE
    assert "front-facing" in selection.reason
    assert "needs 0.50" in selection.reason


def test_a_clip_with_nobody_in_it_says_so(tmp_path: Path) -> None:
    service, _ = _service({0: [], 1: [], 2: []})

    selection = service.select(video_path="c.mp4", output_path=str(tmp_path / "r.jpg"))

    assert selection.status == ReferenceSelectionStatus.NO_QUALIFYING_FACE
    assert selection.frames_with_face == 0
    assert "No face appears" in selection.reason


def test_the_minimum_score_is_the_dividing_line(tmp_path: Path) -> None:
    face = _face(score=0.5)  # scores exactly 0.5

    service, _ = _service({0: [face]})
    assert (
        service.select(video_path="c", output_path=str(tmp_path / "a.jpg")).status
        == ReferenceSelectionStatus.SELECTED
    )

    stricter, _ = _service({0: [face]}, min_score=0.6)
    assert (
        stricter.select(video_path="c", output_path=str(tmp_path / "b.jpg")).status
        == ReferenceSelectionStatus.NO_QUALIFYING_FACE
    )


def test_unavailable_detection_is_reported_not_guessed(tmp_path: Path) -> None:
    service, detector = _service({0: [_face()]}, available=False)

    selection = service.select(video_path="c.mp4", output_path=str(tmp_path / "r.jpg"))

    assert selection.status == ReferenceSelectionStatus.UNAVAILABLE
    assert detector.calls == 0


def test_an_unreadable_clip_is_reported_not_raised(tmp_path: Path) -> None:
    def boom(_path: str, _count: int) -> list[SampledFrame]:
        raise OSError("corrupt")

    service = ReferenceFrameSelectionService(
        detector=_Detector({}),
        availability_check=lambda: True,
        frame_reader=boom,
    )

    selection = service.select(video_path="c.mp4", output_path=str(tmp_path / "r.jpg"))

    assert selection.status == ReferenceSelectionStatus.UNREADABLE


def test_a_clip_with_no_frames_is_unreadable(tmp_path: Path) -> None:
    service = ReferenceFrameSelectionService(
        detector=_Detector({}),
        availability_check=lambda: True,
        frame_reader=lambda _p, _c: [],
    )

    assert (
        service.select(video_path="c", output_path=str(tmp_path / "r.jpg")).status
        == ReferenceSelectionStatus.UNREADABLE
    )


def test_a_frame_the_detector_chokes_on_is_skipped_not_fatal(tmp_path: Path) -> None:
    class _Flaky:
        def detect(self, frame: int) -> list[DetectedFace]:
            if frame == 0:
                raise RuntimeError("bad frame")

            return [_face()]

    frames = [SampledFrame(i, float(i), i) for i in range(2)]
    service = ReferenceFrameSelectionService(
        detector=_Flaky(),
        availability_check=lambda: True,
        frame_reader=lambda _p, _c: frames,
        image_writer=lambda image, path: Path(path).write_bytes(b"x") > 0,
    )

    selection = service.select(video_path="c", output_path=str(tmp_path / "r.jpg"))

    assert selection.status == ReferenceSelectionStatus.SELECTED


def test_a_frame_that_cannot_be_written_is_reported(tmp_path: Path) -> None:
    service, _ = _service({0: [_face()]}, writer_ok=False)

    selection = service.select(video_path="c", output_path=str(tmp_path / "r.jpg"))

    assert selection.status == ReferenceSelectionStatus.UNREADABLE


def test_the_output_folder_is_created(tmp_path: Path) -> None:
    service, _ = _service({0: [_face()]})
    out = tmp_path / "deep" / "er" / "ref.jpg"

    assert (
        service.select(video_path="c", output_path=str(out)).status
        == ReferenceSelectionStatus.SELECTED
    )
    assert out.is_file()


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.5])
def test_a_nonsense_minimum_score_is_rejected(bad: float) -> None:
    with pytest.raises(ValueError):
        ReferenceFrameSelectionService(detector=_Detector({}), min_score=bad)


def test_at_least_one_frame_must_be_sampled() -> None:
    with pytest.raises(ValueError):
        ReferenceFrameSelectionService(detector=_Detector({}), sample_count=0)


# ---- locations: choose the frame that shows the PLACE -----------------


def _environment_service(
    sharpness_by_image: dict[int, float],
    faces_by_image: dict[int, list[DetectedFace]] | None = None,
    spread_by_image: dict[int, float] | None = None,
    **kwargs,  # type: ignore[no-untyped-def]
) -> ReferenceFrameSelectionService:
    faces = faces_by_image or {}
    frames = [
        SampledFrame(index=i * 10, time_seconds=i * 0.5, image=i)
        for i in sharpness_by_image
    ]

    class _D:
        def detect(self, frame: int) -> list[DetectedFace]:
            return faces.get(frame, [])

    return ReferenceFrameSelectionService(
        detector=_D(),
        availability_check=lambda: True,
        frame_reader=lambda _p, _c: frames,
        image_writer=lambda image, path: Path(path).write_bytes(
            f"frame-{image}".encode()
        )
        > 0,
        sharpness_scorer=lambda image: sharpness_by_image[image],
        spread_scorer=lambda image: (spread_by_image or {}).get(image, 1.0),
        **kwargs,
    )


def test_a_location_reference_is_the_sharpest_frame(tmp_path: Path) -> None:
    service = _environment_service({0: 40.0, 1: 180.0, 2: 90.0})
    out = tmp_path / "loc.jpg"

    selection = service.select(
        video_path="c", output_path=str(out), kind=ReferenceKind.ENVIRONMENT
    )

    assert selection.status == ReferenceSelectionStatus.SELECTED
    assert out.read_bytes() == b"frame-1"
    assert selection.score == pytest.approx(1.0)  # relative: the best on offer


def test_a_location_needs_no_face_at_all(tmp_path: Path) -> None:
    """The person gate must not apply: a wheat field has no face."""

    service = _environment_service({0: 50.0, 1: 60.0})

    selection = service.select(
        video_path="c",
        output_path=str(tmp_path / "loc.jpg"),
        kind=ReferenceKind.ENVIRONMENT,
    )

    assert selection.status == ReferenceSelectionStatus.SELECTED
    assert selection.frames_with_face == 0


def test_a_face_filling_the_shot_is_marked_down_for_a_location(tmp_path: Path) -> None:
    """The sharpest frame is a close-up of a person - the place shows in the
    next one, so that is the reference."""

    close_up = _face(width=0.4 * 640)
    service = _environment_service({0: 200.0, 1: 150.0}, faces_by_image={0: [close_up]})
    out = tmp_path / "loc.jpg"

    service.select(video_path="c", output_path=str(out), kind=ReferenceKind.ENVIRONMENT)

    assert out.read_bytes() == b"frame-1"


def test_a_clip_that_is_only_ever_a_close_up_still_gives_a_location_frame(
    tmp_path: Path,
) -> None:
    close_up = _face(width=0.4 * 640)
    service = _environment_service(
        {0: 100.0, 1: 140.0}, faces_by_image={0: [close_up], 1: [close_up]}
    )

    selection = service.select(
        video_path="c",
        output_path=str(tmp_path / "loc.jpg"),
        kind=ReferenceKind.ENVIRONMENT,
    )

    assert selection.status == ReferenceSelectionStatus.SELECTED


def test_a_frame_that_cannot_be_scored_is_skipped_for_a_location(
    tmp_path: Path,
) -> None:
    def sharp(image: int) -> float:
        if image == 0:
            raise RuntimeError("bad frame")

        return 80.0

    service = ReferenceFrameSelectionService(
        detector=_Detector({0: [], 1: []}),
        availability_check=lambda: True,
        frame_reader=lambda _p, _c: [SampledFrame(0, 0.0, 0), SampledFrame(10, 0.5, 1)],
        image_writer=lambda image, path: Path(path).write_bytes(b"x") > 0,
        sharpness_scorer=sharp,
        spread_scorer=lambda _image: 1.0,
    )

    assert (
        service.select(
            video_path="c",
            output_path=str(tmp_path / "l.jpg"),
            kind=ReferenceKind.ENVIRONMENT,
        ).status
        == ReferenceSelectionStatus.SELECTED
    )


def test_a_wide_shot_beats_a_sharper_close_up_of_one_object(tmp_path: Path) -> None:
    """Live, 2026-10-06: the Kitchen reference was a honey-jar close-up (sharp,
    detail only in the middle), so every Kitchen scene came out as the same jar. A
    place has detail spread across the frame."""

    service = _environment_service(
        {0: 220.0, 1: 150.0},  # frame 0 is the sharper one...
        spread_by_image={0: 0.35, 1: 0.9},  # ...but frame 1 shows the whole room
    )
    out = tmp_path / "loc.jpg"

    service.select(video_path="c", output_path=str(out), kind=ReferenceKind.ENVIRONMENT)

    assert out.read_bytes() == b"frame-1"


def test_environment_value_is_comparable_across_frames_and_files(
    tmp_path: Path,
) -> None:
    service = _environment_service(
        {0: 100.0, 1: 100.0}, spread_by_image={0: 0.4, 1: 0.8}
    )

    low, _ = service.environment_value(0)
    high, _ = service.environment_value(1)

    assert high == pytest.approx(2 * low)


def test_a_stored_reference_is_scored_on_the_same_scale(tmp_path: Path) -> None:
    class _D:
        def detect(self, frame):  # type: ignore[no-untyped-def]
            return [_face()] if frame == "portrait" else []

    service = ReferenceFrameSelectionService(
        detector=_D(),
        availability_check=lambda: True,
        image_reader=lambda path: Path(path).stem,
        sharpness_scorer=lambda _i: 100.0,
        spread_scorer=lambda _i: 0.5,
    )

    assert service.value_of_stored_reference(
        "portrait.jpg", ReferenceKind.PERSON
    ) == pytest.approx(0.95)
    assert (
        service.value_of_stored_reference("room.jpg", ReferenceKind.PERSON) == 0.0
    )  # no face in it
    assert service.value_of_stored_reference(
        "room.jpg", ReferenceKind.ENVIRONMENT
    ) == pytest.approx(50.0)


def test_a_stored_reference_that_cannot_be_read_scores_none() -> None:
    service = ReferenceFrameSelectionService(
        detector=_Detector({}),
        availability_check=lambda: True,
        image_reader=lambda _p: None,
    )

    assert service.value_of_stored_reference("x.jpg", ReferenceKind.PERSON) is None


def test_a_location_selection_is_reported_as_such_in_the_pick(tmp_path: Path) -> None:
    pick, _ = pick_reference_frame(
        selection_service=_environment_service({0: 70.0}),
        frame_extraction_service=_FrameExtraction(),  # type: ignore[arg-type]
        video_path="c.mp4",
        duration_seconds=8,
        output_path=str(tmp_path / "r.jpg"),
        kind=ReferenceKind.ENVIRONMENT,
    )

    assert pick is not None
    assert pick.metadata["selection_method"] == "best_environment"
    assert pick.metadata["reference_kind"] == "environment"


def test_a_persons_pick_is_marked_as_a_person(tmp_path: Path) -> None:
    service, _ = _service({0: [_face()]})

    pick, _ = pick_reference_frame(
        selection_service=service,
        frame_extraction_service=_FrameExtraction(),  # type: ignore[arg-type]
        video_path="c.mp4",
        duration_seconds=8,
        output_path=str(tmp_path / "r.jpg"),
    )

    assert pick is not None
    assert pick.metadata["reference_kind"] == "person"


def test_the_bible_decides_what_kind_of_reference_an_identity_gets() -> None:
    person = CanonicalEntityIdentity(
        entity_type=CanonicalEntityType.PERSON,
        name="Jack",
        canonical_description="A farmer.",
    )
    place = CanonicalEntityIdentity(
        entity_type=CanonicalEntityType.LOCATION,
        name="The farm",
        canonical_description="A wheat farm.",
    )

    assert reference_kind_for(person) == ReferenceKind.PERSON
    assert reference_kind_for(place) == ReferenceKind.ENVIRONMENT


# ---- pick_reference_frame (the one place both providers use) ----------


class _FrameExtraction:
    def __init__(self) -> None:
        self.calls = 0

    def extract_last_frame(
        self, *, video_path: str, video_duration_seconds: float, output_path: str
    ) -> str:
        self.calls += 1
        Path(output_path).write_bytes(b"last-frame")

        return output_path


def test_a_selected_frame_is_returned_with_how_it_was_chosen(tmp_path: Path) -> None:
    service, _ = _service({0: [_face()]})
    extraction = _FrameExtraction()

    pick, note = pick_reference_frame(
        selection_service=service,
        frame_extraction_service=extraction,  # type: ignore[arg-type]
        video_path="c.mp4",
        duration_seconds=8,
        output_path=str(tmp_path / "r.jpg"),
    )

    assert pick is not None
    assert pick.metadata["selection_method"] == "best_face"
    assert pick.metadata["reference_score"] == pytest.approx(0.95, abs=0.001)
    assert note == ""
    assert extraction.calls == 0


def test_no_good_frame_means_no_pick_and_no_last_frame_fallback(tmp_path: Path) -> None:
    service, _ = _service({0: [_face(nose_offset=1.0)]})
    extraction = _FrameExtraction()

    pick, note = pick_reference_frame(
        selection_service=service,
        frame_extraction_service=extraction,  # type: ignore[arg-type]
        video_path="c.mp4",
        duration_seconds=8,
        output_path=str(tmp_path / "r.jpg"),
    )

    assert pick is None
    assert "front-facing" in note
    assert extraction.calls == 0  # a bad frame is worse than none


def test_no_selection_service_uses_the_last_frame_as_before(tmp_path: Path) -> None:
    extraction = _FrameExtraction()

    pick, _ = pick_reference_frame(
        selection_service=None,
        frame_extraction_service=extraction,  # type: ignore[arg-type]
        video_path="c.mp4",
        duration_seconds=8,
        output_path=str(tmp_path / "r.jpg"),
    )

    assert pick is not None
    assert pick.metadata == {
        "selection_method": "last_frame",
        "reference_kind": "person",
    }
    assert extraction.calls == 1


def test_unavailable_detection_falls_back_to_the_last_frame(tmp_path: Path) -> None:
    service, _ = _service({0: [_face()]}, available=False)
    extraction = _FrameExtraction()

    pick, _ = pick_reference_frame(
        selection_service=service,
        frame_extraction_service=extraction,  # type: ignore[arg-type]
        video_path="c.mp4",
        duration_seconds=8,
        output_path=str(tmp_path / "r.jpg"),
    )

    assert pick is not None
    assert pick.metadata == {
        "selection_method": "last_frame_fallback",
        "reference_kind": "person",
    }
    assert extraction.calls == 1


def test_the_warning_names_who_got_no_reference() -> None:
    text = no_reference_warning(4, ["Mara", "Jack"], "No face appears in the clip.")

    assert text.startswith("Scene 4:")
    assert "Mara, Jack" in text
    assert "text-only" in text
    assert "no usable reference frame" in text
    assert text.endswith("No face appears in the clip.")


# ---- the real model on real clips -------------------------------------

_MODEL = default_model_directory() / "face_detection_yunet_2023mar.onnx"
_CLIPS = sorted(Path("data/google_flow_downloads/qasim").glob("*/*.mp4"))


def test_the_detector_model_file_ships_with_the_repo() -> None:
    assert _MODEL.is_file()
    assert _MODEL.stat().st_size > 100_000  # a real ONNX file, not a pointer stub


@pytest.mark.skipif(
    not _CLIPS or not YuNetFaceDetector().is_available(),
    reason="Needs OpenCV, the detector model and real generated clips.",
)
def test_the_real_model_finds_a_clear_face_in_real_clips(tmp_path: Path) -> None:
    service = ReferenceFrameSelectionService()
    selected = []

    for index, clip in enumerate(_CLIPS):
        out = tmp_path / f"ref_{index}.jpg"
        selection = service.select(video_path=str(clip), output_path=str(out))

        if selection.status == ReferenceSelectionStatus.SELECTED:
            selected.append((selection, out))

    assert selected, "none of the person clips gave a usable reference"

    for selection, out in selected:
        assert selection.score >= REFERENCE_MIN_SCORE
        assert out.stat().st_size > 5_000  # a real JPEG, not an empty file


def test_lenient_offers_the_sharpest_frame_when_no_face_qualifies(
    tmp_path: Path,
) -> None:
    """A group seen from behind has no clear face; the picker still needs a frame to
    show. Automatic selection (not lenient) keeps refusing."""

    sharpness = {0: 1.0, 1: 5.0, 2: 2.0}
    service, _ = _service(
        {0: [], 1: [], 2: []},
        sharpness_scorer=lambda image: sharpness[image],
        spread_scorer=lambda _image: 1.0,
    )
    out = tmp_path / "ref.jpg"

    strict = service.select(video_path="c.mp4", output_path=str(out))
    lenient = service.select(video_path="c.mp4", output_path=str(out), lenient=True)

    assert strict.status == ReferenceSelectionStatus.NO_QUALIFYING_FACE
    assert lenient.status == ReferenceSelectionStatus.SELECTED
    assert out.read_bytes() == b"frame-1"  # the sharpest one


def test_lenient_still_prefers_a_clear_face_when_there_is_one(tmp_path: Path) -> None:
    service, _ = _service({0: [], 1: [_face()]})
    out = tmp_path / "ref.jpg"

    selection = service.select(video_path="c.mp4", output_path=str(out), lenient=True)

    assert selection.score == pytest.approx(0.95)
    assert out.read_bytes() == b"frame-1"
