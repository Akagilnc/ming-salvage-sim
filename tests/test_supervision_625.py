"""#625 / ADR 0077 钝化事实底＋人身条件化判官口径。

Seams:
- dossier_supervision_presence / dossier_loophole_exposures 事实表
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




# ── AC1 事实底 ────────────────────────────────────────────────────





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
