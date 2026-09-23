from __future__ import annotations

from src.models.thumbnail import ThumbnailTextPosition
from src.services.title_card_render_service import TitleCardRenderService


def test_center_position_centers_both_axes() -> None:
    x_expr, y_expr = TitleCardRenderService._position_expressions(
        ThumbnailTextPosition.CENTER
    )

    assert x_expr == "(w-text_w)/2"
    assert y_expr == "(h-text_h)/2"


def test_top_position_keeps_horizontal_center_but_anchors_near_the_top() -> None:
    x_expr, y_expr = TitleCardRenderService._position_expressions(
        ThumbnailTextPosition.TOP
    )

    assert x_expr == "(w-text_w)/2"
    assert "h*0.08" in y_expr
    assert "text_h" not in y_expr


def test_bottom_position_keeps_horizontal_center_but_anchors_near_the_bottom() -> None:
    x_expr, y_expr = TitleCardRenderService._position_expressions(
        ThumbnailTextPosition.BOTTOM
    )

    assert x_expr == "(w-text_w)/2"
    assert "h-text_h" in y_expr


def test_center_left_anchors_to_the_left_safe_margin() -> None:
    x_expr, y_expr = TitleCardRenderService._position_expressions(
        ThumbnailTextPosition.CENTER_LEFT
    )

    assert "w*0.08" in x_expr
    assert "text_w" not in x_expr
    assert y_expr == "(h-text_h)/2"


def test_center_right_anchors_to_the_right_safe_margin() -> None:
    x_expr, y_expr = TitleCardRenderService._position_expressions(
        ThumbnailTextPosition.CENTER_RIGHT
    )

    assert "text_w" in x_expr
    assert "w*0.08" in x_expr
    assert y_expr == "(h-text_h)/2"


def test_fade_alpha_expression_includes_both_fade_in_and_fade_out_when_requested() -> (
    None
):
    expression = TitleCardRenderService._fade_alpha_expression(
        start_seconds=1.2, end_seconds=3.0, fade_out=True
    )

    assert "1.2" in expression
    assert "3.0" in expression
    # Two nested if()s: one for fade-in, one for fade-out.
    assert expression.count("if(") == 2


def test_fade_alpha_expression_omits_fade_out_when_not_requested() -> None:
    expression = TitleCardRenderService._fade_alpha_expression(
        start_seconds=0.0, end_seconds=1.0, fade_out=False
    )

    assert expression.count("if(") == 1


def test_format_number_drops_trailing_zeros_for_whole_numbers() -> None:
    assert TitleCardRenderService._format_number(30.0) == "30"


def test_format_number_keeps_real_fractional_frame_rates() -> None:
    assert TitleCardRenderService._format_number(29.97) == "29.97"
