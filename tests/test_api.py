from app.config import settings
from tests.conftest import FakeManim, upload


def test_full_pipeline(client, fakes):
    r = upload(client)
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    job_id = job["id"]
    assert job["step"] == "ocr_complete" and job["has_markdown"] is True

    r = client.post(f"/api/jobs/{job_id}/plan")
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    assert job["step"] == "plan_complete" and len(job["slides"]) == 2
    assert client.post(f"/api/jobs/{job_id}/plan").json()["cached"] is True
    assert fakes.planner.calls == 1

    for n in (1, 2):
        r = client.post(f"/api/jobs/{job_id}/slides/{n}/render")
        s = r.json()["slide"]
        assert s["status"] == "submitted" and s["kodisc_job_id"] and s["tier_used"] == "opus_primary"
        assert s["has_code"] is True and "code" not in s
        assert client.get(f"/api/jobs/{job_id}/slides/{n}").json()["slide"]["status"] == "rendering"
        s = client.get(f"/api/jobs/{job_id}/slides/{n}").json()["slide"]
        assert s["status"] == "done" and s["video_url"].endswith(".mp4")
    assert [c for c, _ in fakes.kodisc.submits] == ["Slide001", "Slide002"]
    assert "class Slide001" in client.get(f"/api/jobs/{job_id}/slides/1/code").json()["code"]

    for n in (1, 2):
        a = client.post(f"/api/jobs/{job_id}/voice/{n}").json()["audio"]
        assert a["status"] == "done" and a["duration_seconds"] == 12.5 and a["audio_url"]

    r = client.post(f"/api/jobs/{job_id}/assemble")
    assert r.json()["final"]["status"] == "submitted"
    assert client.get(f"/api/jobs/{job_id}/assemble").json()["final"]["status"] == "rendering"
    r = client.get(f"/api/jobs/{job_id}/assemble").json()
    assert r["final"]["status"] == "done" and r["step"] == "complete"

    edit = fakes.shotstack.edits[0]
    assert [a.audio_duration for a in edit] == [12.5, 12.5]

    doc = client.get(f"/api/jobs/{job_id}").json()
    assert doc["summary"]["slides_rendered"] == 2 and doc["final"]["video_url"].endswith("final.mp4")
    assert client.get("/api/jobs").json()["jobs"][0]["id"] == job_id


def test_tier_escalation_on_render_failure(client, fakes):
    fakes.kodisc.outcomes = {"k1": ["failed"], "k2": ["failed"], "k3": ["completed"]}
    job_id = upload(client).json()["job"]["id"]
    client.post(f"/api/jobs/{job_id}/plan")

    s = client.post(f"/api/jobs/{job_id}/slides/1/render").json()["slide"]
    assert s["tier"] == 1 and s["status"] == "submitted"
    s = client.get(f"/api/jobs/{job_id}/slides/1").json()["slide"]
    assert s["status"] == "retry" and s["tier"] == 2 and "NameError" in s["error"]

    s = client.post(f"/api/jobs/{job_id}/slides/1/render").json()["slide"]
    assert s["tier_used"] == "opus_retry" and fakes.manim.fix_calls == 1
    s = client.get(f"/api/jobs/{job_id}/slides/1").json()["slide"]
    assert s["status"] == "retry" and s["tier"] == 3

    s = client.post(f"/api/jobs/{job_id}/slides/1/render").json()["slide"]
    assert s["tier_used"] == "safe_template"
    code = client.get(f"/api/jobs/{job_id}/slides/1/code").json()["code"]
    assert "class Slide001" in code and "Fallback 1" in code and "FadeOut" not in code
    assert client.get(f"/api/jobs/{job_id}/slides/1").json()["slide"]["status"] == "done"


def test_static_validation_falls_back_to_safe_template(client, fakes, monkeypatch):
    monkeypatch.setattr("app.deps.manim", FakeManim(generate_invalid=True, fix_invalid=True))
    job_id = upload(client).json()["job"]["id"]
    client.post(f"/api/jobs/{job_id}/plan")
    s = client.post(f"/api/jobs/{job_id}/slides/1/render").json()["slide"]
    assert s["tier_used"] == "safe_template" and s["status"] == "submitted"


def test_fatal_vendor_error_is_flagged(client, fakes):
    fakes.kodisc.submit_status_code = 402
    job_id = upload(client).json()["job"]["id"]
    client.post(f"/api/jobs/{job_id}/plan")
    r = client.post(f"/api/jobs/{job_id}/slides/1/render").json()
    assert r["fatal"] is True and r["slide"]["status"] == "failed"
    assert client.get(f"/api/jobs/{job_id}").json()["fatal"] is True


def test_passcode_gate(client, fakes, monkeypatch):
    monkeypatch.setattr(settings, "RUN_PASSCODE", "secret")
    assert client.get("/api/config").json()["passcode_required"] is True
    assert upload(client).status_code == 401
    assert upload(client, headers={"X-Passcode": "wrong"}).status_code == 401
    assert upload(client, headers={"X-Passcode": "secret"}).status_code == 200
    assert client.get("/api/jobs").status_code == 200  # reads stay open


def test_upload_validation(client):
    assert upload(client, name="notes.txt").status_code == 400
    assert upload(client, data=b"hello").status_code == 400
    assert client.get("/api/jobs/zzzzzzzz").status_code == 404
    assert client.get("/api/jobs/../etc").status_code == 404
    assert client.get("/health").json()["status"] == "healthy"
