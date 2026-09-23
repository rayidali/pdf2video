"""
Deterministic Manim slide: the last-resort fallback (tier 3).

No LLM. Title plus three bullets, Text + FadeIn only. The scene ends on its final
composed frame and never fades out, because Shotstack holds the last frame under the
voiceover; a fade-out would leave a black freeze.
"""
from typing import Iterable


def _escape(value: str, max_len: int = 80) -> str:
    if not isinstance(value, str):
        value = str(value)
    cleaned = value.replace("\r", " ").replace("\n", " ").strip()
    cleaned = cleaned.replace("\\", "\\\\").replace('"', '\\"')
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 1].rstrip() + "…"
    return cleaned


def _normalize_bullets(bullets: Iterable[str], desired: int = 3) -> list[str]:
    out: list[str] = []
    for b in bullets or []:
        if not b:
            continue
        out.append(str(b).strip())
        if len(out) == desired:
            break
    while len(out) < desired:
        out.append("")
    return out


def render_safe_slide_code(
    title: str,
    bullets: Iterable[str],
    class_name: str,
    colors: dict | None = None,
    duration_seconds: float = 6.0,
) -> str:
    palette = {"primary": "#58C4DD", "secondary": "#FC6255", "background": "#000000", "text": "#FFFFFF"}
    if colors:
        palette.update({k: v for k, v in colors.items() if v})

    title_safe = _escape(title or "Slide", max_len=60)
    b1, b2, b3 = (_escape(b, max_len=70) for b in _normalize_bullets(bullets, desired=3))
    end_wait = max(1.5, min(float(duration_seconds), 12.0) - 3.0)

    return f'''from manim import *


class {class_name}(Scene):
    def construct(self):
        self.camera.background_color = "{palette["background"]}"

        title = Text(
            "{title_safe}",
            color="{palette["primary"]}",
            font_size=52,
            weight=BOLD,
        )
        title.to_edge(UP, buff=0.9)
        self.play(FadeIn(title, shift=DOWN * 0.3), run_time=0.6)
        self.wait(0.3)

        line1 = Text("• {b1}", color="{palette["text"]}", font_size=34)
        line2 = Text("• {b2}", color="{palette["text"]}", font_size=34)
        line3 = Text("• {b3}", color="{palette["text"]}", font_size=34)

        bullets_group = VGroup(line1, line2, line3).arrange(
            DOWN, aligned_edge=LEFT, buff=0.55
        )
        bullets_group.next_to(title, DOWN, buff=1.0)

        self.play(FadeIn(line1, shift=RIGHT * 0.2), run_time=0.5)
        self.wait(0.4)
        self.play(FadeIn(line2, shift=RIGHT * 0.2), run_time=0.5)
        self.wait(0.4)
        self.play(FadeIn(line3, shift=RIGHT * 0.2), run_time=0.5)
        self.wait({end_wait:.2f})
'''
