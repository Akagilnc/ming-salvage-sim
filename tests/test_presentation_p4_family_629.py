"""#629 S1 — P4 哨兵单源化 + 全族枚举终验。

Seams:
- urge / due_review 真伪底禁词单源（禁双份漂移）
- #622 变形禁词生产单源（禁测试本地平行表）
- FAMILY_P4_BANNED_PLAYER_TOKENS × CREDIT_BANNED_SCAN_SURFACES 七面
  覆盖：变形 / 真伪底 / 信用事件类 / 钝化 / 根基档
- 七面被扫串一律来自生产投影/db 行/真实 payload 组装（禁手写串顶替）
"""

from __future__ import annotations

import json
import subprocess
import sys

from ming_sim.breach_plea import (
    ENTRY_KIND_BREACH_PLEA,
    project_breach_plea_scene,
)
from ming_sim.commitment_backlash import (
    BACKLASH_BANNED_PLAYER_TOKENS,
    BACKLASH_ORIGIN_KIND,
    SOURCE_FAILED_TERMINAL,
    backlash_origin_ref,
)
from ming_sim.credit_events import (
    CREDIT_BANNED_PLAYER_TOKENS,
    CREDIT_BANNED_SCAN_SURFACES,
    FAMILY_P4_BANNED_PLAYER_TOKENS,
    assert_no_family_p4_banned_tokens,
)
from ming_sim.decree_vocabulary import (
    DEFORMATION_BANNED_PLAYER_TOKENS,
    DEFORMATION_STRIP_PLAYER_TOKENS,
    URGE_TRUTH_BANNED_PLAYER_TOKENS,
    format_public_progress_disclosure,
)
from ming_sim.due_review import (
    URGE_TRUTH_BANNED_PLAYER_TOKENS as DUE_REVIEW_URGE_TRUTH,
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
    # due_review 再导出须与叶源同一对象（或等价元组）
    assert DUE_REVIEW_URGE_TRUTH is URGE_TRUTH_BANNED_PLAYER_TOKENS or tuple(
        DUE_REVIEW_URGE_TRUTH
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
    # 生产静默剥离只载无歧义系统词；汉语普通词不进 strip
    for token in ("变形", "分界", "打折走样", "烂尾"):
        assert token not in DEFORMATION_STRIP_PLAYER_TOKENS
        assert token not in _BANNED_PLAYER_TOKENS
    for token in ("beyond_intent", "transformed", "progress_band"):
        assert token in DEFORMATION_STRIP_PLAYER_TOKENS
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


def _seed_halfway_commitment(db, state, *, did: int, title: str) -> int:
    """半途档承诺：投入 + 在办进度 + mid bar（#626 反噬门槛）。"""
    holder = _active_holder(db)
    origin = f"dossier:{did}"
    db.record_issue_economy_move(
        state, "国库", -10, "投入", "半途投入",
        origin_ref=origin, commit=True,
    )
    db.record_dossier_progress(
        did, state.turn, "在办", "过半推进，沿途核验无大异",
        is_terminal=False, commit=True,
    )
    return int(db.insert_issue(
        state,
        kind="initiative",
        title=title,
        origin_kind="decree",
        origin_ref=origin,
        cancellable="decree",
        commitment_kind="until_stop",
        bar_value=45,
        stage_text="在办",
        end_turn=int(state.turn) + 50,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    ))


def _collect_seven_surfaces(db, state, content, *, token: str, memorial_extra: str = ""):
    """组装 CREDIT_BANNED_SCAN_SURFACES 七面——每面均来自生产投影/db 行/payload。

    返回 (surfaces, meta)；meta 含 due_scene/plea_scene/backlash_issue 等供断言。
    """
    did = _policy_dossier(db, state, token=token)
    # 奏报面（生产 progress 行）
    memorial_body = "沿途核验无大异，所委依限推进"
    if memorial_extra:
        memorial_body = f"{memorial_body}{memorial_extra}"
    db.record_dossier_progress(
        did, state.turn, "在办", memorial_body, commit=True,
    )

    # 分段到期 → 复命 scene（生产 project_due_review_scene）
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

    # 哭谏投影（根基档禁词在 payload，玩家面不得泄漏）
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

    # #626 反噬 issue：failed_terminal 路径实例化，扫其玩家可见叙事/进阶
    # （参照 tests/test_commitment_backlash_626.py:893-905）
    bl_did = _policy_dossier(db, state, token=f"{token}-bl")
    cid = _seed_halfway_commitment(
        db, state, did=bl_did, title="P4 终验反噬源诺",
    )
    db.record_dossier_execution(
        bl_did, "failed", "期限已过，诸事不济", int(state.turn),
        close=True, commit=True,
    )
    state.turn = int(state.turn) + 1
    hits = db.trigger_commitment_backlashes(state, commit=True)
    assert hits, "须实例化至少一条 #626 commitment_backlash issue"
    assert hits[0]["source_kind"] == SOURCE_FAILED_TERMINAL
    bl_issue = db.find_any_issue_by_origin(
        BACKLASH_ORIGIN_KIND,
        backlash_origin_ref(cid, SOURCE_FAILED_TERMINAL),
    )
    assert bl_issue is not None
    bl_issue = dict(bl_issue)
    adv = db.conn.execute(
        "SELECT narrative, to_stage_text FROM issue_advances "
        "WHERE issue_id=? ORDER BY id DESC LIMIT 1",
        (int(bl_issue["id"]),),
    ).fetchone()
    assert adv is not None

    # turn_report / knowledge_items：经生产写口落库后回读（非测试内手写扫描串）
    progress_rows = db.list_dossier_progress(did)
    public_disclosure = format_public_progress_disclosure(progress_rows)
    # 回退到 state.turn-1 的 progress 所属回合写月报（did 的 progress 在上一拍）
    report_turn_state = state
    # save 到当前 turn；内容取自生产 memorial 披露，禁另造手写夹具
    knowledge_payload = [
        {
            "title": str(r.get("progress_band") or "在办"),
            "body": str(r.get("memorial_text") or ""),
            "source_id": f"dossier_progress:{did}:{i}",
        }
        for i, r in enumerate(progress_rows)
    ]
    db.save_turn_report(
        report_turn_state,
        public_disclosure,
        knowledge_items=knowledge_payload,
        commit=True,
    )
    turn_report_text = db.get_turn_report(int(report_turn_state.turn))
    knowledge_rows = db.knowledge_items_for_turn(int(report_turn_state.turn))

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
            for r in progress_rows
        ) + "\n" + public_disclosure,
        # narrative：#626 反噬 issue 玩家可见叙事/进阶（生产 db 行）
        "narrative": "\n".join([
            str(bl_issue.get("title") or ""),
            str(bl_issue.get("stage_text") or ""),
            str(bl_issue.get("bar_good_meaning") or ""),
            str(bl_issue.get("bar_bad_meaning") or ""),
            str(adv["narrative"] or ""),
            str(adv["to_stage_text"] or ""),
        ]),
        # turn_report：生产 turn_reports 行
        "turn_report": str(turn_report_text or ""),
        # knowledge_items：生产 character_knowledge_events 投影
        "knowledge_items": json.dumps(
            [
                {
                    "title": str(item.get("title") or ""),
                    "body": str(item.get("body") or ""),
                    "source_id": str(item.get("source_id") or ""),
                }
                for item in knowledge_rows
            ],
            ensure_ascii=False,
        ),
    }
    meta = {
        "due_scene": due_scene,
        "urge_scene": urge_scene,
        "plea_scene": plea_scene,
        "backlash_issue": bl_issue,
        "did": did,
        "progress_rows": progress_rows,
    }
    return surfaces, meta


def test_family_p4_seven_surfaces_scan_production_artifacts_clean(game):
    """七面扫描：每面串取自生产投影/db 行/payload 组装，不得裸露全族禁词。

    narrative 面实例化 #626 commitment_backlash issue 并扫其玩家可见叙事；
    turn_report/knowledge_items 经 save_turn_report 生产写口回读。
    """
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    surfaces, meta = _collect_seven_surfaces(
        db, state, content, token="p4-family-629",
    )

    assert set(surfaces) == set(CREDIT_BANNED_SCAN_SURFACES)
    for name in CREDIT_BANNED_SCAN_SURFACES:
        assert_no_family_p4_banned_tokens(surfaces[name], surface=name)

    # 正向：diegetic 用词仍在
    due_scene = meta["due_scene"]
    plea_scene = meta["plea_scene"]
    assert "复命" in due_scene["scene_text"] or "复命" in surfaces["scene_text"]
    assert "泣血陈情" in plea_scene["scene_text"]
    # #626 反噬已入 narrative 扫描面
    assert meta["backlash_issue"]["title"]
    assert str(meta["backlash_issue"]["title"]) in surfaces["narrative"]
    # 生产回读非空（progress memorial 经写口落库）
    assert surfaces["turn_report"].strip()
    assert "沿途核验无大异" in surfaces["turn_report"]
    assert surfaces["knowledge_items"].strip()
    assert "沿途核验无大异" in surfaces["knowledge_items"]


def test_family_p4_seven_surfaces_red_when_banned_token_injected(game):
    """负向：向活体链路注入 FAMILY_P4 禁词，七面扫描须响亮变红（证明非空心）。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    # 经生产 progress 写口夹带 foundation_tier——memorial/turn_report/knowledge 链路可红
    surfaces, _meta = _collect_seven_surfaces(
        db, state, content,
        token="p4-inject-629",
        memorial_extra=" foundation_tier=halfway",
    )
    assert set(surfaces) == set(CREDIT_BANNED_SCAN_SURFACES)

    red_surfaces = []
    for name in CREDIT_BANNED_SCAN_SURFACES:
        try:
            assert_no_family_p4_banned_tokens(surfaces[name], surface=name)
        except AssertionError:
            red_surfaces.append(name)
    assert red_surfaces, (
        "注入 foundation_tier 后至少一面须红；若全绿则扫描面空心"
    )
    # 注入点在 memorial 生产行，memorial / 由其派生的 turn_report·knowledge 必红
    assert "memorial_text" in red_surfaces
    assert "foundation_tier" in surfaces["memorial_text"]


def test_due_review_preserves_diegetic_fenjie_phrase(game):
    """负向：criterion 含「与喀尔喀分界而治」过 due_review 投影后原词完整保留。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    did = _policy_dossier(db, state, token="fenjie-629")
    diegetic = "与喀尔喀分界而治"
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn,
        "criterion_text": diegetic,
        "origin_context": f"北疆定策：{diegetic}",
    }]
    out = apply_score_extraction(
        db, state,
        {
            "new_issues": [{
                "origin_kind": "decree",
                "origin_ref": f"dossier:{did}",
                "kind": "initiative",
                "title": "分界而治之诺",
                "stage_text": diegetic,
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
    staged_todo = [
        t for t in db.list_next_audience_todos(commitment_ref=issue_id)
        if str(t.get("entry_kind") or "") == ENTRY_KIND_STAGED
    ][0]
    scene = project_due_review_scene(db, staged_todo)
    # 投影后原词完整——静默剥离不得剜「分界」
    assert diegetic in str(scene.get("criterion_text") or "")
    assert "分界" in str(scene.get("scene_text") or "") or diegetic in str(
        scene.get("origin_context") or ""
    )
    assert "与喀尔喀" in str(scene.get("scene_text") or "") + str(
        scene.get("origin_context") or ""
    ) + str(scene.get("criterion_text") or "")
    # 不得被剜成残句「与喀尔喀而治」
    blob = "\n".join([
        str(scene.get("scene_text") or ""),
        str(scene.get("origin_context") or ""),
        str(scene.get("criterion_text") or ""),
        str(scene.get("gap_text") or ""),
    ])
    assert "与喀尔喀而治" not in blob
    assert diegetic in blob


def test_urge_lever_due_review_import_order_both_succeed():
    """负向：先 import urge_lever 与先 import due_review 两种乱序均成功（无环烟）。"""
    scripts = (
        (
            "import ming_sim.urge_lever as ul\n"
            "import ming_sim.due_review as dr\n"
            "assert ul.URGE_TRUTH_BANNED_PLAYER_TOKENS is "
            "dr.URGE_TRUTH_BANNED_PLAYER_TOKENS\n"
        ),
        (
            "import ming_sim.due_review as dr\n"
            "import ming_sim.urge_lever as ul\n"
            "assert ul.URGE_TRUTH_BANNED_PLAYER_TOKENS is "
            "dr.URGE_TRUTH_BANNED_PLAYER_TOKENS\n"
        ),
    )
    for script in scripts:
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, (
            f"import-order subprocess failed\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
