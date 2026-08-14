from __future__ import annotations

from src.models.approval import ApprovalPolicy, ApprovalState
from src.models.content_decision_record import ContentDecisionRecord
from src.models.video_job import VideoJob
from src.services.approval_service import ApprovalService

# --- Basic construction ---

record = ContentDecisionRecord(
    stage="Research",
    summary="Generated research for 'Ancient Rome'.",
    provider_name="openai",
    model="gpt-4o",
    cost_usd=0.02,
)

assert record.stage == "research"
assert record.summary == "Generated research for 'Ancient Rome'."
assert record.cost_usd == 0.02
assert record.approval is None


# --- Field normalization / validation ---

try:
    ContentDecisionRecord(stage="   ", summary="anything")
except ValueError:
    print("Empty stage successfully blocked.")
else:
    raise AssertionError("Empty stage should fail.")

try:
    ContentDecisionRecord(stage="research", summary="   ")
except ValueError:
    print("Empty summary successfully blocked.")
else:
    raise AssertionError("Empty summary should fail.")

try:
    ContentDecisionRecord(stage="research", summary="x", cost_usd=-1.0)
except ValueError:
    print("Negative cost successfully blocked.")
else:
    raise AssertionError("Negative cost should fail.")


# --- Carrying an approval decision ---

approval_service = ApprovalService()

decision = approval_service.open_decision(
    decision_point="research",
    policy=ApprovalPolicy.AUTO,
    confidence=0.95,
)

record_with_approval = ContentDecisionRecord(
    stage="research",
    summary="Generated and auto-approved research.",
    approval=decision,
)

assert record_with_approval.approval is not None
assert record_with_approval.approval.state == ApprovalState.APPROVED


# --- VideoJob: append-only audit trail alongside single-slot fields ---

job = VideoJob(
    project_name="Mission",
    channel_name="Demo",
    niche="History",
    topic="Ancient Rome",
)

assert job.content_decisions == []

job.content_decisions.append(record)
job.content_decisions.append(record_with_approval)

assert len(job.content_decisions) == 2
assert job.content_decisions[0].stage == "research"

# Re-running a stage overwrites the single-slot field, exactly as
# before, but the audit trail below is what preserves the fact a
# prior attempt happened - this is the whole point of the record.
job.research = None

assert job.research is None
assert len(job.content_decisions) == 2


# --- Serialization round-trip through VideoJob (matters for JsonJobStore) ---

dumped = job.model_dump(mode="json")
restored = VideoJob.model_validate(dumped)

assert len(restored.content_decisions) == 2
assert restored.content_decisions[1].approval is not None
assert restored.content_decisions[1].approval.state == ApprovalState.APPROVED


print("Content Decision Record tests completed successfully.")
