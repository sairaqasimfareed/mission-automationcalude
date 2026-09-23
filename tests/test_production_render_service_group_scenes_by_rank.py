"""
REQ-12 (top10 countdown rank cards), 2026-09-23: pure unit coverage of
ProductionRenderService._group_scenes_by_rank() - the contiguous-run
grouping render_top10_countdown() relies on to know where each rank
card belongs. Real end-to-end splicing is covered separately by
test_production_render_service_top10_countdown_real_ffmpeg.py.
"""

from __future__ import annotations

from src.services.production_render_service import ProductionRenderService


def test_groups_a_leading_unranked_hook_separately_from_ranked_scenes() -> None:
    groups = ProductionRenderService._group_scenes_by_rank(
        scene_numbers=[1, 2, 3, 4],
        rank_by_scene_number={3: 10, 4: 10},
    )

    assert groups == [
        (None, [1, 2]),
        (10, [3, 4]),
    ]


def test_adjacent_different_ranks_never_merge() -> None:
    groups = ProductionRenderService._group_scenes_by_rank(
        scene_numbers=[1, 2, 3],
        rank_by_scene_number={1: 10, 2: 9, 3: 9},
    )

    assert groups == [
        (10, [1]),
        (9, [2, 3]),
    ]


def test_no_ranked_scenes_produces_one_unranked_group() -> None:
    groups = ProductionRenderService._group_scenes_by_rank(
        scene_numbers=[1, 2],
        rank_by_scene_number={},
    )

    assert groups == [(None, [1, 2])]


def test_every_scene_individually_ranked_produces_one_group_per_scene() -> None:
    groups = ProductionRenderService._group_scenes_by_rank(
        scene_numbers=[1, 2, 3],
        rank_by_scene_number={1: 10, 2: 9, 3: 8},
    )

    assert groups == [
        (10, [1]),
        (9, [2]),
        (8, [3]),
    ]
