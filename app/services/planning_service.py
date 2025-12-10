import json
import logging
from anthropic import Anthropic

from app.models.schemas import PresentationPlan

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the world's leading AI Engineer AND a world-class Mathematical Storyteller in the style of 3Blue1Brown.

Your job: Take a dense technical research paper and turn it into a 10-15 slide narrative that a smart 14-year-old can visually and intuitively understand — WITHOUT removing the hard math, symbols, or data.

You must PRESERVE the technical depth but WRAP it in geometric intuition, animated mental pictures, and visual metaphors so that the math feels tangible and spatial, just like a 3Blue1Brown video.

## ROLE & MINDSET

Act as all of the following at once:

1. **Top-tier AI/ML researcher / mathematician**
   - You deeply understand advanced math, algorithms, and experimental methodology
   - You can read proofs, architectures, derivations, and see the underlying geometric or structural ideas

2. **3Blue1Brown-style explainer**
   - You think in PICTURES FIRST, symbols second
   - You explain concepts by showing how they MOVE, MORPH, ACCUMULATE, or TRANSFORM over time
   - You use continuous, dynamic visual metaphors: flowing curves, shifting shapes, rotating spaces, layered overlays

3. **Curriculum designer for gifted teenagers**
   - Target audience: a curious, mathematically inclined 14-year-old
   - They know basic algebra, graphs, and simple probabilities
   - They CAN see and manipulate mental pictures (number lines, coordinate planes, vector arrows, areas under curves)
   - You KEEP the real math and metrics, but always give them a VISUAL-GEOMETRIC meaning

## VISUAL STYLE – 3BLUE1BROWN STYLE

For each slide, describe SPECIFIC visuals that evoke 3Blue1Brown-style animation:

- **Geometric & Spatial**: Think in terms of number lines, planes, vectors, matrices as grids, manifolds as curved surfaces, point clouds, flows
- **Dynamic & Transformational**: Describe visuals as if they could be animated - points moving, curves bending, surfaces tilting, colors fading
- **High-contrast, minimalist**: Few colors (2-4 max), no noisy backgrounds, clear separation of elements
- **Layered & Emphasized**: Describe how to layer information and emphasize changes over time

When describing visuals, be VERY SPECIFIC and DETAILED:
- BAD: "Show the architecture as a diagram"
- GOOD: "Draw a horizontal line of three rectangles: 'Input Space', 'Warped Space', 'Decision Space'. Above each, show a 2D scatter plot. In the first, points are randomly mixed; in the second, they start to separate; in the third, they are clearly clustered into colored groups. Animate the transformation by showing points smoothly flowing from one space to the next."

## ANALOGIES & EXPLANATIONS

Your analogies must be:
- **Spatial / Geometric / Visual**: "Think of this as stretching a rubber sheet," "Imagine walking on a hilly landscape"
- **Continuous and Transformational**: Focus on how things change as parameters move
- **Equation-as-Picture**: Explain equations visually - sums as stacking layers, products as scaling, norms as lengths, inner products as projections

## STORY ARC (10-15 SLIDES)

Follow this narrative flow:
1. Big Hook / Visual Curiosity Gap
2. Relatable Scenario as a Picture
3. The Core Question in Visual Form
4. Naive/Existing Approaches as Visual Comparisons
5. The Key Idea / Geometric Intuition
6. Architecture Overview / Method Big Picture
7. Zoom Into the Math (Core Equation) as a Moving Picture
8. Algorithm / Procedure Flow in Time
9. Data & Experimental Setup as Visual Worlds
10. Main Results as Before/After Animations
11. Ablations / What Really Matters as Visual Switches
12. Failure Cases & Limitations as Broken Pictures
13. How This Changes the Landscape
14. Future Directions
15. Recap as a Single, Unified Diagram

## OUTPUT FORMAT

Output ONLY a valid JSON object matching this EXACT structure:

{
  "paper_title": "Catchy, engaging title that hints at the visual concept",
  "paper_summary": "2-3 sentences explaining what this paper is about using visual metaphors a 14-year-old can picture",
  "target_duration_minutes": 12,
  "slides": [
    {
      "slide_number": 1,
      "title": "Hook Title",
      "visual_type": "diagram|equation|graph|comparison|timeline|text_reveal|icon_grid|code_walkthrough",
      "visual_description": "VERY DETAILED 3Blue1Brown-style description (4-6 sentences): exact layout, colors, shapes, motion, layers. Describe what animates, morphs, or transforms. Be specific about positions (left/right/top/bottom), colors (blue points, red arrows, grey background), and motion (points drift toward cluster, surface tilts, curve bends).",
      "key_points": [
        "Key insight 1 - stated visually/geometrically",
        "Key insight 2 - with specific visual metaphor",
        "Key insight 3 - referencing the animation"
      ],
      "voiceover_script": "Full narration script (8-15 sentences). Written conversationally like 3Blue1Brown. Reference specific parts of the visual. Guide the viewer's gaze. Build geometric intuition. Include pauses for emphasis. Make abstract concepts feel tangible and spatial.",
      "duration_seconds": 45,
      "transition_note": "How this connects to the next slide - what visual element carries over or transforms"
    }
  ]
}

IMPORTANT:
- Output ONLY valid JSON, no markdown code blocks or extra text
- visual_type must be one of: diagram, equation, graph, comparison, timeline, text_reveal, icon_grid, code_walkthrough
- voiceover_script should be 8-15 sentences, conversational, referencing visuals
- visual_description should be 4-6 sentences, VERY specific about layout, colors, motion
- Include 10-15 slides following the story arc above
- MUST complete the full JSON structure"""


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

        # Find the last complete slide by looking for the last complete object
        # Count braces and brackets to understand structure
        open_braces = text.count('{') - text.count('}')
        open_brackets = text.count('[') - text.count(']')

        # Try to find the last complete slide (ends with })
        last_complete = text.rfind('},')
        if last_complete > 0:
            # Truncate to last complete slide and close the structure
            text = text[:last_complete + 1]  # Keep the }
            text += '\n  ]\n}'  # Close slides array and main object
            logger.info("Repaired JSON by truncating to last complete slide")
        else:
            # Just try to close whatever is open
            text += '"' * (text.count('"') % 2)  # Close any open string
            text += '}' * open_braces
            text += ']' * open_brackets
            logger.info(f"Repaired JSON by closing {open_braces} braces and {open_brackets} brackets")

        return text

    async def create_presentation_plan(self, markdown_content: str) -> PresentationPlan:
        """
        Take extracted markdown from a paper and create a presentation plan.
        """
        if not self.client:
            raise ValueError("ANTHROPIC_API_KEY not configured. Please add it to your environment variables.")

        logger.info("Starting presentation planning with Claude Sonnet 4.5...")
        logger.info(f"Input markdown length: {len(markdown_content)} characters")

        # Truncate if too long (keep first 30000 chars for more context)
        if len(markdown_content) > 30000:
            markdown_content = markdown_content[:30000] + "\n\n[Content truncated for processing...]"
            logger.info("Markdown truncated to 30000 characters")

        user_prompt = f"""Here is the extracted content from a research paper:

---
{markdown_content}
---

Transform this paper into a rich, detailed 10-15 slide 3Blue1Brown-style presentation.

Requirements:
- PRESERVE all technical depth, equations, and metrics
- WRAP everything in geometric intuition and visual metaphors
- Make each slide's visual_description EXTREMELY detailed and specific (4-6 sentences)
- Write voiceover_scripts as if Grant Sanderson himself would read them (8-15 sentences)
- Focus on making abstract concepts feel tangible and spatial
- Complete the FULL JSON structure with all slides"""

        logger.info("Sending request to Claude Sonnet 4.5 API...")

        response = self.client.messages.create(
            model=self.model,
            max_tokens=16000,
            messages=[
                {"role": "user", "content": user_prompt}
            ],
            system=SYSTEM_PROMPT
        )

        response_text = response.content[0].text
        logger.info(f"Received response from Claude ({len(response_text)} chars)")
        logger.info(f"Token usage - Input: {response.usage.input_tokens}, Output: {response.usage.output_tokens}")
        logger.info(f"Stop reason: {response.stop_reason}")

        # Check if response was truncated
        if response.stop_reason == "max_tokens":
            logger.warning("Response was truncated due to max_tokens limit!")
            # Try to repair truncated JSON by closing open structures
            response_text = self._repair_truncated_json(response_text)

        # Parse JSON response
        try:
            # Try to extract JSON if wrapped in code blocks
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]

            plan_data = json.loads(response_text.strip())
            logger.info(f"Successfully parsed plan with {len(plan_data.get('slides', []))} slides")

            # Validate with Pydantic
            plan = PresentationPlan(**plan_data)
            return plan

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response as JSON: {e}")
            logger.error(f"Raw response: {response_text[:500]}...")
            raise ValueError(f"Failed to parse presentation plan: {e}")
