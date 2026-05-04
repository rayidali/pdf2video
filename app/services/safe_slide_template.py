"""
Deterministic Manim code template — last-resort fallback.

No LLM in the loop. Given a title + bullet list + colors, returns a
hardcoded Manim Scene that renders a styled "title + 3 bullets fade-in"
slide. Uses only Text + FadeIn + arrange — no MathTex, no 3D, no
randomness, no external assets, nothing that historically breaks Manim
runtime.

If this template ever fails to render on Kodisc, the cause is on
Kodisc's side, not the code.
"""

from typing import Iterable


def _escape(value: str, max_len: int = 80) -> str:
    """Escape a string for safe inclusion as a Python string literal body."""
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
    """Return Manim Python source for a guaranteed-rendering bullet slide.

    Args:
        title: Slide title (will be truncated to fit).
        bullets: Up to 3 bullet point strings.
        class_name: Must match Kodisc's `^[A-Za-z_][A-Za-z0-9_]*$`.
        colors: Optional dict with primary/secondary/background/text hex strings.
        duration_seconds: Approximate target duration (controls trailing wait).
    """
    palette = {
        "primary": "#58C4DD",
        "secondary": "#FC6255",
        "background": "#000000",
        "text": "#FFFFFF",
    }
    if colors:
        palette.update({k: v for k, v in colors.items() if v})

    title_safe = _escape(title or "Slide", max_len=60)
    b1, b2, b3 = _normalize_bullets(bullets, desired=3)
    b1_safe = _escape(b1, max_len=70)
    b2_safe = _escape(b2, max_len=70)
    b3_safe = _escape(b3, max_len=70)

    end_wait = max(1.5, float(duration_seconds) - 4.5)

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

        line1 = Text("• {b1_safe}", color="{palette["text"]}", font_size=34)
        line2 = Text("• {b2_safe}", color="{palette["text"]}", font_size=34)
        line3 = Text("• {b3_safe}", color="{palette["text"]}", font_size=34)

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

        self.play(FadeOut(VGroup(title, bullets_group)), run_time=0.6)
'''
