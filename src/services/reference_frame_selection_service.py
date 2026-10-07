from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from src.models.scene import Scene
from src.models.video_clip import VideoClip
from src.models.video_job import VideoJob
from src.models.visual_continuity import (
    CanonicalEntityIdentity,
    CanonicalEntityType,
)
from src.services.asset_storage_service import AssetStorageService
from src.services.frame_extraction_service import FrameExtractionService
from src.shared.logger import logger

# A frame must score at least this to be used as a character reference. Chosen
# from a test on 60 real Flow clips (2026-10-05): clean front-facing close-ups
# scored 0.6-0.95, small helmeted faces in wide shots 0.3-0.5. Below this a
# reference does more harm than none (a profile or a tiny face makes every later
# scene of that character worse than text-only continuity), so nothing is used.
REFERENCE_MIN_SCORE = 0.5

DEFAULT_SAMPLE_COUNT = 8

# Frames are shrunk to this width before detection - about 4x faster than full
# 1280 wide, and plenty to find a face.
DETECTION_WIDTH = 640

# A face this fraction of the frame width (or more) counts as "big enough".
_FULL_SIZE_FACE_WIDTH_FRACTION = 0.12

# How far the nose may sit from the midpoint of the eyes, as a fraction of the eye
# distance, before the face counts as fully turned away.
_FULL_TURN_NOSE_OFFSET = 0.6

# A location reference should show the PLACE. A face filling much of the frame
# makes the generator reproduce that person instead, so frames dominated by a
# face are marked down - fully at this fraction of the frame width, and by at most
# the penalty below (a clip that is only ever a close-up still gets a frame).
_FACE_DOMINANCE_WIDTH_FRACTION = 0.30
_FACE_DOMINANCE_MAX_PENALTY = 0.8

# A face whose box touches the edge of the frame is cut off (forehead, chin or
# side missing). Live, 2026-10-06: a frame showing only a woman's mouth and chin
# scored as a good reference. Such a face is marked down hard; a box within this
# fraction of an edge counts as touching it.
_EDGE_TOUCH_FRACTION = 0.01
_CROPPED_FACE_FACTOR = 0.35

# The detector only reports a face at or above this confidence. Live, 2026-10-06:
# the decorated label on a honey jar was reported as a face at 0.79 and 0.71 and
# became a character's "reference", while real faces in the same project scored
# 0.89-0.91. A missed face costs a reference; a false one poisons every scene.
DETECTOR_CONFIDENCE = 0.85

_DEFAULT_DETECTOR_MODEL = "face_detection_yunet_2023mar.onnx"


def default_model_directory() -> Path:
    """models/face at the repository root - and at the bundle root in the
    packaged app, where the spec places the same folder."""

    return Path(__file__).resolve().parents[2] / "models" / "face"


@dataclass(frozen=True)
class DetectedFace:
    """One face, in the pixel coordinates of a frame `frame_width` wide."""

    width: float
    frame_width: float
    detection_score: float
    right_eye_x: float
    left_eye_x: float
    nose_x: float
    # Where the face box sits in the frame (0 = not reported, so no
    # cropping check is made).
    x: float = 0.0
    y: float = 0.0
    height: float = 0.0
    frame_height: float = 0.0


class FaceDetector(Protocol):
    def detect(self, frame: Any) -> list[DetectedFace]: ...


def frontal_factor(face: DetectedFace) -> float:
    """1.0 = looking straight at the camera, falling to 0 for a profile.

    Taken from where the nose sits between the eyes: centred when frontal, pushed
    to one side as the head turns."""

    eye_distance = abs(face.left_eye_x - face.right_eye_x)

    if eye_distance < 1.0:
        return 0.0

    midpoint = (face.right_eye_x + face.left_eye_x) / 2.0
    offset = abs(face.nose_x - midpoint) / eye_distance

    return max(0.0, 1.0 - offset / _FULL_TURN_NOSE_OFFSET)


def visibility_factor(face: DetectedFace) -> float:
    """1.0 for a face wholly inside the frame, markedly less when its box touches
    an edge (part of the head is out of shot)."""

    if face.frame_height <= 0 or face.height <= 0:
        return 1.0

    margin_x = _EDGE_TOUCH_FRACTION * face.frame_width
    margin_y = _EDGE_TOUCH_FRACTION * face.frame_height
    cut = (
        face.x <= margin_x
        or face.y <= margin_y
        or face.x + face.width >= face.frame_width - margin_x
        or face.y + face.height >= face.frame_height - margin_y
    )

    return _CROPPED_FACE_FACTOR if cut else 1.0


def score_face(face: DetectedFace) -> float:
    """0-1: detector confidence x how big the face is x how frontal it is x
    whether all of it is in the frame."""

    if face.frame_width <= 0:
        return 0.0

    size_factor = min(
        (face.width / face.frame_width) / _FULL_SIZE_FACE_WIDTH_FRACTION, 1.0
    )

    return (
        face.detection_score
        * size_factor
        * frontal_factor(face)
        * visibility_factor(face)
    )


@dataclass(frozen=True)
class SampledFrame:
    index: int
    time_seconds: float
    image: Any


class ReferenceKind(str, Enum):
    """What the reference is OF, which decides how its frame is chosen: a person
    by how clearly their face shows, a place by how clearly the place shows."""

    PERSON = "person"
    ENVIRONMENT = "environment"


def reference_kind_for(identity: CanonicalEntityIdentity) -> ReferenceKind:
    return (
        ReferenceKind.PERSON
        if identity.entity_type == CanonicalEntityType.PERSON
        else ReferenceKind.ENVIRONMENT
    )


class ReferenceSelectionStatus(str, Enum):
    SELECTED = "selected"
    NO_QUALIFYING_FACE = "no_qualifying_face"
    UNREADABLE = "unreadable"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ReferenceFrameSelection:
    status: ReferenceSelectionStatus
    output_path: str | None = None
    score: float = 0.0
    time_seconds: float = 0.0
    frames_sampled: int = 0
    frames_with_face: int = 0
    best_rejected_score: float = 0.0
    # The chosen frame's value on a scale that is comparable ACROSS clips (a
    # person's face score, or a location's sharpness x spread x no-face-in-the-
    # way). `score` for a location is relative to its own clip and cannot be
    # compared with another clip's, or with a stored reference.
    raw_value: float = 0.0
    reason: str = ""


class YuNetFaceDetector:
    """OpenCV's YuNet face detector (a 0.2 MB ONNX model, Apache-2.0, run on the
    CPU). Everything OpenCV is imported lazily so a machine without it still runs
    the app - `is_available()` says whether detection can happen at all."""

    def __init__(
        self,
        *,
        model_path: Path | None = None,
        confidence: float = DETECTOR_CONFIDENCE,
    ) -> None:
        self._confidence = confidence
        self._model_path = model_path or (
            default_model_directory() / _DEFAULT_DETECTOR_MODEL
        )
        self._detector: Any = None
        self._cv2: Any = None

    def is_available(self) -> bool:
        if not self._model_path.is_file():
            return False

        try:
            import cv2  # noqa: F401
        except ImportError:
            return False

        return True

    def detect(self, frame: Any) -> list[DetectedFace]:
        cv2 = self._load()
        height, width = frame.shape[:2]

        if width > DETECTION_WIDTH:
            scale = DETECTION_WIDTH / float(width)
            frame = cv2.resize(frame, (DETECTION_WIDTH, int(round(height * scale))))
            height, width = frame.shape[:2]

        self._detector.setInputSize((width, height))
        _, faces = self._detector.detect(frame)

        if faces is None:
            return []

        return [
            DetectedFace(
                width=float(face[2]),
                frame_width=float(width),
                x=float(face[0]),
                y=float(face[1]),
                height=float(face[3]),
                frame_height=float(height),
                detection_score=float(face[14]),
                right_eye_x=float(face[4]),
                left_eye_x=float(face[6]),
                nose_x=float(face[8]),
            )
            for face in faces
        ]

    def _load(self) -> Any:
        if self._detector is None:
            import cv2

            self._cv2 = cv2
            self._detector = cv2.FaceDetectorYN.create(
                str(self._model_path), "", (320, 320), self._confidence, 0.3, 5000
            )

        return self._cv2


def _read_sample_frames(video_path: str, count: int) -> list[SampledFrame]:
    """`count` evenly spaced frames, read by decoding the clip once in order -
    seeking to each frame is several times slower."""

    import cv2

    capture = cv2.VideoCapture(video_path)

    try:
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = capture.get(cv2.CAP_PROP_FPS) or 24.0

        if total < 1:
            return []

        wanted = sorted({int(total * (i + 0.5) / count) for i in range(count)})
        frames: list[SampledFrame] = []
        index = 0

        for target in wanted:
            while index < target:
                if not capture.grab():
                    return frames

                index += 1

            if not capture.grab():
                return frames

            ok, image = capture.retrieve()
            index += 1

            if ok:
                frames.append(SampledFrame(target, target / fps, image))

        return frames
    finally:
        capture.release()


def _sharpness(image: Any) -> float:
    """How in-focus a frame is: the variance of its Laplacian, on a small
    greyscale copy so the number does not depend on the clip's resolution."""

    import cv2

    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = grey.shape[:2]

    if width > DETECTION_WIDTH:
        grey = cv2.resize(
            grey, (DETECTION_WIDTH, int(round(height * DETECTION_WIDTH / width)))
        )

    return float(cv2.Laplacian(grey, cv2.CV_64F).var())


def _spread(image: Any) -> float:
    """How evenly the frame's detail is spread, 0-1: the normalised entropy of
    the Laplacian energy over a 4x4 grid.

    A wide shot of a room has detail across the whole frame; a close-up of one
    object (a honey jar, a hand) has it in the middle and smooth blur around it.
    A location reference should show the PLACE - without this a sharp close-up of
    a prop beats the wide shot (live, 2026-10-06: the Kitchen reference was the
    honey jar, so every Kitchen scene came out as the same jar)."""

    import math

    import cv2

    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = grey.shape[:2]

    if width > DETECTION_WIDTH:
        grey = cv2.resize(
            grey, (DETECTION_WIDTH, int(round(height * DETECTION_WIDTH / width)))
        )
        height, width = grey.shape[:2]

    energy = abs(cv2.Laplacian(grey, cv2.CV_64F))
    cells = [
        float(
            energy[
                row * height // 4 : (row + 1) * height // 4,
                col * width // 4 : (col + 1) * width // 4,
            ].mean()
        )
        for row in range(4)
        for col in range(4)
    ]
    total = sum(cells)

    if total <= 0:
        return 0.0

    shares = [c / total for c in cells if c > 0]

    return -sum(share * math.log(share) for share in shares) / math.log(16)


def _read_image(path: str) -> Any:
    import cv2

    return cv2.imread(path)


def _write_image(image: Any, path: str) -> bool:
    import cv2

    return bool(cv2.imwrite(path, image))


class ReferenceFrameSelectionService:
    """
    Picks the frame of a generated clip that makes the best reference for the
    character on screen: sampled across the whole clip, each frame scored for a
    detected face that is big enough and facing the camera, the best kept.

    Replaces "whatever the last frame happens to show" - the real cause of an
    unusable side-profile reference (2026-09-21). On 60 real Flow clips the last
    frame was good enough in 12, the best of 8 in 19. If no frame is good
    enough the answer is "none": a bad reference is worse than no reference.

    Local and free - no LLM call, no network.
    """

    def __init__(
        self,
        *,
        detector: FaceDetector | None = None,
        availability_check: Callable[[], bool] | None = None,
        frame_reader: Callable[[str, int], list[SampledFrame]] | None = None,
        image_writer: Callable[[Any, str], bool] | None = None,
        sharpness_scorer: Callable[[Any], float] | None = None,
        spread_scorer: Callable[[Any], float] | None = None,
        image_reader: Callable[[str], Any] | None = None,
        min_score: float = REFERENCE_MIN_SCORE,
        sample_count: int = DEFAULT_SAMPLE_COUNT,
    ) -> None:
        if not 0.0 < min_score <= 1.0:
            raise ValueError("The minimum reference score must be in (0, 1].")

        if sample_count < 1:
            raise ValueError("At least one frame must be sampled.")

        default_detector = YuNetFaceDetector() if detector is None else None
        self._detector: FaceDetector = detector or default_detector  # type: ignore[assignment]
        self._is_available = availability_check or (
            default_detector.is_available if default_detector is not None else _always
        )
        self._read_frames = frame_reader or _read_sample_frames
        self._write_image = image_writer or _write_image
        self._sharpness = sharpness_scorer or _sharpness
        self._spread_of = spread_scorer or _spread
        self._read_image = image_reader or _read_image
        self._min_score = min_score
        self._sample_count = sample_count

    def select(
        self,
        *,
        video_path: str,
        output_path: str,
        kind: ReferenceKind = ReferenceKind.PERSON,
        lenient: bool = False,
    ) -> ReferenceFrameSelection:
        """The best frame of the clip. `lenient` keeps a person reference useful when no
        frame shows a clear front-facing face (a group, people seen from behind, a wide
        shot): the sharpest frame is returned instead of refusing, for the operator to
        judge in the picker. Automatic selection never uses it."""

        if not self._is_available():
            return ReferenceFrameSelection(
                status=ReferenceSelectionStatus.UNAVAILABLE,
                reason="Face detection is not available (OpenCV or the model "
                "file is missing).",
            )

        try:
            frames = self._read_frames(video_path, self._sample_count)
        except Exception as error:  # noqa: BLE001 - a bad clip must not crash the run
            return ReferenceFrameSelection(
                status=ReferenceSelectionStatus.UNREADABLE,
                reason=f"The clip could not be read: {type(error).__name__}.",
            )

        if not frames:
            return ReferenceFrameSelection(
                status=ReferenceSelectionStatus.UNREADABLE,
                reason="No frames could be read from the clip.",
            )

        if kind == ReferenceKind.ENVIRONMENT:
            return self._select_environment(frames, output_path)

        best: tuple[float, SampledFrame] | None = None
        best_any = 0.0
        with_face = 0

        for frame in frames:
            try:
                faces = self._detector.detect(frame.image)
            except Exception as error:  # noqa: BLE001
                logger.warning(
                    "Face detection failed on one frame: %s", type(error).__name__
                )
                continue

            if faces:
                with_face += 1

            score = max((score_face(face) for face in faces), default=0.0)
            best_any = max(best_any, score)

            if score >= self._min_score and (best is None or score > best[0]):
                best = (score, frame)

        if best is None and lenient:
            return self._select_environment(frames, output_path)

        if best is None:
            return ReferenceFrameSelection(
                status=ReferenceSelectionStatus.NO_QUALIFYING_FACE,
                frames_sampled=len(frames),
                frames_with_face=with_face,
                best_rejected_score=best_any,
                reason=(
                    "No sampled frame shows a clear, front-facing face"
                    if with_face
                    else "No face appears in the clip"
                )
                + f" (best score {best_any:.2f}, needs {self._min_score:.2f}).",
            )

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        if not self._write_image(best[1].image, output_path):
            return ReferenceFrameSelection(
                status=ReferenceSelectionStatus.UNREADABLE,
                reason="The chosen frame could not be written to disk.",
            )

        return ReferenceFrameSelection(
            status=ReferenceSelectionStatus.SELECTED,
            output_path=output_path,
            score=best[0],
            raw_value=best[0],
            time_seconds=best[1].time_seconds,
            frames_sampled=len(frames),
            frames_with_face=with_face,
        )

    def environment_value(self, image: Any) -> tuple[float, int]:
        """(value, number of faces) of one frame as a LOCATION reference:
        sharpness x how evenly the detail is spread x not being dominated by a
        face. Comparable across frames, clips and stored references."""

        sharpness = self._sharpness(image)
        spread = self._spread_of(image)
        faces = self._detector.detect(image)
        largest = max(
            (face.width / face.frame_width for face in faces if face.frame_width > 0),
            default=0.0,
        )
        penalty = (
            min(largest / _FACE_DOMINANCE_WIDTH_FRACTION, 1.0)
            * _FACE_DOMINANCE_MAX_PENALTY
        )

        return sharpness * spread * (1.0 - penalty), len(faces)

    def person_value(self, image: Any) -> float:
        """The best face score in one image (0 when no face is found)."""

        return max(
            (score_face(face) for face in self._detector.detect(image)), default=0.0
        )

    def value_of_stored_reference(self, path: str, kind: ReferenceKind) -> float | None:
        """How a reference picture already on disk scores on the same scale as a
        freshly chosen frame - so a stored reference can be compared with a
        candidate. None when the picture cannot be read or scored."""

        try:
            image = self._read_image(path)

            if image is None:
                return None

            if kind == ReferenceKind.PERSON:
                return self.person_value(image)

            return self.environment_value(image)[0]
        except Exception as error:  # noqa: BLE001
            logger.warning(
                "Scoring a stored reference failed: %s", type(error).__name__
            )

            return None

    def is_available(self) -> bool:
        return bool(self._is_available())

    def _select_environment(
        self, frames: list[SampledFrame], output_path: str
    ) -> ReferenceFrameSelection:
        """The sharpest frame, marked down where a face fills the shot, so the
        reference shows the place rather than whoever stands in it. No minimum:
        a location has no "clear face" test to fail, and some frame is always
        the best available."""

        scored: list[tuple[float, SampledFrame, int]] = []

        for frame in frames:
            try:
                value, face_count = self.environment_value(frame.image)
            except Exception as error:  # noqa: BLE001
                logger.warning(
                    "Scoring one frame for a location reference failed: %s",
                    type(error).__name__,
                )
                continue

            scored.append((value, frame, face_count))

        if not scored:
            return ReferenceFrameSelection(
                status=ReferenceSelectionStatus.UNREADABLE,
                reason="No frame of the clip could be scored.",
            )

        best_value, best_frame, _ = max(scored, key=lambda item: item[0])
        peak = max(value for value, _, _ in scored)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        if not self._write_image(best_frame.image, output_path):
            return ReferenceFrameSelection(
                status=ReferenceSelectionStatus.UNREADABLE,
                reason="The chosen frame could not be written to disk.",
            )

        return ReferenceFrameSelection(
            status=ReferenceSelectionStatus.SELECTED,
            output_path=output_path,
            # Sharpness has no fixed scale, so the "score" here is relative: how
            # close the chosen frame is to the best the clip offered (1.0).
            score=(best_value / peak) if peak > 0 else 0.0,
            raw_value=best_value,
            time_seconds=best_frame.time_seconds,
            frames_sampled=len(frames),
            frames_with_face=sum(1 for _, _, count in scored if count),
        )


def _always() -> bool:
    return True


@dataclass(frozen=True)
class ReferenceFramePick:
    """A frame chosen as a reference, plus how it was chosen (stored with the
    asset so a later, clearly better frame can replace it)."""

    path: str
    metadata: dict[str, Any] = field(default_factory=dict)


def pick_reference_frame(
    *,
    selection_service: ReferenceFrameSelectionService | None,
    frame_extraction_service: FrameExtractionService,
    video_path: str,
    duration_seconds: float,
    output_path: str,
    kind: ReferenceKind = ReferenceKind.PERSON,
) -> tuple[ReferenceFramePick | None, str]:
    """
    The one place both video providers choose their reference frame.

    Returns (pick, note). `pick` is None when no frame is good enough - the
    caller then attaches no reference and may show `note` to the operator. With
    no selection service wired, or face detection unavailable on this machine,
    it falls back to the original last-frame grab, so an install without OpenCV
    behaves exactly as it did before.
    """

    if selection_service is not None:
        selection = selection_service.select(
            video_path=video_path, output_path=output_path, kind=kind
        )

        if selection.status == ReferenceSelectionStatus.SELECTED:
            assert selection.output_path is not None

            return (
                ReferenceFramePick(
                    path=selection.output_path,
                    metadata={
                        "selection_method": (
                            "best_face"
                            if kind == ReferenceKind.PERSON
                            else "best_environment"
                        ),
                        "reference_kind": kind.value,
                        "reference_score": round(selection.score, 3),
                        "reference_time_seconds": round(selection.time_seconds, 2),
                    },
                ),
                "",
            )

        if selection.status != ReferenceSelectionStatus.UNAVAILABLE:
            return None, selection.reason

        logger.warning("%s Falling back to the last frame.", selection.reason)
        method = "last_frame_fallback"
    else:
        method = "last_frame"

    extracted = frame_extraction_service.extract_last_frame(
        video_path=video_path,
        video_duration_seconds=duration_seconds,
        output_path=output_path,
    )

    return (
        ReferenceFramePick(
            path=extracted,
            metadata={"selection_method": method, "reference_kind": kind.value},
        ),
        "",
    )


def extract_references_for_identities(
    *,
    job: VideoJob,
    scene: Scene,
    clip: VideoClip,
    identities: list[CanonicalEntityIdentity],
    selection_service: ReferenceFrameSelectionService | None,
    frame_extraction_service: FrameExtractionService,
    asset_storage_service: AssetStorageService,
) -> None:
    """
    Gives each identity a reference chosen FOR WHAT IT IS, per the continuity
    bible: people from the frame that shows their face best, locations from the
    frame that shows the place best. A scene introducing both a person and a
    place stores two different frames, not one shared one. (Several people
    introduced in the same scene still share one frame - telling them apart in a
    frame is not built.)

    Best-effort, like the extraction it replaces: a failure for one kind is
    logged and the run goes on. An identity that gets nothing stays eligible, so
    its next on-screen scene tries again.
    """

    groups: dict[ReferenceKind, list[CanonicalEntityIdentity]] = {}

    for identity in identities:
        groups.setdefault(reference_kind_for(identity), []).append(identity)

    with tempfile.TemporaryDirectory() as temp_directory:
        for kind, group in groups.items():
            try:
                pick, note = pick_reference_frame(
                    selection_service=selection_service,
                    frame_extraction_service=frame_extraction_service,
                    video_path=clip.local_file or "",
                    duration_seconds=float(clip.duration_seconds),
                    output_path=(
                        f"{temp_directory}/scene_{scene.scene_number:03d}_"
                        f"{kind.value}.jpg"
                    ),
                    kind=kind,
                )

                if pick is None:
                    warning = no_reference_warning(
                        scene.scene_number, [i.name for i in group], note
                    )
                    logger.info(warning)

                    if warning not in job.warnings:
                        job.warnings.append(warning)

                    continue

                result = asset_storage_service.store_extracted_frame(
                    source_path=pick.path,
                    project_id=str(job.id),
                    scene_number=scene.scene_number,
                    title=f"Reference - scene {scene.scene_number} ({kind.value})",
                    metadata=pick.metadata,
                )
            except Exception as error:  # noqa: BLE001 - never fails the scene
                logger.warning(
                    "Reference frame extraction failed for scene %s: %s",
                    scene.scene_number,
                    type(error).__name__,
                )
                continue

            if not result.success or result.asset is None:
                logger.warning(
                    "Storing the extracted reference frame failed for scene %s: %s",
                    scene.scene_number,
                    result.message,
                )
                continue

            for identity in group:
                identity.reference_asset_ids = [str(result.asset.id)]


def no_reference_warning(scene_number: int, names: list[str], note: str) -> str:
    """The job warning for an identity that got no reference from a scene."""

    who = ", ".join(names) if names else "the character"

    return (
        f"Scene {scene_number}: no usable reference frame found for {who} - "
        f"continuity stays text-only for them until a scene gives one. {note}"
    ).strip()


__all__ = [
    "DEFAULT_SAMPLE_COUNT",
    "REFERENCE_MIN_SCORE",
    "DetectedFace",
    "FaceDetector",
    "ReferenceFramePick",
    "ReferenceFrameSelection",
    "ReferenceFrameSelectionService",
    "ReferenceSelectionStatus",
    "SampledFrame",
    "YuNetFaceDetector",
    "default_model_directory",
    "ReferenceKind",
    "extract_references_for_identities",
    "frontal_factor",
    "no_reference_warning",
    "pick_reference_frame",
    "reference_kind_for",
    "score_face",
    "visibility_factor",
]
