"""#629 S3 / #233 P2#1 — 非-arrears 承诺进度禁「万两」；四面回归固化。

四面：
1. simulator  payload（build_simulator_payload · 待办未解进度）
2. extractor  payload（_extractor_context_payload · 待办未解进度）
3. web        issue_payloads（commitment_progress_text）
4. CLI        show_active_issues + minister tool 字段

对照：arrears 承诺仍可用「尚欠…万两」；loyalty/goal 门只用定性措辞。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import web_app
from ming_sim.issues import show_active_issues
from ming_sim.simulation import _extractor_context_payload, build_simulator_payload
from ming_sim.tools import _commitment_tool_fields


def _drop_active(db):
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.commit()


def _insert_loyalty_commitment(db, state, *, title: str = "安抚毛文龙·四面回归") -> int:
    return int(db.insert_issue(
        state,
        kind="initiative",
        title=title,
        origin_kind="decree",
        origin_ref="decree:turn-1:loyalty-629",
        bar_value=0,
        inertia=0,
        stage_text="遣臣持诏赴皮岛",
        ongoing_effects={"metrics": {"皇威": 1}},
        stop_condition=json.dumps(
            {"character.毛文龙.loyalty": ">=65"}, ensure_ascii=False,
        ),
        commitment_kind="until_stop",
    ))


def _insert_arrears_commitment(db, state, *, title: str = "关宁补饷·四面对照") -> int:
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    db.conn.execute("UPDATE armies SET arrears=80 WHERE id='guanning'")
    db.conn.commit()
    return int(db.insert_issue(
        state,
        kind="initiative",
        title=title,
        origin_kind="decree",
        origin_ref="decree:turn-1:arrears-629",
        bar_value=0,
        inertia=0,
        stage_text="每月拨银补关宁旧欠",
        ongoing_effects={
            "economy": [
                {"account": "国库", "delta": -10, "reason": "补饷", "purpose": "补饷"}
            ]
        },
        stop_condition=json.dumps(
            {"army.guanning.arrears": "<=0"}, ensure_ascii=False,
        ),
        commitment_kind="until_stop",
    ))


def _web_issue_payloads(db, state):
    rt = object.__new__(web_app.WebGame)
    rt.session = SimpleNamespace(db=db, state=state)
    return web_app.WebGame.issue_payloads(rt)


def _issue_row(db, issue_id: int):
    row = db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert row is not None
    return row


def test_loyalty_commitment_no_wanliang_on_four_surfaces(game, capsys):
    """非-arrears（loyalty gate）四面皆定性措辞，零「万两」。"""
    db, state, _content = game
    _drop_active(db)
    issue_id = _insert_loyalty_commitment(db, state)

    # 1) simulator
    sim = next(
        i for i in build_simulator_payload(state, db, "", "")["active_issues"]
        if i["issue_id"] == issue_id
    )
    sim_text = str(sim.get("待办未解进度") or "")
    assert "直到达标" in sim_text
    assert "万两" not in sim_text
    assert "remaining_arrears" not in (sim.get("commitment_progress") or {})
    # simulator 投影后 remaining_to_goal 为定性
    assert sim["commitment_progress"]["remaining_to_goal"] == "距达标仍有差距"

    # 2) extractor（机面可保留 remaining_to_goal 数值键，但显示串仍禁万两）
    ext = next(
        i for i in _extractor_context_payload(db, state, "", "")["active_issues"]
        if i["issue_id"] == issue_id
    )
    ext_text = str(ext.get("待办未解进度") or "")
    assert "直到达标" in ext_text
    assert "万两" not in ext_text
    assert "remaining_to_goal" in (ext.get("commitment_progress") or {})
    assert "remaining_arrears" not in (ext.get("commitment_progress") or {})

    # 3) web
    web_item = next(p for p in _web_issue_payloads(db, state) if p["id"] == issue_id)
    web_text = str(web_item.get("commitment_progress_text") or "")
    assert "直到达标" in web_text
    assert "万两" not in web_text
    # 非-arrears bar 不得被 arrears bar 算法改写为伪银两进度
    assert web_item.get("commitment_progress", {}).get("remaining_arrears") is None

    # 4) CLI show_active_issues + minister tool 字段
    show_active_issues(db)
    cli_out = capsys.readouterr().out
    # 定位本条标题附近不得含万两
    assert "安抚毛文龙·四面回归" in cli_out
    block = cli_out.split("安抚毛文龙·四面回归", 1)[1].split("[玩家", 1)[0]
    assert "万两" not in block
    assert "直到达标" in block or "已履行" in block

    tool_blob = _commitment_tool_fields(db, state, _issue_row(db, issue_id))
    assert "万两" not in tool_blob
    assert "直到达标" in tool_blob or "已履行" in tool_blob


def test_arrears_commitment_keeps_wanliang_on_four_surfaces(game, capsys):
    """对照：arrears 承诺四面仍可出现「尚欠…万两」。"""
    db, state, _content = game
    _drop_active(db)
    issue_id = _insert_arrears_commitment(db, state)

    sim = next(
        i for i in build_simulator_payload(state, db, "", "")["active_issues"]
        if i["issue_id"] == issue_id
    )
    assert "万两" in str(sim.get("待办未解进度") or "")
    assert "尚欠" in str(sim.get("待办未解进度") or "")

    ext = next(
        i for i in _extractor_context_payload(db, state, "", "")["active_issues"]
        if i["issue_id"] == issue_id
    )
    assert "万两" in str(ext.get("待办未解进度") or "")

    web_item = next(p for p in _web_issue_payloads(db, state) if p["id"] == issue_id)
    assert "万两" in str(web_item.get("commitment_progress_text") or "")

    show_active_issues(db)
    cli_out = capsys.readouterr().out
    assert "关宁补饷·四面对照" in cli_out
    block = cli_out.split("关宁补饷·四面对照", 1)[1].split("[玩家", 1)[0]
    assert "万两" in block

    tool_blob = _commitment_tool_fields(db, state, _issue_row(db, issue_id))
    assert "万两" in tool_blob
