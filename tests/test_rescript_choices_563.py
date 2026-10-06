import json

import pytest

import ming_sim.cli_backend as cli_backend
from tests.dossier_test_helpers import rejected_verdict



def _make_midzhi_dossier(db, state, *, target_id="river-works"):
    return db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="特旨清核河工",
        target_kind="issue",
        target_id=target_id,
        payload={"mode": "midzhi"},
    )

def _rejected_verdict(dossier_id):
    # Preserve suite-specific gatekeeper/band/reason differences via builder knobs.
    return rejected_verdict(
        dossier_id, "强盛", gatekeeper_id="韩爌", reason="科臣封驳",
    )

@pytest.mark.parametrize(
    ("emperor_text", "extracted_mode", "expected"),
    [("中旨直发，清核仓场", "普通", "ordinary"),
     ("清核仓场", "midzhi", "midzhi")],
)
def test_manual_mode_uses_typed_extractor_judgment(
    monkeypatch, emperor_text, extracted_mode, expected,
):
    extracted = json.dumps({
        "拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue",
        "目标ID": "granary", "颁布方式": extracted_mode,
    }, ensure_ascii=False)
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config", lambda *_args, **_kwargs: (extracted, {}),
    )
    assert cli_backend.capture_manual_directive_payload(emperor_text)["mode"] == expected

def test_manual_edit_preserves_existing_mode_when_text_and_extractor_are_silent(monkeypatch):
    extracted = json.dumps({
        "拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue",
        "目标ID": "granary",
    }, ensure_ascii=False)
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config", lambda *_args, **_kwargs: (extracted, {}),
    )

    payload = cli_backend.capture_manual_directive_payload(
        "增列核验期限", existing_mode="midzhi",
    )

    assert payload["mode"] == "midzhi"

def test_predeclared_midzhi_promulgation_persists_stigma(game):
    db, state, _content = game
    dossier_id = _make_midzhi_dossier(db, state)
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    assert db.get_decree_dossier(dossier_id)["stigma"] == [{
        "kind": "midzhi", "reason": "predeclared", "turn": state.turn,
        "source_action": "promulgated",
    }]

def test_missing_dossier_mode_defaults_to_ordinary(game):
    db, state, _content = game
    dossier_id = _make_midzhi_dossier(db, state)
    db.conn.execute(
        "UPDATE decree_dossiers SET payload_json='{}' WHERE id=?", (dossier_id,)
    )

    assert db.get_decree_dossier(dossier_id)["mode"] == "ordinary"

@pytest.mark.parametrize(
    ("caller_mode", "minister_text", "expected"),
    [("ordinary", "中旨直发，清核河工", "ordinary"),
     ("midzhi", "清核河工", "midzhi"),
     (None, "中旨直发，清核河工", "ordinary")],
)
def test_declared_staging_uses_typed_mode_not_minister_text(
    game, caller_mode, minister_text, expected,
):
    db, state, _content = game
    candidate_id = db.stage_directive_candidate(
        state.turn, "温体仁", {"text": minister_text, "actor": "温体仁",
                             "mode": cli_backend.resolve_directive_mode(extracted=caller_mode),
                             "dossier_action_type": "special_decree", "target_kind": "policy",
                             "target_id": "river-works"},
    )
    db.commit_pending_actions(state, action_ids={candidate_id})
    db.ensure_dossiers_for_draft_directives(state)

    dossiers = db.list_decree_dossiers()
    assert len(dossiers) == 1
    assert dossiers[0]["mode"] == expected

def test_presence_aware_mode_preserves_draft_until_explicit_override(game):
    db, state, _content = game
    candidate_id = db.stage_directive_candidate(
        state.turn, "温体仁", {"text": "中旨直发，清核河工", "actor": "温体仁",
                             "mode": "midzhi", "dossier_action_type": "special_decree",
                             "target_kind": "policy", "target_id": "river-works"},
    )
    db.update_directive_candidate(candidate_id, {"text": "增列核验期限"})
    pending = next(
        row for row in db.list_pending_actions(state.turn)
        if row["id"] == candidate_id
    )
    assert json.loads(pending["payload_json"])["mode"] == "midzhi"

    db.update_directive_candidate(candidate_id, {"mode": "ordinary"})
    pending = next(
        row for row in db.list_pending_actions(state.turn)
        if row["id"] == candidate_id
    )
    assert json.loads(pending["payload_json"])["mode"] == "ordinary"

    db.commit_pending_actions(state, kind_filter="directive")
    db.ensure_dossiers_for_draft_directives(state)
    dossiers = db.list_decree_dossiers()
    assert len(dossiers) == 1
    assert dossiers[0]["mode"] == "ordinary"

def test_held_dossier_rejection_stigma_is_idempotent_across_months(game):
    db, state, _content = game
    dossier_id = _make_midzhi_dossier(db, state)
    db.apply_dossier_promulgation(
        state, dossier_id, "rejected", blocked_layer="six_offices", reason="科臣封驳",
    )
    db.record_dossier_decision(dossier_id, "hold")
    state.turn += 1
    db.conn.execute("UPDATE game_state SET turn=? WHERE id=1", (state.turn,))
    db.apply_dossier_promulgation(
        state, dossier_id, "rejected", blocked_layer="six_offices", reason="科臣再驳",
    )

    stored = db.get_decree_dossier(dossier_id)
    decisions = db.conn.execute(
        "SELECT turn,decision FROM decree_dossier_decisions "
        "WHERE dossier_id=? AND rescript_action='' ORDER BY id",
        (dossier_id,),
    ).fetchall()
    assert [(row["turn"], row["decision"]) for row in decisions] == [
        (state.turn - 1, "rejected"),
        (state.turn, "rejected"),
    ]
    assert stored["stigma"] == [{
        "kind": "midzhi", "reason": "predeclared", "turn": state.turn - 1,
        "source_action": "rejected",
    }]

def test_rejected_midzhi_and_force_promulgation_are_idempotent(game):
    db, state, _content = game
    dossier_id = _make_midzhi_dossier(db, state)

    for _ in range(2):
        db.apply_dossier_verdicts(state, [_rejected_verdict(dossier_id)])
    db.apply_dossier_promulgation(state, dossier_id, "force_promulgated")

    with pytest.raises(ValueError):
        db.apply_dossier_promulgation(state, dossier_id, "force_promulgated")

    assert db.get_decree_dossier(dossier_id)["stigma"] == [
        {"kind": "midzhi", "reason": "predeclared", "turn": state.turn,
         "source_action": "rejected"},
    ]

def test_rejected_ordinary_force_promulgation_adds_rescript_stigma(game):
    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id="river-works", payload={"mode": "ordinary"},
    )
    db.apply_dossier_verdicts(state, [_rejected_verdict(dossier_id)])
    db.apply_dossier_promulgation(state, dossier_id, "force_promulgated")

    assert db.get_decree_dossier(dossier_id)["stigma"] == [{
        "kind": "midzhi", "reason": "rescript", "turn": state.turn,
        "source_action": "force_promulgated",
    }]

@pytest.mark.parametrize("labels", [["", "乙"], ["甲", "甲"]])
def test_decision_parser_rejects_empty_or_ambiguous_labels(labels):
    from ming_sim.settlement_payload import parse_decision_blocks

    block = {
        "title": "歧义抉择", "context": "c",
        "options": [{"label": label, "hint": "h"} for label in labels],
    }
    raw = f"<<DECISION>>{json.dumps(block, ensure_ascii=False)}<<END>>"
    decisions = parse_decision_blocks(raw)
    assert decisions == []

