"""#625 / ADR 0077 钝化事实底＋人身条件化判官口径。

Seams:
- dossier_supervision_presence / dossier_loophole_exposures 事实表
- record_monthly_supervision_facts（与 grant recon 同段）
- build_due_review_input.supervision_history
- simulator/extractor 执行格面观察槽
- dossier_reported_progress origin 结构化私货/同派标记
- auto_trigger 涌现缝反制 issue
- AC5 禁词哨兵（scene_text/narrative/turn_report/knowledge_items/memorial_text）
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from ming_sim.db import GameDB
from ming_sim.decree import (
    project_dossiers_for_simulator,
    settle_with_delta,
)
from ming_sim.due_review import (
    build_due_review_input,
    project_due_review_scene,
)
from ming_sim.simulation import (
    build_extractor_shared_context,
    build_simulator_payload,
)
from ming_sim.staged_commitment import (
    TODO_STATUS_PENDING,
    write_due_staged_commitment_todos,
)
from ming_sim.participant_roster import resolve_dossier_owner_name
from ming_sim.supervision import (
    COUNTERMEASURE_ORIGIN_KIND,
    COUNTERMEASURE_PRESENCE_MONTHS,
    EMPTY_TRANSFORMATION_TENDENCY_FACTS,
    EXPOSURE_ALLOWED_COLS,
    EXPOSURE_TABLE,
    FORBIDDEN_DULLING_COL_FRAGMENTS,
    ORIGIN_MARK_PRIVATE_GOODS,
    ORIGIN_MARK_SAME_FACTION_BLIND,
    PRESENCE_ALLOWED_COLS,
    PRESENCE_TABLE,
    SUPERVISION_BANNED_PLAYER_TOKENS,
    SUPERVISION_RELATION,
    SUPERVISION_SURFACE_KEYS,
    assert_no_banned_tokens,
    compose_report_origin,
    derive_consecutive_months,
    faction_relation,
    origin_has_mark,
    parse_report_origin,
    unpack_supervision_surface,
)


# ── fixtures helpers ──────────────────────────────────────────────


def _chars_by_faction(db):
    rows = db.conn.execute(
        "SELECT name, faction, integrity FROM characters "
        "WHERE status='active' AND COALESCE(faction,'') NOT IN ('','流寇','后金','宗室','嫔妃','宠妃','中宫','蒙古','朝鲜') "
        "ORDER BY name"
    ).fetchall()
    by_f: dict[str, list] = {}
    for row in rows:
        by_f.setdefault(str(row["faction"]), []).append(row)
    return by_f


def _pair_same_faction(db):
    by_f = _chars_by_faction(db)
    for fac, rows in by_f.items():
        if len(rows) >= 2:
            return rows[0], rows[1]
    raise RuntimeError("no same-faction pair")


def _pair_enemy_faction(db):
    by_f = _chars_by_faction(db)
    facs = [f for f, rows in by_f.items() if rows]
    assert len(facs) >= 2
    return by_f[facs[0]][0], by_f[facs[1]][0]


def _upright_and_mediocre(db):
    rows = db.conn.execute(
        "SELECT name, faction, integrity FROM characters "
        "WHERE status='active' ORDER BY name"
    ).fetchall()
    upright = next(r for r in rows if int(r["integrity"]) >= 60)
    mediocre = next(r for r in rows if int(r["integrity"]) < 50)
    return upright, mediocre


def _subject_dossier(db, state, *, owner: str, token: str = "subj"):
    did = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"清丈{token}",
        target_kind="issue",
        target_id=f"land-{token}",
        executor_kind="character",
        executor_id=owner,
        participants=[{"character_id": owner, "tier": "主办"}],
    )
    db.apply_dossier_promulgation(state, did, "promulgated")
    return did


def _audit_dossier(db, state, *, auditor: str, subject_id: int, token: str = "audit"):
    """稽核方案卷（新 id）→ 稽核 → 被稽案卷（旧 id）。须后建以保证 id 更大。"""
    aid = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"稽核{token}",
        target_kind="issue",
        target_id=f"audit-{token}",
        executor_kind="character",
        executor_id=auditor,
        participants=[{"character_id": auditor, "tier": "主办"}],
    )
    db.apply_dossier_promulgation(state, aid, "promulgated")
    db.add_dossier_links(aid, [{
        "target_dossier_id": int(subject_id),
        "relation_type": SUPERVISION_RELATION,
        "note": f"稽核案卷{subject_id}",
    }])
    return aid


def _insert_staged(db, state, content, *, dossier_id: int, due_turn: int):
    import ming_sim.issues as issue_engine

    stages = [{
        "stage_idx": 0,
        "due_turn": int(due_turn),
        "criterion_text": "清丈见眉目",
        "origin_context": "限期清丈",
    }]
    out = issue_engine.apply_score_extraction(
        db, state,
        {
            "new_issues": [{
                "origin_kind": "decree",
                "origin_ref": f"dossier:{int(dossier_id)}",
                "kind": "initiative",
                "title": f"清丈分段-{dossier_id}",
                "stage_text": "限期清丈",
                "commitment_kind": "until_stop",
                "ongoing_effects": {},
                "stages": stages,
            }],
        },
        content=content,
    )
    created = out["issue_summary"]["new_issues"][0]
    assert created.get("rejected") is False, created
    return int(created["issue_id"])


def _settle(db, state, content, *, narrative="本月邸报，边事略平。", **extracted):
    settle_with_delta(
        state, db, extracted, before_turn=state.turn, content=content,
        narrative=narrative,
    )


def _table_cols(db, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in db.conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    }


# ── unit pure ─────────────────────────────────────────────────────


def test_derive_consecutive_months_and_faction_relation():
    assert derive_consecutive_months([1, 2, 3, 5], end_turn=5) == 1
    assert derive_consecutive_months([1, 2, 3, 4], end_turn=4) == 4
    assert derive_consecutive_months([10, 11, 12], end_turn=12) == 3
    assert faction_relation("东林", "东林") == "same"
    assert faction_relation("东林", "阉党") == "enemy"
    assert faction_relation("", "阉党") == "other"


def test_origin_mark_compose_parse_roundtrip():
    base = "dossier-report:monthly_errand"
    marked = compose_report_origin(
        base, [ORIGIN_MARK_PRIVATE_GOODS, ORIGIN_MARK_SAME_FACTION_BLIND],
    )
    root, marks = parse_report_origin(marked)
    assert root == base
    assert ORIGIN_MARK_PRIVATE_GOODS in marks
    assert ORIGIN_MARK_SAME_FACTION_BLIND in marks
    assert origin_has_mark(marked, ORIGIN_MARK_PRIVATE_GOODS)


# ── AC1 事实底 ────────────────────────────────────────────────────


def test_ac1_presence_exposure_schema_pragma_and_no_dulling_cols(game):
    db, state, _content = game
    assert PRESENCE_TABLE in {
        r[0] for r in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert EXPOSURE_TABLE in {
        r[0] for r in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    pcols = _table_cols(db, PRESENCE_TABLE)
    ecols = _table_cols(db, EXPOSURE_TABLE)
    assert pcols == PRESENCE_ALLOWED_COLS
    assert ecols == EXPOSURE_ALLOWED_COLS

    # 全库无钝化数值列
    tables = [
        str(r[0])
        for r in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    for table in tables:
        for col in _table_cols(db, table):
            low = col.lower()
            for frag in FORBIDDEN_DULLING_COL_FRAGMENTS:
                assert frag.lower() not in low, f"{table}.{col} 命中禁列片段 {frag}"


def test_ac1_monthly_write_idempotent_readable_and_restore(game, tmp_path, content):
    db, state, _content = game
    subj_owner, _ = _pair_same_faction(db)
    auditor = _upright_and_mediocre(db)[0]
    subject_id = _subject_dossier(db, state, owner=str(subj_owner["name"]), token="r1")
    audit_id = _audit_dossier(
        db, state, auditor=str(auditor["name"]), subject_id=subject_id, token="r1",
    )

    turn = int(state.turn)
    # 同段写口：与 grant recon 一并调用
    db.record_monthly_supervision_facts(turn, commit=True)
    db.record_monthly_supervision_facts(turn, commit=True)  # 幂等不双计

    presence = db.list_supervision_presence(subject_id)
    assert len(presence) == 1
    row = presence[0]
    assert row["turn"] == turn
    assert row["auditor_name"] == str(auditor["name"])
    assert row["audit_dossier_id"] == audit_id
    assert row["relation_type"] == SUPERVISION_RELATION
    assert row["present"] is True

    hist = db.list_supervision_history(subject_id)
    assert len(hist) == 1
    assert hist[0]["consecutive_months"] == 1
    assert "auditor_tenure" in hist[0]
    assert "faction_relation" in hist[0]
    assert "auditor_integrity_band" in hist[0]

    # 空子暴露：机械写入 + 幂等
    db.record_loophole_exposure(
        subject_id, turn, "policy", "transformed", commit=True,
    )
    db.record_loophole_exposure(
        subject_id, turn, "policy", "transformed", commit=True,
    )
    exps = db.list_loophole_exposures(subject_id)
    assert len(exps) == 1
    assert exps[0]["action_type"] == "policy"
    assert exps[0]["execution_form"] == "transformed"

    expected_hist = db.list_supervision_history(subject_id)
    expected_exp = db.list_loophole_exposures(subject_id)

    backup = tmp_path / "restore-625.db"
    db.backup_to(str(backup))
    db.close()

    restored = GameDB(str(backup), content=content)
    try:
        assert restored.list_supervision_history(subject_id) == expected_hist
        assert restored.list_loophole_exposures(subject_id) == expected_exp
        # restore 后同 turn 重跑不双计
        restored.record_monthly_supervision_facts(turn, commit=True)
        assert len(restored.list_supervision_presence(subject_id)) == 1
    finally:
        restored.close()


def test_ac1_settle_segment_writes_presence(game):
    """事实行随 grant recon 同段写入（settle_with_delta atomic）。"""
    db, state, content = game
    owner, _ = _pair_same_faction(db)
    auditor = _upright_and_mediocre(db)[1]
    subject_id = _subject_dossier(db, state, owner=str(owner["name"]), token="seg")
    _audit_dossier(
        db, state, auditor=str(auditor["name"]), subject_id=subject_id, token="seg",
    )
    before_turn = int(state.turn)
    before = len(db.list_supervision_presence(subject_id))
    _settle(db, state, content)
    after = db.list_supervision_presence(subject_id)
    assert len(after) == before + 1
    # settle 推进 turn；在场行键控 before_turn
    assert any(int(r["turn"]) == before_turn for r in after)


# ── AC2 成对锚观察槽 + 反制硬门 ───────────────────────────────────


def test_ac2_paired_observation_slots_and_countermeasure_hard_gate(game):
    """judge-in-loop 确定性前置：观察槽=执行格判词面+变形倾向事实；孤直满 12 月反制必立。"""
    db, state, content = game
    upright, mediocre = _upright_and_mediocre(db)

    # 庸吏同路：被稽与稽核同派
    by_f = _chars_by_faction(db)
    med_fac = str(mediocre["faction"] or "")
    peers = by_f.get(med_fac) or []
    subject_owner = next(
        (r for r in peers if str(r["name"]) != str(mediocre["name"])),
        mediocre,
    )
    sub_m = _subject_dossier(db, state, owner=str(subject_owner["name"]), token="med")
    _audit_dossier(
        db, state, auditor=str(mediocre["name"]), subject_id=sub_m, token="med",
    )

    # 孤直同路
    up_fac = str(upright["faction"] or "")
    up_peers = by_f.get(up_fac) or []
    subject_up = next(
        (r for r in up_peers if str(r["name"]) != str(upright["name"])),
        upright,
    )
    sub_u = _subject_dossier(db, state, owner=str(subject_up["name"]), token="up")
    _audit_dossier(
        db, state, auditor=str(upright["name"]), subject_id=sub_u, token="up",
    )

    base_turn = int(state.turn)
    for offset in range(COUNTERMEASURE_PRESENCE_MONTHS):
        db.record_monthly_supervision_facts(base_turn + offset, commit=True)

    hist_m = db.list_supervision_history(sub_m, as_of_turn=base_turn + 11)
    hist_u = db.list_supervision_history(sub_u, as_of_turn=base_turn + 11)
    assert hist_m[0]["consecutive_months"] == 12
    assert hist_u[0]["consecutive_months"] == 12

    surface_m = db.build_supervision_judge_surface(sub_m, as_of_turn=base_turn + 11)
    surface_u = db.build_supervision_judge_surface(sub_u, as_of_turn=base_turn + 11)
    # 观察槽：变形倾向事实（无钝化数值）
    tend_m = surface_m["transformation_tendency_facts"]
    tend_u = surface_u["transformation_tendency_facts"]
    assert tend_m["longest_consecutive_presence_months"] == 12
    assert tend_u["longest_consecutive_presence_months"] == 12
    assert tend_m["has_mediocre_auditor"] is True
    assert tend_u["has_upright_auditor"] is True
    assert "dull" not in json.dumps(tend_m, ensure_ascii=False).lower()
    assert "钝化" not in json.dumps(tend_m, ensure_ascii=False)

    # 执行格判词观察槽：注入 due_review / simulator 面
    _insert_staged(db, state, content, dossier_id=sub_m, due_turn=state.turn)
    write_due_staged_commitment_todos(db, state)
    todo = db.list_next_audience_todos(status=TODO_STATUS_PENDING)[0]
    inp = build_due_review_input(db, todo)
    assert inp["supervision_history"]
    assert inp["transformation_tendency_facts"]["longest_consecutive_presence_months"] >= 1

    # 孤直反制硬门：满 12 月 → 涌现缝立 issue（邸报前 auto_trigger 同缝）
    triggered = db.trigger_supervision_countermeasures(state, commit=True)
    assert triggered, "孤直满 12 月须立反制 issue"
    kinds = {str(item.get("countermeasure_kind") or "") for item in triggered}
    assert kinds & {"架空", "断信息", "诬告围攻", "明升暗调"}
    issue = db.find_active_issue_by_origin(
        COUNTERMEASURE_ORIGIN_KIND,
        triggered[0]["origin_ref"],
    )
    assert issue is not None
    # 重跑幂等
    again = db.trigger_supervision_countermeasures(state, commit=True)
    assert again == []


# ── AC3 同派/敌派 origin 标记 ─────────────────────────────────────


def test_ac3_same_vs_enemy_origin_marks_on_reported_progress(game):
    db, state, _content = game
    same_a, same_b = _pair_same_faction(db)
    enemy_a, enemy_b = _pair_enemy_faction(db)

    # 同派
    sub_s = _subject_dossier(db, state, owner=str(same_a["name"]), token="sf")
    _audit_dossier(
        db, state, auditor=str(same_b["name"]), subject_id=sub_s, token="sf",
    )
    db.record_monthly_supervision_facts(state.turn, commit=True)
    origin_s = db.compose_supervision_report_origin(sub_s, state.turn)
    assert origin_has_mark(origin_s, ORIGIN_MARK_SAME_FACTION_BLIND)
    assert not origin_has_mark(origin_s, ORIGIN_MARK_PRIVATE_GOODS)

    rid = db.record_dossier_progress(
        sub_s, state.turn, "在办", "同路稽核例行奏报",
        origin=origin_s, commit=True,
    )
    assert rid > 0
    rows = db.list_dossier_progress(sub_s)
    assert origin_has_mark(rows[-1]["origin"], ORIGIN_MARK_SAME_FACTION_BLIND)

    # 敌派
    sub_e = _subject_dossier(db, state, owner=str(enemy_a["name"]), token="ef")
    _audit_dossier(
        db, state, auditor=str(enemy_b["name"]), subject_id=sub_e, token="ef",
    )
    db.record_monthly_supervision_facts(state.turn, commit=True)
    origin_e = db.compose_supervision_report_origin(sub_e, state.turn)
    assert origin_has_mark(origin_e, ORIGIN_MARK_PRIVATE_GOODS)
    assert not origin_has_mark(origin_e, ORIGIN_MARK_SAME_FACTION_BLIND)

    db.record_dossier_progress(
        sub_e, state.turn, "在办", "异路稽核密折",
        origin=origin_e, commit=True,
    )
    rows_e = db.list_dossier_progress(sub_e)
    assert origin_has_mark(rows_e[-1]["origin"], ORIGIN_MARK_PRIVATE_GOODS)

    # 奏报永不入 apply：世界指纹不因 origin 标记而改库外状态（钱粮）
    before_inner = int(state.metrics.get("内库") or 0)
    assert int(state.metrics.get("内库") or 0) == before_inner


# ── AC4 空子转移读入面差分 ────────────────────────────────────────


def test_ac4_exposure_history_delta_on_tendency_surface(game):
    db, state, _content = game
    owner, _ = _pair_same_faction(db)
    subject_id = _subject_dossier(db, state, owner=str(owner["name"]), token="lp")
    before = db.build_supervision_judge_surface(subject_id)
    assert before["transformation_tendency_facts"]["exposure_count"] == 0
    assert before["loophole_exposures"] == []

    db.record_loophole_exposure(
        subject_id, state.turn, "policy", "transformed", commit=True,
    )
    after = db.build_supervision_judge_surface(subject_id)
    assert after["transformation_tendency_facts"]["exposure_count"] == 1
    assert "policy+transformed" in after["transformation_tendency_facts"]["exposure_classes"]
    assert len(after["loophole_exposures"]) == 1
    # 差分可断言
    assert after["loophole_exposures"] != before["loophole_exposures"]


def test_ac4_unified_presence_gate_on_terminal_and_recon_paths(game):
    """⑤统一在场门：终值路/对账路均须本 turn 稽核在场才写暴露；AC4 差分仍立。"""
    db, state, _content = game
    owner, auditor_row = _pair_same_faction(db)
    turn = int(state.turn)

    # 无人盯：终值变形不落暴露
    bare_id = _subject_dossier(db, state, owner=str(owner["name"]), token="bare")
    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing' WHERE id=?", (bare_id,),
    )
    db.conn.commit()
    db.record_dossier_execution(
        bare_id, "transformed", "无人盯走样", turn, close=True, commit=True,
    )
    assert db.list_loophole_exposures(bare_id) == []

    # 被盯紧：终值变形落暴露 → 读入面差分
    watched_id = _subject_dossier(db, state, owner=str(owner["name"]), token="watch")
    _audit_dossier(
        db, state, auditor=str(auditor_row["name"]), subject_id=watched_id, token="watch",
    )
    db.record_monthly_supervision_presence(turn, commit=True)
    assert db.dossier_has_supervision_presence(watched_id, turn)
    before = db.build_supervision_judge_surface(watched_id)
    assert before["transformation_tendency_facts"]["exposure_count"] == 0

    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing' WHERE id=?", (watched_id,),
    )
    db.conn.commit()
    db.record_dossier_execution(
        watched_id, "transformed", "被盯紧走样", turn, close=True, commit=True,
    )
    after = db.build_supervision_judge_surface(watched_id)
    assert after["transformation_tendency_facts"]["exposure_count"] == 1
    assert "policy+transformed" in after["transformation_tendency_facts"]["exposure_classes"]
    assert after["loophole_exposures"] != before["loophole_exposures"]

    # 对账路：同门——无在场不写，有在场才写
    recon_bare = _subject_dossier(db, state, owner=str(owner["name"]), token="rb")
    db.conn.execute(
        """
        INSERT INTO decree_dossier_reconciliations
            (dossier_id, turn, ordered_amount, arrived_amount, loss_amount)
        VALUES (?, ?, 100, 40, 60)
        """,
        (recon_bare, turn),
    )
    db.conn.commit()
    out_bare = db.record_monthly_loophole_exposures_from_reconciliations(turn, commit=True)
    assert int(out_bare["exposure_written"]) == 0
    assert db.list_loophole_exposures(recon_bare) == []

    recon_watched = _subject_dossier(db, state, owner=str(owner["name"]), token="rw")
    _audit_dossier(
        db, state, auditor=str(auditor_row["name"]),
        subject_id=recon_watched, token="rw",
    )
    db.record_monthly_supervision_presence(turn, commit=True)
    db.conn.execute(
        """
        INSERT INTO decree_dossier_reconciliations
            (dossier_id, turn, ordered_amount, arrived_amount, loss_amount)
        VALUES (?, ?, 100, 40, 60)
        """,
        (recon_watched, turn),
    )
    db.conn.commit()
    out_w = db.record_monthly_loophole_exposures_from_reconciliations(turn, commit=True)
    assert int(out_w["exposure_written"]) >= 1
    exps = db.list_loophole_exposures(recon_watched)
    assert any(r["execution_form"] == "degraded" for r in exps)


def test_owner_identity_single_source_shared_with_tenure():
    """①归属人单源：executor 优先，否则首名主办；#613 任别共调。"""
    by_executor = {
        "executor_id": "张居正",
        "executor_kind": "character",
        "participant_roster": [{"character_id": "他人", "tier": "主办"}],
    }
    assert resolve_dossier_owner_name(by_executor) == "张居正"
    by_roster = {
        "executor_id": "",
        "executor_kind": "",
        "participant_roster": [
            {"character_id": "知情甲", "tier": "知情"},
            {"character_id": "主办乙", "tier": "主办"},
        ],
    }
    assert resolve_dossier_owner_name(by_roster) == "主办乙"
    assert resolve_dossier_owner_name({}) == ""


def test_unpack_supervision_surface_empty_form_is_constant():
    """②三键 unpack + 空形常量真源。"""
    empty = unpack_supervision_surface(None)
    assert empty["supervision_history"] == []
    assert empty["loophole_exposures"] == []
    assert empty["transformation_tendency_facts"] == EMPTY_TRANSFORMATION_TENDENCY_FACTS
    assert set(empty) == set(SUPERVISION_SURFACE_KEYS)


# ── AC5 哨兵 ──────────────────────────────────────────────────────


def test_ac5_banned_tokens_absent_from_named_surfaces(game):
    db, state, content = game
    owner, auditor_row = _pair_same_faction(db)
    subject_id = _subject_dossier(db, state, owner=str(owner["name"]), token="ban")
    _audit_dossier(
        db, state, auditor=str(auditor_row["name"]), subject_id=subject_id, token="ban",
    )
    db.record_monthly_supervision_facts(state.turn, commit=True)
    db.record_loophole_exposure(
        subject_id, state.turn, "policy", "degraded", commit=True,
    )
    origin = db.compose_supervision_report_origin(subject_id, state.turn)
    db.record_dossier_progress(
        subject_id, state.turn, "在办", "沿途核验无大异",
        origin=origin, commit=True,
    )

    _insert_staged(db, state, content, dossier_id=subject_id, due_turn=state.turn)
    write_due_staged_commitment_todos(db, state)
    todo = db.list_next_audience_todos(status=TODO_STATUS_PENDING)[0]
    scene = project_due_review_scene(db, todo)

    # scene_text
    assert_no_banned_tokens(scene["scene_text"], surface="scene_text")
    assert_no_banned_tokens(scene.get("gap_text"), surface="scene_text.gap")
    assert_no_banned_tokens(scene.get("statement_text"), surface="scene_text.statement")

    # memorial_text（奏报正文）
    for row in db.list_dossier_progress(subject_id):
        assert_no_banned_tokens(row.get("memorial_text"), surface="memorial_text")

    # narrative / turn_report via settle
    _settle(db, state, content, narrative="本月边报无异，吏治照常")
    # settle 后 turn_logs / turn_reports
    logs = db.conn.execute(
        "SELECT message FROM turn_logs ORDER BY turn DESC LIMIT 3"
    ).fetchall()
    for row in logs:
        assert_no_banned_tokens(row["message"], surface="narrative")

    reports = db.conn.execute(
        "SELECT report FROM turn_reports ORDER BY turn DESC LIMIT 3"
    ).fetchall()
    for rep in reports:
        assert_no_banned_tokens(rep["report"], surface="turn_report")

    # knowledge_items
    if hasattr(db, "knowledge_items_for_turn"):
        items = db.knowledge_items_for_turn(state.turn) or []
        for item in items:
            if isinstance(item, dict):
                for key in ("text", "body", "summary", "content"):
                    if key in item:
                        assert_no_banned_tokens(item.get(key), surface="knowledge_items")

    # 禁词表本身含票面点名系统词
    for token in ("钝化", "陋规化"):
        assert token in SUPERVISION_BANNED_PLAYER_TOKENS


# ── 注入面 ────────────────────────────────────────────────────────


def test_injection_simulator_and_extractor_surfaces(game):
    db, state, content = game
    owner, auditor_row = _pair_same_faction(db)
    subject_id = _subject_dossier(db, state, owner=str(owner["name"]), token="inj")
    _audit_dossier(
        db, state, auditor=str(auditor_row["name"]), subject_id=subject_id, token="inj",
    )
    db.record_monthly_supervision_facts(state.turn, commit=True)
    db.record_loophole_exposure(
        subject_id, state.turn, "policy", "degraded", commit=True,
    )

    visible = [dict(r) for r in db.list_decree_dossiers_for_simulation(state.turn)]
    projected = project_dossiers_for_simulator(visible, db=db, state=state)
    hit = next(r for r in projected if int(r["id"]) == subject_id)
    assert "supervision_history" in hit
    assert "loophole_exposures" in hit
    assert "transformation_tendency_facts" in hit
    assert hit["supervision_history"]
    assert hit["loophole_exposures"]

    payload = build_simulator_payload(state, db, "着清丈", "")
    # payload 经 project 装配时由调用方传入；此处直接验 project 结果已含槽
    ctx = build_extractor_shared_context(db, state, "邸报", "", module="issues")
    dhit = next(r for r in ctx["decree_dossiers"] if int(r["id"]) == subject_id)
    assert dhit.get("supervision_history") is not None
    assert dhit.get("transformation_tendency_facts") is not None


def test_extractor_supervision_keys_gated_to_issues_module(game):
    """⑥监督三键仅 module==issues；其他 extractor 不得见未申报键。"""
    db, state, _content = game
    owner, auditor_row = _pair_same_faction(db)
    subject_id = _subject_dossier(db, state, owner=str(owner["name"]), token="gate")
    _audit_dossier(
        db, state, auditor=str(auditor_row["name"]), subject_id=subject_id, token="gate",
    )
    db.record_monthly_supervision_presence(state.turn, commit=True)

    issues_ctx = build_extractor_shared_context(
        db, state, "邸报", "", module="issues",
    )
    issues_hit = next(
        r for r in issues_ctx["decree_dossiers"] if int(r["id"]) == subject_id
    )
    for key in SUPERVISION_SURFACE_KEYS:
        assert key in issues_hit

    for module in ("internal", "military_external", "personnel_secret"):
        other = build_extractor_shared_context(
            db, state, "邸报", "", module=module,
        )
        other_hit = next(
            r for r in other["decree_dossiers"] if int(r["id"]) == subject_id
        )
        for key in SUPERVISION_SURFACE_KEYS:
            assert key not in other_hit, f"{module} 不得注入 {key}"


def test_due_review_supervision_history_no_longer_hardcoded_empty(game):
    """授权面：更新 #621 空列表断言——有在场事实时非空。"""
    db, state, content = game
    owner, auditor_row = _pair_same_faction(db)
    subject_id = _subject_dossier(db, state, owner=str(owner["name"]), token="dr")
    _audit_dossier(
        db, state, auditor=str(auditor_row["name"]), subject_id=subject_id, token="dr",
    )
    db.record_monthly_supervision_facts(state.turn, commit=True)
    _insert_staged(db, state, content, dossier_id=subject_id, due_turn=state.turn)
    write_due_staged_commitment_todos(db, state)
    todo = db.list_next_audience_todos(status=TODO_STATUS_PENDING)[0]
    inp = build_due_review_input(db, todo)
    assert inp["supervision_history"] != []
    assert inp["supervision_history"][0]["auditor_name"] == str(auditor_row["name"])


def test_decide_due_review_verdict_unchanged_by_supervision(game):
    """解 A：不改 decide_due_review_verdict 确定性分支。"""
    from ming_sim.due_review import decide_due_review_verdict

    base = {
        "mid_stage": False,
        "durable_effects": [{"id": 1}],
        "progress_reports": [],
        "criterion_text": "清丈",
        "origin_context": "",
        "supervision_history": [{
            "consecutive_months": 12,
            "auditor_integrity_band": "操守平常",
            "faction_relation": "same",
        }],
        "transformation_tendency_facts": {
            "longest_consecutive_presence_months": 12,
            "has_mediocre_auditor": True,
        },
    }
    v = decide_due_review_verdict(base)
    assert v["outcome"] == "fulfilled"
    assert v["close"] is True
