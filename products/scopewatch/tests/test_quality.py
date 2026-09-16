"""The refusal gates. Each one has to fire when it should and stay quiet when it should.

The second half is the harder half. A gate that rejects everything is trivially safe
and useless, so every test that asserts a refusal has a partner asserting that the
same gate leaves a good frame alone.
"""

from __future__ import annotations

import numpy as np
import pytest
from scopewatch import quality
from scopewatch.config import Thresholds
from scopewatch.synth import SceneSpec, render

# ---------------------------------------------------------------------------
# The lit field
# ---------------------------------------------------------------------------


def test_the_aperture_is_found_and_the_black_surround_excluded(clean_scene):
    lit = quality.field_mask(clean_scene.image)
    fraction = float(lit.mean())
    # The synthetic aperture is a circle of radius 0.49 * min(w, h) in a 960x540
    # frame: pi * 264^2 / 518400 = 0.42.
    assert 0.38 < fraction < 0.46, f"lit fraction {fraction:.3f} is not the aperture"


def test_a_frame_with_no_aperture_falls_back_to_the_whole_image():
    image = np.full((200, 300, 3), 120, np.uint8)
    lit = quality.field_mask(image)
    assert lit.mean() == pytest.approx(1.0)


def test_counting_the_black_corners_would_deflate_every_fraction(clean_scene):
    """Why the aperture matters: the same mask over two denominators."""
    lit = quality.field_mask(clean_scene.image)
    whole = clean_scene.image.shape[0] * clean_scene.image.shape[1]
    assert int(lit.sum()) < 0.5 * whole


# ---------------------------------------------------------------------------
# Focus
# ---------------------------------------------------------------------------


def test_a_sharp_frame_passes(clean_scene):
    q = quality.assess(clean_scene.image)
    assert q.usable, q.reasons
    assert q.focus > Thresholds().focus_min


@pytest.mark.parametrize("sigma", [7.0, 9.0])
def test_a_badly_blurred_frame_is_refused(sigma):
    scene = render(SceneSpec(pool_area_px=12_000, blur_sigma=sigma, seed=5))
    q = quality.assess(scene.image)
    assert not q.usable
    assert "OUT_OF_FOCUS" in q.reasons or "LENS_FOGGED" in q.reasons


def test_a_mildly_soft_frame_is_still_measured():
    """The gate must not cost us frames a surgeon would call perfectly clear."""
    scene = render(SceneSpec(pool_area_px=12_000, blur_sigma=1.0, seed=5))
    q = quality.assess(scene.image)
    assert q.usable, q.reasons


# ---------------------------------------------------------------------------
# Fog
# ---------------------------------------------------------------------------


def test_a_fogged_lens_is_refused_as_fog_and_not_as_blur():
    """The useful thing to say is 'wipe the lens', not 'it is blurry'."""
    scene = render(SceneSpec(pool_area_px=12_000, fog=0.85, seed=5))
    q = quality.assess(scene.image)
    assert not q.usable
    assert q.reasons[0] == "LENS_FOGGED", q.reasons


def test_a_clear_lens_is_not_called_fogged(clean_scene):
    q = quality.assess(clean_scene.image)
    assert "LENS_FOGGED" not in q.reasons


def test_the_fog_statistic_rises_with_fog():
    levels = [0.0, 0.3, 0.6, 0.9]
    values = [
        quality.dark_channel(render(SceneSpec(pool_area_px=12_000, fog=f, seed=5)).image)
        for f in levels
    ]
    assert values == sorted(values), f"dark channel is not monotone in fog: {values}"


# ---------------------------------------------------------------------------
# Occlusion
# ---------------------------------------------------------------------------


def test_a_swab_across_the_field_is_refused():
    scene = render(SceneSpec(pool_area_px=8_000, occlusion=0.7, seed=5))
    q = quality.assess(scene.image)
    assert not q.usable
    assert "OCCLUDED" in q.reasons


def test_a_settled_pool_of_blood_is_not_called_an_occlusion(big_scene):
    """The first version of this gate rejected 39% of a measurable clip for this."""
    q = quality.assess(big_scene.image)
    assert "OCCLUDED" not in q.reasons, (
        f"a {big_scene.area_px} pixel pool was mistaken for an occluder "
        f"(occlusion statistic {q.occlusion:.3f})"
    )


def test_two_instruments_in_view_do_not_occlude_the_field(clean_scene):
    q = quality.assess(clean_scene.image)
    assert q.occlusion < Thresholds().occlusion_max


# ---------------------------------------------------------------------------
# Exposure
# ---------------------------------------------------------------------------


def test_a_blown_out_frame_is_refused():
    image = np.full((400, 600, 3), 255, np.uint8)
    q = quality.assess(image)
    assert not q.usable
    assert "EXPOSURE_CLIPPED" in q.reasons or "OCCLUDED" in q.reasons


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------


def test_the_ledger_counts_every_reason_and_every_frame():
    ledger = quality.QualityLedger()
    for fog in (0.0, 0.0, 0.9, 0.9, 0.9):
        scene = render(SceneSpec(pool_area_px=8_000, fog=fog, seed=5))
        ledger.add(quality.assess(scene.image))
    assert ledger.total == 5
    assert ledger.usable == 2
    assert ledger.usable_fraction == pytest.approx(0.4)
    assert ledger.by_reason.get("LENS_FOGGED") == 3
    assert ledger.to_dict()["rejected_by"]["LENS_FOGGED"] == 3


def test_a_refusal_carries_a_sentence_a_person_can_act_on():
    scene = render(SceneSpec(pool_area_px=8_000, fog=0.9, seed=5))
    q = quality.assess(scene.image)
    assert "lens" in q.message.lower() or "haze" in q.message.lower()
    assert q.message != "Measurable."
