"""场景声明与密令、任命暂存的行为契约。"""

from __future__ import annotations

import json
import threading
import types
from types import SimpleNamespace

import pytest

_POLICY_FIELDS = {
    "dossier_action_type": "policy",
    "target_kind": "issue",
    "target_id": "test-policy",
}

import ming_sim.audience_night as audience_night
import ming_sim.cli_backend as cb
import ming_sim.session as session_mod
from ming_sim.session import GameSession
from tests.dossier_test_helpers import TYPED_COVERT_EXTRACT, TYPED_COVERT_TASK, create_test_secret_order as _create_secret_order, promulgate_proposed_appointments


def test_opening_seed_secret_orders_empty_or_structured(game):
    """#1274 K1 seed 开局合约：生产开局同核无预置密令（或 content 来自结构化源）。"""
    db, _state, _ = game
    orders = db.list_secret_orders()
    # 当前生产开局：零条预置密令
    assert orders == []


def test_scene_secret_order_progress_stages_pending_not_direct_write(game):
    """转译记录往期密令进展先走候选闸门，不直写真实密令。"""
    from ming_sim.audience_translate import normalize_audience_declaration
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    minister = "毕自严"
    oid = _create_secret_order(db, state, minister, "查辽饷", "查辽饷侵冒。", [], deadline_months=0)
    db.conn.execute("UPDATE secret_orders SET turn_issued=? WHERE id=?", (state.turn - 1, oid))
    db.conn.commit()

    declaration = normalize_audience_declaration({"commissions": [{
        "text": "奏报密令进展。",
        "secret_order_progress": {"order_id": oid, "note": "已封存兵部辽饷册。"},
    }]})
    result = dispatch_declaration(db, state, declaration, minister_name=minister)
    assert result.commissions.rejected == []
    assert "已封存兵部辽饷册" not in (
        db.conn.execute("SELECT result FROM secret_orders WHERE id=?", (oid,)).fetchone()["result"] or ""
    )
    pending = db.list_pending_actions(state.turn)
    assert len(pending) == 1
    assert pending[0]["kind"] == "secret_order" and pending[0]["action"] == "记进展"
    assert pending[0]["target_id"] == oid


def test_scene_directive_midzhi_stages_draft(game):
    """场景交办明示中旨时暂存与成案皆保留模式。"""
    from ming_sim.audience_translate import normalize_audience_declaration
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    declaration = normalize_audience_declaration({"commissions": [{
        "text": "着户部清核辽饷。", "mode": "midzhi",
    }]})
    result = dispatch_declaration(db, state, declaration, minister_name="毕自严")
    assert result.commissions.rejected == []
    pending = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "directive"]
    assert len(pending) == 1
    pending_payload = json.loads(pending[0]["payload_json"])
    assert pending_payload["mode"] == "midzhi"

    db.commit_pending_actions(state, kind_filter="directive")
    db.ensure_dossiers_for_draft_directives(state)
    dossiers = db.list_decree_dossiers()
    assert len(dossiers) == 1
    assert dossiers[0]["mode"] == "midzhi"














def test_scene_promises_confirm_directive_and_secret_order_independently(game):
    """同轮两项应允：密令即落档，拟旨经收夜提交，不彼此吞并。"""
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    minister = next(iter(content.characters.values())).name
    directive_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={**_POLICY_FIELDS, "text": "着户部清核辽饷。", "actor": minister},
    )
    secret_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister,
        payload={"covert_task": TYPED_COVERT_TASK, "title": "暗查辽饷",
                 "content": "暗查辽饷侵冒。", "assignee": minister,
                 "tags": [], "deadline_months": 0},
    )
    result = dispatch_declaration(db, state, {"promises": [
        {"action_id": action_id, "decision": "应允"}
        for action_id in (directive_id, secret_id)
    ]}, minister_name=minister)
    assert result.promises.rejected == []
    assert {r["action_id"] for r in result.promises.applied} == {directive_id, secret_id}
    assert [order["title"] for order in db.list_secret_orders()] == ["暗查辽饷"]
    assert db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (directive_id,),
    ).fetchone()["night_approved"] == 1
    db.commit_pending_actions(state, action_ids=[directive_id])
    assert db.list_pending_actions(state.turn) == []
    directives = db.list_directives(state, statuses=("draft",))
    assert len(directives) == 1 and directives[0]["text"] == "着户部清核辽饷。"


def test_pending_directive_identity_version_increments_on_edit(game):
    """A decree forecast identity is the durable pending row plus its draft version."""
    from ming_sim.declaration_dispatch import (
        pending_action_decree_ref, stage_declaration,
    )
    from ming_sim.entities.staged_declaration.store import DecreeAlreadySettled

    db, state, content = game
    minister = next(iter(content.characters.values())).name
    pending_id = db.stage_directive_candidate(
        state.turn, minister, {**_POLICY_FIELDS, "text": "着户部清核辽饷。", "actor": minister},
    )

    row = db.conn.execute(
        "SELECT id,version FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()
    assert (int(row["id"]), int(row["version"])) == (pending_id, 1)
    old_ref = pending_action_decree_ref(pending_id, int(row["version"]))
    stage_declaration(db, decree_ref=old_ref, declaration={"commissions": []}, turn=state.turn)

    db.update_directive_candidate(pending_id, {
        **_POLICY_FIELDS,
        "text": "着户部重核辽饷。",
        "actor": minister,
    })
    row = db.conn.execute(
        "SELECT id,version FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()
    assert (int(row["id"]), int(row["version"])) == (pending_id, 2)
    assert db.conn.execute(
        "SELECT status FROM staged_declarations WHERE decree_ref=?",
        (old_ref,),
    ).fetchone()["status"] == "discarded"
    with pytest.raises(DecreeAlreadySettled):
        stage_declaration(
            db, decree_ref=old_ref, declaration={"commissions": []}, turn=state.turn,
        )


def test_undo_directive_edit_restores_text_with_new_forecast_version(game):
    from ming_sim.declaration_dispatch import (
        pending_action_decree_ref, stage_declaration,
    )

    db, state, content = game
    minister = next(iter(content.characters.values())).name
    pending_id = db.stage_directive_candidate(state.turn, minister, {**_POLICY_FIELDS, "text": "着户部清核辽饷。", "actor": minister})
    chat_turn_id = db.create_chat_turn(state, minister, "undo-directive-edit", 0)
    before = db.capture_chat_rollback_snapshot()
    db.update_directive_candidate(pending_id, {
        **_POLICY_FIELDS,
        "text": "着户部重核辽饷。",
        "actor": minister,
    })
    after = db.capture_chat_rollback_snapshot()
    db.record_chat_turn_rollback_diffs(chat_turn_id, before, after)

    db.undo_chat_turn(chat_turn_id)

    row = db.conn.execute(
        "SELECT id,version,payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()
    assert (int(row["id"]), int(row["version"])) == (pending_id, 3)
    assert json.loads(row["payload_json"])["text"] == "着户部清核辽饷。"
    restored_ref = pending_action_decree_ref(pending_id, 3)
    stage_declaration(db, decree_ref=restored_ref, declaration={"commissions": []}, turn=state.turn)


def test_withdraw_directive_invalidates_its_forecast(game):
    from ming_sim.declaration_dispatch import (
        pending_action_decree_ref, stage_declaration,
    )
    from ming_sim.entities.staged_declaration.store import DecreeAlreadySettled

    db, state, content = game
    minister = next(iter(content.characters.values())).name
    pending_id = db.stage_directive_candidate(state.turn, minister, {**_POLICY_FIELDS, "text": "着户部清核辽饷。", "actor": minister})
    forecast_ref = pending_action_decree_ref(pending_id, 1)
    stage_declaration(
        db, decree_ref=forecast_ref, declaration={"commissions": []}, turn=state.turn,
    )

    assert db.withdraw_pending_action(pending_id, state.turn)
    assert db.conn.execute(
        "SELECT 1 FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone() is None
    assert db.conn.execute(
        "SELECT status FROM staged_declarations WHERE decree_ref=?",
        (forecast_ref,),
    ).fetchone()["status"] == "discarded"
    with pytest.raises(DecreeAlreadySettled):
        stage_declaration(
            db, decree_ref=forecast_ref,
            declaration={"commissions": []}, turn=state.turn,
        )


def _forecast_decision_block():
    return "<<DECISION>>" + json.dumps({
        "title": "廷议",
        "context": "待择",
        "options": [{"label": "施行"}, {"label": "暂缓"}],
    }, ensure_ascii=False) + "<<END>>"


def _forecast_config():
    from ming_sim.models import LLMConfig

    return LLMConfig(
        api_key="test", base_url="https://example.invalid/v1", model="test-model",
    )




def test_scene_new_secret_order_is_not_confirmed_in_same_turn(game):
    """同轮新建密令不能被同轮应允声明直接落地。"""
    from ming_sim.audience_translate import normalize_audience_declaration
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    minister = "毕自严"
    next_id = db.conn.execute(
        "SELECT COALESCE(MAX(id), 0)+1 FROM pending_actions"
    ).fetchone()[0]
    declaration = normalize_audience_declaration({
        "commissions": [{"text": "密查辽饷。", "secret_order": {
            "title": "暗查辽饷", "content": "暗查辽饷侵冒。",
            "assignee": minister, "tags": [], "deadline_months": 0,
            "covert_task": TYPED_COVERT_TASK,
        }}],
        "promises": [{"action_id": next_id, "decision": "应允"}],
    })
    result = dispatch_declaration(db, state, declaration, minister_name=minister)
    assert result.commissions.rejected == []
    assert result.commissions.applied[0]["id"] == next_id
    assert len(result.promises.rejected) == 1
    assert db.list_secret_orders() == []
    pending = db.list_pending_actions(state.turn)
    assert len(pending) == 1 and pending[0]["kind"] == "secret_order"


def test_scene_two_independent_secret_commissions_commit_separately(game):
    """两条新交办分别暂存和落档，不因同一承办人合并成一案。"""
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, _content = game
    minister = "毕自严"
    declaration = {"commissions": [
        {"text": content, "secret_order": {
            "title": title, "content": content, "assignee": minister,
            "tags": [], "deadline_months": deadline, "covert_task": TYPED_COVERT_TASK,
        }}
        for title, content, deadline in (("暗查甲", "查甲", 0), ("暗查乙", "查乙", 3))
    ]}
    result = dispatch_declaration(db, state, declaration, minister_name=minister)
    assert len(result.commissions.applied) == 2
    assert result.commissions.rejected == []
    assert len(db.list_pending_actions(state.turn)) == 2
    assert db.list_secret_orders() == []
    db.commit_pending_actions(state)
    orders = db.list_secret_orders()
    assert {(r["title"], r["content"], r["due_turn"]) for r in orders} == {
        ("暗查甲", "查甲", 0), ("暗查乙", "查乙", state.turn + 3),
    }


@pytest.mark.parametrize("mode", [None, "ordinary", "midzhi"])
def test_scene_appointment_mode_contract(game, mode):
    """任免声明的显式密旨/普通模式不得被工具退役吞掉。"""
    from ming_sim.audience_translate import normalize_audience_declaration
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    minister = "毕自严"
    appointment = {"name": minister, "office": "户部尚书", "appoint_action": "任命"}
    if mode is not None:
        appointment["mode"] = mode
    declaration = normalize_audience_declaration({"commissions": [{
        "text": "着毕自严为户部尚书。", "appointment": appointment,
    }]})
    result = dispatch_declaration(db, state, declaration, minister_name=minister)
    assert result.commissions.rejected == []
    rows = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "office"]
    assert len(rows) == 1
    assert json.loads(rows[0]["payload_json"]).get("mode", "ordinary") == (mode or "ordinary")


def test_scene_appointment_region_id_stages_same_seat(game):
    """地方任所只来自声明 region_id，不从官名推断。"""
    from ming_sim.audience_translate import normalize_audience_declaration
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    minister = "毕自严"
    declaration = normalize_audience_declaration({"commissions": [{
        "text": "着毕自严为陕西巡抚。",
        "appointment": {"name": minister, "office": "陕西巡抚",
                        "appoint_action": "任命", "region_id": "shaanxi"},
    }]})
    result = dispatch_declaration(db, state, declaration, minister_name=minister)
    assert result.commissions.rejected == []
    rows = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "office"]
    assert len(rows) == 1
    payload = json.loads(rows[0]["payload_json"])
    assert payload["region_id"] == "shaanxi"
    assert payload["name"] == minister
    assert payload["office"] == "陕西巡抚"


@pytest.mark.parametrize(
    ("appointee", "seed_modes", "continue_mode", "expected_id_relation", "expected_modes"),
    [
        # 沉默续拟：同一 id，保留 midzhi
        ("续拟沉默", ("midzhi",), None, "same", ("midzhi",)),
        # 显式 ordinary：同一 id，原地降级
        ("续拟降级", ("midzhi",), "ordinary", "same", ("ordinary",)),
        # 多命中：不 INSERT，原行不动（人名须 ≤20，session 截断）
        ("续拟双命中", ("ordinary", "midzhi"), "ordinary", "zero", ("ordinary", "midzhi")),
    ],
)
def test_propose_appointment_continue_draft_same_direction(
    game, appointee, seed_modes, continue_mode, expected_id_relation, expected_modes,
):
    """#1731 场景任免续拟：同向命中合并/多命中禁插。"""
    from ming_sim.audience_translate import normalize_audience_declaration
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    minister = "毕自严"
    appointee = minister
    office = "户部尚书"
    seed_ids = []
    for mode in seed_modes:
        seed_ids.append(db.stage_pending_action(
            state.turn, kind="office", action="任命",
            minister_name=minister, target_id=None,
            payload={"text": "测试任免原文",
                "name": appointee, "office": office,
                "appointer": minister, "mode": mode,
            },
        ))
    appointment = {"name": appointee, "office": office, "appoint_action": "任命"}
    if continue_mode is not None:
        appointment["mode"] = continue_mode
    declaration = normalize_audience_declaration({"commissions": [{
        "text": "着毕自严继续掌户部。", "appointment": appointment,
    }]})
    result = dispatch_declaration(db, state, declaration, minister_name=minister)
    continued_id = result.commissions.applied[0]["id"] if result.commissions.applied else 0
    rows = [
        {"id": int(p["id"]), "mode": json.loads(p["payload_json"]).get("mode")}
        for p in db.list_pending_actions(state.turn)
        if p["kind"] == "office"
        and json.loads(p["payload_json"]).get("name") == appointee
        and json.loads(p["payload_json"]).get("office") == office
    ]
    if expected_id_relation == "same":
        assert continued_id == seed_ids[0]
        assert rows == [{"id": seed_ids[0], "mode": expected_modes[0]}]
    else:
        assert continued_id == 0
        assert len(result.commissions.rejected) == 1
        assert [r["id"] for r in rows] == seed_ids
        assert [r["mode"] for r in rows] == list(expected_modes)








@pytest.mark.parametrize("use_alias", [False, True])
def test_declared_noop_appointment_is_not_staged(game, use_alias):
    """结构化任免使用同一 canonical 目标与已在职判断，不重复立案。"""
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    target = next(
        ch for ch in content.characters.values()
        if getattr(ch, "power_id", "ming") == "ming"
        and getattr(ch, "office", "")
        and getattr(ch, "office_type", "") != "后宫"
        and (not use_alias or any(a != ch.name for a in (ch.aliases or [])))
        and db.get_character_status(ch.name)[0] == "active"
    )
    name = next(a for a in target.aliases if a != target.name) if use_alias else target.name
    result = dispatch_declaration(db, state, {"commissions": [{
        "text": "核对现任官职", "appointment": {
            "appoint_action": "任命", "name": name, "office": target.office,
        },
    }]}, minister_name="毕自严")
    assert result.commissions.applied == []
    assert result.commissions.rejected == []
    assert db.list_pending_actions(state.turn) == []


def _link_night_chat_turn(db, state, night_id, minister, user_text, minister_text):
    """在指定夜为大臣落一条完成态对话轮（user+minister 消息已 link），供按夜取回测。"""
    tid = db.create_chat_turn(
        state, minister, agno_session_id="", agno_runs_before=0, night_id=int(night_id))
    uid = db.append_chat_message(minister, state.turn, "user", user_text)
    mid = db.append_chat_message(minister, state.turn, "minister", minister_text)
    db.update_chat_turn_messages(tid, user_message_id=uid, minister_message_id=mid)
    return tid




def test_begin_turn_syncs_offices_with_runtime_llm_config(monkeypatch):
    seen = []
    cfg = SimpleNamespace(channel="api")
    state = SimpleNamespace(turn_phase="summoning")
    fake_db = SimpleNamespace(
        load_state=lambda: state,
        apply_historical_deaths=lambda state: [],
        apply_historical_debuts=lambda state: [],
        apply_historical_power_renames=lambda state: [],
        previous_turn_summary=lambda state: "",
        save_state=lambda state: None,
    )
    fake = SimpleNamespace(
        state=state,
        db=fake_db,
        content=SimpleNamespace(characters={}),
        llm_config=cfg,
        agno_db=SimpleNamespace(),
        previous_summary="",
        last_decree="",
        last_report="",
        _begun=False,
        auto_save=lambda label: None,
        turn_snapshot=lambda: SimpleNamespace(ok=True),
    )
    monkeypatch.setattr(session_mod, "_sync_offices_from_db_impl",
                        lambda content, db, llm_config=None: seen.append(llm_config))

    GameSession.begin_turn(fake)

    assert seen == [cfg]


def test_chat_rollback_refresh_syncs_offices_with_runtime_llm_config(monkeypatch):
    seen = []
    cfg = SimpleNamespace(channel="api")
    state = SimpleNamespace(turn_phase="summoning")
    fake_db = SimpleNamespace(load_state=lambda: state)
    fake = SimpleNamespace(
        state=state,
        db=fake_db,
        content=SimpleNamespace(characters={}),
        llm_config=cfg,
        agno_db=SimpleNamespace(),
        previous_summary="",
    )
    monkeypatch.setattr(session_mod, "_sync_offices_from_db_impl",
                        lambda content, db, llm_config=None: seen.append(llm_config))

    GameSession.refresh_runtime_after_chat_rollback(fake)

    assert seen == [cfg]


# ── codexC-1：会话动作（非前缀）必须经 session 路径落地，不再只在 web 有 ──
