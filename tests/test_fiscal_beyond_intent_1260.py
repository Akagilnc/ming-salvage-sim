"""#1260 fiscal 三表 beyond_intent 全链 + 读端单源化 + 嵌套别名。

S1 写端 tracer（三族 + 负向）
S2 纯 fiscal 旨外 → 终裁/fork/反噬接通
S3 嵌套通道「旨外恶果」别名 → ledger=1
"""

from __future__ import annotations

import json

from ming_sim.issues import apply_score_extraction
from ming_sim.simulation import _sanitize_module_output


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


