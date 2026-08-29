"""#622 变形判定＋双口径分叉（0072 口径＋0073 读端）。

测试预算 ≤3：
① AC1+AC2（transformed/degraded 对照）端到端 tracer + AC4 溯源 + 假进度零入 apply
② AC5 稽核信号正负成对
③ AC6 哨兵（progress_band + 公开面渲染 + scene_text 三面）

#621 接管窗/连坐/fail-closed 既有断言不得放松（本文件不改 #621 测）。
"""

from __future__ import annotations

import json

from ming_sim.db import GameDB
from tests.dossier_test_helpers import create_test_secret_order
from ming_sim.decree_vocabulary import (
    DEFORMATION_BANNED_PLAYER_TOKENS,
    format_public_progress_disclosure,
)
from ming_sim.due_review import (
    apply_pending_due_reviews,
    decide_due_review_verdict,
    list_due_review_scenes,
)
from ming_sim.flows import _apply_economy_list
from ming_sim.issues import apply_issue_inertia_and_ongoing, apply_score_extraction
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


# #629：提升入生产单源 decree_vocabulary.DEFORMATION_BANNED_PLAYER_TOKENS
_BANNED_SURFACE_TOKENS = DEFORMATION_BANNED_PLAYER_TOKENS


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


def test_apply_economy_list_directed_pay_arrears_echoes_beyond_intent(game):
    """定向补饷：beyond_intent 经 coerce 落 ledger 且 applied 回执回响；无标记仍为 0。"""
    db, state, _content = game
    army_id = "guanning"
    _seed_army_arrears(db, army_id, 30)
    state.metrics["国库"] = max(int(state.metrics.get("国库") or 0), 100)

    ledger_before = db.conn.execute("SELECT COUNT(*) FROM economy_ledger").fetchone()[0]

    applied = _apply_economy_list(
        db,
        state,
        [{
            "account": "国库",
            "delta": -10,
            "purpose": "补饷",
            "target_kind": "army",
            "target_id": army_id,
            "category": "补饷",
            "reason": "定向补饷旨外",
            "origin_ref": "dossier:item",
            "beyond_intent": True,
        }],
        origin_ref="dossier:parent",
        commit=True,
    )
    assert applied and applied[0].get("beyond_intent") is True, applied
    assert applied[0]["delta"] == -10
    assert applied[0]["origin_ref"] == "dossier:parent"
    assert applied[0]["applied"] is True

    row = db.conn.execute(
        "SELECT beyond_intent, purpose, target_id, origin_ref FROM economy_ledger "
        "WHERE id > ? ORDER BY id DESC LIMIT 1",
        (ledger_before,),
    ).fetchone()
    assert row is not None
    assert int(row["beyond_intent"]) == 1
    assert row["purpose"] == "补饷"
    assert row["target_id"] == army_id
    assert row["origin_ref"] == "dossier:parent"

    # 反向锚：不带标记 → ledger=0，canonical 回执为 false/空来源
    applied_plain = _apply_economy_list(
        db,
        state,
        [{
            "account": "国库",
            "delta": -5,
            "purpose": "补饷",
            "target_kind": "army",
            "target_id": army_id,
            "category": "补饷",
            "reason": "定向补饷无标记",
        }],
        commit=True,
    )
    assert applied_plain and applied_plain[0]["beyond_intent"] is False, applied_plain
    assert applied_plain[0]["origin_ref"] == ""
    assert applied_plain[0]["applied"] is True
    plain_row = db.conn.execute(
        "SELECT beyond_intent FROM economy_ledger WHERE reason=? ORDER BY id DESC LIMIT 1",
        ("定向补饷无标记",),
    ).fetchone()
    assert plain_row is not None
    assert int(plain_row["beyond_intent"]) == 0

    # 畸形值仍由 coerce 单点归 0，补饷分支不得自建判定
    applied_bad = _apply_economy_list(
        db,
        state,
        [{
            "account": "国库",
            "delta": -3,
            "purpose": "补饷",
            "target_kind": "army",
            "target_id": army_id,
            "category": "补饷",
            "reason": "定向补饷畸形",
            "beyond_intent": [],
        }],
        commit=True,
    )
    assert applied_bad and applied_bad[0]["beyond_intent"] is False, applied_bad
    assert applied_bad[0]["origin_ref"] == ""
    assert applied_bad[0]["applied"] is True
    bad_row = db.conn.execute(
        "SELECT beyond_intent FROM economy_ledger WHERE reason=? ORDER BY id DESC LIMIT 1",
        ("定向补饷畸形",),
    ).fetchone()
    assert bad_row is not None
    assert int(bad_row["beyond_intent"]) == 0


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


# ── ⑦ #651 continue：四出口 receipt × outer-first origin 对账矩阵 ─────────


def test_apply_economy_list_four_exit_effective_origin_receipt_matrix(game):
    """四出口 canonical receipt 与 durable ledger 共用 outer-first effective origin。

    出口：池化补饷成功 / 欠饷不足零支出 / 定向补饷成功 / 常规 economy move 成功。
    组合：outer-only、outer-over-item、双空反向锚。
    有落账的出口须 receipt.origin_ref/beyond_intent 与 economy_ledger 对账。
    """
    db, state, _content = game
    army_id = "guanning"
    state.metrics["国库"] = max(int(state.metrics.get("国库") or 0), 500)

    modes = (
        {
            "label": "outer_only",
            "outer": "dossier:outer651",
            "item_origin": "",
            "beyond": True,
            "expect_origin": "dossier:outer651",
            "expect_beyond": True,
        },
        {
            "label": "outer_over_item",
            "outer": "dossier:outer651",
            "item_origin": "dossier:item651",
            "beyond": True,
            "expect_origin": "dossier:outer651",
            "expect_beyond": True,
        },
        {
            "label": "dual_empty",
            "outer": "",
            "item_origin": "",
            "beyond": False,
            "expect_origin": "",
            "expect_beyond": False,
        },
    )

    def _ledger_max_id() -> int:
        return int(db.conn.execute("SELECT COALESCE(MAX(id), 0) FROM economy_ledger").fetchone()[0])

    def _ledger_after(before_id: int):
        return db.conn.execute(
            "SELECT origin_ref, beyond_intent, delta, purpose, reason "
            "FROM economy_ledger WHERE id > ? ORDER BY id",
            (before_id,),
        ).fetchall()

    def _move_base(reason: str, *, item_origin: str, beyond: bool) -> dict:
        move = {
            "account": "国库",
            "category": "补饷",
            "reason": reason,
        }
        if item_origin:
            move["origin_ref"] = item_origin
        if beyond:
            move["beyond_intent"] = True
        return move

    def _assert_receipt(receipt: dict, *, expect_origin: str, expect_beyond: bool, applied: bool):
        assert "origin_ref" in receipt and "beyond_intent" in receipt and "applied" in receipt, receipt
        assert receipt["origin_ref"] == expect_origin, receipt
        assert receipt["beyond_intent"] is expect_beyond, receipt
        assert receipt["applied"] is applied, receipt

    def _assert_ledger_matches(rows, *, expect_origin: str, expect_beyond: bool):
        assert rows, "须落 durable ledger 才能对账"
        for row in rows:
            assert str(row["origin_ref"] or "") == expect_origin, dict(row)
            assert bool(int(row["beyond_intent"])) is expect_beyond, dict(row)

    for mode in modes:
        label = mode["label"]
        outer = mode["outer"]
        item_origin = mode["item_origin"]
        beyond = mode["beyond"]
        expect_origin = mode["expect_origin"]
        expect_beyond = mode["expect_beyond"]

        # 1) 池化补饷成功
        _seed_army_arrears(db, army_id, 40)
        before = _ledger_max_id()
        pooled_reason = f"池化补饷-{label}"
        pooled_move = _move_base(pooled_reason, item_origin=item_origin, beyond=beyond)
        pooled_move["delta"] = -10
        pooled_move["purpose"] = "补饷"
        pooled = _apply_economy_list(
            db, state, [pooled_move],
            origin_ref=outer,
            allow_pay_arrears_pool=True,
            pay_arrears_pool_army_ids=[army_id],
            commit=True,
        )
        assert pooled and len(pooled) == 1, (label, pooled)
        _assert_receipt(
            pooled[0], expect_origin=expect_origin, expect_beyond=expect_beyond, applied=True,
        )
        assert pooled[0]["delta"] == -10, pooled[0]
        pooled_rows = [r for r in _ledger_after(before) if pooled_reason in str(r["reason"] or "")]
        _assert_ledger_matches(pooled_rows, expect_origin=expect_origin, expect_beyond=expect_beyond)
        assert sum(int(r["delta"]) for r in pooled_rows) == -10

        # 2) 欠饷不足/零支出（定向补饷，无 durable 落账）
        _seed_army_arrears(db, army_id, 0)
        before = _ledger_max_id()
        zero_reason = f"零支出补饷-{label}"
        zero_move = _move_base(zero_reason, item_origin=item_origin, beyond=beyond)
        zero_move.update({
            "delta": -8,
            "purpose": "补饷",
            "target_kind": "army",
            "target_id": army_id,
        })
        zeroed = _apply_economy_list(
            db, state, [zero_move], origin_ref=outer, commit=True,
        )
        assert zeroed and len(zeroed) == 1, (label, zeroed)
        _assert_receipt(
            zeroed[0], expect_origin=expect_origin, expect_beyond=expect_beyond, applied=False,
        )
        assert zeroed[0]["delta"] == 0, zeroed[0]
        assert _ledger_after(before) == [], (label, [dict(r) for r in _ledger_after(before)])

        # 3) 定向补饷成功
        _seed_army_arrears(db, army_id, 30)
        before = _ledger_max_id()
        directed_reason = f"定向补饷-{label}"
        directed_move = _move_base(directed_reason, item_origin=item_origin, beyond=beyond)
        directed_move.update({
            "delta": -6,
            "purpose": "补饷",
            "target_kind": "army",
            "target_id": army_id,
        })
        directed = _apply_economy_list(
            db, state, [directed_move], origin_ref=outer, commit=True,
        )
        assert directed and len(directed) == 1, (label, directed)
        _assert_receipt(
            directed[0], expect_origin=expect_origin, expect_beyond=expect_beyond, applied=True,
        )
        assert directed[0]["delta"] == -6, directed[0]
        directed_rows = [r for r in _ledger_after(before) if str(r["reason"] or "") == directed_reason]
        _assert_ledger_matches(directed_rows, expect_origin=expect_origin, expect_beyond=expect_beyond)
        assert sum(int(r["delta"]) for r in directed_rows) == -6

        # 4) 常规 economy move 成功
        before = _ledger_max_id()
        ordinary_reason = f"常规扣账-{label}"
        ordinary_move = _move_base(ordinary_reason, item_origin=item_origin, beyond=beyond)
        ordinary_move["delta"] = -4
        ordinary_move["category"] = "事项"
        # 无 purpose/target → 常规扣账出口
        ordinary = _apply_economy_list(
            db, state, [ordinary_move], origin_ref=outer, commit=True,
        )
        assert ordinary and len(ordinary) == 1, (label, ordinary)
        _assert_receipt(
            ordinary[0], expect_origin=expect_origin, expect_beyond=expect_beyond, applied=True,
        )
        assert ordinary[0]["delta"] == -4, ordinary[0]
        ordinary_rows = [r for r in _ledger_after(before) if str(r["reason"] or "") == ordinary_reason]
        _assert_ledger_matches(ordinary_rows, expect_origin=expect_origin, expect_beyond=expect_beyond)
        assert sum(int(r["delta"]) for r in ordinary_rows) == -4
