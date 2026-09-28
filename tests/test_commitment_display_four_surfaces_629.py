"""#629 S3 / #233 P2#1 — 非-arrears 承诺进度禁「万两」；四面回归固化。

四面：
1. simulator  payload（build_simulator_payload · 待办未解进度）
2. web        issue_payloads（commitment_progress_text）
3. CLI        show_active_issues
4. minister tool 字段

对照：arrears 承诺仍可用「尚欠…万两」；loyalty/goal 门只用定性措辞。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import web_app
from ming_sim.issues import show_active_issues
from ming_sim.simulation import build_simulator_payload


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

