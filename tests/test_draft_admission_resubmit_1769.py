"""#1769 draft 成案拒收 → 结算路补交 / 耗尽留到下月。

真实入口：POST /api/directives → POST /api/decree/issue/stream。
断言 SSE 终态与 turn_directives / rejection_reports / dossier 结构化字段；
不扫描 LLM 措辞。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import ming_sim.cli_backend as cb
import web_app
from tests.test_army_pay_decree_1503 import _army_row, _set_guanning_arrears
from tests.test_month_loop_tracer_1468 import (
    _get_state,
    _parse_sse,
    _post_issue_stream,
    _stub_outer_llm_seams,
    _turn_of,
)
from tests.test_session_write_queue_1353 import wait_pending_writes


_DECREE_TEXT = (
    "命户部尚书郭允厚从国库核拨关宁军欠饷十五万两，"
    "解赴宁远军前，十日内奏报实发数目，不得加派于民。"
)

# 产键证据同形：分类 pay_order_override + 坏键 arrears_priority_军饷，金额 null
_BAD_PAY_ORDER_CAPTURE = {
    "拟旨意图": "拟旨",
    "动作类型": "pay_order_override",
    "entries": [{"key": "arrears_priority_军饷", "value": 1}],
    "恩赏拨帑": "无",
    "姓名": "郭允厚",
    "目标": "关宁军",
    "目标类型": "army",
    "金额": None,
    "账户": "国库",
    "用途": "补饷",
    "拨付节奏": "一次性",
    "颁布方式": "ordinary",
    "执行面": "in_transit",
    "目标候选": "宁远军前",
    "目标ID": "guanning",
    "地区ID": "",
    "施行范围": "无",
    "事务类别": "钱粮",
    "承办人": "郭允厚",
    "参与人": [],
    "期限月数": None,
    "目标案卷ID": None,
}

_GOOD_XIEANG_CAPTURE = {
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


def _install_web_game(tmp_path, monkeypatch):
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    # 必须在 stub 前抓住真 capture：_stub_outer_llm_seams 会换成 canned policy。
    real_capture = cb.capture_manual_directive_payload
    _stub_outer_llm_seams(monkeypatch)
    # 本票走真实 capture；模型边界由 _run_backend_for_config 队列喂。
    monkeypatch.setattr(cb, "capture_manual_directive_payload", real_capture)
    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", game)
    if getattr(game.session, "llm_config", None) is not None:
        try:
            game.session.llm_config.channel = "cli"
        except Exception:
            pass
    return game


def _queue_backend(monkeypatch, captures: list):
    queue = list(captures)
    prompts: list[str] = []

    def fake_backend(prompt, *_a, **_k):
        prompts.append(str(prompt or ""))
        if not queue:
            raise RuntimeError("draft_intent backend queue exhausted")
        return json.dumps(queue.pop(0), ensure_ascii=False), {}

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_backend)
    return prompts


def _post_issue_stream_allow_error(client: TestClient, *, expected_turn: int) -> tuple[str, dict]:
    """与 _post_issue_stream 同入口；允许 error 终态（真代码故障钉）。"""
    resp = client.post(
        "/api/decree/issue/stream",
        json={"expected_turn": expected_turn},
    )
    assert resp.status_code == 200, resp.text
    events = _parse_sse(resp.text)
    assert events, resp.text
    terminal = events[-1]
    raw = terminal.get("data") or "{}"
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        data = {"message": raw}
    if not isinstance(data, dict):
        data = {"message": str(data)}
    return str(terminal.get("event") or ""), data


def test_draft_admission_resubmit_success_advances_month(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
):
    """补交路：坏产物 → 补交输入含失败事实与原产物 → 可成案 → 月份推进。

    对比原始返回与投影：重写不得把定额补饷偷换成偿还序调整（P1）。
    """
    game = _install_web_game(tmp_path, monkeypatch)
    prompts = _queue_backend(monkeypatch, [_BAD_PAY_ORDER_CAPTURE, _GOOD_XIEANG_CAPTURE])
    client = TestClient(web_app.app)
    try:
        turn = int(game.state.turn)
        _set_guanning_arrears(game.db, 60, central=60, province=0)
        game.state.metrics["国库"] = max(int(game.state.metrics.get("国库") or 0), 100)

        posted = client.post("/api/directives", json={"text": _DECREE_TEXT, "notes": ""})
        assert posted.status_code == 200, posted.text
        wait_pending_writes(game)

        draft = game.db.conn.execute(
            "SELECT id, status, dossier_payload_json FROM turn_directives "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert draft is not None
        first_payload = json.loads(str(draft["dossier_payload_json"] or "{}"))
        # 原始返回投影：坏分类 + 坏键进了 draft（ensure 前）
        assert first_payload.get("dossier_action_type") == "pay_order_override"
        assert any(
            (e or {}).get("key") == "arrears_priority_军饷"
            for e in (first_payload.get("entries") or [])
            if isinstance(e, dict)
        )

        body = _post_issue_stream(client, expected_turn=turn, step="1769 resubmit success")
        after = _get_state(client)
        assert _turn_of(after) == turn + 1, after.get("turn")

        # 补交 prompt 含失败事实与原产物（结构化键，不锁 LLM 自由措辞）
        assert len(prompts) >= 2
        resubmit_prompt = prompts[1]
        assert "arrears_priority_军饷" in resubmit_prompt
        assert "pay_order_override" in resubmit_prompt

        dossier = game.db.get_dossier_for_directive(int(draft["id"]))
        assert dossier is not None
        projected = json.loads(dossier["payload_json"])
        # 承重：定额补饷 grant_allocation，不是偿还序 pay_order_override（P1）
        assert dossier["action_type"] == "grant_allocation"
        assert projected.get("grant_action") == "协饷"
        assert projected.get("amount") == 15
        assert projected.get("account") == "国库"
        assert projected.get("purpose") == "补饷"
        assert projected.get("target_kind") == "army"
        assert projected.get("target_id") == "guanning"
        status = game.db.conn.execute(
            "SELECT status FROM turn_directives WHERE id=?", (int(draft["id"]),),
        ).fetchone()["status"]
        assert status == "issued"
    finally:
        try:
            game.session.close()
        except Exception:
            pass


def test_draft_admission_exhaust_keeps_draft_and_advances(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
):
    """耗尽路：该旨保持 draft、月份照常推进；拒因留痕；不误报无草案。"""
    game = _install_web_game(tmp_path, monkeypatch)
    # 首抽坏 + 补交仍坏
    _queue_backend(monkeypatch, [_BAD_PAY_ORDER_CAPTURE, _BAD_PAY_ORDER_CAPTURE])
    client = TestClient(web_app.app)
    try:
        turn = int(game.state.turn)
        _set_guanning_arrears(game.db, 60, central=60, province=0)
        game.state.metrics["国库"] = max(int(game.state.metrics.get("国库") or 0), 100)

        posted = client.post("/api/directives", json={"text": _DECREE_TEXT, "notes": ""})
        assert posted.status_code == 200, posted.text
        wait_pending_writes(game)
        directive_id = int(game.db.conn.execute(
            "SELECT id FROM turn_directives ORDER BY id DESC LIMIT 1"
        ).fetchone()["id"])

        body = _post_issue_stream(client, expected_turn=turn, step="1769 exhaust")
        after = _get_state(client)
        assert _turn_of(after) == turn + 1, after.get("turn")

        row = game.db.conn.execute(
            "SELECT status, turn FROM turn_directives WHERE id=?", (directive_id,),
        ).fetchone()
        assert row["status"] == "draft"
        assert game.db.get_dossier_for_directive(directive_id) is None

        rejection_rows = game.db.conn.execute(
            "SELECT reason, category, source FROM rejection_reports "
            "WHERE section = 'directive_locality' "
            "AND json_extract(item_json, '$.directive_id') = ?",
            (directive_id,),
        ).fetchall()
        assert rejection_rows, "真实拒因须留痕"
        assert any(r["category"] == "locality_fanout_failed" for r in rejection_rows)
        assert any(r["source"] == "player_decree" for r in rejection_rows)

        # 下月开桌该旨仍在（跨月 draft 列表）
        listed = game.db.list_directives(game.state, statuses=("draft",))
        assert any(int(r["id"]) == directive_id for r in listed)

        # 确定性诊断出口：SSE done，不得把 override 键名/键族语法透传给皇帝
        blob = json.dumps(body, ensure_ascii=False)
        assert "arrears_priority_" not in blob
        assert "override 键" not in blob
    finally:
        try:
            game.session.close()
        except Exception:
            pass


def test_draft_admission_mixed_good_and_bad_independent(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
):
    """混合好坏旨互不牵连：好旨成案、坏旨 draft 留到下月、月份推进。"""
    game = _install_web_game(tmp_path, monkeypatch)
    # ① 好旨 capture  ② 坏旨 capture  ③ 坏旨补交仍坏
    _queue_backend(monkeypatch, [
        _GOOD_XIEANG_CAPTURE,
        _BAD_PAY_ORDER_CAPTURE,
        _BAD_PAY_ORDER_CAPTURE,
    ])
    client = TestClient(web_app.app)
    try:
        turn = int(game.state.turn)
        _set_guanning_arrears(game.db, 60, central=60, province=0)
        game.state.metrics["国库"] = max(int(game.state.metrics.get("国库") or 0), 100)

        good = client.post(
            "/api/directives",
            json={"text": "准从国库见银拨关宁军饷十五万两即发。", "notes": ""},
        )
        assert good.status_code == 200, good.text
        wait_pending_writes(game)
        good_id = int(game.db.conn.execute(
            "SELECT id FROM turn_directives ORDER BY id DESC LIMIT 1"
        ).fetchone()["id"])

        bad = client.post("/api/directives", json={"text": _DECREE_TEXT, "notes": ""})
        assert bad.status_code == 200, bad.text
        wait_pending_writes(game)
        bad_id = int(game.db.conn.execute(
            "SELECT id FROM turn_directives ORDER BY id DESC LIMIT 1"
        ).fetchone()["id"])
        assert bad_id != good_id

        _post_issue_stream(client, expected_turn=turn, step="1769 mixed")
        after = _get_state(client)
        assert _turn_of(after) == turn + 1

        assert game.db.get_dossier_for_directive(good_id) is not None
        good_status = game.db.conn.execute(
            "SELECT status FROM turn_directives WHERE id=?", (good_id,),
        ).fetchone()["status"]
        assert good_status == "issued"

        assert game.db.get_dossier_for_directive(bad_id) is None
        bad_status = game.db.conn.execute(
            "SELECT status FROM turn_directives WHERE id=?", (bad_id,),
        ).fetchone()["status"]
        assert bad_status == "draft"
    finally:
        try:
            game.session.close()
        except Exception:
            pass


def test_draft_admission_code_fault_aborts_with_error_pack(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
):
    """真代码故障（非产物错）仍响亮中止出错误包；月份不推进。"""
    game = _install_web_game(tmp_path, monkeypatch)
    _queue_backend(monkeypatch, [_GOOD_XIEANG_CAPTURE])
    client = TestClient(web_app.app)
    try:
        turn = int(game.state.turn)
        _set_guanning_arrears(game.db, 60, central=60, province=0)
        game.state.metrics["国库"] = max(int(game.state.metrics.get("国库") or 0), 100)

        posted = client.post(
            "/api/directives",
            json={"text": "准从国库见银拨关宁军饷十五万两即发。", "notes": ""},
        )
        assert posted.status_code == 200, posted.text
        wait_pending_writes(game)

        real_ensure = game.db._ensure_directive_dossier

        def boom(*_a, **_k):
            raise RuntimeError("simulated ensure code fault #1769")

        monkeypatch.setattr(game.db, "_ensure_directive_dossier", boom)

        ev, data = _post_issue_stream_allow_error(client, expected_turn=turn)
        assert ev == "error", data
        message = str(data.get("message") or data)
        assert "错误包" in message or "error_pack" in message.lower() or "结算失败" in message
        assert int(game.state.turn) == turn

        # 恢复 ensure 以免 teardown 再炸
        monkeypatch.setattr(game.db, "_ensure_directive_dossier", real_ensure)
    finally:
        try:
            game.session.close()
        except Exception:
            pass


def test_pay_order_grounding_lists_arrears_subjects():
    """输入侧结构契约：欠科目词表进提示（ADR0143/P6）。"""
    from ming_sim.pay_order import ARREARS_SUBJECTS

    facts = cb._pay_order_grounding_facts(None, db=None)
    for subject in ARREARS_SUBJECTS:
        assert subject in facts
