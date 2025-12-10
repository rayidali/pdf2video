import json
import logging
from anthropic import Anthropic
from typing import Optional

from app.models.schemas import SlideContent, ManimSlide

logger = logging.getLogger(__name__)

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


class ManimService:
    def __init__(self, api_key: str):
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY not set - manim generation will fail")
        self.api_key = api_key
        self.client = Anthropic(api_key=api_key) if api_key else None
        self.model = "claude-sonnet-4-5-20250929"

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

        # Clean up response - remove markdown code blocks if present
        code = response_text.strip()
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

        return ManimSlide(
            slide_number=slide.slide_number,
            class_name=f"Slide{slide.slide_number:03d}",
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
