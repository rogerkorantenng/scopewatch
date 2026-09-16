"""Instrument detection and the scale it produces.

The scale is the load-bearing number in this product: it enters the area squared,
so a 10% scale error is a 20% volume error. Everything here is a claim about how
well millimetres-per-pixel is recovered from an object whose size we chose.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from scopewatch import instruments
from scopewatch.quality import field_mask
from scopewatch.synth import SceneSpec, render


def test_both_shafts_are_found(clean_scene):
    lit = field_mask(clean_scene.image)
    shafts, entries, _ = instruments.find_shafts_and_entries(clean_scene.image, lit)
    assert entries == 2, f"two instruments entered the field, found {entries}"
    assert shafts, "no shaft survived the elongation and width filters"


def test_no_instruments_means_no_shafts(no_instrument_scene):
    lit = field_mask(no_instrument_scene.image)
    shafts, entries, _ = instruments.find_shafts_and_entries(no_instrument_scene.image, lit)
    assert entries == 0
    assert not shafts


def test_the_shaft_width_matches_what_was_drawn(clean_scene):
    lit = field_mask(clean_scene.image)
    shafts, _ = instruments.find_shafts(clean_scene.image, lit)
    widths = [s.width_px for s in shafts]
    truth = clean_scene.shaft_width_px
    assert widths, "nothing to measure"
    error = abs(float(np.median(widths)) - truth) / truth
    assert error < 0.05, f"shaft width {np.median(widths):.1f} px against a true {truth:.1f} px"


def test_the_scale_is_recovered_to_within_two_percent():
    errors = []
    for seed in (3, 11, 29, 47):
        scene = render(SceneSpec(pool_area_px=12_000, seed=seed))
        lit = field_mask(scene.image)
        reading, _ = instruments.read_frame(scene.image, lit, assumed_shaft_mm=5.0)
        assert reading.mm_per_px is not None
        errors.append(abs(reading.mm_per_px - scene.spec.mm_per_px) / scene.spec.mm_per_px)
    assert max(errors) < 0.02, f"worst scale error {max(errors):.2%}"


def test_no_scale_when_nothing_of_known_size_is_in_view(no_instrument_scene):
    lit = field_mask(no_instrument_scene.image)
    reading, _ = instruments.read_frame(no_instrument_scene.image, lit)
    assert reading.mm_per_px is None
    assert reading.scale_source == "none"


def test_an_operator_supplied_scale_overrides_the_shaft(clean_scene):
    lit = field_mask(clean_scene.image)
    reading, _ = instruments.read_frame(clean_scene.image, lit, mm_per_px_override=0.25)
    assert reading.mm_per_px == 0.25
    assert reading.scale_source == "operator"
    assert reading.mm_per_px_sigma == 0.0


def test_the_field_boundary_is_the_circle_not_the_rectangle(clean_scene):
    """The bug this function exists to fix: testing against the image rectangle
    finds no instrument at all, because the scope's circle stops hundreds of
    pixels short of the frame edge."""
    lit = field_mask(clean_scene.image)
    ring = instruments.field_boundary(lit, lit.shape)
    ys, xs = np.nonzero(ring)
    assert xs.min() > 5, "the ring is hugging the image edge, not the aperture"
    assert xs.max() < lit.shape[1] - 5


def test_a_diagonal_shaft_is_elongated_by_its_rotated_rectangle():
    """A bounding box says a 45 degree shaft is square. A minAreaRect does not."""
    mask = np.zeros((400, 400), np.uint8)
    cv2.line(mask, (20, 20), (380, 380), 1, 20)
    elongation, minor = instruments._rect_elongation(mask)
    assert elongation > 10.0, f"minAreaRect elongation {elongation:.1f}"
    assert 15 < minor < 30
    bbox_elongation = 1.0  # 360 x 360
    assert elongation > bbox_elongation * 5


def test_a_wide_device_shows_in_the_upper_tail_of_the_width_profile():
    """When a clip applier crosses a grasper the two merge, and only the p95 sees it."""
    narrow = render(SceneSpec(pool_area_px=4_000, wide_device=False, seed=5))
    wide = render(SceneSpec(pool_area_px=4_000, wide_device=True, seed=5))
    peaks = []
    for scene in (narrow, wide):
        lit = field_mask(scene.image)
        shafts, _ = instruments.find_shafts(scene.image, lit)
        peaks.append(max((s.width_p95_px for s in shafts), default=0.0))
    assert peaks[1] > 1.4 * peaks[0], f"p95 widths {peaks}"


def test_instruments_that_touch_are_still_counted_at_the_edge():
    """Merged in the middle, separate at the rim. The count comes from the rim."""
    scene = render(SceneSpec(pool_area_px=4_000, wide_device=True, seed=5))
    lit = field_mask(scene.image)
    _shafts, entries, _ = instruments.find_shafts_and_entries(scene.image, lit)
    assert entries == 2


def test_a_shaft_that_does_not_reach_the_edge_carries_no_scale():
    """A bright elongated blob in the middle of the field is not an instrument."""
    shaft = instruments.Shaft(
        label=1, bbox=(100, 100, 200, 30), area_px=4000, elongation=6.0,
        width_px=30.0, width_p95_px=32.0, width_iqr_px=1.0, merged=False,
        touches_border=False, tip=(300, 115), angle_deg=0.0,
    )
    mm_per_px, sigma, assumed = instruments.scale_from_shafts([shaft])
    assert mm_per_px is None and sigma == 0.0 and assumed is None


def test_the_scale_sigma_is_never_zero_when_it_came_from_a_shaft(clean_scene):
    """A manufactured shaft is 5 mm to a tolerance, and the scale cannot be
    better known than its reference."""
    lit = field_mask(clean_scene.image)
    reading, _ = instruments.read_frame(clean_scene.image, lit)
    assert reading.mm_per_px_sigma > 0.0
    assert reading.mm_per_px_sigma < 0.2 * reading.mm_per_px


def test_the_tip_is_the_end_inside_the_field(clean_scene):
    lit = field_mask(clean_scene.image)
    shafts, _ = instruments.find_shafts(clean_scene.image, lit)
    dist = cv2.distanceTransform(lit.astype(np.uint8), cv2.DIST_L2, 5)
    for shaft in shafts:
        x, y, w, h = shaft.bbox
        assert dist[shaft.tip[1], shaft.tip[0]] > 0, "the tip landed outside the lit field"
        assert x - 2 <= shaft.tip[0] <= x + w + 2
        assert y - 2 <= shaft.tip[1] <= y + h + 2


@pytest.mark.model
def test_the_dnn_channel_runs_and_says_what_it_is(clean_scene):
    """YOLOX-tiny in cv2.dnn. Skipped when the ONNX file is not on this machine."""
    from pathlib import Path

    from visioncore import YoloxDetector

    model_dir = Path(__file__).resolve().parents[1] / "models"
    try:
        detector = YoloxDetector(cache_dir=model_dir)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"YOLOX model unavailable: {exc}")
    objects = instruments.dnn_objects(detector, clean_scene.image)
    assert isinstance(objects, list)
    for obj in objects:
        assert "not a surgical instrument taxonomy" in obj["note"], (
            "the DNN channel must not imply a surgical detector we do not have"
        )
