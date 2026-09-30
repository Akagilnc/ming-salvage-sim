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
from types import SimpleNamespace

import pytest

import ming_sim.decree as decree_mod
import ming_sim.decree_forecast as forecast_mod
import ming_sim.month_translate as month_translate
from ming_sim.audience_night import open_night
from ming_sim.decree_forecast import release_forecast_materials
from ming_sim.declaration_dispatch import pending_action_decree_ref
from ming_sim.exceptions import LLMUnavailable
from ming_sim.models import LLMConfig
from ming_sim.session import GameSession
from ming_sim.session_write_queue import get_session_write_queue
from tests.conftest import (
    offline_empty_audience_translate,
    persist_and_schedule_scene,
    stub_audience_translate,
    stub_scene_agent,
)
from tests.dossier_test_helpers import TYPED_COVERT_TASK


def _sess(db, state, content, monkeypatch, translate_fn):
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = LLMConfig(
        api_key="test", base_url="https://example.invalid/v1", model="test-model",
    )
    sess.temporary_characters = {}
    sess.agno_db = None
    sess._beat_generator = None
    sess._scene_registry = None
    sess._write_gate = get_session_write_queue(sess).write_gate
    stub_audience_translate(monkeypatch, translate_fn)
    stub_scene_agent(monkeypatch, SimpleNamespace(
        run=lambda _message: SimpleNamespace(content="臣领旨。", tools=[]),
    ))
    return sess


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
    assert audit and "指向不存在案卷" in audit[-1]["reason"]


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


def test_night_forecast_exhaustion_leaves_source_turn_retry_row(game, monkeypatch):
    """P2：非 429 耗尽 → 来源轮下持久失败行 + 错误包；撤掉故障原位补跑即收。"""
    db, state, content = game
    night = open_night(db, state)
    minister = _active_minister(content)
    ctid = db.create_chat_turn(
        state, "殿上", "s", 0, night_id=int(night["id"]), status="active",
    )
    db.append_chat_message("殿上", int(state.turn), "user", "拟一道核实辽饷的旨。")
    pending_id = _approved_directive(db, state, night, ctid, minister, "着户部核辽饷。")

    def translate_fn(prompt, llm_config):
        return {
            **offline_empty_audience_translate(prompt, llm_config),
            "promises": [{"action_id": pending_id, "decision": "应允"}],
        }

    calls = []

    def judge(_agent, prompt, **_kwargs):
        calls.append(1)
        dossier = json.loads(prompt)["dossiers"][0]
        assert dossier["decree_text"] == "着户部核辽饷。"
        return json.dumps({
            "verdicts": [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        })

    monkeypatch.setattr(decree_mod, "run_agent_text", judge)
    monkeypatch.setattr(forecast_mod.agents, "run_agent_text", lambda *a, **k: "预演如此。")
    monkeypatch.setattr(
        month_translate, "run_declaration_translate_prompt",
        lambda *a, **k: {"effects": {}},
    )
    sess = _sess(db, state, content, monkeypatch, translate_fn)

    boom = LLMUnavailable("预推用尽（受控注入）", stage="decree_forecast")
    real_judge = judge

    def failing_judge(_agent, prompt, **kwargs):
        calls.append(1)
        raise boom

    monkeypatch.setattr(decree_mod, "run_agent_text", failing_judge)
    result = sess.scene_chat("准这道", chat_turn_id=ctid)
    persist_and_schedule_scene(sess, db, result)
    _drain(sess)

    ref = pending_action_decree_ref(pending_id, 1)
    assert db.staged_declarations.staged_for(ref) == ()
    turn = db.conn.execute(
        "SELECT post_reply_recovery, post_reply_error_pack_path FROM chat_turns WHERE id=?",
        (ctid,),
    ).fetchone()
    # 非 429 耗尽：源轮下留持久失败相位 + 重试行。耗尽是预算事实不是代码故障，
    # 按召对既有约定不带错误包（代码异常才带，见 test_forecast_code_error_gives_error_pack）。
    assert turn["post_reply_recovery"] == forecast_mod.FORECAST_RECOVERY_PHASE
    assert str(turn["post_reply_error_pack_path"] or "") == ""

    # 撤掉故障 → 原位重试只补这一轮未成的预推，成品落一次、不重复。
    monkeypatch.setattr(decree_mod, "run_agent_text", real_judge)
    summary = forecast_mod.retry_forecast_for_turn(sess, ctid)
    assert summary == {"forecasted": 1, "pending": 0}
    stored = db.staged_declarations.staged_for(ref)
    assert len(stored) == 1 and stored[0].verdict["decision"] == "promulgated"
    turn = db.conn.execute(
        "SELECT post_reply_recovery FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()
    assert turn["post_reply_recovery"] == ""


def test_forecast_retry_never_relands_staged_decrees(game, monkeypatch):
    """已成不重落：已暂存的那一旨不在重试集合里，重试只补未成的那一旨。"""
    db, state, content = game
    night = open_night(db, state)
    minister = _active_minister(content)
    ctid = db.create_chat_turn(
        state, "殿上", "s", 0, night_id=int(night["id"]), status="active",
    )
    db.append_chat_message("殿上", int(state.turn), "user", "两道旨。")
    done_id = _approved_directive(db, state, night, ctid, minister, "已成之一。")
    todo_id = _approved_directive(db, state, night, ctid, minister, "未成之一。")
    db.conn.execute(
        "UPDATE pending_actions SET night_approved=1 WHERE id IN (?,?)",
        (done_id, todo_id),
    )
    db.conn.commit()
    db.staged_declarations.stage(
        decree_ref=pending_action_decree_ref(done_id, 1),
        declaration={"effects": {}}, turn=int(state.turn),
        verdict={"decision": "promulgated"}, forecast_text="已成",
    )
    monkeypatch.setattr(decree_mod, "run_agent_text", lambda _agent, prompt, **_k: json.dumps({
        "verdicts": [{"dossier_id": json.loads(prompt)["dossiers"][0]["id"],
                      "decision": "promulgated"}],
    }))
    monkeypatch.setattr(forecast_mod.agents, "run_agent_text", lambda *a, **k: "预演。")
    monkeypatch.setattr(
        month_translate, "run_declaration_translate_prompt", lambda *a, **k: {"effects": {}},
    )
    sess = _sess(db, state, content, monkeypatch, lambda *a, **k: {})

    summary = forecast_mod.retry_forecast_for_turn(sess, ctid)

    assert summary == {"forecasted": 1, "pending": 0}
    assert len(db.staged_declarations.staged_for(pending_action_decree_ref(done_id, 1))) == 1
    assert len(db.staged_declarations.staged_for(pending_action_decree_ref(todo_id, 1))) == 1


def test_forecast_code_error_gives_error_pack(game, monkeypatch):
    """代码异常与耗尽同形显露，且按票面要求把错误包路径交给作者。"""
    db, state, content = game
    night = open_night(db, state)
    minister = _active_minister(content)
    ctid = db.create_chat_turn(
        state, "殿上", "s", 0, night_id=int(night["id"]), status="active",
    )
    uid = db.append_chat_message("殿上", int(state.turn), "user", "拟旨。")
    mid = db.append_chat_message("殿上", int(state.turn), "minister", "臣拟旨在此。")
    # 预推由「回话已落」的转译起，失败行挂的就是这样一轮（mark_post_reply_failure 的守卫）。
    db.conn.execute(
        "UPDATE chat_turns SET user_message_id=?, minister_message_id=? WHERE id=?",
        (uid, mid, ctid),
    )
    pending_id = _approved_directive(db, state, night, ctid, minister, "着户部核辽饷。")
    db.conn.execute(
        "UPDATE pending_actions SET night_approved=1 WHERE id=?", (pending_id,),
    )
    db.conn.commit()
    sess = _bare_sess(db, state)
    snapshot = forecast_mod._pending_snapshot(sess, pending_id, int(night["id"]))
    assert snapshot is not None
    try:
        recorded = forecast_mod.record_forecast_failure(
            sess, snapshot, RuntimeError("预推代码故障（受控注入）"),
        )
        assert recorded == int(ctid)
        turn = db.conn.execute(
            "SELECT post_reply_recovery, post_reply_error_pack_path FROM chat_turns WHERE id=?",
            (ctid,),
        ).fetchone()
        assert turn["post_reply_recovery"] == forecast_mod.FORECAST_RECOVERY_PHASE
        pack = str(turn["post_reply_error_pack_path"] or "")
        assert pack and (Path(pack) / "message.txt").exists()
    finally:
        release_forecast_materials(snapshot)


def _bare_sess(db, state):
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess._write_gate = get_session_write_queue(sess).write_gate
    return sess


def test_forecast_failure_without_source_turn_is_not_faked(game, monkeypatch):
    """无来源轮的预推（留中回流等）不伪造召对失败行——没有源轮可挂，行将无处呈现。"""
    db, state, _content = game
    state.turn += 1
    db.save_state(state)
    open_night(db, state)
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="留中复拟", target_kind="issue",
        target_id="test-policy", payload={"text": "留中复拟"},
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET status='proposed', promulgation_decision='rejected', "
        "held_turn=?, rescript_pending=0 WHERE id=?",
        (int(state.turn) - 1, dossier_id),
    )
    db.conn.commit()
    sess = _bare_sess(db, state)
    snapshot = forecast_mod._held_snapshot(sess, dossier_id)
    assert snapshot is not None and "pending_action_id" not in snapshot

    recorded = forecast_mod.record_forecast_failure(
        sess, snapshot, LLMUnavailable("留中复拟用尽", stage="decree_forecast"),
    )

    assert recorded == 0
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM chat_turns WHERE post_reply_recovery != ''",
    ).fetchone()["n"] == 0
