"""Blood on the field: segment it, measure its area, turn area into a volume interval.

The hard part is not finding red pixels. Everything in an abdomen is red. The
discriminator between perfused tissue and pooled blood is that pooled blood is
*both* further along the red-green axis *and* darker, because a pool absorbs the
scope's own light instead of scattering it back. That is why the winning decision
here is two-dimensional in CIE Lab and not a hue range in HSV; `experiments.py`
scores five candidates against masks known by construction and writes the numbers
into docs/evaluation.md.

Area to volume is where a tool like this usually starts lying. Pixel area is not
millilitres. To get from one to the other you need a scale (millimetres per pixel,
recovered from an object of known size in the same plane) and a depth (how thick
the film is, which a single camera cannot see). We recover the first and we refuse
to pretend about the second: the depth is an assumption with a stated range, and
every volume Scopewatch reports is the interval that range produces, never a point.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from visioncore import stage

from .config import (
    FILM_DEPTH_MM_HIGH,
    FILM_DEPTH_MM_LOW,
    FILM_DEPTH_MM_NOMINAL,
    LAB_A_MIN,
    LAB_L_PERCENTILE,
    MIN_POOL_AREA_PX,
    MIN_POOL_WIDTH_PX,
    MORPH_KERNEL,
    SPECULAR_S_MAX,
    SPECULAR_V_MIN,
)

# Segmentation is not perfect and saying so costs nothing. But a single relative
# error is the wrong shape for this estimator, and the area sweep shows why: the
# error is not a constant percentage, it is a roughly constant *number of pixels*
# of false positive - surface vessels and inflamed serosa that survive both votes -
# divided by however big the pool is. At 70,000 pixels that floor is under 1% of
# the answer; at 4,000 pixels it is most of it.
#
# So the uncertainty is a function of the measurement. `FALSE_POSITIVE_FLOOR_PX` is
# the median area returned on synthetic fields that contain no blood at all;
# `AREA_SHAPE_SIGMA` is what is left over once the pool is large enough for the
# floor not to matter - boundary placement, the specular exclusion, morphology.
# Both come from `evaluate.py` and both are quoted in docs/evaluation.md.
# Both of these are deliberately larger than the synthetic sweep measures, and that
# is a judgement rather than an oversight.
#
# What the sweep measures, once the illumination estimate and the darkness cut were
# fixed: a false-positive floor of **zero pixels** on fields containing no blood, and
# a relative area error with a standard deviation of **0.54%** on pools of four
# thousand pixels and up. Printing an interval built from those numbers would claim a
# precision that belongs to the renderer, not to tissue. A synthetic pool has a clean
# boundary, a single illuminant and no fat, no bile, no cautery char and no irrigation
# fluid, and the real floor is unknown because we have no clinical video.
#
# So the floor is set at 600 pixels rather than zero, and the shape sigma at 5% rather
# than 0.54%, roughly a ten-fold inflation of what was measured. If and when clinical
# video is available these should be re-fitted on it, and docs/evaluation.md says so.
FALSE_POSITIVE_FLOOR_PX = 600.0
AREA_SHAPE_SIGMA = 0.05


def relative_area_sigma(area_px: float) -> float:
    """1-sigma relative error on a measured pool area of this size."""
    if area_px <= 0:
        return 1.0
    return float(np.hypot(FALSE_POSITIVE_FLOOR_PX / area_px, AREA_SHAPE_SIGMA))


# Below this the assumed false-positive floor is a quarter of the answer or more, and
# a percentage stops being worth printing. The area is still reported and the volume
# still carries its interval; the measurement is flagged unreliable so the reader
# knows which side of the line it is on, and the onset detector will not declare an
# onset on a frame this flags.
MIN_RELIABLE_POOL_PX = 2400

# The scale recovered from an instrument shaft is isotropic and local: it says how
# many millimetres a pixel spans at that shaft's distance. It says nothing about the
# orientation of the *surface the blood is lying on*. A pool on peritoneum tilted
# away from the camera projects to a smaller area than it has, by cos(tilt), and
# multiplying pixels by an isotropic scale therefore under-reports it.
#
# A single camera with no planar reference cannot recover that tilt, so it is not
# estimated - it is bounded. A laparoscope is worked at roughly normal incidence to
# the structure of interest, and beyond about 40 degrees the surgeon repositions
# because they cannot see what they are doing either. 1/cos(40 deg) = 1.305, so the
# upper end of every area interval is widened by 30%. The lower end is not: tilt can
# only make the true area larger than the projection, never smaller.
SURFACE_TILT_MAX_DEG = 40.0
TILT_AREA_FACTOR = 1.0 / float(np.cos(np.radians(SURFACE_TILT_MAX_DEG)))


@dataclass(frozen=True)
class BloodMeasurement:
    """One frame's worth of blood, with everything needed to audit the number."""

    area_px: int
    field_px: int
    area_fraction: float
    pools: int
    largest_pool_px: int
    specular_px: int
    area_mm2: float | None = None
    area_mm2_low: float | None = None
    area_mm2_high: float | None = None
    volume_ml: float | None = None
    volume_ml_low: float | None = None
    volume_ml_high: float | None = None
    mm_per_px: float | None = None
    scale_source: str = "none"
    reliable: bool = True

    @property
    def measured(self) -> bool:
        return self.volume_ml is not None

    def to_dict(self) -> dict[str, Any]:
        def r(v: float | None, n: int = 3) -> float | None:
            return None if v is None else round(float(v), n)

        return {
            "area_px": self.area_px,
            "field_px": self.field_px,
            "area_fraction": round(self.area_fraction, 5),
            "pools": self.pools,
            "largest_pool_px": self.largest_pool_px,
            "specular_px": self.specular_px,
            "area_mm2": r(self.area_mm2, 1),
            "area_mm2_low": r(self.area_mm2_low, 1),
            "area_mm2_high": r(self.area_mm2_high, 1),
            "volume_ml": r(self.volume_ml),
            "volume_ml_low": r(self.volume_ml_low),
            "volume_ml_high": r(self.volume_ml_high),
            "mm_per_px": r(self.mm_per_px, 5),
            "scale_source": self.scale_source,
            "measured": self.measured,
            "reliable": self.reliable,
            "relative_sigma": round(relative_area_sigma(self.area_px), 4),
        }


# ---------------------------------------------------------------------------
# Specular highlights
# ---------------------------------------------------------------------------


def specular_mask(image: np.ndarray) -> np.ndarray:
    """Near-white, low-chroma pixels: the scope's own light coming straight back.

    These sit *inside* pools as often as on tissue. Left in, they punch holes in a
    pool and the area is under-reported; classed as blood, a wet drape reads as
    haemorrhage. They are excluded from both the blood mask and the field it is
    measured against, and the count is reported so the exclusion is visible.
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    sat, val = hsv[:, :, 1], hsv[:, :, 2]
    mask = ((val >= SPECULAR_V_MIN) & (sat <= SPECULAR_S_MAX)).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    return cv2.dilate(mask, kernel)


# ---------------------------------------------------------------------------
# Segmentation - the candidates the experiment chooses between
# ---------------------------------------------------------------------------


def _clean(mask: np.ndarray) -> np.ndarray:
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (MORPH_KERNEL, MORPH_KERNEL))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)


# Otsu is the wrong tool here and it took the sweep to see it. Otsu assumes two
# comparable classes. A frame with a 30 ml pool has blood on about 4% of the lit
# field, and a frame with no bleeding has none at all - so Otsu splits the *tissue*,
# down the fat-against-vessel axis, and hands back half the abdomen with complete
# confidence. Every candidate below therefore thresholds against the tissue mode
# instead: find the dominant population, measure its spread on the side blood
# cannot contaminate, and take what lies far above it. That works when the target
# is 0.1% of the field and it returns nothing when the target is not there, which
# is the behaviour a measurement instrument has to have.
#
# The two constants are the operating point; `evaluate.py` sweeps them and
# docs/evaluation.md reports what they cost.
OUTLIER_K = 4.0  # standard deviations above the tissue mode
OUTLIER_MIN_LEVELS = 10.0  # and never closer than this many 8-bit levels


def _mode_and_spread(values: np.ndarray, *, upper_tail: bool = True) -> tuple[float, float]:
    """The dominant mode of an 8-bit channel and the spread of its clean side.

    The clean side is the one the target class cannot reach: when we are hunting a
    high tail we measure the spread below the mode, and vice versa. A median
    absolute deviation taken over the whole distribution would be inflated by the
    very pixels we are trying to find.
    """
    hist = cv2.calcHist([values.reshape(-1, 1)], [0], None, [256], [0, 256]).ravel()
    hist = cv2.GaussianBlur(hist.reshape(-1, 1), (1, 9), 0).ravel()
    mode = float(int(np.argmax(hist)))
    clean = values[values <= mode] if upper_tail else values[values >= mode]
    if clean.size < 32:
        return mode, 1.0
    mad = float(np.median(np.abs(clean.astype(np.float32) - mode)))
    return mode, max(1.0, 1.4826 * mad)


def _above_tissue(
    channel: np.ndarray,
    valid: np.ndarray,
    *,
    k: float = OUTLIER_K,
    min_levels: float = OUTLIER_MIN_LEVELS,
) -> np.ndarray:
    """Pixels far enough above the tissue mode of this channel to be another class."""
    sel = channel[valid.astype(bool)]
    if sel.size < 256:
        return np.zeros(channel.shape, np.uint8)
    mode, sigma = _mode_and_spread(sel, upper_tail=True)
    threshold = max(mode + k * sigma, mode + min_levels)
    return ((channel.astype(np.float32) > threshold) & valid.astype(bool)).astype(np.uint8)


def segment_hsv(image: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Candidate 1: the obvious one. Hue near red, saturation and value in range."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    low = cv2.inRange(hsv, (0, 90, 30), (12, 255, 210))
    high = cv2.inRange(hsv, (168, 90, 30), (180, 255, 210))
    return _clean(cv2.bitwise_and(cv2.bitwise_or(low, high) // 255, valid))


def segment_lab_a(image: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Candidate 2: Lab a* alone. Redness, and nothing but redness."""
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2Lab)
    return _clean(_above_tissue(lab[:, :, 1], valid))


def segment_ycrcb(image: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Candidate 3: YCrCb Cr. The chroma-red axis broadcast video already carries."""
    ycc = cv2.cvtColor(image, cv2.COLOR_BGR2YCrCb)
    return _clean(_above_tissue(ycc[:, :, 1], valid))


def redness_ratio(image: np.ndarray) -> np.ndarray:
    """(R-G)/(R+G) rescaled to 8 bits. Invariant to a multiplicative light change.

    That invariance is the reason this channel is worth having: a laparoscope's
    automatic gain moves every pixel's brightness between frames, and a ratio of
    two channels divides the gain straight back out.
    """
    img = image.astype(np.float32) + 1.0
    g, r = img[:, :, 1], img[:, :, 2]
    ratio = (r - g) / (r + g)
    return np.clip((ratio + 1.0) * 127.5, 0, 255).astype(np.uint8)


def segment_ratio(image: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Candidate 4: normalised redness, thresholded above the tissue mode."""
    return _clean(_above_tissue(redness_ratio(image), valid))


# How far below the surrounding tissue a region has to sit before "darker" means
# anything. In multiples of the tissue's own robust spread, plus an absolute floor
# in 8-bit levels so a very uniform frame cannot make a one-level difference
# significant. Both from the area sweep; see docs/evaluation.md.
DARKNESS_K = 2.5
DARKNESS_MIN_LEVELS = 22.0


def _darker_than_tissue(
    flat: np.ndarray, context: np.ndarray, *, k: float = DARKNESS_K
) -> float:
    """The lightness cut, taken from the median and MAD of the tissue around it.

    Not the mode. After flattening, the histogram's peak lands well up in the bright
    tail - measured at 171 on a frame whose tissue median was 154 - and the spread
    measured on the side above a peak that high is tiny. Together they produced a cut
    of 167, which calls ordinary tissue dark and hands back a patch of inflamed
    serosa as a fifteen-thousand-pixel haemorrhage. A median and a median absolute
    deviation over the same pixels put the cut at about 134, which is where "darker
    than the tissue around it" actually starts.
    """
    values = flat[context.astype(bool)]
    if values.size < 256:
        return 0.0
    median = float(np.median(values))
    mad = 1.4826 * float(np.median(np.abs(values - median)))
    return min(median - k * max(mad, 1.0), median - DARKNESS_MIN_LEVELS)


def illumination_field(channel: np.ndarray, valid: np.ndarray, *, sigma_fraction: float = 0.22) -> np.ndarray:
    """A very low-frequency estimate of how the scope is lighting the field.

    A laparoscope's light source sits at the tip of the scope, a few centimetres
    from the tissue, so the frame has a strong radial falloff: the periphery is
    darker than the centre by a factor of two or more. The darkness vote in
    `segment_lab_ad` cannot tell that apart from a pool, and the result is a ring of
    false positives around the edge of every frame - which is exactly what the small
    pool sizes in the sweep were picking up.

    Dividing by this estimate is the standard illumination-normalisation step. The
    excluded region - the black surround outside the scope's circle, and the candidate
    blood - is filled by **normalised convolution** rather than by the field's mean.

    That distinction is not cosmetic and it cost a real false positive. Filling a hole
    with the global mean puts the *average* brightness of the whole frame into a place
    whose neighbours are much darker, because the scope's light falls off radially. The
    estimate there comes out too high, dividing by it makes the region look too dark,
    and a patch of inflamed serosa sitting off-centre is then reported as a pool of
    blood - fourteen thousand pixels of it, on a frame whose true pool was a thousand.
    Normalised convolution propagates the *neighbouring* illumination into the hole,
    which is what an illumination estimate should do.

    The blur is done on a downscaled copy. The sigma this needs is about a fifth of
    the frame, and a Gaussian that wide costs 300 milliseconds a frame at 960 by 540 -
    which was seventy per cent of the whole pipeline, to compute a field that has no
    detail in it by construction. Shrinking by eight, blurring there, and scaling the
    result back up gives the same field for about one per cent of the cost. The
    quantity being estimated is the lighting, and the lighting has no high
    frequencies.
    """
    h, w = channel.shape[:2]
    scale = 8
    small = (max(8, w // scale), max(8, h // scale))
    sigma = max(2.0, sigma_fraction * max(small))

    support_full = valid.astype(np.float32)
    support = cv2.resize(support_full, small, interpolation=cv2.INTER_AREA)
    values = cv2.resize(channel.astype(np.float32) * support_full, small,
                        interpolation=cv2.INTER_AREA)

    numerator = cv2.GaussianBlur(values, (0, 0), sigma)
    denominator = cv2.GaussianBlur(support, (0, 0), sigma)
    field_small = numerator / np.maximum(denominator, 1e-4)

    # Where there is no nearby support at all, fall back to the supported mean rather
    # than to a division by almost nothing.
    m = valid.astype(bool)
    fallback = float(channel[m].mean()) if m.any() else 1.0
    field_small = np.where(denominator < 1e-3, fallback, field_small)

    field = cv2.resize(field_small, (w, h), interpolation=cv2.INTER_LINEAR)
    return np.maximum(field, 1.0)


def flatten_lightness(
    lightness: np.ndarray, valid: np.ndarray, *, exclude: np.ndarray | None = None
) -> np.ndarray:
    """L* divided by the illumination estimate and rescaled back to 8-bit levels.

    `exclude` takes the candidate blood region out of the estimate. Leaving it in
    was the second bug here: a pool covering a tenth of the field pulls the local
    illumination estimate down around itself, the flattened pool is then no darker
    than its surroundings, and a large haemorrhage is under-measured by a fifth.
    The lighting is estimated from tissue and applied to everything.
    """
    support = valid.astype(bool)
    if exclude is not None:
        remaining = support & ~exclude.astype(bool)
        if remaining.sum() >= 0.15 * support.sum():
            support = remaining
    field = illumination_field(lightness, support.astype(np.uint8))
    m = valid.astype(bool)
    reference = float(field[m].mean()) if m.any() else 1.0
    return np.clip(lightness.astype(np.float32) * reference / field, 0, 255)


def segment_lab_ad(image: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Candidate 5: redder than tissue AND darker than tissue. Two votes, one class.

    The second vote is what separates a pool from a vessel. A vessel on the surface
    of the liver is redder than the tissue around it and is not blood loss; a pool
    is redder *and* darker, because it absorbs the scope's light instead of
    scattering it back. Requiring both cuts the vessel false positives that the
    redness-only candidates cannot.

    `LAB_A_MIN` remains as an absolute floor, so a frame of pale fat under a bright
    lamp cannot be declared red by a mode that happens to sit low.
    """
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2Lab)
    lightness, a_star = lab[:, :, 0], lab[:, :, 1]
    red = _above_tissue(a_star, valid).astype(bool) & (a_star >= LAB_A_MIN - 20)
    if red.sum() < 64:
        return np.zeros(lightness.shape, np.uint8)

    flat = flatten_lightness(lightness, valid, exclude=red)

    # The darkness cut is taken from the tissue *around* the red region, never from
    # the whole field. Take it from the whole field and a frame that is mostly blood
    # makes blood the mode, the cut lands below the pool, and a massive haemorrhage
    # reads as no haemorrhage at all. That inversion showed up on the 12% area sweep
    # and it is the single worst failure this module could have had.
    context = valid.astype(bool) & ~red
    if context.sum() < 256:
        context = valid.astype(bool)
    cut = _darker_than_tissue(flat, context)
    return _clean((red & (flat <= cut)).astype(np.uint8))


def segment_ratio_dark(image: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Candidate 6, and the one in use: normalised redness AND flattened darkness.

    Same two votes as `lab_ad`, with the redness vote moved off a*. The sweep
    showed why it had to move. CIE Lab's chroma axes scale with lightness, so a
    *dark* saturated red - which is exactly what a blood pool is - lands at an a*
    of about 165 while the perfused tissue around it sits at 149 with a spread of
    5. Four sigma above the tissue mode is 167, and the pool falls on the wrong
    side of it. On four of twenty-four sweep scenes that produced an empty mask for
    a field that was a quarter covered in blood: a total miss, reported with
    confidence, on the largest bleeds in the set.

    `(R-G)/(R+G)` has no such compression. It is a ratio, so it is invariant both
    to the scope's gain and to how dark the surface is, and the pool separates from
    tissue by a wide margin at every pool size. The darkness vote still does the
    work of rejecting inflamed serosa; it just is not being asked to do the redness
    vote's job as well.
    """
    ratio = redness_ratio(image)
    red = _above_tissue(ratio, valid).astype(bool)
    if red.sum() < 64:
        return np.zeros(ratio.shape, np.uint8)

    lightness = cv2.cvtColor(image, cv2.COLOR_BGR2Lab)[:, :, 0]
    flat = flatten_lightness(lightness, valid, exclude=red)
    context = valid.astype(bool) & ~red
    if context.sum() < 256:
        context = valid.astype(bool)
    cut = _darker_than_tissue(flat, context)
    return _clean((red & (flat <= cut)).astype(np.uint8))


SEGMENTERS = {
    "hsv": segment_hsv,
    "lab_a": segment_lab_a,
    "ycrcb": segment_ycrcb,
    "ratio": segment_ratio,
    "lab_ad": segment_lab_ad,
    "ratio_dark": segment_ratio_dark,
}


def blood_mask(
    image: np.ndarray,
    field: np.ndarray | None = None,
    *,
    method: str = "lab_ad",
) -> tuple[np.ndarray, np.ndarray]:
    """Return (blood mask, valid field mask with speculars removed)."""
    if method not in SEGMENTERS:
        raise ValueError(f"unknown segmentation method {method!r}; have {sorted(SEGMENTERS)}")
    h, w = image.shape[:2]
    field = np.ones((h, w), np.uint8) if field is None else field.astype(np.uint8)
    valid = cv2.bitwise_and(field, 1 - specular_mask(image))
    with stage(f"segment:{method}"):
        mask = SEGMENTERS[method](image, valid)
    return mask, valid


def drop_small_pools(
    mask: np.ndarray,
    min_area: int = MIN_POOL_AREA_PX,
    *,
    min_width_px: float = MIN_POOL_WIDTH_PX,
) -> tuple[np.ndarray, int, int]:
    """Keep the pools, drop the vessels and the speckle.

    Area alone is not enough, and the sweep is where that showed. A vessel running
    across the surface of the liver is redder than the tissue around it *and*
    darker, because it too absorbs the light instead of scattering it - so it
    passes both votes, exactly as blood does, which is unsurprising given that it
    is blood. It is not blood loss.

    What separates them is shape. A pool has extent in two dimensions; a vessel has
    extent in one. So each surviving component is measured on its own medial axis -
    `distanceTransform`, then the ridge - and a component whose median width is a
    few pixels is a line, not a pool, whatever its total area. This is the same
    measurement `visioncore.stroke_width_profile` does for crack widths, used here
    to throw something away rather than to report it.
    """
    binary = mask.astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    if count <= 1:
        return np.zeros(mask.shape, np.uint8), 0, 0

    dist = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
    ridge = cv2.dilate(dist, np.ones((3, 3), np.uint8))
    on_ridge = (dist >= ridge - 1e-6) & (dist > 0)

    keep: list[int] = []
    for i in range(1, count):
        if stats[i, cv2.CC_STAT_AREA] < min_area:
            continue
        sel = on_ridge & (labels == i)
        if not sel.any():
            continue
        # The *thickest* point, not the median. A pool that an instrument crosses
        # is two lobes joined by a narrow neck, and its median ridge width is a
        # vessel's. Its widest point is not. Using the median here threw away whole
        # pools on a third of the sweep - a 100% error, reported as zero blood.
        width = 2.0 * float(dist[sel].max()) - 1.0
        if width < min_width_px:
            continue
        keep.append(i)

    if not keep:
        return np.zeros(mask.shape, np.uint8), 0, 0
    out = np.isin(labels, keep).astype(np.uint8)
    largest = int(max(stats[i, cv2.CC_STAT_AREA] for i in keep))
    return out, len(keep), largest


# ---------------------------------------------------------------------------
# Area to volume
# ---------------------------------------------------------------------------


def measure(
    image: np.ndarray,
    field: np.ndarray | None = None,
    *,
    method: str = "lab_ad",
    mm_per_px: float | None = None,
    mm_per_px_sigma: float = 0.0,
    depth_mm: float = FILM_DEPTH_MM_NOMINAL,
    depth_low_mm: float = FILM_DEPTH_MM_LOW,
    depth_high_mm: float = FILM_DEPTH_MM_HIGH,
    scale_source: str = "none",
) -> tuple[BloodMeasurement, np.ndarray]:
    """Measure the blood on one frame. Returns the measurement and its mask.

    With no scale, the area fraction is still reported - it is a real, unitless,
    comparable quantity - but `volume_ml` stays `None` and the caller raises
    NO_SCALE_REFERENCE. Area fraction without a scale is honest; millilitres
    without a scale is not.
    """
    mask, valid = blood_mask(image, field, method=method)
    mask, pools, largest = drop_small_pools(mask)

    area_px = int(mask.sum())
    field_px = int(valid.sum())
    fraction = area_px / field_px if field_px else 0.0
    spec_px = int(specular_mask(image).sum())

    if mm_per_px is None or mm_per_px <= 0:
        return (
            BloodMeasurement(
                area_px=area_px,
                field_px=field_px,
                area_fraction=fraction,
                pools=pools,
                largest_pool_px=largest,
                specular_px=spec_px,
                scale_source=scale_source,
            ),
            mask,
        )

    # Area interval: the scale enters squared, so its relative error doubles, and
    # the segmentation's own relative error adds in quadrature.
    rel_scale = (mm_per_px_sigma / mm_per_px) if mm_per_px else 0.0
    rel_area = float(np.hypot(2.0 * rel_scale, relative_area_sigma(area_px)))
    area_mm2 = area_px * mm_per_px * mm_per_px
    area_low = area_mm2 * (1.0 - rel_area)
    # Surface tilt is one-sided: a tilted pool can only be larger than it looks.
    area_high = area_mm2 * (1.0 + rel_area) * TILT_AREA_FACTOR

    # Volume interval: the worst case of the area interval against the depth range.
    # 1 ml = 1000 mm^3.
    volume = area_mm2 * depth_mm / 1000.0
    volume_low = area_low * depth_low_mm / 1000.0
    volume_high = area_high * depth_high_mm / 1000.0

    return (
        BloodMeasurement(
            area_px=area_px,
            field_px=field_px,
            area_fraction=fraction,
            pools=pools,
            largest_pool_px=largest,
            specular_px=spec_px,
            area_mm2=area_mm2,
            area_mm2_low=max(0.0, area_low),
            area_mm2_high=area_high,
            volume_ml=volume,
            volume_ml_low=max(0.0, volume_low),
            volume_ml_high=volume_high,
            mm_per_px=mm_per_px,
            scale_source=scale_source,
            reliable=area_px >= MIN_RELIABLE_POOL_PX,
        ),
        mask,
    )


def overlay(image: np.ndarray, mask: np.ndarray, colour: tuple[int, int, int]) -> np.ndarray:
    """An evidence frame: the segmented pool outlined and tinted over the original."""
    out = image.copy()
    tint = np.zeros_like(out)
    tint[:, :] = colour
    sel = mask.astype(bool)
    out[sel] = cv2.addWeighted(out, 0.55, tint, 0.45, 0.0)[sel]
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(out, contours, -1, colour, 2)
    return out
