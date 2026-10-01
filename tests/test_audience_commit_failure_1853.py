"""#1853 P1/P2：召对应允真落库异常不得吞成假成功；夜里预推耗尽要有原位恢复接缝。

P1 现象（判官实测）：真实 HTTP 下一轮召对应允密令，落库边界抛真异常时
action.status=failed、orders=0，而 extract_status=done、error_pack_path=""，
chat／scroll 重试列表皆空——密令没落，界面却显示本轮已整理。

P2 现象：夜里非 429 预推耗尽（decree_forecast._submit_snapshot_job）只完成票据、
不留任何失败动作；chat／scroll 无失败行，staged_count=0，撤掉故障后无从重试。

两处都验「失败必须显露 + 原位可重试 + 已成不重落」，不按文案措辞断言。
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

import ming_sim.decree as decree_mod
import ming_sim.decree_forecast as forecast_mod
import ming_sim.month_translate as month_translate
from ming_sim.audience_night import open_night
from ming_sim.declaration_dispatch import pending_action_decree_ref
from ming_sim.exceptions import LLMUnavailable
from ming_sim.session_write_queue import get_session_write_queue
from tests.conftest import (
    offline_empty_audience_translate,
    persist_and_schedule_scene,
    stub_audience_translate,
)
from tests.dossier_test_helpers import TYPED_COVERT_TASK, create_test_secret_order
from tests.test_decree_forecast_1861 import _sess


def _secret_commission(action_id: int) -> dict:
    return {
        "promises": [{"action_id": action_id, "decision": "应允"}],
    }


def _stage_secret_order(db, state, ctid, minister: str) -> int:
    return db.stage_pending_action(
        int(state.turn), "secret_order", "新建", minister,
        {
            "title": "夜行查饷", "content": "着即密核三边饷数。",
            "assignee": minister, "tags": [],
            "covert_task": TYPED_COVERT_TASK,
            "origin_chat_message_id": int(db.conn.execute(
                "SELECT id FROM chat_messages ORDER BY id DESC LIMIT 1",
            ).fetchone()["id"]),
        },
        source_chat_turn_id=int(ctid),
    )


def _active_minister(content) -> str:
    for c in content.characters.values():
        if c.status == "active" and c.power_id == "ming" and c.office_type not in {"后宫", "宗藩"}:
            return c.name
    raise AssertionError("找不到在朝大臣")


# ── P1 ────────────────────────────────────────────────────────────────────

def test_secret_order_commit_code_error_is_not_laundered_into_success(game, monkeypatch):
    """P1：应允直写落库真异常 → 本轮标 pending + 错误包，密令不落也不谎报成功。"""
    db, state, content = game
    night = open_night(db, state)
    minister = _active_minister(content)
    ctid = db.create_chat_turn(
        state, "殿上", "s", 0, night_id=int(night["id"]), status="active",
    )
    db.append_chat_message("殿上", int(state.turn), "user", "着王绍徽密核三边饷数。")
    action_id = _stage_secret_order(db, state, ctid, minister)

    boom = RuntimeError("落库边界故障（受控注入）")
    monkeypatch.setattr(
        type(db), "create_secret_order",
        lambda self, *a, **k: (_ for _ in ()).throw(boom),
    )

    def translate_fn(prompt, llm_config):
        return {
            **offline_empty_audience_translate(prompt, llm_config),
            **_secret_commission(action_id),
        }

    sess = _sess(db, state, content, monkeypatch, translate_fn)
    result = sess.scene_chat("准此旨", chat_turn_id=ctid)
    future = persist_and_schedule_scene(sess, db, result)
    assert future is not None
    with pytest.raises(BaseException):
        future.result()

    # 密令确实没落（本轮回滚），且原动作仍可核、仍可重试——不是终态 failed。
    assert db.list_secret_orders() == []
    row = db.conn.execute(
        "SELECT status, source_chat_turn_id FROM pending_actions WHERE id=?",
        (action_id,),
    ).fetchone()
    assert row["status"] == "pending"
    assert int(row["source_chat_turn_id"]) == int(ctid)
    # 假成功被拆掉：本轮不标 done，失败行带错误包出现在既有翻译重试列表里。
    turn = db.conn.execute(
        "SELECT extract_status, error_pack_path FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()
    assert turn["extract_status"] == "pending"
    assert str(turn["error_pack_path"] or "")

    from ming_sim.audience_translation import list_pending_translations

    retries = list_pending_translations(db, write_queue=get_session_write_queue(sess))
    assert [int(r["chat_turn_id"]) for r in retries] == [int(ctid)]

    # 撤掉故障后原位重试：只补这一轮，成功即收水位，密令落库。
    monkeypatch.undo()
    stub_audience_translate(monkeypatch, translate_fn)
    from ming_sim.audience_translation import catch_up_pending_translations

    stats = catch_up_pending_translations(
        db, state, chat_turn_id=int(ctid),
        llm_config=sess.llm_config, write_gate=sess._write_gate,
        write_queue=get_session_write_queue(sess),
    )
    assert stats["extracted"] == 1 and stats["pending"] == 0
    assert len(db.list_secret_orders()) == 1
    turn = db.conn.execute(
        "SELECT extract_status FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()
    assert turn["extract_status"] == "done"


def test_dossier_link_rejection_stays_business_refusal_not_loud(game, monkeypatch):
    """业务拒收与系统失败分流：模型指向不存在案卷仍走 durable 审计 + 终态 failed。"""
    db, state, content = game
    night = open_night(db, state)
    minister = _active_minister(content)
    ctid = db.create_chat_turn(
        state, "殿上", "s", 0, night_id=int(night["id"]), status="active",
    )
    db.append_chat_message("殿上", int(state.turn), "user", "着密核三边饷数。")
    action_id = _stage_secret_order(db, state, ctid, minister)
    payload = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (action_id,),
    ).fetchone()["payload_json"])
    payload["dossier_links"] = [{
        "target_dossier_id": 999999, "relation_type": "护卫", "note": "护送",
    }]
    db.conn.execute(
        "UPDATE pending_actions SET payload_json=? WHERE id=?",
        (json.dumps(payload, ensure_ascii=False), action_id),
    )
    db.conn.commit()

    def translate_fn(prompt, llm_config):
        return {
            **offline_empty_audience_translate(prompt, llm_config),
            **_secret_commission(action_id),
        }

    sess = _sess(db, state, content, monkeypatch, translate_fn)
    result = sess.scene_chat("准此旨", chat_turn_id=ctid)
    future = persist_and_schedule_scene(sess, db, result)
    future.result()

    assert db.list_secret_orders() == []
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (action_id,),
    ).fetchone()["status"] == "failed"
    audit = db.list_dossier_link_rejections(pending_action_id=action_id)
    assert audit
    assert int(audit[-1]["pending_action_id"]) == int(action_id)
    assert int(audit[-1]["target_dossier_id"]) == 999999
    assert audit[-1]["relation_type"] == "护卫"
    turn = db.conn.execute(
        "SELECT extract_status, error_pack_path FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()
    assert turn["extract_status"] == "done"
    assert str(turn["error_pack_path"] or "") == ""


# ── P2 ────────────────────────────────────────────────────────────────────

def _approved_directive(db, state, night_id, ctid, minister: str, text: str) -> int:
    return db.stage_pending_action(
        int(state.turn), kind="directive", action="拟旨", minister_name=minister,
        payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "test-policy", "actor": minister, "mode": "ordinary",
            "text": text,
        },
        source_chat_turn_id=int(ctid),
    )


def _drain(sess) -> None:
    assert get_session_write_queue(sess).wait_idle(timeout_s=10)


def _consumer(sess):
    from web_app import WebGame

    game = WebGame.__new__(WebGame)
    game.session = sess
    game.chat_history = {}
    return game


def _foreign_minister(content) -> str:
    for character in content.characters.values():
        if getattr(character, "power_id", "ming") != "ming":
            return character.name
    raise AssertionError("找不到非大明人物")


def test_ineligible_secret_order_is_business_refusal(game, monkeypatch):
    """承办资格是业务拒收：终态该项，转译可完成，不留系统错误包。"""
    db, state, content = game
    night = open_night(db, state)
    assignee = _foreign_minister(content)
    ctid = db.create_chat_turn(
        state, "殿上", "s", 0, night_id=int(night["id"]), status="active",
    )
    db.append_chat_message("殿上", int(state.turn), "user", "着外藩承办密核。")
    action_id = _stage_secret_order(db, state, ctid, assignee)

    def translate_fn(prompt, llm_config):
        return {
            **offline_empty_audience_translate(prompt, llm_config),
            **_secret_commission(action_id),
        }

    sess = _sess(db, state, content, monkeypatch, translate_fn)
    result = sess.scene_chat("准此旨", chat_turn_id=ctid)
    future = persist_and_schedule_scene(sess, db, result)
    future.result()

    assert db.list_secret_orders() == []
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (action_id,),
    ).fetchone()["status"] == "failed"
    reports = db.conn.execute(
        "SELECT category FROM rejection_reports",
    ).fetchall()
    assert any(row["category"] == "ineligible_power" for row in reports)
    turn = db.conn.execute(
        "SELECT extract_status, error_pack_path FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()
    assert turn["extract_status"] == "done"
    assert str(turn["error_pack_path"] or "") == ""


def test_closed_secret_order_rush_fails_one_item_and_commits_the_rest(game):
    """已结案密令的催办是业务拒收：该项 failed，同批其余项照常 committed，不抛。"""
    db, state, content = game
    minister = _active_minister(content)
    live = create_test_secret_order(db, state, minister, "在办密令", "仍在办", [])
    closed = create_test_secret_order(db, state, minister, "已结密令", "已结案", [])
    db.close_secret_order(closed, "done", "账目已核", state.turn)
    first = db.stage_pending_action(
        state.turn, "secret_order", "更新", minister,
        {"new_title": "在办改题", "new_content": "仍在办"},
        target_id=live,
    )
    rush = db.stage_pending_action(
        state.turn, "secret_order", "催办", minister,
        {"deadline_months": 1, "reason": "加急"},
        target_id=closed,
    )
    second = db.stage_pending_action(
        state.turn, "secret_order", "更新", minister,
        {"new_title": "在办再改", "new_content": "仍在办"},
        target_id=live,
    )

    applied = db.commit_pending_actions(state, content=content)

    statuses = {
        int(row["id"]): row["status"]
        for row in db.conn.execute(
            "SELECT id, status FROM pending_actions WHERE id IN (?,?,?)",
            (first, rush, second),
        )
    }
    assert statuses[first] == "committed"
    assert statuses[rush] == "failed"
    assert statuses[second] == "committed"
    assert {int(item["id"]) for item in applied} == {first, second}
    assert db.get_secret_order(live)["title"] == "在办再改"
    assert db.get_secret_order(closed)["status"] == "done"


def test_night_forecast_exhaustion_resumes_from_real_consumer(game, monkeypatch, tmp_path):
    """非 429 耗尽留下相位和错误包。重试后同一交办只暂存一次，相位清掉。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    db, state, content = game
    night = open_night(db, state)
    minister = _active_minister(content)
    ctid = db.create_chat_turn(
        state, "殿上", "s", 0, night_id=int(night["id"]), status="active",
    )
    uid = db.append_chat_message("殿上", int(state.turn), "user", "拟一道核实辽饷的旨。")
    db.conn.execute(
        "UPDATE chat_turns SET user_message_id=? WHERE id=?",
        (uid, ctid),
    )
    db.conn.commit()
    pending_id = _approved_directive(db, state, night, ctid, minister, "着户部核辽饷。")
    version = int(db.conn.execute(
        "SELECT version FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["version"])
    cause = "预推用尽（受控注入）"

    def translate_fn(prompt, llm_config):
        return {
            **offline_empty_audience_translate(prompt, llm_config),
            "promises": [{"action_id": pending_id, "decision": "应允"}],
        }

    def judge(_agent, prompt, **_kwargs):
        dossier = json.loads(prompt)["dossiers"][0]
        return json.dumps({
            "verdicts": [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        })

    translates = {"n": 0}

    def segment(*_a, **_k):
        translates["n"] += 1
        if translates["n"] == 1:
            raise LLMUnavailable(cause, stage="decree_forecast")
        return {"effects": {}}

    monkeypatch.setattr(decree_mod, "run_agent_text", judge)
    monkeypatch.setattr(forecast_mod.agents, "run_agent_text", lambda *_a, **_k: "预演如此。")
    monkeypatch.setattr(month_translate, "run_declaration_translate_prompt", segment)
    sess = _sess(db, state, content, monkeypatch, translate_fn)
    result = sess.scene_chat("准这道", chat_turn_id=ctid)
    persist_and_schedule_scene(sess, db, result)
    _drain(sess)

    ref = pending_action_decree_ref(pending_id, version)
    assert db.staged_declarations.staged_for(ref) == ()
    turn = db.conn.execute(
        "SELECT post_reply_recovery, post_reply_error_pack_path FROM chat_turns WHERE id=?",
        (ctid,),
    ).fetchone()
    assert turn["post_reply_recovery"] == forecast_mod.FORECAST_RECOVERY_PHASE
    pack = Path(str(turn["post_reply_error_pack_path"] or ""))
    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["message"] == cause
    assert manifest["detail"]["failure_class"] == "model_exhausted"

    _consumer(sess).retry_interrupted_reply("殿上", ctid)
    _drain(sess)

    stored = db.staged_declarations.staged_for(ref)
    assert len(stored) == 1 and stored[0].verdict["decision"] == "promulgated"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM decree_dossiers WHERE pending_action_id=?",
        (pending_id,),
    ).fetchone()[0] == 0
    assert int(db.conn.execute(
        "SELECT id FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["id"]) == pending_id
    turn = db.conn.execute(
        "SELECT post_reply_recovery FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()
    assert turn["post_reply_recovery"] == ""


def test_unhandled_forecast_failure_stops_month_without_replay(game, monkeypatch, tmp_path):
    """夜里非 429 耗尽未点重试时，过月停在该旨，不再自动补算。"""
    from ming_sim.audience_night import close_night
    from ming_sim.exceptions import SettlementAbort
    from tests.month_chain_helpers import make_light_session

    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    db, state, content = game
    night = open_night(db, state)
    minister = _active_minister(content)
    ctid = db.create_chat_turn(
        state, "殿上", "s", 0, night_id=int(night["id"]), status="active",
    )
    uid = db.append_chat_message("殿上", int(state.turn), "user", "拟一道核实辽饷的旨。")
    db.conn.execute(
        "UPDATE chat_turns SET user_message_id=? WHERE id=?",
        (uid, ctid),
    )
    db.conn.commit()
    pending_id = _approved_directive(db, state, night, ctid, minister, "着户部核辽饷。")
    cause = "预推用尽（受控注入）"
    produces = {"n": 0}
    real_produce = forecast_mod.produce_forecast_product

    def counting(session, snapshot):
        produces["n"] += 1
        return real_produce(session, snapshot)

    def translate_fn(prompt, llm_config):
        return {
            **offline_empty_audience_translate(prompt, llm_config),
            "promises": [{"action_id": pending_id, "decision": "应允"}],
        }

    def judge(_agent, prompt, **_kwargs):
        dossier = json.loads(prompt)["dossiers"][0]
        return json.dumps({
            "verdicts": [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        })

    def segment(*_a, **_k):
        raise LLMUnavailable(cause, stage="decree_forecast")

    monkeypatch.setattr(forecast_mod, "produce_forecast_product", counting)
    monkeypatch.setattr(decree_mod, "run_agent_text", judge)
    monkeypatch.setattr(forecast_mod.agents, "run_agent_text", lambda *_a, **_k: "预演如此。")
    monkeypatch.setattr(month_translate, "run_declaration_translate_prompt", segment)
    sess = _sess(db, state, content, monkeypatch, translate_fn)
    result = sess.scene_chat("准这道", chat_turn_id=ctid)
    persist_and_schedule_scene(sess, db, result)
    _drain(sess)
    night_produces = produces["n"]
    assert night_produces >= 1

    close_night(db, state, night_id=int(night["id"]), content=content)
    turn = db.conn.execute(
        "SELECT post_reply_recovery FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()
    assert turn["post_reply_recovery"] == forecast_mod.FORECAST_RECOVERY_PHASE

    def blocked(*_a, **_k):
        produces["n"] += 1
        raise AssertionError("未点重试不得补算预推")

    monkeypatch.setattr(forecast_mod, "produce_forecast_product", blocked)
    monkeypatch.setattr("ming_sim.session.write_decree_with_agno", lambda *_a, **_k: "诏")
    month = make_light_session(db, state, content)
    month.llm_config = sess.llm_config
    with pytest.raises(SettlementAbort):
        month.resolve_turn(allow_empty_decree=True)

    assert produces["n"] == night_produces
    chain = (db.get_resolve_context(int(state.turn)) or {}).get(
        "simulator_payload", {},
    ).get("month_chain", {})
    failure = chain.get("call_failure") or {}
    assert failure.get("step") == "edict_forecast"
    assert failure.get("message") == cause
    assert failure.get("kind") == "model_exhausted"
    turn = db.conn.execute(
        "SELECT post_reply_recovery FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()
    assert turn["post_reply_recovery"] == ""


def test_late_forecast_failure_ignores_replaced_or_voided_decree(game, monkeypatch, tmp_path):
    """改版已暂存、或原旨已撤回后，迟到失败不再写回原轮相位。"""
    from ming_sim.declaration_dispatch import stage_declaration

    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    db, state, content = game
    night = open_night(db, state)
    minister = _active_minister(content)
    ctid = db.create_chat_turn(
        state, "殿上", "s", 0, night_id=int(night["id"]), status="active",
    )
    uid = db.append_chat_message("殿上", int(state.turn), "user", "拟旨。")
    mid = db.append_chat_message("殿上", int(state.turn), "minister", "臣拟旨在此。")
    db.conn.execute(
        "UPDATE chat_turns SET user_message_id=?, minister_message_id=? WHERE id=?",
        (uid, mid, ctid),
    )
    pending_id = _approved_directive(db, state, night, ctid, minister, "着户部核辽饷。")
    db.conn.execute(
        "UPDATE pending_actions SET night_approved=1, night_id=?, version=2 WHERE id=?",
        (int(night["id"]), pending_id),
    )
    db.conn.commit()
    stage_declaration(
        db, decree_ref=pending_action_decree_ref(pending_id, 2),
        declaration={"effects": {}}, turn=int(state.turn),
        verdict={"decision": "promulgated"},
    )
    sess = _sess(db, state, content, monkeypatch, lambda *_a, **_k: {})
    forecast_mod.record_forecast_failure(
        sess,
        {"pending_action_id": pending_id, "version": 1, "night_id": int(night["id"])},
        RuntimeError("迟到的旧版"),
    )
    phase = db.conn.execute(
        "SELECT post_reply_recovery FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["post_reply_recovery"]
    assert phase == ""

    db.void_pending_actions_for_chat_turn(ctid)
    forecast_mod.record_forecast_failure(
        sess,
        {"pending_action_id": pending_id, "version": 2, "night_id": int(night["id"])},
        RuntimeError("撤回后的迟到失败"),
    )
    phase = db.conn.execute(
        "SELECT post_reply_recovery FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["post_reply_recovery"]
    assert phase == ""


def test_forecast_snapshot_and_pack_failures_still_mark_phase(game, monkeypatch):
    """快照准备失败，以及写包失败，都不能让失败相位落空。"""
    db, state, content = game
    night = open_night(db, state)
    minister = _active_minister(content)
    ctid = db.create_chat_turn(
        state, "殿上", "s", 0, night_id=int(night["id"]), status="active",
    )
    uid = db.append_chat_message("殿上", int(state.turn), "user", "拟旨。")
    mid = db.append_chat_message("殿上", int(state.turn), "minister", "臣拟旨在此。")
    db.conn.execute(
        "UPDATE chat_turns SET user_message_id=?, minister_message_id=? WHERE id=?",
        (uid, mid, ctid),
    )
    pending_id = _approved_directive(db, state, night, ctid, minister, "着户部核辽饷。")
    db.conn.execute(
        "UPDATE pending_actions SET night_approved=1, night_id=? WHERE id=?",
        (int(night["id"]), pending_id),
    )
    db.conn.commit()
    sess = _sess(db, state, content, monkeypatch, lambda *a, **k: {})

    def broken_snapshot(*_a, **_k):
        raise RuntimeError("快照准备故障")

    monkeypatch.setattr(forecast_mod, "_pending_snapshot", broken_snapshot)
    assert forecast_mod.schedule_pending_decree_forecast(
        sess, pending_id, night_id=int(night["id"]),
    )
    _drain(sess)
    turn = db.conn.execute(
        "SELECT post_reply_recovery, post_reply_error_pack_path FROM chat_turns WHERE id=?",
        (ctid,),
    ).fetchone()
    assert turn["post_reply_recovery"] == forecast_mod.FORECAST_RECOVERY_PHASE
    pack = str(turn["post_reply_error_pack_path"] or "")
    manifest = json.loads((Path(pack) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["message"] == "快照准备故障"
    assert manifest["detail"]["failure_class"] == "code_exception"

    db.clear_post_reply_failure(ctid)
    monkeypatch.undo()
    monkeypatch.setattr(decree_mod, "run_agent_text", lambda *_a, **_k: (_ for _ in ()).throw(
        RuntimeError("预推代码故障"),
    ))

    def broken_pack(**_k):
        raise RuntimeError("写包故障")

    monkeypatch.setattr(
        "ming_sim.audience_night.write_audience_error_pack", broken_pack,
    )
    assert forecast_mod.schedule_pending_decree_forecast(
        sess, pending_id, night_id=int(night["id"]),
    )
    _drain(sess)
    turn = db.conn.execute(
        "SELECT post_reply_recovery, post_reply_error_pack_path FROM chat_turns WHERE id=?",
        (ctid,),
    ).fetchone()
    assert turn["post_reply_recovery"] == forecast_mod.FORECAST_RECOVERY_PHASE
    assert str(turn["post_reply_error_pack_path"] or "") == ""
