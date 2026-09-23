from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Presentation plan (produced by Claude via structured output)
# ---------------------------------------------------------------------------

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
    title: str = Field(description="Short slide title, max 6 words")
    visual_type: VisualType
    visual_description: str = Field(
        description="Natural description of what the animation should show. Geometric primitives only."
    )
    key_points: List[str] = Field(description="2-3 ultra-short on-screen points, max 4 words each")
    voiceover_script: str = Field(description="3-4 conversational sentences the narrator says, 8th grade level")
    duration_seconds: int = Field(default=30, description="Target narration length for this slide")
    transition_note: Optional[str] = Field(default=None, description="How this connects to the next slide")
    fallback_title: str = Field(default="", description="Max 5 words, no punctuation; used if animation fails")
    fallback_points: List[str] = Field(
        default_factory=list,
        description="Exactly 3 bullet points, max 4 words each, no punctuation; used if animation fails",
    )


class PresentationPlan(BaseModel):
    paper_title: str = Field(description="Catchy 3-5 word title")
    paper_summary: str = Field(description="One sentence summary for a curious 12-year-old")
    target_duration_minutes: int = Field(default=5)
    slides: List[SlideContent]


class ManimSlide(BaseModel):
    slide_number: int
    class_name: str
    manim_code: str
    expected_duration: float


# ---------------------------------------------------------------------------
# Job document: one JSON row per job in the store
# ---------------------------------------------------------------------------

class SlideState(BaseModel):
    slide_number: int
    title: str = ""
    tier: int = 1              # 1 = Opus primary, 2 = Opus fix, 3 = safe template
    attempts: int = 0
    status: str = "pending"    # pending | submitted | rendering | done | retry | failed
    code: Optional[str] = None
    kodisc_job_id: Optional[str] = None
    video_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    error: Optional[str] = None
    tier_used: Optional[str] = None


class AudioState(BaseModel):
    slide_number: int
    status: str = "pending"    # pending | done | failed | skipped
    audio_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None


class FinalState(BaseModel):
    status: str = "pending"    # pending | submitted | rendering | done | failed
    render_id: Optional[str] = None
    video_url: Optional[str] = None
    error: Optional[str] = None


class Job(BaseModel):
    id: str
    filename: str
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)
    step: str = "uploaded"     # uploaded | ocr_complete | plan_complete | rendering | voicing | assembling | complete | failed
    error: Optional[str] = None
    fatal: bool = False        # True when a vendor rejected the key or credits ran out; client must stop
    markdown: Optional[str] = None
    plan: Optional[PresentationPlan] = None
    slides: dict[str, SlideState] = Field(default_factory=dict)
    audio: dict[str, AudioState] = Field(default_factory=dict)
    final: FinalState = Field(default_factory=FinalState)

    # -- helpers ------------------------------------------------------------
    def slide(self, n: int) -> Optional[SlideState]:
        return self.slides.get(str(n))

    def audio_for(self, n: int) -> Optional[AudioState]:
        return self.audio.get(str(n))

    def apply_plan(self, plan: PresentationPlan) -> None:
        self.plan = plan
        self.slides = {
            str(s.slide_number): SlideState(slide_number=s.slide_number, title=s.title)
            for s in plan.slides
        }
        self.audio = {str(s.slide_number): AudioState(slide_number=s.slide_number) for s in plan.slides}
        self.step = "plan_complete"

    @property
    def paper_title(self) -> Optional[str]:
        return self.plan.paper_title if self.plan else None

    def summary(self) -> dict:
        total = len(self.slides)
        rendered = sum(1 for s in self.slides.values() if s.status == "done")
        voiced = sum(1 for a in self.audio.values() if a.status == "done")
        return {
            "id": self.id,
            "filename": self.filename,
            "paper_title": self.paper_title,
            "step": self.step,
            "error": self.error,
            "fatal": self.fatal,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "slides_total": total,
            "slides_rendered": rendered,
            "slides_voiced": voiced,
            "final_status": self.final.status,
            "final_url": self.final.video_url,
        }

    def public(self) -> dict:
        """Full document for the UI, minus the large blobs (markdown, Manim code)."""
        d = self.model_dump()
        d.pop("markdown", None)
        d["has_markdown"] = bool(self.markdown)
        for s in d["slides"].values():
            s["has_code"] = bool(s.pop("code", None))
        d["summary"] = self.summary()
        return d
