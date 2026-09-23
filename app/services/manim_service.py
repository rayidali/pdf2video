"""Claude writes Manim scenes. Async client, Opus 5 by default, static validation by the caller."""
import logging

from anthropic import AsyncAnthropic

from app.models.schemas import ManimSlide, SlideContent
from app.services.manim_validator import format_error_report

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert Manim Community Edition developer. You produce code that renders successfully on the FIRST try on a remote Manim render farm. Reliability beats sophistication.

## OUTPUT FORMAT
Output ONLY raw Python code. No markdown fences, no prose, no explanations. The first line must be `from manim import *`.

## CODE STRUCTURE (NON-NEGOTIABLE)
1. Single `from manim import *` import.
2. Exactly one class inheriting from `Scene`. Use the EXACT class name the user specifies (e.g., `Slide001`).
3. All animation logic inside `def construct(self):`.
4. Set background explicitly at the top of construct: `self.camera.background_color = "#000000"`.
5. End with `self.wait(1.5)` with everything still on screen. NEVER fade out, clear, or remove the final objects. The last frame is held on screen while the narrator finishes speaking, so it must be the complete, meaningful final state of the slide.

## HARD BANS (these break renders)
- DO NOT use `MathTex`, `Tex`, or any LaTeX. No exceptions. Render math with `Text("a^2 + b^2 = c^2")`.
- DO NOT use 3D scenes, `ThreeDScene`, `ThreeDAxes`, camera rotation, or `MovingCameraScene`.
- DO NOT use `Code`, `ImageMobject`, `SVGMobject`, or any external asset.
- DO NOT use `random`, `numpy.random`, physics simulation, collision detection, or `always_redraw` with stateful closures.
- DO NOT define helper classes other than the one Scene class.
- DO NOT use f-strings inside `Text(...)`. Pre-build the string in a variable.

## ALLOWED PRIMITIVES
- Mobjects: `Text`, `Circle`, `Rectangle`, `Square`, `RoundedRectangle`, `Line`, `Arrow`, `DoubleArrow`, `Dot`, `VGroup`, `Axes`, `NumberLine`.
- Animations: `FadeIn`, `FadeOut` (only for intermediate elements, never the final state), `Write`, `Create`, `Transform`, `ReplacementTransform`, `GrowArrow`, `GrowFromCenter`, `Indicate`, `.animate`.
- Layout: `.to_edge(UP/DOWN/LEFT/RIGHT, buff=...)`, `.next_to(other, DOWN, buff=...)`, `.move_to(...)`, `.shift(...)`, `VGroup(...).arrange(DOWN, buff=...)`, `.scale(...)`.

## SAFETY RULES
- Stay inside the visible frame: x in [-6.5, 6.5], y in [-3.5, 3.5]. Prefer `.to_edge` and `.arrange` over absolute coordinates.
- Cap total mobjects at 14.
- Cap text at 60 characters per Text mobject; split long ideas across lines.
- Use hex color strings ("#58C4DD") or Manim constants (BLUE, YELLOW, GREEN, RED, WHITE, GRAY). NEVER bare strings like "blue".
- Use `font_size=` for Text. 32-40 for body, 52-56 for titles.
- Total animation 8-15 seconds of motion, then hold.
- Never reference a variable before assigning it. Every animated mobject must first be added via `self.add` or a `self.play(Create/Write/FadeIn(...))`.

## STYLE
- Black background, primary color #58C4DD (cyan), accent #FFD166 (yellow), white body text.
- Title at top via `.to_edge(UP, buff=0.7)`. Body content centered or grouped via `VGroup(...).arrange(DOWN)`.
- Smooth `run_time` 0.4-0.8s per animation, with `self.wait(0.3)` between for pacing.
- Show the concept visually (shapes, arrows, growth, transformation). Key points appear as short labels, not paragraphs.

## EXAMPLE (mirror this structure)
from manim import *

class ExampleSlide(Scene):
    def construct(self):
        self.camera.background_color = "#000000"
        title = Text("Concept Name", color="#58C4DD", font_size=54, weight=BOLD).to_edge(UP, buff=0.7)
        box_a = RoundedRectangle(width=3, height=1.4, color="#58C4DD").shift(LEFT * 3)
        box_b = RoundedRectangle(width=3, height=1.4, color="#FFD166").shift(RIGHT * 3)
        label_a = Text("Old way", font_size=32).move_to(box_a)
        label_b = Text("New way", font_size=32).move_to(box_b)
        arrow = Arrow(box_a.get_right(), box_b.get_left(), color=WHITE)
        note = Text("3x faster", color="#FFD166", font_size=36).next_to(arrow, DOWN, buff=0.6)

        self.play(FadeIn(title, shift=DOWN * 0.2), run_time=0.5)
        self.play(Create(box_a), Write(label_a), run_time=0.7)
        self.wait(0.3)
        self.play(GrowArrow(arrow), run_time=0.6)
        self.play(Create(box_b), Write(label_b), run_time=0.7)
        self.wait(0.3)
        self.play(FadeIn(note, shift=UP * 0.2), run_time=0.5)
        self.wait(1.5)
"""

FIX_SYSTEM_PROMPT = """You are an expert Manim Community Edition debugger. Fix broken Manim code so it renders successfully on a remote render farm.

You will receive the original code and either static-analysis problems or a runtime error reported by the renderer.

Rules:
1. Return ONLY the corrected Python code. No markdown fences, no prose.
2. The first line must be `from manim import *`.
3. Preserve the EXACT class name from the original code.
4. If the error mentions LaTeX/MathTex/Tex, replace every `MathTex(...)` and `Tex(...)` with plain `Text(...)`. LaTeX is unavailable on the renderer.
5. Strip any `Code`, `ImageMobject`, `SVGMobject`, `ThreeDScene`, `MovingCameraScene`, `random`, `numpy.random` usages. Replace with `Text`/`Rectangle`/`VGroup` equivalents.
6. Keep all elements within x in [-6.5, 6.5] and y in [-3.5, 3.5].
7. Ensure every animated mobject was added via `self.play(Create/FadeIn/Write(...))` or `self.add(...)` before being transformed.
8. End the construct method with `self.wait(1.5)` and everything still on screen. Do not fade out or clear the final frame.
9. Do not introduce helper classes. Single Scene only. Simplify aggressively if that is what it takes to render.

Output ONLY the corrected Python code."""


def _text_of(response) -> str:
    """Concatenate text blocks; thinking blocks may precede them on Opus 5."""
    return "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", "") == "text")


def clean_code(response_text: str) -> str:
    code = response_text.strip()
    if code.startswith("```python"):
        code = code[9:]
    elif code.startswith("```"):
        code = code[3:]
    if code.endswith("```"):
        code = code[:-3]
    code = code.strip()
    if not code.startswith("from manim import"):
        code = "from manim import *\n\n" + code
    return code


class ManimService:
    def __init__(self, api_key: str, model: str = "claude-opus-5"):
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY not set - Manim generation will fail")
        self.client = AsyncAnthropic(api_key=api_key) if api_key else None
        self.model = model

    def is_configured(self) -> bool:
        return self.client is not None

    async def generate_slide_code(self, slide: SlideContent, paper_title: str, paper_summary: str) -> ManimSlide:
        if not self.client:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")
        class_name = f"Slide{slide.slide_number:03d}"
        points = "\n".join(f"- {p}" for p in slide.key_points)
        user_prompt = f"""Generate Manim code for this slide.

**Paper Context:**
- Title: {paper_title}
- Summary: {paper_summary}

**Slide {slide.slide_number}: {slide.title}**
- Visual Type: {slide.visual_type.value}
- Narration length: about {slide.duration_seconds} seconds (the final frame is held for the remainder)

**Visual Description:**
{slide.visual_description}

**Key Points to show as short labels:**
{points}

**Voiceover (for reference only):**
{slide.voiceover_script}

The class name must be `{class_name}`. Animate for 8-15 seconds, then hold the complete final frame with `self.wait(1.5)`."""

        logger.info(f"[Manim] generating {class_name} with {self.model}")
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        code = clean_code(_text_of(response))
        logger.info(f"[Manim] {class_name}: {len(code)} chars, in={response.usage.input_tokens} out={response.usage.output_tokens}")
        return ManimSlide(
            slide_number=slide.slide_number,
            class_name=class_name,
            manim_code=code,
            expected_duration=float(slide.duration_seconds),
        )

    async def fix_code(self, code: str, errors: list[str], class_name: str) -> str:
        if not self.client:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")
        prompt = f"Fix the following Manim code. The class name must be `{class_name}`.\n\n{format_error_report(code, errors)}\nReturn ONLY the corrected Python code."
        logger.info(f"[Manim] requesting fix for {class_name}")
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=8000,
            system=FIX_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        fixed = clean_code(_text_of(response))
        logger.info(f"[Manim] fix for {class_name}: {len(fixed)} chars")
        return fixed
