"""#1769 draft 成案拒收 → 结算路补交 / 耗尽留到下月。

真实入口：POST /api/directives → POST /api/decree/issue/stream。
断言 SSE 终态与 turn_directives / rejection_reports / dossier 结构化字段。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import ming_sim.cli_backend as cb
import web_app
from ming_sim.error_pack import latest_error_pack_for_turn
from tests.test_army_pay_decree_1503 import _set_guanning_arrears
from tests.test_month_loop_tracer_1468 import (
    _get_state,
    _post_issue_stream,
    _stub_outer_llm_seams,
    _turn_of,
)
from tests.test_session_write_queue_1353 import wait_pending_writes


_DECREE_TEXT = (
    "命户部尚书郭允厚从国库核拨关宁军欠饷十五万两，"
    "解赴宁远军前，十日内奏报实发数目，不得加派于民。"
)

# 产键证据同形
_BAD_PAY_ORDER = {
    "拟旨意图": "拟旨",
    "动作类型": "pay_order_override",
    "entries": [{"key": "arrears_priority_军饷", "value": 1}],
    "恩赏拨帑": "无",
    "目标": "关宁军",
    "目标类型": "army",
    "目标ID": "guanning",
    "金额": None,
    "账户": "国库",
    "用途": "补饷",
    "拨付节奏": "一次性",
    "颁布方式": "ordinary",
    "执行面": "in_transit",
    "施行范围": "无",
    "承办人": "郭允厚",
    "参与人": [],
    "期限月数": None,
    "目标案卷ID": None,
}

_GOOD_XIEANG = {
    "拟旨意图": "拟旨",
    "动作类型": "grant_allocation",
    "恩赏拨帑": "协饷",
    "用途": "补饷",
    "目标类型": "army",
    "目标": "关宁军",
    "目标ID": "guanning",
    "颁布方式": "ordinary",
    "金额": 15,
    "账户": "国库",
    "拨付节奏": "一次性",
    "执行面": "immediate",
    "承办人": "郭允厚",
    "参与人": [],
    "施行范围": "无",
    "期限月数": None,
    "目标案卷ID": None,
    "entries": [],
}


@pytest.fixture
def admission_game(tmp_path, monkeypatch, _offline_scene_beat_generator):
    """共享 WebGame + 真 capture；模型边界由各测 _queue_backend 喂。"""
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    real_capture = cb.capture_manual_directive_payload
    _stub_outer_llm_seams(monkeypatch)
    monkeypatch.setattr(cb, "capture_manual_directive_payload", real_capture)
    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", game)
    if getattr(game.session, "llm_config", None) is not None:
        try:
            game.session.llm_config.channel = "cli"
        except Exception:
            pass
    _set_guanning_arrears(game.db, 60, central=60, province=0)
    game.state.metrics["国库"] = max(int(game.state.metrics.get("国库") or 0), 100)
    try:
        yield game
    finally:
        try:
            game.session.close()
        except Exception:
            pass


def _queue_backend(monkeypatch, captures: list) -> list[str]:
    queue = list(captures)
    prompts: list[str] = []

    def fake_backend(prompt, *_a, **_k):
        prompts.append(str(prompt or ""))
        if not queue:
            raise RuntimeError("draft_intent backend queue exhausted")
        return json.dumps(queue.pop(0), ensure_ascii=False), {}

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_backend)
    return prompts


def _post_directive(client, text: str) -> None:
    resp = client.post("/api/directives", json={"text": text, "notes": ""})
    assert resp.status_code == 200, resp.text


def _latest_directive_id(game) -> int:
    return int(game.db.conn.execute(
        "SELECT id FROM turn_directives ORDER BY id DESC LIMIT 1"
    ).fetchone()["id"])


def _rejection_rows(game, directive_id: int):
    return game.db.conn.execute(
        "SELECT reason, category, source FROM rejection_reports "
        "WHERE section = 'directive_locality' "
        "AND json_extract(item_json, '$.directive_id') = ?",
        (directive_id,),
    ).fetchall()


def test_draft_admission_resubmit_success_advances_month(admission_game, monkeypatch):
    """补交路：坏产物 → 输入含失败事实与原产物 → 可成案 → 月推进；非偿还序。"""
    game = admission_game
    prompts = _queue_backend(monkeypatch, [_BAD_PAY_ORDER, _GOOD_XIEANG])
    client = TestClient(web_app.app)
    turn = int(game.state.turn)

    _post_directive(client, _DECREE_TEXT)
    wait_pending_writes(game)
    draft_id = _latest_directive_id(game)
    first = json.loads(game.db.conn.execute(
        "SELECT dossier_payload_json FROM turn_directives WHERE id=?", (draft_id,),
    ).fetchone()["dossier_payload_json"])
    assert first.get("dossier_action_type") == "pay_order_override"
    assert any(
        isinstance(e, dict) and e.get("key") == "arrears_priority_军饷"
        for e in (first.get("entries") or [])
    )

    _post_issue_stream(client, expected_turn=turn, step="1769 resubmit")
    assert _turn_of(_get_state(client)) == turn + 1
    assert len(prompts) >= 2
    # 补交输入含失败事实与原产物（结构化键，不锁自由措辞）
    assert "arrears_priority_军饷" in prompts[1]
    assert "pay_order_override" in prompts[1]

    dossier = game.db.get_dossier_for_directive(draft_id)
    assert dossier is not None
    assert dossier["action_type"] == "grant_allocation"
    projected = json.loads(dossier["payload_json"])
    assert projected.get("grant_action") == "协饷"
    assert projected.get("amount") == 15
    assert projected.get("account") == "国库"
    assert projected.get("purpose") == "补饷"
    assert projected.get("target_kind") == "army"
    assert projected.get("target_id") == "guanning"
    assert game.db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (draft_id,),
    ).fetchone()["status"] == "issued"


def test_draft_admission_exhaust_keeps_draft_and_advances(admission_game, monkeypatch):
    """耗尽路：第二次仍坏产物 → draft 留到下月、月推进、拒因留痕、诊断不透传。"""
    game = admission_game
    # 首抽坏 + 补交仍返回坏产物（真耗尽，非队列空）
    _queue_backend(monkeypatch, [_BAD_PAY_ORDER, _BAD_PAY_ORDER])
    client = TestClient(web_app.app)
    turn = int(game.state.turn)

    _post_directive(client, _DECREE_TEXT)
    wait_pending_writes(game)
    did = _latest_directive_id(game)

    body = _post_issue_stream(client, expected_turn=turn, step="1769 exhaust")
    assert _turn_of(_get_state(client)) == turn + 1
    assert game.db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (did,),
    ).fetchone()["status"] == "draft"
    assert game.db.get_dossier_for_directive(did) is None

    rows = _rejection_rows(game, did)
    assert rows
    assert any(r["category"] == "locality_fanout_failed" for r in rows)
    assert any(r["source"] == "player_decree" for r in rows)
    # 不透明：拒因 reason 原文不得出现在 SSE done 载荷
    blob = json.dumps(body, ensure_ascii=False)
    assert rows[0]["reason"] not in blob

    # 下月开桌该旨仍在
    listed = game.db.list_directives(game.state, statuses=("draft",))
    assert any(int(r["id"]) == did for r in listed)


def test_draft_admission_mixed_good_and_bad_independent(admission_game, monkeypatch):
    """混合：好旨成案、坏旨 draft 留、月推进。"""
    game = admission_game
    _queue_backend(monkeypatch, [_GOOD_XIEANG, _BAD_PAY_ORDER, _BAD_PAY_ORDER])
    client = TestClient(web_app.app)
    turn = int(game.state.turn)

    _post_directive(client, "准从国库见银拨关宁军饷十五万两即发。")
    wait_pending_writes(game)
    good_id = _latest_directive_id(game)
    _post_directive(client, _DECREE_TEXT)
    wait_pending_writes(game)
    bad_id = _latest_directive_id(game)
    assert bad_id != good_id

    _post_issue_stream(client, expected_turn=turn, step="1769 mixed")
    assert _turn_of(_get_state(client)) == turn + 1
    assert game.db.get_dossier_for_directive(good_id) is not None
    assert game.db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (good_id,),
    ).fetchone()["status"] == "issued"
    assert game.db.get_dossier_for_directive(bad_id) is None
    assert game.db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (bad_id,),
    ).fetchone()["status"] == "draft"


def test_draft_admission_code_fault_aborts_with_error_pack(admission_game, monkeypatch):
    """真代码故障：SSE error + 错误包目录存在 + 月份不推进。"""
    game = admission_game
    _queue_backend(monkeypatch, [_GOOD_XIEANG])
    client = TestClient(web_app.app)
    turn = int(game.state.turn)

    _post_directive(client, "准从国库见银拨关宁军饷十五万两即发。")
    wait_pending_writes(game)

    def boom(*_a, **_k):
        raise RuntimeError("simulated ensure code fault #1769")

    monkeypatch.setattr(game.db, "_ensure_directive_dossier", boom)
    body = _post_issue_stream(
        client, expected_turn=turn, step="1769 code-fault", allow_error=True,
    )
    assert body.get("_event") == "error"
    assert int(game.state.turn) == turn
    pack = latest_error_pack_for_turn(game.db.path, turn)
    assert pack, "须出错误包"
    assert Path(pack).is_dir()
