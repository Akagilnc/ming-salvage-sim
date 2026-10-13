from __future__ import annotations
from ming_sim.settlement.dossier import apply_dossier_promulgation
from ming_sim.due_review import apply_pending_due_reviews
from ming_sim.situation_drift import apply_situation_monthly_drift
from ming_sim.staged_commitment import write_due_staged_commitment_todos
from ming_sim.settlement import SettlementContext, settle_delta
from ming_sim.settlement.views import section, view
"""#1260 fiscal 三表 beyond_intent 全链 + 读端单源化 + 嵌套别名。

S1 写端 tracer（三族 + 负向）
S2 纯 fiscal 旨外 → 终裁/fork/反噬接通
S3 嵌套通道「旨外恶果」别名 → ledger=1
"""





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
    apply_dossier_promulgation(db, state, dossier_id, "promulgated")
    assert db.dossiers.get(dossier_id)["status"] == "executing"
    return dossier_id


def _insert_final_stage(db, state, content, *, dossier_id: int, title: str):
    origin = f"dossier:{int(dossier_id)}"
    out = settle_delta(state, db, {'new_issues': [{'origin_kind': 'decree', 'origin_ref': origin, 'kind': 'initiative', 'title': title, 'stage_text': '所约之事依限办结。', 'commitment_kind': 'until_stop', 'ongoing_effects': {}, 'stages': [{'stage_idx': 0, 'due_turn': state.turn, 'criterion_text': '所约财政见成数', 'origin_context': '借旨加派/新立税目'}]}]}, SettlementContext(content=content))
    created = out.issue.new_issues[0]
    assert "rejected" not in created, created
    return int(created["issue_id"])


def _prime_and_apply_due_review(
    db, state, content, *, dossier_id: int, title: str,
    outcome: str, note: str, stage_writer=_insert_final_stage,
):
    """模型经 dossier_executions 写终值后，正式复核只消费 todo（#1835 J18）。"""
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    stage_writer(db, state, content, dossier_id=dossier_id, title=title)
    write_due_staged_commitment_todos(db, state)
    db.conn.execute(
        "UPDATE next_audience_todos SET created_turn=?",
        (state.turn - 1,),
    )
    db.conn.commit()
    written = settle_delta(
        state, db,
        {"dossier_executions": [{
            "dossier_id": int(dossier_id),
            "outcome": outcome,
            "note": note,
        }]},
        SettlementContext(content=content),
    )
    assert not section(written, "dossier_executions").rejected, written
    results = apply_pending_due_reviews(db, state)
    assert results and results[0].get("branch") == "dossier"
    assert results[0].get("consumed") is True
    return results[0]




# ── S1：三族写端 tracer + 负向 ──────────────────────────────────────


def test_s1_fiscal_creates_beyond_intent_tracer_and_negatives(game, content):
    """fiscal_creates 写端：肯定→两行 creations 同旗 True；缺省/畸形/否定→False。"""
    db, state, _ = game
    did = _executing_policy(db, state, token="fc-1260")
    origin = f"dossier:{did}"

    applied = settle_delta(state, db, {'fiscal_creates': [{'key': '剿饷浮收', 'account': '国库', 'direction': 'income', 'init_value': 15, 'reason': '借剿饷名义加派', 'origin_ref': origin, 'beyond_intent': True}]}, SettlementContext(content=content))
    assert view(applied, "fiscal_creates"), applied
    rows = db.fiscal_config.effects_for_origin(f"dossier:{int(did)}")
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
        out = settle_delta(state, db, {'fiscal_creates': [{'key': key, 'account': '国库', 'direction': 'income', 'init_value': 3, 'reason': f'负向{key}', 'origin_ref': origin, **flag}]}, SettlementContext(content=content))
        assert view(out, "fiscal_creates"), out
    neg_rows = [
        r for r in db.fiscal_config.effects_for_origin(f"dossier:{int(did)}")
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

    applied = settle_delta(state, db, {'fiscal_changes': [{'key': rate_key, 'delta': 1, 'reason': '借旨加派一成', 'origin_ref': origin, 'beyond_intent': True}]}, SettlementContext(content=content))
    assert view(applied, "fiscal_changes"), applied
    change_rows = [
        r for r in db.fiscal_config.effects_for_origin(f"dossier:{int(did)}")
        if r.get("effect_kind") == "change"
    ]
    assert change_rows and all(r["beyond_intent"] is True for r in change_rows), change_rows

    # 负向三态
    for label, flag in (
        ("缺省", {}),
        ("畸形", {"beyond_intent": {}}),
        ("否定", {"beyond_intent": "false"}),
    ):
        out = settle_delta(state, db, {'fiscal_changes': [{'key': rate_key, 'delta': 1, 'reason': f'调率负向{label}', 'origin_ref': origin, **flag}]}, SettlementContext(content=content))
        assert view(out, "fiscal_changes"), out
    all_changes = [
        r for r in db.fiscal_config.effects_for_origin(f"dossier:{int(did)}")
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
        out = settle_delta(state, db, {'fiscal_removes': [{'key': stem, 'reason': f'裁撤{stem}', 'origin_ref': origin, **flag}]}, SettlementContext(content=content))
        assert view(out, "fiscal_removes"), out
        tomb = [
            r for r in db.fiscal_config.effects_for_origin(f"dossier:{int(did)}")
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
    rows = db.fiscal_config.effects_for_origin(f"dossier:{int(did)}")
    create_rows = [r for r in rows if r.get("effect_kind") == "create"]
    assert create_rows
    assert all(r["beyond_intent"] is False for r in create_rows), create_rows


# ── S2：纯 fiscal 旨外案卷 → 终裁/fork/反噬 ─────────────────────────


def test_s2_pure_fiscal_beyond_intent_transformed_fork_backlash(game, content):
    """纯 fiscal 旨外（零 economy 流水）→ 留痕/fork；模型写 transformed 后复核消费。"""
    db, state, _ = game
    did = _executing_policy(db, state, token="s2-xf")
    origin = f"dossier:{did}"

    # Only fiscal create with beyond_intent — no economy moves for this flag
    applied = settle_delta(state, db, {'fiscal_creates': [{'key': '借旨新税', 'account': '国库', 'direction': 'income', 'init_value': 20, 'reason': '借剿饷名义新立浮收', 'origin_ref': origin, 'beyond_intent': True}]}, SettlementContext(content=content))
    assert view(applied, "fiscal_creates")
    # Zero beyond-flagged economy moves (foundation seed may add plain spend later)
    eco = db.reign.list_economy_moves_for_origin(f"dossier:{int(did)}")
    assert not any(bool(m.get("beyond_intent")) for m in eco), eco
    fisc = db.fiscal_config.effects_for_origin(f"dossier:{int(did)}")
    assert any(r.get("beyond_intent") is True for r in fisc), fisc

    # Single-source helpers
    durable = db.list_dossier_durable_effects(did)
    assert any(r.get("beyond_intent") is True for r in durable)
    assert db.dossier_has_beyond_intent(did) is True

    # Fork predicate expands to fiscal
    db.dossiers.record_dossier_progress(
        did, state.turn, "在办", "新税已立、岁入可期",
        commit=True,
    )
    fork_state = db.read_dossier_fork_state(did)
    assert fork_state["beyond_intent"] is True
    assert fork_state["fork"] is True

    # 终值由模型声明写格；到期复核只消费，不机械替判
    result = _prime_and_apply_due_review(
        db, state, content, dossier_id=did, title="借旨新税之诺",
        outcome="transformed", note="名实已乖，借旨新立浮收",
    )
    assert (result.get("execution") or {}).get("outcome") == "transformed", result
    dossier = db.dossiers.get(did)
    assert dossier["execution_outcome"] == "transformed"
    assert dossier["status"] == "closed"




# ── S3：嵌套通道别名 ────────────────────────────────────────────────


def test_s3_nested_ongoing_economy_alias_旨外恶果_lands_ledger(game):
    """嵌套通道 ongoing_effects.economy 用「旨外恶果」别名 → ledger beyond_intent=1。"""
    db, state, _ = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.execute("UPDATE legacies SET status='cleared' WHERE status='active'")
    state.metrics["国库"] = 500
    db.reign.save_game_state(state)

    ledger_before = db.conn.execute("SELECT COUNT(*) FROM economy_ledger").fetchone()[0]
    db.insert_issue(
        state,
        kind="initiative",
        title="嵌套旨外恶果月拨",
        origin_kind="decree",
        origin_ref="decree:turn-1:nested-beyond-1260",
        bar_value=0,
        inertia=0,
        stage_text="每月借名浮收。",
        ongoing_effects={
            "economy": [{
                "account": "国库",
                "delta": -8,
                "category": "借名月拨",
                "reason": "嵌套旨外恶果",
                # 嵌套路不经 cleaner；只认全套别名单源
                "旨外恶果": True,
            }]
        },
        end_turn=state.turn + 3,
        commitment_kind="until_stop",
        cancellable="decree",
    )

    apply_situation_monthly_drift(db, state)

    rows = db.conn.execute(
        "SELECT beyond_intent, reason, delta FROM economy_ledger "
        "WHERE id > ? AND reason='嵌套旨外恶果' ORDER BY id",
        (ledger_before,),
    ).fetchall()
    assert rows, "嵌套 ongoing economy 须落 ledger"
    assert all(int(r["beyond_intent"]) == 1 for r in rows), [dict(r) for r in rows]

def test_s2_pure_fiscal_without_beyond_intent_fulfilled(game, content):
    """无旨外 fiscal 效果；模型写 fulfilled 后复核消费。"""
    db, state, _ = game
    did = _executing_policy(db, state, token="s2-neg")
    origin = f"dossier:{did}"

    applied = settle_delta(state, db, {'fiscal_creates': [{'key': '正额新税', 'account': '国库', 'direction': 'income', 'init_value': 10, 'reason': '奉旨正额', 'origin_ref': origin}]}, SettlementContext(content=content))
    assert view(applied, "fiscal_creates")
    assert db.dossier_has_beyond_intent(did) is False

    result = _prime_and_apply_due_review(
        db, state, content, dossier_id=did, title="正额新税之诺",
        outcome="fulfilled", note="正额新税如期见成",
    )
    assert (result.get("execution") or {}).get("outcome") == "fulfilled", result
    dossier = db.dossiers.get(did)
    assert dossier["execution_outcome"] == "fulfilled"
    assert dossier["status"] == "closed"
