"""The time series: smoothing, motion gating, rate fitting and change-point detection.

Synthetic series here, built from a formula, so the expected answer is arithmetic
rather than a rendered scene. The whole-video versions live in test_pipeline.py.
"""

from __future__ import annotations

import numpy as np
import pytest
from scopewatch import onset
from scopewatch.synth import SceneSpec, render


def ramp(n: int = 80, fps: float = 4.0, start_index: int = 40, slope_per_s: float = 0.02):
    """A flat series that starts rising at a known sample. Returns (times_ms, values)."""
    times = [i / fps * 1000.0 for i in range(n)]
    values = []
    for i in range(n):
        base = 0.20
        if i >= start_index:
            base += slope_per_s * (i - start_index) / fps
        values.append(base)
    return times, values


# ---------------------------------------------------------------------------
# Smoothing
# ---------------------------------------------------------------------------


def test_the_median_rejects_a_single_bad_frame():
    values = [1.0] * 10
    values[5] = 40.0
    smoothed = onset.median_filter(values, window=5)
    assert max(smoothed) == pytest.approx(1.0)


def test_the_median_does_not_flatten_a_real_trend():
    values = [float(i) for i in range(20)]
    smoothed = onset.median_filter(values, window=5)
    assert smoothed[-1] > smoothed[0]
    assert smoothed[10] == pytest.approx(10.0)


def test_the_ema_lags_but_converges():
    values = [0.0] * 5 + [1.0] * 40
    smoothed = onset.ema(values, alpha=0.35)
    assert smoothed[5] < 0.5, "no lag at all means no smoothing"
    assert smoothed[-1] == pytest.approx(1.0, abs=1e-3)


# ---------------------------------------------------------------------------
# Rate
# ---------------------------------------------------------------------------


def test_the_fitted_slope_is_the_slope_that_was_put_in():
    times = [i * 250.0 for i in range(40)]
    values = [0.5 + 0.01 * (t / 1000.0) for t in times]  # 0.01 per second
    rates = onset.windowed_rate([t / 1000.0 for t in times], values, window_s=4.0)
    assert rates[-1] == pytest.approx(0.6, rel=0.02), "0.01/s is 0.6/min"


def test_a_flat_series_has_no_slope():
    times = [i * 250.0 for i in range(40)]
    rates = onset.windowed_rate([t / 1000.0 for t in times], [0.4] * 40)
    assert max(abs(r) for r in rates) < 1e-6


def test_a_window_with_too_few_samples_reports_zero_rather_than_noise():
    rates = onset.windowed_rate([0.0, 0.25], [0.1, 9.0], window_s=4.0)
    assert rates == [0.0, 0.0]


# ---------------------------------------------------------------------------
# CUSUM
# ---------------------------------------------------------------------------


def test_the_cusum_alarms_after_the_step_and_not_before():
    _times, values = ramp(start_index=40)
    stat, alarm = onset.cusum(values)
    assert alarm is not None
    assert alarm >= 40, "alarmed before the change point"
    assert alarm < 60, f"took {alarm - 40} samples to notice"
    assert stat[39] == pytest.approx(0.0, abs=1e-9)


def test_the_cusum_does_not_alarm_on_noise_alone():
    rng = np.random.default_rng(0)
    values = list(0.40 + rng.normal(0, 0.004, 200))
    _stat, alarm = onset.cusum(values)
    assert alarm is None, "a flat noisy series produced a change point"


def test_the_cusum_thresholds_scale_with_the_series_noise():
    """A fixed millilitre slack is wrong for every scope but one."""
    quiet = [0.4 + 0.001 * (i % 2) for i in range(100)]
    noisy = [0.4 + 0.05 * (i % 2) for i in range(100)]
    assert onset.difference_sigma(noisy) > 10 * onset.difference_sigma(quiet)


# ---------------------------------------------------------------------------
# Onset
# ---------------------------------------------------------------------------


def test_the_onset_lands_near_the_step_with_its_window_as_uncertainty():
    times, values = ramp(start_index=40, slope_per_s=0.03)
    series, result = onset.analyse(times, values, threshold=0.35)
    assert result.detected
    assert result.timestamp_ms == pytest.approx(10_000.0, abs=4_000.0)
    assert result.uncertainty_ms == 4_000.0
    assert result.rate_per_min >= 0.35
    assert len(series.smoothed) == len(values)


def test_when_a_gate_stops_the_alarm_the_reason_names_the_gate_not_the_threshold():
    """Real footage: three clips had slopes of 17.87, 19.13 and 98.11 ml/min against a
    0.35 threshold, and the reason still said the slope "never reached" it."""
    times, values = ramp(start_index=40, slope_per_s=0.03)
    motion = [30.0] * len(times)  # the camera is moving the whole time
    _series, result = onset.analyse(times, values, motion_px=motion, threshold=0.35)
    assert not result.detected
    assert "never reached" not in result.reason
    assert result.candidates > 0
    assert result.blocked_by.get(onset.GATE_MOTION) == result.candidates
    assert "camera was moving" in result.reason


def test_a_refusal_gap_is_not_a_fall_and_a_rise():
    """Unmeasurable frames used to enter the series as zero, which turned every gap
    into a slope. All 32 candidate frames on the Kavalakat clip had one in the window."""
    times = [i * 250.0 for i in range(120)]
    values = [2.0] * 120
    measurable = [not (40 <= i < 60) for i in range(120)]
    for i in range(40, 60):
        values[i] = 0.0
    _series, result = onset.analyse(times, values, measurable=measurable, threshold=0.35)
    assert result.candidates == 0, result.reason


def test_a_flat_series_produces_no_onset_and_says_why():
    times = [i * 250.0 for i in range(120)]
    _series, result = onset.analyse(times, [0.4] * 120, threshold=0.35)
    assert not result.detected
    assert "never reached" in result.reason


def test_a_camera_pan_does_not_count_as_a_bleed():
    """The whole field moved. A slope measured across that is not about bleeding."""
    times, values = ramp(start_index=40, slope_per_s=0.05)
    motion = [0.0] * 40 + [60.0] * 40  # a large pan exactly over the rise
    _series, result = onset.analyse(times, values, motion_px=motion, threshold=0.35)
    assert not result.detected, "a pan was timestamped as a haemorrhage"


def test_unmeasurable_frames_do_not_carry_an_onset():
    times, values = ramp(start_index=40, slope_per_s=0.05)
    measurable = [True] * 40 + [False] * 40
    _series, result = onset.analyse(times, values, measurable=measurable, threshold=0.35)
    assert not result.detected


def test_too_few_frames_to_fit_anything():
    _series, result = onset.analyse([0.0, 250.0], [0.1, 0.5])
    assert not result.detected
    assert "too few" in result.reason


# ---------------------------------------------------------------------------
# Cumulative loss
# ---------------------------------------------------------------------------


def test_the_cumulative_total_counts_rises_and_ignores_falls():
    """Suction removes blood from the field. That is why the total is a lower bound.

    Three fill-and-suction cycles have to total more than one fill that then sits
    there, because the field really did carry three times the blood. Each cycle is
    given enough samples to survive the median-and-EMA smoothing; with three
    samples a cycle the smoother flattens it, which is the smoother working.
    """
    def cycles(n: int, per: int = 24) -> list[float]:
        out: list[float] = []
        for _ in range(n):
            out += [i / (per // 2) for i in range(per // 2)]  # fill to 1.0
            out += [0.0] * (per // 2)  # suctioned away
        return out

    three = cycles(3)
    one = [i / 12 for i in range(12)] + [1.0] * (len(three) - 12)
    times = [i * 250.0 for i in range(len(three))]
    total = onset.cumulative_observed_loss(times, three)
    monotone = onset.cumulative_observed_loss(times[: len(one)], one)
    assert total > monotone, f"three fills {total:.2f} did not beat one {monotone:.2f}"
    assert total > 0.0


# ---------------------------------------------------------------------------
# Motion
# ---------------------------------------------------------------------------


def test_a_still_camera_reports_almost_no_motion(clean_scene):
    estimator = onset.MotionEstimator()
    assert estimator.update(clean_scene.image) == 0.0  # first frame has no predecessor
    assert estimator.update(clean_scene.image) < 1.0


def test_a_shifted_frame_reports_the_shift():
    scene = render(SceneSpec(pool_area_px=12_000, seed=3))
    shifted = np.roll(scene.image, 40, axis=1)
    estimator = onset.MotionEstimator()
    estimator.update(scene.image)
    moved = estimator.update(shifted)
    assert moved > 20.0, f"a 40 pixel roll measured as {moved:.1f} px"
