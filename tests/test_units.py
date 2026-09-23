import ast

from app.services.manim_validator import validate_code
from app.services.safe_slide_template import render_safe_slide_code
from app.services.shotstack_service import ShotstackService, SlideAsset
from tests.conftest import INVALID_CODE, VALID_CODE


def test_validator_accepts_good_code():
    assert validate_code(VALID_CODE.format(cls="Slide001"), "Slide001") == []


def test_validator_flags_bad_code():
    problems = validate_code(INVALID_CODE, "Slide001")
    assert any("[CLASS]" in p for p in problems)
    assert any("LaTeX" in p for p in problems)
    assert any("[SYNTAX]" in p for p in validate_code("def broken(:\n  pass", "X"))


def test_safe_template_is_valid_and_holds_last_frame():
    code = render_safe_slide_code('Title with "quotes"', ["a", "b"], "Slide007", duration_seconds=30)
    ast.parse(code)
    assert validate_code(code, "Slide007") == []
    assert "FadeOut" not in code and code.rstrip().endswith(")")
    assert 'Title with \\"quotes\\"' in code


def test_shotstack_timeline_math():
    slides = [
        SlideAsset(slide_number=2, video_url="v2", audio_url="a2", audio_duration=10.0),
        SlideAsset(slide_number=1, video_url="v1", audio_url="a1", audio_duration=4.5),
        SlideAsset(slide_number=3, video_url="v3", fallback_duration=6.0),
    ]
    tl = ShotstackService.build_timeline(slides)
    audio, video = tl["tracks"]
    assert [c["asset"]["src"] for c in video["clips"]] == ["v1", "v2", "v3"]
    assert [c["start"] for c in video["clips"]] == [0.0, 4.5, 14.5]
    assert [c["length"] for c in video["clips"]] == [4.5, 10.0, 6.0]
    assert len(audio["clips"]) == 2 and audio["clips"][1]["start"] == 4.5
