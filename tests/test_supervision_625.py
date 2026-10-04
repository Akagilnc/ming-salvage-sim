"""#625 / ADR 0077 钝化事实底＋人身条件化判官口径。

Seams:
- dossier_supervision_presence / dossier_loophole_exposures 事实表
- record_monthly_supervision_presence（与 grant recon 同段）
- build_due_review_input.supervision_history
- 督办复核的监督事实观察槽
- auto_trigger 涌现缝反制 issue

同派／敌派与月报行动声明的真实过月入口在 test_month_chain_1847。
"""

from __future__ import annotations

import sqlite3

import pytest

from ming_sim.db import GameDB
from ming_sim.decree import pre_settle
from ming_sim.models import TurnPhase
from tests.test_due_review_621 import _settle_empty_month
from ming_sim.due_review import (
    apply_pending_due_reviews,
    build_due_review_input,
)
from ming_sim.staged_commitment import (
    TODO_STATUS_PENDING,
    write_due_staged_commitment_todos,
)
from ming_sim.supervision import (
    EMPTY_TRANSFORMATION_TENDENCY_FACTS,
    EXPOSURE_TABLE,
    FORBIDDEN_DULLING_COL_FRAGMENTS,
    PRESENCE_TABLE,
    SUPERVISION_RELATION,
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


def _table_cols(db, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in db.conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    }


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
    # 全库不得长出钝化数值列。
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
    db.record_monthly_supervision_presence(turn, commit=True)
    db.record_monthly_supervision_presence(turn, commit=True)  # 幂等不双计

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
        restored.record_monthly_supervision_presence(turn, commit=True)
        assert len(restored.list_supervision_presence(subject_id)) == 1
    finally:
        restored.close()


def test_ac1_settle_segment_writes_presence(game, monkeypatch):
    """事实行随真实过月 grant recon 同段写入。"""
    db, state, content = game
    owner, _ = _pair_same_faction(db)
    auditor = _upright_and_mediocre(db)[1]
    subject_id = _subject_dossier(db, state, owner=str(owner["name"]), token="seg")
    _audit_dossier(
        db, state, auditor=str(auditor["name"]), subject_id=subject_id, token="seg",
    )
    before_turn = int(state.turn)
    before = len(db.list_supervision_presence(subject_id))
    _settle_empty_month(db, state, content, monkeypatch)
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
    for offset in range(12):  # 原硬门月数门（#1895 退役）只为铺满在场事实
        db.record_monthly_supervision_presence(base_turn + offset, commit=True)

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
    # 观察槽键集＝事实包真源。不在整包序列化文本里扫词，免得稽核人姓名撞上禁词。
    assert set(tend_m) == set(EMPTY_TRANSFORMATION_TENDENCY_FACTS)
    assert set(tend_u) == set(EMPTY_TRANSFORMATION_TENDENCY_FACTS)

    # 执行格判词观察槽：督办复核读取监督事实
    _insert_staged(db, state, content, dossier_id=sub_m, due_turn=state.turn)
    write_due_staged_commitment_todos(db, state)
    todo = db.list_next_audience_todos(status=TODO_STATUS_PENDING)[0]
    inp = build_due_review_input(db, todo)
    assert inp["supervision_history"]
    assert inp["transformation_tendency_facts"]["longest_consecutive_presence_months"] >= 1

    # 抓手与事实素材照留：连续在场月数、稽核人派系操守定性仍可读可持久。
    assert tend_u["has_upright_auditor"] is True
    assert surface_u["supervision_history"], "监督在场事实必须仍可供料"
    # 真实前括号：退役硬门若被装回 pre_settle，这里会立反制局势或调用失败。
    state.turn_phase = TurnPhase.SUMMONING.value
    db.save_state(state)
    pre_settle(state, db, content=content)
    assert db.find_any_issue_by_origin(
        "supervision_countermeasure",
        f"auditor:{upright['name']}:dossier:{sub_u}",
    ) is None


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


def test_due_review_supervision_history_no_longer_hardcoded_empty(game):
    """有在场事实时监督史非空；到期消费后执行格只跟实况账。"""
    db, state, content = game
    owner, auditor_row = _pair_same_faction(db)
    subject_id = _subject_dossier(db, state, owner=str(owner["name"]), token="dr")
    _audit_dossier(
        db, state, auditor=str(auditor_row["name"]), subject_id=subject_id, token="dr",
    )
    db.record_monthly_supervision_presence(state.turn, commit=True)
    db.record_dossier_progress(
        subject_id, state.turn, "在办", "表报已陈，实绩未充",
        is_terminal=False, commit=True,
    )
    _insert_staged(db, state, content, dossier_id=subject_id, due_turn=state.turn)
    write_due_staged_commitment_todos(db, state)
    todo = db.list_next_audience_todos(status=TODO_STATUS_PENDING)[0]
    inp = build_due_review_input(db, todo)
    assert inp["supervision_history"] != []
    assert inp["supervision_history"][0]["auditor_name"] == str(auditor_row["name"])
    db.conn.execute(
        "UPDATE next_audience_todos SET created_turn=?",
        (int(state.turn) - 1,),
    )
    db.conn.commit()
    applied = apply_pending_due_reviews(db, state, commit=True)
    assert applied
    dossier = db.get_decree_dossier(subject_id)
    assert dossier["execution_outcome"] == "degraded"
    assert dossier["status"] == "closed"
