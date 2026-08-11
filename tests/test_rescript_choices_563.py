import json

import pytest

import ming_sim.cli_backend as cli_backend
import ming_sim.decree as decree_mod


def _make_midzhi_dossier(db, state, *, target_id="river-works"):
    return db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="特旨清核河工",
        target_kind="issue",
        target_id=target_id,
        payload={"mode": "midzhi"},
    )


def test_real_midzhi_entry_reaches_provider_and_persists_stigma(game, monkeypatch):
    db, state, content = game
    extracted = json.dumps({
        "拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue",
        "目标ID": "river-works", "颁布方式": "中旨直发",
    }, ensure_ascii=False)
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config", lambda *_args, **_kwargs: (extracted, {}),
    )
    payload = cli_backend.capture_manual_directive_payload("中旨直发，清核河工")
    directive_id = db.add_directive(
        state, None, "中旨直发，清核河工", "手动新增", dossier_payload=payload,
    )
    db.ensure_dossiers_for_draft_directives(state)
    dossier = db.get_dossier_for_directive(directive_id)
    seen_modes = []

    def provider(dossiers, _state):
        seen_modes.extend(row["mode"] for row in dossiers)
        return [{"dossier_id": dossier["id"], "decision": "promulgated"}]

    monkeypatch.setattr(
        db, "list_decree_dossiers_for_simulation",
        lambda _turn: (_ for _ in ()).throw(RuntimeError("tracer stop")),
    )
    with pytest.raises(RuntimeError, match="tracer stop"):
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "中旨直发，清核河工",
            content=content, promulgation_verdict_provider=provider,
        )
    db.apply_dossier_verdicts(state, db.get_pending_promulgation_verdicts(state.turn))

    stored = db.get_decree_dossier(dossier["id"])
    assert payload["mode"] == "midzhi"
    assert seen_modes == ["midzhi"]
    assert stored["stigma"] == [{
        "kind": "midzhi", "reason": "predeclared", "turn": state.turn,
        "source_action": "promulgated",
    }]


def test_ordinary_entry_remains_ordinary(monkeypatch):
    extracted = json.dumps({
        "拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue",
        "目标ID": "granary", "颁布方式": "普通",
    }, ensure_ascii=False)
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config", lambda *_args, **_kwargs: (extracted, {}),
    )
    assert cli_backend.capture_manual_directive_payload("清核仓场")["mode"] == "ordinary"


@pytest.mark.parametrize(
    ("column", "stored", "message"),
    [
        ("payload_json", "{", "payload_json 无效"),
        ("payload_json", "[]", "payload_json 非对象"),
        ("payload_json", '{"mode":"secret"}', "mode 非法"),
        ("stigma_json", "{}", "stigma_json 非列表"),
    ],
)
def test_corrupt_dossier_state_fails_at_db_read_seam(game, column, stored, message):
    db, state, _content = game
    dossier_id = _make_midzhi_dossier(db, state)
    db.conn.execute(f"UPDATE decree_dossiers SET {column}=? WHERE id=?", (stored, dossier_id))

    with pytest.raises(ValueError, match=message):
        db.get_decree_dossier(dossier_id)


def test_rejected_midzhi_and_force_promulgation_are_idempotent(game):
    db, state, _content = game
    dossier_id = _make_midzhi_dossier(db, state)

    db.apply_dossier_promulgation(
        state, dossier_id, "rejected", blocked_layer="six_offices", reason="科臣封驳"
    )
    db.apply_dossier_promulgation(state, dossier_id, "force_promulgated")
    db.apply_dossier_promulgation(state, dossier_id, "force_promulgated")

    assert db.get_decree_dossier(dossier_id)["stigma"] == [
        {"kind": "midzhi", "reason": "predeclared", "turn": state.turn,
         "source_action": "rejected"},
        {"kind": "midzhi", "reason": "rescript", "turn": state.turn,
         "source_action": "force_promulgated"},
    ]
