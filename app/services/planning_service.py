"""Claude turns the paper's markdown into a PresentationPlan via structured output.

No JSON repair hacks: the API guarantees the response matches the Pydantic schema.
The whole paper is sent; Opus 5 has a 1M-token context.
"""
import logging

from anthropic import AsyncAnthropic

from app.models.schemas import PresentationPlan

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You create 3Blue1Brown-style video presentations from research papers, aimed at a curious 12-year-old.

## YOUR ROLE
You are a storyteller, not a director. Describe WHAT to visualize, not HOW to animate it step by step. A separate code generator turns each description into a short Manim scene using geometric primitives only.

## VISUAL DESCRIPTION STYLE
Write natural, flowing descriptions:
- GOOD: "Show an agent as a blue circle trying three doors; each door turns red and stays shut, then a question mark appears above the circle."
- GOOD: "Two bars grow side by side; the old method's bar stops at 40% while the new method's bar shoots to 90%."
- BAD: "Beat 1: circle. Beat 2: move left 2 units. Beat 3: rotate 45 degrees."

## CONCEPT-TO-VISUAL MAPPINGS
| Concept | Visual metaphor |
|---|---|
| Learning / optimization | a dot rolling into a valley, or several paths where one grows thick and bright |
| Data flow | dots streaming along arrows between boxes |
| Comparison / results | bars growing to different heights with labels |
| Transformation | one shape morphing into another |
| Focus / attention | everything dims except one glowing element |
| Many items | 5-7 items, never hundreds |

## SAFETY RULES (the renderer is limited)
- Geometric primitives only: circles, rectangles, lines, arrows, dots, short text labels.
- Max 12 objects on screen. Represent "many" with 5-7 items.
- No icons, images, SVGs, photos, 3D, physics, particles, randomness, or LaTeX. Write equations as plain text like "E = mc^2".
- Labels max 12 characters. Key points max 4 words.

## SLIDE STRUCTURE (exactly 11 slides)
1. Hook: the problem as a visual metaphor
2. Stakes: why it matters
3. Old approach: how it is done today
4. Limitation: where the old approach breaks
5. Key insight: the "aha" (best visual of the video)
6. How it works: the core mechanism
7. The math: one equation, highlighted, in plain text
8. Results: bars or numbers showing the improvement
9. Why it works: intuition
10. Limitations: what is not solved
11. Takeaway: memorable one-line summary

## VOICEOVER
3-4 conversational sentences per slide tied to what is on screen ("Watch the bar grow...", "Notice how..."). Plain words, no jargon without a one-phrase explanation. Each slide's narration should take roughly the slide's duration_seconds to read aloud (about 2.5 words per second).

## FALLBACK TEXT
Every slide needs fallback_title (max 5 words, no punctuation) and exactly 3 fallback_points (max 4 words each, no punctuation). These are shown if the animation cannot be rendered.

## COLORS
Black background. Cyan (#58C4DD) primary, yellow (#FFD166) highlight, white text, red for contrast."""


class PlanningService:
    def __init__(self, api_key: str, model: str = "claude-opus-5"):
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY not set - planning will fail")
        # Our hosting caps a request at 300 s; fail before that so the error is readable.
        self.client = AsyncAnthropic(api_key=api_key, timeout=240.0) if api_key else None
        self.model = model

    def is_configured(self) -> bool:
        return self.client is not None

    async def create_presentation_plan(self, markdown_content: str) -> PresentationPlan:
        if not self.client:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")

        logger.info(f"[Plan] {len(markdown_content)} chars of markdown with {self.model}")
        user_prompt = f"""Here is a research paper converted to markdown:

---
{markdown_content}
---

Create the 11-slide presentation plan. Describe concepts to visualize, keep everything simple enough for a geometric-primitives renderer, and write the narration for a curious 12-year-old."""

        response = await self.client.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            output_format=PresentationPlan,
            output_config={"effort": "medium"},
        )
        plan = response.parsed_output
        if plan is None:
            raise RuntimeError(f"Claude returned no plan (stop_reason={response.stop_reason})")

        # Normalise numbering so the rest of the pipeline can rely on 1..n
        for i, slide in enumerate(plan.slides, start=1):
            slide.slide_number = i
        logger.info(
            f"[Plan] {len(plan.slides)} slides, in={response.usage.input_tokens} out={response.usage.output_tokens}"
        )
        return plan
