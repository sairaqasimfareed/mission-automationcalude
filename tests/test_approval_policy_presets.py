from __future__ import annotations

from src.models.approval import ApprovalPolicy, ApprovalPolicyConfig

# ApprovalPolicyConfig also carries its own id/created_at/updated_at
# (MissionBaseModel) - two independently-constructed instances with
# identical AUTO/REVIEW/MANUAL fields are never `==` because of those,
# so preset-equivalence comparisons here go through this instead.
_BASE_FIELDS = {"id", "created_at", "updated_at"}


def _fields(policy: ApprovalPolicyConfig) -> dict[str, object]:
    return policy.model_dump(exclude=_BASE_FIELDS)


_ALL_DECISION_POINTS = (
    "topic",
    "content_strategy",
    "research",
    "story_angle",
    "narrative_architecture",
    "hook",
    "final_script",
    "production_plan",
    "budget",
    "final_preview",
    "publishing",
)


def test_full_auto_sets_every_decision_point_to_auto() -> None:
    policy = ApprovalPolicyConfig.full_auto()

    for decision_point in _ALL_DECISION_POINTS:
        assert policy.policy_for(decision_point) == ApprovalPolicy.AUTO


def test_manual_editorial_sets_every_decision_point_to_manual() -> None:
    policy = ApprovalPolicyConfig.manual_editorial()

    for decision_point in _ALL_DECISION_POINTS:
        assert policy.policy_for(decision_point) == ApprovalPolicy.MANUAL


def test_review_critical_stages_matches_the_conservative_default() -> None:
    policy = ApprovalPolicyConfig.review_critical_stages()

    assert _fields(policy) == _fields(ApprovalPolicyConfig())
    assert policy.publishing == ApprovalPolicy.MANUAL
    assert policy.story_angle == ApprovalPolicy.REVIEW
    assert policy.narrative_architecture == ApprovalPolicy.REVIEW
    assert policy.topic == ApprovalPolicy.AUTO


def test_the_three_presets_are_mutually_distinct() -> None:
    presets = [
        ApprovalPolicyConfig.full_auto(),
        ApprovalPolicyConfig.review_critical_stages(),
        ApprovalPolicyConfig.manual_editorial(),
    ]

    for first, second in ((0, 1), (0, 2), (1, 2)):
        assert _fields(presets[first]) != _fields(presets[second])


def test_new_decision_points_default_consistently_with_neighboring_stages() -> None:
    default_policy = ApprovalPolicyConfig()

    # content_strategy is a cheap early step, matching topic/research.
    assert default_policy.content_strategy == ApprovalPolicy.AUTO
    # narrative_architecture is a structural creative decision,
    # matching story_angle/final_script.
    assert default_policy.narrative_architecture == ApprovalPolicy.REVIEW
