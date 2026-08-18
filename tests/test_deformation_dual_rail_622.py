"""#622 变形判定＋双口径分叉（0072 口径＋0073 读端）。

测试预算 ≤3：
① AC1+AC2（transformed/degraded 对照）端到端 tracer + AC4 溯源 + 假进度零入 apply
② AC5 稽核信号正负成对
③ AC6 哨兵（progress_band + 公开面渲染 + scene_text 三面）

#621 接管窗/连坐/fail-closed 既有断言不得放松（本文件不改 #621 测）。
"""

from __future__ import annotations

from ming_sim.db import GameDB
from ming_sim.decree_vocabulary import format_public_progress_disclosure
from ming_sim.due_review import (
    apply_pending_due_reviews,
    decide_due_review_verdict,
    list_due_review_scenes,
)
from ming_sim.issues import apply_score_extraction
from ming_sim.simulation import _sanitize_module_output
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


_BANNED_SURFACE_TOKENS = (
    "transformed", "degraded", "fulfilled", "failed", "executing",
    "progress_band", "is_terminal", "beyond_intent",
    "变形", "分界", "打折走样", "烂尾",
)


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
    assert "变形" not in term["memorial_text"]
    assert "名实已乖" not in term["memorial_text"]  # 假象，非判官 note
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
    db.record_issue_economy_move(
        state, "国库", 5, "浮收", "借旨行私",
        origin_ref=f"dossier:{target_id}", beyond_intent=True, commit=True,
    )

    # 正：长差稽核密令 + 稽核链指向目标
    audit_order = db.create_secret_order(
        state, actor, "密查清丈浮收", "逐月密奏", ["稽核"], deadline_months=4,
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
    escort_order = db.create_secret_order(
        state, actor, "护行辽饷", "逐月办理", ["护行"], deadline_months=4,
    )
    escort_dossier = int(db.get_dossier_for_secret_order(escort_order)["id"])
    nudges2 = db.list_monthly_dossier_progress_nudges()
    escort_nudge = next(n for n in nudges2 if int(n["dossier_id"]) == escort_dossier)
    assert "audit_fork_signals" not in escort_nudge


# ── ③ AC6 哨兵三面 ───────────────────────────────────────────────────


def test_ac6_sentinel_no_system_tokens_on_three_surfaces(game):
    """断言面=progress_band 列 + 公开面渲染 + 到期复命 scene_text；变形/分界等零裸露。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    dossier_id = _executing_policy(db, state, token="sentinel-622")
    db.record_dossier_progress(
        dossier_id, state.turn, "在办", "臣工奏称诸事已妥",
        is_terminal=False, commit=True,
    )
    apply_score_extraction(
        db, state,
        {
            "economy_moves": [{
                "account": "国库",
                "delta": 3,
                "category": "浮收",
                "reason": "额外加派",
                "origin_ref": f"dossier:{dossier_id}",
                "beyond_intent": True,
            }],
        },
        content=content,
    )
    _insert_final_stage(
        db, state, content, dossier_id=dossier_id, title="哨兵·清丈",
    )
    write_due_staged_commitment_todos(db, state)

    # 面 3：到期复命 scene_text（落格前可读）
    scenes = list_due_review_scenes(db, state)
    assert scenes
    for token in ("变形", "分界", "transformed", "degraded", "beyond_intent",
                  "fulfilled", "failed", "executing", "progress_band"):
        assert token not in scenes[0]["scene_text"], token
        assert token not in scenes[0].get("gap_text", ""), token
        assert token not in scenes[0].get("statement_text", ""), token

    db.conn.execute(
        "UPDATE next_audience_todos SET created_turn=?",
        (state.turn - 1,),
    )
    db.conn.commit()
    apply_pending_due_reviews(db, state, commit=True)

    # 面 1：dossier_reported_progress.progress_band 列
    rows = db.list_dossier_progress(dossier_id)
    assert rows
    for row in rows:
        band = str(row["progress_band"])
        memorial = str(row["memorial_text"])
        for token in _BANNED_SURFACE_TOKENS:
            assert token not in band, (token, band)
            # memorial 允许普通中文，但禁系统词
        for token in ("变形", "分界", "transformed", "degraded", "beyond_intent"):
            assert token not in band
            assert token not in memorial

    # 面 2：公开面渲染（生产单源 format_public_progress_disclosure）
    public = format_public_progress_disclosure(rows)
    for token in _BANNED_SURFACE_TOKENS:
        assert token not in public, (token, public)

    # 执行格真值仍在（哨兵不覆盖机面）
    assert db.get_decree_dossier(dossier_id)["execution_outcome"] == "transformed"


# ── ④ web 路真清洗器 seam（#622 剥键点）────────────────────────────────


def test_web_sanitize_seam_beyond_intent_survives_to_transformed(game, content):
    """穿 _sanitize_module_output 真清洗器 seam：beyond_intent 须存活到 apply 与终裁。

    旧测失明原因：test_deformation_dual_rail_622.py:127/:266/:316/:205-228 全部直调
    applier/DB/裁决函数，注入起点在剥键点（_clean_economy_moves 合法行重建）下游一站，
    清洗器被切在断言线外——web 真路经 cleaner 重建 entry 时 beyond_intent 被静默丢掉，
    旧测仍绿。本条强制 raw extractor 输出形（旨外别名 + beyond_intent 英文键）先过
    _sanitize_module_output("internal", …）再合并喂 apply_score_extraction。
    """
    db, state, _content = game
    dossier_id = _executing_policy(db, state, token="sanitize-seam-622")
    origin = f"dossier:{dossier_id}"

    # raw extractor 输出形：一条中文别名 旨外:true + 一条 beyond_intent:true
    raw_internal = {
        "economy_moves": [
            {
                "account": "国库",
                "delta": 8,
                "category": "地方浮收",
                "reason": "借清丈加派入私",
                "origin_ref": origin,
                "旨外": True,
            },
            {
                "account": "内库",
                "delta": 4,
                "category": "额外进项",
                "reason": "旨外受益入内",
                "origin_ref": origin,
                "beyond_intent": True,
            },
        ],
    }
    cleaned = _sanitize_module_output("internal", raw_internal)
    moves_out = cleaned.get("economy_moves") or []
    assert len(moves_out) == 2, moves_out
    # cleaner 须无损透传（别名已由 _canonical_item_fields 归一）；不在此判真假
    assert all("beyond_intent" in m for m in moves_out), moves_out

    applied = apply_score_extraction(db, state, cleaned, content=content)
    assert applied["economy_moves"], applied
    stored = db.list_economy_moves_for_dossier(dossier_id)
    assert len(stored) >= 2, stored
    assert all(m["beyond_intent"] is True for m in stored), stored
    assert all(m["origin_ref"] == origin for m in stored), stored

    # 续走到到期复核：终裁须落 transformed（标记存活到裁决读端）
    result = _prime_and_apply_due_review(
        db, state, content, dossier_id=dossier_id, title="清洗器缝·清丈",
    )
    assert result["verdict"]["outcome"] == "transformed"
    assert db.get_decree_dossier(dossier_id)["execution_outcome"] == "transformed"


# ── ⑤ coerce 闭世界肯定识别器（#622 r2 畸形归 0）────────────────────


def test_coerce_beyond_intent_flag_closed_affirmative_world():
    """coerce_beyond_intent_flag 是闭世界肯定识别器。

    仅契约内肯定表示（True / 非零 int·float / 肯定串集）→1；
    缺席、否定、空、任何畸形（含非标量、非契约串）一律 →0。
    开放兜底永不得回归。
    """
    coerce = GameDB.coerce_beyond_intent_flag

    # 肯定集
    for value in (True, 1, 2, 1.5, "true", "TRUE", "1", "yes", "on", "是", "有", "真"):
        assert coerce(value) == 1, value

    # 否定 / 缺省
    for value in (False, 0, 0.0, None, "否", "无", "off", "false", "no", "0"):
        assert coerce(value) == 0, value

    # 畸形：非标量 + 垃圾串 + 空串 —— 一律 0（不得捏造肯定）
    for value in ([], {}, [False], {"a": 1}, "null", "None", "0.0", "", "  ", "maybe", "garbage"):
        assert coerce(value) == 0, value


def test_decide_due_review_malformed_beyond_intent_stays_fulfilled():
    """durable_effects 带 beyond_intent=[] 畸形标记须判 fulfilled 而非 transformed。"""
    review_input = {
        "mid_stage": False,
        "criterion_text": "清丈见成数",
        "origin_context": "清丈畿辅田亩",
        "progress_reports": [{"progress_band": "在办", "memorial_text": "已办十之八九"}],
        "durable_effects": [{
            "origin_ref": "dossier:0",
            "delta": 12,
            "beyond_intent": [],
        }],
    }
    assert decide_due_review_verdict(review_input)["outcome"] == "fulfilled"
