"""#542 r6: repository lifecycle doubles are opt-in, not autouse hijacks.

Seams:
- Without requesting the light-shell fixtures, production create_llm_beat_generator,
  GameSession class attrs, and atomic stay on the real wiring.
- Tests that need offline scene / connless atomic must opt in explicitly.
"""

from __future__ import annotations

import ming_sim.applier as applier
import ming_sim.beat_orchestration as bo
import web_app
from ming_sim.session import GameSession


def test_default_wiring_keeps_production_create_llm_beat_generator():
    """Unrelated / real-DB tests must not inherit the offline factory stub."""
    assert bo.create_llm_beat_generator.__name__ == "create_llm_beat_generator"
    assert getattr(bo.create_llm_beat_generator, "__module__", "") == "ming_sim.beat_orchestration"


def test_default_wiring_keeps_production_atomic():
    """Transaction boundary must remain production atomic, not the connless wrapper."""
    assert applier.atomic.__name__ == "atomic"
    assert getattr(applier.atomic, "__module__", "") == "ming_sim.applier"
    assert web_app.atomic.__name__ == "atomic"


def test_default_gamesession_class_has_no_offline_scene_doubles():
    """Class-level offline _beat_generator / _scene_registry must not leak globally."""
    assert "_beat_generator" not in GameSession.__dict__
    assert "_scene_registry" not in GameSession.__dict__


def test_opt_in_offline_scene_and_connless_atomic_installs_light_shell_doubles(
    _offline_scene_beat_generator,
    _atomic_connless_test_shell_compat,
):
    """Light-shell tests can still request the shared offline doubles explicitly."""
    assert bo.create_llm_beat_generator.__name__ != "create_llm_beat_generator"
    gen = bo.create_llm_beat_generator(object())
    assert gen(type("I", (), {"beat_kind": "open", "person_name": ""})()) == "kind=open"

    assert "_beat_generator" in GameSession.__dict__
    assert "_scene_registry" in GameSession.__dict__
    assert GameSession._scene_registry.join(1) == []

    class _Connless:
        conn = None

    # Production atomic rejects non-_SuspendableConnection; opt-in wrapper allows no-conn shells.
    with applier.atomic(_Connless()):
        pass
    with web_app.atomic(_Connless()):
        pass


def test_opt_in_connless_wrapper_passthrough_real_db(
    _atomic_connless_test_shell_compat,
    game,
):
    """Opt-in atomic wrapper must still use real atomic for true GameDB connections."""
    db, _state, _content = game
    with applier.atomic(db):
        assert getattr(db.conn, "_atomic_depth", 0) >= 1
