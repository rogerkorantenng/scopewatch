"""Blood segmentation and the area-to-volume arithmetic.

These assert on numbers, not on "it ran". Ground truth is set before the pixels
exist, so every tolerance here is a real claim about the estimator.
"""

from __future__ import annotations

import numpy as np
import pytest
from scopewatch import blood
from scopewatch.quality import field_mask
from scopewatch.synth import SceneSpec, render


def dice(truth: np.ndarray, predicted: np.ndarray) -> float:
    t, p = truth.astype(bool), predicted.astype(bool)
    total = int(t.sum()) + int(p.sum())
    return 1.0 if total == 0 else 2.0 * float((t & p).sum()) / total


def measure_scene(scene, method: str = blood.SEGMENTERS and "ratio_dark"):
    lit = field_mask(scene.image)
    mask, _ = blood.blood_mask(scene.image, lit, method=method)
    mask, pools, largest = blood.drop_small_pools(mask)
    return mask, pools, largest


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------


def test_finds_a_pool_it_was_given(clean_scene):
    mask, pools, _ = measure_scene(clean_scene)
    assert pools >= 1
    assert dice(clean_scene.blood_mask, mask) > 0.85


def test_a_field_with_no_blood_returns_almost_nothing(empty_scene):
    """Otsu would return half the abdomen here. The mode-outlier test must not."""
    mask, _, _ = measure_scene(empty_scene)
    field = int(field_mask(empty_scene.image).sum())
    assert int(mask.sum()) < 0.02 * field, (
        f"{int(mask.sum())} false positive pixels on an empty field of {field}"
    )


def test_a_field_a_third_covered_is_not_missed(big_scene):
    """The inversion case: when blood is the mode, a mode-based cut must not flip."""
    mask, _, _ = measure_scene(big_scene)
    assert int(mask.sum()) > 0.7 * big_scene.area_px
    assert dice(big_scene.blood_mask, mask) > 0.9


def test_inflamed_serosa_is_not_counted_as_blood():
    """Red and not dark. A redness-only segmenter calls this a haemorrhage."""
    scene = render(SceneSpec(pool_area_px=0, blush_area_px=40_000, seed=11))
    mask, _, _ = measure_scene(scene)
    assert int(mask.sum()) < 0.25 * 40_000


def test_two_votes_beat_redness_alone_on_the_distractor():
    """The experiment's conclusion, pinned as a test so it cannot silently reverse."""
    scores = {name: [] for name in ("ratio", "ratio_dark")}
    for seed in (3, 11, 29):
        scene = render(SceneSpec(pool_area_px=12_000, blush_area_px=20_000, seed=seed))
        lit = field_mask(scene.image)
        for name in scores:
            mask, _ = blood.blood_mask(scene.image, lit, method=name)
            mask, _, _ = blood.drop_small_pools(mask)
            scores[name].append(dice(scene.blood_mask, mask))
    assert np.mean(scores["ratio_dark"]) > np.mean(scores["ratio"])


def test_a_surface_vessel_is_a_line_not_a_pool():
    """A long thin red-and-dark component must not survive the width criterion."""
    mask = np.zeros((300, 400), np.uint8)
    import cv2

    cv2.line(mask, (20, 150), (380, 160), 1, 5)  # 360 x 5 = 1800 px, well over min area
    kept, pools, _ = blood.drop_small_pools(mask, min_area=200)
    assert pools == 0
    assert int(kept.sum()) == 0


def test_a_round_pool_of_the_same_area_survives():
    import cv2

    mask = np.zeros((300, 400), np.uint8)
    cv2.circle(mask, (200, 150), 24, 1, -1)  # about 1800 px, but compact
    kept, pools, largest = blood.drop_small_pools(mask, min_area=200)
    assert pools == 1
    assert largest > 1500
    assert int(kept.sum()) > 1500


def test_unknown_method_raises():
    with pytest.raises(ValueError, match="unknown segmentation method"):
        blood.blood_mask(np.zeros((10, 10, 3), np.uint8), method="hue-vibes")


# ---------------------------------------------------------------------------
# Specular highlights
# ---------------------------------------------------------------------------


def test_speculars_are_excluded_from_the_field_they_are_measured_against(clean_scene):
    lit = field_mask(clean_scene.image)
    _mask, valid = blood.blood_mask(clean_scene.image, lit, method="ratio_dark")
    assert int(valid.sum()) < int(lit.sum()), "speculars were not removed from the field"


# ---------------------------------------------------------------------------
# Area to volume
# ---------------------------------------------------------------------------


def test_no_scale_means_no_millilitres(clean_scene):
    """Area fraction without a scale is honest. Millilitres without a scale is not."""
    lit = field_mask(clean_scene.image)
    m, _ = blood.measure(clean_scene.image, lit, method="ratio_dark", mm_per_px=None)
    assert m.volume_ml is None
    assert m.measured is False
    assert m.area_fraction > 0.0, "the unitless quantity is still reported"


def test_volume_is_area_times_depth():
    """1 ml is 1000 cubic millimetres and the arithmetic must say so exactly."""
    lit = np.ones((200, 200), np.uint8)
    image = np.zeros((200, 200, 3), np.uint8)
    m, _ = blood.measure(image, lit, method="ratio_dark", mm_per_px=0.1, depth_mm=2.0)
    assert m.volume_ml == 0.0  # a black frame has no blood on it
    # And directly on the formula, with a known area:
    area_px, mm_per_px, depth = 10_000, 0.1, 2.0
    expected_ml = area_px * mm_per_px**2 * depth / 1000.0
    assert expected_ml == pytest.approx(0.2)


def test_the_interval_is_wider_for_a_small_pool_than_a_large_one():
    assert blood.relative_area_sigma(2_000) > blood.relative_area_sigma(60_000)
    assert blood.relative_area_sigma(60_000) < 0.10
    assert blood.relative_area_sigma(0) == 1.0


def test_the_upper_bound_carries_the_surface_tilt_term():
    """Tilt can only make a pool larger than its projection, never smaller."""
    lit = np.ones((100, 100), np.uint8)
    image = np.zeros((100, 100, 3), np.uint8)
    m, _ = blood.measure(image, lit, method="ratio_dark", mm_per_px=0.1)
    assert blood.TILT_AREA_FACTOR > 1.0
    assert m.volume_ml_low == 0.0 and m.volume_ml_high == 0.0  # nothing to scale


@pytest.mark.parametrize("area", [12_000, 36_000, 72_000])
def test_the_reported_interval_contains_the_truth(area):
    from scopewatch import instruments

    covered = []
    for seed in (3, 11, 29):
        scene = render(SceneSpec(pool_area_px=area, blush_area_px=20_000, seed=seed + area))
        lit = field_mask(scene.image)
        reading, _ = instruments.read_frame(scene.image, lit)
        m, _ = blood.measure(
            scene.image,
            lit,
            method="ratio_dark",
            mm_per_px=reading.mm_per_px,
            mm_per_px_sigma=reading.mm_per_px_sigma,
            scale_source=reading.scale_source,
        )
        assert m.volume_ml is not None, "an instrument was in view, so there is a scale"
        covered.append(m.volume_ml_low <= scene.volume_ml <= m.volume_ml_high)
    assert all(covered), f"interval missed the truth on {covered.count(False)} of 3 scenes"


def test_a_large_pool_is_measured_to_within_ten_percent(big_scene):
    mask, _, _ = measure_scene(big_scene)
    error = abs(int(mask.sum()) - big_scene.area_px) / big_scene.area_px
    assert error < 0.10, f"area error {error:.1%} on a {big_scene.area_px} pixel pool"


def test_a_small_pool_is_flagged_as_unreliable_rather_than_reported_confidently():
    scene = render(SceneSpec(pool_area_px=1_200, blush_area_px=20_000, seed=7))
    lit = field_mask(scene.image)
    m, _ = blood.measure(scene.image, lit, method="ratio_dark", mm_per_px=0.09)
    assert m.reliable is False
    assert m.volume_ml_high > 1.5 * (m.volume_ml or 0.0), (
        "a pool near the false-positive floor must carry a wide interval"
    )
