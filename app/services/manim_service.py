import json
import logging
from anthropic import Anthropic
from typing import Optional

from app.models.schemas import SlideContent, ManimSlide
from app.services.manim_validator import ManimValidator, validator

logger = logging.getLogger(__name__)

# Maximum number of fix attempts for broken code
MAX_FIX_ATTEMPTS = 3

SYSTEM_PROMPT = """You are an expert Manim developer who creates beautiful 3Blue1Brown-style mathematical animations.

Your job: Take a visual description for a slide and generate working Manim Community Edition code that creates that animation.

## MANIM STYLE GUIDELINES

Follow 3Blue1Brown's visual style:
- **Colors**: Use a dark background (default). Primary colors: BLUE, YELLOW, GREEN, RED, WHITE. Use color constants from Manim.
- **Typography**: Use Tex for math, Text for regular text. Keep text minimal and large.
- **Animation**: Smooth animations with Write, FadeIn, Transform, MoveToTarget. Use appropriate run_time (1-3 seconds typically).
- **Layout**: Center important elements. Use arrange(), next_to(), shift() for positioning.
- **Pacing**: Add self.wait() between animations for breathing room.

## CODE REQUIREMENTS

1. Create a single Scene class that inherits from Scene
2. Class name should be descriptive (e.g., `class TransformerAttention(Scene):`)
3. All animation logic goes in the `construct(self)` method
4. Use Manim Community Edition syntax (not ManimGL or old Manim)
5. Import statement should be: `from manim import *`
6. Code must be complete and runnable

## VISUAL TYPES AND APPROACHES

- **diagram**: Use shapes (Rectangle, Circle, Arrow, Line), VGroup for grouping, arrange for layout
- **equation**: Use MathTex for LaTeX equations, TransformMatchingTex for equation morphing
- **graph**: Use Axes, plot methods, dots and lines
- **comparison**: Split screen with VGroup, use side-by-side layout
- **timeline**: Horizontal arrow with labeled points
- **text_reveal**: Write animation for text, maybe with highlights
- **code_walkthrough**: Use Code class or Text with monospace font

## OUTPUT FORMAT

Output ONLY the Python code, no markdown code blocks or explanations. The code should be directly executable.

Example output format:
from manim import *

class SlideTitle(Scene):
    def construct(self):
        # Your animation code here
        title = Text("Example")
        self.play(Write(title))
        self.wait()
"""

FIX_SYSTEM_PROMPT = """You are an expert Manim debugger. Your job is to fix broken Manim code.

You will receive:
1. The original Manim code that has errors
2. A list of specific errors found in the code

Your task:
1. Analyze each error carefully
2. Fix ALL the errors while preserving the original animation intent
3. Return ONLY the corrected Python code, no explanations

Common fixes:
- Syntax errors: Fix typos, missing colons, incorrect indentation
- Import errors: Ensure 'from manim import *' is present
- Name errors: Use correct Manim class/function names (e.g., MathTex not MathTeX)
- Type errors: Ensure correct argument types for Manim functions
- Missing construct: Ensure the Scene class has a construct(self) method

Output ONLY the fixed Python code, nothing else."""


class ManimService:
    def __init__(self, api_key: str, skip_validation: bool = False):
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY not set - manim generation will fail")
        self.api_key = api_key
        self.client = Anthropic(api_key=api_key) if api_key else None
        self.model = "claude-sonnet-4-5-20250929"
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
