"""#629 S4 — extractor 奏报/分段/信用事件三槽路由收口 + 拒收报告可读性。

既有槽（禁新建平行槽）：
1. 奏报记录 → dossier_progress_reports（personnel_secret）
2. 分段承诺 → new_issues.stages（issues 嵌套字段，非顶层槽）
3. 信用事件 → apply 后 resolve_credit_events_from_extraction（非 extractor 顶层字段）

验收：路由归属钉死；错放 misroute 可读；坏分段拒收 reason 人读。
"""

from __future__ import annotations

import json

from ming_sim.issues import apply_score_extraction
from ming_sim.simulation import (
    EMPTY_EXTRACTION,
    MODULE_FIELDS,
    _FIELD_OWNER_MODULE,
    _sanitize_module_output,
)


# ── 路由收口：既有槽、禁平行 ─────────────────────────────────────────


def test_three_slots_are_existing_routes_no_parallel_top_level():
    """三槽不得升格为平行顶层 extractor 字段。"""
    # 奏报：personnel_secret 独有
    assert "dossier_progress_reports" in MODULE_FIELDS["personnel_secret"]
    assert "dossier_progress_reports" not in MODULE_FIELDS["issues"]
    assert "dossier_progress_reports" not in MODULE_FIELDS["internal"]
    assert _FIELD_OWNER_MODULE["dossier_progress_reports"] == "personnel_secret"

    # 分段：嵌在 new_issues，非 EMPTY/MODULE 顶层键
    assert "stages" not in EMPTY_EXTRACTION
    assert "stages" not in MODULE_FIELDS["issues"]
    assert "stages_json" not in EMPTY_EXTRACTION
    assert "new_issues" in MODULE_FIELDS["issues"]

    # 信用事件：写端后置，非 extractor 产出槽
    for banned in (
        "credit_events",
        "信用事件",
        "credit_event_resolutions",
        "credit:fulfill",
    ):
        assert banned not in EMPTY_EXTRACTION
        for fields in MODULE_FIELDS.values():
            assert banned not in fields


def test_dossier_progress_misroute_into_issues_is_readable(monkeypatch):
    """奏报槽错放进 issues：剔除 + 拒收 reason 人读（不猜改路由）。"""
    msgs: list[str] = []
    import ming_sim.simulation as sim
    monkeypatch.setattr(sim, "tlog", lambda m: msgs.append(m))

    out = _sanitize_module_output(
        "issues",
        {
            "new_issues": [],
            "dossier_progress_reports": [
                {"dossier_id": 1, "progress_band": "在办", "memorial_text": "误放"}
            ],
        },
    )
    assert "dossier_progress_reports" not in out or out.get("dossier_progress_reports") == []
    # 空模板默认 [] 在 cleaned；错放值不得存活
    assert out.get("dossier_progress_reports") in ([], None) or out["dossier_progress_reports"] == []
    rejections = out.get("_module_rejections") or []
    assert rejections, (out, msgs)
    hit = next(
        r for r in rejections
        if (r.get("item") or {}).get("field") == "dossier_progress_reports"
    )
    reason = str(hit.get("reason") or "")
    assert "personnel_secret" in reason
    assert "拒收" in reason or "不能由" in reason
    assert hit.get("category") == "misrouted_field"
    assert any("misroute" in m and "dossier_progress_reports" in m for m in msgs)


def test_staged_commitment_routes_via_new_issues_not_top_level_slot(game):
    """分段经 new_issues.stages 既有路径落库；无平行顶层 stages 消费。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    holder = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' "
        "AND office IS NOT NULL AND office != '' ORDER BY name LIMIT 1"
    ).fetchone()["name"]
    did = db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text="分段路由验",
        target_kind="issue",
        target_id="stage-route-629",
        executor_kind="character",
        executor_id=holder,
        payload={"token": "stage-route-629"},
    )
    db.record_dossier_decision(did, "promulgated")
    stages = [
        {
            "stage_idx": 0,
            "due_turn": state.turn + 12,
            "criterion_text": "火器见眉目",
            "origin_context": "一年火器见眉目",
        }
    ]
    out = apply_score_extraction(
        db, state,
        {
            "new_issues": [{
                "origin_kind": "decree",
                "origin_ref": f"dossier:{did}",
                "kind": "initiative",
                "title": "分段路由验之诺",
                "commitment_kind": "until_stop",
                "ongoing_effects": {},
                "stages": stages,
            }]
        },
        content=content,
    )
    created = out["issue_summary"]["new_issues"][0]
    assert created.get("rejected") is False, created
    row = db.conn.execute(
        "SELECT stages_json FROM issues WHERE id=?",
        (int(created["issue_id"]),),
    ).fetchone()
    stored = json.loads(row["stages_json"])
    assert stored[0]["criterion_text"] == "火器见眉目"


def test_credit_events_resolve_post_apply_not_extractor_slot(game):
    """信用事件只在 apply 后置识别；extractor 顶层喂 credit_events 不得建平行槽。"""
    db, state, content = game
    # 顶层平行键应被 sanitize 丢弃（无 owner）
    cleaned = _sanitize_module_output(
        "issues",
        {"new_issues": [], "credit_events": [{"kind": "兑现所托"}], "信用事件": []},
    )
    assert "credit_events" not in cleaned
    assert "信用事件" not in cleaned
    # 无主键不进 misroute 噪音
    assert not any(
        (r.get("item") or {}).get("field") in {"credit_events", "信用事件"}
        for r in (cleaned.get("_module_rejections") or [])
    )

    # 既有后置：apply 返回 credit_event_resolutions 键（写端汇总，非 extractor 输入槽）
    holder = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"]
    did = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="信用路由验",
        target_kind="issue",
        target_id="credit-route-629",
        executor_kind="character",
        executor_id=holder,
        participants=[{"character_id": holder, "tier": "主办"}],
        payload={"mode": "ordinary"},
    )
    db.record_dossier_decision(did, "promulgated")
    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing' WHERE id=?", (did,),
    )
    db.conn.commit()
    out = apply_score_extraction(
        db, state,
        {
            "dossier_executions": [{
                "dossier_id": did,
                "outcome": "fulfilled",
                "note": "所委依限办结",
            }]
        },
        content=content,
    )
    assert "credit_event_resolutions" in out


# ── 拒收报告可读性 ───────────────────────────────────────────────────


def test_bad_stages_rejection_reason_is_human_readable(game):
    """坏分段经 new_issues 路径拒收：reason 含人读中文，非空/非堆栈。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    holder = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' "
        "AND office IS NOT NULL AND office != '' ORDER BY name LIMIT 1"
    ).fetchone()["name"]
    did = db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text="坏段拒收验",
        target_kind="issue",
        target_id="bad-stage-629",
        executor_kind="character",
        executor_id=holder,
        payload={"token": "bad-stage-629"},
    )
    db.record_dossier_decision(did, "promulgated")

    out = apply_score_extraction(
        db, state,
        {
            "new_issues": [{
                "origin_kind": "decree",
                "origin_ref": f"dossier:{did}",
                "kind": "initiative",
                "title": "坏段拒收之诺",
                "commitment_kind": "until_stop",
                "ongoing_effects": {},
                # 显式坏 stages：due_turn=0 → capture 响亮 ValueError → 项拒收
                "stages": [{"due_turn": 0, "criterion_text": "x"}],
            }]
        },
        content=content,
    )
    created = out["issue_summary"]["new_issues"][0]
    assert created.get("rejected") is True, created
    reason = str(created.get("reason") or "")
    assert reason.strip(), created
    assert "Traceback" not in reason
    # 人读：点明 commitment 字段 / 段
    assert "commitment" in reason or "段" in reason or "stages" in reason
    assert created.get("category") == "invalid_enum"


def test_misroute_rejection_report_shape_is_readable():
    """misroute 拒收条具备 ADR 0015 形：rejected/reason/category/item。"""
    out = _sanitize_module_output(
        "internal",
        {
            "metric_delta": {},
            "dossier_progress_reports": [
                {"dossier_id": 9, "progress_band": "在办", "memorial_text": "错模块"}
            ],
        },
    )
    rejections = out.get("_module_rejections") or []
    assert len(rejections) == 1
    row = rejections[0]
    assert row["rejected"] is True
    assert isinstance(row["reason"], str) and len(row["reason"]) >= 8
    assert row["category"] == "misrouted_field"
    assert row["item"]["field"] == "dossier_progress_reports"
    assert row["item"]["owner_module"] == "personnel_secret"
    # 中文可读，非裸英文 enum-only
    assert any(ch >= "\u4e00" for ch in row["reason"])
