"""The agent loop, the phase state machine, and the human control that ends it.

The competition's Agentic Vision rubric puts 15% on "failure handling,
observability, security and human control". These are the tests for that: nothing
resolves itself, nothing resolves on a timer, and every transition carries the
frame that caused it.
"""

from __future__ import annotations

import pytest
from scopewatch import agent, phase
from scopewatch.config import DISMISSAL_REASONS


# `motion` is the instrument-activity signal: the share of the steel mask that
# changed since the previous frame, so it runs 0 to 1, not in pixels. 0.4 is a
# working instrument, 0.02 is one being held still.
def features(t_s: float, *, n: int = 2, wide: float = 0.0, median: float = 50.0,
             motion: float = 0.4, measurable: bool = True) -> phase.PhaseFeatures:
    return phase.PhaseFeatures(
        timestamp_ms=t_s * 1000.0,
        instrument_count=n,
        max_shaft_width_px=wide or median,
        median_shaft_width_px=median,
        blood_fraction=0.01,
        tip_motion_px=motion,
        measurable=measurable,
    )


# ---------------------------------------------------------------------------
# Phase
# ---------------------------------------------------------------------------


def test_an_empty_field_is_preparation():
    track = phase.infer([features(t, n=0) for t in (0.0, 1.0, 2.0, 3.0, 4.0)])
    assert track.labels[-1] == "preparation"


def test_two_working_instruments_become_dissection():
    track = phase.infer([features(t) for t in [i * 0.25 for i in range(40)]])
    assert track.labels[-1] == "dissection"


def test_a_wide_device_early_is_not_a_clip_applier():
    """A 10 mm trocar during access must not hold a checkpoint before the operation."""
    track = phase.infer([features(t, wide=100.0) for t in [i * 0.25 for i in range(20)]])
    assert "critical_approach" not in track.labels


def test_a_wide_device_after_sustained_dissection_is_the_critical_approach():
    frames = [features(i * 0.25) for i in range(120)]  # 30 s of dissection
    frames += [features(30.0 + i * 0.25, wide=100.0) for i in range(24)]
    track = phase.infer(frames)
    assert "critical_approach" in track.labels


def test_the_approach_gives_way_to_division_after_its_window():
    frames = [features(i * 0.25) for i in range(120)]
    frames += [features(30.0 + i * 0.25, wide=100.0, motion=0.02) for i in range(120)]
    track = phase.infer(frames)
    assert track.labels[-1] == "division"


def test_hysteresis_stops_a_one_frame_blip_changing_the_phase():
    frames = [features(i * 0.25) for i in range(60)]
    frames[30] = features(30 * 0.25, n=0)  # one frame with nothing in the field
    track = phase.infer(frames)
    assert track.labels[30] == track.labels[29]


def test_a_fogged_frame_never_changes_the_phase():
    frames = [features(i * 0.25) for i in range(40)]
    for i in range(20, 30):
        frames[i] = features(i * 0.25, measurable=False)
    track = phase.infer(frames)
    assert track.labels[25] == track.labels[19]


def test_spans_cover_every_frame():
    track = phase.infer([features(i * 0.25) for i in range(40)])
    assert sum(s.frames for s in track.spans) == len(track.labels)


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def observation(t_s: float, phase_name: str, **kw) -> agent.Observation:
    return agent.Observation(
        index=int(t_s * 4),
        timestamp_ms=t_s * 1000.0,
        phase=phase_name,
        measurable=kw.pop("measurable", True),
        **kw,
    )


def test_the_checkpoint_is_held_only_after_the_phase_persists():
    loop = agent.AgentLoop()
    loop.observe(observation(10.0, "critical_approach"))
    assert loop.state == agent.CANDIDATE
    assert loop.open_checkpoint is None, "held on the very first frame of the phase"
    loop.observe(observation(11.8, "critical_approach"))
    assert loop.state == agent.HELD
    assert loop.open_checkpoint is not None


def test_leaving_the_phase_releases_a_candidate_without_holding():
    loop = agent.AgentLoop()
    loop.observe(observation(10.0, "critical_approach"))
    actions = loop.observe(observation(10.5, "dissection"))
    assert loop.state == agent.OBSERVING
    assert any(a.kind == agent.ACTION_RESUME for a in actions)
    assert not loop.checkpoints


def test_a_recorded_safety_view_raises_no_checkpoint():
    loop = agent.AgentLoop()
    for t in (10.0, 11.0, 12.0, 13.0):
        loop.observe(observation(t, "critical_approach", safety_view_established=True))
    assert loop.state == agent.OBSERVING
    assert not loop.checkpoints


def test_nothing_resolves_a_checkpoint_except_a_person():
    """No timeout, no auto-clear. Feed it a hundred more frames and it stays held."""
    loop = agent.AgentLoop()
    loop.observe(observation(10.0, "critical_approach"))
    loop.observe(observation(12.0, "critical_approach"))
    for i in range(100):
        loop.observe(observation(13.0 + i * 0.25, "division"))
    assert loop.open_checkpoint is not None
    assert loop.state == agent.HELD


def test_confirming_records_who_and_when():
    loop = agent.AgentLoop()
    loop.observe(observation(10.0, "critical_approach"))
    loop.observe(observation(12.0, "critical_approach"))
    cp = loop.open_checkpoint
    resolved = loop.confirm(cp.checkpoint_id, "S. Amoah", "criterion three now visible")
    assert resolved.state == agent.CONFIRMED
    assert resolved.decided_by == "S. Amoah"
    assert resolved.decided_at is not None
    assert loop.open_checkpoint is None
    last = loop.transitions[-1]
    assert last.to_state == agent.CONFIRMED and last.actor == "S. Amoah"


def test_dismissing_without_a_reason_is_refused():
    loop = agent.AgentLoop()
    loop.observe(observation(10.0, "critical_approach"))
    loop.observe(observation(12.0, "critical_approach"))
    cp = loop.open_checkpoint
    with pytest.raises(ValueError, match="only be dismissed with a reason"):
        loop.dismiss(cp.checkpoint_id, "S. Amoah", "   ")
    assert loop.open_checkpoint is not None


def test_dismissing_with_a_reason_records_it():
    loop = agent.AgentLoop()
    loop.observe(observation(10.0, "critical_approach"))
    loop.observe(observation(12.0, "critical_approach"))
    cp = loop.open_checkpoint
    reason = DISMISSAL_REASONS[1]
    resolved = loop.dismiss(cp.checkpoint_id, "S. Amoah", reason)
    assert resolved.state == agent.DISMISSED
    assert resolved.reason == reason
    assert loop.transitions[-1].reason == reason


def test_every_transition_names_the_frame_that_caused_it():
    loop = agent.AgentLoop()
    loop.observe(observation(10.0, "critical_approach", evidence_uri="/api/x/1.jpg"))
    loop.observe(observation(12.0, "critical_approach", evidence_uri="/api/x/2.jpg"))
    assert loop.transitions
    for t in loop.transitions:
        assert t.frame_index >= 0
        assert t.at_ms >= 0
        assert t.trigger, "a transition with no stated cause is not auditable"
    assert loop.transitions[-1].evidence_uri == "/api/x/2.jpg"


def test_transition_sequence_numbers_are_strictly_increasing():
    loop = agent.AgentLoop()
    loop.observe(observation(10.0, "critical_approach"))
    loop.observe(observation(12.0, "critical_approach"))
    loop.confirm(loop.open_checkpoint.checkpoint_id, "S. Amoah")
    seqs = [t.seq for t in loop.transitions]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


# ---------------------------------------------------------------------------
# The other two loop closures
# ---------------------------------------------------------------------------


def test_an_onset_asks_for_a_dense_re_read_of_that_window():
    loop = agent.AgentLoop()
    actions = loop.observe(observation(30.0, "dissection", onset=True, volume_ml=0.8))
    rescan = next(a for a in actions if a.kind == agent.ACTION_RESCAN)
    assert rescan.detail["stride"] == 1
    assert rescan.detail["start_ms"] == pytest.approx(25_000.0)
    assert rescan.detail["end_ms"] == pytest.approx(35_000.0)


def test_only_the_first_onset_buys_a_re_read():
    loop = agent.AgentLoop()
    loop.observe(observation(30.0, "dissection", onset=True))
    again = loop.observe(observation(40.0, "dissection", onset=True))
    assert not [a for a in again if a.kind == agent.ACTION_RESCAN]


def test_a_run_of_fogged_frames_asks_for_the_lens_and_suppresses_the_alarm():
    loop = agent.AgentLoop()
    emitted = []
    for i in range(5):
        emitted += loop.observe(
            observation(10.0 + i * 0.25, "dissection", measurable=False, refusal="LENS_FOGGED")
        )
    requests = [a for a in emitted if a.kind == agent.ACTION_CLEAN_LENS]
    assert len(requests) == 1, "asked more than once, or not at all"
    assert requests[0].detail["suppressed"] == "bleeding onset detection"


def test_one_fogged_frame_is_not_worth_asking_about():
    loop = agent.AgentLoop()
    actions = loop.observe(
        observation(10.0, "dissection", measurable=False, refusal="LENS_FOGGED")
    )
    assert not [a for a in actions if a.kind == agent.ACTION_CLEAN_LENS]


def test_the_loop_states_its_own_autonomy_in_the_record():
    loop = agent.AgentLoop()
    text = loop.to_dict()["autonomy"]
    assert "takes no clinical action" in text
    assert "named human" in text
