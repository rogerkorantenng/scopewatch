"""Every threshold Scopewatch uses, in one file, with the reason it has that value.

Nothing in this file is a magic number that someone tuned until a demo looked good.
Each constant either (a) comes from a physical fact about laparoscopy, (b) was
chosen by the colour-space experiment in `experiments.py`, or (c) was set on the
synthetic sweeps in `evaluate.py` and its operating point is reported in
`docs/evaluation.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Physical facts
# ---------------------------------------------------------------------------

# Standard laparoscopic instrument shafts are manufactured at 5 mm outer diameter.
# 10 mm shafts exist (clip appliers, specimen retrieval) and 3 mm paediatric shafts
# exist, so the width we recover is matched against this set, not assumed.
SHAFT_DIAMETERS_MM: tuple[float, ...] = (3.0, 5.0, 10.0)
DEFAULT_SHAFT_MM = 5.0

# The tolerance a manufactured shaft holds. Used as the floor on scale precision:
# we can never claim the scale is better known than the reference object is.
SHAFT_TOLERANCE_MM = 0.15

# Depth of a blood film pooled on peritoneal/hepatic surface. There is no way to
# recover this from a monocular image, so it is an assumption with a stated range
# and every volume we report is an interval built from it. The range is deliberately
# wide: a 3x span, because a 3x span is the honest state of knowledge.
FILM_DEPTH_MM_LOW = 1.0
FILM_DEPTH_MM_NOMINAL = 2.0
FILM_DEPTH_MM_HIGH = 3.0

# ---------------------------------------------------------------------------
# Blood segmentation
# ---------------------------------------------------------------------------

# Chosen by experiment. `experiments.run_colour_space_trial()` scores five candidate
# spaces on synthetic scenes with masks known by construction; the winner and its
# Dice score are written into docs/evaluation.md. Change this only by re-running it.
BLOOD_COLOUR_SPACE = "ratio_dark"  # normalised redness AND flattened darkness

# a* is stored 0..255 with 128 as neutral. Pooled blood sits well above neutral.
LAB_A_MIN = 148
# Pooled blood is *darker* than perfused tissue at the same redness. This percentile
# of L* within the a*-positive region separates pool from tissue.
LAB_L_PERCENTILE = 62.0

# Specular highlights from the laparoscope's own light source are near-white and
# would otherwise be scored as "not blood" inside a pool, eroding the area. They are
# masked out of both the numerator and the denominator.
SPECULAR_V_MIN = 235
SPECULAR_S_MAX = 42

# Morphology. 5x5 elliptical, one open then one close: remove single-pixel noise,
# then bridge the specular holes we just punched.
MORPH_KERNEL = 5
MIN_POOL_AREA_PX = 120  # smaller than this at 960px wide is speckle, not a pool

# A pool has extent in two dimensions; a surface vessel has extent in one, and a
# vessel is redder and darker than the tissue around it for the obvious reason. A
# component whose median medial-axis width is below this is a line, not a pool.
MIN_POOL_WIDTH_PX = 9.0

# Below this area the false-positive floor - a few thousand pixels of vessel and
# inflamed serosa - is comparable to the pool itself, and a percentage error on the
# measurement is meaningless. Scopewatch reports the area but withholds a volume
# and says why. Set from the area sweep in docs/evaluation.md.
MIN_REPORTABLE_POOL_PX = 6000

# ---------------------------------------------------------------------------
# Scene usability - the refusal gates
# ---------------------------------------------------------------------------

# Variance of the Laplacian, measured on an eroded core of the lit field so the hard
# rim of the projected circle does not dominate it.
#
# The operating point comes from the blur sweep, and the sweep changed what this
# gate is for. Defocus barely moves the *area* error: the segmentation is a colour
# decision over a compact region and blurring a red pool leaves it red. What defocus
# does move is the *scale*, because the shaft's medial-axis width spreads as the
# edges soften - measured at -0.3% at sigma 0, -3.1% at sigma 2, -13.2% at sigma 8.
# The scale enters the area squared, so a 13% scale error is a 24% volume error.
# 25 puts the cut at about sigma 2.5, which holds the scale error under 3%.
FOCUS_LAPLACIAN_MIN = 25.0

# Lens fogging / smoke. The dark channel prior: haze lifts the per-pixel minimum
# across channels. A clean laparoscopic frame has deep shadows somewhere.
# From the fog sweep: at fog 0.2 the dark channel is 123 and the area error is 17%;
# at 0.4 it is 142 and the error is -25%; at 0.5 and above the pool is missed
# entirely and the tool reports no blood on a bleeding field. 132 puts the cut
# between the third and fourth rung, which is the last one that still measures.
FOG_DARK_CHANNEL_MAX = 132.0
# Fog also flattens the histogram's tails; global contrast is the second vote.
FOG_CONTRAST_MIN = 22.0

# Occlusion: the fraction of the visible circle taken by instrument, swab or a
# blacked-out region. Past this we are measuring a corner of the field, not a field.
OCCLUSION_MAX_FRACTION = 0.55

# Clipping. An over- or under-exposed frame cannot be colour-segmented at all.
EXPOSURE_CLIP_MAX_FRACTION = 0.34

# ---------------------------------------------------------------------------
# Temporal
# ---------------------------------------------------------------------------

SMOOTHING_ALPHA = 0.35  # exponential moving average on the volume series
MEDIAN_WINDOW = 5  # frames; rejects a single mis-segmented frame

# Bleeding onset. A rate fitted by least squares over a sliding window, confirmed by
# a one-sided CUSUM so a single spike does not trigger. Both must agree.
#
# The threshold is in millilitres per minute *of blood visible on the field*, which
# is a much smaller number than blood lost. A laparoscope at working distance sees
# roughly 4 to 8 cm across; at a 2 mm film that whole field holds only a few
# millilitres, and everything beyond that goes to suction and is never on camera.
# A default of 2 ml/min - which is what this was set to first - is a threshold the
# field can physically never reach, and the detector simply never fires.
ONSET_WINDOW_S = 4.0
ONSET_RATE_ML_PER_MIN = 0.35

# The CUSUM's slack and decision interval are set from the series' own noise rather
# than in absolute millilitres, because "how much does this estimate jitter" depends
# on the scope, the distance and the field size, and a fixed millilitre figure is
# wrong for every case but one. k is half a noise sigma, h is five; those are the
# textbook values for a shift of about one sigma.
ONSET_CUSUM_K_SIGMA = 0.5
ONSET_CUSUM_H_SIGMA = 5.0
ONSET_CUSUM_MIN_SIGMA_ML = 0.002  # a floor, so a perfectly flat series still works

# Global camera motion. Estimated by phase correlation on a downscaled grey frame.
# Above this the field moved and a rate-of-change estimate is not about bleeding.
MOTION_SUSPECT_PX = 14.0

# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------

# Metallic shafts are low-saturation and bright relative to tissue.
INSTRUMENT_S_MAX = 78
INSTRUMENT_V_MIN = 92
INSTRUMENT_MIN_ELONGATION = 2.8  # major/minor of the minimum-area rectangle
INSTRUMENT_MIN_AREA_PX = 900
INSTRUMENT_BORDER_MARGIN_PX = 6  # a shaft enters from outside the field of view

YOLOX_STRIDE = 10  # run the DNN every Nth kept frame; classical channel runs always
YOLOX_SCORE = 0.25

# ---------------------------------------------------------------------------
# Phase
# ---------------------------------------------------------------------------

PHASES: tuple[str, ...] = (
    "preparation",
    "exposure",
    "dissection",
    "critical_approach",
    "division",
    "extraction",
)

# A phase must hold for this long before the state machine accepts the change.
# Hysteresis is what stops a phase ribbon that flickers once per second.
PHASE_MIN_DWELL_S = 2.5

# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

CHECKPOINT_STATES: tuple[str, ...] = (
    "observing",
    "candidate",
    "held",
    "confirmed",
    "dismissed",
)

# The checkpoint fires when the phase reaches critical_approach and the safety view
# has not been recorded as established. `candidate` must persist this long before
# the hold, so a one-frame phase blip does not stop an operation.
CHECKPOINT_CANDIDATE_S = 1.5

DISMISSAL_REASONS: tuple[str, ...] = (
    "Critical view established, not yet recorded",
    "Bail-out: subtotal cholecystectomy",
    "Bail-out: converted to open",
    "Not at that step",
    "Anatomy confirmed by other means",
    "Other (written below)",
)

# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------


@dataclass
class PipelineParams:
    """What a caller may change per run. Everything else is a constant above."""

    # Decimation on the first pass. 5 frames/s at 25 fps source is enough to see a
    # bleed start; the agent re-reads at full rate where it matters.
    stride: int = 5
    max_side: int = 960  # analysis resolution; evidence frames are saved at this size
    max_frames: int | None = 1200
    shaft_mm: float = DEFAULT_SHAFT_MM
    mm_per_px: float | None = None  # operator override; skips shaft calibration
    film_depth_mm: float = FILM_DEPTH_MM_NOMINAL
    film_depth_low_mm: float = FILM_DEPTH_MM_LOW
    film_depth_high_mm: float = FILM_DEPTH_MM_HIGH
    onset_rate_ml_per_min: float = ONSET_RATE_ML_PER_MIN
    use_dnn: bool = True
    rescan: bool = True  # the agent's second look around a detected onset
    safety_view_established: bool = False

    def to_dict(self) -> dict[str, float | int | bool | None]:
        return {
            "stride": self.stride,
            "max_side": self.max_side,
            "max_frames": self.max_frames,
            "shaft_mm": self.shaft_mm,
            "mm_per_px": self.mm_per_px,
            "film_depth_mm": self.film_depth_mm,
            "film_depth_low_mm": self.film_depth_low_mm,
            "film_depth_high_mm": self.film_depth_high_mm,
            "onset_rate_ml_per_min": self.onset_rate_ml_per_min,
            "use_dnn": self.use_dnn,
            "rescan": self.rescan,
            "safety_view_established": self.safety_view_established,
        }


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Palette:
    """Ligature, from docs/design/atlas.md section 1. BGR, because this is OpenCV."""

    ground: tuple[int, int, int] = (16, 18, 11)
    surface: tuple[int, int, int] = (27, 31, 20)
    accent: tuple[int, int, int] = (61, 138, 255)  # #FF8A3D
    established: tuple[int, int, int] = (166, 211, 95)  # #5FD3A6
    ink: tuple[int, int, int] = (236, 241, 233)  # #E9F1EC
    ink_dim: tuple[int, int, int] = (172, 179, 157)  # #9DB3AC
    blood: tuple[int, int, int] = (72, 60, 214)


PALETTE = Palette()

REFUSAL_CODES: dict[str, str] = {
    "OUT_OF_FOCUS": "The frame carries no usable edge energy.",
    "LENS_FOGGED": "Haze or smoke across the lens; the field is not visible.",
    "OCCLUDED": "Too much of the field is covered to measure what is on it.",
    "EXPOSURE_CLIPPED": "The frame is clipped; colour cannot be separated.",
    "NO_SCALE_REFERENCE": "No instrument shaft in view, so there is no scale.",
    "NO_USABLE_FRAMES": "No frame in this clip was good enough to measure.",
    "DECODE_FAILED": "The file could not be decoded as video or an image.",
}


@dataclass
class Thresholds:
    """A mutable copy of the gates, so the evaluation can sweep them."""

    focus_min: float = FOCUS_LAPLACIAN_MIN
    fog_dark_channel_max: float = FOG_DARK_CHANNEL_MAX
    fog_contrast_min: float = FOG_CONTRAST_MIN
    occlusion_max: float = OCCLUSION_MAX_FRACTION
    exposure_clip_max: float = EXPOSURE_CLIP_MAX_FRACTION
    extras: dict[str, float] = field(default_factory=dict)
