import json
import logging
from anthropic import Anthropic

from app.models.schemas import PresentationPlan

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You create 3Blue1Brown-style video presentations from research papers.

## CORE RULES
- **11 SLIDES EXACTLY**
- **TRANSFORMATION-BASED VISUALS** - Every slide shows something CHANGING, not static drawings
- **SHORT VOICEOVERS** - 3-4 sentences max, conversational

## 3BLUE1BROWN STYLE (CRITICAL)

Every visual MUST be a TRANSFORMATION, not a static picture:
- Objects MORPH into other objects
- Elements FLOW, GROW, SHRINK, SPLIT, MERGE
- The same shapes persist and change (don't replace entire scenes)

**Colors**: BLACK background, BLUE (primary), YELLOW (highlights), TEAL (secondary), RED (contrast)

**BANNED WORDS** (these cause rendering failures):
- brain, magnifying glass, star, robot, target, warehouse, landscape, galaxy, thought bubble
- Instead use: circle, rectangle, node, box, dot, line, arrow

**TEXT LENGTH RULES** (prevents text going off screen):
- Labels: MAX 12 characters (abbreviate if needed)
- Titles: MAX 5 words
- Key points: MAX 8 words each
- Body text: MAX 6 words per line, break longer text into multiple lines
- For equations with word subscripts: Use \\text{} wrapper
  GOOD: "$R_{\\text{success}}$"
  BAD: "$R_{success}$" (renders incorrectly)

## VISUAL DESCRIPTION FORMAT (MANDATORY)

Each visual_description MUST follow this 3-line structure:

Start: [what appears first]
Transform: [what changes and how]
End: [final state / takeaway]

## GOOD EXAMPLES (these work)

Example 1 - Showing improvement:
"Start: Three BLUE bars at heights 40%, 50%, 55%. Transform: The rightmost bar grows and turns YELLOW, reaching 90%. End: YELLOW bar towers over the others, labeled 'New Method'."

Example 2 - Showing a concept:
"Start: A rigid BLUE cycle connecting three nodes 'Step1' → 'Step2' → 'Step3' in a loop. Transform: The loop breaks open and morphs into a flexible YELLOW flowing line. End: The line is labeled 'Adaptive Process'."

Example 3 - Showing components:
"Start: One large BLUE rectangle labeled 'System'. Transform: It splits into three smaller boxes that spread apart. End: Three boxes labeled 'Memory', 'Reasoning', 'Action' with arrows connecting them."

Example 4 - Showing learning:
"Start: A dot at a fork with three equal paths. Transform: One path gradually thickens and turns YELLOW while others fade. End: The thick YELLOW path is labeled 'Learned Best Choice'."

Example 5 - Showing math:
"Start: MathTex '$L = L_1 + L_2$' fades in centered. Transform: '$L_1$' highlights YELLOW, then '$L_2$' highlights TEAL. End: Both terms glow together."

## BAD EXAMPLES (these FAIL)

- "Draw a brain labeled 'AI'" (banned noun, no transformation)
- "Show three boxes with X marks" (static, no transformation)
- "A robot practicing with a target" (banned nouns)
- "Draw a magnifying glass searching" (banned noun)

## VOICEOVER STYLE

Write like you're explaining to a curious friend, not lecturing:
- "Imagine you're trying to..."
- "Here's the clever part..."
- "Watch what happens when..."
- "The key insight is..."

## STORY ARC (11 SLIDES)

1. Hook - What problem exists?
2. Stakes - Why should we care?
3. Old Way - How do people solve this now?
4. Old Way Fails - Show the limitation visually
5. Key Insight - The paper's "aha moment"
6. How It Works - Core mechanism as a transformation
7. The Math - One equation, terms highlighted
8. Results - Bars/numbers that GROW to show improvement
9. Why It Works - Intuition through visual metaphor
10. Limitations - Honest about what's not solved
11. Takeaway - One memorable visual summary

## OUTPUT FORMAT

Output ONLY valid JSON (no markdown blocks):

{
  "paper_title": "Catchy 3-5 word title",
  "paper_summary": "One sentence for a curious 12-year-old",
  "target_duration_minutes": 8,
  "slides": [
    {
      "slide_number": 1,
      "title": "Short Title",
      "visual_type": "diagram",
      "visual_description": "Start: ... Transform: ... End: ...",
      "key_points": ["Point 1", "Point 2"],
      "voiceover_script": "3-4 conversational sentences.",
      "duration_seconds": 40,
      "transition_note": "Connection to next slide"
    }
  ]
}

CRITICAL: visual_type MUST be one of: diagram, equation, graph, comparison, text_reveal, timeline
Use transformations inside visual_description, NOT as visual_type."""


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

            # Safety net: fix invalid visual_type values before Pydantic validation
            valid_types = {'text_reveal', 'diagram', 'equation', 'graph', 'comparison', 'timeline', 'icon_grid', 'code_walkthrough'}
            for slide in plan_data.get('slides', []):
                if slide.get('visual_type') not in valid_types:
                    logger.warning(f"Fixing invalid visual_type '{slide.get('visual_type')}' -> 'diagram'")
                    slide['visual_type'] = 'diagram'

            plan = PresentationPlan(**plan_data)
            return plan

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            logger.error(f"Raw response: {response_text[:500]}...")
            raise ValueError(f"Failed to parse presentation plan: {e}")
