"""The time series: smoothing, camera motion, rate of change, and bleeding onset.

The question "when did this start bleeding" is a change-point question on a noisy
series, and the two ways to get it wrong are both common.

The first is to threshold the volume itself. That answers "when was there a lot of
blood", which is minutes later than the event you wanted and is exactly the delay a
surgeon already has by eye.

The second is to threshold the raw first difference. Laparoscopic video is a
handheld camera in a moving cavity, so the frame-to-frame difference is dominated
by the scope panning across a pool that was already there. A pan produces the same
positive slope as a bleed, and a tool that cannot tell them apart will timestamp
every camera movement as a haemorrhage.

So: fit a slope by least squares over a window, in millilitres per minute, and
require a one-sided CUSUM on the same series to agree. Gate both on a global motion
estimate from phase correlation, so frames where the field moved do not contribute
a rate. The reported onset carries the window length as its uncertainty, because
that is genuinely how well a windowed estimator can localise a step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from .config import (
    MEDIAN_WINDOW,
    MOTION_SUSPECT_PX,
    ONSET_CUSUM_H_SIGMA,
    ONSET_CUSUM_K_SIGMA,
    ONSET_CUSUM_MIN_SIGMA_ML,
    ONSET_RATE_ML_PER_MIN,
    ONSET_WINDOW_S,
    SMOOTHING_ALPHA,
)


# ---------------------------------------------------------------------------
# Camera motion
# ---------------------------------------------------------------------------


class MotionEstimator:
    """Global translation between consecutive kept frames, by phase correlation.

    Phase correlation on a Hanning-windowed, downscaled grey frame costs under a
    millisecond and gives a sub-pixel global shift. It is not optical flow and does
    not pretend to be: it answers "did the whole field move", which is the only
    question this pipeline needs it to answer.
    """

    def __init__(self, size: int = 256) -> None:
        self.size = size
        self._previous: np.ndarray | None = None
        self._window: np.ndarray | None = None

    def _prepare(self, image: np.ndarray) -> np.ndarray:
        grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        small = cv2.resize(grey, (self.size, self.size), interpolation=cv2.INTER_AREA)
        return small.astype(np.float32)

    def update(self, image: np.ndarray) -> float:
        """Pixels of global shift since the previous call, scaled to the input frame."""
        current = self._prepare(image)
        if self._window is None:
            self._window = cv2.createHanningWindow((self.size, self.size), cv2.CV_32F)
        if self._previous is None:
            self._previous = current
            return 0.0
        (dx, dy), _response = cv2.phaseCorrelate(self._previous, current, self._window)
        self._previous = current
        scale = max(image.shape[:2]) / float(self.size)
        return float(np.hypot(dx, dy) * scale)


# ---------------------------------------------------------------------------
# Smoothing
# ---------------------------------------------------------------------------


def median_filter(values: list[float], window: int = MEDIAN_WINDOW) -> list[float]:
    """Running median. Rejects a single mis-segmented frame without lagging a trend."""
    if window < 2 or len(values) < 2:
        return list(values)
    half = window // 2
    out: list[float] = []
    for i in range(len(values)):
        lo, hi = max(0, i - half), min(len(values), i + half + 1)
        out.append(float(np.median(values[lo:hi])))
    return out


def ema(values: list[float], alpha: float = SMOOTHING_ALPHA) -> list[float]:
    """Exponential moving average, applied after the median."""
    out: list[float] = []
    acc: float | None = None
    for v in values:
        acc = v if acc is None else alpha * v + (1.0 - alpha) * acc
        out.append(float(acc))
    return out


def smooth(values: list[float], *, window: int = MEDIAN_WINDOW, alpha: float = SMOOTHING_ALPHA) -> list[float]:
    return ema(median_filter(values, window), alpha)


# ---------------------------------------------------------------------------
# Rate
# ---------------------------------------------------------------------------


def windowed_rate(
    times_s: list[float],
    values: list[float],
    *,
    window_s: float = ONSET_WINDOW_S,
) -> list[float]:
    """Least-squares slope over a trailing window, in units per minute.

    Trailing rather than centred, because a theatre instrument may not look into
    the future. Windows with fewer than three samples or no time span report zero
    rather than a slope fitted through noise.
    """
    rates: list[float] = []
    for i, t in enumerate(times_s):
        lo = i
        while lo > 0 and t - times_s[lo - 1] <= window_s:
            lo -= 1
        xs = np.asarray(times_s[lo : i + 1], dtype=np.float64)
        ys = np.asarray(values[lo : i + 1], dtype=np.float64)
        if xs.size < 3 or (xs[-1] - xs[0]) <= 1e-6:
            rates.append(0.0)
            continue
        xs = xs - xs.mean()
        denom = float((xs * xs).sum())
        slope = float((xs * (ys - ys.mean())).sum() / denom) if denom > 0 else 0.0
        rates.append(slope * 60.0)
    return rates


def difference_sigma(values: list[float], *, floor: float = ONSET_CUSUM_MIN_SIGMA_ML) -> float:
    """Robust noise scale of the series, from the median absolute first difference.

    The median is used rather than the standard deviation precisely because the
    change we are hunting is in the tail. A standard deviation computed over a
    series that contains the bleed is inflated by the bleed, and the detector then
    needs a bigger bleed to notice - which is the wrong way round.
    """
    if len(values) < 3:
        return floor
    diffs = np.abs(np.diff(np.asarray(values, dtype=np.float64)))
    mad = float(np.median(diffs))
    return max(floor, 1.4826 * mad)


def cusum(
    values: list[float],
    *,
    k: float | None = None,
    h: float | None = None,
) -> tuple[list[float], int | None]:
    """One-sided upward CUSUM on the first differences. Returns (statistic, first alarm).

    Page's classic detector. `k` is the slack: increments smaller than it accumulate
    nothing, so ordinary segmentation jitter never drifts the statistic upward. `h`
    is the decision interval. Left unset, both are scaled from this series' own
    noise, because a millilitre figure that is right for one scope at one working
    distance is wrong for the next.
    """
    sigma = difference_sigma(values)
    k = ONSET_CUSUM_K_SIGMA * sigma if k is None else k
    h = ONSET_CUSUM_H_SIGMA * sigma if h is None else h
    s = 0.0
    out: list[float] = []
    alarm: int | None = None
    previous = values[0] if values else 0.0
    for i, v in enumerate(values):
        delta = v - previous
        previous = v
        s = max(0.0, s + delta - k)
        out.append(s)
        if alarm is None and s > h:
            alarm = i
    return out, alarm


# ---------------------------------------------------------------------------
# Onset
# ---------------------------------------------------------------------------


@dataclass
class Onset:
    """When the rate of change crossed the threshold, and how sure we are of when."""

    detected: bool
    index: int | None = None
    timestamp_ms: float | None = None
    uncertainty_ms: float = 0.0
    rate_ml_per_min: float | None = None
    threshold_ml_per_min: float = ONSET_RATE_ML_PER_MIN
    cusum_index: int | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "index": self.index,
            "timestamp_ms": None if self.timestamp_ms is None else round(self.timestamp_ms, 1),
            "uncertainty_ms": round(self.uncertainty_ms, 1),
            "rate_ml_per_min": None if self.rate_ml_per_min is None else round(self.rate_ml_per_min, 3),
            "threshold_ml_per_min": self.threshold_ml_per_min,
            "cusum_index": self.cusum_index,
            "reason": self.reason,
        }


@dataclass
class Series:
    """The whole case as numbers, which is what the trace draws and the report quotes."""

    times_ms: list[float] = field(default_factory=list)
    raw: list[float] = field(default_factory=list)
    smoothed: list[float] = field(default_factory=list)
    rate: list[float] = field(default_factory=list)
    cusum: list[float] = field(default_factory=list)
    motion_px: list[float] = field(default_factory=list)
    measurable: list[bool] = field(default_factory=list)
    instruments: list[int] = field(default_factory=list)
    reliable: list[bool] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "times_ms": [round(t, 1) for t in self.times_ms],
            "raw": [round(v, 4) for v in self.raw],
            "smoothed": [round(v, 4) for v in self.smoothed],
            "rate_per_min": [round(v, 4) for v in self.rate],
            "cusum": [round(v, 4) for v in self.cusum],
            "motion_px": [round(v, 2) for v in self.motion_px],
            "measurable": list(self.measurable),
            "instruments": list(self.instruments),
            "reliable": list(self.reliable),
        }


def analyse(
    times_ms: list[float],
    values: list[float],
    *,
    motion_px: list[float] | None = None,
    measurable: list[bool] | None = None,
    instruments: list[int] | None = None,
    reliable: list[bool] | None = None,
    window_s: float = ONSET_WINDOW_S,
    threshold: float = ONSET_RATE_ML_PER_MIN,
    motion_limit: float = MOTION_SUSPECT_PX,
) -> tuple[Series, Onset]:
    """Smooth the series, fit the rate, run the CUSUM, and pick the onset."""
    n = len(times_ms)
    motion_px = motion_px or [0.0] * n
    measurable = measurable if measurable is not None else [True] * n
    instruments = instruments if instruments is not None else [0] * n
    reliable = reliable if reliable is not None else [True] * n
    times_s = [t / 1000.0 for t in times_ms]

    smoothed = smooth(values)
    rate = windowed_rate(times_s, smoothed, window_s=window_s)
    stat, alarm = cusum(smoothed)

    series = Series(
        times_ms=list(times_ms),
        raw=list(values),
        smoothed=smoothed,
        rate=rate,
        cusum=stat,
        motion_px=list(motion_px),
        measurable=list(measurable),
        instruments=list(instruments),
        reliable=list(reliable),
    )

    if n < 4:
        return series, Onset(False, reason="too few measurable frames to fit a rate")

    for i in range(n):
        if not measurable[i]:
            continue
        if motion_px[i] > motion_limit:
            continue  # the field moved; this slope is not about bleeding
        if not reliable[i]:
            # The measurement at this frame is below the pool size where the
            # false-positive floor stops mattering, and at that size the estimator's
            # own jitter is the same order as the rate we are looking for. On a
            # quiet synthetic case with a 900 pixel baseline pool it produced a
            # confident onset with a peak slope of 1.19 ml/min and no bleeding in
            # the clip at all. An onset is not declared on a number the pipeline has
            # already flagged as unreliable; the frame still appears in the trace.
            continue
        if _instruments_changed(times_s, instruments, i, window_s):
            # An instrument entering or leaving uncovers or hides part of the pool,
            # and the measured area steps. That step has the same shape as a bleed
            # and none of the meaning, and on a quiet synthetic case it produced a
            # confident onset at 4.5 s where the script has no bleeding at all.
            continue
        if rate[i] < threshold:
            continue
        if alarm is None or i < alarm - 2:
            continue  # the CUSUM has not confirmed a real step yet
        return series, Onset(
            detected=True,
            index=i,
            timestamp_ms=times_ms[i],
            uncertainty_ms=window_s * 1000.0,
            rate_ml_per_min=rate[i],
            threshold_ml_per_min=threshold,
            cusum_index=alarm,
            reason=(
                f"slope {rate[i]:.2f} ml/min over a {window_s:.0f} s window, "
                f"confirmed by CUSUM at sample {alarm}"
            ),
        )

    eligible = [
        rate[i] for i in range(n)
        if measurable[i] and reliable[i] and motion_px[i] <= motion_limit
    ]
    peak = max(eligible) if eligible else 0.0
    if not eligible:
        reason = (
            "no frame was both measurable and above the pool size where a rate "
            "estimate means anything, so no onset was declared"
        )
    else:
        reason = (
            f"peak slope {peak:.2f} ml/min never reached {threshold:.2f} ml/min "
            "on a still field with a reliable measurement"
        )
    return series, Onset(
        False,
        rate_ml_per_min=peak,
        threshold_ml_per_min=threshold,
        cusum_index=alarm,
        reason=reason,
    )


def _instruments_changed(
    times_s: list[float], instruments: list[int], index: int, window_s: float
) -> bool:
    """True when the instrument count moved anywhere inside the rate window."""
    if not instruments:
        return False
    lo = index
    while lo > 0 and times_s[index] - times_s[lo - 1] <= window_s:
        lo -= 1
    window = instruments[lo : index + 1]
    return len(set(window)) > 1


def cumulative_observed_loss(times_ms: list[float], values: list[float]) -> float:
    """Sum of the positive increases in on-field volume across the case.

    This is a **lower bound** on blood loss and is labelled as one everywhere it is
    shown. Blood that is suctioned away between two frames leaves the field and is
    never counted again; blood that soaks into a swab is not on the field at all.
    What this number is good for is comparison - between two halves of one case,
    or between the same operation done twice - not for a transfusion decision.
    """
    smoothed = smooth(values)
    total = 0.0
    for i in range(1, len(smoothed)):
        delta = smoothed[i] - smoothed[i - 1]
        if delta > 0:
            total += delta
    del times_ms
    return float(total)
