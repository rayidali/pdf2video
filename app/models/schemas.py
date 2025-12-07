from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum


class VisualType(str, Enum):
    TEXT_REVEAL = "text_reveal"
    DIAGRAM = "diagram"
    EQUATION = "equation"
    GRAPH = "graph"
    COMPARISON = "comparison"
    TIMELINE = "timeline"
    ICON_GRID = "icon_grid"
    CODE_WALKTHROUGH = "code_walkthrough"


class SlideContent(BaseModel):
    slide_number: int
    title: str
    visual_type: VisualType
    visual_description: str = Field(
        description="Detailed description of what the animation should show"
    )
    key_points: List[str] = Field(
        description="3-5 bullet points to visualize"
    )
    voiceover_script: str = Field(
        description="What the narrator says during this slide (8th grade level)"
    )
    duration_seconds: int = Field(
        default=30,
        description="Estimated duration for this slide"
    )
    transition_note: Optional[str] = Field(
        default=None,
        description="How this connects to the next slide"
    )


class PresentationPlan(BaseModel):
    paper_title: str
    paper_summary: str = Field(
        description="2-3 sentence summary for 8th graders"
    )
    target_duration_minutes: int = Field(default=5)
    slides: List[SlideContent]


class ManimSlide(BaseModel):
    slide_number: int
    class_name: str
    manim_code: str
    expected_duration: float


class JobStatus(BaseModel):
    job_id: str
    status: str  # "processing", "complete", "failed"
    step: Optional[str] = None
    video_url: Optional[str] = None
    error: Optional[str] = None
