"""Reads a pasted table of "narration | on screen" rows and matches each row to the scene it belongs to.

The operator's script and the table (often written by another assistant) rarely line up row for row
with the scenes the app made: the scene planner groups sentences into clips of at most 8 seconds, so
21 sentences can be 19 scenes. Row NUMBERS are therefore ignored. A row is matched by its narration
text, walking the rows and the scenes in order, so a short repeated row ("Her.", "It was her.") lands in
the right scene and not the first one that happens to contain the words.

Nothing is guessed: a row that cannot be found is reported with the nearest scene, and the operator
decides. Pure and deterministic - no model call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from src.models.scene import Scene
from src.models.scene_visual import (
    MAX_VISUAL_CHARACTERS,
    SceneVisual,
    SceneVisualPlan,
    narration_key,
    normalize_text,
)

# How many scenes ahead of the last match a row may be found. A row that exists only further away is
# reported instead of silently dragging the pointer across the script.
_LOOK_AHEAD_SCENES = 6
# A scene that receives this many rows is flagged: one clip cannot show many beats.
CROWDED_ROW_COUNT = 3

_NO_VISUAL = frozenset({"", "-", "—", "–", "none", "n/a", "na", "no visual"})
_MARKDOWN_RULE = re.compile(r"[\s|:\-]+")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?…])\s+")
_NUMBER_CELL = re.compile(r"\d+[.)]?")


def _is_visual_header(text: str) -> bool:
    lowered = text.strip().lower()

    return len(lowered) <= 30 and ("screen" in lowered or "visual" in lowered)


def _stacked_pairs(lines: list[str]) -> list[tuple[str, str]] | None:
    """(narration, visual) pairs from a table whose cells each sit on their own line:

        #  /  Narration  /  On screen  /  1  /  <narration>  /  <visual>  /  2  /  ...

    A numbered table is read by its numbers (a visual may wrap over several lines until the next
    number), an unnumbered one two lines at a time. None when the first lines are not a header
    or the rest does not line up - the caller then asks for a table with columns."""

    cells = [line.strip() for line in lines]

    if (
        len(cells) >= 3
        and cells[0].lower() in {"#", "no", "no.", "scene", "number"}
        and cells[1].lower() == "narration"
        and _is_visual_header(cells[2])
    ):
        data = cells[3:]
        pairs: list[tuple[str, str]] = []
        index = 0
        expected: int | None = None

        while index < len(data):
            number_cell = data[index]

            if not _NUMBER_CELL.fullmatch(number_cell) or index + 2 >= len(data):
                return None

            number = int(number_cell.rstrip(".)"))

            if expected is not None and number != expected:
                return None

            narration = data[index + 1]
            index += 2
            visual: list[str] = []

            while index < len(data) and not (
                _NUMBER_CELL.fullmatch(data[index])
                and int(data[index].rstrip(".)")) == number + 1
            ):
                if _NUMBER_CELL.fullmatch(data[index]):
                    return None  # a bare number that is not the next one: the rows do not line up

                visual.append(data[index])
                index += 1

            if not visual:
                return None

            pairs.append((narration, " ".join(visual)))
            expected = number + 1

        return pairs or None

    if (
        len(cells) >= 2
        and cells[0].lower() == "narration"
        and _is_visual_header(cells[1])
    ):
        data = cells[2:]

        if not data or len(data) % 2:
            return None

        return [(data[i], data[i + 1]) for i in range(0, len(data), 2)]

    return None


class RowStatus(str, Enum):
    MATCHED = "matched"
    PARTIAL = "partial"  # only some of its sentences were found
    SPANS = "spans"  # its sentences fall in more than one scene
    OUT_OF_ORDER = "out_of_order"  # found, but earlier than the previous row
    UNMATCHED = "unmatched"


@dataclass(frozen=True)
class VisualRow:
    index: int  # 1-based position among the pasted rows that carry a visual
    narration: str
    visual: str


@dataclass
class RowResult:
    row: VisualRow
    status: RowStatus
    scene_numbers: list[int] = field(default_factory=list)
    nearest_scene: int | None = None
    similarity: float = 0.0

    @property
    def is_placed(self) -> bool:
        return bool(self.scene_numbers)


@dataclass
class MatchResult:
    results: list[RowResult]
    scenes: list[Scene]

    def assign(self, row_index: int, scene_number: int) -> None:
        """Place a row the operator chose a scene for (an unmatched or out-of-order one)."""

        if scene_number not in {s.scene_number for s in self.scenes}:
            raise ValueError(f"This project has no scene {scene_number}.")

        for result in self.results:
            if result.row.index == row_index:
                result.scene_numbers = [scene_number]
                result.status = RowStatus.MATCHED

                return

        raise ValueError(f"There is no pasted row {row_index}.")

    def rows_by_scene(self) -> dict[int, list[VisualRow]]:
        placed: dict[int, list[VisualRow]] = {}

        for result in self.results:
            for number in result.scene_numbers:
                placed.setdefault(number, []).append(result.row)

        return {number: placed[number] for number in sorted(placed)}

    @property
    def unplaced(self) -> list[RowResult]:
        return [r for r in self.results if not r.is_placed]

    @property
    def scenes_without_visual(self) -> list[int]:
        placed = self.rows_by_scene()

        return [s.scene_number for s in self.scenes if s.scene_number not in placed]

    @property
    def crowded_scenes(self) -> list[int]:
        return [
            number
            for number, rows in self.rows_by_scene().items()
            if len(rows) >= CROWDED_ROW_COUNT
        ]

    def to_plan(self) -> SceneVisualPlan:
        by_number = {s.scene_number: s for s in self.scenes}
        visuals: list[SceneVisual] = []

        for number, rows in self.rows_by_scene().items():
            text = " Then ".join(row.visual.rstrip(". ") + "." for row in rows)

            visuals.append(
                SceneVisual(
                    scene_number=number,
                    text=(
                        text[:MAX_VISUAL_CHARACTERS].rsplit(" ", 1)[0]
                        if len(text) > MAX_VISUAL_CHARACTERS
                        else text
                    ),
                    narration_key=narration_key(by_number[number].narration),
                    row_count=len(rows),
                )
            )

        return SceneVisualPlan(visuals=visuals)


class SceneVisualMatchingService:
    # ---------------------------------------------------------------------- parse

    @staticmethod
    def parse(text: str) -> list[VisualRow]:
        """The rows of a pasted table that carry a visual. Raises ValueError, in plain words,
        when the text is not a table or holds no usable row."""

        lines = [
            line for line in text.replace("\r\n", "\n").split("\n") if line.strip()
        ]

        if not lines:
            raise ValueError("Paste the table first.")

        if any("\t" in line for line in lines):
            separator = "\t"
        elif any("|" in line for line in lines):
            separator = "|"
        else:
            # A table copied from a page can arrive with every cell on its own line.
            stacked = _stacked_pairs(lines)

            if stacked is None:
                raise ValueError(
                    "Paste the table with its columns - narration, then what is on screen "
                    "(copied from the chat, or written with | between the columns)."
                )

            return SceneVisualMatchingService._rows_from(stacked)

        parsed: list[tuple[str, str]] = []

        for line in lines:
            if separator == "|":
                if _MARKDOWN_RULE.fullmatch(line):
                    continue

                cells = [c.strip() for c in line.strip().strip("|").split("|")]
            else:
                cells = [c.strip() for c in line.split("\t")]

            joined = " ".join(cells).lower()

            if "narration" in joined and (
                "on screen" in joined or "visual" in joined or "on-screen" in joined
            ):
                continue

            non_empty = [c for c in cells if c]

            if len(non_empty) == 1 and len(cells) == 1:
                # A cell that wrapped onto its own line continues the previous row's visual.
                if parsed:
                    narration, visual = parsed[-1]
                    parsed[-1] = (narration, f"{visual} {non_empty[0]}".strip())

                continue

            if len(cells) >= 3 and _NUMBER_CELL.fullmatch(cells[0]):
                narration, visual = cells[1], " ".join(c for c in cells[2:] if c)
            elif len(cells) == 2 and _NUMBER_CELL.fullmatch(cells[0]):
                continue  # a number and a narration with no visual column
            else:
                narration, visual = cells[0], " ".join(c for c in cells[1:] if c)

            parsed.append((narration, visual))

        return SceneVisualMatchingService._rows_from(parsed)

    @staticmethod
    def _rows_from(parsed: list[tuple[str, str]]) -> list[VisualRow]:
        rows: list[VisualRow] = []

        for narration, visual in parsed:
            cleaned_visual = " ".join(visual.replace("**", "").split())

            if not narration.strip() or cleaned_visual.lower() in _NO_VISUAL:
                continue

            rows.append(
                VisualRow(
                    index=len(rows) + 1,
                    narration=" ".join(narration.replace("**", "").split()),
                    visual=cleaned_visual,
                )
            )

        if not rows:
            raise ValueError(
                "No row with both a narration and an on-screen description was found."
            )

        return rows

    # ---------------------------------------------------------------------- match

    def match(self, rows: list[VisualRow], scenes: list[Scene]) -> MatchResult:
        ordered = sorted(scenes, key=lambda s: s.scene_number)
        padded = [f" {normalize_text(s.narration)} " for s in ordered]
        pointer = _Pointer()
        results: list[RowResult] = []

        for row in rows:
            results.append(self._place(row, ordered, padded, pointer))

        return MatchResult(results=results, scenes=ordered)

    def _place(
        self,
        row: VisualRow,
        scenes: list[Scene],
        padded: list[str],
        pointer: _Pointer,
    ) -> RowResult:
        whole = normalize_text(row.narration)
        found = self._locate(whole, padded, pointer)

        if found is not None:
            pointer.move(*found)

            return RowResult(
                row=row,
                status=RowStatus.MATCHED,
                scene_numbers=[scenes[found[0]].scene_number],
            )

        sentences = [
            normalize_text(part)
            for part in _SENTENCE_BREAK.split(row.narration)
            if normalize_text(part)
        ]

        if len(sentences) >= 2:
            trial = pointer.copy()
            hits: list[int] = []

            for sentence in sentences:
                hit = self._locate(sentence, padded, trial)

                if hit is not None:
                    trial.move(*hit)
                    hits.append(hit[0])

            if hits:
                pointer.become(trial)
                distinct = sorted({scenes[i].scene_number for i in hits})
                complete = len(hits) == len(sentences)

                if len(distinct) > 1:
                    status = RowStatus.SPANS if complete else RowStatus.PARTIAL
                else:
                    status = RowStatus.MATCHED if complete else RowStatus.PARTIAL

                return RowResult(row=row, status=status, scene_numbers=distinct)

        earlier = any(f" {whole} " in text for text in padded[: pointer.scene])
        nearest, similarity = self._nearest(whole, scenes, pointer.scene)

        return RowResult(
            row=row,
            status=RowStatus.OUT_OF_ORDER if earlier else RowStatus.UNMATCHED,
            nearest_scene=nearest,
            similarity=similarity,
        )

    @staticmethod
    def _locate(
        needle: str, padded: list[str], pointer: _Pointer
    ) -> tuple[int, int] | None:
        """(scene index, offset just after the match) of the first place at or after the pointer
        within the look-ahead window, else None."""

        if not needle:
            return None

        target = f" {needle} "

        for index in range(
            pointer.scene, min(len(padded), pointer.scene + _LOOK_AHEAD_SCENES)
        ):
            start = pointer.offset if index == pointer.scene else 0
            at = padded[index].find(target, start)

            if at >= 0:
                # the trailing space of the match can be the leading space of the next one
                return index, at + len(target) - 1

        return None

    @staticmethod
    def _nearest(
        whole: str, scenes: list[Scene], pointer_scene: int
    ) -> tuple[int | None, float]:
        """The scene sharing the largest share of the row's words (ties go to the scene
        closest to where the last row ended), and that share."""

        words = set(whole.split())

        if not words:
            return None, 0.0

        best_index: int | None = None
        best_key: tuple[float, int] = (0.0, 0)

        for index, scene in enumerate(scenes):
            overlap = len(words & set(normalize_text(scene.narration).split())) / len(
                words
            )
            key = (overlap, -abs(index - pointer_scene))

            if overlap > 0 and (best_index is None or key > best_key):
                best_index, best_key = index, key

        if best_index is None:
            return None, 0.0

        return scenes[best_index].scene_number, round(best_key[0], 2)


class _Pointer:
    """Where the last row ended: a scene index and a character offset inside it."""

    def __init__(self) -> None:
        self.scene = 0
        self.offset = 0

    def move(self, scene: int, offset: int) -> None:
        self.scene = scene
        self.offset = offset

    def copy(self) -> _Pointer:
        clone = _Pointer()
        clone.scene, clone.offset = self.scene, self.offset

        return clone

    def become(self, other: _Pointer) -> None:
        self.scene, self.offset = other.scene, other.offset
