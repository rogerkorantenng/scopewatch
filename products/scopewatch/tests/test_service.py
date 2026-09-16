"""The HTTP surface, including the two routes a held checkpoint needs.

The checkpoint routes are the security-and-human-control part of the agentic
rubric, so they are tested as a contract: no anonymous decisions, no bare
dismissals, no resolving someone else's checkpoint by guessing an id.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from scopewatch.agent import AgentLoop, Observation
from scopewatch.service import REGISTRY, SAMPLE_VIDEO, app

client = TestClient(app)


@pytest.fixture
def held_loop():
    """A loop with one open checkpoint, registered under a known job id."""
    loop = AgentLoop()
    for t in (10.0, 12.0):
        loop.observe(
            Observation(index=int(t * 4), timestamp_ms=t * 1000.0,
                        phase="critical_approach", measurable=True,
                        evidence_uri="/api/jobs/testjob/evidence/x.jpg")
        )
    REGISTRY.put("testjob", loop)
    assert loop.open_checkpoint is not None
    return loop


# ---------------------------------------------------------------------------
# The basics
# ---------------------------------------------------------------------------


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["product"] == "scopewatch"


def test_version_states_the_opencv_it_is_running():
    r = client.get("/version")
    assert r.status_code == 200
    body = r.json()
    assert body["opencv_version"].startswith("5."), (
        "the competition requires OpenCV 5 and this is what a judge checks"
    )
    assert body["product"]["slug"] == "scopewatch"


def test_the_index_renders():
    r = client.get("/")
    assert r.status_code == 200
    assert "Scopewatch" in r.text


def test_config_offers_the_parameters_the_ui_needs():
    r = client.get("/api/config")
    assert r.status_code == 200
    names = {p["name"] for p in r.json()["params"]}
    assert {"stride", "shaft_mm", "film_depth_mm", "safety_view_established"} <= names


def test_the_product_says_plainly_what_it_is_not():
    description = client.get("/api/config").json()["product"]["description"]
    assert "not a medical device" in description.lower()


# ---------------------------------------------------------------------------
# The bundled sample
# ---------------------------------------------------------------------------


def test_a_judge_can_run_it_with_no_file_of_their_own():
    r = client.get("/api/sample")
    assert r.status_code == 200
    body = r.json()
    assert body["bytes"] > 100_000
    assert body["truth"]["bleed_start_s"] == 26.0
    assert SAMPLE_VIDEO.is_file()


def test_the_sample_downloads():
    r = client.get("/api/sample/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "video/mp4"
    assert len(r.content) > 100_000


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------


def test_an_unsupported_file_type_is_rejected_before_it_reaches_opencv():
    r = client.post(
        "/api/jobs",
        files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
        data={"params": "{}"},
    )
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "UNSUPPORTED_MEDIA"


def test_an_empty_upload_is_rejected():
    r = client.post(
        "/api/jobs",
        files={"file": ("clip.mp4", io.BytesIO(b""), "video/mp4")},
        data={"params": "{}"},
    )
    assert r.status_code == 400


def test_malformed_params_are_rejected_with_a_readable_message():
    r = client.post(
        "/api/jobs",
        files={"file": ("clip.mp4", io.BytesIO(b"x" * 64), "video/mp4")},
        data={"params": "{not json"},
    )
    assert r.status_code == 400
    assert "not valid JSON" in r.json()["error"]["message"]


def test_an_unknown_job_is_a_404():
    assert client.get("/api/jobs/doesnotexist").status_code == 404


# ---------------------------------------------------------------------------
# The checkpoint
# ---------------------------------------------------------------------------


def test_the_checkpoint_is_visible_over_http(held_loop):
    r = client.get("/api/jobs/testjob/checkpoints")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "held"
    assert body["open_checkpoint"] == held_loop.open_checkpoint.checkpoint_id
    assert body["checkpoints"][0]["reasons_offered"]


def test_a_checkpoint_cannot_be_confirmed_anonymously(held_loop):
    cp = held_loop.open_checkpoint.checkpoint_id
    r = client.post(f"/api/jobs/testjob/checkpoints/{cp}/confirm", json={})
    assert r.status_code == 400
    assert "named person" in r.json()["error"]["message"]
    assert held_loop.open_checkpoint is not None


def test_confirming_records_the_person(held_loop):
    cp = held_loop.open_checkpoint.checkpoint_id
    r = client.post(
        f"/api/jobs/testjob/checkpoints/{cp}/confirm",
        json={"actor": "S. Amoah", "note": "criterion three visible"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["checkpoint"]["state"] == "confirmed"
    assert body["checkpoint"]["decided_by"] == "S. Amoah"
    assert body["agent"]["open_checkpoint"] is None


def test_a_dismissal_without_a_reason_is_refused_and_offers_the_reasons(held_loop):
    cp = held_loop.open_checkpoint.checkpoint_id
    r = client.post(
        f"/api/jobs/testjob/checkpoints/{cp}/dismiss", json={"actor": "S. Amoah"}
    )
    assert r.status_code == 400
    assert r.json()["error"]["details"]["reasons_offered"]
    assert held_loop.open_checkpoint is not None


def test_a_dismissal_with_a_reason_is_recorded(held_loop):
    cp = held_loop.open_checkpoint.checkpoint_id
    r = client.post(
        f"/api/jobs/testjob/checkpoints/{cp}/dismiss",
        json={"actor": "S. Amoah", "reason": "Bail-out: subtotal cholecystectomy"},
    )
    assert r.status_code == 200
    assert r.json()["checkpoint"]["reason"] == "Bail-out: subtotal cholecystectomy"
    transitions = r.json()["agent"]["transitions"]
    assert transitions[-1]["to"] == "dismissed"
    assert transitions[-1]["actor"] == "S. Amoah"


def test_an_unknown_checkpoint_id_is_a_404(held_loop):
    r = client.post(
        "/api/jobs/testjob/checkpoints/deadbeef/confirm", json={"actor": "S. Amoah"}
    )
    assert r.status_code == 404


def test_an_unknown_job_has_no_loop():
    assert client.get("/api/jobs/nosuchjob/checkpoints").status_code == 404


# ---------------------------------------------------------------------------
# A whole job through the API
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_the_bundled_sample_runs_end_to_end_through_the_api():
    """The whole thing over HTTP, including the agent loop's own output.

    `TestClient` must be used as a context manager here. Outside one, starlette
    opens its portal for the duration of a single request and closes it again, so
    the analyzer's background task gets no event loop to run on between calls and
    the job sits at "running" until the test times out. Inside one, the portal
    stays up.
    """
    with TestClient(app) as client:
        _run_sample_job(client)


def _run_sample_job(client: TestClient) -> None:
    data = SAMPLE_VIDEO.read_bytes()
    r = client.post(
        "/api/jobs",
        files={"file": (SAMPLE_VIDEO.name, io.BytesIO(data), "video/mp4")},
        data={"params": '{"stride": 8, "use_dnn": false, "max_frames": 80}'},
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    import time

    deadline = time.time() + 240
    job = client.get(f"/api/jobs/{job_id}").json()
    while job["status"] in ("queued", "running") and time.time() < deadline:
        time.sleep(0.5)
        job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "done", job.get("error")
    result = job["result"]
    assert result["env"]["opencv_version"].startswith("5.")
    assert result["metrics"]["frames_analysed"] > 0
    assert result["results"]

    # The agent loop has to have produced something. A record with an empty loop is
    # the failure mode a recording of this product would show as a blank event log.
    agent = result["metrics"]["agent"]
    assert agent["transitions"], "the agent loop logged no transitions"
    assert agent["checkpoints"], "the wide device entered and no checkpoint was raised"
    assert agent["open_checkpoint"], "the checkpoint resolved itself, which it must not"
    assert result["evidence"], "no evidence frames were saved"
    assert result["metrics"]["onset"]["detected"], "the bleed in the sample was missed"
