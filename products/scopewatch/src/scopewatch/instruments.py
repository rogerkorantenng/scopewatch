"""Instruments in the field, and the scale they give us for free.

Two channels, and they do different jobs.

**The shaft channel (classical, always on).** Laparoscopic instruments are steel:
low chroma and bright against tissue that is neither. They enter from outside the
projected circle, so a real shaft touches the edge of the field. And they are long
and straight, so the medial axis of the mask is a line whose distance-transform
values are half the shaft width. That last property is the useful one, because a
laparoscopic shaft is manufactured at a known outer diameter - 5 mm for the common
sizes - which makes every instrument in view a calibration target. This is how
Scopewatch gets millimetres per pixel out of a monocular video with no marker, no
chessboard and nothing added to the theatre.

**The DNN channel (YOLOX-tiny in `cv2.dnn`, Apache-2.0).** Run on a decimated
schedule and reported honestly: the official YOLOX-tiny weights are trained on
COCO, and COCO has no surgical instrument classes. It cannot name a Maryland
dissector. What it does contribute is a licence-clean, ONNX-only, OpenCV-5 DNN
path that flags generic elongated foreign objects in the field and gives the
technical report a measured `cv2.dnn` latency on the new engine. Where the DNN and
the shaft channel disagree, the shaft channel wins and the disagreement is logged.
We say this plainly rather than implying a surgical detector we do not have; the
weights for one exist only behind dataset registration forms (see README).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from visioncore import stage, stroke_width_profile

from .config import (
    INSTRUMENT_BORDER_MARGIN_PX,
    INSTRUMENT_MIN_AREA_PX,
    INSTRUMENT_MIN_ELONGATION,
    INSTRUMENT_S_MAX,
    INSTRUMENT_V_MIN,
    SHAFT_DIAMETERS_MM,
    SHAFT_TOLERANCE_MM,
)

# The largest relative width spread that is treated as measurement uncertainty
# rather than as evidence that the component is not a single shaft.
MAX_WIDTH_SPREAD = 0.15


@dataclass(frozen=True)
class Shaft:
    """One instrument shaft: where it is, how wide it is, how sure we are."""

    label: int
    bbox: tuple[int, int, int, int]
    area_px: int
    elongation: float
    width_px: float
    width_p95_px: float
    width_iqr_px: float
    merged: bool
    touches_border: bool
    tip: tuple[int, int]
    angle_deg: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "bbox": list(self.bbox),
            "area_px": self.area_px,
            "elongation": round(self.elongation, 2),
            "width_px": round(self.width_px, 2),
            "width_p95_px": round(self.width_p95_px, 2),
            "width_iqr_px": round(self.width_iqr_px, 2),
            "merged": self.merged,
            "touches_border": self.touches_border,
            "tip": list(self.tip),
            "angle_deg": round(self.angle_deg, 1),
        }


@dataclass
class InstrumentReading:
    """What one frame said about the instruments and the scale."""

    shafts: list[Shaft] = field(default_factory=list)
    entries: int = 0
    mm_per_px: float | None = None
    mm_per_px_sigma: float = 0.0
    assumed_shaft_mm: float | None = None
    scale_source: str = "none"
    dnn_objects: list[dict[str, Any]] = field(default_factory=list)
    dnn_ran: bool = False

    @property
    def count(self) -> int:
        """How many instruments are in the field.

        Counted at the edge of the projected circle, not in the middle. Two
        instruments working on the same structure touch, and a component count in
        the middle of the field then says "one". The number of separate places the
        steel crosses into the field is stable under that.
        """
        return max(self.entries, len(self.shafts))

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "entries": self.entries,
            "shafts": [s.to_dict() for s in self.shafts],
            "mm_per_px": None if self.mm_per_px is None else round(self.mm_per_px, 5),
            "mm_per_px_sigma": round(self.mm_per_px_sigma, 5),
            "assumed_shaft_mm": self.assumed_shaft_mm,
            "scale_source": self.scale_source,
            "dnn_ran": self.dnn_ran,
            "dnn_objects": list(self.dnn_objects),
        }


# ---------------------------------------------------------------------------
# The metallic mask
# ---------------------------------------------------------------------------


def metallic_mask(image: np.ndarray, field_mask: np.ndarray | None = None) -> np.ndarray:
    """Low-saturation, high-value pixels inside the lit field: steel, not tissue."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    sat, val = hsv[:, :, 1], hsv[:, :, 2]
    mask = ((sat <= INSTRUMENT_S_MAX) & (val >= INSTRUMENT_V_MIN)).astype(np.uint8)
    if field_mask is not None:
        mask = cv2.bitwise_and(mask, field_mask.astype(np.uint8))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)


def field_boundary(field_mask: np.ndarray | None, shape: tuple[int, int]) -> np.ndarray:
    """A one-pixel ring around the *lit* region, not around the image rectangle.

    This matters more than it sounds. A laparoscope projects a circle, so an
    instrument entering through a port crosses the edge of that circle several
    hundred pixels from the edge of the frame. Testing against the image rectangle
    finds nothing and the scale silently disappears - which is exactly the bug this
    function was written to fix.
    """
    height, width = shape
    if field_mask is None:
        ring = np.zeros((height, width), np.uint8)
        m = INSTRUMENT_BORDER_MARGIN_PX
        ring[:m, :] = 1
        ring[-m:, :] = 1
        ring[:, :m] = 1
        ring[:, -m:] = 1
        return ring
    mask = field_mask.astype(np.uint8)
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * INSTRUMENT_BORDER_MARGIN_PX + 1,) * 2
    )
    return cv2.subtract(mask, cv2.erode(mask, kernel))


def _rect_elongation(component: np.ndarray) -> tuple[float, float]:
    """Aspect ratio and minor side of the minimum-area rectangle, in pixels.

    The bounding box is useless here: a shaft at 45 degrees has a nearly square
    bounding box and would be thrown away as a blob. The rotated rectangle is the
    shape the object actually has.
    """
    contours, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return 0.0, 0.0
    biggest = max(contours, key=cv2.contourArea)
    if len(biggest) < 5:
        return 0.0, 0.0
    (_cx, _cy), (rw, rh), _angle = cv2.minAreaRect(biggest)
    long_side, short_side = max(rw, rh), min(rw, rh)
    if short_side <= 0:
        return 0.0, 0.0
    return long_side / short_side, short_side


def _tip_and_angle(
    component: np.ndarray,
    bbox: tuple[int, int, int, int],
    field_dist: np.ndarray | None = None,
) -> tuple[tuple[int, int], float]:
    """The working end of the shaft, and the shaft's angle in the frame.

    PCA on the component's pixels gives the axis. Of the two ends, the tip is the
    one further inside the lit field - measured on a distance transform of the
    field mask, not on distance to the image rectangle, because the scope's circle
    is where an instrument actually enters.
    """
    ys, xs = np.nonzero(component)
    if xs.size == 0:
        x, y, w, h = bbox
        return (x + w // 2, y + h // 2), 0.0
    pts = np.stack([xs, ys], axis=1).astype(np.float32)
    centred = pts - pts.mean(axis=0)
    _, _, vt = np.linalg.svd(centred, full_matrices=False)
    axis = vt[0]
    proj = centred @ axis
    candidates = [pts[int(np.argmin(proj))], pts[int(np.argmax(proj))]]
    height, width = component.shape

    def inwardness(p: np.ndarray) -> float:
        col, row = int(round(p[0])), int(round(p[1]))
        if field_dist is not None:
            return float(field_dist[min(max(row, 0), height - 1), min(max(col, 0), width - 1)])
        return float(min(col, row, width - 1 - col, height - 1 - row))

    tip = max(candidates, key=inwardness)
    angle = float(np.degrees(np.arctan2(axis[1], axis[0])))
    return (int(round(tip[0])), int(round(tip[1]))), angle


def find_shafts(
    image: np.ndarray,
    field_mask: np.ndarray | None = None,
    *,
    min_area_px: int = INSTRUMENT_MIN_AREA_PX,
    min_elongation: float = INSTRUMENT_MIN_ELONGATION,
) -> tuple[list[Shaft], np.ndarray]:
    """Find instrument shafts and measure each one's width on its medial axis."""
    with stage("instruments:shafts"):
        mask = metallic_mask(image, field_mask)
        ring = field_boundary(field_mask, mask.shape)
        lit = (field_mask.astype(np.uint8) if field_mask is not None
               else np.ones(mask.shape, np.uint8))
        field_dist = cv2.distanceTransform(lit, cv2.DIST_L2, 5)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        shafts: list[Shaft] = []
        kept = np.zeros(mask.shape, np.uint8)
        for label in range(1, count):
            x, y, w, h, area = (int(v) for v in stats[label])
            if area < min_area_px:
                continue
            component = (labels == label).astype(np.uint8)
            elongation, _minor = _rect_elongation(component)
            on_border = bool(cv2.bitwise_and(component, ring).any())
            # Two instruments working on the same structure touch, and the union of
            # two crossed shafts is not elongated. Rejecting it loses both, and with
            # them the scale. So a large border-crossing blob is kept and flagged
            # `merged`: its median width is still the shaft width (most of the
            # medial axis runs along a shaft), and the evaluation reports the two
            # cases separately.
            merged = elongation < min_elongation
            if merged and not (on_border and area >= 3 * min_area_px):
                continue
            # trim_fraction drops the flared jaws at the working end and the
            # partial cross-section at the port, leaving the parallel shaft.
            profile = stroke_width_profile(component * 255, min_samples=12, trim_fraction=0.2)
            if not profile.ok or profile.p50_px is None:
                continue
            spread = float((profile.p90_px or profile.p50_px) - profile.p50_px)
            tip, angle = _tip_and_angle(component, (x, y, w, h), field_dist)
            shafts.append(
                Shaft(
                    label=label,
                    bbox=(x, y, w, h),
                    area_px=area,
                    elongation=elongation,
                    width_px=float(profile.p50_px),
                    width_p95_px=float(profile.p95_px or profile.p50_px),
                    width_iqr_px=abs(spread),
                    merged=merged,
                    touches_border=on_border,
                    tip=tip,
                    angle_deg=angle,
                )
            )
            kept[labels == label] = 255
        shafts.sort(key=lambda s: -s.area_px)
        return shafts, kept


def count_entries(
    mask: np.ndarray,
    ring: np.ndarray,
    *,
    min_px: int = 24,
    min_component_px: int = INSTRUMENT_MIN_AREA_PX,
) -> int:
    """Distinct places where steel crosses into the lit field.

    The crossing has to belong to something substantial. A specular highlight sitting
    on the rim of the projected circle is low-saturation and bright, exactly like
    steel, and counting it puts a phantom instrument in an empty field - which then
    puts the phase machine into `exposure` for a case that has not started.
    """
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    substantial = np.zeros(mask.shape, np.uint8)
    for i in range(1, count):
        if stats[i, cv2.CC_STAT_AREA] >= min_component_px:
            substantial[labels == i] = 1
    crossings = cv2.bitwise_and(substantial, ring)
    n, _l, cstats, _c = cv2.connectedComponentsWithStats(crossings, 8)
    return sum(1 for i in range(1, n) if cstats[i, cv2.CC_STAT_AREA] >= min_px)


# ---------------------------------------------------------------------------
# Scale
# ---------------------------------------------------------------------------


def scale_from_shafts(
    shafts: list[Shaft],
    *,
    assumed_mm: float = 5.0,
    match_catalogue: bool = True,
) -> tuple[float | None, float, float | None]:
    """Millimetres per pixel from the widest border-touching shaft.

    Returns (mm_per_px, sigma, assumed_shaft_mm). `None` when nothing in the frame
    can carry a scale, which is a refusal the caller must surface, not a zero.

    Only shafts that touch the border are used: a bright elongated blob that does
    not reach the edge of the projected circle is more likely a highlight on a clip
    or a piece of gauze than an instrument entering through a port.

    The sigma combines the manufacturing tolerance of the reference (a real 5 mm
    shaft is 5 mm to about a tenth) with the spread of the medial-axis width
    samples, which is what perspective foreshortening and a wet shaft do to the
    measurement.
    """
    usable = [s for s in shafts if s.touches_border and s.width_px > 2.0]
    if not usable:
        return None, 0.0, None
    # Prefer a shaft that is on its own. A merged component is two instruments, and
    # its width distribution is bimodal: the spread between its median and its 90th
    # percentile is the difference between two different instruments, not the
    # uncertainty in measuring one. Taken as an uncertainty it reached 97% on a
    # sample case, which widened the reported volume interval to nearly six times
    # the estimate and made the number useless.
    singles = [s for s in usable if not s.merged]
    pool = singles or usable
    shaft = max(pool, key=lambda s: s.area_px)
    diameter_mm = assumed_mm
    if match_catalogue and len(pool) >= 2:
        # Two instruments of the same catalogue size should measure the same width.
        # If the widest is close to double the narrowest, it is a 10 mm device and
        # the narrow one is the better reference.
        widths = sorted(s.width_px for s in pool)
        if widths[-1] > 1.7 * widths[0]:
            shaft = min(pool, key=lambda s: s.width_px)
            diameter_mm = min(SHAFT_DIAMETERS_MM, key=lambda d: abs(d - assumed_mm))
    mm_per_px = diameter_mm / shaft.width_px
    rel_tolerance = SHAFT_TOLERANCE_MM / diameter_mm
    rel_measurement = shaft.width_iqr_px / shaft.width_px if shaft.width_px else 0.0
    # Capped, for the reason above. Past this the spread is telling us the component
    # is not one shaft, which is a segmentation fact rather than a measurement
    # uncertainty, and the frame is better handled by the case-level median.
    rel_measurement = min(rel_measurement, MAX_WIDTH_SPREAD)
    sigma = mm_per_px * float(np.hypot(rel_tolerance, rel_measurement))
    return mm_per_px, sigma, diameter_mm


# ---------------------------------------------------------------------------
# The DNN channel
# ---------------------------------------------------------------------------


def dnn_objects(detector: Any, image: np.ndarray, *, score: float = 0.25) -> list[dict[str, Any]]:
    """Run YOLOX-tiny and report what it saw, without pretending it saw instruments."""
    detections = detector.detect(image)
    return [
        {
            "bbox": [round(v, 1) for v in d.bbox],
            "score": round(float(d.score), 3),
            "class_name": d.class_name,
            "note": "COCO class; not a surgical instrument taxonomy",
        }
        for d in detections
        if d.score >= score
    ]


def find_shafts_and_entries(
    image: np.ndarray, field_mask: np.ndarray | None = None
) -> tuple[list[Shaft], int, np.ndarray]:
    shafts, kept = find_shafts(image, field_mask)
    mask = metallic_mask(image, field_mask)
    ring = field_boundary(field_mask, mask.shape)
    return shafts, count_entries(mask, ring), kept


def read_frame(
    image: np.ndarray,
    field_mask: np.ndarray | None = None,
    *,
    assumed_shaft_mm: float = 5.0,
    mm_per_px_override: float | None = None,
    detector: Any | None = None,
    dnn_score: float = 0.25,
) -> tuple[InstrumentReading, np.ndarray]:
    """Everything one frame says about instruments and scale."""
    shafts, entries, mask = find_shafts_and_entries(image, field_mask)
    if mm_per_px_override is not None and mm_per_px_override > 0:
        mm_per_px, sigma, assumed = mm_per_px_override, 0.0, None
        source = "operator"
    else:
        mm_per_px, sigma, assumed = scale_from_shafts(shafts, assumed_mm=assumed_shaft_mm)
        source = "instrument_shaft" if mm_per_px else "none"

    reading = InstrumentReading(
        shafts=shafts,
        entries=entries,
        mm_per_px=mm_per_px,
        mm_per_px_sigma=sigma,
        assumed_shaft_mm=assumed,
        scale_source=source,
    )
    if detector is not None:
        reading.dnn_objects = dnn_objects(detector, image, score=dnn_score)
        reading.dnn_ran = True
    return reading, mask
