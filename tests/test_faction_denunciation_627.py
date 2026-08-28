"""#627 政敌检举轨——真伪底与带私货审计（ID-12，r4 宪法版）。

引擎三职：供事实（注入既有叙事 LLM 步）/ 承接落库（clamp）/ 真伪底派生。
禁：烈度门/quota/文字模板（P6/P7）。

Seams:
- supervision.is_reported_actual_fork（fork 判据单源）
- GameDB.read_dossier_fork_state / build_faction_denunciation_facts
- GameDB.accept_faction_denunciations（结构化承接）
- compose_denunciation_origin + derive_denunciation_is_true
- SUPERVISION_BANNED_PLAYER_TOKENS 单源扩展
- build_simulator_payload 事实注入
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from ming_sim.db import GameDB
from ming_sim.simulation import build_simulator_payload
from ming_sim.supervision import (
    DENUNCIATION_ALLOWED_COLS,
    DENUNCIATION_ORIGIN_BASE,
    DENUNCIATION_TABLE,
    ORIGIN_MARK_DENUNCIATION_FALSE,
    ORIGIN_MARK_DENUNCIATION_TRUE,
    SUPERVISION_BANNED_PLAYER_TOKENS,
    assert_no_banned_tokens,
    compose_denunciation_origin,
    derive_denunciation_is_true,
    faction_relation,
    is_reported_actual_fork,
    origin_has_mark,
)
from tests.test_dossier_reported_progress_619 import _world_fingerprint
from tests.dossier_test_helpers import investigation_covert_task


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
    # 找确为 enemy 的两派
    for i, fa in enumerate(facs):
        for fb in facs[i + 1:]:
            if faction_relation(fa, fb) == "enemy":
                return by_f[fa][0], by_f[fb][0]
    return by_f[facs[0]][0], by_f[facs[1]][0]


def _enemy_accuser(db, subject_faction: str) -> str:
    by_f = _chars_by_faction(db)
    for fac, rows in by_f.items():
        if faction_relation(fac, subject_faction) == "enemy" and rows:
            return str(rows[0]["name"])
    raise AssertionError("无敌对派系在朝人物")


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


def _escalate_fork(db, state, dossier_id: int, *, token: str = "esc"):
    """案情升级：再落一笔旨外恶果（actual_effect_count↑）。"""
    db.record_issue_economy_move(
        state, "国库", 3, "再浮收", f"升级{token}",
        origin_ref=f"dossier:{dossier_id}", beyond_intent=True, commit=True,
    )


def _table_cols(db, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in db.conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    }


def _scripted_entry(
    *,
    accuser: str,
    subject: str,
    dossier_id: int,
    body: str = "臣闻承办清丈有异状，请按问。",
) -> dict:
    return {
        "accuser_name": accuser,
        "subject_name": subject,
        "target_dossier_id": dossier_id,
        "memorial_text": body,
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

    src = (_REPO / "ming_sim" / "supervision.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    defs = [
        n.name for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "is_reported_actual_fork"
    ]
    assert defs == ["is_reported_actual_fork"]


def test_veracity_derivation_mechanical_and_origin_marks():
    """真伪底派生：分叉→真；无分叉→私货；origin 单源 mark。"""
    assert derive_denunciation_is_true(fork=True) is True
    assert derive_denunciation_is_true(fork=False) is False

    o_true = compose_denunciation_origin(is_true=True)
    o_false = compose_denunciation_origin(is_true=False)
    assert o_true.startswith(DENUNCIATION_ORIGIN_BASE)
    assert origin_has_mark(o_true, ORIGIN_MARK_DENUNCIATION_TRUE)
    assert origin_has_mark(o_false, ORIGIN_MARK_DENUNCIATION_FALSE)
    assert not origin_has_mark(o_true, ORIGIN_MARK_DENUNCIATION_FALSE)


def test_no_intensity_quota_template_symbols():
    """P6/P7：烈度门/quota/模板函数定义不得再存在（禁词表字符串除外）。"""
    src = (_REPO / "ming_sim" / "supervision.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    top_names = {
        n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assign_names: set[str] = set()
    for n in tree.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    assign_names.add(t.id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            assign_names.add(n.target.id)
    for banned in (
        "DENUNCIATION_INTENSITY_GATES",
        "denunciation_quota",
        "render_denunciation_memorial",
        "faction_conflict_intensity",
        "pick_denunciation_accusers",
    ):
        assert banned not in top_names, banned
        assert banned not in assign_names, banned
    db_src = (_REPO / "ming_sim" / "db.py").read_text(encoding="utf-8")
    db_tree = ast.parse(db_src)
    db_fns = {
        n.name for n in ast.walk(db_tree) if isinstance(n, ast.FunctionDef)
    }
    assert "render_denunciation_memorial" not in db_fns
    assert "denunciation_quota" not in db_fns
    assert "trigger_faction_denunciations" not in db_fns
    assert "accept_faction_denunciations" in db_fns
    assert "build_faction_denunciation_facts" in db_fns


# ── AC1 事实供给 ──────────────────────────────────────────────────


def test_ac1_fact_supply_four_classes_no_veracity_no_quota(game):
    db, state, _content = game
    subject, _ = _pair_enemy(db)
    subject_name = str(subject["name"])
    did = _subject_dossier(db, state, owner=subject_name, token="facts")
    _make_forked(db, state, did, token="facts")

    facts = db.build_faction_denunciation_facts()
    # 四类事实
    for key in (
        "forked_dossiers",
        "faction_enmities",
        "faction_situations",
        "character_personas",
    ):
        assert key in facts, key
        assert isinstance(facts[key], list), key

    assert any(int(d["dossier_id"]) == did for d in facts["forked_dossiers"])
    assert facts["faction_enmities"], "须有敌对关系事实"
    assert facts["faction_situations"], "须有派系处境定性档"
    assert facts["character_personas"], "须有人物个性"

    # 处境/个性为定性档，非裸分
    for sit in facts["faction_situations"]:
        assert "leverage_band" in sit and "satisfaction_band" in sit
        assert "leverage" not in sit
        assert "satisfaction" not in sit
    for persona in facts["character_personas"]:
        assert "integrity_band" in persona

    # 输入不携真伪位、无 quota
    blob = json.dumps(facts, ensure_ascii=False)
    for banned in (
        "denunciation_true", "denunciation_false", "is_true", "veracity",
        "quota", "denunciation_quota", "intensity", "faction_conflict_intensity",
    ):
        assert banned not in blob, banned

    # 叙事步输入构造：simulator payload 含此键且同约束
    payload = build_simulator_payload(state, db, decree_text="试", previous_narrative="")
    assert "faction_denunciation_facts" in payload
    injected = payload["faction_denunciation_facts"]
    assert set(injected) >= {
        "forked_dossiers", "faction_enmities",
        "faction_situations", "character_personas",
    }
    inj_blob = json.dumps(injected, ensure_ascii=False)
    for banned in ("denunciation_true", "denunciation_false", "quota", "veracity"):
        assert banned not in inj_blob, banned


# ── AC2 承接与 clamp ──────────────────────────────────────────────


def test_ac2_scripted_accept_and_clamp(game):
    db, state, _content = game
    subject, _ = _pair_enemy(db)
    subject_name = str(subject["name"])
    subject_faction = str(subject["faction"])
    accuser = _enemy_accuser(db, subject_faction)

    did = _subject_dossier(db, state, owner=subject_name, token="acc")
    _make_forked(db, state, did, token="acc")

    body = f"{accuser}奏：{subject_name}清丈有私，请皇上按问。"
    hits = db.accept_faction_denunciations(
        state,
        [_scripted_entry(
            accuser=accuser, subject=subject_name, dossier_id=did, body=body,
        )],
        commit=True,
    )
    assert len(hits) == 1
    hit = hits[0]
    assert hit["accuser_name"] == accuser
    assert int(hit["target_dossier_id"]) == did
    assert hit["memorial_text"] == body
    assert origin_has_mark(hit["origin"], ORIGIN_MARK_DENUNCIATION_TRUE)

    rows = db.list_faction_denunciations(turn=state.turn, target_dossier_id=did)
    assert len(rows) == 1
    assert rows[0]["memorial_text"] == body

    # 所指案卷不存在 → 拒
    missing = db.accept_faction_denunciations(
        state,
        [_scripted_entry(
            accuser=accuser, subject=subject_name, dossier_id=9_999_999,
            body="妄指无案",
        )],
        commit=True,
    )
    assert missing == []

    # 检举人不在场 → 拒
    ghost = db.accept_faction_denunciations(
        state,
        [_scripted_entry(
            accuser="不存在之人甲乙丙", subject=subject_name, dossier_id=did,
            body="鬼影弹章",
        )],
        commit=True,
    )
    assert ghost == []


# ── AC3 真伪底派生 ────────────────────────────────────────────────


def test_ac3_veracity_true_and_false_from_fork(game):
    db, state, _content = game
    subject, _ = _pair_enemy(db)
    subject_name = str(subject["name"])
    subject_faction = str(subject["faction"])
    accuser = _enemy_accuser(db, subject_faction)

    did_true = _subject_dossier(db, state, owner=subject_name, token="vt")
    _make_forked(db, state, did_true, token="vt")
    assert db.read_dossier_fork_state(did_true)["fork"] is True

    did_false = _subject_dossier(db, state, owner=subject_name, token="vf")
    _make_transformed_no_fork(db, state, did_false)
    assert db.read_dossier_fork_state(did_false)["fork"] is False

    hits = db.accept_faction_denunciations(
        state,
        [
            _scripted_entry(
                accuser=accuser, subject=subject_name, dossier_id=did_true,
                body="真分叉弹章",
            ),
            _scripted_entry(
                accuser=accuser, subject=subject_name, dossier_id=did_false,
                body="无分叉私货弹章",
            ),
        ],
        commit=True,
    )
    by_did = {int(h["target_dossier_id"]): h for h in hits}
    assert origin_has_mark(by_did[did_true]["origin"], ORIGIN_MARK_DENUNCIATION_TRUE)
    assert by_did[did_true]["is_true"] is True
    assert by_did[did_true]["payload"].get("fork") is True
    assert "fork_exposure" in by_did[did_true]["payload"]

    assert origin_has_mark(by_did[did_false]["origin"], ORIGIN_MARK_DENUNCIATION_FALSE)
    assert by_did[did_false]["is_true"] is False
    assert "fork_exposure" not in by_did[did_false]["payload"]


# ── AC4 重复语义三断言 + restore ──────────────────────────────────


def test_ac4_dedup_upgrade_closed_and_restore(game, tmp_path, content):
    db, state, _content = game
    subject, _ = _pair_enemy(db)
    subject_name = str(subject["name"])
    subject_faction = str(subject["faction"])
    accuser = _enemy_accuser(db, subject_faction)

    did = _subject_dossier(db, state, owner=subject_name, token="dedup")
    _make_forked(db, state, did, token="dedup")
    entry = _scripted_entry(
        accuser=accuser, subject=subject_name, dossier_id=did, body="初弹",
    )

    first = db.accept_faction_denunciations(state, [entry], commit=True)
    assert len(first) == 1

    # 同 turn 同键二次拒（去重由承接查询单源，非 UNIQUE）
    same_turn_dup = db.accept_faction_denunciations(state, [entry], commit=True)
    assert same_turn_dup == []
    assert len(db.list_faction_denunciations(target_dossier_id=did)) == 1

    # 同 turn 案情升级可再落（禁 UNIQUE(turn,...)：否则 IntegrityError）
    _escalate_fork(db, state, did, token="same-turn")
    same_turn_up = db.accept_faction_denunciations(
        state,
        [_scripted_entry(
            accuser=accuser, subject=subject_name, dossier_id=did, body="同回合升级再弹",
        )],
        commit=True,
    )
    assert len(same_turn_up) == 1
    assert len(db.list_faction_denunciations(target_dossier_id=did)) == 2

    # 同人同案同真伪类跨 turn 亦拒（去重键不含 turn）
    state.turn = int(state.turn) + 1
    db.save_state(state)
    second = db.accept_faction_denunciations(state, [entry], commit=True)
    assert second == []
    assert len(db.list_faction_denunciations(target_dossier_id=did)) == 2

    # 跨 turn 案情再升级可再落
    _escalate_fork(db, state, did, token="up")
    upgraded = db.accept_faction_denunciations(
        state,
        [_scripted_entry(
            accuser=accuser, subject=subject_name, dossier_id=did, body="升级再弹",
        )],
        commit=True,
    )
    assert len(upgraded) == 1
    assert len(db.list_faction_denunciations(target_dossier_id=did)) == 3

    # closed 案卷拒
    did_closed = _subject_dossier(db, state, owner=subject_name, token="cls")
    _make_forked(db, state, did_closed, token="cls")
    db.conn.execute(
        "UPDATE decree_dossiers SET status='closed' WHERE id=?", (did_closed,),
    )
    db.conn.commit()
    closed_hits = db.accept_faction_denunciations(
        state,
        [_scripted_entry(
            accuser=accuser, subject=subject_name, dossier_id=did_closed,
            body="结案勿弹",
        )],
        commit=True,
    )
    assert closed_hits == []

    # restore 无损接续
    expected = db.list_faction_denunciations()
    backup = tmp_path / "restore-627.db"
    db.backup_to(str(backup))
    db.close()

    restored = GameDB(str(backup), content=content)
    try:
        got = restored.list_faction_denunciations()
        assert got == expected
        # restore 后同键重跑不双计
        again = restored.accept_faction_denunciations(
            state,
            [_scripted_entry(
                accuser=accuser, subject=subject_name, dossier_id=did, body="升级再弹",
            )],
            commit=True,
        )
        assert again == []
        assert restored.list_faction_denunciations() == expected
    finally:
        restored.close()


# ── AC5 零模板 + banned tokens + #622 单源 + 暴露载体 ─────────────


def test_ac5_zero_template_banned_tokens_exposure_and_622(game):
    db, state, _content = game
    subject, _ = _pair_enemy(db)
    subject_name = str(subject["name"])
    subject_faction = str(subject["faction"])
    accuser = _enemy_accuser(db, subject_faction)

    did = _subject_dossier(db, state, owner=subject_name, token="ban")
    _make_forked(db, state, did, token="ban")

    fp_before = _world_fingerprint(db)
    loophole_before = db.list_loophole_exposures(did)
    knowledge_n_before = db.conn.execute(
        "SELECT COUNT(*) AS n FROM character_knowledge_events"
    ).fetchone()["n"]
    inv_before = db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers "
        "WHERE action_type IN ('investigation','密查','查访')"
    ).fetchone()["n"]
    dossier_n_before = db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers"
    ).fetchone()["n"]

    body = f"{accuser}疏称{subject_name}清丈借旨行私，请按问以肃官箴。"
    hits = db.accept_faction_denunciations(
        state,
        [_scripted_entry(
            accuser=accuser, subject=subject_name, dossier_id=did, body=body,
        )],
        commit=True,
    )
    assert hits
    for h in hits:
        assert_no_banned_tokens(h["memorial_text"], surface="memorial_text")
        # 正文即 LLM/scripted 原文，非引擎模板壳
        assert h["memorial_text"] == body

    # 暴露落条目自身，不写 loophole、不回注知识轨、不改世界状态
    assert hits[0]["payload"].get("fork_exposure", {}).get("fork") is True
    assert db.list_loophole_exposures(did) == loophole_before
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM character_knowledge_events"
    ).fetchone()["n"] == knowledge_n_before
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers "
        "WHERE action_type IN ('investigation','密查','查访')"
    ).fetchone()["n"] == inv_before
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers"
    ).fetchone()["n"] == dossier_n_before
    assert _world_fingerprint(db) == fp_before

    # 反向：知识轨无检举事件（呈现由 simulator 事件章/探子回报，非引擎回注）
    items = db.knowledge_items_for_turn(state.turn)
    bodies = [
        str(it.get("body") or "")
        for it in items
        if isinstance(it, dict)
    ]
    assert body not in bodies
    for it in items:
        if not isinstance(it, dict):
            continue
        blob = " ".join(
            str(it.get(k) or "")
            for k in ("title", "body", "text", "summary", "content", "kind", "source_id")
        )
        assert "检举" not in blob
        assert "faction_denunciation" not in blob
        for key in ("title", "body", "text", "summary", "content"):
            if key in it:
                assert_no_banned_tokens(it.get(key), surface="knowledge_items")

    for token in (
        "denunciation_true", "denunciation_false",
        "fork_exposure", "veracity",
        "denunciation_quota", "faction_conflict_intensity",
    ):
        assert token in SUPERVISION_BANNED_PLAYER_TOKENS

    # schema 白名单
    assert DENUNCIATION_TABLE in {
        r[0] for r in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert _table_cols(db, DENUNCIATION_TABLE) == DENUNCIATION_ALLOWED_COLS

    # 引擎侧零模板句：产出路径无固定文案常量
    prod_files = [
        _REPO / "ming_sim" / "supervision.py",
        _REPO / "ming_sim" / "db.py",
        _REPO / "ming_sim" / "decree.py",
    ]
    template_re = re.compile(
        r"奏称：.*办理.*有异状|请皇上按问"
    )
    for path in prod_files:
        text = path.read_text(encoding="utf-8")
        assert not template_re.search(text), f"模板句残留于 {path.name}"

    # #622 读端改调 public fork 单源
    actor = subject_name
    audit_order = db.create_secret_order(state, actor, "密查清丈", "逐月密奏", ["稽核"], deadline_months=4, covert_task=investigation_covert_task("密查清丈"))
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


def test_accept_wired_in_settle_not_pre_settle_emergence():
    """承接在 settle 抽取后；pre_settle 不再硬触发检举。"""
    decree_src = (_REPO / "ming_sim" / "decree.py").read_text(encoding="utf-8")
    assert "accept_faction_denunciations" in decree_src
    # pre_settle 内不得再 trigger
    tree = ast.parse(decree_src)
    pre = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "pre_settle"
    )
    pre_body = ast.get_source_segment(decree_src, pre) or ""
    assert "trigger_faction_denunciations" not in pre_body
    assert "accept_faction_denunciations" not in pre_body

    sim_src = (_REPO / "ming_sim" / "simulation.py").read_text(encoding="utf-8")
    assert "faction_denunciation_facts" in sim_src
    assert "faction_denunciations" in sim_src  # extractor 字段
