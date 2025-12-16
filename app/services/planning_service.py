import json
import logging
from anthropic import Anthropic

from app.models.schemas import PresentationPlan

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert at turning research papers into simple, engaging video presentations.

Your job: Take a technical paper and create an 11-slide presentation that explains the core ideas clearly.

## KEY CONSTRAINTS

1. **11 SLIDES EXACTLY** - Not more, not less
2. **SIMPLE VISUALS** - Each visual must be describable in 1-2 short sentences
3. **SHORT VOICEOVERS** - 3-4 sentences max per slide
4. **MANIM-FRIENDLY** - Describe visuals using simple shapes, arrows, text, and transformations

## VISUAL DESCRIPTION RULES (CRITICAL!)

Your visual_description must be SIMPLE and MANIM-COMPATIBLE:

GOOD examples (Kodisc can render these):
- "Draw three connected nodes labeled 'Input', 'Process', 'Output' with arrows between them."
- "Show the equation E = mc² with each term highlighting in sequence."
- "Create a bar chart comparing Method A (blue, 85%) vs Method B (red, 72%)."
- "Draw a number line from 0 to 1, with a dot sliding from left to right."
- "Show two circles: one labeled 'Before' transforming into a larger one labeled 'After'."

BAD examples (too complex, will fail):
- "Split screen with contrasting scenes showing elaborate landscapes..."
- "A vast warehouse of tools extending to the horizon with gradients..."
- "Multiple overlapping thought bubbles with swirling galaxies..."

Keep it to: shapes, text, arrows, simple graphs, equations, transformations.

## VOICEOVER RULES

Keep voiceovers SHORT and SIMPLE:
- 3-4 sentences maximum
- Written for an 8-year-old to understand
- No jargon without immediate explanation
- Conversational tone

## STORY ARC (11 SLIDES)

1. Hook - What problem are we solving?
2. Why it matters - Real world impact
3. Current approach - How do people solve this now?
4. The problem - Why current approach fails
5. Key insight - The paper's main idea (simple version)
6. How it works - Core mechanism (one simple diagram)
7. The math - One key equation, explained simply
8. Results - Main performance comparison
9. Why it works - Intuition behind success
10. Limitations - What doesn't work yet
11. Takeaway - One sentence summary

## OUTPUT FORMAT

Output ONLY valid JSON:

{
  "paper_title": "Simple, catchy title",
  "paper_summary": "One sentence explaining what this paper does, for an 8-year-old",
  "target_duration_minutes": 8,
  "slides": [
    {
      "slide_number": 1,
      "title": "Short Title",
      "visual_type": "diagram",
      "visual_description": "1-2 sentences describing simple shapes/text/arrows that Manim can render",
      "key_points": ["Point 1", "Point 2", "Point 3"],
      "voiceover_script": "3-4 short sentences. Simple words. For an 8-year-old.",
      "duration_seconds": 40,
      "transition_note": "Brief note on connection to next slide"
    }
  ]
}

CRITICAL RULES:
- EXACTLY 11 slides
- visual_description: 1-2 sentences, simple Manim shapes only
- voiceover_script: 3-4 sentences max, simple language
- visual_type: diagram, equation, graph, comparison, or text_reveal
- Output ONLY valid JSON, no markdown blocks"""


class PlanningService:
    def __init__(self, api_key: str):
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY not set - planning will fail")
        self.api_key = api_key
        self.client = Anthropic(api_key=api_key) if api_key else None
        self.model = "claude-sonnet-4-5-20250929"

    def _repair_truncated_json(self, text: str) -> str:
        """Attempt to repair truncated JSON by closing open structures."""
        logger.info("Attempting to repair truncated JSON...")

        open_braces = text.count('{') - text.count('}')
        open_brackets = text.count('[') - text.count(']')

        last_complete = text.rfind('},')
        if last_complete > 0:
            text = text[:last_complete + 1]
            text += '\n  ]\n}'
            logger.info("Repaired JSON by truncating to last complete slide")
        else:
            text += '"' * (text.count('"') % 2)
            text += '}' * open_braces
            text += ']' * open_brackets
            logger.info(f"Repaired JSON by closing {open_braces} braces and {open_brackets} brackets")

        return text

    async def create_presentation_plan(self, markdown_content: str) -> PresentationPlan:
        """
        Take extracted markdown from a paper and create a presentation plan.
        """
        if not self.client:
            raise ValueError("ANTHROPIC_API_KEY not configured.")

        logger.info("Starting presentation planning with Claude...")
        logger.info(f"Input markdown length: {len(markdown_content)} characters")

        # Truncate if too long
        if len(markdown_content) > 25000:
            markdown_content = markdown_content[:25000] + "\n\n[Content truncated...]"
            logger.info("Markdown truncated to 25000 characters")

        user_prompt = f"""Here is a research paper:

---
{markdown_content}
---

Create an 11-slide presentation following the rules exactly.

Remember:
- EXACTLY 11 slides
- Simple visuals (shapes, arrows, text only)
- Short voiceovers (3-4 sentences)
- For an 8-year-old audience
- Valid JSON only"""

        logger.info("Sending request to Claude API...")

        response = self.client.messages.create(
            model=self.model,
            max_tokens=8000,
            messages=[
                {"role": "user", "content": user_prompt}
            ],
            system=SYSTEM_PROMPT
        )

        response_text = response.content[0].text
        logger.info(f"Received response ({len(response_text)} chars)")
        logger.info(f"Stop reason: {response.stop_reason}")

        if response.stop_reason == "max_tokens":
            logger.warning("Response truncated!")
            response_text = self._repair_truncated_json(response_text)

        try:
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]

            plan_data = json.loads(response_text.strip())
            logger.info(f"Parsed plan with {len(plan_data.get('slides', []))} slides")

            plan = PresentationPlan(**plan_data)
            return plan

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            logger.error(f"Raw response: {response_text[:500]}...")
            raise ValueError(f"Failed to parse presentation plan: {e}")
