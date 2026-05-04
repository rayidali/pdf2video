import json
import logging
from anthropic import Anthropic
from typing import Optional

from app.models.schemas import SlideContent, ManimSlide
from app.services.manim_validator import ManimValidator, validator

logger = logging.getLogger(__name__)

# Maximum number of static-validator fix attempts.
# Render-time retries happen at the orchestration layer (see main.py), so
# keep this small to avoid burning latency on the LLM round-trip.
MAX_FIX_ATTEMPTS = 1

SYSTEM_PROMPT = """You are an expert Manim Community Edition developer. You produce code that renders successfully on the FIRST try on a remote Manim render farm. Reliability beats sophistication.

## OUTPUT FORMAT
Output ONLY raw Python code. No markdown fences, no prose, no explanations. The first line must be `from manim import *`.

## CODE STRUCTURE (NON-NEGOTIABLE)
1. Single `from manim import *` import.
2. Exactly one class inheriting from `Scene`. Use the EXACT class name the user specifies (e.g., `Slide001`).
3. All animation logic inside `def construct(self):`.
4. Set background explicitly at the top of construct: `self.camera.background_color = "#000000"`.
5. End with `self.wait(1.0)` then `self.play(FadeOut(<group_of_everything>), run_time=0.5)`.

## HARD BANS (these break renders)
- DO NOT use `MathTex`, `Tex`, or any LaTeX. No exceptions — even for math, render it with `Text("a^2 + b^2 = c^2")`.
- DO NOT use 3D scenes, `ThreeDScene`, `ThreeDAxes`, camera rotation.
- DO NOT use `Code`, `ImageMobject`, `SVGMobject`, `MovingCamera`, or any external asset.
- DO NOT use `numpy.random`, `random`, physics simulation, collision detection, or `always_redraw` with stateful closures.
- DO NOT define helper classes other than the one Scene class.
- DO NOT use f-strings inside `Text(...)` — pre-build the string in a variable.

## ALLOWED PRIMITIVES (use these)
- Mobjects: `Text`, `Circle`, `Rectangle`, `Square`, `Line`, `Arrow`, `DoubleArrow`, `Dot`, `VGroup`, `Axes`, `NumberLine`.
- Animations: `FadeIn`, `FadeOut`, `Write`, `Create`, `Transform`, `ReplacementTransform`, `GrowArrow`, `GrowFromCenter`, `Indicate`.
- Layout: `.to_edge(UP/DOWN/LEFT/RIGHT, buff=...)`, `.next_to(other, DOWN, buff=...)`, `.move_to(...)`, `.shift(...)`, `VGroup(...).arrange(DOWN, buff=...)`, `.scale(...)`.

## SAFETY RULES
- Stay inside the visible frame: x in [-6.5, 6.5], y in [-3.5, 3.5]. Use `.to_edge` and `.arrange` rather than absolute coordinates when possible.
- Cap total mobjects at 12.
- Cap text content at 80 chars per Text mobject.
- Use hex color strings ("#58C4DD") OR Manim color constants (BLUE, YELLOW, GREEN, RED, WHITE, GRAY) — NEVER bare strings like "blue".
- Use `font_size=` (not `size=`) for Text. Default 36–48 for body, 56 for titles.
- Total animation 6–10 seconds.
- Never reference a variable before assigning it.
- Every mobject you animate must have been added with `self.add` or via a `self.play(Create/Write/FadeIn(...))` first.

## STYLE
- Black background, primary color #58C4DD (cyan), white body text.
- Title at top via `.to_edge(UP, buff=0.7)`. Body content centered or grouped via `VGroup(...).arrange(DOWN)`.
- Smooth `run_time` 0.4–0.8s per animation, with `self.wait(0.3)` between for pacing.

## EXAMPLE (mirror this structure exactly)
from manim import *

class ExampleSlide(Scene):
    def construct(self):
        self.camera.background_color = "#000000"
        title = Text("Concept Name", color="#58C4DD", font_size=54, weight=BOLD).to_edge(UP, buff=0.7)
        body = VGroup(
            Text("First key idea", color=WHITE, font_size=36),
            Text("Second key idea", color=WHITE, font_size=36),
            Text("Third key idea", color=WHITE, font_size=36),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.5).next_to(title, DOWN, buff=1.0)

        self.play(FadeIn(title, shift=DOWN*0.2), run_time=0.5)
        for line in body:
            self.play(FadeIn(line, shift=RIGHT*0.2), run_time=0.5)
            self.wait(0.3)
        self.wait(2.0)
        self.play(FadeOut(VGroup(title, body)), run_time=0.5)
"""

FIX_SYSTEM_PROMPT = """You are an expert Manim Community Edition debugger. Fix broken Manim code so it renders successfully on a remote render farm.

You will receive the original code and either a list of static errors or a runtime/render error from Manim itself.

Rules:
1. Return ONLY the corrected Python code. No markdown fences, no prose.
2. The first line must be `from manim import *`.
3. Preserve the EXACT class name from the original code.
4. If the error mentions LaTeX/MathTex/Tex, REPLACE all `MathTex(...)` and `Tex(...)` calls with plain `Text(...)`. LaTeX is unavailable on the renderer.
5. Strip any `Code`, `ImageMobject`, `SVGMobject`, `ThreeDScene`, `numpy.random`, `random` usages — replace with `Text`/`Rectangle`/`VGroup` equivalents.
6. Keep all elements within x in [-6.5, 6.5] and y in [-3.5, 3.5].
7. Ensure every animated mobject was added via `self.play(Create/FadeIn/Write(...))` or `self.add(...)` before being transformed.
8. End the construct method with `self.wait(1.0)` followed by `self.play(FadeOut(...))`.
9. Do not introduce helper classes. Single Scene only.

Output ONLY the corrected Python code."""


class ManimService:
    def __init__(self, api_key: str, skip_validation: bool = False):
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY not set - manim generation will fail")
        self.api_key = api_key
        self.client = Anthropic(api_key=api_key) if api_key else None
        self.model = "claude-opus-4-7"
        self.validator = validator
        self.skip_validation = skip_validation

    def _clean_code(self, response_text: str) -> str:
        """Clean up Claude's response to extract pure Python code."""
        code = response_text.strip()

        # Remove markdown code blocks if present
        if code.startswith("```python"):
            code = code[9:]
        elif code.startswith("```"):
            code = code[3:]
        if code.endswith("```"):
            code = code[:-3]
        code = code.strip()

        # Ensure the code starts with the import
        if not code.startswith("from manim import"):
            code = "from manim import *\n\n" + code

        return code

    def _request_fix(self, code: str, errors: list[str], expected_class: str) -> str:
        """Request Claude to fix broken code."""
        error_report = self.validator.format_error_report(code, errors)

        fix_prompt = f"""Fix the following Manim code. The class name must be `{expected_class}`.

{error_report}

Return ONLY the corrected Python code."""

        logger.info(f"Requesting code fix from Claude...")

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            messages=[
                {"role": "user", "content": fix_prompt}
            ],
            system=FIX_SYSTEM_PROMPT
        )

        fixed_code = self._clean_code(response.content[0].text)
        logger.info(f"Received fixed code ({len(fixed_code)} chars)")
        logger.info(f"Fix token usage - Input: {response.usage.input_tokens}, Output: {response.usage.output_tokens}")

        return fixed_code

    def _validate_and_fix(
        self,
        code: str,
        expected_class: str,
        max_attempts: int = MAX_FIX_ATTEMPTS
    ) -> tuple[str, bool, list[str]]:
        """
        Validate code and attempt to fix if errors are found.

        Returns:
            (final_code, is_valid, remaining_errors)
        """
        # Skip validation if disabled (for testing without manim installed)
        if self.skip_validation:
            logger.info("Validation skipped (skip_validation=True)")
            return code, True, []

        for attempt in range(max_attempts + 1):
            # Validate the code (skip import check since manim may not be installed in API server)
            is_valid, errors = self.validator.validate(
                code,
                expected_class,
                skip_import_check=True  # Server likely doesn't have manim installed
            )

            if is_valid:
                if attempt > 0:
                    logger.info(f"Code fixed successfully after {attempt} attempt(s)")
                return code, True, []

            logger.warning(f"Validation failed (attempt {attempt + 1}/{max_attempts + 1}): {errors}")

            # If we've exhausted fix attempts, return with errors
            if attempt >= max_attempts:
                logger.error(f"Failed to fix code after {max_attempts} attempts")
                return code, False, errors

            # Request a fix from Claude
            code = self._request_fix(code, errors, expected_class)

        return code, False, errors

    async def generate_slide_code(
        self,
        slide: SlideContent,
        paper_title: str,
        paper_summary: str
    ) -> ManimSlide:
        """
        Generate Manim code for a single slide based on its visual description.
        """
        if not self.client:
            raise ValueError("ANTHROPIC_API_KEY not configured.")

        slide_id = f"s{slide.slide_number:03d}"
        logger.info(f"Generating Manim code for slide {slide_id}: {slide.title}")

        user_prompt = f"""Generate Manim code for this slide:

**Paper Context:**
- Title: {paper_title}
- Summary: {paper_summary}

**Slide {slide.slide_number}: {slide.title}**
- Visual Type: {slide.visual_type.value}
- Duration: {slide.duration_seconds} seconds

**Visual Description:**
{slide.visual_description}

**Key Points to Visualize:**
{chr(10).join(f"- {point}" for point in slide.key_points)}

**Voiceover (for timing reference):**
{slide.voiceover_script}

Generate complete, working Manim code for this slide. The class name should be `Slide{slide.slide_number:03d}` (e.g., Slide001, Slide002).
Make the animation approximately {slide.duration_seconds} seconds long using appropriate self.wait() calls."""

        logger.info(f"Sending request to Claude for slide {slide_id}...")

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            messages=[
                {"role": "user", "content": user_prompt}
            ],
            system=SYSTEM_PROMPT
        )

        response_text = response.content[0].text
        logger.info(f"Received Manim code for slide {slide_id} ({len(response_text)} chars)")
        logger.info(f"Token usage - Input: {response.usage.input_tokens}, Output: {response.usage.output_tokens}")

        # Clean up the response
        code = self._clean_code(response_text)
        expected_class = f"Slide{slide.slide_number:03d}"

        # Validate and fix if needed
        code, is_valid, errors = self._validate_and_fix(code, expected_class)

        if not is_valid:
            logger.error(f"Slide {slide_id} has validation errors that could not be fixed: {errors}")
            # Still return the code, but log the warning
            # The code may still work at runtime even if static validation fails

        return ManimSlide(
            slide_number=slide.slide_number,
            class_name=expected_class,
            manim_code=code,
            expected_duration=float(slide.duration_seconds)
        )

    async def generate_all_slides(
        self,
        slides: list[SlideContent],
        paper_title: str,
        paper_summary: str
    ) -> list[ManimSlide]:
        """
        Generate Manim code for all slides sequentially.
        """
        logger.info(f"Starting Manim code generation for {len(slides)} slides...")

        manim_slides = []
        for slide in slides:
            try:
                manim_slide = await self.generate_slide_code(slide, paper_title, paper_summary)
                manim_slides.append(manim_slide)
                logger.info(f"Successfully generated code for slide {slide.slide_number}")
            except Exception as e:
                logger.error(f"Failed to generate code for slide {slide.slide_number}: {e}")
                raise

        logger.info(f"Completed Manim code generation for all {len(manim_slides)} slides")
        return manim_slides
