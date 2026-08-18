"""#627 政敌检举轨——真伪底与带私货审计（ID-12）。

Seams:
- supervision.is_reported_actual_fork（fork 判据单源）
- GameDB.read_dossier_fork_state / trigger_faction_denunciations
- decree pre_settle 邸报前涌现缝（#625 同缝）
- faction_denunciations 独立载体（明文不写 loophole_exposures）
- compose_denunciation_origin + render_denunciation_memorial
- SUPERVISION_BANNED_PLAYER_TOKENS 单源扩展
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from ming_sim.db import GameDB
from ming_sim.supervision import (
    DENUNCIATION_ALLOWED_COLS,
    DENUNCIATION_ORIGIN_BASE,
    DENUNCIATION_TABLE,
    ORIGIN_MARK_DENUNCIATION_FALSE,
    ORIGIN_MARK_DENUNCIATION_TRUE,
    SUPERVISION_BANNED_PLAYER_TOKENS,
    assert_no_banned_tokens,
    compose_denunciation_origin,
    denunciation_quota,
    faction_conflict_intensity,
    faction_relation,
    is_reported_actual_fork,
    origin_has_mark,
    render_denunciation_memorial,
)
from tests.test_dossier_reported_progress_619 import _world_fingerprint


_REPO = Path(__file__).resolve().parents[1]


# ── helpers ───────────────────────────────────────────────────────


def _chars_by_faction(db) -> dict[str, list]:
    rows = db.conn.execute(
        "SELECT name, faction FROM characters "
        "WHERE status='active' AND COALESCE(faction,'') NOT IN "
        "('','流寇','后金','宗室','嫔妃','宠妃','中宫','蒙古','朝鲜') "
        "ORDER BY name"
    ).fetchall()
    by_f: dict[str, list] = {}
    for row in rows:
        by_f.setdefault(str(row["faction"]), []).append(row)
    return by_f


def _pair_enemy(db):
    by_f = _chars_by_faction(db)
    facs = [f for f, rs in by_f.items() if rs]
    assert len(facs) >= 2
    return by_f[facs[0]][0], by_f[facs[1]][0]


def _enemy_faction_with_accusers(db, subject_faction: str, *, min_n: int = 3) -> str:
    """选与 subject 敌对且在朝人数够 quota 的派系。"""
    by_f = _chars_by_faction(db)
    ranked = sorted(
        (
            (fac, rows)
            for fac, rows in by_f.items()
            if faction_relation(fac, subject_faction) == "enemy"
        ),
        key=lambda item: len(item[1]),
        reverse=True,
    )
    assert ranked, "无敌对派系"
    fac, rows = ranked[0]
    assert len(rows) >= min_n, f"敌派 {fac} 仅 {len(rows)} 人，不足 {min_n}"
    return fac


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
    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing' WHERE id=?", (did,),
    )
    db.conn.commit()
    return did


def _make_forked(db, state, dossier_id: int, *, token: str = "fork"):
    """奏报 + 旨外实况 → fork 单源读端为真。"""
    db.record_dossier_progress(
        dossier_id, state.turn, "已竣", f"奏称{token}已完",
        is_terminal=False, commit=True,
    )
    db.record_issue_economy_move(
        state, "国库", 5, "浮收", "借旨行私",
        origin_ref=f"dossier:{dossier_id}", beyond_intent=True, commit=True,
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET execution_outcome='transformed' WHERE id=?",
        (dossier_id,),
    )
    db.conn.commit()


def _make_transformed_no_fork(db, state, dossier_id: int):
    """变形但无奏报分叉（无私货/无旨外）——fork 读端为假。"""
    db.conn.execute(
        "UPDATE decree_dossiers SET execution_outcome='transformed' WHERE id=?",
        (dossier_id,),
    )
    db.conn.commit()


def _zero_all_faction_leverage(db):
    """把全部派系 leverage 压到 0（经 offset 注入，读端立即可见）。"""
    rows = db.conn.execute("SELECT name, leverage FROM factions").fetchall()
    for row in rows:
        name = str(row["name"])
        lev = int(row["leverage"] or 0)
        if lev != 0:
            db.adjust_factions({name: {"leverage": -lev}})
        # 非白名单可能仍残留；兜底直写
        db.conn.execute(
            "UPDATE factions SET leverage=0 WHERE name=?", (name,),
        )
    db.conn.commit()


def _set_faction_leverage(db, faction: str, target: int):
    _zero_all_faction_leverage(db)
    cur = int(db.faction_leverage(faction))
    delta = int(target) - cur
    if delta:
        db.adjust_factions({faction: {"leverage": delta}})
    # 兜底：保证读端为目标值（测试盘面控制）
    db.conn.execute(
        "UPDATE factions SET leverage=? WHERE name=?", (int(target), faction),
    )
    db.conn.commit()


def _table_cols(db, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in db.conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    }


# ── unit pure ─────────────────────────────────────────────────────


def test_fork_predicate_pure_and_single_source_expression():
    assert is_reported_actual_fork(
        reported_bands=["已竣"], beyond_intent=True, execution_outcome="executing",
    ) is True
    assert is_reported_actual_fork(
        reported_bands=["已竣"], beyond_intent=False, execution_outcome="transformed",
    ) is True
    assert is_reported_actual_fork(
        reported_bands=["已竣"], beyond_intent=False, execution_outcome="fulfilled",
    ) is False
    assert is_reported_actual_fork(
        reported_bands=[], beyond_intent=True, execution_outcome="transformed",
    ) is False

    # 结构断言：fork 判据表达式全库仅一处（supervision.py）
    needle = 'outcome not in {"", "fulfilled", "executing"}'
    hits: list[Path] = []
    for path in (_REPO / "ming_sim").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if needle in text:
            hits.append(path.relative_to(_REPO))
    assert hits == [Path("ming_sim/supervision.py")], hits

    # 定义唯一
    src = (_REPO / "ming_sim" / "supervision.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    defs = [
        n.name for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "is_reported_actual_fork"
    ]
    assert defs == ["is_reported_actual_fork"]


def test_intensity_quota_and_render_ac2():
    assert faction_conflict_intensity(relation="same", enemy_leverage=80) == 0
    assert faction_conflict_intensity(relation="enemy", enemy_leverage=80) == 80
    assert faction_conflict_intensity(
        relation="enemy", enemy_leverage=50, enemy_satisfaction=0,
    ) == 60  # +10 anger
    assert denunciation_quota(0) == 0
    assert denunciation_quota(1) == 1
    assert denunciation_quota(40) == 2
    assert denunciation_quota(70) == 3

    # AC2：真/伪同一渲染函数，剔除案由变量后串相等
    true_text = render_denunciation_memorial(
        accuser_name="温体仁", subject_name="钱谦益", case_summary="CASE_X",
    )
    false_text = render_denunciation_memorial(
        accuser_name="温体仁", subject_name="钱谦益", case_summary="CASE_Y",
    )
    assert true_text != false_text  # 案由不同则全文不同
    stripped_t = true_text.replace("CASE_X", "")
    stripped_f = false_text.replace("CASE_Y", "")
    assert stripped_t == stripped_f

    # 同案由 → 全文相等（同一话术机器）
    assert render_denunciation_memorial(
        accuser_name="A", subject_name="B", case_summary="清丈",
    ) == render_denunciation_memorial(
        accuser_name="A", subject_name="B", case_summary="清丈",
    )

    o_true = compose_denunciation_origin(is_true=True)
    o_false = compose_denunciation_origin(is_true=False)
    assert o_true.startswith(DENUNCIATION_ORIGIN_BASE)
    assert origin_has_mark(o_true, ORIGIN_MARK_DENUNCIATION_TRUE)
    assert origin_has_mark(o_false, ORIGIN_MARK_DENUNCIATION_FALSE)
    assert not origin_has_mark(o_true, ORIGIN_MARK_DENUNCIATION_FALSE)


# ── AC1 真检举 ────────────────────────────────────────────────────


def test_ac1_true_denunciation_points_to_forked_dossier(game):
    db, state, _content = game
    subject, _enemy_char = _pair_enemy(db)
    subject_name = str(subject["name"])
    subject_faction = str(subject["faction"])
    enemy_faction = _enemy_faction_with_accusers(db, subject_faction, min_n=1)
    # 抬高敌派 leverage，压低其它
    _set_faction_leverage(db, enemy_faction, 75)

    did = _subject_dossier(db, state, owner=subject_name, token="true1")
    _make_forked(db, state, did, token="true1")
    fork_state = db.read_dossier_fork_state(did)
    assert fork_state["fork"] is True

    hits = db.trigger_faction_denunciations(state, commit=True)
    assert hits, "敌派对分叉承办人须产检举"
    true_hits = [h for h in hits if h.get("is_true")]
    assert true_hits, "须有真检举"
    hit = true_hits[0]
    assert int(hit["target_dossier_id"]) == did
    assert origin_has_mark(hit["origin"], ORIGIN_MARK_DENUNCIATION_TRUE)
    assert hit["payload"].get("fork") is True
    assert "fork_exposure" in hit["payload"]
    assert hit["payload"]["fork_exposure"]["fork"] is True

    # 读端列表一致
    rows = db.list_faction_denunciations(turn=state.turn, target_dossier_id=did)
    assert any(origin_has_mark(r["origin"], ORIGIN_MARK_DENUNCIATION_TRUE) for r in rows)


# ── AC2 私货 + 同渲染 ─────────────────────────────────────────────


def test_ac2_false_denunciation_and_same_render_function(game):
    db, state, _content = game
    subject, _ = _pair_enemy(db)
    subject_name = str(subject["name"])
    subject_faction = str(subject["faction"])
    enemy_faction = _enemy_faction_with_accusers(db, subject_faction, min_n=3)
    _set_faction_leverage(db, enemy_faction, 80)  # quota≥3 → 真+伪

    did = _subject_dossier(db, state, owner=subject_name, token="mix")
    _make_forked(db, state, did, token="mix")
    hits = db.trigger_faction_denunciations(state, commit=True)
    false_hits = [h for h in hits if not h.get("is_true")]
    assert false_hits, "高烈度须夹带私货检举"
    for h in false_hits:
        assert origin_has_mark(h["origin"], ORIGIN_MARK_DENUNCIATION_FALSE)
        assert "fork_exposure" not in h["payload"]

    # 真/伪 memorial 走同一渲染：剔除案由后相等
    true_m = next(h["memorial_text"] for h in hits if h.get("is_true"))
    false_m = false_hits[0]["memorial_text"]
    # 案由相同（同源 decree_text）→ 全文应能由同一模板解释
    case = "清丈mix"[:24]
    assert true_m == render_denunciation_memorial(
        accuser_name=next(h["accuser_name"] for h in hits if h.get("is_true")),
        subject_name=subject_name,
        case_summary=case if len("清丈mix") <= 24 else "清丈mix"[:24],
    )
    # 换案由变量后模板壳相等
    a = render_denunciation_memorial(
        accuser_name="甲", subject_name="乙", case_summary="案甲",
    )
    b = render_denunciation_memorial(
        accuser_name="甲", subject_name="乙", case_summary="案乙",
    )
    assert a.replace("案甲", "") == b.replace("案乙", "")


def test_ac2_false_only_on_transformed_without_fork(game):
    db, state, _content = game
    subject, _ = _pair_enemy(db)
    subject_name = str(subject["name"])
    subject_faction = str(subject["faction"])
    enemy_faction = _enemy_faction_with_accusers(db, subject_faction, min_n=1)
    _set_faction_leverage(db, enemy_faction, 50)

    did = _subject_dossier(db, state, owner=subject_name, token="nofork")
    _make_transformed_no_fork(db, state, did)
    assert db.read_dossier_fork_state(did)["fork"] is False

    hits = db.trigger_faction_denunciations(state, commit=True)
    assert hits, "变形无分叉仍可产私货检举"
    assert all(not h.get("is_true") for h in hits)
    assert all(
        origin_has_mark(h["origin"], ORIGIN_MARK_DENUNCIATION_FALSE) for h in hits
    )


# ── AC3 暴露载体 + 负向 ───────────────────────────────────────────


def test_ac3_exposure_on_entry_not_loophole_table_world_unchanged(game):
    db, state, _content = game
    subject, _ = _pair_enemy(db)
    subject_name = str(subject["name"])
    subject_faction = str(subject["faction"])
    enemy_faction = _enemy_faction_with_accusers(db, subject_faction, min_n=1)
    _set_faction_leverage(db, enemy_faction, 55)

    did = _subject_dossier(db, state, owner=subject_name, token="exp")
    _make_forked(db, state, did, token="exp")

    # 世界指纹：trigger 前已有旨外 move；再拍指纹后只跑检举
    fp_before = _world_fingerprint(db)
    loophole_before = db.list_loophole_exposures(did)
    # 查案差务计数（action_type 含密查/查访类）
    inv_before = db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers "
        "WHERE action_type IN ('investigation','密查','查访')"
    ).fetchone()["n"]
    dossier_n_before = db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers"
    ).fetchone()["n"]

    hits = db.trigger_faction_denunciations(state, commit=True)
    true_hits = [h for h in hits if h.get("is_true")]
    assert true_hits
    exposure = true_hits[0]["payload"].get("fork_exposure")
    assert exposure and exposure.get("fork") is True

    # 明文不写 loophole_exposures
    assert db.list_loophole_exposures(did) == loophole_before
    # 不产查案差务
    inv_after = db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers "
        "WHERE action_type IN ('investigation','密查','查访')"
    ).fetchone()["n"]
    assert inv_after == inv_before
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers"
    ).fetchone()["n"] == dossier_n_before

    # 世界状态零变化（钱粮/区域/军队）
    assert _world_fingerprint(db) == fp_before

    # 玩家面可见 memorial；公开见闻有条目
    memorials = [h["memorial_text"] for h in hits]
    assert all(memorials)
    items = db.knowledge_items_for_turn(state.turn)
    bodies = [
        str(it.get("body") or "")
        for it in items
        if isinstance(it, dict)
    ]
    assert any(m in bodies for m in memorials)

    # schema 白名单
    assert DENUNCIATION_TABLE in {
        r[0] for r in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert _table_cols(db, DENUNCIATION_TABLE) == DENUNCIATION_ALLOWED_COLS


# ── AC4 烈度单调 + restore ────────────────────────────────────────


def test_ac4_intensity_monotone_and_restore(game, tmp_path, content):
    db, state, _content = game
    subject, _ = _pair_enemy(db)
    subject_name = str(subject["name"])
    subject_faction = str(subject["faction"])
    enemy_faction = _enemy_faction_with_accusers(db, subject_faction, min_n=3)

    did = _subject_dossier(db, state, owner=subject_name, token="mono")
    _make_forked(db, state, did, token="mono")

    # 低烈度盘面
    _set_faction_leverage(db, enemy_faction, 20)
    low_hits = db.trigger_faction_denunciations(state, commit=True)
    low_n = len([
        h for h in low_hits if h.get("accuser_faction") == enemy_faction
    ])
    assert low_n >= 1

    # 清本 turn 检举再跑高烈度（同 turn 对照）
    db.conn.execute(
        "DELETE FROM faction_denunciations WHERE turn=?", (state.turn,),
    )
    db.conn.execute(
        "DELETE FROM character_knowledge_events WHERE turn=? AND kind=?",
        (state.turn, "faction_denunciation"),
    )
    db.conn.commit()

    _set_faction_leverage(db, enemy_faction, 80)
    high_hits = db.trigger_faction_denunciations(state, commit=True)
    high_n = len([
        h for h in high_hits if h.get("accuser_faction") == enemy_faction
    ])
    assert high_n > low_n, f"高 leverage 条数须单调：low={low_n} high={high_n}"

    expected = db.list_faction_denunciations(turn=state.turn)
    backup = tmp_path / "restore-627.db"
    db.backup_to(str(backup))
    db.close()

    restored = GameDB(str(backup), content=content)
    try:
        got = restored.list_faction_denunciations(turn=state.turn)
        assert got == expected
        # restore 后同 turn 重跑不双计
        again = restored.trigger_faction_denunciations(state, commit=True)
        assert again == []
        assert restored.list_faction_denunciations(turn=state.turn) == expected
    finally:
        restored.close()


# ── AC5 禁词 + #622 读端改调 ──────────────────────────────────────


def test_ac5_banned_tokens_and_622_uses_single_fork_source(game):
    db, state, _content = game
    subject, _ = _pair_enemy(db)
    subject_name = str(subject["name"])
    subject_faction = str(subject["faction"])
    enemy_faction = _enemy_faction_with_accusers(db, subject_faction, min_n=1)
    _set_faction_leverage(db, enemy_faction, 60)

    did = _subject_dossier(db, state, owner=subject_name, token="ban")
    _make_forked(db, state, did, token="ban")
    hits = db.trigger_faction_denunciations(state, commit=True)
    assert hits
    for h in hits:
        assert_no_banned_tokens(h["memorial_text"], surface="memorial_text")

    items = db.knowledge_items_for_turn(state.turn)
    for it in items:
        if not isinstance(it, dict):
            continue
        for key in ("title", "body", "text", "summary", "content"):
            if key in it:
                assert_no_banned_tokens(it.get(key), surface="knowledge_items")

    for token in (
        "denunciation_true", "denunciation_false",
        "faction_conflict_intensity", "fork_exposure", "veracity",
    ):
        assert token in SUPERVISION_BANNED_PLAYER_TOKENS

    # #622 读端改调 public fork：稽核链信号 fork 与 read_dossier_fork_state 一致
    actor = subject_name
    audit_order = db.create_secret_order(
        state, actor, "密查清丈", "逐月密奏", ["稽核"], deadline_months=4,
    )
    audit_dossier = int(db.get_dossier_for_secret_order(audit_order)["id"])
    db.add_dossier_links(
        audit_dossier,
        [{"target_dossier_id": did, "relation_type": "稽核", "note": "密查"}],
    )
    nudges = db.list_monthly_dossier_progress_nudges()
    audit_nudge = next(n for n in nudges if int(n["dossier_id"]) == audit_dossier)
    signals = audit_nudge["audit_fork_signals"]
    hit = next(s for s in signals if int(s["target_dossier_id"]) == did)
    assert hit["fork"] is True
    assert hit["fork"] == db.read_dossier_fork_state(did)["fork"]


def test_emergence_seam_wired_in_pre_settle_source():
    """产生缝=邸报前涌现缝：decree.pre_settle 源码挂 trigger_faction_denunciations。"""
    src = (_REPO / "ming_sim" / "decree.py").read_text(encoding="utf-8")
    assert "trigger_faction_denunciations" in src
    assert "trigger_supervision_countermeasures" in src
    # 同函数体内、auto_trigger 之后
    tree = ast.parse(src)
    fn = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "pre_settle"
    )
    body = ast.get_source_segment(src, fn) or ""
    assert "trigger_faction_denunciations" in body
    assert body.index("auto_trigger_seed_issues") < body.index(
        "trigger_faction_denunciations"
    )
