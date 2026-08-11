"""#522 招抚动作聚类：typed contract 与暂存路由。"""

from types import SimpleNamespace

import ming_sim.action_materialize  # noqa: F401 -- installs the package-owned catalog
from ming_sim.action_clusters import candidates_from_classifier_payload
from ming_sim.action_materialize import MaterializeCtx, run_materialize_pipeline


class RecordingDB:
    def __init__(self):
        self.staged = []

    def stage_directive_candidate(self, turn, minister_name, payload):
        self.staged.append((turn, minister_name, payload))
        return len(self.staged)


def _ctx(db, candidates):
    return MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=7)),
        character=SimpleNamespace(name="孙传庭", office_type="文官"),
        player_message="招抚李自成归顺朝廷。",
        reply="臣请遣使招抚李自成，许其归顺朝廷。",
        message_text="招抚李自成归顺朝廷。",
        explicit_prefixed=False,
        has_directive=False,
        pend_for_minister=[],
        out={},
        intent=None,
        intent_kind="none",
        llm_config=None,
        intent_candidates=candidates,
    )


def test_pacification_typed_candidate_stages_character_directive_only():
    candidate = candidates_from_classifier_payload(
        {"kind": "pacification", "target_id": "li_zicheng"}, soft=False,
    )
    db = RecordingDB()
    ctx = _ctx(db, candidate)

    run_materialize_pipeline(ctx)

    assert ctx.out["pending_action_id"] == 1
    assert db.staged == [(7, "孙传庭", {
        "text": "臣请遣使招抚李自成，许其归顺朝廷。",
        "actor": "孙传庭",
        "dossier_action_type": "pacification",
        "target_kind": "character",
        "target_id": "li_zicheng",
    })]


def test_pacification_without_character_target_does_not_stage_directive():
    for payload in (
        {"kind": "pacification"},
        {"kind": "pacification", "target_id": ""},
        {"kind": "pacification", "target_id": ["li_zicheng"]},
    ):
        db = RecordingDB()
        ctx = _ctx(db, [payload])

        run_materialize_pipeline(ctx)

        assert db.staged == []
        assert "pending_action_id" not in ctx.out


def test_non_pacification_candidate_does_not_stage_pacification_directive():
    db = RecordingDB()
    ctx = _ctx(db, [{"kind": "none"}])

    run_materialize_pipeline(ctx)

    assert db.staged == []
