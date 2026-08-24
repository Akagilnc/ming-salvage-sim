"""#626 反噬涌现挂轨——承诺所系后续事件。

Seams:
- trigger_commitment_backlashes（#625 形制硬门）
- pre_settle 邸报前既有挂点（与 trigger_supervision_countermeasures 同格）
- assess_foundation_tier 触发侧重算（零新列）
- find_any_issue_by_origin 幂等
- issue_advances.trigger_ref 溯源源承诺
- 与 #623 _apply_halfway_national_setback 去重（无双份 metrics 直击）
- 呈现哨兵：真实玩家面无系统词；bar 空串 web 条件渲染（无空括号/端标）；#625 区分经特征约束
- extractor commitment_backlash_facts 仅 module==issues 门控
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import ming_sim.commitment_backlash as backlash_mod
from ming_sim.breach_plea import (
    BREACH_KIND_POLICY_REVERSAL,
    FOUNDATION_HALFWAY,
    FOUNDATION_JUST_STARTED,
    FOUNDATION_ROOTED,
    HALFWAY_SETBACK_EVENT_ID,
    PLEA_VERDICT_EXPIRED,
    PLEA_VERDICT_KEY,
    PLEA_VERDICT_PERSIST,
    PLEA_VERDICT_REGRET,
    assess_foundation_tier,
    expire_breach_pleas_on_due,
    finalize_persist,
    finalize_regret,
    write_breach_plea_todo,
)
from ming_sim.commitment_backlash import (
    BACKLASH_BANNED_PLAYER_TOKENS,
    BACKLASH_NAMED_METRICS,
    BACKLASH_ORIGIN_KIND,
    SOURCE_BREACH_VERDICT,
    SOURCE_DEFORMATION_EXPOSURE,
    SOURCE_FAILED_TERMINAL,
    assert_no_backlash_banned_tokens,
    backlash_origin_ref,
    build_backlash_narrative_features,
    classify_backlash_source,
)
from ming_sim.constants import GATE_TABLES
from ming_sim.db import GameDB
from ming_sim.decree import pre_settle
from ming_sim.issues import (
    _expire_commitment_issue,
    _resolve_commitment_issue,
    apply_issue_inertia_and_ongoing,
    apply_score_extraction,
)
from ming_sim.models import TurnPhase, loads_effect_dict
from ming_sim.simulation import build_extractor_shared_context, build_simulator_payload
from ming_sim.staged_commitment import TODO_STATUS_PENDING


# ── fixtures ──────────────────────────────────────────────────────


def _holder(db) -> str:
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "ORDER BY name LIMIT 1"
    ).fetchone()["name"])


def _executing_policy_dossier(db, state, *, token: str = "bl-626", holder: str = ""):
    if not holder:
        holder = _holder(db)
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
    title: str,
    origin_ref: str,
    bar_value: int = 45,
    end_turn: int = 0,
    participants=None,
):
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title=title,
        origin_kind="decree",
        origin_ref=origin_ref,
        cancellable="decree",
        commitment_kind="until_stop",
        bar_value=bar_value,
        stage_text="在办",
        end_turn=int(end_turn or state.turn + 50),
        participants=participants,
    )
    return int(issue_id)


def _seed_halfway(db, state, *, did: int, bar: int = 45):
    """半途档：投入 + 在办进度 + mid bar。"""
    origin = f"dossier:{did}"
    db.record_issue_economy_move(
        state, "国库", -10, "投入", "半途投入",
        origin_ref=origin, commit=True,
    )
    db.record_dossier_progress(
        did, state.turn, "在办", "过半", is_terminal=False, commit=True,
    )
    return bar


def _pending_pleas(db):
    from ming_sim.breach_plea import ENTRY_KIND_BREACH_PLEA
    return [
        t for t in db.list_next_audience_todos(status=TODO_STATUS_PENDING)
        if str(t.get("entry_kind") or "") == ENTRY_KIND_BREACH_PLEA
    ]


def _backlash_issues(db):
    return [
        dict(r) for r in db.conn.execute(
            "SELECT * FROM issues WHERE origin_kind=? ORDER BY id",
            (BACKLASH_ORIGIN_KIND,),
        ).fetchall()
    ]


def _set_phase_runnable(state, db):
    """pre_settle 幂等守门：settling/issued 会早退，复位到召对相位。"""
    state.turn_phase = TurnPhase.SUMMONING.value
    db.save_state(state)


# ── AC1：三类触发各一 ─────────────────────────────────────────────


def test_ac1_breach_verdict_triggers_commitment_backlash(game):
    """事废判决（#623 finalize halfway）→ 次回合承诺所系反噬。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    did, holder = _executing_policy_dossier(db, state, token="bv")
    bar = _seed_halfway(db, state, did=did)
    cid = _insert_commitment(
        db, state, title="事废清丈之诺", origin_ref=f"dossier:{did}",
        bar_value=bar,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    assert assess_foundation_tier(db, cid) == FOUNDATION_HALFWAY

    todo_id = write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="坚持撤·事废", target_dossier_id=did, commit=True,
    )
    todo = next(t for t in _pending_pleas(db) if int(t["id"]) == todo_id)
    result = finalize_persist(db, state, todo, commit=True)
    assert result["outcome"] == "failed"
    assert "事废" in str(result.get("note") or "")
    # 当回合硬门不扫（一拍差）
    assert db.trigger_commitment_backlashes(state, commit=True) == []
    assert _backlash_issues(db) == []

    # 次回合
    state.turn = int(state.turn) + 1
    _set_phase_runnable(state, db)
    hits = db.trigger_commitment_backlashes(state, commit=True)
    assert hits, "事废判决次回合须立承诺所系反噬"
    assert hits[0]["source_kind"] == SOURCE_BREACH_VERDICT
    assert hits[0]["commitment_ref"] == cid
    assert hits[0]["trigger_ref"] == f"issue:{cid}"
    issue = db.find_any_issue_by_origin(
        BACKLASH_ORIGIN_KIND, backlash_origin_ref(cid, SOURCE_BREACH_VERDICT),
    )
    assert issue is not None
    assert str(issue["status"]) == "active"
    # trigger_ref 溯源
    adv = db.conn.execute(
        "SELECT trigger_kind, trigger_ref FROM issue_advances "
        "WHERE issue_id=? AND trigger_kind='commitment_backlash' ORDER BY id DESC LIMIT 1",
        (int(issue["id"]),),
    ).fetchone()
    assert adv is not None
    assert str(adv["trigger_ref"]) == f"issue:{cid}"


def test_ac1_failed_terminal_triggers_commitment_backlash(game):
    """烂尾终值（#621 执行格 failed → 结构化 failed_terminal）→ 反噬。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    did, holder = _executing_policy_dossier(db, state, token="ft")
    bar = _seed_halfway(db, state, did=did)
    cid = _insert_commitment(
        db, state, title="烂尾清丈之诺", origin_ref=f"dossier:{did}",
        bar_value=bar,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    assert assess_foundation_tier(db, cid) == FOUNDATION_HALFWAY

    # 直接落 #621 式烂尾终值；总纲：源类读执行格，不读 note 子串
    db.record_dossier_execution(
        did, "failed", "期限已过，诸事不济", int(state.turn),
        close=True, commit=True,
    )
    # 即便 note 含「事废」字样，执行格 failed 仍只归 failed_terminal（非子串判别）
    assert classify_backlash_source(execution_outcome="failed") == SOURCE_FAILED_TERMINAL
    assert classify_backlash_source(execution_outcome="failed") != SOURCE_BREACH_VERDICT

    # 当回合不触发
    assert db.trigger_commitment_backlashes(state, commit=True) == []

    state.turn = int(state.turn) + 1
    hits = db.trigger_commitment_backlashes(state, commit=True)
    assert hits
    assert hits[0]["source_kind"] == SOURCE_FAILED_TERMINAL
    assert hits[0]["commitment_ref"] == cid
    issue = db.find_any_issue_by_origin(
        BACKLASH_ORIGIN_KIND, backlash_origin_ref(cid, SOURCE_FAILED_TERMINAL),
    )
    assert issue is not None
    adv = db.conn.execute(
        "SELECT trigger_ref FROM issue_advances WHERE issue_id=? AND trigger_ref=?",
        (int(issue["id"]), f"issue:{cid}"),
    ).fetchone()
    assert adv is not None


def test_ac1_deformation_exposure_triggers_commitment_backlash(game):
    """变形暴露（#622 transformed + beyond_intent 分叉）→ 反噬。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    did, holder = _executing_policy_dossier(db, state, token="xf")
    bar = _seed_halfway(db, state, did=did)
    cid = _insert_commitment(
        db, state, title="变形清丈之诺", origin_ref=f"dossier:{did}",
        bar_value=bar,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    # #622 分叉读端：奏报假象 + 旨外实况
    db.record_dossier_progress(
        did, state.turn, "在办", "田亩清丈已十之八九",
        is_terminal=False, commit=True,
    )
    applied = apply_score_extraction(
        db, state,
        {
            "economy_moves": [{
                "account": "国库",
                "delta": 8,
                "category": "地方浮收",
                "reason": "借清丈之名额外加派",
                "origin_ref": f"dossier:{did}",
                "beyond_intent": True,
            }],
        },
        content=content,
    )
    assert applied.get("economy_moves")
    moves = db.list_economy_moves_for_dossier(did)
    # _seed_halfway 先落投入行；#622 分叉读端看 beyond_intent 实况行（非首行）
    assert moves and any(bool(m.get("beyond_intent")) for m in moves)

    db.record_dossier_execution(
        did, "transformed", "名实已乖，旨外受益", int(state.turn),
        close=True, commit=True,
    )
    assert db.get_decree_dossier(did)["execution_outcome"] == "transformed"

    assert db.trigger_commitment_backlashes(state, commit=True) == []

    state.turn = int(state.turn) + 1
    hits = db.trigger_commitment_backlashes(state, commit=True)
    assert hits
    assert hits[0]["source_kind"] == SOURCE_DEFORMATION_EXPOSURE
    assert hits[0]["trigger_ref"] == f"issue:{cid}"
    issue = db.find_any_issue_by_origin(
        BACKLASH_ORIGIN_KIND, backlash_origin_ref(cid, SOURCE_DEFORMATION_EXPOSURE),
    )
    assert issue is not None


def test_ac1_transformed_without_beyond_intent_does_not_trigger(game):
    """仅 transformed / 无 #622 分叉 beyond_intent → 不立反噬（AC1 负向成对）。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    did, holder = _executing_policy_dossier(db, state, token="xf-neg")
    bar = _seed_halfway(db, state, did=did)
    cid = _insert_commitment(
        db, state, title="无分叉变形之诺", origin_ref=f"dossier:{did}",
        bar_value=bar,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    # 仅落 transformed 终值，不种 beyond_intent 实况行
    db.record_dossier_execution(
        did, "transformed", "名实已乖（无旨外账）", int(state.turn),
        close=True, commit=True,
    )
    assert db.get_decree_dossier(did)["execution_outcome"] == "transformed"
    moves = db.list_economy_moves_for_dossier(did)
    assert not any(bool(m.get("beyond_intent")) for m in moves)

    state.turn = int(state.turn) + 1
    hits = db.trigger_commitment_backlashes(state, commit=True)
    assert hits == []
    assert db.find_any_issue_by_origin(
        BACKLASH_ORIGIN_KIND, backlash_origin_ref(cid, SOURCE_DEFORMATION_EXPOSURE),
    ) is None
    assert _backlash_issues(db) == []


# ── AC2：办到一半撤 + 与 #623 无双扣 ──────────────────────────────


def test_ac2_halfway_persist_one_national_plus_one_commitment_no_double_metrics(game):
    """坚持撤 halfway：一次全国余波（#623）+ 一次承诺所系一锤子（#626）；穿 settle 无续扣。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    did, holder = _executing_policy_dossier(db, state, token="dedup")
    bar = _seed_halfway(db, state, did=did)
    cid = _insert_commitment(
        db, state, title="去重清丈之诺", origin_ref=f"dossier:{did}",
        bar_value=bar,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )

    todo_id = write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="坚持撤·去重", target_dossier_id=did, commit=True,
    )
    todo = next(t for t in _pending_pleas(db) if int(t["id"]) == todo_id)

    minxin_0 = int(state.metrics.get("民心", 0) or 0)
    huangwei_0 = int(state.metrics.get("皇威", 0) or 0)

    result = finalize_persist(db, state, todo, commit=True)
    assert result.get("setback")
    assert str(result["setback"].get("event_id") or "") == HALFWAY_SETBACK_EVENT_ID
    # #623 全国余波 metrics 账恰一套（与 0056 皇威成本分立，不把 -5 算进本断言）
    assert dict(result["setback"].get("metrics_delta") or {}) == {"民心": -3, "皇威": -2}
    minxin_1 = int(state.metrics.get("民心", 0) or 0)
    huangwei_1 = int(state.metrics.get("皇威", 0) or 0)
    assert minxin_1 == max(0, minxin_0 - 3)
    # 皇威至少含 setback -2；0056 可另扣，但不得出现双份 setback（-4）
    assert huangwei_1 <= max(0, huangwei_0 - 2)
    assert huangwei_1 != max(0, huangwei_0 - 4)
    # 全国余波 issue 恰一条
    setback_count = db.conn.execute(
        "SELECT COUNT(*) AS c FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
        (HALFWAY_SETBACK_EVENT_ID,),
    ).fetchone()["c"]
    assert int(setback_count) == 1

    # 次回合承诺所系一锤子
    state.turn = int(state.turn) + 1
    hits = db.trigger_commitment_backlashes(state, commit=True)
    assert len(hits) == 1
    assert hits[0]["source_kind"] == SOURCE_BREACH_VERDICT
    assert hits[0]["trigger_ref"] == f"issue:{cid}"
    assert dict(hits[0].get("metrics_delta") or {}) == dict(BACKLASH_NAMED_METRICS)

    # #626 具名 metrics 恰一次（与 #623 -3/-2 套件分立，禁同套双扣）
    minxin_2 = int(state.metrics.get("民心", 0) or 0)
    huangwei_2 = int(state.metrics.get("皇威", 0) or 0)
    assert minxin_2 == minxin_1 + int(BACKLASH_NAMED_METRICS["民心"])
    assert huangwei_2 == huangwei_1 + int(BACKLASH_NAMED_METRICS["皇威"])
    # 无双份 #623 直击（不会再叠 -3/-2）
    assert minxin_2 == minxin_0 - 3 + int(BACKLASH_NAMED_METRICS["民心"])
    assert minxin_2 != minxin_0 - 6

    bl_issue = db.conn.execute(
        "SELECT id, ongoing_effects FROM issues WHERE id=?",
        (int(hits[0]["issue_id"]),),
    ).fetchone()
    assert bl_issue is not None
    ongoing = loads_effect_dict(bl_issue["ongoing_effects"])
    assert not (ongoing.get("metrics") or {}), ongoing  # 无镜像月扣

    # 全国余波仍一条；承诺所系一条（settle 隔离前先锁计数）
    assert int(db.conn.execute(
        "SELECT COUNT(*) AS c FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
        (HALFWAY_SETBACK_EVENT_ID,),
    ).fetchone()["c"]) == 1
    assert len(_backlash_issues(db)) == 1

    # 穿完整 settle：隔离他源 ongoing（#623 setback 自带月扣民心-1），只留本片
    # 断言本 issue 触发回合净变恰一次 BACKLASH_NAMED_METRICS，次月无续扣（I1）。
    db.conn.execute(
        "UPDATE issues SET status='dropped' WHERE status='active' AND origin_kind!=?",
        (BACKLASH_ORIGIN_KIND,),
    )
    db.conn.commit()
    apply_issue_inertia_and_ongoing(db, state)
    minxin_after_settle = int(state.metrics.get("民心", 0) or 0)
    huangwei_after_settle = int(state.metrics.get("皇威", 0) or 0)
    assert minxin_after_settle == minxin_2, (
        f"触发回合 settle 后民心被续扣：{minxin_2}→{minxin_after_settle}"
    )
    assert huangwei_after_settle == huangwei_2, (
        f"触发回合 settle 后皇威被续扣：{huangwei_2}→{huangwei_after_settle}"
    )

    # 次月：本 issue 不再引起 metrics 续扣（I1 与 settle 次数无关）
    state.turn = int(state.turn) + 1
    apply_issue_inertia_and_ongoing(db, state)
    assert int(state.metrics.get("民心", 0) or 0) == minxin_after_settle
    assert int(state.metrics.get("皇威", 0) or 0) == huangwei_after_settle


# ── AC3：负向对照 ─────────────────────────────────────────────────


def test_ac3_just_started_and_rooted_do_not_trigger(game):
    """刚起头撤 / 根基已成撤 → 不触发（分档重算，断言只落定性产物）。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    # 刚起头
    did_j, holder = _executing_policy_dossier(db, state, token="js")
    cid_j = _insert_commitment(
        db, state, title="刚起头之诺", origin_ref=f"dossier:{did_j}",
        bar_value=10,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    assert assess_foundation_tier(db, cid_j) == FOUNDATION_JUST_STARTED
    todo_j = write_breach_plea_todo(
        db, state, commitment_ref=cid_j,
        breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="刚起头撤", target_dossier_id=did_j, commit=True,
    )
    todo = next(t for t in _pending_pleas(db) if int(t["id"]) == todo_j)
    finalize_persist(db, state, todo, commit=True)
    # 无 setback（#623 也不落）
    # 根基已成
    did_r, _ = _executing_policy_dossier(db, state, token="rt")
    db.record_issue_economy_move(
        state, "国库", -10, "投入", "生根投入",
        origin_ref=f"dossier:{did_r}", commit=True,
    )
    db.record_dossier_progress(
        did_r, state.turn, "告成", "已生根", is_terminal=False, commit=True,
    )
    cid_r = _insert_commitment(
        db, state, title="根基已成之诺", origin_ref=f"dossier:{did_r}",
        bar_value=80,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    assert assess_foundation_tier(db, cid_r) == FOUNDATION_ROOTED
    todo_r = write_breach_plea_todo(
        db, state, commitment_ref=cid_r,
        breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="根基已成撤", target_dossier_id=did_r, commit=True,
    )
    todo2 = next(t for t in _pending_pleas(db) if int(t["id"]) == todo_r)
    finalize_persist(db, state, todo2, commit=True)

    state.turn = int(state.turn) + 1
    hits = db.trigger_commitment_backlashes(state, commit=True)
    # 定性：无 commitment_backlash issue
    assert hits == []
    assert _backlash_issues(db) == []


def test_ac3_regret_then_resolve_no_breach_verdict_hammer(game):
    """I2a：finalize_regret → resolve 结清 → 后续 pre_settle 不立 breach_verdict、metrics 不动。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    did, holder = _executing_policy_dossier(db, state, token="rg-rs")
    bar = _seed_halfway(db, state, did=did)
    cid = _insert_commitment(
        db, state, title="反悔后结清之诺", origin_ref=f"dossier:{did}",
        bar_value=bar,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    assert assess_foundation_tier(db, cid) == FOUNDATION_HALFWAY

    todo_id = write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="反悔·结清", target_dossier_id=did, commit=True,
    )
    todo = next(t for t in _pending_pleas(db) if int(t["id"]) == todo_id)
    result = finalize_regret(db, state, todo, commit=True)
    assert result["decision"] == "regret"
    assert result["commitment_continues"] is True
    stamped = next(
        t for t in db.list_next_audience_todos(status="consumed")
        if int(t["id"]) == todo_id
    )
    assert stamped["payload_json"].get(PLEA_VERDICT_KEY) == PLEA_VERDICT_REGRET

    # 承诺仍续跑后自然结清（resolved）
    row = db.conn.execute("SELECT * FROM issues WHERE id=?", (cid,)).fetchone()
    assert str(row["status"]) == "active"
    _resolve_commitment_issue(db, state, row, commit=True)
    closed = db.conn.execute(
        "SELECT status, closed_turn, bar_value FROM issues WHERE id=?", (cid,),
    ).fetchone()
    assert str(closed["status"]) == "resolved"
    assert int(closed["closed_turn"]) == int(state.turn)

    state.turn = int(state.turn) + 1
    _set_phase_runnable(state, db)
    # 硬门本身：metrics 一锤子不得落（与 pre_settle 财政噪声隔离）
    minxin_0 = int(state.metrics.get("民心", 0) or 0)
    huangwei_0 = int(state.metrics.get("皇威", 0) or 0)
    hits = db.trigger_commitment_backlashes(state, commit=True)
    assert hits == []
    assert int(state.metrics.get("民心", 0) or 0) == minxin_0
    assert int(state.metrics.get("皇威", 0) or 0) == huangwei_0

    # 同缝 pre_settle 亦不立 breach_verdict（幂等守门前复位相位）
    _set_phase_runnable(state, db)
    auto = pre_settle(state, db, content=content)
    bl = [a for a in (auto or []) if a.get("source") == "commitment_backlash"]
    assert bl == []
    assert db.find_any_issue_by_origin(
        BACKLASH_ORIGIN_KIND, backlash_origin_ref(cid, SOURCE_BREACH_VERDICT),
    ) is None
    assert _backlash_issues(db) == []


def test_ac3_regret_then_expire_dropped_no_hammer(game):
    """I2b：finalize_regret → expire 停账(dropped, bar 不变, HALFWAY) → 不打锤。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    did, holder = _executing_policy_dossier(db, state, token="rg-ex")
    bar = _seed_halfway(db, state, did=did)
    cid = _insert_commitment(
        db, state, title="反悔后到期之诺", origin_ref=f"dossier:{did}",
        bar_value=bar,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    assert assess_foundation_tier(db, cid) == FOUNDATION_HALFWAY

    todo_id = write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="反悔·到期", target_dossier_id=did, commit=True,
    )
    todo = next(t for t in _pending_pleas(db) if int(t["id"]) == todo_id)
    finalize_regret(db, state, todo, commit=True)

    row = db.conn.execute("SELECT * FROM issues WHERE id=?", (cid,)).fetchone()
    bar_before = int(row["bar_value"])
    _expire_commitment_issue(db, state, row, commit=True)
    closed = db.conn.execute(
        "SELECT status, closed_turn, bar_value FROM issues WHERE id=?", (cid,),
    ).fetchone()
    assert str(closed["status"]) == "dropped"
    assert int(closed["bar_value"]) == bar_before
    assert int(closed["closed_turn"]) == int(state.turn)
    # 停账后仍可评 HALFWAY（原 dropped 门会漏的链）
    assert assess_foundation_tier(db, cid) == FOUNDATION_HALFWAY

    minxin_0 = int(state.metrics.get("民心", 0) or 0)
    huangwei_0 = int(state.metrics.get("皇威", 0) or 0)

    state.turn = int(state.turn) + 1
    hits = db.trigger_commitment_backlashes(state, commit=True)
    assert hits == []
    assert db.find_any_issue_by_origin(
        BACKLASH_ORIGIN_KIND, backlash_origin_ref(cid, SOURCE_BREACH_VERDICT),
    ) is None
    assert _backlash_issues(db) == []
    assert int(state.metrics.get("民心", 0) or 0) == minxin_0
    assert int(state.metrics.get("皇威", 0) or 0) == huangwei_0


def test_ac3_plea_due_expire_then_commitment_expire_no_hammer(game):
    """I2c：expire_breach_pleas_on_due(commitment_due) → 承诺到期停账 → 不打锤。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    did, holder = _executing_policy_dossier(db, state, token="due-ex")
    bar = _seed_halfway(db, state, did=did)
    due = int(state.turn)
    cid = _insert_commitment(
        db, state, title="挽留到期停账之诺", origin_ref=f"dossier:{did}",
        bar_value=bar, end_turn=due,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    assert assess_foundation_tier(db, cid) == FOUNDATION_HALFWAY

    todo_id = write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="欲撤·到期失效", target_dossier_id=did, commit=True,
    )
    expired = expire_breach_pleas_on_due(db, state, commit=True)
    assert expired
    assert expired[0]["reason"] == "commitment_due"
    stamped = next(
        t for t in db.list_next_audience_todos(status="consumed")
        if int(t["id"]) == todo_id
    )
    assert stamped["payload_json"].get(PLEA_VERDICT_KEY) == PLEA_VERDICT_EXPIRED

    row = db.conn.execute("SELECT * FROM issues WHERE id=?", (cid,)).fetchone()
    assert str(row["status"]) == "active"
    bar_before = int(row["bar_value"])
    _expire_commitment_issue(db, state, row, commit=True)
    closed = db.conn.execute(
        "SELECT status, closed_turn, bar_value FROM issues WHERE id=?", (cid,),
    ).fetchone()
    assert str(closed["status"]) == "dropped"
    assert int(closed["bar_value"]) == bar_before
    assert assess_foundation_tier(db, cid) == FOUNDATION_HALFWAY

    minxin_0 = int(state.metrics.get("民心", 0) or 0)
    huangwei_0 = int(state.metrics.get("皇威", 0) or 0)

    state.turn = int(state.turn) + 1
    hits = db.trigger_commitment_backlashes(state, commit=True)
    assert hits == []
    assert db.find_any_issue_by_origin(
        BACKLASH_ORIGIN_KIND, backlash_origin_ref(cid, SOURCE_BREACH_VERDICT),
    ) is None
    assert _backlash_issues(db) == []
    assert int(state.metrics.get("民心", 0) or 0) == minxin_0
    assert int(state.metrics.get("皇威", 0) or 0) == huangwei_0


def test_ac3_persist_stamps_verdict_and_still_triggers(game):
    """I3 辅证：finalize_persist 落 verdict=persist；次回合 breach_verdict 仍触发。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    did, holder = _executing_policy_dossier(db, state, token="pv")
    bar = _seed_halfway(db, state, did=did)
    cid = _insert_commitment(
        db, state, title="坚持撤既判之诺", origin_ref=f"dossier:{did}",
        bar_value=bar,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    todo_id = write_breach_plea_todo(
        db, state, commitment_ref=cid,
        breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="坚持撤·痕迹", target_dossier_id=did, commit=True,
    )
    todo = next(t for t in _pending_pleas(db) if int(t["id"]) == todo_id)
    finalize_persist(db, state, todo, commit=True)
    stamped = next(
        t for t in db.list_next_audience_todos(status="consumed")
        if int(t["id"]) == todo_id
    )
    assert stamped["payload_json"].get(PLEA_VERDICT_KEY) == PLEA_VERDICT_PERSIST

    state.turn = int(state.turn) + 1
    hits = db.trigger_commitment_backlashes(state, commit=True)
    assert hits
    assert hits[0]["source_kind"] == SOURCE_BREACH_VERDICT
    assert hits[0]["commitment_ref"] == cid


# ── AC4：restore 无损 ─────────────────────────────────────────────


def test_ac4_backlash_survives_restore_both_states(game, tmp_path, content):
    """触发前/后两态 backup→restore 无损。"""
    db, state, _content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    did, holder = _executing_policy_dossier(db, state, token="rs")
    bar = _seed_halfway(db, state, did=did)
    cid = _insert_commitment(
        db, state, title="restore之诺", origin_ref=f"dossier:{did}",
        bar_value=bar,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    db.record_dossier_execution(
        did, "failed", "期限已过，诸事不济", int(state.turn),
        close=True, commit=True,
    )

    # 触发前
    pre = tmp_path / "pre-626.db"
    db.backup_to(str(pre))
    restored_pre = GameDB(str(pre), content=content)
    try:
        assert restored_pre.trigger_commitment_backlashes(
            restored_pre.load_state(), commit=True,
        ) == []  # 同 turn 一拍差
        st = restored_pre.load_state()
        st.turn = int(st.turn) + 1
        hits_pre = restored_pre.trigger_commitment_backlashes(st, commit=True)
        assert hits_pre
    finally:
        restored_pre.close()

    # 原库触发后
    state.turn = int(state.turn) + 1
    hits = db.trigger_commitment_backlashes(state, commit=True)
    assert hits
    origin = backlash_origin_ref(cid, SOURCE_FAILED_TERMINAL)
    issue_id = int(hits[0]["issue_id"])

    post = tmp_path / "post-626.db"
    db.backup_to(str(post))
    restored_post = GameDB(str(post), content=content)
    try:
        row = restored_post.find_any_issue_by_origin(BACKLASH_ORIGIN_KIND, origin)
        assert row is not None
        assert int(row["id"]) == issue_id
        st2 = restored_post.load_state()
        # 幂等：restore 后重跑不双立
        again = restored_post.trigger_commitment_backlashes(st2, commit=True)
        assert again == []
        assert int(restored_post.conn.execute(
            "SELECT COUNT(*) AS c FROM issues WHERE origin_kind=? AND origin_ref=?",
            (BACKLASH_ORIGIN_KIND, origin),
        ).fetchone()["c"]) == 1
        adv = restored_post.conn.execute(
            "SELECT trigger_ref FROM issue_advances WHERE issue_id=? AND trigger_ref=?",
            (issue_id, f"issue:{cid}"),
        ).fetchone()
        assert adv is not None
    finally:
        restored_post.close()


# ── AC5：无平行结算 / 挂点 / 幂等 / 不扩 gate ─────────────────────


def test_ac5_hook_idempotent_no_gate_table_expansion(game):
    """硬门挂邸报前既有挂点；幂等；调用侧无第二扫描；GATE_TABLES 不动。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    # 挂点：pre_settle 源码恰一处调用
    src = inspect.getsource(pre_settle)
    assert "trigger_commitment_backlashes" in src
    assert src.count("trigger_commitment_backlashes") == 1
    assert "trigger_supervision_countermeasures" in src  # 同格既有挂点

    # 不扩 GATE_TABLES
    assert GATE_TABLES == (
        "region", "army", "building", "power", "class", "faction", "character", "event",
    )
    # 硬门实现不引用 trigger_gate 求值
    gate_src = inspect.getsource(GameDB.trigger_commitment_backlashes)
    assert "evaluate_trigger_gate" not in gate_src
    assert "GATE_TABLES" not in gate_src

    did, holder = _executing_policy_dossier(db, state, token="idemp")
    bar = _seed_halfway(db, state, did=did)
    cid = _insert_commitment(
        db, state, title="幂等之诺", origin_ref=f"dossier:{did}",
        bar_value=bar,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    db.record_dossier_execution(
        did, "failed", "期限已过，诸事不济", int(state.turn),
        close=True, commit=True,
    )
    state.turn = int(state.turn) + 1
    first = db.trigger_commitment_backlashes(state, commit=True)
    assert len(first) == 1
    second = db.trigger_commitment_backlashes(state, commit=True)
    assert second == []
    assert len(_backlash_issues(db)) == 1

    # pre_settle 路径也只产一条（相位可跑）
    _set_phase_runnable(state, db)
    # 已幂等，pre_settle 再跑不应新立
    auto = pre_settle(state, db, content=content)
    bl = [a for a in (auto or []) if a.get("source") == "commitment_backlash"]
    assert bl == []
    assert len(_backlash_issues(db)) == 1


# ── AC6：呈现哨兵 ─────────────────────────────────────────────────


def test_ac6_presentation_sentinel_distinct_from_625(game):
    """真实玩家面：无系统词裸露；bar 空串无空括号/端标（甲）；#625 区分经特征约束。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    did, holder = _executing_policy_dossier(db, state, token="sent")
    bar = _seed_halfway(db, state, did=did)
    cid = _insert_commitment(
        db, state, title="哨兵之诺", origin_ref=f"dossier:{did}",
        bar_value=bar,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    db.record_dossier_execution(
        did, "failed", "期限已过，诸事不济", int(state.turn),
        close=True, commit=True,
    )
    state.turn = int(state.turn) + 1
    hits = db.trigger_commitment_backlashes(state, commit=True)
    assert hits
    assert hits[0]["source_kind"] == SOURCE_FAILED_TERMINAL
    issue = db.conn.execute(
        "SELECT * FROM issues WHERE id=?", (int(hits[0]["issue_id"]),),
    ).fetchone()
    assert issue is not None

    # 机读身份保留 origin_kind/origin_ref；tags 不承载系统词
    assert str(issue["origin_kind"]) == BACKLASH_ORIGIN_KIND
    assert str(issue["origin_ref"]) == backlash_origin_ref(cid, SOURCE_FAILED_TERMINAL)
    tags = json.loads(str(issue["tags"] or "[]"))
    assert isinstance(tags, list)
    for tag in tags:
        assert_no_backlash_banned_tokens(tag, surface="tags")

    # P7：硬门不得再落 bar/stage/narrative 成句常量；与 #625 反制 bar 区分
    assert not hasattr(backlash_mod, "build_backlash_copy")
    assert not hasattr(backlash_mod, "BACKLASH_BAR_GOOD")
    assert not hasattr(backlash_mod, "BACKLASH_BAR_BAD")
    assert not hasattr(backlash_mod, "BACKLASH_CODE_FIXED_PHRASES")
    assert not hasattr(backlash_mod, "assert_no_backlash_code_fixed_phrases")
    gate_src = inspect.getsource(GameDB.trigger_commitment_backlashes)
    assert "build_backlash_copy" not in gate_src
    assert "所系余波" not in gate_src
    assert "反噬平息" not in gate_src
    assert "反噬坐大" not in gate_src
    assert "classify_backlash_source" in gate_src
    # 总纲：删『事废 in note』子串判别；classify 签名与实现均不读 note
    cls_src = inspect.getsource(classify_backlash_source)
    assert "execution_note" not in cls_src
    assert "execution_note" not in inspect.signature(classify_backlash_source).parameters
    assert "'事废' in" not in cls_src and '"事废" in' not in cls_src
    assert "in note" not in cls_src
    # 硬门调用 classify 时不传 note
    assert "execution_note=" not in gate_src
    assert "execution_note=row" not in gate_src

    # 真实玩家面：title 仅源承诺事实链接；stage/narrative/bar 硬门留空
    assert str(issue["title"]) == "哨兵之诺"
    assert str(issue["stage_text"] or "") == ""
    assert str(issue["bar_good_meaning"] or "") == ""
    assert str(issue["bar_bad_meaning"] or "") == ""
    assert "反噬平息" not in str(issue["bar_good_meaning"] or "")
    assert "反噬坐大" not in str(issue["bar_bad_meaning"] or "")

    player_surfaces = (
        ("title", issue["title"]),
        ("stage_text", issue["stage_text"]),
        ("bar_good", issue["bar_good_meaning"]),
        ("bar_bad", issue["bar_bad_meaning"]),
    )
    for surface_name, text in player_surfaces:
        assert_no_backlash_banned_tokens(text, surface=surface_name)

    adv = db.conn.execute(
        "SELECT narrative, to_stage_text FROM issue_advances "
        "WHERE issue_id=? ORDER BY id DESC LIMIT 1",
        (int(issue["id"]),),
    ).fetchone()
    assert str(adv["narrative"] or "") == ""
    assert str(adv["to_stage_text"] or "") == ""
    assert_no_backlash_banned_tokens(adv["narrative"], surface="narrative")
    assert_no_backlash_banned_tokens(adv["to_stage_text"], surface="advance.stage")

    # issue_payloads 对应字段（web situation 主行/tip 同源）不得裸露禁词
    payload_fields = {
        "title": issue["title"],
        "stage_text": issue["stage_text"],
        "bar_good_meaning": issue["bar_good_meaning"],
        "bar_bad_meaning": issue["bar_bad_meaning"],
        "tags": tags,
    }
    payload_blob = json.dumps(payload_fields, ensure_ascii=False)
    assert_no_backlash_banned_tokens(payload_blob, surface="issue_payloads")

    # 特征化输入注入叙事步；#625 用语区分以约束传递（非代码 bar 常量）
    features = build_backlash_narrative_features(db)
    assert features and int(features[0]["issue_id"]) == int(issue["id"])
    assert features[0]["commitment_ref"] == cid
    assert features[0]["commitment_title"] == "哨兵之诺"
    assert features[0]["source_kind"] == SOURCE_FAILED_TERMINAL
    constraints = features[0]["presentation_constraints"]
    assert "反噬平息" in constraints["avoid_phrases"]
    assert "反噬坐大" in constraints["avoid_phrases"]
    payload = build_simulator_payload(
        state, db, decree_text="试", previous_narrative="",
    )
    assert "commitment_backlash_facts" in payload
    assert payload["commitment_backlash_facts"]
    assert int(payload["commitment_backlash_facts"][0]["issue_id"]) == int(issue["id"])

    # 禁词表含 #625 反制用语与系统词
    for token in ("反噬平息", "反噬坐大", "commitment_backlash", "foundation_tier"):
        assert token in BACKLASH_BANNED_PLAYER_TOKENS

    # AC6 增断（甲）：玩家面无空括号/空端标——硬门 bar 空 + 无 LLM bar 写口
    # + web 条件渲染；advance_issue 不写 bar_*_meaning；season_simulator 不承诺 bar 语义
    advance_src = inspect.getsource(GameDB.advance_issue)
    assert "bar_good_meaning" not in advance_src
    assert "bar_bad_meaning" not in advance_src
    root = Path(__file__).resolve().parents[1]
    sim_prompt = (root / "content/prompts/season_simulator.md").read_text(encoding="utf-8")
    # 反噬段不得再要求 LLM 长出进度条两端文案（甲：无 bar 写口）
    bl_idx = sim_prompt.find("commitment_backlash_facts")
    assert bl_idx >= 0
    bl_section = sim_prompt[bl_idx: bl_idx + 600]
    assert "bar 语义" not in bl_section
    assert "进度条两端文案不在本步填写" in bl_section
    assert "标题/阶段/叙述/bar" not in bl_section
    web_src = (root / "web/src/components/situation.tsx").read_text(encoding="utf-8")
    assert "outcomeHead" in web_src
    assert "barLabel" in web_src
    # 空串渲染契约：不得再无条件插值『达成（{bar}）』
    assert "达成（{issue.bar_good_meaning}）" not in web_src
    assert "失败（{issue.bar_bad_meaning}）" not in web_src
    # 空 bar 时玩家可见面不得出现空括号（web 契约由 outcomeHead 保证）
    good = str(issue["bar_good_meaning"] or "").strip()
    bad = str(issue["bar_bad_meaning"] or "").strip()
    assert good == "" and bad == ""
    # 等价于 web outcomeHead：空 → 仅『达成』/『失败』，无『（）』
    assert (f"达成（{good}）" if good else "达成") == "达成"
    assert (f"失败（{bad}）" if bad else "失败") == "失败"
    assert "达成（）" not in (f"达成（{good}）" if good else "达成")
    assert "失败（）" not in (f"失败（{bad}）" if bad else "失败")


def test_extractor_commitment_backlash_facts_gated_to_issues_module(game):
    """#626 P3：commitment_backlash_facts 仅 module==issues；他模块不得见。"""
    db, state, _content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    did, holder = _executing_policy_dossier(db, state, token="xgate")
    bar = _seed_halfway(db, state, did=did)
    _insert_commitment(
        db, state, title="门控之诺", origin_ref=f"dossier:{did}",
        bar_value=bar,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
    )
    db.record_dossier_execution(
        did, "failed", "期限已过，诸事不济", int(state.turn),
        close=True, commit=True,
    )
    state.turn = int(state.turn) + 1
    hits = db.trigger_commitment_backlashes(state, commit=True)
    assert hits

    issues_ctx = build_extractor_shared_context(
        db, state, "邸报", "", module="issues",
        transit_semantics=[],
    )
    assert "commitment_backlash_facts" in issues_ctx
    assert issues_ctx["commitment_backlash_facts"]
    assert int(issues_ctx["commitment_backlash_facts"][0]["issue_id"]) == int(
        hits[0]["issue_id"]
    )

    for module in ("internal", "military_external", "personnel_secret"):
        other = build_extractor_shared_context(
            db, state, "邸报", "", module=module,
        )
        assert "commitment_backlash_facts" not in other, (
            f"{module} 不得注入 commitment_backlash_facts"
        )

    # 无门副本已撤：_extractor_context_payload 不再常驻该键
    from ming_sim.simulation import _extractor_context_payload

    base = _extractor_context_payload(db, state, "邸报", "")
    assert "commitment_backlash_facts" not in base
