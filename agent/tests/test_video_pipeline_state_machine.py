import pytest
from hypothesis import given, strategies as st

from flowboard.services.video_pipeline import state_machine as sm


def test_scene_forward_transitions_allowed():
    assert sm.can_transition_scene("pending", "storyboard_running")
    assert sm.can_transition_scene("storyboard_running", "storyboard_done")
    assert sm.can_transition_scene("storyboard_done", "clip_running")
    assert sm.can_transition_scene("clip_running", "clip_done")
    assert sm.can_transition_scene("clip_done", "merged")


def test_scene_backward_transition_rejected():
    assert not sm.can_transition_scene("clip_done", "pending")
    assert not sm.can_transition_scene("merged", "storyboard_running")


def test_scene_failure_allowed_from_any_running():
    assert sm.can_transition_scene("storyboard_running", "failed")
    assert sm.can_transition_scene("clip_running", "failed")


def test_video_transitions():
    assert sm.can_transition_video("pending", "composite_done")
    assert sm.can_transition_video("composite_done", "scripted")
    assert sm.can_transition_video("scripted", "scenes_done")
    assert sm.can_transition_video("scenes_done", "merging")
    assert sm.can_transition_video("merging", "done")
    assert not sm.can_transition_video("done", "pending")


def test_run_terminal_states_are_sinks():
    for terminal in ("done", "failed", "cancelled"):
        for nxt in sm.RUN_STATES:
            if nxt != terminal:
                assert not sm.can_transition_run(terminal, nxt)


@given(st.sampled_from(sorted(sm.SCENE_STATES)),
       st.sampled_from(sorted(sm.SCENE_STATES)))
def test_scene_transition_never_raises(a, b):
    assert isinstance(sm.can_transition_scene(a, b), bool)


def test_unknown_state_raises_valueerror():
    with pytest.raises(ValueError):
        sm.can_transition_scene("bogus", "merged")
