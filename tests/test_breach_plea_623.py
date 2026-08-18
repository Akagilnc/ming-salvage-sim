"""#623 挽留场（0075）——松手检测·哭谏·根基分档。

Seams:
- ENTRY_KIND_BREACH_PLEA 写端（stage_idx=触发 turn）
- list_due_review_scenes 哭谏场面（召对待裁通道）
- apply_pending_due_reviews 仅 staged 终裁；哭谏 pending 保留
- dossiers_with_pending_due_review 不含挽留
- revoke 拦截：当回合无损 + 写挽留 todo
- resolve_breach_pleas_from_extraction 召对真入口（反悔/坚持）
- 沉默滚存 / 承诺到期失效
- 根基三档 + 办到一半国势倒退写侧
"""

from __future__ import annotations

import json

import pytest

from ming_sim.breach_plea import (
    BREACH_KIND_FUNDING,
    BREACH_KIND_MISAPPROPRIATION,
    BREACH_KIND_POLICY_REVERSAL,
    BREACH_KIND_REMOVE_SPONSOR,
    ENTRY_KIND_BREACH_PLEA,
    FOUNDATION_HALFWAY,
    FOUNDATION_JUST_STARTED,
    FOUNDATION_ROOTED,
    assess_foundation_tier,
    expire_breach_pleas_on_due,
    finalize_persist,
    scan_and_write_breach_pleas,
    try_defer_revoke_to_breach_plea,
    write_breach_plea_todo,
)
from ming_sim.decree import settle_with_delta
from ming_sim.due_review import (
    apply_pending_due_reviews,
    dossiers_with_pending_due_review,
    list_due_review_scenes,
)
from ming_sim.issues import apply_score_extraction
from ming_sim.models import TurnPhase
from ming_sim.staged_commitment import (
    ENTRY_KIND_STAGED,
    TODO_STATUS_CONSUMED,
    TODO_STATUS_PENDING,
)


# ── fixtures（复用 #621 三拍/_cost_events 口径）────────────────────────


def _cost_events(db, dossier_id, *, identity="breach"):
    return [
        dict(row)
        for row in db.conn.execute(
            "SELECT * FROM decree_cost_events WHERE dossier_id=? AND cost_identity=? ORDER BY id",
            (int(dossier_id), identity),
        ).fetchall()
    ]


def _executing_policy_dossier(db, state, *, token: str = "breach-623", holder: str = ""):
    if not holder:
        holder = str(db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
            "ORDER BY name LIMIT 1"
        ).fetchone()["name"])
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"清丈差务·{token}",
        target_kind="issue",
        target_id=token,
        executor_kind="character",
        executor_id=holder,
        participants=[
            {"character_id": holder, "tier": "主办", "role": "清丈"},
        ],
        payload={"mode": "ordinary", "text": token},
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    assert db.get_decree_dossier(dossier_id)["status"] == "executing"
    return dossier_id, holder


def _insert_commitment(
    db, state, *,
    title: str = "徐光启清丈之诺",
    origin_ref: str = "",
    stages=None,
    end_turn: int = 0,
    ongoing_effects=None,
    stop_condition=None,
    bar_value: int = 20,
    participants=None,
    tags=None,
):
    """经 insert_issue 直写 active 承诺（commitment_kind 非空）。"""
    if not origin_ref:
        did, _ = _executing_policy_dossier(db, state, token=title)
        origin_ref = f"dossier:{did}"
    kwargs = dict(
        kind="initiative",
        title=title,
        origin_kind="decree",
        origin_ref=origin_ref,
        cancellable="decree",
        commitment_kind="until_stop",
        bar_value=bar_value,
        stage_text="在办",
        ongoing_effects=ongoing_effects or {},
        end_turn=int(end_turn or 0),
        stages_json=stages,
        participants=participants,
        tags=list(tags or []),
    )
    if stop_condition is not None:
        kwargs["stop_condition"] = stop_condition
    issue_id = db.insert_issue(state, **kwargs)
    return int(issue_id), origin_ref


def _settle_empty_month(db, state, content):
    before = state.turn
    report = settle_with_delta(state, db, {}, before_turn=before, content=content)
    assert state.turn == before + 1
    return report


def _pending_pleas(db):
    return [
        t for t in db.list_next_audience_todos(status=TODO_STATUS_PENDING)
        if str(t.get("entry_kind") or "") == ENTRY_KIND_BREACH_PLEA
    ]


# ── 四类松手：当回合无损 + 次回合哭谏 ────────────────────────────────


def test_funding_cutoff_writes_plea_no_damage_same_turn(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="fund")
    origin = f"dossier:{did}"
    # 历史月供
    db.record_issue_economy_move(
        state, "国库", -5, "清丈月供", "履行期月供",
        origin_ref=origin, commit=True,
    )
    # 今已断供：ongoing 无 economy
    cid, _ = _insert_commitment(
        db, state, title="清丈月供之诺", origin_ref=origin,
        ongoing_effects={}, bar_value=15,
        end_turn=state.turn + 24,
    )
    auth_before = int(state.metrics.get("皇威", 0) or 0)
    costs_before = _cost_events(db, did)

    written = scan_and_write_breach_pleas(db, state, commit=True)
    assert written
    pleas = _pending_pleas(db)
    assert len(pleas) == 1
    assert pleas[0]["criterion_text"] == "断供"
    assert int(pleas[0]["stage_idx"]) == int(state.turn)
    # 当回合无损
    assert db.get_decree_dossier(did)["status"] == "executing"
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()["status"] == "active"
    assert _cost_events(db, did) == costs_before
    assert int(state.metrics.get("皇威", 0) or 0) == auth_before

    # 次回合场面
    scenes = list_due_review_scenes(db, state)
    plea_scenes = [s for s in scenes if s.get("entry_kind") == ENTRY_KIND_BREACH_PLEA]
    assert plea_scenes
    assert plea_scenes[0]["kind"] == "breach_plea"
    assert plea_scenes[0]["channel"] == "audience_pending"
    assert "信心一半是皇爷给的" in plea_scenes[0]["scene_text"]
    # 呈现面：玩家可见串无 DECISION/系统枚举；entry_kind 机读字段可保留供通道断言
    for token in ("AWAITING_DECISION", "<<DECISION>>", "fulfilled", "确认弹窗"):
        assert token not in plea_scenes[0]["scene_text"]
        assert token not in str(plea_scenes[0].get("origin_context") or "")


def test_misappropriation_writes_plea(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="misapp")
    origin = f"dossier:{did}"
    # 专款：真实 producer= tags「专款:账户」（new_issues.tags 写口），禁 stop_condition 夹具造假
    cid, _ = _insert_commitment(
        db, state, title="国库专款之诺", origin_ref=origin,
        bar_value=20, end_turn=state.turn + 12,
    )
    db.conn.execute(
        "UPDATE issues SET tags=? WHERE id=?",
        (json.dumps(["专款:国库"], ensure_ascii=False), cid),
    )
    db.conn.commit()
    # 本回合挪用：从专款账户支用且 origin 非本承诺
    db.record_issue_economy_move(
        state, "国库", -8, "他用", "挪作赏功",
        origin_ref="dossier:99999", commit=True,
    )
    written = scan_and_write_breach_pleas(db, state, commit=True)
    assert written
    pleas = _pending_pleas(db)
    assert any(p["criterion_text"] == "挪用" for p in pleas)
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()["status"] == "active"


def test_remove_sponsor_writes_plea(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="rm-sponsor")
    origin = f"dossier:{did}"
    cid, _ = _insert_commitment(
        db, state, title="人存政举之诺", origin_ref=origin,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
        bar_value=20, end_turn=state.turn + 18,
    )
    # 罢主办
    db.conn.execute(
        "UPDATE characters SET status='dismissed' WHERE name=?", (holder,),
    )
    db.conn.commit()
    written = scan_and_write_breach_pleas(db, state, commit=True)
    assert written
    pleas = _pending_pleas(db)
    assert any(p["criterion_text"] == "撤人" for p in pleas)
    # 当回合承诺仍 active；0056 不落（撤人）
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()["status"] == "active"
    assert _cost_events(db, did) == []


def test_policy_reversal_revoke_defers_breach(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="revoke-defer")
    origin = f"dossier:{did}"
    cid, _ = _insert_commitment(
        db, state, title="改弦可挽之诺", origin_ref=origin,
        bar_value=20, end_turn=state.turn + 30,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    auth_before = int(state.metrics.get("皇威", 0) or 0)

    # 走真实 revoke verdict 物化缝
    revoke_id = db.create_decree_dossier(
        state,
        action_type="revoke_decree",
        decree_text="前旨作废",
        target_kind="dossier",
        target_id=str(did),
        payload={
            "revoke_target_dossier_id": did,
            "text": "前旨作废，撤回成命",
        },
    )
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": revoke_id, "decision": "promulgated"}],
        content=content,
    )
    # 当回合：目标未关、无 0056、有哭谏 todo
    assert db.get_decree_dossier(did)["status"] == "executing"
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()["status"] == "active"
    assert _cost_events(db, did) == []
    assert int(state.metrics.get("皇威", 0) or 0) == auth_before
    pleas = _pending_pleas(db)
    assert len(pleas) == 1
    assert pleas[0]["criterion_text"] == "改弦"
    assert int(pleas[0]["stage_idx"]) == int(state.turn)

    scenes = list_due_review_scenes(db, state)
    assert any(s.get("kind") == "breach_plea" for s in scenes)


# ── 同承诺两次松手各有独立条 ──────────────────────────────────────────


def test_two_successive_loosenings_get_independent_pleas(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="twice")
    origin = f"dossier:{did}"
    db.record_issue_economy_move(
        state, "国库", -3, "月供", "历史供拨", origin_ref=origin, commit=True,
    )
    cid, _ = _insert_commitment(
        db, state, title="两度松手之诺", origin_ref=origin,
        ongoing_effects={}, bar_value=20, end_turn=state.turn + 40,
    )
    # 第一次：断供
    t1 = write_breach_plea_todo(
        db, state, commitment_ref=cid, breach_kind=BREACH_KIND_FUNDING,
        reason="断供", target_dossier_id=did, commit=True,
    )
    assert t1 > 0
    # 推进一回合后第二次：改弦
    state.turn += 1
    db.save_state(state)
    t2 = write_breach_plea_todo(
        db, state, commitment_ref=cid, breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="改弦", target_dossier_id=did, commit=True,
    )
    assert t2 > 0
    assert t2 != t1
    pleas = _pending_pleas(db)
    assert len(pleas) == 2
    stage_idxs = sorted(int(p["stage_idx"]) for p in pleas)
    assert stage_idxs[0] != stage_idxs[1]


# ── 反悔 / 坚持 ────────────────────────────────────────────────────────


def test_regret_via_extraction_true_entry_zero_damage(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="regret")
    origin = f"dossier:{did}"
    cid, _ = _insert_commitment(
        db, state, title="可反悔之诺", origin_ref=origin,
        bar_value=20, end_turn=state.turn + 20,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    write_breach_plea_todo(
        db, state, commitment_ref=cid, breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="欲撤", target_dossier_id=did, commit=True,
    )
    auth_before = int(state.metrics.get("皇威", 0) or 0)

    # 召对真入口：既有键 issue_advances / economy 续拨（禁 breach_plea_decisions 显式通道）
    out = apply_score_extraction(
        db, state,
        {
            "issue_advances": [{
                "issue_id": cid, "delta_bar": 1,
                "narrative": "朕加拨复其供亿，前诺照旧",
            }],
        },
        content=content,
    )
    assert out.get("breach_plea_resolutions")
    assert out["breach_plea_resolutions"][0]["decision"] == "regret"
    # 两轨零落账（反悔不写撑腰边）
    assert _cost_events(db, did) == []
    assert db.get_decree_dossier(did)["status"] == "executing"
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()["status"] == "active"
    assert int(state.metrics.get("皇威", 0) or 0) == auth_before
    assert _pending_pleas(db) == []
    assert db.conn.execute(
        "SELECT COUNT(*) AS c FROM relation_edge_events "
        "WHERE event_kind='撑腰' AND origin LIKE ?",
        (f"issue:{cid}:%",),
    ).fetchone()["c"] == 0


def test_persist_foundation_tiers(game):
    """坚持分支：三档根基各一用例；办到一半国势倒退写侧可查；无双扣。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    cases = [
        (FOUNDATION_JUST_STARTED, 10, "刚起头", "failed", False),
        (FOUNDATION_HALFWAY, 45, "办到一半", "failed", True),
        (FOUNDATION_ROOTED, 80, "根基已成", "degraded", False),
    ]
    for tier_name, bar, label, expect_outcome, expect_setback in cases:
        token = f"tier-{tier_name}"
        did, holder = _executing_policy_dossier(db, state, token=token)
        origin = f"dossier:{did}"
        if tier_name != FOUNDATION_JUST_STARTED:
            db.record_issue_economy_move(
                state, "国库", -10, "投入", f"{label}投入",
                origin_ref=origin, commit=True,
            )
        if tier_name == FOUNDATION_ROOTED:
            db.record_dossier_progress(
                did, state.turn, "告成", "已生根", is_terminal=False, commit=True,
            )
        elif tier_name == FOUNDATION_HALFWAY:
            db.record_dossier_progress(
                did, state.turn, "在办", "过半", is_terminal=False, commit=True,
            )
        cid, _ = _insert_commitment(
            db, state, title=f"{label}之诺", origin_ref=origin,
            bar_value=bar, end_turn=state.turn + 50,
            participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
        )
        assert assess_foundation_tier(db, cid) == tier_name

        todo_id = write_breach_plea_todo(
            db, state, commitment_ref=cid,
            breach_kind=BREACH_KIND_POLICY_REVERSAL,
            reason=f"坚持撤·{label}", target_dossier_id=did, commit=True,
        )
        todo = next(t for t in _pending_pleas(db) if int(t["id"]) == todo_id)
        minxin_before = int(state.metrics.get("民心", 0) or 0)
        result = finalize_persist(db, state, todo, commit=True)
        assert result["foundation_tier"] == tier_name
        assert result["outcome"] == expect_outcome
        assert result["breach_0056"] is True
        # 0056 恰一次
        breach_costs = _cost_events(db, did, identity="breach")
        assert breach_costs, f"{label} 应落 0056"
        # 幂等：不再双开
        assert db.breach_decree_dossier(state, did, reason="重复", commit=True) is False
        assert _cost_events(db, did, identity="breach") == breach_costs

        if expect_setback:
            assert result.get("setback")
            assert int(result["setback"].get("setback_issue_id") or 0) > 0
            assert int(state.metrics.get("民心", 0) or 0) < minxin_before
            # 0014 涌现缝：seed event_to_issue + event_triggers 终态账
            assert str(result["setback"].get("event_id") or "") == "breach_halfway_setback"
            setback_row = db.conn.execute(
                "SELECT title, status, origin_kind, origin_ref FROM issues WHERE id=?",
                (int(result["setback"]["setback_issue_id"]),),
            ).fetchone()
            assert setback_row is not None
            assert "半途而废" in str(setback_row["title"])
            assert str(setback_row["origin_kind"]) == "event_pool"
            assert str(setback_row["origin_ref"]) == "breach_halfway_setback"
            assert db.conn.execute(
                "SELECT 1 FROM event_triggers WHERE event_id=? AND terminal_state='triggered'",
                ("breach_halfway_setback",),
            ).fetchone() is not None
        else:
            assert not result.get("setback")

        # 承诺已停
        assert db.conn.execute(
            "SELECT status FROM issues WHERE id=?", (cid,),
        ).fetchone()["status"] == "dropped"


def test_persist_remove_sponsor_no_0056(game):
    """0041③：撤人坚持不触发 0056，事轴仍落。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="no56")
    origin = f"dossier:{did}"
    cid, _ = _insert_commitment(
        db, state, title="撤人不毁约名", origin_ref=origin,
        bar_value=15, end_turn=state.turn + 12,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    todo_id = write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_REMOVE_SPONSOR,
        reason="罢主办", target_dossier_id=did, commit=True,
    )
    todo = next(t for t in _pending_pleas(db) if int(t["id"]) == todo_id)
    result = finalize_persist(db, state, todo, commit=True)
    assert result["breach_0056"] is False
    assert _cost_events(db, did, identity="breach") == []
    assert result["outcome"] in {"failed", "degraded"}
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()["status"] == "dropped"


def test_persist_via_extraction_cancels_true_entry(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="persist-x")
    origin = f"dossier:{did}"
    cid, _ = _insert_commitment(
        db, state, title="extraction坚持", origin_ref=origin,
        bar_value=12, end_turn=state.turn + 15,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="仍撤", target_dossier_id=did, commit=True,
    )
    out = apply_score_extraction(
        db, state,
        {"cancels": [{"issue_id": cid, "narrative": "朕意已决，仍撤此诺"}]},
        content=content,
    )
    assert out.get("breach_plea_resolutions")
    assert out["breach_plea_resolutions"][0]["decision"] == "persist"
    assert _pending_pleas(db) == []
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()["status"] == "dropped"


# ── 沉默滚存 / 到期失效 ──────────────────────────────────────────────


def test_silence_keeps_pending_across_settle(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="silence")
    cid, _ = _insert_commitment(
        db, state, title="沉默滚存之诺", origin_ref=f"dossier:{did}",
        bar_value=20, end_turn=state.turn + 30,
    )
    write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_FUNDING, reason="断供",
        target_dossier_id=did, commit=True,
    )
    # 把 created_turn 调旧，使 apply 会扫到
    db.conn.execute(
        "UPDATE next_audience_todos SET created_turn=? WHERE entry_kind=?",
        (state.turn - 1, ENTRY_KIND_BREACH_PLEA),
    )
    db.conn.commit()
    results = apply_pending_due_reviews(db, state, commit=True)
    # 哭谏被 skip 保留
    skipped = [r for r in results if r.get("skipped") and r.get("entry_kind") == ENTRY_KIND_BREACH_PLEA]
    assert skipped
    assert _pending_pleas(db)
    assert db.get_decree_dossier(did)["status"] == "executing"

    # 再 settle 一拍仍 pending 可顶出
    _settle_empty_month(db, state, content)
    assert _pending_pleas(db)
    scenes = list_due_review_scenes(db, state)
    assert any(s.get("kind") == "breach_plea" for s in scenes)


def test_commitment_due_expires_plea_without_persist_damage(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="expire")
    due = state.turn  # 已到期
    cid, _ = _insert_commitment(
        db, state, title="到期失效之诺", origin_ref=f"dossier:{did}",
        bar_value=20, end_turn=due,
    )
    write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_POLICY_REVERSAL, reason="欲撤",
        target_dossier_id=did, commit=True,
    )
    auth_before = int(state.metrics.get("皇威", 0) or 0)
    expired = expire_breach_pleas_on_due(db, state, commit=True)
    assert expired
    assert expired[0]["reason"] == "commitment_due"
    assert _pending_pleas(db) == []
    # 不补 0056 / 事轴倒退
    assert _cost_events(db, did) == []
    assert int(state.metrics.get("皇威", 0) or 0) == auth_before
    # 承诺本身仍 active（#621 到期终局另管；此处只关挽留条）
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (cid,),
    ).fetchone()["status"] == "active"


# ── kind 对称闸 / 接管窗 / restore ────────────────────────────────────


def test_kind_gate_apply_only_finalizes_staged(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="kind-gate")
    # staged todo
    stages = [{
        "stage_idx": 0, "due_turn": state.turn,
        "criterion_text": "火器", "origin_context": "三年火器",
    }]
    from ming_sim.issues import apply_score_extraction as ase
    # 用 staged 写端
    from ming_sim.staged_commitment import write_due_staged_commitment_todos
    cid_staged, _ = _insert_commitment(
        db, state, title="分段闸测", origin_ref=f"dossier:{did}",
        stages=stages, bar_value=20,
    )
    write_due_staged_commitment_todos(db, state, commit=True)
    # breach plea
    cid_plea, _ = _insert_commitment(
        db, state, title="哭谏闸测", origin_ref=f"dossier:{did}",
        bar_value=20, end_turn=state.turn + 10,
    )
    # 同 dossier 第二承诺——改用独立 dossier 避免互相干扰
    did2, _ = _executing_policy_dossier(db, state, token="kind-gate-2")
    db.conn.execute("UPDATE issues SET origin_ref=? WHERE id=?", (f"dossier:{did2}", cid_plea))
    db.conn.commit()
    write_breach_plea_todo(
        db, state, commitment_ref=cid_plea,
        breach_kind=BREACH_KIND_FUNDING, reason="断", target_dossier_id=did2,
        commit=True,
    )
    db.conn.execute(
        "UPDATE next_audience_todos SET created_turn=?",
        (state.turn - 1,),
    )
    db.conn.commit()

    before_plea = _pending_pleas(db)
    assert before_plea
    results = apply_pending_due_reviews(db, state, commit=True)
    staged_done = [r for r in results if r.get("entry_kind") == ENTRY_KIND_STAGED and r.get("consumed")]
    plea_skip = [r for r in results if r.get("entry_kind") == ENTRY_KIND_BREACH_PLEA and r.get("skipped")]
    assert staged_done or any(
        str(t.get("entry_kind")) == ENTRY_KIND_STAGED
        and str(t.get("status")) == TODO_STATUS_CONSUMED
        for t in db.list_next_audience_todos()
    )
    assert plea_skip
    assert _pending_pleas(db), "哭谏须仍 pending"
    # 非 staged 未连坐 did2
    assert _cost_events(db, did2, identity="连坐") == []


def test_takeover_window_excludes_breach_plea(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="takeover-ex")
    cid, _ = _insert_commitment(
        db, state, title="不占接管窗", origin_ref=f"dossier:{did}",
        bar_value=20, end_turn=state.turn + 10,
    )
    write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_POLICY_REVERSAL, reason="欲撤",
        target_dossier_id=did, commit=True,
    )
    owned = dossiers_with_pending_due_review(db, state)
    assert did not in owned


def test_breach_plea_survives_restore(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="restore")
    cid, _ = _insert_commitment(
        db, state, title="restore挽留", origin_ref=f"dossier:{did}",
        bar_value=20, end_turn=state.turn + 20,
    )
    write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_MISAPPROPRIATION, reason="挪",
        target_dossier_id=did, commit=True,
    )
    path = db.path
    db.conn.close()
    from ming_sim.db import GameDB
    db2 = GameDB(path)
    state2 = db2.load_state()
    pleas = [
        t for t in db2.list_next_audience_todos(status=TODO_STATUS_PENDING)
        if t.get("entry_kind") == ENTRY_KIND_BREACH_PLEA
    ]
    assert len(pleas) == 1
    scenes = list_due_review_scenes(db2, state2)
    assert any(s.get("kind") == "breach_plea" for s in scenes)
    db2.close()


def test_no_decision_pause_on_breach_plea_settle(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="no-dec")
    db.record_issue_economy_move(
        state, "国库", -2, "月供", "史", origin_ref=f"dossier:{did}", commit=True,
    )
    _insert_commitment(
        db, state, title="不停轮", origin_ref=f"dossier:{did}",
        ongoing_effects={}, bar_value=15, end_turn=state.turn + 24,
    )
    report = _settle_empty_month(db, state, content)
    assert "<<DECISION>>" not in report
    assert state.turn_phase != TurnPhase.AWAITING_DECISION.value
    assert "AWAITING_DECISION" not in report


def test_try_defer_only_for_commitment_kind(game):
    """非承诺 initiative 不 defer——#523 锚形仍即时 breach。"""
    db, state, content = game
    did, holder = _executing_policy_dossier(db, state, token="non-commit")
    # 无 commitment_kind
    issue_id = db.insert_issue(
        state, kind="initiative", title="非承诺initiative",
        origin_kind="decree", origin_ref=f"dossier:{did}",
        cancellable="decree",
    )
    deferred = try_defer_revoke_to_breach_plea(
        db, state, target_dossier_id=did, target_issue_id=issue_id, reason="撤",
    )
    assert deferred is None


# ── 修后四组新增用例 ──────────────────────────────────────────────────


def test_same_turn_dual_breach_kinds_merge_not_swallowed(game):
    """同回合第二类松手不得静默吞：并入既有 pending + meta 记全被吞类。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="dual-kind")
    origin = f"dossier:{did}"
    db.record_issue_economy_move(
        state, "国库", -3, "月供", "历史供拨", origin_ref=origin, commit=True,
    )
    cid, _ = _insert_commitment(
        db, state, title="同回合双类之诺", origin_ref=origin,
        ongoing_effects={}, bar_value=20, end_turn=state.turn + 40,
        tags=["专款:国库"],
    )
    t1 = write_breach_plea_todo(
        db, state, commitment_ref=cid, breach_kind=BREACH_KIND_FUNDING,
        reason="断供", target_dossier_id=did, commit=True,
    )
    assert t1 > 0
    # 同回合第二类：改弦（不推进 turn）
    t2 = write_breach_plea_todo(
        db, state, commitment_ref=cid, breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="改弦", target_dossier_id=did, commit=True,
    )
    assert t2 == t1  # 并入同一条
    pleas = _pending_pleas(db)
    assert len(pleas) == 1
    from ming_sim.breach_plea import decode_plea_meta
    meta = decode_plea_meta(pleas[0]["origin_context"])
    assert meta.get("breach_kind") == BREACH_KIND_FUNDING
    absorbed = meta.get("absorbed_breach_kinds") or []
    assert BREACH_KIND_POLICY_REVERSAL in absorbed
    # try_defer 不得返空 todo_ids
    deferred = try_defer_revoke_to_breach_plea(
        db, state, target_dossier_id=did, reason="再撤", commit=True,
    )
    assert deferred and deferred.get("deferred")
    assert deferred.get("todo_ids"), "try_defer 不得返空 todo_ids 掩蔽"


def test_persist_reclaims_bundled_authority(game):
    """坚持落地=立即 revoke 路径：捆带授权收回 fail-loud。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="auth-bundle")
    origin = f"dossier:{did}"
    # 目标案卷授予一条授权
    db.conn.execute(
        "INSERT INTO authority_records "
        "(holder_id, privilege, scope, effective_turn, expires_turn, dossier_id, revoked) "
        "VALUES (?, ?, ?, ?, NULL, ?, 0)",
        (holder, "便宜行事", f"region:shaanxi", int(state.turn), int(did)),
    )
    db.conn.commit()
    auth_id = int(db.conn.execute(
        "SELECT id FROM authority_records WHERE dossier_id=? AND revoked=0",
        (did,),
    ).fetchone()["id"])
    cid, _ = _insert_commitment(
        db, state, title="捆带授权之诺", origin_ref=origin,
        bar_value=15, end_turn=state.turn + 20,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    todo_id = write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="坚持撤·捆带", target_dossier_id=did, commit=True,
    )
    todo = next(t for t in _pending_pleas(db) if int(t["id"]) == todo_id)
    result = finalize_persist(db, state, todo, commit=True)
    assert result["breach_0056"] is True
    row = db.conn.execute(
        "SELECT revoked FROM authority_records WHERE id=?", (auth_id,),
    ).fetchone()
    assert row is not None and int(row["revoked"] or 0) == 1
    assert result.get("authority_reclaims")


def test_remove_sponsor_persist_writes_credit_edge(game):
    """0079：撤人坚持撤有案卷时仍写辜负边（0056 不触发，不重复）。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, holder = _executing_policy_dossier(db, state, token="credit-rm")
    origin = f"dossier:{did}"
    cid, _ = _insert_commitment(
        db, state, title="撤人信用边", origin_ref=origin,
        bar_value=12, end_turn=state.turn + 12,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    todo_id = write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_REMOVE_SPONSOR,
        reason="罢主办", target_dossier_id=did, commit=True,
    )
    todo = next(t for t in _pending_pleas(db) if int(t["id"]) == todo_id)
    result = finalize_persist(db, state, todo, commit=True)
    assert result["breach_0056"] is False
    edges = list(db.conn.execute(
        "SELECT event_kind, target, origin FROM relation_edge_events "
        "WHERE target=? AND event_kind='辜负' ORDER BY id",
        (holder,),
    ).fetchall())
    assert edges, "撤人坚持须写 0079 辜负边"
    assert any(f"issue:{cid}" in str(e["origin"] or "") for e in edges)


def test_misappropriation_via_tags_producer_pipeline(game):
    """挪用真实管线：tags 专款写口（模拟 new_issues.tags producer）可达。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="mis-pipe")
    origin = f"dossier:{did}"
    # 经 insert_issue tags 参数（与 new_issues.tags 同写口）
    cid, _ = _insert_commitment(
        db, state, title="tags专款管线", origin_ref=origin,
        bar_value=20, end_turn=state.turn + 12,
        tags=["专款:国库", "清丈"],
        ongoing_effects={
            "economy": [{
                "account": "国库", "delta": -4,
                "category": "专款月供", "reason": "清丈专款",
            }],
        },
    )
    # 确认读口可达
    from ming_sim.breach_plea import _dedicated_accounts
    row = db.conn.execute("SELECT * FROM issues WHERE id=?", (cid,)).fetchone()
    assert "国库" in _dedicated_accounts(row)
    db.record_issue_economy_move(
        state, "国库", -6, "他用", "挪作赏功",
        origin_ref="盘面自发", commit=True,
    )
    written = scan_and_write_breach_pleas(db, state, commit=True)
    assert written
    assert any(p["criterion_text"] == "挪用" for p in _pending_pleas(db))
