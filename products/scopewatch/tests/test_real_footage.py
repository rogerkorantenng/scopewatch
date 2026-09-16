"""Regression tests from real laparoscopic footage.

Every test here is a defect that real, openly licensed video exposed and synthetic
scenes never did. The crops are in tests/fixtures/real with their credit and licence.
There is no true blood volume behind any of them; what they pin down is which pixels
are blood, which frames are refused, and how wide a real shaft is.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from scopewatch import blood, instruments, quality
from visioncore import stroke_width_profile

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "real"


def _read(name: str) -> np.ndarray:
    image = cv2.imread(str(FIXTURES / name), cv2.IMREAD_COLOR)
    assert image is not None, name
    return image


def _fraction(image: np.ndarray, method: str) -> tuple[float, np.ndarray]:
    lit = quality.field_mask(image)
    m, mask = blood.measure(image, lit, method=method)
    return m.area_fraction, mask


def test_a_pooled_blood_field_is_found():
    """WSES ulcer repair: the old segmenter read this pool as nothing at all."""
    image = _read("wses-pool-1050-crop.png")
    label = cv2.imread(str(FIXTURES / "wses-pool-1050-crop-label.png"), cv2.IMREAD_GRAYSCALE)
    truth = label == 255
    scored = label != 128
    _, new = _fraction(image, "chroma_scene")
    _, old = _fraction(image, "ratio_dark")
    recall_new = (new.astype(bool) & truth & scored).sum() / (truth & scored).sum()
    recall_old = (old.astype(bool) & truth & scored).sum() / (truth & scored).sum()
    assert recall_old < 0.05, "the defect this test exists for has changed shape"
    assert recall_new > 0.45, f"recall {recall_new:.2f} on a labelled pool"


def test_shadow_at_the_rim_of_the_scope_circle_is_not_blood():
    """Barroso hernia repair: 9.97 ml of 'blood' that was shadowed peritoneum."""
    image = _read("barroso-rim-827-crop.png")
    new, _ = _fraction(image, "chroma_scene")
    old, _ = _fraction(image, "ratio_dark")
    assert old > 0.2, "the defect this test exists for has changed shape"
    assert new < 0.01, f"{new:.1%} of a bloodless rim read as blood"


def test_the_inside_of_a_port_sleeve_is_not_blood():
    """Kavalakat omentectomy: the camera inside a pale sleeve read as a bleed."""
    image = _read("kavalakat-port-1650-crop.png")
    new, _ = _fraction(image, "chroma_scene")
    old, _ = _fraction(image, "ratio_dark")
    assert old > 0.05, "the defect this test exists for has changed shape"
    assert new < 0.03, f"{new:.1%} of a port sleeve read as blood"


def test_gloved_hands_in_an_open_abdomen_are_out_of_domain():
    """Gupta open cholecystectomy: measured as if laparoscopic, 0.00 ml throughout."""
    q = quality.assess(_read("gupta-glove-1019-crop.png"))
    assert "OUT_OF_DOMAIN" in q.reasons, q.to_dict()


def test_a_wet_shaft_is_measured_edge_to_edge_not_along_its_highlight():
    """The steel mask of a wet shaft is the stripe facing the light: half the shaft.
    That is why the shaft scale ran about twice too coarse on real footage. The width
    read by eye off a perpendicular saturation profile of this frame is about 40 px."""
    image = _read("wses-shaft-8s-crop.png")
    mask = instruments.metallic_mask(image, None)
    _count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    component = (labels == biggest).astype(np.uint8)
    saturation = cv2.GaussianBlur(
        cv2.cvtColor(image, cv2.COLOR_BGR2HSV)[:, :, 1].astype(np.float32), (3, 3), 0
    )
    width, profiles, spread = instruments.edge_width(saturation, component)
    medial = stroke_width_profile(component * 255, min_samples=12, trim_fraction=0.2).p50_px
    assert width is not None and profiles >= instruments.EDGE_MIN_PROFILES
    assert spread is not None and spread <= instruments.EDGE_MAX_SPREAD
    assert 34.0 <= width <= 46.0, width
    assert medial is not None and width > 1.8 * medial, (width, medial)
