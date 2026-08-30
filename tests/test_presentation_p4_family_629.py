"""#629 P4 输入侧结构化守门与投影回归。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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
from ming_sim.urge_lever import (
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


def _policy_dossier(db, state, *, token: str) -> int:
    holder = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' "
        "AND office IS NOT NULL AND office != '' ORDER BY name LIMIT 1"
    ).fetchone()["name"]
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"P4 投影回归 {token}",
        target_kind="issue",
        target_id=token,
        executor_kind="character",
        executor_id=holder,
        participants=[{"character_id": holder, "tier": "主办"}],
        payload={"mode": "ordinary"},
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    return int(dossier_id)


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
    repo_root = Path(__file__).resolve().parents[1]
    for script in scripts:
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        assert completed.returncode == 0, (
            f"import-order subprocess failed\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
