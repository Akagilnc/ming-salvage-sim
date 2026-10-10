"""#1769 draft 成案拒收 → 结算路补交 / 耗尽留到下月。

真实入口：草稿落桌（#1849 后走现行 capture 核 + session.add_directive；
独立手拟新增 Web 口已退役）→ POST /api/decree/issue/stream；
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
from ming_sim.entities.issue.store import IssueStore
from tests.army_pay_helpers import _set_guanning_arrears
from tests.test_month_loop_tracer_1468 import _get_state, _stub_outer_llm_seams, _turn_of


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


def _spy_resubmit_kwargs(monkeypatch) -> tuple[list[dict], list[str]]:
    """截获补交结构化入参与本轮产物失败事实（failure_reason 源），不扫 prompt。

    返回 (calls, product_faults)：
    - calls[i]["failure_reason"] = 实际回喂给 LLM 的诊断
    - product_faults = 各次 resubmit 自身抛出的 ValueError 原文（carry_over 源）
    来源保真：下一轮 failure_reason 必须等于对应 product_fault，不得只验非空/次数。
    """
    calls: list[dict] = []
    product_faults: list[str] = []
    real = cb.resubmit_draft_admission_payload

    def wrapper(decree_text, *, bad_payload, failure_reason, **kwargs):
        calls.append({
            "failure_reason": str(failure_reason or ""),
            "bad_payload": dict(bad_payload or {}),
            "decree_text": str(decree_text or ""),
        })
        try:
            return real(
                decree_text,
                bad_payload=bad_payload,
                failure_reason=failure_reason,
                **kwargs,
            )
        except ValueError as exc:
            product_faults.append(str(exc))
            raise

    monkeypatch.setattr(cb, "resubmit_draft_admission_payload", wrapper)
    return calls, product_faults


def _spy_ensure_rejection_reasons(monkeypatch, game) -> list[list[tuple[int, str]]]:
    """按轮截获 ensure_dossiers 拒因（directive_id, reason），作回喂源真值。"""
    rounds: list[list[tuple[int, str]]] = []
    real = game.db.ensure_dossiers_for_draft_directives

    def wrapper(state, record_rejections=False):
        result = real(state, record_rejections=record_rejections)
        rounds.append([
            (int(item["directive_id"]), str(item.get("reason") or ""))
            for item in (result or [])
            if item.get("directive_id") is not None
        ])
        return result

    monkeypatch.setattr(game.db, "ensure_dossiers_for_draft_directives", wrapper)
    return rounds


def _reason_for_directive(
    round_rows: list[tuple[int, str]], directive_id: int,
) -> str:
    matched = [reason for did, reason in round_rows if did == int(directive_id)]
    assert matched, f"ensure 轮次无 directive#{directive_id} 拒因"
    return matched[0]


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


def _finish_month_after_gazette(game, turn: int) -> None:
    """ADR 0157：写成邸报后主链才推进。作者替身已写成时不再推进第二次。"""
    if int(game.state.turn) > int(turn):
        assert int(game.state.turn) == int(turn) + 1
        return
    game.db.conn.execute(
        "INSERT INTO turn_reports (turn, year, period, report) VALUES (?, ?, ?, ?)",
        (int(turn), int(game.state.year), int(game.state.period), "邸报已成"),
    )
    game.db.conn.commit()
    from ming_sim.month_chain import run_player_month_chain
    result = run_player_month_chain(
        game.state, game.db, game.session.agno_db, game.session.llm_config,
    )
    assert result.advanced is True
    assert int(game.state.turn) == int(turn) + 1


def _post_directive(game, text: str) -> int:
    """#1849：独立手拟新增 Web 口已退役；经现行 capture 核 + session 落草案。

    与召对拟旨同一条 turn_directives 写入、同一拟旨抽取核，故下游成案准入断言
    仍验的是真实落桌产物。
    """
    from tests.directive_seed_helpers import seed_manual_draft

    return seed_manual_draft(game.session, text)


def _latest_directive_id(game) -> int:
    row = IssueStore(game.db.conn).directive(int(game.db.conn.execute(
        "SELECT id FROM turn_directives ORDER BY id DESC LIMIT 1"
    ).fetchone()["id"]))
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












# ── 线上材料庭 r1 三类负向 / pending / 零成案耗尽 ──────────────────────────


_NO_INTENT_REWRITE = {
    # 缺「拟旨意图」或垃圾 → extract 映 draft_action=无 → project 曾落 special_decree
    # fallback；结算路 B 不得 replace_payload 毁掉原 pay_order。
    "动作类型": "special_decree",
    "目标类型": "policy",
    "目标ID": "manual-directive",
}










def test_advance_without_edict_vacuum_no_decree_issued(
    admission_game, monkeypatch,
):
    """类B：POST 真空退朝成功 → 月份真推进，且本月无旨（last_decree 仍空）。"""
    game = admission_game
    turn = int(game.state.turn)
    assert not (game.session.last_decree or "").strip()
    client = TestClient(web_app.app)
    resp = client.post(
        "/api/decree/advance_without_edict",
        json={"expected_turn": turn},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("awaiting_decision") is False
    assert body.get("advanced") is True
    assert _turn_of(_get_state(client)) == turn + 1
    assert not (game.session.last_decree or "").strip()
