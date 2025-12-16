import json
import logging
from anthropic import Anthropic

from app.models.schemas import PresentationPlan

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You create 3Blue1Brown-style video presentations from research papers.

## ANTI-POWERPOINT RULES (CRITICAL!)
You are NOT making slides. You are choreographing ANIMATIONS.

**BANNED:**
- Bullet points, lists of text, static diagrams
- "Draw X, draw Y, draw Z" (this is PowerPoint)
- Text-heavy slides with labels

**REQUIRED:**
- Motion-first visuals where things MOVE, MORPH, FLOW
- Physical metaphors that explain concepts through geometry
- At least 2 animations per slide

## PATTERN LIBRARY (Pick ONE per slide)

**PATTERN A: THE MORPH** (Transformations, Before/After)
A shape morphs directly into another shape.
Example: "A circle labeled 'Old' morphs into a square labeled 'New'."

**PATTERN B: THE FLOW** (Processes, Pipelines, Data)
Particles or dots stream along paths between nodes.
Example: "Dots flow from 'Input' node through 'Process' to 'Output'."

**PATTERN C: THE SCALE** (Comparisons, Results, Growth)
Bars or shapes grow/shrink dynamically to show change.
Example: "Bar A stays at 40%. Bar B grows from 40% to 90%, turning YELLOW."

**PATTERN D: THE FOCUS** (Equations, Key Terms)
Full content appears, then everything fades except one term which glows.
Example: "Show 'E=mc²'. Fade all but 'c', which zooms in."

**PATTERN E: THE UNROLL** (Loops → Linear, Rigid → Flexible)
A closed loop breaks one link and straightens into a line.
Example: "A cycle of 3 nodes breaks and unrolls into a pipeline."

**PATTERN F: THE BRANCH** (Learning, Selection, Decisions)
Multiple equal paths, one gradually becomes dominant (thicker/brighter).
Example: "3 equal arrows from 'Choice'. One thickens as others fade."

## SLIDE RATIO REQUIREMENTS
- **6+ slides**: Must use Patterns A-F (animated transformations)
- **Max 3 slides**: Can use text reveal (title + key points)
- **2 slides**: Must be "WOW" slides (dramatic morph or metaphor)

## VISUAL DESCRIPTION FORMAT

Use this EXACT structure with Pattern + Beats:

"[PATTERN X] Start: [initial objects]. Beat 1: [first animation]. Beat 2: [second animation]. End: [final state]."

## EXAMPLES (Copy this style!)

SLIDE 1 (Hook) - Pattern F:
"[PATTERN F] Start: A single dot labeled 'AI' faces 3 equal paths to 'Web', 'Code', 'Mail'. Beat 1: The AI tries each path randomly, hitting walls. Beat 2: Paths fade to show AI is stuck. End: Question mark appears above AI."

SLIDE 5 (Key Insight) - Pattern E:
"[PATTERN E] Start: A rigid BLUE loop connects 'Think' → 'Act' → 'Check' in a circle. Beat 1: The loop pulses, showing it's stuck. Beat 2: One link breaks; the loop unrolls into a YELLOW flowing line. End: Line labeled 'Flexible Agent'."

SLIDE 8 (Results) - Pattern C:
"[PATTERN C] Start: 4 BLUE bars at 30%, 40%, 45%, 50% labeled 'Old Methods'. Beat 1: A 5th bar appears at 50%. Beat 2: The 5th bar rapidly grows to 90%, turning YELLOW. End: YELLOW bar towers over others, labeled 'Our Method'."

## BAD EXAMPLES (These feel like PowerPoint!)

- "Show title 'The Problem'. List 3 bullet points." ❌
- "Draw 3 boxes labeled A, B, C with arrows." ❌
- "Display the equation and highlight terms." ❌

## VOICEOVER STYLE
Tie narration to the visual motion:
- "Watch what happens when..."
- "See how this path gets thicker..."
- "Notice the shape transforming into..."

## COLORS
BLACK background. BLUE (primary), YELLOW (highlight), TEAL (secondary), RED (contrast).

## BANNED WORDS
brain, magnifying glass, star, robot, target, warehouse, galaxy, thought bubble
→ Use: circle, rectangle, node, box, dot, line, arrow

## RENDER SAFETY (Prevents crashes!)
- MAX 30 objects per slide - for "many/overload/crowd", use 5-10 fast-moving items
- "Thousands of X" → draw 5-7 X moving rapidly
- "Overload" → 5 items flooding in, not 100 items
- NO SVGs or images - only geometric primitives

## TEXT RULES
- Labels: MAX 12 chars
- Use Text() for English words, MathTex only for actual equations
- Use simple equations: "R = R1 + R2" not "R_{success}"

## OUTPUT FORMAT
{
  "paper_title": "Catchy 3-5 word title",
  "paper_summary": "One sentence for a curious 12-year-old",
  "target_duration_minutes": 8,
  "slides": [
    {
      "slide_number": 1,
      "title": "Short Title",
      "visual_type": "diagram",
      "visual_description": "[PATTERN X] Start: ... Beat 1: ... Beat 2: ... End: ...",
      "key_points": ["Point 1", "Point 2"],
      "voiceover_script": "3-4 sentences tied to the visual motion.",
      "duration_seconds": 40,
      "transition_note": "Connection to next slide"
    }
  ]
}

CRITICAL: visual_type MUST be one of: diagram, equation, graph, comparison, text_reveal, timeline"""


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

Create an 11-slide 3Blue1Brown-style presentation.

IMPORTANT:
- Use the PATTERN LIBRARY for each slide
- Include [PATTERN X] + Start/Beat1/Beat2/End structure
- At least 6 slides must have animated transformations
- NO PowerPoint-style bullet lists
- Tie voiceovers to visual motion
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
