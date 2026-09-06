from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.script_selection_edit import (
    SelectionEditOperation,
    SelectionEditRequest,
)


def _set(
    *,
    segment_number: int = 1,
    operation: SelectionEditOperation = SelectionEditOperation.REWRITE,
    selected_text: str | None = None,
    custom_instruction: str | None = None,
) -> SelectionEditRequest:
    return SelectionEditRequest(
        segment_number=segment_number,
        operation=operation,
        selected_text=selected_text,
        custom_instruction=custom_instruction,
    )


def test_constructs_with_no_selection() -> None:
    request = _set()

    assert request.selected_text is None
    assert request.custom_instruction is None


def test_constructs_with_a_selection() -> None:
    request = _set(selected_text="the crew vanished")

    assert request.selected_text == "the crew vanished"


def test_selected_text_is_stripped_and_blank_becomes_none() -> None:
    request = _set(selected_text="   ")

    assert request.selected_text is None


def test_custom_operation_requires_a_custom_instruction() -> None:
    with pytest.raises(ValidationError, match="requires a custom_instruction"):
        _set(operation=SelectionEditOperation.CUSTOM)


def test_custom_operation_with_instruction_constructs() -> None:
    request = _set(
        operation=SelectionEditOperation.CUSTOM,
        custom_instruction="Make it sound like a radio broadcast.",
    )

    assert request.custom_instruction == "Make it sound like a radio broadcast."


def test_non_custom_operation_rejects_a_custom_instruction() -> None:
    with pytest.raises(ValidationError, match="only accepted for the CUSTOM"):
        _set(
            operation=SelectionEditOperation.REWRITE,
            custom_instruction="This should not be allowed here.",
        )
