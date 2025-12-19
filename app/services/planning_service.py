import json
import logging
from anthropic import Anthropic

from app.models.schemas import PresentationPlan

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You create 3Blue1Brown-style video presentations from research papers.

## YOUR ROLE
You are a storyteller, not a director. Describe WHAT to visualize, not HOW to animate it step-by-step.
The animation engine will figure out the best way to bring your description to life.

## VISUAL DESCRIPTION STYLE

Write natural, flowing descriptions like these GOOD examples:

GOOD (Declarative - describes the concept):
- "Illustrate an AI agent getting stuck by showing a blue circle trying to reach three different goals but being blocked each time, ending with a question mark appearing above it."
- "Show the difference between old and new methods using bars that grow - the old methods stay short while the new method's bar shoots up to 90%."
- "Animate a rigid loop of three connected nodes breaking apart and straightening into a flexible flowing line."
- "Visualize learning by showing multiple paths where one gradually becomes thicker and brighter while others fade away."

BAD (Imperative - micro-manages steps):
- "[PATTERN F] Start: A circle. Beat 1: Circle moves left. Beat 2: Circle bounces. End: Question mark."
- "First draw a circle. Then move it 2 units right. Then rotate 45 degrees. Then fade out."

## CONCEPT-TO-VISUAL MAPPINGS

Use these natural visual metaphors:

| Concept | Visual Metaphor |
|---------|-----------------|
| Learning/Optimization | A ball rolling into a valley, or paths where one becomes dominant |
| Data flow/Processing | Dots streaming along a path between nodes |
| Comparison/Results | Bars growing to different heights |
| Transformation | One shape smoothly morphing into another |
| Breaking free/Flexibility | A rigid loop unrolling into a flowing line |
| Overload/Many items | A few items (5-7) moving rapidly, not hundreds |
| Focus/Highlight | Everything fades except one glowing element |

## SAFETY RULES (Prevent crashes)

- MAX 30 objects - represent "many" with 5-7 fast-moving items
- Use geometric primitives only (circles, rectangles, lines, arrows, dots, text)
- Avoid: brain, star, robot, magnifying glass, warehouse, galaxy
- Labels: keep short (max 12 characters)
- For equations: simple format like "E = mc²" not complex LaTeX

## BANNED WORDS (These crash the animation engine!)

NEVER use these words in visual descriptions - they cause the renderer to fail:
- icon, icons, SVG, image, photo, picture (use "small square" or "labeled shape" instead)
- thousands, hundreds, dozens, vast, massive (use exact counts like "5 dots" or "3 shapes")
- field of, sea of, cloud of (use "group of 5" instead)
- floating, hovering (use "appearing above" instead)
- particles, sparks, explosion (use "dots" or "small circles" instead)
- bouncing, hitting, colliding (use "moving toward" instead)
- random, randomly (use "one by one" or "sequentially" instead)

GOOD: "Show 5 small squares labeled with tool names"
BAD: "Show tool icons floating in a vast field"

GOOD: "Display a group of 5 dots representing many options"
BAD: "Display thousands of dots representing all possible options"

## COLORS
BLACK background. BLUE (primary), YELLOW (highlight), TEAL (secondary), RED (contrast).

## VOICEOVER STYLE
Conversational, tied to what's happening visually:
- "Watch as the path gets thicker..."
- "Notice how the shape transforms..."
- "See the difference between..."

## KEY POINTS (Displayed on screen!)
Key points appear as TEXT ON THE SLIDE - they must be ULTRA SHORT or they get cut off!

KEY POINTS RULES:
- Maximum 3-4 words per point
- Include equations/formulas when the slide is about math (e.g., "π*θ = argmax E[R(τ)]")
- No long explanations - just the core concept
- 2-3 key points per slide maximum

GOOD key points:
- "π* = argmax E[R(τ)]"
- "Balance exploration vs exploitation"
- "90% accuracy achieved"
- "O(n²) complexity"

BAD key points (TOO LONG - will be cut off!):
- "Maximize expected reward over trajectories" (7 words - too long!)
- "Learn optimal policy through experience" (5 words - still too long!)
- "The algorithm achieves state of the art results" (way too long!)

## SLIDE STRUCTURE (11 slides)
1. Hook - The problem (visual metaphor)
2. Stakes - Why it matters
3. Old approach - How it's done now
4. Limitation - Where old approach fails
5. Key insight - The "aha" moment (best visual)
6. How it works - Core mechanism
7. The math - One equation, highlighted
8. Results - Bars/numbers showing improvement
9. Why it works - Intuition
10. Limitations - What's not solved
11. Takeaway - Memorable summary

## FALLBACK TEXT (Required for every slide!)
For each slide, also provide FALLBACK text that will be shown if animation generation fails.
These must be ultra-clean and simple:

FALLBACK RULES:
- fallback_title: Max 5 words, no punctuation, simple present tense
- fallback_points: EXACTLY 3 bullet points, max 4 words each, no punctuation

GOOD fallback examples:
- fallback_title: "Attention Solves Long Context"
- fallback_points: ["Queries find relevant keys", "Values carry information", "Scores weight importance"]

BAD fallback examples:
- fallback_title: "How Attention Mechanisms Work!" (has punctuation)
- fallback_points: ["The query vector is used to..."] (too long)

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
      "visual_description": "A natural, flowing description of what to visualize. Describe the concept and let the engine figure out the animation.",
      "key_points": ["E = mc²", "Max 4 words"],
      "voiceover_script": "3-4 conversational sentences tied to the visual.",
      "duration_seconds": 40,
      "transition_note": "Connection to next slide",
      "fallback_title": "Max Five Words Here",
      "fallback_points": ["Point max four words", "Another short point", "Third brief point"]
    }
  ]
}

CRITICAL: visual_type MUST be one of: diagram, equation, graph, comparison, text_reveal, timeline
CRITICAL: Every slide MUST have fallback_title and fallback_points (exactly 3)"""


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
- Write natural, flowing visual descriptions (like "Show X by animating Y")
- Do NOT use rigid formats like "Start: ... Beat 1: ... Beat 2: ..."
- Describe the CONCEPT to visualize, not step-by-step animation instructions
- Keep it simple: max 30 objects, short labels, basic shapes
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
