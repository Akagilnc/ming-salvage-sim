"""#1769 draft 成案拒收 → 结算路补交 / 耗尽留到下月。

真实入口：POST /api/directives → POST /api/decree/issue/stream；
下月供料经 session.write_decree → write_decree_with_agno 真实投影。
断言 SSE 终态与 turn_directives / rejection_reports / dossier 结构化字段。

本文件只断言结构化事实（供料入参 / 案卷字段 / DB 终态 / 错误包 manifest），
不扫 LLM 自由文本——回禀措辞由 LLM 自己长（P7 / ADR 0142）。

人工审读指针（验收 2 与 4，不锁 LLM 措辞）：
  - issue #1769 真实局证据：qa-1765-run3（driver.out / net-016-SSE /
    cli_trace_16204.jsonl / m-1627-10-t1-issue-error.png）；真实局 #3 为跨月留存局。
  - 验收 4：回禀是否把 override 键名/键族语法透传给皇帝，由人工核对该局。
  - 验收 2 的「下次召对大臣可就此追问」：本文件只证供料到位（召对组装输入含原旨
    与「尚未入档」事实）；大臣实际怎么开口追问，人工对着上述真实局与
    docs/AUDIENCE_NORTH_STAR.md 审读。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import ming_sim.cli_backend as cb
import ming_sim.decree as decree_mod
import ming_sim.session as session_mod
import web_app
from ming_sim.decree import write_decree_with_agno as _real_write_decree_with_agno
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

# 产键证据同形（真实局 cli_trace_16204）
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


# 名册产物错同形：结构合法但点名朝中查无此人 → heal 耗尽 → UnknownParticipantEscalate
_UNKNOWN_NAME = "张三丰"
_BAD_UNKNOWN_PARTICIPANT = {
    **_GOOD_XIEANG,
    "参与人": [
        {"character_id": _UNKNOWN_NAME, "tier": "协办", "role": "转运",
         "delegator_id": None},
    ],
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


def _queue_backend(monkeypatch, captures: list) -> None:
    """模型边界供料：按序返回，队尾之后一直重复最后一条。

    队列枯竭**不得**抛异常——那是测试自造的替代故障，会顶替被测的真故障
    （错误包/中止案由此在宽吞变异下仍误绿）。供料永不断，故障只能来自被测对象。
    """
    queue = list(captures)
    assert queue, "模型供料不得为空"

    def fake_backend(prompt, *_a, **_k):
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        return json.dumps(item, ensure_ascii=False), {}

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_backend)


def _spy_resubmit_kwargs(monkeypatch) -> list[dict]:
    """截获补交结构化入参（failure_reason / bad_payload），不扫 prompt 文本。"""
    calls: list[dict] = []
    real = cb.resubmit_draft_admission_payload

    def wrapper(decree_text, *, bad_payload, failure_reason, **kwargs):
        calls.append({
            "failure_reason": str(failure_reason or ""),
            "bad_payload": dict(bad_payload or {}),
            "decree_text": str(decree_text or ""),
        })
        return real(
            decree_text,
            bad_payload=bad_payload,
            failure_reason=failure_reason,
            **kwargs,
        )

    monkeypatch.setattr(cb, "resubmit_draft_admission_payload", wrapper)
    return calls


_ENSURE_FAULT_MARK = "simulated ensure code fault #1769"
_RESUBMIT_FAULT_MARK = "simulated resubmit code fault #1769"


def _assert_error_pack_from(game, turn: int, marker: str) -> None:
    """错误包须来自被测的真故障本身——不认「有个包就行」。"""
    pack = latest_error_pack_for_turn(game.db.path, turn)
    assert pack, "须出错误包"
    assert Path(pack).is_dir()
    manifest = json.loads(
        (Path(pack) / "manifest.json").read_text(encoding="utf-8"),
    )
    assert manifest["exception_type"] == "RuntimeError"
    assert manifest["exception_message"] == marker
    assert marker in (Path(pack) / "traceback.txt").read_text(encoding="utf-8")


def _post_directive(client, text: str) -> None:
    resp = client.post("/api/directives", json={"text": text, "notes": ""})
    assert resp.status_code == 200, resp.text


def _latest_directive_id(game) -> int:
    row = game.db.get_directive(
        int(game.db.conn.execute(
            "SELECT id FROM turn_directives ORDER BY id DESC LIMIT 1"
        ).fetchone()["id"])
    )
    assert row is not None
    return int(row["id"])


def _rejection_rows(game, directive_id: int):
    return game.db.conn.execute(
        "SELECT reason, category, source, turn FROM rejection_reports "
        "WHERE section = 'directive_locality' "
        "AND json_extract(item_json, '$.directive_id') = ?",
        (directive_id,),
    ).fetchall()


def _write_decree_capture_payloads(monkeypatch, game) -> list[dict]:
    """恢复真实 write_decree_with_agno；截 agent.run 入参 JSON（拟诏真实入口）。"""
    captured: list[dict] = []

    class _CapturingAgent:
        def run(self, text):
            captured.append(json.loads(text) if isinstance(text, str) else dict(text))
            return type("RunOut", (), {"content": "奉天承运，诏曰：着户部清核辽饷。"})()

    monkeypatch.setattr(session_mod, "write_decree_with_agno", _real_write_decree_with_agno)
    monkeypatch.setattr(
        decree_mod, "create_decree_writer_agent",
        lambda *a, **k: _CapturingAgent(),
    )
    game.session.write_decree()
    return captured


def test_draft_admission_resubmit_success_advances_month(admission_game, monkeypatch):
    """补交路：原抽坏 → 第一次重写仍坏 → 第二次重写成案 → 月推进。

    投影承重=第二次重写模型返回，非偿还序偷换。总计 3（原抽+重写2）。
    """
    game = admission_game
    # 原抽 + 重写1 仍坏；重写2 才成案（owner：总计 3）
    _queue_backend(monkeypatch, [_BAD_PAY_ORDER, _BAD_PAY_ORDER, _GOOD_XIEANG])
    resubmit_calls = _spy_resubmit_kwargs(monkeypatch)
    client = TestClient(web_app.app)
    turn = int(game.state.turn)

    _post_directive(client, _DECREE_TEXT)
    wait_pending_writes(game)
    draft_id = _latest_directive_id(game)
    first_row = game.db.get_directive(draft_id)
    first = game.db.read_directive_dossier_payload(first_row)
    assert first.get("dossier_action_type") == "pay_order_override"
    assert any(
        isinstance(e, dict) and e.get("key") == "arrears_priority_军饷"
        for e in (first.get("entries") or [])
    )

    _post_issue_stream(client, expected_turn=turn, step="1769 resubmit")
    assert _turn_of(_get_state(client)) == turn + 1

    # 两次 LLM 重写；入参含失败事实 + 原产物（结构化字段，不扫 prompt）
    assert len(resubmit_calls) == 2
    assert resubmit_calls[0]["failure_reason"]
    assert resubmit_calls[0]["bad_payload"].get("dossier_action_type") == "pay_order_override"
    assert any(
        isinstance(e, dict) and e.get("key") == "arrears_priority_军饷"
        for e in (resubmit_calls[0]["bad_payload"].get("entries") or [])
    )
    assert resubmit_calls[0]["decree_text"] == _DECREE_TEXT
    assert resubmit_calls[1]["failure_reason"]
    assert resubmit_calls[1]["decree_text"] == _DECREE_TEXT

    dossier = game.db.get_dossier_for_directive(draft_id)
    assert dossier is not None
    assert dossier["action_type"] == "grant_allocation"
    projected = json.loads(dossier["payload_json"])
    # 第二次重写返回（模型边界 _GOOD_XIEANG）vs 投影承重
    assert projected.get("grant_action") == _GOOD_XIEANG["恩赏拨帑"] == "协饷"
    assert projected.get("amount") == _GOOD_XIEANG["金额"] == 15
    assert projected.get("account") == _GOOD_XIEANG["账户"] == "国库"
    assert projected.get("purpose") == _GOOD_XIEANG["用途"]
    assert projected.get("target_kind") == "army"
    assert projected.get("target_id") == "guanning"
    assert projected.get("dossier_action_type", dossier["action_type"]) != "pay_order_override"
    assert projected.get("entries") in (None, [], ())
    # 颁布格等既有承重载荷字段同样按第二次重写返回投影，不得在补交路上漂移
    assert projected.get("mode") == _GOOD_XIEANG["颁布方式"] == "ordinary"
    assert dossier["executor_id"] == _GOOD_XIEANG["承办人"] == "郭允厚"
    assert not _rejection_rows(game, draft_id)
    row = game.db.get_directive(draft_id)
    assert row is not None and str(row["status"]) == "issued"


def test_draft_admission_exhaust_keeps_draft_and_advances(admission_game, monkeypatch):
    """耗尽路：原抽+重写2 共 3 次仍坏 → draft 留到下月、月推进、拒因留痕。"""
    game = admission_game
    # 原抽 + 两次重写皆坏（总计 3）；变异把重写预算改回 1 时本案须红（calls==2）
    _queue_backend(monkeypatch, [_BAD_PAY_ORDER, _BAD_PAY_ORDER, _BAD_PAY_ORDER])
    resubmit_calls = _spy_resubmit_kwargs(monkeypatch)
    client = TestClient(web_app.app)
    turn = int(game.state.turn)

    _post_directive(client, _DECREE_TEXT)
    wait_pending_writes(game)
    did = _latest_directive_id(game)
    source_turn = int(game.db.get_directive(did)["turn"])

    body = _post_issue_stream(client, expected_turn=turn, step="1769 exhaust")
    assert _turn_of(_get_state(client)) == turn + 1
    assert len(resubmit_calls) == 2
    row = game.db.get_directive(did)
    assert row is not None and str(row["status"]) == "draft"
    assert game.db.get_dossier_for_directive(did) is None

    rows = _rejection_rows(game, did)
    assert len(rows) == 1
    assert rows[0]["category"] == "locality_fanout_failed"
    assert rows[0]["source"] == "player_decree"
    # 诊断出口：SSE done 结构化载荷无 reason 字段（不扫自由文本）
    assert body.get("reason") in (None, "")
    assert body.get("_event") in (None, "done", "")

    listed = game.db.list_directives(game.state, statuses=("draft",))
    assert any(int(r["id"]) == did for r in listed)
    assert source_turn < int(game.state.turn)

    # 下月召对真实供料（验收 2「下次召对大臣可就此追问」，复用 A 路、无新通知）：
    # 大臣本月奏对的组装输入里带该旨原文与「尚未入档」事实，回禀措辞由 LLM 自己长。
    minister = next(
        c for c in game.session.content.characters.values()
        if c.office_type not in ("后宫",)
    )
    audience_input = game.session._audience_prompt_for_message("卿有何事？", minister)
    assert str(row["text"] or "") in audience_input
    assert str(did) in audience_input
    # 本月新拟、尚未跨月的草案不得因此漏进召对输入（密事边界不变）
    fresh = int(game.db.add_directive(
        game.state, None, "着兵部查点京营。", "player-decree-test",
        dossier_payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "jingying-check", "locality_scope": "none",
        },
    ))
    assert "着兵部查点京营。" not in game.session._audience_prompt_for_message(
        "卿有何事？", minister,
    )
    game.db.delete_directive(fresh)

    # 下月拟诏真实入口：write_decree → 供料含 admission_status=上月未入档
    payloads = _write_decree_capture_payloads(monkeypatch, game)
    assert payloads
    feed_item = next(
        d for d in payloads[0]["directives"]
        if str(d.get("text") or "") == str(row["text"] or "")
    )
    assert feed_item.get("admission_status") == "上月未入档"

    # 刷新/恢复：同库重开身份一致、无重复案卷
    db_path = str(game.db.path)
    game.session.close()
    restored = web_app.WebGame(fresh=False, db_path=db_path)
    try:
        monkeypatch.setattr(web_app, "web_game", restored)
        r_row = restored.db.get_directive(did)
        assert r_row is not None
        assert str(r_row["status"]) == "draft"
        assert int(r_row["id"]) == did
        assert restored.db.get_dossier_for_directive(did) is None
        assert len(_rejection_rows(restored, did)) == 1
        assert not any(
            d.get("directive_id") == did
            for d in restored.db.list_decree_dossiers()
        )
    finally:
        try:
            restored.session.close()
        except Exception:
            pass


def test_draft_admission_mixed_good_and_bad_independent(admission_game, monkeypatch):
    """混合：好旨成案、坏旨补交耗尽 → draft 留、月推进，坏旨不连带好旨。

    坏旨两次重写都点名朝中查无此人 → cli_backend 已识别的名册产物错
    （UnknownParticipantEscalate）。它是产物错，走本票 B 路预算/留存：不得升成
    整月 SettlementAbort。第二次重写须听见第一次重写自己的失败事实，
    而不是拿 DB 里的旧拒因再问一遍。
    """
    game = admission_game
    _queue_backend(monkeypatch, [
        _GOOD_XIEANG, _BAD_PAY_ORDER, _BAD_UNKNOWN_PARTICIPANT,
    ])
    resubmit_calls = _spy_resubmit_kwargs(monkeypatch)
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
    assert str(game.db.get_directive(good_id)["status"]) == "issued"
    assert game.db.get_dossier_for_directive(bad_id) is None
    assert str(game.db.get_directive(bad_id)["status"]) == "draft"
    assert len(_rejection_rows(game, bad_id)) == 1
    assert not _rejection_rows(game, good_id)
    # 名册产物错未被当成系统故障：无错误包、月已推进（上方断言）
    assert not latest_error_pack_for_turn(game.db.path, turn)
    # 首轮拒因来自原产物；第二次重写听见的是第一次重写自己的失败事实
    assert len(resubmit_calls) == 2
    assert _UNKNOWN_NAME not in resubmit_calls[0]["failure_reason"]
    assert _UNKNOWN_NAME in resubmit_calls[1]["failure_reason"]


def test_draft_admission_code_fault_aborts_with_error_pack(admission_game, monkeypatch):
    """真代码故障（ensure）：SSE error + 错误包记真故障 + 月份不推进。

    模型供料不断（枯竭不抛），故中止只能来自 boom；ensure 宽吞变异下本案必红。
    """
    game = admission_game
    _queue_backend(monkeypatch, [_GOOD_XIEANG])
    client = TestClient(web_app.app)
    turn = int(game.state.turn)

    _post_directive(client, "准从国库见银拨关宁军饷十五万两即发。")
    wait_pending_writes(game)

    def boom(*_a, **_k):
        raise RuntimeError(_ENSURE_FAULT_MARK)

    monkeypatch.setattr(game.db, "_ensure_directive_dossier", boom)
    body = _post_issue_stream(
        client, expected_turn=turn, step="1769 code-fault", allow_error=True,
    )
    assert body.get("_event") == "error"
    assert int(game.state.turn) == turn
    _assert_error_pack_from(game, turn, _ENSURE_FAULT_MARK)


def test_draft_admission_resubmit_code_fault_aborts_with_error_pack(
    admission_game, monkeypatch,
):
    """补交环真代码故障不得洗成耗尽：SSE error + 错误包 + 月不推进。"""
    game = admission_game
    _queue_backend(monkeypatch, [_BAD_PAY_ORDER])
    client = TestClient(web_app.app)
    turn = int(game.state.turn)

    _post_directive(client, _DECREE_TEXT)
    wait_pending_writes(game)

    def boom(*_a, **_k):
        raise RuntimeError(_RESUBMIT_FAULT_MARK)

    monkeypatch.setattr(cb, "resubmit_draft_admission_payload", boom)
    body = _post_issue_stream(
        client, expected_turn=turn, step="1769 resubmit-code-fault",
        allow_error=True,
    )
    assert body.get("_event") == "error"
    assert int(game.state.turn) == turn
    _assert_error_pack_from(game, turn, _RESUBMIT_FAULT_MARK)
