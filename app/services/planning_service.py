import json
import logging
from anthropic import Anthropic

from app.models.schemas import PresentationPlan

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an educational content planner specializing in transforming academic research papers into engaging explainer videos for 8th graders (13-14 year olds).

Your task is to create a presentation plan that:
1. Breaks down complex concepts into simple, relatable explanations
2. Uses analogies and real-world examples
3. Structures content for visual animation (think 3Blue1Brown style)
4. Keeps the audience engaged with a clear narrative arc

Output a valid JSON object matching this structure:
{
  "paper_title": "Simple, engaging title",
  "paper_summary": "2-3 sentences explaining what this paper is about in simple terms",
  "target_duration_minutes": 5,
  "slides": [
    {
      "slide_number": 1,
      "title": "Hook/Introduction",
      "visual_type": "text_reveal|diagram|equation|graph|comparison|timeline|icon_grid|code_walkthrough",
      "visual_description": "Detailed description of what the animation should show",
      "key_points": ["point 1", "point 2", "point 3"],
      "voiceover_script": "What the narrator says (conversational, 8th grade level)",
      "duration_seconds": 30,
      "transition_note": "How this connects to the next slide"
    }
  ]
}

Guidelines:
- Start with a hook that makes the topic relatable
- Use 5-8 slides for a 5-minute video
- Each slide should have ONE main idea
- Visual descriptions should be specific enough for an animator
- Voiceover should sound natural and conversational
- End with a summary and "why this matters"

IMPORTANT: Output ONLY valid JSON, no markdown code blocks or extra text."""


class PlanningService:
    def __init__(self, api_key: str):
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY not set - planning will fail")
        self.api_key = api_key
        self.client = Anthropic(api_key=api_key) if api_key else None
        self.model = "claude-sonnet-4-20250514"

    async def create_presentation_plan(self, markdown_content: str) -> PresentationPlan:
        """
        Take extracted markdown from a paper and create a presentation plan.
        """
        if not self.client:
            raise ValueError("ANTHROPIC_API_KEY not configured. Please add it to your environment variables.")

        logger.info("Starting presentation planning with Claude...")
        logger.info(f"Input markdown length: {len(markdown_content)} characters")

        # Truncate if too long (keep first 15000 chars for context window)
        if len(markdown_content) > 15000:
            markdown_content = markdown_content[:15000] + "\n\n[Content truncated for processing...]"
            logger.info("Markdown truncated to 15000 characters")

        user_prompt = f"""Here is the extracted content from a research paper:

---
{markdown_content}
---

Create a presentation plan to explain this paper's key concepts to 8th graders in an engaging 5-minute video. Focus on the main ideas and make them accessible and interesting."""

        logger.info("Sending request to Claude API...")

        # Note: Anthropic client is sync, so we run it directly
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            messages=[
                {"role": "user", "content": user_prompt}
            ],
            system=SYSTEM_PROMPT
        )

        response_text = response.content[0].text
        logger.info(f"Received response from Claude ({len(response_text)} chars)")
        logger.info(f"Token usage - Input: {response.usage.input_tokens}, Output: {response.usage.output_tokens}")

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
