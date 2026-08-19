"""#1260 fiscal 三表 beyond_intent 全链 + 读端单源化 + 嵌套别名。

S1 写端 tracer（三族 + 负向）
S2 纯 fiscal 旨外 → 终裁/fork/反噬接通
S3 嵌套通道「旨外恶果」别名 → ledger=1
"""

from __future__ import annotations

import json

from ming_sim.commitment_backlash import (
    BACKLASH_ORIGIN_KIND,
    SOURCE_DEFORMATION_EXPOSURE,
    backlash_origin_ref,
)
from ming_sim.due_review import (
    apply_pending_due_reviews,
    decide_due_review_verdict,
)
from ming_sim.issues import apply_score_extraction
from ming_sim.simulation import _sanitize_module_output
from ming_sim.staged_commitment import write_due_staged_commitment_todos


# ── helpers ──────────────────────────────────────────────────────────


def _executing_policy(db, state, *, token: str):
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"财政旨外·{token}",
        target_kind="issue",
        target_id=token,
        participants=[
            {"character_id": "倪元璐", "tier": "主办", "role": "经办"},
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
                        "criterion_text": "所约财政见成数",
                        "origin_context": "借旨加派/新立税目",
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


def _insert_commitment(db, state, *, title: str, origin_ref: str, bar_value: int = 45):
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title=title,
        origin_kind="decree",
        origin_ref=origin_ref,
        bar_value=bar_value,
        inertia=0,
        stage_text="在办",
        end_turn=int(state.turn) + 50,
        commitment_kind="until_stop",
        cancellable="decree",
    )
    return int(issue_id)


# ── S1：三族写端 tracer + 负向 ──────────────────────────────────────


def test_s1_fiscal_creates_beyond_intent_tracer_and_negatives(game, content):
    """fiscal_creates 写端：肯定→两行 creations 同旗 True；缺省/畸形/否定→False。"""
    db, state, _ = game
    did = _executing_policy(db, state, token="fc-1260")
    origin = f"dossier:{did}"

    applied = apply_score_extraction(
        db, state,
        {
            "fiscal_creates": [{
                "key": "剿饷浮收",
                "account": "国库",
                "direction": "income",
                "init_value": 15,
                "reason": "借剿饷名义加派",
                "origin_ref": origin,
                "beyond_intent": True,
            }],
        },
        content=content,
    )
    assert applied["fiscal_creates"] and not applied["fiscal_creates"][0].get("rejected"), applied
    rows = db.list_fiscal_effects_for_dossier(did)
    create_rows = [r for r in rows if r.get("effect_kind") == "create"]
    assert {r["key"] for r in create_rows} == {"剿饷浮收_base", "剿饷浮收_rate"}
    assert all(r["beyond_intent"] is True for r in create_rows), create_rows
    # raw DB also stores 1
    raw = db.conn.execute(
        "SELECT beyond_intent FROM fiscal_config_creations WHERE origin_ref=?",
        (origin,),
    ).fetchall()
    assert all(int(r["beyond_intent"]) == 1 for r in raw)

    # 负向：缺省 / 畸形 / 否定 → False
    cases = [
        ("缺省税目", {}),
        ("畸形税目", {"beyond_intent": []}),
        ("否定税目", {"beyond_intent": False}),
        ("零值税目", {"beyond_intent": 0}),
        ("否串税目", {"beyond_intent": "no"}),
    ]
    for key, flag in cases:
        out = apply_score_extraction(
            db, state,
            {
                "fiscal_creates": [{
                    "key": key,
                    "account": "国库",
                    "direction": "income",
                    "init_value": 3,
                    "reason": f"负向{key}",
                    "origin_ref": origin,
                    **flag,
                }],
            },
            content=content,
        )
        assert out["fiscal_creates"] and not out["fiscal_creates"][0].get("rejected"), out
    neg_rows = [
        r for r in db.list_fiscal_effects_for_dossier(did)
        if r.get("effect_kind") == "create"
        and str(r.get("key") or "").endswith("_base")
        and any(str(r.get("key") or "").startswith(k) for k, _ in cases)
    ]
    assert len(neg_rows) == len(cases), neg_rows
    assert all(r["beyond_intent"] is False for r in neg_rows), neg_rows


def test_s1_fiscal_changes_beyond_intent_tracer_and_negatives(game, content):
    """fiscal_changes 写端：肯定→changes 行 True；缺省/畸形/否定→False。"""
    db, state, _ = game
    did = _executing_policy(db, state, token="ch-1260")
    origin = f"dossier:{did}"

    # Pick an existing adjustable fiscal key
    key = db.conn.execute(
        "SELECT key FROM fiscal_config WHERE key LIKE '%_rate' "
        "AND key NOT LIKE '%损耗%' ORDER BY key LIMIT 1"
    ).fetchone()
    assert key is not None, "fixture must have a fiscal_config rate key"
    rate_key = str(key["key"])

    applied = apply_score_extraction(
        db, state,
        {
            "fiscal_changes": [{
                "key": rate_key,
                "delta": 1,
                "reason": "借旨加派一成",
                "origin_ref": origin,
                "beyond_intent": True,
            }],
        },
        content=content,
    )
    assert applied["fiscal_changes"] and not applied["fiscal_changes"][0].get("rejected"), applied
    change_rows = [
        r for r in db.list_fiscal_effects_for_dossier(did)
        if r.get("effect_kind") == "change"
    ]
    assert change_rows and all(r["beyond_intent"] is True for r in change_rows), change_rows

    # 负向三态
    for label, flag in (
        ("缺省", {}),
        ("畸形", {"beyond_intent": {}}),
        ("否定", {"beyond_intent": "false"}),
    ):
        out = apply_score_extraction(
            db, state,
            {
                "fiscal_changes": [{
                    "key": rate_key,
                    "delta": 1,
                    "reason": f"调率负向{label}",
                    "origin_ref": origin,
                    **flag,
                }],
            },
            content=content,
        )
        assert out["fiscal_changes"] and not out["fiscal_changes"][0].get("rejected"), out
    all_changes = [
        r for r in db.list_fiscal_effects_for_dossier(did)
        if r.get("effect_kind") == "change"
    ]
    # first is True; the three negatives are False
    flags = [r["beyond_intent"] for r in all_changes]
    assert flags[0] is True
    assert flags[1:] == [False, False, False], flags


def test_s1_fiscal_removes_beyond_intent_tracer_and_negatives(game, content):
    """fiscal_removes 写端：肯定→tombstones 显式常量 True；缺省/畸形/否定→False。"""
    db, state, _ = game
    did = _executing_policy(db, state, token="rm-1260")
    origin = f"dossier:{did}"

    # Create four disposable subjects: one positive + three negatives
    subjects = [
        ("旨外罢税", {"beyond_intent": True}, True),
        ("缺省罢税", {}, False),
        ("畸形罢税", {"beyond_intent": ["x"]}, False),
        ("否定罢税", {"beyond_intent": 0}, False),
    ]
    for stem, _flag, _exp in subjects:
        created = db.create_fiscal_item(
            stem, "国库", "expense", stem, 5,
            origin_ref=origin, turn=state.turn, commit=True,
            # creations themselves not under test here
        )
        assert created, stem

    for stem, flag, expected in subjects:
        out = apply_score_extraction(
            db, state,
            {
                "fiscal_removes": [{
                    "key": stem,
                    "reason": f"裁撤{stem}",
                    "origin_ref": origin,
                    **flag,
                }],
            },
            content=content,
        )
        assert out["fiscal_removes"] and not out["fiscal_removes"][0].get("rejected"), out
        tomb = [
            r for r in db.list_fiscal_effects_for_dossier(did)
            if r.get("effect_kind") == "remove" and str(r.get("key") or "").startswith(stem)
        ]
        assert tomb, stem
        assert all(r["beyond_intent"] is expected for r in tomb), (stem, tomb)

    # Ban SELECT * residue: tombstone INSERT must carry explicit beyond_intent column
    # (verified by presence of the column value, not by grepping source)
    raw = db.conn.execute(
        "SELECT beyond_intent FROM fiscal_config_tombstones WHERE origin_ref=?",
        (origin,),
    ).fetchall()
    assert raw and all("beyond_intent" in dict(r) for r in raw)


def test_s1_cleaner_passthrough_fiscal_beyond_intent_aliases(game, content):
    """三 cleaner 透传已归一旨外键（含中文别名经 _sanitize_module_output）。"""
    db, state, _ = game
    did = _executing_policy(db, state, token="cl-1260")
    origin = f"dossier:{did}"

    # Create a disposable item so remove has a target
    db.create_fiscal_item(
        "别名透传税", "国库", "expense", "别名透传税", 4,
        origin_ref=origin, turn=state.turn, commit=True,
    )
    rate_key = db.conn.execute(
        "SELECT key FROM fiscal_config WHERE key LIKE '%_rate' "
        "AND key NOT LIKE '%损耗%' ORDER BY key LIMIT 1"
    ).fetchone()["key"]

    raw = {
        "fiscal_creates": [{
            "键": "别名新立税",
            "账户": "国库",
            "方向": "收",
            "初值": 8,
            "原因": "别名新立",
            "来源引用": origin,
            "旨外": True,
        }],
        "fiscal_changes": [{
            "键": rate_key,
            "增量": 1,
            "原因": "别名调率",
            "来源引用": origin,
            "旨外标记": 1,
        }],
        "fiscal_removes": [{
            "键": "别名透传税",
            "原因": "别名裁撤",
            "来源引用": origin,
            "旨外恶果": True,
        }],
    }
    cleaned = _sanitize_module_output("internal", raw)
    # Cleaners must preserve beyond_intent after alias canonicalization
    assert cleaned["fiscal_creates"][0].get("beyond_intent") is True, cleaned
    assert cleaned["fiscal_changes"][0].get("beyond_intent") == 1, cleaned
    assert cleaned["fiscal_removes"][0].get("beyond_intent") is True, cleaned

    applied = apply_score_extraction(db, state, cleaned, content=content)
    assert applied["fiscal_creates"] and not applied["fiscal_creates"][0].get("rejected")
    assert applied["fiscal_changes"] and not applied["fiscal_changes"][0].get("rejected")
    assert applied["fiscal_removes"] and not applied["fiscal_removes"][0].get("rejected")
    effects = db.list_fiscal_effects_for_dossier(did)
    assert any(
        r.get("effect_kind") == "create"
        and str(r.get("key") or "").startswith("别名新立税")
        and r["beyond_intent"] is True
        for r in effects
    ), effects
    assert any(
        r.get("effect_kind") == "change" and r["beyond_intent"] is True for r in effects
    ), effects
    assert any(
        r.get("effect_kind") == "remove"
        and str(r.get("key") or "").startswith("别名透传税")
        and r["beyond_intent"] is True
        for r in effects
    ), effects


def test_s1_engine_grant_fiscal_create_stays_beyond_intent_zero(game):
    """db.py 引擎确定性拨帑建项显式留 0（旨内，禁捏造旗值）。"""
    db, state, _ = game
    did = _executing_policy(db, state, token="grant-1260")
    created = db._create_grant_fiscal_item(
        state,
        {"grant_action": "赏赉", "reason": "恩赏月拨", "cadence": "每月"},
        did,
        account="国库",
        amount=10,
        text="赏银月拨",
    )
    assert created
    rows = db.list_fiscal_effects_for_dossier(did)
    create_rows = [r for r in rows if r.get("effect_kind") == "create"]
    assert create_rows
    assert all(r["beyond_intent"] is False for r in create_rows), create_rows


# ── S2：纯 fiscal 旨外案卷 → 终裁/fork/反噬 ─────────────────────────


def test_s2_pure_fiscal_beyond_intent_transformed_fork_backlash(game, content):
    """纯 fiscal 旨外（零 economy 流水）→ 终裁 transformed + fork=True + 反噬入选。"""
    db, state, _ = game
    did = _executing_policy(db, state, token="s2-xf")
    origin = f"dossier:{did}"

    # Only fiscal create with beyond_intent — no economy moves for this flag
    applied = apply_score_extraction(
        db, state,
        {
            "fiscal_creates": [{
                "key": "借旨新税",
                "account": "国库",
                "direction": "income",
                "init_value": 20,
                "reason": "借剿饷名义新立浮收",
                "origin_ref": origin,
                "beyond_intent": True,
            }],
        },
        content=content,
    )
    assert applied["fiscal_creates"] and not applied["fiscal_creates"][0].get("rejected")
    # Zero beyond-flagged economy moves (foundation seed may add plain spend later)
    eco = db.list_economy_moves_for_dossier(did)
    assert not any(bool(m.get("beyond_intent")) for m in eco), eco
    fisc = db.list_fiscal_effects_for_dossier(did)
    assert any(r.get("beyond_intent") is True for r in fisc), fisc

    # Single-source helpers
    durable = db.list_dossier_durable_effects(did)
    assert any(r.get("beyond_intent") is True for r in durable)
    assert db.dossier_has_beyond_intent(did) is True

    # Fork predicate expands to fiscal
    db.record_dossier_progress(
        did, state.turn, "在办", "新税已立、岁入可期",
        is_terminal=False, commit=True,
    )
    fork_state = db.read_dossier_fork_state(did)
    assert fork_state["beyond_intent"] is True
    assert fork_state["fork"] is True

    # Due-review terminal → transformed
    result = _prime_and_apply_due_review(
        db, state, content, dossier_id=did, title="借旨新税之诺",
    )
    assert result["verdict"]["outcome"] == "transformed", result
    dossier = db.get_decree_dossier(did)
    assert dossier["execution_outcome"] == "transformed"

    # Backlash gate: pure fiscal beyond_intent qualifies
    # Re-open a fresh dossier path for backlash (execution already closed above).
    # Use the same closed transformed dossier + halfway foundation.
    # Foundation needs spend; use plain (non-beyond) economy so fiscal remains the beyond source.
    db.record_issue_economy_move(
        state, "国库", -25, "投入", "半途根基",
        origin_ref=origin, beyond_intent=0, commit=True,
    )
    cid = _insert_commitment(
        db, state, title="借旨新税反噬诺", origin_ref=origin, bar_value=45,
    )
    # Ensure closed_turn is in the past relative to trigger turn
    state.turn = int(state.turn) + 1
    hits = db.trigger_commitment_backlashes(state, commit=True)
    assert any(
        h.get("source_kind") == SOURCE_DEFORMATION_EXPOSURE
        and h.get("trigger_ref") == f"issue:{cid}"
        for h in hits
    ), hits
    assert db.find_any_issue_by_origin(
        BACKLASH_ORIGIN_KIND,
        backlash_origin_ref(cid, SOURCE_DEFORMATION_EXPOSURE),
    ) is not None


def test_s2_pure_fiscal_without_beyond_intent_fulfilled_no_backlash(game, content):
    """无旨外 fiscal 效果 → 终裁 fulfilled；transformed 无 beyond → 不立案。"""
    db, state, _ = game
    did = _executing_policy(db, state, token="s2-neg")
    origin = f"dossier:{did}"

    applied = apply_score_extraction(
        db, state,
        {
            "fiscal_creates": [{
                "key": "正额新税",
                "account": "国库",
                "direction": "income",
                "init_value": 10,
                "reason": "奉旨正额",
                "origin_ref": origin,
                # no beyond_intent
            }],
        },
        content=content,
    )
    assert applied["fiscal_creates"] and not applied["fiscal_creates"][0].get("rejected")
    assert db.dossier_has_beyond_intent(did) is False

    result = _prime_and_apply_due_review(
        db, state, content, dossier_id=did, title="正额新税之诺",
    )
    assert result["verdict"]["outcome"] == "fulfilled", result

    # Separate dossier: transformed text without beyond → no backlash
    did2 = _executing_policy(db, state, token="s2-neg2")
    origin2 = f"dossier:{did2}"
    db.record_issue_economy_move(
        state, "国库", -25, "投入", "半途根基2",
        origin_ref=origin2, beyond_intent=0, commit=True,
    )
    # fiscal effect present but no beyond flag
    apply_score_extraction(
        db, state,
        {
            "fiscal_creates": [{
                "key": "无旗税目",
                "account": "国库",
                "direction": "income",
                "init_value": 5,
                "reason": "无旗",
                "origin_ref": origin2,
            }],
        },
        content=content,
    )
    cid = _insert_commitment(
        db, state, title="无分叉变形诺", origin_ref=origin2, bar_value=45,
    )
    db.record_dossier_execution(
        did2, "transformed", "名实已乖（无旨外账）", int(state.turn),
        close=True, commit=True,
    )
    state.turn = int(state.turn) + 1
    hits = db.trigger_commitment_backlashes(state, commit=True)
    assert not any(
        h.get("source_kind") == SOURCE_DEFORMATION_EXPOSURE
        and h.get("trigger_ref") == f"issue:{cid}"
        for h in hits
    ), hits


def test_s2_decide_due_review_shape_unchanged_with_helper():
    """红线：助手只供事实；decide_due_review_verdict 判定形状不改。"""
    # Pure unit: fiscal-shaped durable effect with beyond_intent → transformed
    verdict = decide_due_review_verdict({
        "mid_stage": False,
        "durable_effects": [
            {"effect_kind": "create", "key": "x_base", "beyond_intent": True},
        ],
        "progress_reports": [],
        "criterion_text": "新税见成",
    })
    assert verdict["outcome"] == "transformed"
    assert verdict["close"] is True
    assert "is_terminal" in verdict

    # No beyond → fulfilled when effects present
    verdict2 = decide_due_review_verdict({
        "mid_stage": False,
        "durable_effects": [
            {"effect_kind": "create", "key": "y_base", "beyond_intent": False},
        ],
        "progress_reports": [],
        "criterion_text": "正额",
    })
    assert verdict2["outcome"] == "fulfilled"
