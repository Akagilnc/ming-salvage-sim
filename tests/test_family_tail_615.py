"""#615 473·S9 族尾收口：贯通 tracer + 密令 0055 豁免 + 接缝核对。"""

import json

import pytest

import ming_sim.decree as decree_mod
from ming_sim import issues as issue_engine
from ming_sim.db import GameDB
from ming_sim.models import Character
from tests.dossier_test_helpers import _cost_events, _sat


BLOCKED_LAYERS = {"cabinet_drafting", "palace_rescript", "six_offices"}
SNAPSHOT_KEYS = {
    "imperial_authority_band",
    "appointment_tenure",
    "authorization_ids",
    "endorsement_entry_ids",
}


def _minister(db):
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "AND office_type!='后宫' ORDER BY name LIMIT 1"
    ).fetchone()["name"])


def _add_white_body(db, state, name):
    db.add_character(state, Character(
        name=name, office="白身", office_type="布衣", faction="中立",
        aliases=[], personal_skills=[], loyalty=50, ability=50, integrity=50,
        courage=50, style="", power_id="ming",
    ))


def _stage_break_rank_acting(db, state, content, name):
    """Real office admission → 越级署理 appointment dossier (break_rank auto)."""
    minister = _minister(db)
    pending_id = db.stage_pending_action(
        state.turn, kind="office", action="任命",
        minister_name=minister, target_id=None,
        payload={"name": name, "office": "陕西巡抚", "任别": "署理"},
    )
    db.commit_pending_actions(state, content=content, registry=None)
    dossier = next(
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] == pending_id
    )
    payload = json.loads(str(dossier["payload_json"] or "{}"))
    assert payload.get("任别") == "署理"
    assert payload.get("break_rank", {}).get("is_break_rank") is True
    return dossier


def _grant_self_scope_authority(db, state, content, holder):
    """Grant held privilege projected onto character:<holder> appointment domain."""
    grant_id = db.create_decree_dossier(
        state,
        action_type="authorization",
        decree_text="授以便宜行事之权",
        target_kind="character",
        target_id=holder,
        executor_kind="character",
        executor_id=holder,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
        payload={"mode": "ordinary"},
    )
    db.record_dossier_decision(grant_id, "promulgated")
    result = issue_engine.apply_score_extraction(db, state, {
        "authority_changes": [{
            "动作": "授予",
            "holder_id": holder,
            "privilege": "便宜行事",
            "scope": f"character:{holder}",
            "dossier_id": grant_id,
        }],
    }, content=content)["authority_changes"][0]
    assert result.get("rejected") is not True
    return int(result["authority_id"])


def _board_with_td4_three(db, state, content, *, appointee="越级署理甲"):
    """同档：署理任别 + 在持授权 + 背书，挂在同一越级任命案卷上。"""
    _add_white_body(db, state, appointee)
    dossier = _stage_break_rank_acting(db, state, content, appointee)
    authority_id = _grant_self_scope_authority(db, state, content, appointee)
    endorser = _minister(db)
    chat_turn_id = db.create_chat_turn(state, endorser, "family-tail-615", 0)
    endorsement_id = db.add_dossier_endorsement(
        int(dossier["id"]), form="会签", endorser_id=endorser,
        source_chat_turn_id=chat_turn_id,
    )
    context = decree_mod.build_promulgation_judge_context(
        db, state, [db.get_decree_dossier(dossier["id"])],
    )
    row = context["dossiers"][0]
    assert row["appointment_tenure"] == "署理"
    assert row["held_authorities"]
    assert int(row["held_authorities"][0]["id"]) == authority_id
    assert row["criteria_snapshot_source"]["authorization_ids"] == [str(authority_id)]
    assert row["endorsements"]
    assert row["criteria_snapshot_source"]["endorsement_entry_ids"] == [endorsement_id]
    assert set(row["criteria_snapshot_source"]) == SNAPSHOT_KEYS
    return {
        "dossier_id": int(dossier["id"]),
        "appointee": appointee,
        "authority_id": authority_id,
        "endorsement_id": endorsement_id,
        "context": context,
        "snapshot": dict(row["criteria_snapshot_source"]),
        "held_authorities": list(row["held_authorities"]),
        "endorsements": list(row["endorsements"]),
    }


@pytest.mark.parametrize(
    ("decision", "expected_status", "expect_force_costs"),
    [
        ("force_promulgated", "executing", True),
        ("withdrawn", "closed", False),
        ("hold", "proposed", False),
    ],
)
def test_break_rank_appointment_rescript_td4_tracer(
    game, monkeypatch, decision, expected_status, expect_force_costs,
):
    """P-2：越级任命打回三格 → 批红三选参数化 → TD-4 三要素 restore 同档。"""
    from ming_sim.decree import _chosen_rescript_actions, settle_with_delta

    db, state, content = game
    board = _board_with_td4_three(db, state, content)
    dossier_id = board["dossier_id"]

    # TD-4：关闭重开后任别/授权/背书与判官读端一致。
    db_path = db.path
    db.close()
    restored = GameDB(db_path, content)
    restored_state = restored.load_state()
    after = decree_mod.build_promulgation_judge_context(
        restored, restored_state,
        [restored.get_decree_dossier(dossier_id)],
    )["dossiers"][0]
    assert after["appointment_tenure"] == "署理"
    assert after["held_authorities"] == board["held_authorities"]
    assert after["endorsements"] == board["endorsements"]
    assert after["criteria_snapshot_source"] == board["snapshot"]

    # 打回三格 + 四键快照（fixture 注入，同 #563/#614 自证）。
    before_auth = restored_state.metrics["皇威"]
    before_faction = _sat(restored, "factions", "东林")
    gatekeeper = _minister(restored)
    verdict = {
        "dossier_id": dossier_id,
        "decision": "rejected",
        "blocked_layer": "six_offices",
        "primary_opponents": [{"kind": "faction", "key": "东林"}],
        "gatekeeper_id": gatekeeper,
        "reason": "越级署理封驳，名分不正。",
        "criteria_snapshot": board["snapshot"],
        "affected_parties": [
            {
                "kind": "faction", "key": "东林",
                "direction": "negative", "intensity": "weak",
            },
        ],
    }
    restored.apply_dossier_verdicts(
        restored_state, [verdict], content=content, registry=None,
    )
    rejected = restored.get_decree_dossier(dossier_id)
    assert rejected["status"] == "proposed"
    assert rejected["promulgation_decision"] == "rejected"
    assert rejected["rescript_pending"] is True
    assert rejected["promulgation_blocked_layer"] in BLOCKED_LAYERS
    assert rejected["promulgation_blocked_layer"] == "six_offices"
    opponents = rejected.get("primary_opponents") or json.loads(
        restored.conn.execute(
            "SELECT primary_opponents_json FROM decree_dossier_decisions "
            "WHERE dossier_id=? ORDER BY id DESC LIMIT 1",
            (dossier_id,),
        ).fetchone()[0]
    )
    assert opponents and all(
        set(item) == {"kind", "key"} and item["kind"] == "faction"
        for item in opponents
    )
    dec = restored.conn.execute(
        "SELECT gatekeeper_id,reason,criteria_snapshot_json "
        "FROM decree_dossier_decisions WHERE dossier_id=? ORDER BY id DESC LIMIT 1",
        (dossier_id,),
    ).fetchone()
    assert dec["gatekeeper_id"] == gatekeeper
    assert str(dec["reason"] or "").strip()
    snap = json.loads(dec["criteria_snapshot_json"])
    assert set(snap) == SNAPSHOT_KEYS
    assert snap == board["snapshot"]
    # ordinary 打回零代价；批红前盘面中性。
    assert restored_state.metrics["皇威"] == before_auth
    assert _sat(restored, "factions", "东林") == before_faction
    assert _cost_events(restored, dossier_id) == []

    actions = _chosen_rescript_actions([{
        "event_id": f"dossier:{dossier_id}",
        "choice": {"dossier_id": dossier_id, "dossier_decision": decision},
    }])
    assert actions == [{"dossier_id": dossier_id, "decision": decision}]

    def _forbid_verdicts(*_a, **_k):
        raise AssertionError(
            "player disposition rows must not enter apply_dossier_verdicts"
        )

    monkeypatch.setattr(restored, "apply_dossier_verdicts", _forbid_verdicts)
    settle_turn = restored_state.turn
    settle_with_delta(
        restored_state, restored, {}, before_turn=settle_turn, content=content,
        dossier_rescript_actions=actions,
    )

    row = restored.get_decree_dossier(dossier_id)
    assert row["status"] == expected_status
    authority_events = [
        x for x in _cost_events(restored, dossier_id)
        if x["cost_kind"] == "authority"
    ]
    sat_events = [
        x for x in _cost_events(restored, dossier_id)
        if x["cost_kind"] == "satisfaction"
    ]
    if expect_force_costs:
        assert row["promulgation_decision"] == "rejected"
        stigma = row.get("stigma") or []
        assert any(item.get("kind") == "midzhi" for item in stigma)
        # 强颁：中旨/污名代价流水落（对照 0056/#564）；绝对值可被 settle 其它步触动。
        assert {(x["cost_identity"], x["delta"]) for x in authority_events} == {
            ("override", -5),
        }
        assert sat_events  # 普通强颁补落反应
    else:
        # 收回/留中：零皇威/派系代价流水（批红选择不追加 override 账）
        assert authority_events == []
        assert sat_events == []
        assert _sat(restored, "factions", "东林") == before_faction
    if decision == "hold":
        assert row["rescript_pending"] is False
        assert int(row["held_turn"] or 0) == settle_turn
        assert row["promulgation_decision"] == "rejected"
        # 再判入口可接：仍 proposed、同 id，不要求本片再跑真判官。
        assert restored.get_decree_dossier(dossier_id)["id"] == dossier_id
        assert restored.get_decree_dossier(dossier_id)["status"] == "proposed"
    if decision == "withdrawn":
        assert row["promulgation_decision"] == "rejected"
    restored.close()


def test_secret_order_0055_exempt_not_in_rescript_with_break_rank(game, monkeypatch):
    """P-3：密令应允即颁、不入批红集；同回合明发越级旨仍走打回批红。"""
    db, state, content = game
    minister = _minister(db)
    appointee = "密令对照越级乙"
    _add_white_body(db, state, appointee)

    secret_pending = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister,
        target_id=None, payload={
            "title": "密查仓场", "content": "密查仓场侵冒，不得外泄。",
            "assignee": minister, "tags": [], "deadline_months": 0,
        },
    )
    office_pending = db.stage_pending_action(
        state.turn, kind="office", action="任命",
        minister_name=minister, target_id=None,
        payload={"name": appointee, "office": "陕西巡抚", "任别": "署理"},
    )
    db.commit_pending_actions(state, content=content, registry=None)

    secret = next(
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] == secret_pending
    )
    appointment = next(
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] == office_pending
    )
    assert secret["action_type"] == "secret_order"
    assert secret["status"] == "promulgated"
    assert appointment["status"] == "proposed"
    payload = json.loads(str(appointment["payload_json"] or "{}"))
    assert payload.get("break_rank", {}).get("is_break_rank") is True

    context = decree_mod.build_promulgation_judge_context(
        db, state, [db.get_decree_dossier(appointment["id"])],
    )
    snapshot = context["dossiers"][0]["criteria_snapshot_source"]
    verdict = {
        "dossier_id": int(appointment["id"]),
        "decision": "rejected",
        "blocked_layer": "six_offices",
        "primary_opponents": [{"kind": "faction", "key": "东林"}],
        "gatekeeper_id": None,
        "reason": "越级任命封驳。",
        "criteria_snapshot": snapshot,
        "affected_parties": [
            {
                "kind": "faction", "key": "东林",
                "direction": "negative", "intensity": "weak",
            },
        ],
    }

    monkeypatch.setattr(
        decree_mod, "create_promulgation_judge_agent", lambda *a, **k: object(),
    )
    monkeypatch.setattr(
        decree_mod, "run_agent_text",
        lambda *_a, **_k: json.dumps({"verdicts": [verdict]}, ensure_ascii=False),
    )
    monkeypatch.setattr(
        decree_mod, "create_season_simulator_agent", lambda *a, **k: object(),
    )
    monkeypatch.setattr(
        decree_mod,
        "simulate_season_with_payload",
        lambda *a, **k: ("越级旨被封驳，待批红。", k["simulator_payload"]),
    )

    result = decree_mod.resolve_directives(
        state, db, None, None, [object()], "密令对照越级", content=content,
    )

    assert result.awaiting is True
    # 密令应允即颁；awaiting 时打回 verdict 仍在 pending，批红决策只挂明发越级旨。
    assert db.get_decree_dossier(secret["id"])["status"] == "promulgated"
    pending = db.get_pending_promulgation_verdicts(state.turn)
    assert pending == [verdict]
    assert all(int(item["dossier_id"]) != int(secret["id"]) for item in pending)
    rescript_ids = {
        int(str(decision["event_id"]).split(":", 1)[1])
        for decision in result.decisions
        if str(decision.get("event_id") or "").startswith("dossier:")
    }
    assert int(appointment["id"]) in rescript_ids
    assert int(secret["id"]) not in rescript_ids
    labels = {
        option["label"]
        for decision in result.decisions
        if decision.get("event_id") == f"dossier:{appointment['id']}"
        for option in decision.get("options") or []
    }
    assert labels == {"强颁", "收回", "留中"}
