"""#1769 draft 成案拒收 → 结算路补交 / 耗尽留到下月。

真实入口：POST /api/directives → POST /api/decree/issue/stream。
断言 SSE 终态与 turn_directives / rejection_reports / dossier 结构化字段。

人工审读指针（验收 4，不锁 LLM 措辞）：
  - issue #1769 真实局证据：qa-1765-run3（driver.out / net-016-SSE /
    cli_trace_16204.jsonl / m-1627-10-t1-issue-error.png）
  - issue 评论链与票面冻结 t-1769-v3；回禀是否键名透传由人工核对该局。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import ming_sim.cli_backend as cb
import web_app
from ming_sim.decree import draft_directives_llm_feed
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


def _queue_backend(monkeypatch, captures: list) -> list[dict]:
    """返回每次 backend 调用的结构化 raw capture（非 prompt 文本扫描）。"""
    queue = list(captures)
    seen: list[dict] = []

    def fake_backend(prompt, *_a, **_k):
        if not queue:
            raise RuntimeError("draft_intent backend queue exhausted")
        item = queue.pop(0)
        seen.append(dict(item))
        return json.dumps(item, ensure_ascii=False), {}

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_backend)
    return seen


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


def _bearing_fields(raw: dict) -> dict:
    """承重比对：动作类型 / 金额 / 账户（及定额补饷关键字段）。"""
    return {
        "动作类型": raw.get("动作类型") or raw.get("dossier_action_type"),
        "金额": raw.get("金额") if "金额" in raw else raw.get("amount"),
        "账户": raw.get("账户") if "账户" in raw else raw.get("account"),
        "恩赏拨帑": raw.get("恩赏拨帑") if "恩赏拨帑" in raw else raw.get("grant_action"),
        "用途": raw.get("用途") if "用途" in raw else raw.get("purpose"),
        "目标类型": raw.get("目标类型") if "目标类型" in raw else raw.get("target_kind"),
        "目标ID": raw.get("目标ID") if "目标ID" in raw else raw.get("target_id"),
    }


def test_draft_admission_resubmit_success_advances_month(admission_game, monkeypatch):
    """补交路：坏产物 → 可成案 → 月推进；原始返回与投影承重一致，非偿还序偷换。"""
    game = admission_game
    seen = _queue_backend(monkeypatch, [_BAD_PAY_ORDER, _GOOD_XIEANG])
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
    # 首抽 + 补交各一次结构化 raw（不扫 prompt 自由文本）
    assert len(seen) >= 2
    assert seen[0].get("动作类型") == "pay_order_override"
    assert seen[1].get("动作类型") == "grant_allocation"
    assert seen[1].get("金额") == 15
    assert seen[1].get("账户") == "国库"

    dossier = game.db.get_dossier_for_directive(draft_id)
    assert dossier is not None
    assert dossier["action_type"] == "grant_allocation"
    projected = json.loads(dossier["payload_json"])
    # 原始第二次返回 vs 投影：承重字段一致，不得偷换成偿还序
    raw_bearing = _bearing_fields(seen[1])
    proj_bearing = _bearing_fields(projected)
    assert proj_bearing["动作类型"] == "grant_allocation"
    assert proj_bearing["动作类型"] != "pay_order_override"
    assert proj_bearing["金额"] == raw_bearing["金额"] == 15
    assert proj_bearing["账户"] == raw_bearing["账户"] == "国库"
    assert proj_bearing["恩赏拨帑"] == "协饷"
    assert proj_bearing["用途"] == "补饷"
    assert proj_bearing["目标类型"] == "army"
    assert proj_bearing["目标ID"] == "guanning"
    assert projected.get("entries") in (None, [], ())
    # 补交成功不得残留首轮拒收
    assert not _rejection_rows(game, draft_id)
    row = game.db.get_directive(draft_id)
    assert row is not None and str(row["status"]) == "issued"


def test_draft_admission_exhaust_keeps_draft_and_advances(admission_game, monkeypatch):
    """耗尽路：draft 留到下月、月推进、拒因留痕、供料含上月未入档、刷新身份一致。"""
    game = admission_game
    _queue_backend(monkeypatch, [_BAD_PAY_ORDER, _BAD_PAY_ORDER])
    client = TestClient(web_app.app)
    turn = int(game.state.turn)

    _post_directive(client, _DECREE_TEXT)
    wait_pending_writes(game)
    did = _latest_directive_id(game)
    source_turn = int(game.db.get_directive(did)["turn"])

    body = _post_issue_stream(client, expected_turn=turn, step="1769 exhaust")
    assert _turn_of(_get_state(client)) == turn + 1
    row = game.db.get_directive(did)
    assert row is not None and str(row["status"]) == "draft"
    assert game.db.get_dossier_for_directive(did) is None

    rows = _rejection_rows(game, did)
    # 拒只在耗尽终态落一次，不双记首轮探测
    assert len(rows) == 1
    assert rows[0]["category"] == "locality_fanout_failed"
    assert rows[0]["source"] == "player_decree"
    # 诊断出口：拒因 reason 不进 SSE done 结构化载荷
    assert "reason" not in body or body.get("reason") in (None, "")
    assert rows[0]["reason"] not in json.dumps(body, ensure_ascii=False)

    # 下月开桌该旨仍在 + 输入侧供料含「上月未入档」（不新建通知）
    listed = game.db.list_directives(game.state, statuses=("draft",))
    assert any(int(r["id"]) == did for r in listed)
    assert source_turn < int(game.state.turn)
    feed = draft_directives_llm_feed(listed, current_turn=int(game.state.turn))
    carry = next(
        item for item, r in zip(feed, listed) if int(r["id"]) == did
    )
    assert carry.get("admission_status") == "上月未入档"

    # 刷新/恢复：同库重开身份一致、无重复案卷效果
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
        # 恢复后供料仍含上月未入档
        r_listed = restored.db.list_directives(restored.state, statuses=("draft",))
        r_feed = draft_directives_llm_feed(
            r_listed, current_turn=int(restored.state.turn),
        )
        r_carry = next(
            item for item, r in zip(r_feed, r_listed) if int(r["id"]) == did
        )
        assert r_carry.get("admission_status") == "上月未入档"
    finally:
        try:
            restored.session.close()
        except Exception:
            pass


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
    assert str(game.db.get_directive(good_id)["status"]) == "issued"
    assert game.db.get_dossier_for_directive(bad_id) is None
    assert str(game.db.get_directive(bad_id)["status"]) == "draft"
    assert len(_rejection_rows(game, bad_id)) == 1
    assert not _rejection_rows(game, good_id)


def test_draft_admission_code_fault_aborts_with_error_pack(admission_game, monkeypatch):
    """真代码故障（ensure）：SSE error + 错误包目录存在 + 月份不推进。"""
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
        raise RuntimeError("simulated ensure code fault #1769")

    monkeypatch.setattr(cb, "resubmit_draft_admission_payload", boom)
    body = _post_issue_stream(
        client, expected_turn=turn, step="1769 resubmit-code-fault",
        allow_error=True,
    )
    assert body.get("_event") == "error"
    assert int(game.state.turn) == turn
    pack = latest_error_pack_for_turn(game.db.path, turn)
    assert pack, "须出错误包"
    assert Path(pack).is_dir()
