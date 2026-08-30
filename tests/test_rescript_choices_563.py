import json

import pytest

import ming_sim.cli_backend as cli_backend
import ming_sim.decree as decree_mod
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


@pytest.mark.parametrize("extractor_result", ["missing-mode", "failure"])
def test_real_midzhi_entry_reaches_provider_and_persists_stigma(
    game, monkeypatch, extractor_result,
):
    db, state, content = game
    extracted = json.dumps({
        "拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue",
        "目标ID": "river-works",
    }, ensure_ascii=False)
    if extractor_result == "missing-mode":
        backend = lambda *_args, **_kwargs: (extracted, {})
    else:
        def backend(*_args, **_kwargs):
            raise RuntimeError("extractor unavailable")
    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    payload = cli_backend.capture_manual_directive_payload("中旨直发，清核河工")
    directive_id = db.add_directive(
        state, None, "中旨直发，清核河工", "手动新增", dossier_payload=payload,
    )
    db.ensure_dossiers_for_draft_directives(state)
    dossier = db.get_dossier_for_directive(directive_id)
    seen_modes = []

    def provider(dossiers, _state):
        seen_modes.extend(row["mode"] for row in dossiers)
        return [{
            "dossier_id": dossier["id"], "decision": "promulgated",
            "affected_parties": [
                {"kind": "faction", "key": "东林", "direction": "negative", "intensity": "weak"},
            ],
        }]

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


def test_rejected_unpromulgatable_midzhi_omits_force_at_public_resolve_seam(
    game, monkeypatch,
):
    db, state, content = game
    dossier_id = _make_midzhi_dossier(db, state)

    def provider(_dossiers, _state):
        return [rejected_verdict(dossier_id, midzhi=True)]

    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: object())
    monkeypatch.setattr(
        decree_mod,
        "simulate_season_with_payload",
        lambda _simulator, _state, _db, _decree_text, _previous, **kwargs: (
            "本月邸报。", kwargs["simulator_payload"],
        ),
    )

    result = decree_mod.resolve_directives(
        state, db, None, None, [object()], "中旨直发，清核河工",
        content=content, promulgation_verdict_provider=provider,
    )

    assert result.awaiting is True
    dossier_decisions = {
        option["dossier_decision"]
        for decision in result.decisions
        if decision["event_id"] == f"dossier:{dossier_id}"
        for option in decision["options"]
    }
    assert dossier_decisions == {"withdrawn", "hold"}
    assert "force_promulgated" not in dossier_decisions


@pytest.mark.parametrize(
    ("emperor_text", "expected"),
    [("清核仓场", "ordinary"), ("中旨直发，清核仓场", "midzhi")],
)
def test_manual_mode_declaration_overrides_extractor(monkeypatch, emperor_text, expected):
    extracted = json.dumps({
        "拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue",
        "目标ID": "granary", "颁布方式": "普通",
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
     (None, "中旨直发，清核河工", "midzhi")],
)
def test_explicit_staging_prefers_caller_authority_before_minister_text(
    game, caller_mode, minister_text, expected,
):
    db, state, _content = game
    candidate_id = db.stage_explicit_directive(
        state.turn, "温体仁", minister_text, mode=caller_mode,
    )
    db.commit_pending_actions(state, action_ids={candidate_id})
    db.ensure_dossiers_for_draft_directives(state)

    dossiers = db.list_decree_dossiers()
    assert len(dossiers) == 1
    assert dossiers[0]["mode"] == expected


def test_presence_aware_mode_preserves_draft_until_explicit_override(game):
    db, state, _content = game
    candidate_id = db.stage_explicit_directive(
        state.turn, "温体仁", "中旨直发，清核河工",
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

    with pytest.raises(ValueError, match="强颁只可承接"):
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


# ---------------------------------------------------------------------------
# #657 片2：canonical / capability 回验
# ---------------------------------------------------------------------------

def test_657_canonical_choice_stable_key_order():
    from ming_sim.rescript_actions import canonical_choice
    a = canonical_choice({
        "decision_key": "rescript_draft:1:0",
        "action": "follow_draft",
        "draft_capability": "abc",
        "label": "甲",
        "hint": "h",
        "note": "批",
    })
    b = canonical_choice({
        "hint": "h",
        "label": "甲",
        "action": "follow_draft",
        "decision_key": "rescript_draft:1:0",
        "draft_capability": "abc",
        "note": "批",
    })
    assert a == b
    assert a["decision_key"] == "rescript_draft:1:0"
    assert a["action"] == "follow_draft"


def test_financial_decision_uses_stored_option_not_client_payload():
    """普通亲裁只按 label 选项；机械拨帑字段由服务端 option 定权。"""
    from ming_sim import rescript_actions as ra

    key = "decision:3:0"
    stored = {
        "label": "发内帑三十万两", "hint": "济军",
        "action_type": "grant_allocation", "grant_action": "协饷",
        "account": "内库", "amount": 30, "purpose": "补饷",
        "target_kind": "army", "target_id": "guanning", "cadence": "一次性",
    }
    desk = [{
        "decision_key": key, "kind": "decision", "turn": 3, "idx": 0,
        "status": "pending", "options": [stored, {"label": "暂缓", "hint": "守财"}],
    }]
    batch = ra.validate_all(desk, [{
        "decision_key": key, "label": stored["label"],
        "action_type": "punishment", "account": "国库", "amount": 999,
    }])
    choice = batch.items[0].choice
    assert choice["action_type"] == "grant_allocation"
    assert choice["account"] == "内库"
    assert choice["amount"] == 30


def test_657_capability_revalidate_on_follow(game):
    """服务端回验：请求 capability 必须等于对当前 option 结构化字段重算值。"""
    from ming_sim.decree_vocabulary import derive_draft_capability
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option
    from ming_sim import rescript_actions as ra

    db, state, _content = game
    opt = normalize_rescript_layer_a_option({
        "label": "发帑赈济", "hint": "所安者饥民",
        "action_type": "assignment", "assignee_name": "",
        "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈",
    })
    assert opt["draft_capability"] == derive_draft_capability(opt)
    db.save_rescript_drafts(int(state.turn), [{
        "title": "急", "context": "c",
        "options": [opt, {"label": "备", "hint": "b",
                           "draft_capability": derive_draft_capability({"label": "备"})}],
        "actor_name": "A", "actor_office": "o", "actor_faction": "f",
    }])
    db.conn.commit()
    desk = db.list_rescript_desk(int(state.turn))
    key = desk[0]["decision_key"]
    # 正确 cap 通过
    batch = ra.validate_all(desk, [{
        "decision_key": key, "action": "follow_draft",
        "draft_capability": opt["draft_capability"], "label": opt["label"],
    }])
    assert batch.items[0].choice["draft_capability"] == opt["draft_capability"]
    # 旧 cap（改票后）拒
    with pytest.raises(ValueError, match="capability|stale"):
        ra.validate_all(desk, [{
            "decision_key": key, "action": "follow_draft",
            "draft_capability": "old-round-cap", "label": opt["label"],
        }])
