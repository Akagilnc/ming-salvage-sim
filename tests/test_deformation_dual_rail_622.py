"""#622 变形判定＋双口径分叉（0072 口径＋0073 读端）。

测试预算 ≤3：
① AC1+AC2（transformed/degraded 对照）端到端 tracer + AC4 溯源 + 假进度零入 apply
② AC5 稽核信号正负成对

#621 接管窗/连坐/fail-closed 既有断言不得放松（本文件不改 #621 测）。
"""

from __future__ import annotations

import json

from ming_sim.db import GameDB
from tests.dossier_test_helpers import create_test_secret_order
from ming_sim.due_review import (
    apply_pending_due_reviews,
    decide_due_review_verdict,
)
from ming_sim.issues import apply_issue_inertia_and_ongoing, apply_score_extraction
from ming_sim.staged_commitment import write_due_staged_commitment_todos
from tests.test_dossier_reported_progress_619 import _world_fingerprint


# ── shared helpers ────────────────────────────────────────────────────


def _executing_policy(db, state, *, token: str):
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"清丈差务·{token}",
        target_kind="issue",
        target_id=token,
        participants=[
            {"character_id": "倪元璐", "tier": "主办", "role": "清丈"},
            {"character_id": "徐光启", "tier": "协办", "role": "坐镇"},
        ],
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    assert db.get_decree_dossier(dossier_id)["status"] == "executing"
    return dossier_id


def _insert_final_stage(db, state, content, *, dossier_id: int, title: str):
    origin = f"dossier:{int(dossier_id)}"
    out = apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": origin,
                    "kind": "initiative",
                    "title": title,
                    "stage_text": "所约之事依限办结。",
                    "commitment_kind": "until_stop",
                    "ongoing_effects": {},
                    "stages": [{
                        "stage_idx": 0,
                        "due_turn": state.turn,
                        "criterion_text": "清丈见成数",
                        "origin_context": "清丈畿辅田亩",
                    }],
                }
            ]
        },
        content=content,
    )
    created = out["issue_summary"]["new_issues"][0]
    assert created.get("rejected") is False, created
    return int(created["issue_id"])


def _prime_and_apply_due_review(db, state, content, *, dossier_id: int, title: str):
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    _insert_final_stage(db, state, content, dossier_id=dossier_id, title=title)
    write_due_staged_commitment_todos(db, state)
    db.conn.execute(
        "UPDATE next_audience_todos SET created_turn=?",
        (state.turn - 1,),
    )
    db.conn.commit()
    results = apply_pending_due_reviews(db, state, commit=True)
    assert results and results[0].get("branch") == "dossier"
    return results[0]


def _cost_liability(db, dossier_id):
    return [
        dict(row)
        for row in db.conn.execute(
            "SELECT * FROM decree_cost_events "
            "WHERE dossier_id=? AND cost_identity='连坐' AND cost_kind='liability' "
            "ORDER BY id",
            (int(dossier_id),),
        ).fetchall()
    ]




# ── ① AC1+AC2(+AC4) tracer ───────────────────────────────────────────


def test_ac1_ac2_transformed_vs_degraded_dual_rail_tracer(game, tmp_path, content):
    """同场景仅旨外标记不同 → transformed vs degraded；双口径三面；假进度零入 apply；restore 溯源。"""
    db, state, _content = game

    # ── transformed 支：实况效果带 beyond_intent + 奏报假象 ──
    xf_id = _executing_policy(db, state, token="xf-622")
    before_fp = _world_fingerprint(db)

    # 承办人先挂过程奏报（假象：报已成）
    db.record_dossier_progress(
        xf_id, state.turn, "在办", "田亩清丈已十之八九，即可全竣",
        is_terminal=False, commit=True,
    )
    # 月末 extractor 落旨外恶果（浮收翻倍样例）——同 origin 载体
    applied = apply_score_extraction(
        db, state,
        {
            "economy_moves": [{
                "account": "国库",
                "delta": 12,
                "category": "地方浮收",
                "reason": "借清丈之名额外加派入私",
                "origin_ref": f"dossier:{xf_id}",
                "beyond_intent": True,
            }],
        },
        content=content,
    )
    assert applied["economy_moves"], applied
    moves = db.list_economy_moves_for_dossier(xf_id)
    assert moves and moves[0]["beyond_intent"] is True
    assert moves[0]["origin_ref"] == f"dossier:{xf_id}"

    # 假进度奏报本身不改世界——对照 fingerprint 只允许实况 economy 那一笔
    after_real = _world_fingerprint(db)
    assert after_real != before_fp  # 实况入 apply
    # 再挂一条纯假进度，世界不得再变
    mid_fp = _world_fingerprint(db)
    db.record_dossier_progress(
        xf_id, state.turn, "已全完", "田亩尽数清丈、国库应增百万",
        is_terminal=False, commit=True,
    )
    assert _world_fingerprint(db) == mid_fp  # AC2/AC3：假进度零入 apply

    result_xf = _prime_and_apply_due_review(
        db, state, content, dossier_id=xf_id, title="变形对照·清丈",
    )
    xf_dossier = db.get_decree_dossier(xf_id)
    assert xf_dossier["execution_outcome"] == "transformed"
    assert xf_dossier["status"] == "closed"
    assert result_xf["verdict"]["outcome"] == "transformed"
    # 连坐走既有挂载点
    assert len(_cost_liability(db, xf_id)) == 1

    # 双口径三面：奏报说兑现 × 执行格记变形 × 实况效果在库
    xf_progress = db.list_dossier_progress(xf_id)
    terminal_rows = [r for r in xf_progress if r.get("is_terminal")]
    assert terminal_rows, xf_progress
    term = terminal_rows[-1]
    assert term["progress_band"] not in {
        "transformed", "degraded", "fulfilled", "failed", "executing", "变形",
    }
    assert xf_dossier["execution_outcome"] == "transformed"
    assert db.list_economy_moves_for_dossier(xf_id)
    # 机械分叉：list_dossier_progress band 面 ≠ 英文执行格原串
    bands = {r["progress_band"] for r in xf_progress}
    assert "transformed" not in bands

    # AC4：restore 后旨外效果可溯源
    backup = tmp_path / "restore-622.db"
    db.backup_to(str(backup))
    restored = GameDB(str(backup), content=content)
    try:
        r_moves = restored.list_economy_moves_for_dossier(xf_id)
        assert r_moves and r_moves[0]["beyond_intent"] is True
        assert r_moves[0]["origin_ref"] == f"dossier:{xf_id}"
        assert restored.get_decree_dossier(xf_id)["execution_outcome"] == "transformed"
    finally:
        restored.close()

    # ── degraded 对照：同场景无旨外标记、仅表报 → degraded ──
    deg_id = _executing_policy(db, state, token="deg-622")
    db.record_dossier_progress(
        deg_id, state.turn, "在办", "田亩清丈已十之八九，即可全竣",
        is_terminal=False, commit=True,
    )
    # 无 durable beyond_intent 效果——仅表报
    assert db.list_economy_moves_for_dossier(deg_id) == []

    # 单元对照：decide_due_review_verdict 仅标记不同
    base_input = {
        "mid_stage": False,
        "criterion_text": "清丈见成数",
        "origin_context": "清丈畿辅田亩",
        "progress_reports": [{"progress_band": "在办", "memorial_text": "已办十之八九"}],
        "durable_effects": [{
            "origin_ref": "dossier:0",
            "delta": 12,
            "beyond_intent": False,
        }],
    }
    # 有实况无旨外 → fulfilled（对照树完整性）
    assert decide_due_review_verdict(base_input)["outcome"] == "fulfilled"
    marked = dict(base_input)
    marked["durable_effects"] = [{
        "origin_ref": "dossier:0",
        "delta": 12,
        "beyond_intent": True,
    }]
    assert decide_due_review_verdict(marked)["outcome"] == "transformed"
    # 无实况有表报 → degraded（与 transformed 对照）
    no_effects = dict(base_input)
    no_effects["durable_effects"] = []
    assert decide_due_review_verdict(no_effects)["outcome"] == "degraded"

    result_deg = _prime_and_apply_due_review(
        db, state, content, dossier_id=deg_id, title="打折对照·清丈",
    )
    deg_dossier = db.get_decree_dossier(deg_id)
    assert deg_dossier["execution_outcome"] == "degraded"
    assert result_deg["verdict"]["outcome"] == "degraded"
    deg_progress = db.list_dossier_progress(deg_id)
    deg_term = [r for r in deg_progress if r.get("is_terminal")][-1]
    assert deg_term["progress_band"] not in {
        "degraded", "transformed", "fulfilled", "failed", "executing",
    }
    # 假进度尾部：再写奏报，世界 fingerprint 不变
    fp_before_fake = _world_fingerprint(db)
    db.record_dossier_progress(
        deg_id, state.turn + 1, "已竣", "奏称完结而库银未动",
        is_terminal=False, commit=True,
    )
    assert _world_fingerprint(db) == fp_before_fake


# ── ② AC5 稽核信号正负成对 ───────────────────────────────────────────


def test_ac5_audit_fork_signal_present_only_with_audit_link(game):
    """有稽核链 → 月报输入面确定性携带分叉信号；无链 → 键不出现。"""
    db, state, _content = game
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"]

    # 被稽核目标案卷：奏报 + 旨外实况 → 分叉
    target_id = _executing_policy(db, state, token="audit-target-622")
    db.record_dossier_progress(
        target_id, state.turn, "已竣", "清丈全完、加派如额",
        is_terminal=False, commit=True,
    )
    db.record_dossier_execution(
        target_id, "transformed", "奏报与旨外实况相左", state.turn,
        close=False, commit=True,
    )
    db.record_issue_economy_move(
        state, "国库", 5, "浮收", "借旨行私",
        origin_ref=f"dossier:{target_id}", beyond_intent=True, commit=True,
    )

    # 正：长差稽核密令 + 稽核链指向目标
    audit_order = create_test_secret_order(
        db, state, actor, "密查清丈浮收", "逐月密奏", ["稽核"], deadline_months=4,
    )
    audit_dossier = int(db.get_dossier_for_secret_order(audit_order)["id"])
    db.add_dossier_links(
        audit_dossier,
        [{"target_dossier_id": target_id, "relation_type": "稽核", "note": "密查该路清丈"}],
    )

    nudges = db.list_monthly_dossier_progress_nudges()
    audit_nudge = next(n for n in nudges if int(n["dossier_id"]) == audit_dossier)
    assert "audit_fork_signals" in audit_nudge
    signals = audit_nudge["audit_fork_signals"]
    assert signals
    hit = next(s for s in signals if int(s["target_dossier_id"]) == target_id)
    assert hit["relation_type"] == "稽核"
    assert hit["beyond_intent"] is True
    assert hit["fork"] is True
    assert "已竣" in hit["reported_bands"]

    # 负：护行长差无稽核链 → 不出现 audit_fork_signals 键
    escort_order = create_test_secret_order(
        db, state, actor, "护行辽饷", "逐月办理", ["护行"], deadline_months=4,
    )
    escort_dossier = int(db.get_dossier_for_secret_order(escort_order)["id"])
    nudges2 = db.list_monthly_dossier_progress_nudges()
    escort_nudge = next(n for n in nudges2 if int(n["dossier_id"]) == escort_dossier)
    assert "audit_fork_signals" not in escort_nudge


# ── ⑤ coerce 闭世界肯定识别器（#622 r2 畸形归 0）────────────────────






# ── ⑥ 补饷路由 seam：beyond_intent 不得因 purpose 分叉丢键（#622 r3）──


def _seed_army_arrears(db, army_id: str, arrears: int) -> None:
    db.conn.execute(
        """
        UPDATE armies
        SET arrears = ?, province_pay_arrears = 0, central_pay_arrears = ?
        WHERE id = ?
        """,
        (arrears, arrears, army_id),
    )
    db.conn.commit()


def test_commitment_pooled_pay_arrears_inherits_beyond_intent(game):
    """池化补饷：承诺月拨带 beyond_intent，拆分落库每行均继承（走 issues 结算 choke）。"""
    db, state, _content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    db.conn.execute("UPDATE armies SET arrears=0 WHERE owner_power='ming'")
    _seed_army_arrears(db, "guanning", 40)
    _seed_army_arrears(db, "xuan_da", 30)
    state.metrics["国库"] = 500
    db.save_state(state)

    ledger_before = db.conn.execute("SELECT COUNT(*) FROM economy_ledger").fetchone()[0]
    db.insert_issue(
        state,
        kind="initiative",
        title="边军月饷旨外",
        origin_kind="decree",
        origin_ref="decree:turn-1:beyond-pool-622",
        bar_value=0,
        inertia=0,
        stage_text="户部每月拨银补边军旧欠。",
        ongoing_effects={
            "economy": [{
                "account": "国库",
                "delta": -50,
                "category": "补饷承诺",
                "reason": "边军月饷旨外",
                "beyond_intent": 1,
            }]
        },
        stop_condition=json.dumps(
            {"army.guanning|xuan_da.arrears.sum": "<=0"}, ensure_ascii=False,
        ),
        commitment_kind="until_stop",
        cancellable="decree",
    )

    apply_issue_inertia_and_ongoing(db, state)

    rows = db.conn.execute(
        "SELECT beyond_intent, purpose, target_kind, target_id, delta "
        "FROM economy_ledger WHERE id > ? AND purpose='补饷' ORDER BY id",
        (ledger_before,),
    ).fetchall()
    assert rows, "池化补饷须落至少一笔 ledger"
    assert len(rows) >= 2, [dict(r) for r in rows]  # 多军拆分
    assert all(int(r["beyond_intent"]) == 1 for r in rows), [dict(r) for r in rows]
    assert all(r["target_kind"] == "army" for r in rows)
    assert {r["target_id"] for r in rows} <= {"guanning", "xuan_da"}
    assert sum(int(r["delta"]) for r in rows) == -50
