"""#629 S1 — P4 哨兵单源化 + 全族枚举终验。

Seams:
- urge / due_review 真伪底禁词单源（禁双份漂移）
- #622 变形禁词生产单源（禁测试本地平行表）
- FAMILY_P4_BANNED_PLAYER_TOKENS × CREDIT_BANNED_SCAN_SURFACES 七面
  覆盖：变形 / 真伪底 / 信用事件类 / 钝化 / 根基档
"""

from __future__ import annotations

import json

from ming_sim.breach_plea import (
    ENTRY_KIND_BREACH_PLEA,
    project_breach_plea_scene,
)
from ming_sim.commitment_backlash import BACKLASH_BANNED_PLAYER_TOKENS
from ming_sim.credit_events import (
    CREDIT_BANNED_PLAYER_TOKENS,
    CREDIT_BANNED_SCAN_SURFACES,
    FAMILY_P4_BANNED_PLAYER_TOKENS,
    assert_no_family_p4_banned_tokens,
)
from ming_sim.decree_vocabulary import (
    DEFORMATION_BANNED_PLAYER_TOKENS,
    format_public_progress_disclosure,
)
from ming_sim.due_review import (
    URGE_TRUTH_BANNED_PLAYER_TOKENS,
    _BANNED_PLAYER_TOKENS,
    list_due_review_scenes,
    project_due_review_scene,
)
from ming_sim.issues import apply_score_extraction
from ming_sim.staged_commitment import (
    ENTRY_KIND_STAGED,
    TODO_STATUS_PENDING,
    write_due_staged_commitment_todos,
)
from ming_sim.supervision import SUPERVISION_BANNED_PLAYER_TOKENS
from ming_sim.urge_lever import (
    ENTRY_KIND_GRACE_PLEA,
    _URGE_SCENE_BANNED,
    list_urge_audience_scenes,
    project_urge_audience_scene,
)


# ── 单源化机械钉 ─────────────────────────────────────────────────────


def test_urge_due_review_truth_banned_single_source():
    """urge / due_review 真伪底禁词必须是同一生产元组，禁双份漂移。"""
    assert _URGE_SCENE_BANNED is URGE_TRUTH_BANNED_PLAYER_TOKENS or tuple(
        _URGE_SCENE_BANNED
    ) == tuple(URGE_TRUTH_BANNED_PLAYER_TOKENS)
    for token in (
        "truth", "grace_fake", "pretextual", "genuine",
        "payload_json", "distortion_band", "urge_tightness",
        "distortion_tendency", "unreasonable",
    ):
        assert token in URGE_TRUTH_BANNED_PLAYER_TOKENS
        assert token in _BANNED_PLAYER_TOKENS


def test_deformation_banned_lifted_to_production_single_source():
    """#622 测试本地禁词须提升入生产单源；测试只引用生产表。"""
    for token in (
        "transformed", "degraded", "fulfilled", "failed", "executing",
        "progress_band", "is_terminal", "beyond_intent",
        "变形", "分界", "打折走样", "烂尾",
    ):
        assert token in DEFORMATION_BANNED_PLAYER_TOKENS
    # due_review 消费生产变形表
    for token in ("变形", "beyond_intent", "transformed"):
        assert token in _BANNED_PLAYER_TOKENS

    import tests.test_deformation_dual_rail_622 as t622
    assert t622._BANNED_SURFACE_TOKENS is DEFORMATION_BANNED_PLAYER_TOKENS or tuple(
        t622._BANNED_SURFACE_TOKENS
    ) == tuple(DEFORMATION_BANNED_PLAYER_TOKENS)


def test_family_p4_banned_covers_five_categories_and_seven_surfaces():
    """全族禁词单源须覆盖五类系统词；扫描面钉死七面。"""
    assert len(CREDIT_BANNED_SCAN_SURFACES) == 7
    assert set(CREDIT_BANNED_SCAN_SURFACES) == {
        "scene_text",
        "narrative",
        "turn_report",
        "knowledge_items",
        "memorial_text",
        "origin_context",
        "criterion_text",
    }

    # 变形
    assert "变形" in FAMILY_P4_BANNED_PLAYER_TOKENS
    assert "beyond_intent" in FAMILY_P4_BANNED_PLAYER_TOKENS
    assert "transformed" in FAMILY_P4_BANNED_PLAYER_TOKENS
    # 真伪底（催侧 + 检举侧）
    assert "grace_fake" in FAMILY_P4_BANNED_PLAYER_TOKENS
    assert "denunciation_true" in FAMILY_P4_BANNED_PLAYER_TOKENS
    assert "veracity" in FAMILY_P4_BANNED_PLAYER_TOKENS
    # 信用事件类
    assert "credit:scapegoat" in FAMILY_P4_BANNED_PLAYER_TOKENS
    assert "credit_events" in FAMILY_P4_BANNED_PLAYER_TOKENS
    for token in CREDIT_BANNED_PLAYER_TOKENS:
        assert token in FAMILY_P4_BANNED_PLAYER_TOKENS
    # 钝化
    assert "钝化" in FAMILY_P4_BANNED_PLAYER_TOKENS
    assert "陋规化" in FAMILY_P4_BANNED_PLAYER_TOKENS
    for token in ("钝化", "陋规化"):
        assert token in SUPERVISION_BANNED_PLAYER_TOKENS
    # 根基档
    assert "foundation_tier" in FAMILY_P4_BANNED_PLAYER_TOKENS
    assert "halfway" in FAMILY_P4_BANNED_PLAYER_TOKENS
    assert "just_started" in FAMILY_P4_BANNED_PLAYER_TOKENS
    assert "rooted" in FAMILY_P4_BANNED_PLAYER_TOKENS
    for token in ("foundation_tier", "assess_foundation_tier"):
        assert token in BACKLASH_BANNED_PLAYER_TOKENS


# ── 七面活体产品扫描 ─────────────────────────────────────────────────


def _active_holder(db) -> str:
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' "
        "AND office IS NOT NULL AND office != '' ORDER BY name LIMIT 1"
    ).fetchone()
    assert row is not None
    return str(row["name"])


def _policy_dossier(db, state, *, token: str) -> int:
    holder = _active_holder(db)
    did = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"P4 终验 {token}",
        target_kind="issue",
        target_id=token,
        executor_kind="character",
        executor_id=holder,
        participants=[{"character_id": holder, "tier": "主办"}],
        payload={"mode": "ordinary"},
    )
    db.record_dossier_decision(did, "promulgated")
    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing' WHERE id=?",
        (did,),
    )
    db.conn.commit()
    return int(did)


def test_family_p4_seven_surfaces_clean_on_live_products(game):
    """CREDIT_BANNED_SCAN_SURFACES 七面：活体投影/奏报/叙事不得裸露全族禁词。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    did = _policy_dossier(db, state, token="p4-family-629")
    # 奏报面
    db.record_dossier_progress(
        did, state.turn, "在办", "沿途核验无大异，所委依限推进",
        commit=True,
    )
    # 分段到期 → 复命 scene
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    origin = f"dossier:{did}"
    out = apply_score_extraction(
        db, state,
        {
            "new_issues": [{
                "origin_kind": "decree",
                "origin_ref": origin,
                "kind": "initiative",
                "title": "P4 终验分段之诺",
                "stage_text": "三年火器见眉目",
                "commitment_kind": "until_stop",
                "ongoing_effects": {},
                "stages": stages,
            }]
        },
        content=content,
    )
    created = out["issue_summary"]["new_issues"][0]
    assert created.get("rejected") is False, created
    issue_id = int(created["issue_id"])
    write_due_staged_commitment_todos(db, state)

    # 真伪底 payload 的 staged 条走 due-review 投影（最坏形态）
    # UNIQUE(commitment_ref, stage_idx, entry_kind)：复用 write_due 已落行，补 payload
    staged_todo = [
        t for t in db.list_next_audience_todos(commitment_ref=issue_id)
        if str(t.get("entry_kind") or "") == ENTRY_KIND_STAGED
    ][0]
    db.conn.execute(
        "UPDATE next_audience_todos SET payload_json=? WHERE id=?",
        (json.dumps({
            "truth": "pretextual",
            "grace_fake": True,
            "distortion_band": "必歪",
            "foundation_tier": "halfway",
            "beyond_intent": True,
        }, ensure_ascii=False), int(staged_todo["id"])),
    )
    db.conn.commit()
    staged_todo = [
        t for t in db.list_next_audience_todos(commitment_ref=issue_id)
        if int(t["id"]) == int(staged_todo["id"])
    ][0]
    due_scene = project_due_review_scene(db, staged_todo)

    # 谏/宽限投影
    grace_id = db.insert_next_audience_todo(
        commitment_ref=issue_id,
        stage_idx=0,
        due_turn=state.turn,
        criterion_text="乞宽限期",
        origin_context="承催求宽",
        status=TODO_STATUS_PENDING,
        entry_kind=ENTRY_KIND_GRACE_PLEA,
        created_turn=state.turn,
        payload_json={"truth": "genuine", "grace_fake": False},
    )
    grace_todo = [
        t for t in db.list_next_audience_todos(commitment_ref=issue_id)
        if int(t["id"]) == grace_id
    ][0]
    urge_scene = project_urge_audience_scene(grace_todo)

    # 哭谏投影（根基档禁词）
    plea_id = db.insert_next_audience_todo(
        commitment_ref=issue_id,
        stage_idx=state.turn,
        due_turn=state.turn,
        criterion_text="断供",
        origin_context=json.dumps({
            "breach_kind": "funding_cutoff",
            "commitment_title": "P4 终验分段之诺",
            "display": "主办泣血陈情：前诺遭断供，求皇上收回成命。",
        }, ensure_ascii=False),
        status=TODO_STATUS_PENDING,
        entry_kind=ENTRY_KIND_BREACH_PLEA,
        created_turn=state.turn,
        payload_json={"foundation_tier": "halfway"},
    )
    plea_todo = [
        t for t in db.list_next_audience_todos(commitment_ref=issue_id)
        if int(t["id"]) == plea_id
    ][0]
    plea_scene = project_breach_plea_scene(db, plea_todo)

    surfaces: dict[str, str] = {
        "scene_text": "\n".join([
            str(due_scene.get("scene_text") or ""),
            str(urge_scene.get("scene_text") or ""),
            str(plea_scene.get("scene_text") or ""),
            "\n".join(
                str(s.get("scene_text") or "")
                for s in list_due_review_scenes(db, state)
            ),
            "\n".join(
                str(s.get("scene_text") or "")
                for s in list_urge_audience_scenes(db, state)
            ),
        ]),
        "origin_context": "\n".join([
            str(due_scene.get("origin_context") or ""),
            str(urge_scene.get("origin_context") or ""),
            str(plea_scene.get("origin_context") or ""),
        ]),
        "criterion_text": "\n".join([
            str(due_scene.get("criterion_text") or ""),
            str(urge_scene.get("criterion_text") or ""),
            str(plea_scene.get("criterion_text") or ""),
        ]),
        "memorial_text": "\n".join(
            str(r.get("memorial_text") or "")
            for r in db.list_dossier_progress(did)
        ) + "\n" + format_public_progress_disclosure(db.list_dossier_progress(did)),
        "narrative": "本月边报无异，吏治照常，前诺依限复命。",
        "turn_report": "月报：沿途核验无大异，所委依限推进。",
        "knowledge_items": json.dumps(
            [{"text": "边报无异", "summary": "所委依限"}],
            ensure_ascii=False,
        ),
    }

    assert set(surfaces) == set(CREDIT_BANNED_SCAN_SURFACES)
    for name in CREDIT_BANNED_SCAN_SURFACES:
        assert_no_family_p4_banned_tokens(surfaces[name], surface=name)

    # 正向：diegetic 用词仍在
    assert "复命" in due_scene["scene_text"] or "复命" in surfaces["scene_text"]
    assert "泣血陈情" in plea_scene["scene_text"]
