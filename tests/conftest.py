"""Fakes for every vendor so the whole pipeline runs offline in milliseconds."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import deps
from app.config import settings
from app.models.schemas import ManimSlide, PresentationPlan, SlideContent, VisualType
from app.services.elevenlabs_service import VoiceoverResult
from app.services.kodisc_service import KodiscResult
from app.services.r2_service import UploadResult
from app.services.shotstack_service import ShotstackResult
from app.store import SqliteJobStore

PDF_BYTES = b"%PDF-1.4\n% fake pdf for tests\n"   # unreadable by pypdf -> exercises the OCR fallback


def make_text_pdf(text: str, copies: int = 1) -> bytes:
    """A minimal valid single-page PDF whose page contains `text` repeated `copies` times."""
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, StreamObject

    w = PdfWriter()
    page = w.add_blank_page(width=612, height=792)
    lines = "\n".join(f"BT /F1 12 Tf 40 {760 - 14 * i} Td ({text}) Tj ET" for i in range(copies))
    stream = StreamObject(); stream._data = lines.encode()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})})
    page[NameObject("/Contents")] = w._add_object(stream)
    import io
    buf = io.BytesIO(); w.write(buf)
    return buf.getvalue()

VALID_CODE = '''from manim import *

class {cls}(Scene):
    def construct(self):
        self.camera.background_color = "#000000"
        t = Text("Hello", font_size=48)
        self.play(FadeIn(t))
        self.wait(1.5)
'''

INVALID_CODE = '''from manim import *

class WrongName(Scene):
    def construct(self):
        eq = MathTex("x^2")
        self.play(Write(eq))
'''


def make_plan(n: int = 2) -> PresentationPlan:
    return PresentationPlan(
        paper_title="Test Paper",
        paper_summary="A paper about testing.",
        slides=[
            SlideContent(
                slide_number=i,
                title=f"Slide {i}",
                visual_type=VisualType.DIAGRAM,
                visual_description="Two boxes and an arrow.",
                key_points=["Point A", "Point B"],
                voiceover_script=f"This is slide {i}.",
                duration_seconds=20,
                fallback_title=f"Fallback {i}",
                fallback_points=["One", "Two", "Three"],
            )
            for i in range(1, n + 1)
        ],
    )


class FakeOCR:
    def is_configured(self):
        return True

    async def pdf_to_markdown(self, data: bytes, filename: str) -> str:
        assert data.startswith(b"%PDF")
        return "# Test Paper\n\nSome extracted text."


class FakePlanner:
    def __init__(self):
        self.calls = 0

    def is_configured(self):
        return True

    async def create_presentation_plan(self, markdown: str) -> PresentationPlan:
        self.calls += 1
        return make_plan()


class FakeManim:
    def __init__(self, generate_invalid=False, fix_invalid=False):
        self.generate_calls = 0
        self.fix_calls = 0
        self.generate_invalid = generate_invalid
        self.fix_invalid = fix_invalid

    def is_configured(self):
        return True

    async def generate_slide_code(self, slide, paper_title, paper_summary) -> ManimSlide:
        self.generate_calls += 1
        cls = f"Slide{slide.slide_number:03d}"
        code = INVALID_CODE if self.generate_invalid else VALID_CODE.format(cls=cls)
        return ManimSlide(slide_number=slide.slide_number, class_name=cls, manim_code=code, expected_duration=20.0)

    async def fix_code(self, code, errors, class_name) -> str:
        self.fix_calls += 1
        return INVALID_CODE if self.fix_invalid else VALID_CODE.format(cls=class_name)


class FakeKodisc:
    """submit() hands out k1, k2, ...; check() walks `outcomes[job_id]` then stays on the last value."""

    def __init__(self):
        self.submits: list[tuple[str, str]] = []
        self.outcomes: dict[str, list[str]] = {}
        self.submit_status_code = None  # set to 402/401 to simulate fatal errors

    def is_configured(self):
        return True

    async def submit(self, code, class_name, quality="medium", aspect_ratio="16:9", **kw) -> KodiscResult:
        if self.submit_status_code:
            return KodiscResult(success=False, status_code=self.submit_status_code, error=f"HTTP {self.submit_status_code}")
        self.submits.append((class_name, code))
        return KodiscResult(success=True, status="queued", job_id=f"k{len(self.submits)}")

    async def check(self, job_id) -> KodiscResult:
        seq = self.outcomes.setdefault(job_id, ["running", "completed"])
        status = seq.pop(0) if len(seq) > 1 else seq[0]
        if status == "completed":
            return KodiscResult(success=True, status="completed", job_id=job_id,
                                video_url=f"https://cdn.example/{job_id}.mp4", thumbnail_url=f"https://cdn.example/{job_id}.png")
        if status == "failed":
            return KodiscResult(success=True, status="failed", job_id=job_id, error="NameError: name 'foo' is not defined")
        return KodiscResult(success=True, status=status, job_id=job_id)


class FakeTTS:
    def is_configured(self):
        return True

    async def generate_voiceover(self, text, **kw) -> VoiceoverResult:
        return VoiceoverResult(success=True, audio_data=b"ID3fake", file_size_bytes=7, duration_seconds=12.5)


class FakeR2:
    def __init__(self):
        self.uploads = {}

    def is_configured(self):
        return True

    def presign(self, key, expires=0):
        return f"https://r2.example/{key}?sig=fresh"

    async def presign_async(self, key):
        return self.presign(key)

    async def upload_async(self, data, name, content_type="audio/mpeg") -> UploadResult:
        self.uploads[name] = data
        return UploadResult(success=True, key=name, public_url=f"https://r2.example/{name}?sig=upload")


class FakeShotstack:
    def __init__(self):
        self.edits = []
        self.checks = 0

    def is_configured(self):
        return True

    async def submit_render(self, slides) -> ShotstackResult:
        self.edits.append(slides)
        return ShotstackResult(success=True, render_id="r1", status="queued")

    async def check_render_status(self, render_id) -> ShotstackResult:
        self.checks += 1
        if self.checks < 2:
            return ShotstackResult(success=True, render_id=render_id, status="rendering")
        return ShotstackResult(success=True, render_id=render_id, status="done", video_url="https://cdn.example/final.mp4")


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    f = SimpleNamespace(
        ocr=FakeOCR(), planner=FakePlanner(), manim=FakeManim(), kodisc=FakeKodisc(),
        tts=FakeTTS(), r2=FakeR2(), shotstack=FakeShotstack(),
    )
    for name, value in vars(f).items():
        monkeypatch.setattr(deps, name, value)
    monkeypatch.setattr(deps, "store", SqliteJobStore(tmp_path / "jobs.db"))
    monkeypatch.setattr(settings, "RUN_PASSCODE", "")
    return f


@pytest.fixture
def client(fakes, monkeypatch):
    from app.main import app

    async def fake_fetch(url, timeout=0):
        return b"FAKE-MP4-" + url.encode()

    monkeypatch.setattr("app.routers.jobs._fetch_bytes", fake_fetch)
    return TestClient(app)


def upload(client, name="paper.pdf", data=PDF_BYTES, headers=None):
    return client.post("/api/jobs", files={"file": (name, data, "application/pdf")}, headers=headers or {})
