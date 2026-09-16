"""Shared fixtures. Everything the tests measure against is rendered here."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scopewatch.synth import CaseScript, SceneSpec, render, write_case_video  # noqa: E402

DISTRACTOR_PX = 20_000


@pytest.fixture(scope="session")
def clean_scene():
    """A measurable field with a 12,000 pixel pool and an inflamed-serosa distractor."""
    return render(SceneSpec(pool_area_px=12_000, blush_area_px=DISTRACTOR_PX, seed=3))


@pytest.fixture(scope="session")
def empty_scene():
    """The same field with no blood on it at all."""
    return render(SceneSpec(pool_area_px=0, blush_area_px=DISTRACTOR_PX, seed=3))


@pytest.fixture(scope="session")
def big_scene():
    """A field a third covered in blood - the case that broke the first segmenter."""
    return render(SceneSpec(pool_area_px=72_000, blush_area_px=DISTRACTOR_PX, seed=29))


@pytest.fixture(scope="session")
def no_instrument_scene():
    """No steel in the field, so there is no scale reference and no millilitres."""
    return render(SceneSpec(pool_area_px=12_000, instrument_count=0, seed=3))


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory) -> Path:
    """A short scripted case: bleed at 14 s, fog at 7 to 9 s, wide device at 20 s."""
    out = tmp_path_factory.mktemp("cases") / "case.mp4"
    # The wide device enters at 25 s, which is the earliest it can mean anything:
    # the phase machine needs 20 s of sustained dissection behind it before a wide
    # shaft counts as a clip applier rather than a port trocar.
    script = CaseScript(
        duration_s=34.0,
        fps=8.0,
        bleed_start_s=14.0,
        bleed_rate_ml_per_min=1.8,
        fog_window_s=(7.0, 9.0),
        phase_plan=(
            (0.0, 0, False, False),
            (1.5, 1, False, False),
            (3.0, 2, False, True),
            (25.0, 2, True, True),
            (31.0, 2, True, False),
        ),
        seed=7,
    )
    write_case_video(script, out)
    return out


@pytest.fixture(scope="session")
def fogged_video(tmp_path_factory) -> Path:
    """A case the tool must decline to measure from beginning to end."""
    out = tmp_path_factory.mktemp("cases") / "fogged.mp4"
    write_case_video(
        CaseScript(duration_s=8.0, fps=8.0, bleed_start_s=None, fog_window_s=None,
                   fog_base=0.8, seed=9),
        out,
    )
    return out


@pytest.fixture(scope="session")
def quiet_video(tmp_path_factory) -> Path:
    """The same case with no bleed in it. Nothing here should trigger an onset."""
    out = tmp_path_factory.mktemp("cases") / "quiet.mp4"
    write_case_video(
        CaseScript(duration_s=24.0, fps=10.0, bleed_start_s=None, fog_window_s=None, seed=23),
        out,
    )
    return out
