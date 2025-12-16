"""
Generative Manim Service

Integrates with the Generative Manim API to:
1. Generate Manim code from text descriptions (using their fine-tuned models)
2. Render Manim code into actual videos
3. Full pipeline: description → code → video

API Docs: https://github.com/marcelo-earth/generative-manim

Supported engines for code generation:
- "openai" (GPT-4o with custom system prompt)
- "anthropic" (Claude Sonnet with custom system prompt)
"""

import httpx
import logging
import asyncio
from typing import Optional, Literal
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Default timeout for rendering (can take a while for complex scenes)
RENDER_TIMEOUT = 300  # 5 minutes
CODE_GEN_TIMEOUT = 120  # 2 minutes for code generation

# Available engines in Generative Manim API
CodeGenEngine = Literal["openai", "anthropic"]


@dataclass
class CodeGenResult:
    """Result of a code generation attempt."""
    success: bool
    code: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class RenderResult:
    """Result of a render attempt."""
    success: bool
    video_url: Optional[str] = None
    video_path: Optional[str] = None
    error_message: Optional[str] = None
    render_time: Optional[float] = None
    code: Optional[str] = None  # Include generated code if available


class GenerativeManimService:
    """
    Service to render Manim code using the Generative Manim API.

    This provides real validation by actually running the code,
    catching runtime errors that static analysis would miss.
    """

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:8080",
        timeout: int = RENDER_TIMEOUT
    ):
        """
        Initialize the render service.

        Args:
            api_url: Base URL of the Generative Manim API
                     Default: http://127.0.0.1:8080 for local
                     Or use: https://api.generativemanim.com for hosted
            timeout: Timeout for render requests in seconds
        """
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self._available = None  # Cached availability check

    async def check_availability(self) -> bool:
        """
        Check if the Generative Manim API is available.
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.api_url}/health")
                self._available = response.status_code == 200
                return self._available
        except Exception as e:
            logger.warning(f"Generative Manim API not available: {e}")
            self._available = False
            return False

    # ========================================
    # CODE GENERATION (using GM's LLM models)
    # ========================================

    async def generate_code(
        self,
        prompt: str,
        engine: CodeGenEngine = "anthropic"
    ) -> CodeGenResult:
        """
        Generate Manim code from a text description using GM API's LLM.

        This uses the Generative Manim API's fine-tuned prompts
        specifically optimized for Manim code generation.

        Args:
            prompt: Text description of the animation to create
            engine: LLM engine to use ("openai" or "anthropic")

        Returns:
            CodeGenResult with generated code or error
        """
        payload = {
            "prompt": prompt,
            "engine": engine
        }

        logger.info(f"Generating Manim code via GM API (engine: {engine})...")

        try:
            async with httpx.AsyncClient(timeout=CODE_GEN_TIMEOUT) as client:
                response = await client.post(
                    f"{self.api_url}/v1/code/generation",
                    json=payload
                )

                if response.status_code == 200:
                    data = response.json()
                    code = data.get("code") or data.get("result")
                    logger.info(f"Code generated successfully ({len(code) if code else 0} chars)")
                    return CodeGenResult(
                        success=True,
                        code=code
                    )
                else:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("detail") or error_data.get("error") or f"HTTP {response.status_code}"
                    logger.error(f"Code generation failed: {error_msg}")
                    return CodeGenResult(
                        success=False,
                        error_message=error_msg
                    )

        except httpx.TimeoutException:
            logger.error(f"Code generation timeout after {CODE_GEN_TIMEOUT}s")
            return CodeGenResult(
                success=False,
                error_message=f"Code generation timed out after {CODE_GEN_TIMEOUT} seconds"
            )
        except Exception as e:
            logger.error(f"Code generation error: {e}")
            return CodeGenResult(
                success=False,
                error_message=str(e)
            )

    async def generate_code_chat(
        self,
        messages: list[dict],
        engine: CodeGenEngine = "anthropic"
    ) -> CodeGenResult:
        """
        Generate Manim code using chat-style interaction.

        This allows for multi-turn conversations to refine the animation.

        Args:
            messages: List of message dicts with "role" and "content"
            engine: LLM engine to use

        Returns:
            CodeGenResult with generated code or error
        """
        payload = {
            "messages": messages,
            "engine": engine
        }

        logger.info(f"Generating Manim code via chat (engine: {engine})...")

        try:
            async with httpx.AsyncClient(timeout=CODE_GEN_TIMEOUT) as client:
                response = await client.post(
                    f"{self.api_url}/v1/chat/generation",
                    json=payload
                )

                if response.status_code == 200:
                    # Chat endpoint may stream, try to get full response
                    code = response.text
                    logger.info(f"Code generated via chat ({len(code)} chars)")
                    return CodeGenResult(
                        success=True,
                        code=code
                    )
                else:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("detail") or f"HTTP {response.status_code}"
                    return CodeGenResult(
                        success=False,
                        error_message=error_msg
                    )

        except Exception as e:
            logger.error(f"Chat code generation error: {e}")
            return CodeGenResult(
                success=False,
                error_message=str(e)
            )

    async def generate_and_render(
        self,
        prompt: str,
        class_name: str = "GeneratedScene",
        engine: CodeGenEngine = "anthropic",
        aspect_ratio: str = "16:9"
    ) -> RenderResult:
        """
        Full pipeline: Text prompt → Video (single API call).

        Uses GM API's /v1/video/generation endpoint which handles
        both code generation and rendering in one request.

        Args:
            prompt: Text description of the animation
            class_name: Name for the generated Scene class (for our tracking)
            engine: LLM engine for code generation ("openai" or "anthropic")
            aspect_ratio: Video aspect ratio ("16:9", "1:1", or "9:16")

        Returns:
            RenderResult with video URL and generated code
        """
        import time
        start_time = time.time()

        payload = {
            "prompt": prompt,
            "engine": engine,
            "aspect_ratio": aspect_ratio
        }

        logger.info(f"Generating video via GM API /v1/video/generation (engine: {engine})...")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.api_url}/v1/video/generation",
                    json=payload
                )

                render_time = time.time() - start_time

                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"Video generated successfully in {render_time:.1f}s")
                    return RenderResult(
                        success=True,
                        video_url=data.get("video_url"),
                        video_path=data.get("video_path"),
                        code=data.get("code"),
                        render_time=render_time
                    )
                else:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("detail") or error_data.get("error") or f"HTTP {response.status_code}"
                    logger.error(f"Video generation failed: {error_msg}")
                    return RenderResult(
                        success=False,
                        error_message=error_msg
                    )

        except httpx.TimeoutException:
            logger.error(f"Video generation timeout after {self.timeout}s")
            return RenderResult(
                success=False,
                error_message=f"Video generation timed out after {self.timeout} seconds"
            )
        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to GM API: {e}")
            return RenderResult(
                success=False,
                error_message=f"Cannot connect to GM API at {self.api_url}. Is it running?"
            )
        except Exception as e:
            logger.error(f"Video generation error: {e}")
            return RenderResult(
                success=False,
                error_message=str(e)
            )

    # ========================================
    # RENDERING (existing methods)
    # ========================================

    async def render_code(
        self,
        code: str,
        class_name: str,
        file_name: Optional[str] = None,
        stream: bool = False
    ) -> RenderResult:
        """
        Render Manim code into a video.

        Args:
            code: The full Manim Python code
            class_name: The Scene class to render (e.g., "Slide001")
            file_name: Optional file name for the output
            stream: Whether to stream the render progress

        Returns:
            RenderResult with success status, video URL, or error message
        """
        if file_name is None:
            file_name = f"scene_{class_name.lower()}"

        payload = {
            "code": code,
            "file_name": file_name,
            "file_class": class_name,
            "stream": stream
        }

        logger.info(f"Rendering {class_name} via Generative Manim API...")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.api_url}/v1/video/rendering",
                    json=payload
                )

                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"Render successful for {class_name}")
                    return RenderResult(
                        success=True,
                        video_url=data.get("video_url"),
                        video_path=data.get("video_path"),
                        render_time=data.get("render_time")
                    )
                else:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("detail") or error_data.get("error") or f"HTTP {response.status_code}"
                    logger.error(f"Render failed for {class_name}: {error_msg}")
                    return RenderResult(
                        success=False,
                        error_message=error_msg
                    )

        except httpx.TimeoutException:
            logger.error(f"Render timeout for {class_name} after {self.timeout}s")
            return RenderResult(
                success=False,
                error_message=f"Render timed out after {self.timeout} seconds"
            )
        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to Generative Manim API: {e}")
            return RenderResult(
                success=False,
                error_message=f"Cannot connect to render API at {self.api_url}. Is it running?"
            )
        except Exception as e:
            logger.error(f"Unexpected render error for {class_name}: {e}")
            return RenderResult(
                success=False,
                error_message=str(e)
            )

    async def validate_by_rendering(
        self,
        code: str,
        class_name: str
    ) -> tuple[bool, Optional[str]]:
        """
        Validate code by attempting to render it.

        This catches runtime errors that static analysis would miss,
        like incorrect Manim API usage, missing animations, etc.

        Args:
            code: The Manim code to validate
            class_name: The Scene class name

        Returns:
            (is_valid, error_message)
        """
        result = await self.render_code(code, class_name)
        return result.success, result.error_message

    async def render_all_slides(
        self,
        slides_dir: Path,
        manifest: list[dict]
    ) -> list[RenderResult]:
        """
        Render all slides from a manifest.

        Args:
            slides_dir: Path to the slides directory
            manifest: List of slide info dicts with code_path and class_name

        Returns:
            List of RenderResults for each slide
        """
        results = []

        for slide_info in manifest:
            code_path = Path(slide_info["code_path"])
            class_name = slide_info["class_name"]

            if not code_path.exists():
                results.append(RenderResult(
                    success=False,
                    error_message=f"Code file not found: {code_path}"
                ))
                continue

            code = code_path.read_text()
            result = await self.render_code(code, class_name)
            results.append(result)

            # Add a small delay between renders to avoid overwhelming the API
            await asyncio.sleep(1)

        return results


class LocalManimRenderer:
    """
    Alternative renderer that runs Manim locally.

    Use this if you have Manim installed locally and don't want
    to depend on the Generative Manim API.
    """

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def render_code(
        self,
        code: str,
        class_name: str,
        quality: str = "medium_quality"  # low_quality, medium_quality, high_quality
    ) -> RenderResult:
        """
        Render Manim code locally using subprocess.

        Requires Manim to be installed locally.
        """
        import tempfile
        import subprocess

        # Write code to temp file
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.py',
            delete=False
        ) as f:
            f.write(code)
            temp_path = f.name

        try:
            # Quality flag mapping
            quality_flags = {
                "low_quality": "-ql",
                "medium_quality": "-qm",
                "high_quality": "-qh"
            }
            quality_flag = quality_flags.get(quality, "-qm")

            # Run manim
            cmd = [
                "manim",
                quality_flag,
                temp_path,
                class_name,
                "-o", f"{class_name}.mp4",
                "--media_dir", str(self.output_dir)
            ]

            logger.info(f"Running: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode == 0:
                # Find the output video
                video_path = self.output_dir / "videos" / f"{class_name}.mp4"
                return RenderResult(
                    success=True,
                    video_path=str(video_path)
                )
            else:
                error_msg = result.stderr or result.stdout or "Unknown error"
                return RenderResult(
                    success=False,
                    error_message=error_msg
                )

        except subprocess.TimeoutExpired:
            return RenderResult(
                success=False,
                error_message="Render timed out after 300 seconds"
            )
        except FileNotFoundError:
            return RenderResult(
                success=False,
                error_message="Manim not found. Install with: pip install manim"
            )
        except Exception as e:
            return RenderResult(
                success=False,
                error_message=str(e)
            )
        finally:
            # Clean up temp file
            Path(temp_path).unlink(missing_ok=True)
