from __future__ import annotations

from pydantic import ValidationError

from src.pipeline.pipeline_resume_plan import (
    PipelineResumePlan,
)
from src.pipeline.pipeline_stage import (
    PipelineStageName,
)


def test_disabled_plan() -> None:
    plan = PipelineResumePlan(
        resume_enabled=False,
        execution_stages=[
            PipelineStageName.VOICE,
            PipelineStageName.RENDER,
        ],
    )

    assert plan.resume_enabled is False
    assert plan.resume_stage is None
    assert plan.skipped_stages == []


def test_enabled_plan() -> None:
    plan = PipelineResumePlan(
        resume_enabled=True,
        resume_stage=(PipelineStageName.RENDER),
        skipped_stages=[
            PipelineStageName.VOICE,
        ],
        execution_stages=[
            PipelineStageName.RENDER,
        ],
        checkpoint_stage=(PipelineStageName.RENDER),
        resumed_from_failure=True,
    )

    assert plan.resume_enabled is True

    assert plan.resume_stage == PipelineStageName.RENDER

    assert plan.resumed_from_failure is True


def test_disabled_plan_rejects_resume_stage() -> None:
    try:
        PipelineResumePlan(
            resume_enabled=False,
            resume_stage=(PipelineStageName.RENDER),
            execution_stages=[
                PipelineStageName.RENDER,
            ],
        )
    except ValidationError as error:
        assert "Disabled resume plan" in str(error)
    else:
        raise AssertionError("Disabled plan with resume " "stage must fail.")


def test_resume_origins_are_mutually_exclusive() -> None:
    try:
        PipelineResumePlan(
            resume_enabled=True,
            resume_stage=(PipelineStageName.RENDER),
            execution_stages=[
                PipelineStageName.RENDER,
            ],
            resumed_from_failure=True,
            resumed_from_waiting=True,
        )
    except ValidationError as error:
        assert "failure and waiting-for-user" in str(error)
    else:
        raise AssertionError("Contradictory resume origin " "must fail.")


def test_resume_stage_must_be_executed() -> None:
    try:
        PipelineResumePlan(
            resume_enabled=True,
            resume_stage=(PipelineStageName.RENDER),
            execution_stages=[
                PipelineStageName.VOICE,
            ],
        )
    except ValidationError as error:
        assert "must appear in execution stages" in str(error)
    else:
        raise AssertionError("Resume stage outside execution " "set must fail.")


def test_skip_execute_overlap_rejected() -> None:
    try:
        PipelineResumePlan(
            resume_enabled=True,
            resume_stage=(PipelineStageName.RENDER),
            skipped_stages=[
                PipelineStageName.VOICE,
            ],
            execution_stages=[
                PipelineStageName.VOICE,
                PipelineStageName.RENDER,
            ],
        )
    except ValidationError as error:
        assert "both skip and execute" in str(error)
    else:
        raise AssertionError("Skip/execution overlap must fail.")


def main() -> None:
    print()
    print("Running Pipeline Resume Plan tests...")
    print()

    test_disabled_plan()
    test_enabled_plan()
    test_disabled_plan_rejects_resume_stage()
    test_resume_origins_are_mutually_exclusive()
    test_resume_stage_must_be_executed()
    test_skip_execute_overlap_rejected()

    print()
    print("Pipeline Resume Plan tests " "completed successfully.")


if __name__ == "__main__":
    main()
