from __future__ import annotations

from src.models.video_job import VideoJob
from src.pipeline.pipeline_stage import (
    PipelineStageName,
)
from src.pipeline.pipeline_state import (
    PipelineState,
)
from src.pipeline.stage_context import (
    StageContext,
)


def build_context(
    *,
    user_input: dict[str, object] | None = None,
) -> StageContext:
    """Build a minimum valid StageContext."""

    job = VideoJob(
        project_name=("Stage Context User Input Test"),
        channel_name="Mission Channel",
        niche="automation",
        topic=("Execution-scoped user input"),
    )

    state = PipelineState(
        current_stage=(PipelineStageName.RESEARCH),
    )

    return StageContext(
        job=job,
        pipeline_state=state,
        dry_run=True,
        user_input=dict(user_input or {}),
    )


def test_has_user_input_reports_presence() -> None:
    context = build_context(
        user_input={
            "asset_decisions": [
                {
                    "scene_number": 1,
                    "decision": "manual_upload",
                },
            ],
        }
    )

    assert context.has_user_input("asset_decisions") is True

    assert context.has_user_input("missing") is False


def test_get_user_input_does_not_consume() -> None:
    payload = [
        {
            "scene_number": 1,
            "decision": "manual_upload",
        },
    ]

    context = build_context(
        user_input={
            "asset_decisions": payload,
        }
    )

    first = context.get_user_input("asset_decisions")

    second = context.get_user_input("asset_decisions")

    assert first == payload
    assert second == payload

    assert context.has_user_input("asset_decisions") is True


def test_get_user_input_returns_default() -> None:
    context = build_context()

    sentinel = object()

    result = context.get_user_input(
        "missing",
        sentinel,
    )

    assert result is sentinel


def test_consume_user_input_removes_key() -> None:
    payload = {
        "scene_number": 1,
        "decision": "manual_upload",
    }

    context = build_context(
        user_input={
            "asset_decisions": payload,
        }
    )

    consumed = context.consume_user_input("asset_decisions")

    assert consumed == payload

    assert context.has_user_input("asset_decisions") is False

    assert "asset_decisions" not in context.user_input


def test_consumption_is_one_time() -> None:
    context = build_context(
        user_input={
            "asset_decisions": [
                {
                    "scene_number": 1,
                    "decision": "manual_upload",
                },
            ],
        }
    )

    first = context.consume_user_input("asset_decisions")

    second = context.consume_user_input("asset_decisions")

    assert first is not None
    assert second is None


def test_consume_user_input_returns_default() -> None:
    context = build_context()

    sentinel = object()

    result = context.consume_user_input(
        "missing",
        sentinel,
    )

    assert result is sentinel


def test_consuming_one_key_preserves_others() -> None:
    context = build_context(
        user_input={
            "asset_decisions": [
                {
                    "scene_number": 1,
                    "decision": "manual_upload",
                },
            ],
            "approval": {
                "approved": True,
            },
            "notes": "keep me",
        }
    )

    context.consume_user_input("asset_decisions")

    assert "asset_decisions" not in context.user_input

    assert context.user_input["approval"] == {
        "approved": True,
    }

    assert context.user_input["notes"] == "keep me"


def test_user_input_instances_are_independent() -> None:
    first = build_context()

    second = build_context()

    first.user_input["asset_decisions"] = [
        {
            "scene_number": 1,
            "decision": "manual_upload",
        },
    ]

    assert second.user_input == {}


def main() -> None:
    print()
    print("Running Stage Context " "User Input tests...")
    print()

    test_has_user_input_reports_presence()
    test_get_user_input_does_not_consume()
    test_get_user_input_returns_default()
    test_consume_user_input_removes_key()
    test_consumption_is_one_time()
    test_consume_user_input_returns_default()
    test_consuming_one_key_preserves_others()
    test_user_input_instances_are_independent()

    print()
    print("Stage Context User Input tests " "completed successfully.")


if __name__ == "__main__":
    main()
