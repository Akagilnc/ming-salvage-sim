"""#1503 拨饷诏颁布即落账销欠。

Seams:
- stage_grant_allocation_candidate / commit_pending_actions（成案结构化载荷）
- apply_dossier_verdicts / apply_dossier_promulgation（颁布缝一次消费）
- _apply_economy_list / _pay_single_army_arrears（扣库+销欠 + ADR 0023 clamp）
- apply_score_extraction economy_moves 过滤（单写者；extractor 不二扣）
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import ming_sim.action_materialize  # noqa: F401 -- installs package catalog
from ming_sim.action_clusters import candidates_from_classifier_payload
from ming_sim.action_materialize import MaterializeCtx, run_materialize_pipeline
from ming_sim.issues import apply_score_extraction
from tests.dossier_test_helpers import rejected_verdict as _rejected_verdict


def _ctx(db, character, candidates, turn, *, message, reply):
    return MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=turn)),
        character=SimpleNamespace(name=character, office_type="文官"),
        player_message=message,
        reply=reply,
        message_text=message,
        explicit_prefixed=False, has_directive=False, pend_for_minister=[], out={},
        intent=None, intent_kind="none", llm_config=None, intent_candidates=candidates,
    )


def _stage_xiexang(db, turn, *, amount, account="国库", target_id="guanning",
                   message=None, reply=None, **extra):
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    payload = {
        "kind": "grant_allocation",
        "grant_action": "协饷",
        "amount": amount,
        "account": account,
        "purpose": extra.pop("purpose", "补饷"),
        "target_kind": "army",
        "target_id": target_id,
        **extra,
    }
    candidate = candidates_from_classifier_payload(payload, soft=False)
    spoken = message or f"拨{target_id}军饷{amount}万两。"
    ctx = _ctx(
        db, actor, candidate, turn,
        message=spoken,
        reply=reply or f"臣请户部发帑{amount}万两协济，请陛下定夺准驳。",
    )
    run_materialize_pipeline(ctx)
    return ctx


def _close_night_dossier(db, state, content, pending_id):
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    return next(
        d for d in db.list_decree_dossiers()
        if d["pending_action_id"] == pending_id
    )


def _set_guanning_arrears(db, arrears: float, *, central: float | None = None,
                          province: float | None = None) -> None:
    if central is None and province is None:
        central = float(arrears)
        province = 0.0
    elif central is None:
        central = max(0.0, float(arrears) - float(province or 0))
    elif province is None:
        province = max(0.0, float(arrears) - float(central or 0))
    db.conn.execute(
        """
        UPDATE armies
        SET arrears=?, province_pay_arrears=?, central_pay_arrears=?
        WHERE id='guanning'
        """,
        (float(arrears), float(province), float(central)),
    )
    db.conn.commit()


def _army_row(db, army_id="guanning"):
    return dict(db.conn.execute(
        "SELECT arrears, province_pay_arrears, central_pay_arrears FROM armies WHERE id=?",
        (army_id,),
    ).fetchone())


def _promulgate(db, state, content, dossier_id, decision="promulgated"):
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier_id, "decision": decision}],
        content=content,
    )


# ── ① 成案结构化载荷 ──────────────────────────────────────────────

def test_xiexang_stages_structured_pay_payload(game):
    """成案载荷必含 amount/account/purpose=补饷/target_kind=army/target_id。"""
    db, state, content = game
    ctx = _stage_xiexang(
        db, state.turn, amount=15, target_id="guanning",
        message="拨关宁军饷十五万两。",
    )
    pending_id = ctx.out["pending_action_id"]
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["payload_json"])
    assert pending["dossier_action_type"] == "grant_allocation"
    assert pending["grant_action"] == "协饷"
    assert int(pending["amount"]) == 15
    assert pending["account"] == "国库"
    assert pending["purpose"] == "补饷"
    assert pending["target_kind"] == "army"
    assert pending["target_id"] == "guanning"

    dossier = _close_night_dossier(db, state, content, pending_id)
    payload = json.loads(dossier["payload_json"])
    assert payload["purpose"] == "补饷"
    assert payload["target_kind"] == "army"
    assert payload["target_id"] == "guanning"
    assert int(payload["amount"]) == 15
    assert payload["account"] == "国库"


def test_army_pay_missing_fields_fail_loud_at_admission(game):
    """真实成案 admission 同时缺五项：一次 typed 聚合，案卷/账本/国库零写。"""
    db, state, content = game
    treasury_before = int(state.metrics["国库"])
    ledger_before = db.conn.execute("SELECT COUNT(*) AS n FROM economy_ledger").fetchone()["n"]
    before_ids = {int(d["id"]) for d in db.list_decree_dossiers()}
    candidate_id = db.stage_pending_action(
        state.turn, "directive", "拟旨", "兵部尚书",
        {"text": "拟旨如下：准拨军饷。"},
    )
    from ming_sim.action_materialize import IncompleteXiexangPayloadError

    with pytest.raises(IncompleteXiexangPayloadError) as caught:
        db.update_directive_candidate(
            candidate_id,
            {
                "text": "拟旨如下：准拨军饷。",
                "dossier_action_type": "grant_allocation",
                "grant_action": "协饷",
            },
        )
    assert caught.value.missing_fields == (
        "amount", "account", "purpose", "target_kind", "target_id",
    )
    with pytest.raises(IncompleteXiexangPayloadError) as cadence_error:
        from ming_sim.action_materialize import require_explicit_xiexang_fields
        require_explicit_xiexang_fields(
            amount=15, account="国库", purpose="补饷",
            target_kind="army", target_id="guanning", cadence="每季",
        )
    assert "cadence" in cadence_error.value.missing_fields
    assert {int(d["id"]) for d in db.list_decree_dossiers()} == before_ids
    assert int(state.metrics["国库"]) == treasury_before
    ledger_after = db.conn.execute("SELECT COUNT(*) AS n FROM economy_ledger").fetchone()["n"]
    assert ledger_after == ledger_before


def test_xiexang_unresolvable_target_rejected_before_pending(game):
    """五项齐全但 target 无法解析为军队：fail-loud、零写入。"""
    db, state, content = game
    from ming_sim.action_materialize import stage_grant_allocation_candidate

    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    treasury_before = int(state.metrics["国库"])
    before_ids = {int(d["id"]) for d in db.list_decree_dossiers()}
    before_pending = db.list_pending_actions(state.turn, minister_name=actor)

    with pytest.raises(ValueError, match=r"协饷旨意 target 无法解析为军队"):
        stage_grant_allocation_candidate(
            db, state.turn, actor,
            text="臣请协饷辽东。",
            grant_action="协饷",
            target_kind="army",
            target_id="liaodong",
            amount=15,
            account="国库",
            purpose="补饷",
        )
    after_pending = db.list_pending_actions(state.turn, minister_name=actor)
    assert len(after_pending) == len(before_pending)
    assert int(state.metrics["国库"]) == treasury_before
    after_ids = {int(d["id"]) for d in db.list_decree_dossiers()}
    assert after_ids == before_ids


def test_revise_away_from_xiexang_clears_pay_only_fields(game):
    """改案离开协饷时清 purpose/immediate，不得残留销欠语义。"""
    db, state, content = game
    from ming_sim.action_materialize import stage_grant_allocation_candidate

    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    first_id = stage_grant_allocation_candidate(
        db, state.turn, actor,
        text="臣请协饷关宁十五万。",
        grant_action="协饷",
        target_kind="army",
        target_id="guanning",
        amount=15,
        account="国库",
        purpose="补饷",
    )
    assert first_id > 0
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (first_id,),
    ).fetchone()["payload_json"])
    assert pending["purpose"] == "补饷"
    assert pending.get("execution_surface") == "immediate"

    updated = stage_grant_allocation_candidate(
        db, state.turn, actor,
        text="臣请改拨军械项目经费十万。",
        grant_action="项目经费",
        target_kind="army",
        target_id="guanning",
        amount=10,
        account="国库",
        target_candidate=str(first_id),
    )
    assert updated == first_id
    revised = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (first_id,),
    ).fetchone()["payload_json"])
    assert revised["grant_action"] == "项目经费"
    assert revised.get("purpose") in (None, "")
    assert not db._is_army_pay_grant_payload(revised)
    assert revised.get("execution_surface") != "immediate" or revised.get("purpose") != "补饷"


# ── ② 颁布缝一次消费：扣库+销欠同回合 ────────────────────────────

def test_promulgation_settle_applies_once_ready_replay_no_double_debit(game, monkeypatch):
    """颁布缝落账恰一次；ready=1 恢复重放不二扣。"""
    import ming_sim.decree as dm
    from ming_sim.decree import persist_resolve_context, pre_settle
    from ming_sim.session import TurnPhase
    from tests.test_advance_paths_atomic import _recovery_session

    db, state, content = game
    _set_guanning_arrears(db, 60, central=60, province=0)
    state.metrics["国库"] = max(int(state.metrics["国库"]), 100)

    ctx = _stage_xiexang(db, state.turn, amount=15, target_id="guanning")
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    did = int(dossier["id"])

    turn = state.turn
    pre_settle(state, db, content=content)
    assert state.turn_phase == TurnPhase.SETTLING.value
    arrears_after_pre = _army_row(db)["arrears"]

    persist_resolve_context(
        db, turn,
        {},
        decree_text="拨饷诏",
        narrative="已存邸报……",
        simulator_payload={
            "dossier_verdicts": [{"dossier_id": did, "decision": "promulgated"}],
        },
        secret_orders=[],
        relevant_memories=[],
    )
    ready = db.get_resolve_context(turn)
    assert ready is not None and ready.get("extracted") is not None
    assert (ready.get("simulator_payload") or {}).get("dossier_verdicts") == [
        {"dossier_id": did, "decision": "promulgated"},
    ]

    def _must_not_run(*a, **k):
        raise AssertionError("恢复直入 apply 不应重跑 simulator/extractor")
    monkeypatch.setattr(dm, "simulate_season_with_payload", _must_not_run)
    monkeypatch.setattr(dm, "extract_scores_by_modules_with_agno", _must_not_run)

    result = _recovery_session(db, state, content, monkeypatch).resolve_turn()

    assert result.awaiting is False
    assert state.turn == turn + 1
    assert db.get_resolve_context(turn) is None
    moves = db.list_economy_moves_for_dossier(did)
    assert len(moves) == 1
    assert int(moves[0]["delta"]) == -15
    pay_ledger = [
        dict(r) for r in db.conn.execute(
            """
            SELECT delta, origin_ref FROM economy_ledger
            WHERE purpose='补饷' AND origin_ref=?
            """,
            (f"dossier:{did}",),
        ).fetchall()
    ]
    assert len(pay_ledger) == 1
    assert int(pay_ledger[0]["delta"]) == -15
    assert _army_row(db)["arrears"] == pytest.approx(arrears_after_pre - 15)


def test_rejected_and_hold_leave_zero_ledger(game):
    """拒颁/留中：零落账。"""
    db, state, content = game
    _set_guanning_arrears(db, 60, central=60, province=0)
    state.metrics["国库"] = max(int(state.metrics["国库"]), 100)
    treasury_before = int(state.metrics["国库"])
    before = _army_row(db)

    # 拒颁
    ctx = _stage_xiexang(db, state.turn, amount=15, target_id="guanning")
    d1 = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    db.apply_dossier_verdicts(state, [_rejected_verdict(d1["id"])], content=content)
    assert db.list_economy_moves_for_dossier(d1["id"]) == []
    assert int(state.metrics["国库"]) == treasury_before
    assert _army_row(db)["arrears"] == pytest.approx(before["arrears"])

    # 留中：打回后 hold
    ctx2 = _stage_xiexang(
        db, state.turn, amount=12, target_id="guanning",
        message="再拨关宁十二万。",
    )
    d2 = _close_night_dossier(db, state, content, ctx2.out["pending_action_id"])
    db.apply_dossier_verdicts(state, [_rejected_verdict(d2["id"])], content=content)
    db.apply_dossier_promulgation(state, d2["id"], "hold", content=content)
    assert db.list_economy_moves_for_dossier(d2["id"]) == []
    assert int(state.metrics["国库"]) == treasury_before
    assert _army_row(db)["arrears"] == pytest.approx(before["arrears"])


# ── ④ 协饷同规 + ADR 0023 clamp ──────────────────────────────────

def test_xiexang_clamp_when_amount_exceeds_arrears(game):
    """余额/超欠沿 ADR 0023 clamp：实扣=欠额，残余不落账。"""
    db, state, content = game
    _set_guanning_arrears(db, 8, central=8, province=0)
    state.metrics["国库"] = max(int(state.metrics["国库"]), 100)
    treasury_before = int(state.metrics["国库"])

    ctx = _stage_xiexang(db, state.turn, amount=15, target_id="guanning")
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    _promulgate(db, state, content, dossier["id"])

    moves = db.list_economy_moves_for_dossier(dossier["id"])
    assert len(moves) == 1
    assert int(moves[0]["delta"]) == -8  # clamp to arrears
    assert int(state.metrics["国库"]) == treasury_before - 8
    assert _army_row(db)["arrears"] == pytest.approx(0)


def test_xiexang_clamp_when_treasury_short(game):
    """国库不足时实扣=库余额，且执行格记不足额 failed（非 fulfilled）。"""
    db, state, content = game
    _set_guanning_arrears(db, 60, central=60, province=0)
    state.metrics["国库"] = 5
    treasury_before = 5

    ctx = _stage_xiexang(db, state.turn, amount=15, target_id="guanning")
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    _promulgate(db, state, content, dossier["id"])

    moves = db.list_economy_moves_for_dossier(dossier["id"])
    spent = abs(sum(int(m["delta"]) for m in moves))
    assert spent == 5
    assert int(state.metrics["国库"]) == 0
    assert _army_row(db)["arrears"] == pytest.approx(60 - spent)
    closed = db.get_decree_dossier(dossier["id"])
    assert closed["status"] == "closed"
    assert closed["execution_outcome"] == "failed"
    assert "不足额" in str(closed.get("execution_note") or "")


def test_army_pay_forces_immediate_over_inherited_in_transit(game):
    """拨饷覆盖继承的 in_transit 默认；不得进月度在途对账轨。"""
    db, state, content = game
    _set_guanning_arrears(db, 40, central=40, province=0)
    state.metrics["国库"] = max(int(state.metrics["国库"]), 50)

    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text="拨关宁军饷十万两。",
        target_kind="army",
        target_id="guanning",
        payload={
            "grant_action": "协饷",
            "purpose": "补饷",
            "amount": 10,
            "account": "国库",
            "target_kind": "army",
            "target_id": "guanning",
            # 模拟旧 pending / normalize 前置插入的在途默认
            "execution_surface": "in_transit",
        },
    )
    row = db.get_decree_dossier(dossier_id)
    payload = json.loads(row["payload_json"])
    assert payload["execution_surface"] == "immediate"

    _promulgate(db, state, content, dossier_id)
    closed = db.get_decree_dossier(dossier_id)
    assert closed["status"] == "closed"
    assert closed["execution_outcome"] == "fulfilled"
    # 已结案的 immediate 不得出现在在途对账扫描面
    open_ids = {
        int(t["dossier_id"])
        for t in db.list_monthly_grant_reconciliation_targets()
    }
    assert dossier_id not in open_ids


# ── 负向：非拨饷不误落；extractor 单写者 ─────────────────────────

def test_non_army_grant_does_not_clear_arrears(game):
    """非拨饷类 special_decree / 赈灾不误落补饷销欠。"""
    db, state, content = game
    _set_guanning_arrears(db, 60, central=60, province=0)
    before = _army_row(db)
    state.metrics["国库"] = max(int(state.metrics["国库"]), 100)
    treasury_before = int(state.metrics["国库"])

    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    candidate = candidates_from_classifier_payload({
        "kind": "grant_allocation",
        "grant_action": "赈灾",
        "amount": 10,
        "account": "国库",
        "target_id": "shaanxi",
    }, soft=False)
    ctx = _ctx(
        db, actor, candidate, state.turn,
        message="调银十万两赈灾。",
        reply="臣请户部发帑赈陕西。",
    )
    run_materialize_pipeline(ctx)
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    _promulgate(db, state, content, dossier["id"])

    moves = db.list_economy_moves_for_dossier(dossier["id"])
    assert moves and int(moves[0]["delta"]) == -10
    assert moves[0].get("purpose") in (None, "", "其它")
    assert int(state.metrics["国库"]) == treasury_before - 10
    assert _army_row(db)["arrears"] == pytest.approx(before["arrears"])


@pytest.mark.parametrize("grant_action,message,reply", [
    ("项目经费", "拨关宁军械项目经费十万两。", "臣请户部发帑十万两作军械项目经费。"),
    ("项目经费", "拨关宁筑城经费十万两。", "臣请户部发帑十万两作筑城经费。"),
])
def test_army_target_non_pay_grant_does_not_clear_arrears(
    game, grant_action, message, reply,
):
    """army 对象的军械/筑城/项目经费：可扣库，不得升格协饷销欠。"""
    db, state, content = game
    _set_guanning_arrears(db, 60, central=60, province=0)
    before = _army_row(db)
    state.metrics["国库"] = max(int(state.metrics["国库"]), 100)
    treasury_before = int(state.metrics["国库"])

    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    # 显式 army 目标 + 非协饷 grant_action：不得因 army+金额+账户升格补饷。
    from ming_sim.action_materialize import stage_grant_allocation_candidate
    pending_id = stage_grant_allocation_candidate(
        db, state.turn, actor,
        text=reply,
        grant_action=grant_action,
        target_kind="army",
        target_id="guanning",
        emperor_text=message,
        amount=10,
        account="国库",
    )
    assert pending_id > 0
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["payload_json"])
    assert pending.get("purpose") != "补饷"
    assert pending.get("grant_action") == grant_action
    assert not db._is_army_pay_grant_payload(pending)

    dossier = _close_night_dossier(db, state, content, pending_id)
    payload = json.loads(dossier["payload_json"])
    assert payload.get("purpose") != "补饷"
    assert not db._is_army_pay_grant_payload(payload)

    _promulgate(db, state, content, dossier["id"])

    moves = db.list_economy_moves_for_dossier(dossier["id"])
    assert moves and int(moves[0]["delta"]) == -10
    assert moves[0].get("purpose") != "补饷"
    assert int(state.metrics["国库"]) == treasury_before - 10
    # 根因：不得因 army 目标误销欠饷
    assert _army_row(db)["arrears"] == pytest.approx(before["arrears"])
    assert _army_row(db)["central_pay_arrears"] == pytest.approx(
        before["central_pay_arrears"]
    )


def test_extractor_cannot_second_write_army_pay_for_payload_dossier(game):
    """单写者机械检查：payload 案卷颁布后 extractor 补饷不得二扣。"""
    db, state, content = game
    _set_guanning_arrears(db, 40, central=40, province=0)
    state.metrics["国库"] = max(int(state.metrics["国库"]), 100)
    treasury_before = int(state.metrics["国库"])

    ctx = _stage_xiexang(db, state.turn, amount=10, target_id="guanning")
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    _promulgate(db, state, content, dossier["id"])
    assert int(state.metrics["国库"]) == treasury_before - 10
    arrears_mid = _army_row(db)["arrears"]

    applied = apply_score_extraction(
        db, state,
        {
            "economy_moves": [{
                "account": "国库",
                "delta": -10,
                "category": "补饷",
                "reason": "extractor 试图再写",
                "purpose": "补饷",
                "target_kind": "army",
                "target_id": "guanning",
                "origin_ref": f"dossier:{dossier['id']}",
            }],
        },
        content=content,
    )
    eco = applied.get("economy_moves") or []
    assert all(int(m.get("delta") or 0) == 0 or m.get("rejected") for m in eco) or eco == []
    assert int(state.metrics["国库"]) == treasury_before - 10
    assert len(db.list_economy_moves_for_dossier(dossier["id"])) == 1
    assert _army_row(db)["arrears"] == pytest.approx(arrears_mid)


def test_closed_army_pay_dossier_keeps_origin_in_extractor_input(game):
    """#1503 provenance：closed 拨饷 origin 仅 internal 可见（module 门控双向）。"""
    from ming_sim.simulation import EXTRACTION_MODULES, build_extractor_shared_context

    db, state, content = game
    _set_guanning_arrears(db, 40, central=40, province=0)
    state.metrics["国库"] = max(int(state.metrics["国库"]), 100)

    ctx = _stage_xiexang(db, state.turn, amount=10, target_id="guanning")
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    did = int(dossier["id"])
    _promulgate(db, state, content, did)
    closed = db.get_decree_dossier(did)
    assert closed["status"] == "closed"
    assert closed["execution_outcome"] == "fulfilled"
    # 模拟可见集可不再含 closed；extractor 输入接缝必须保留身份。
    assert did not in {
        int(r["id"]) for r in db.list_decree_dossiers_for_simulation(state.turn)
    }
    assert did in {
        int(r["id"])
        for r in db.list_closed_army_pay_dossiers_for_provenance(state.turn)
    }

    # 正向：唯一拥有 economy_moves 的 internal 能见 closed 拨饷 provenance。
    payload = build_extractor_shared_context(
        db, state, narrative="", decree_text="", module="internal",
    )
    slim = payload.get("decree_dossiers") or []
    hit = next((r for r in slim if int(r["id"]) == did), None)
    assert hit is not None
    assert hit["origin_ref"] == f"dossier:{did}"
    assert hit["action_type"] == "grant_allocation"

    # 负向：其余 extractor 不因本修复新增 closed 拨饷案卷输入面。
    non_internal = tuple(m for m in EXTRACTION_MODULES if m != "internal")
    # #633: relations 并入后同受此负向门(不吃 closed 拨饷 provenance)。
    assert non_internal == (
        "military_external", "issues", "personnel_secret", "relations",
    )
    for module in non_internal:
        other = build_extractor_shared_context(
            db, state, narrative="", decree_text="", module=module
        )
        other_ids = {int(r["id"]) for r in (other.get("decree_dossiers") or [])}
        assert did not in other_ids, (
            f"module={module!r} 不应吃 closed 拨饷 provenance；ids={sorted(other_ids)}"
        )


def test_closed_army_pay_provenance_injects_when_decree_dossiers_prepassed(game):
    """#1507-F1：生产 settle 预传 decree_dossiers（list，非 None）时 internal 仍须注入。

    旧门 `decree_dossiers is None` 在 decree.py 必传 list 下永假，provenance 死门。
    """
    from ming_sim.simulation import build_extractor_shared_context

    db, state, content = game
    _set_guanning_arrears(db, 40, central=40, province=0)
    state.metrics["国库"] = max(int(state.metrics["国库"]), 100)

    ctx = _stage_xiexang(db, state.turn, amount=10, target_id="guanning")
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    did = int(dossier["id"])
    _promulgate(db, state, content, did)
    assert db.get_decree_dossier(did)["status"] == "closed"

    # 生产同形：预传模拟可见集（closed 拨饷已不在内；或显式空 list）
    sim_rows = list(db.list_decree_dossiers_for_simulation(state.turn))
    assert did not in {int(r["id"]) for r in sim_rows}

    for prepassed in (sim_rows, []):
        payload = build_extractor_shared_context(
            db, state, narrative="", decree_text="",
            module="internal", decree_dossiers=prepassed,
        )
        hit = next(
            (r for r in (payload.get("decree_dossiers") or []) if int(r["id"]) == did),
            None,
        )
        assert hit is not None, f"prepassed={prepassed!r} 须注入 closed 拨饷 provenance"
        assert hit["origin_ref"] == f"dossier:{did}"

        # 非 internal 预传同 list 仍不得吃 closed 拨饷
        other = build_extractor_shared_context(
            db, state, narrative="", decree_text="",
            module="issues", decree_dossiers=prepassed
        )
        other_ids = {int(r["id"]) for r in (other.get("decree_dossiers") or [])}
        assert did not in other_ids


def test_army_pay_already_cleared_spent_zero_is_fulfilled(game):
    """#1507-F5：颁布时军已清（spent=0, still_owed=0）记 fulfilled，非 failed。"""
    db, state, content = game
    _set_guanning_arrears(db, 15, central=15, province=0)
    state.metrics["国库"] = max(int(state.metrics["国库"]), 100)

    ctx = _stage_xiexang(db, state.turn, amount=15, target_id="guanning")
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    did = int(dossier["id"])

    # staging 与颁布之间：独立盘面自发补饷已把欠饷清零
    apply_score_extraction(
        db, state,
        {
            "economy_moves": [{
                "account": "国库",
                "delta": -15,
                "category": "补饷",
                "reason": "同回合盘面自发先清",
                "purpose": "补饷",
                "target_kind": "army",
                "target_id": "guanning",
                "origin_ref": "盘面自发",
            }],
        },
        content=content,
    )
    assert _army_row(db)["arrears"] == pytest.approx(0)

    _promulgate(db, state, content, did)
    closed = db.get_decree_dossier(did)
    assert closed["status"] == "closed"
    assert closed["execution_outcome"] == "fulfilled", closed
    # clamp 到 0：本案无补饷流水（或 spent=0），不得记不足额 failed
    note = str(closed.get("execution_note") or "")
    assert "不足额" not in note


def test_independent_panmian_zifa_pay_lands_alongside_decree_pay(game):
    """负向：同军同回合『旨意补饷 + 独立盘面自发补饷』两笔都应落。"""
    db, state, content = game
    _set_guanning_arrears(db, 40, central=40, province=0)
    state.metrics["国库"] = max(int(state.metrics["国库"]), 100)
    treasury_before = int(state.metrics["国库"])

    ctx = _stage_xiexang(db, state.turn, amount=10, target_id="guanning")
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    did = int(dossier["id"])
    _promulgate(db, state, content, did)
    assert int(state.metrics["国库"]) == treasury_before - 10
    arrears_mid = _army_row(db)["arrears"]

    # 独立盘面自发（非案卷回声）：不得被 army+turn 宽去重吞掉。
    applied = apply_score_extraction(
        db, state,
        {
            "economy_moves": [{
                "account": "国库",
                "delta": -5,
                "category": "补饷",
                "reason": "边镇自筹另笔补饷（独立于旨意）",
                "purpose": "补饷",
                "target_kind": "army",
                "target_id": "guanning",
                "origin_ref": "盘面自发",
            }],
        },
        content=content,
    )
    eco = [m for m in (applied.get("economy_moves") or []) if not m.get("rejected")]
    assert any(int(m.get("delta") or 0) == -5 for m in eco)
    assert int(state.metrics["国库"]) == treasury_before - 15
    assert len(db.list_economy_moves_for_dossier(did)) == 1
    assert _army_row(db)["arrears"] == pytest.approx(arrears_mid - 5)
    ledger = [
        dict(r) for r in db.conn.execute(
            """
            SELECT origin_ref, delta FROM economy_ledger
            WHERE purpose='补饷' AND target_id='guanning' AND turn=?
            ORDER BY id
            """,
            (state.turn,),
        ).fetchall()
    ]
    assert {str(r["origin_ref"]) for r in ledger} == {f"dossier:{did}", "盘面自发"}
    assert sorted(int(r["delta"]) for r in ledger) == [-10, -5]


def test_extractor_echo_with_dossier_origin_still_single_writer_after_close(game):
    """单写者：结案后 extractor 以 origin_ref=dossier:<id> 回声仍不得二扣。"""
    db, state, content = game
    _set_guanning_arrears(db, 40, central=40, province=0)
    state.metrics["国库"] = max(int(state.metrics["国库"]), 100)
    treasury_before = int(state.metrics["国库"])

    ctx = _stage_xiexang(db, state.turn, amount=10, target_id="guanning")
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    did = int(dossier["id"])
    _promulgate(db, state, content, did)
    arrears_mid = _army_row(db)["arrears"]
    assert db.get_decree_dossier(did)["status"] == "closed"

    applied = apply_score_extraction(
        db, state,
        {
            "economy_moves": [{
                "account": "国库",
                "delta": -10,
                "category": "补饷",
                "reason": "邸报叙已拨关宁（dossier 回声应被 provenance 滤掉）",
                "purpose": "补饷",
                "target_kind": "army",
                "target_id": "guanning",
                "origin_ref": f"dossier:{did}",
            }],
        },
        content=content,
    )
    eco = applied.get("economy_moves") or []
    assert all(int(m.get("delta") or 0) == 0 or m.get("rejected") for m in eco) or eco == []
    assert int(state.metrics["国库"]) == treasury_before - 10
    assert len(db.list_economy_moves_for_dossier(did)) == 1
    assert _army_row(db)["arrears"] == pytest.approx(arrears_mid)


# ── ⑦ #1503 上游 carrier：显式拟旨前缀 → typed grant 单轨 ─────────────

def _scripted_xiexang_candidates(*, amount=15, account="国库", target_id="guanning"):
    return candidates_from_classifier_payload(
        {
            "kind": "grant_allocation",
            "grant_action": "协饷",
            "amount": amount,
            "account": account,
            "purpose": "补饷",
            "target_kind": "army",
            "target_id": target_id,
        },
        soft=False,
    )


@pytest.mark.parametrize("amount", [True, 15.9, "15"])
def test_xiexang_amount_rejects_non_json_integer(amount):
    from ming_sim.action_materialize import IncompleteXiexangPayloadError, require_explicit_xiexang_fields

    with pytest.raises(IncompleteXiexangPayloadError) as exc:
        require_explicit_xiexang_fields(
            amount=amount, account="国库", purpose="补饷",
            target_kind="army", target_id="guanning",
        )
    assert "amount" in exc.value.missing_fields


def test_manual_directive_admission_real_http_tracer_1591(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
):
    """#1591 真实入口 tracer：同一 WebGame/TestClient 内证两支外部行为。

    ① `POST /api/directives` 手工拟旨 account=太仓 经 capture 透传五字段后 canonical 为国库。
    ② 同入口 account 非法，且有无关非旨 pending action 并存时，
    `POST /api/decree/issue` 外部响应须是真实 admission 拒因，不得被掩盖为「至少一条草案」。

    stub 仅 LLM payload 产出边界（拟旨抽取/结算外层）；不 mock
    ensure_dossiers_for_draft_directives / list_dossiered_draft_directives /
    preview_pending_directives / list_pending_actions / resolve_turn。
    """
    from fastapi.testclient import TestClient

    import ming_sim.cli_backend as cb
    import web_app
    from tests.test_month_loop_tracer_1468 import (
        _get_state, _post_issue_stream, _stub_outer_llm_seams, _turn_of,
    )
    from tests.test_session_write_queue_1353 import wait_pending_writes

    captured_ok = {
        "draft_action": "拟旨",
        "dossier_action_type": "grant_allocation",
        "grant_action": "协饷",
        "purpose": "补饷",
        "target_kind": "army",
        "target_id": "guanning",
        "mode": "ordinary",
        "amount": 15,
        "account": "太仓",
    }
    captured_bad = dict(captured_ok, account="藩库")
    captures = [captured_ok, captured_bad]

    def fake_extract(*_a, **_k):
        return dict(captures.pop(0))

    real_capture = cb.capture_manual_directive_payload
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    _stub_outer_llm_seams(monkeypatch)
    monkeypatch.setattr(cb, "extract_draft_intent_with_roster_heal", fake_extract)
    monkeypatch.setattr(cb, "capture_manual_directive_payload", real_capture)

    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", game)
    try:
        name = next(
            getattr(ch, "name", key)
            for key, ch in game.content.characters.items()
            if getattr(ch, "office_type", "") == "户部"
            and getattr(ch, "power_id", "ming") == "ming"
            and game.db.get_character_status(getattr(ch, "name", key))[0] == "active"
        )
        if getattr(game.session, "llm_config", None) is not None:
            try:
                game.session.llm_config.channel = "cli"
            except Exception:
                pass

        client = TestClient(web_app.app)

        # ── ① 手工拟旨太仓→国库：原票 POST /api/directives 入口 ──
        turn1 = int(game.state.turn)
        directive_ok = client.post(
            "/api/directives",
            json={"text": "准从太仓见银拨关宁军饷十五万两即发。", "notes": ""},
        )
        assert directive_ok.status_code == 200, directive_ok.text
        wait_pending_writes(game)
        _post_issue_stream(client, expected_turn=turn1, step="1591①太仓 issue/stream")
        after = _get_state(client)
        assert _turn_of(after) == turn1 + 1, after.get("turn")
        dossier = next(
            d for d in game.db.list_decree_dossiers()
            if d["action_type"] == "grant_allocation"
        )
        payload = json.loads(dossier["payload_json"])
        assert payload.get("account") == "国库", payload

        # ── ② 手工拟旨 account 非法 + 无关非旨 pending 并存：issue 须回真实拒因 ──
        turn2 = int(game.state.turn)
        directive = client.post(
            "/api/directives",
            json={"text": "准从藩库见银拨关宁军饷十五万两即发。", "notes": ""},
        )
        assert directive.status_code == 200, directive.text
        directive_id = int(directive.json()["directive"]["id"])
        wait_pending_writes(game)

        game.db.stage_pending_action(
            turn2, kind="office", action="任命", minister_name=name,
            payload={"name": name, "office": "经略关宁", "_office_action": "任命"},
        )
        assert game.db.list_pending_actions(turn2), "无关非旨 pending action 应在场"

        issue = client.post("/api/decree/issue", json={"expected_turn": turn2})
        assert issue.status_code == 400, issue.text
        detail = issue.json().get("detail")
        message = detail.get("message") if isinstance(detail, dict) else detail
        # 同次 admission 拒因真源：ledger 按 turn+section+directive_id 定位唯一记录，
        # HTTP message 与 ledger.reason 只做不透明值相等，不锁具体措辞（#13）。
        rejection_rows = game.db.conn.execute(
            "SELECT reason, category, source FROM rejection_reports "
            "WHERE turn = ? AND section = 'directive_locality' "
            "AND json_extract(item_json, '$.directive_id') = ?",
            (turn2, directive_id),
        ).fetchall()
        assert len(rejection_rows) == 1, [dict(row) for row in rejection_rows]
        rejection_row = rejection_rows[0]
        assert rejection_row["category"] == "locality_fanout_failed", dict(rejection_row)
        assert rejection_row["source"] == "player_decree", dict(rejection_row)
        assert message == rejection_row["reason"], (message, rejection_row["reason"])
        assert int(game.state.turn) == turn2, "拒案不得推进回合"
    finally:
        try:
            game.session.close()
        except Exception:
            pass


def test_non_xiexang_payload_cannot_smuggle_army_pay_purpose(game):
    db, state, content = game
    _set_guanning_arrears(db, 60, central=60, province=0)
    before = _army_row(db)
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    ledger_before = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger"
    ).fetchone()[0]
    pending_id = db.stage_directive_candidate(state.turn, actor, payload={
        "text": "拨关宁军械项目经费十万两。",
        "actor": actor,
        "dossier_action_type": "grant_allocation",
        "grant_action": "项目经费",
        "target_kind": "army",
        "target_id": "guanning",
        "amount": 10,
        "account": "国库",
        "purpose": "补饷",
        "mode": "ordinary",
    })

    db.commit_pending_actions(state, content=content, action_ids=[pending_id])

    assert not any(
        row["pending_action_id"] == pending_id for row in db.list_decree_dossiers()
    )
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger"
    ).fetchone()[0] == ledger_before
    assert _army_row(db) == before


def test_explicit_draft_prefix_without_grant_candidate_stays_generic(game, monkeypatch):
    """非载荷拟旨：classifier 无 grant 候选时仍走 generic special_decree；颁布不误落补饷。"""
    import types

    import ming_sim.cli_backend as cb
    from ming_sim.session import GameSession

    db, state, content = game
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    character = content.characters[actor]
    seed = "臣遵旨，着户部清核辽饷。钦此。"

    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": "",
    })
    monkeypatch.setattr(cb, "extract_confirmation_intent", lambda *a, **k: "无")

    sess = types.SimpleNamespace(
        db=db,
        state=state,
        content=content,
        llm_config=types.SimpleNamespace(channel="cli"),
        registry=None,
    )
    sess.apply_cli_conversation_actions = types.MethodType(
        GameSession.apply_cli_conversation_actions, sess,
    )
    out = sess.apply_cli_conversation_actions(
        character,
        "拟旨如下：着户部清核辽饷。",
        seed,
        has_directive=False,
        secret_order_id=None,
        preclassified_intent=[],  # classifier 已跑、无动作
    )
    pending_id = out.get("pending_action_id")
    assert pending_id
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["payload_json"])
    assert pending.get("dossier_action_type") == "special_decree"
    assert pending.get("text") == seed
    assert pending.get("purpose") != "补饷"

    _set_guanning_arrears(db, 60, central=60, province=0)
    before = _army_row(db)
    state.metrics["国库"] = max(int(state.metrics["国库"]), 100)
    dossier = _close_night_dossier(db, state, content, pending_id)
    _promulgate(db, state, content, dossier["id"])
    moves = db.list_economy_moves_for_dossier(dossier["id"])
    assert all(m.get("purpose") != "补饷" for m in moves)
    pay_ledger = [
        dict(r) for r in db.conn.execute(
            """
            SELECT purpose, origin_ref FROM economy_ledger
            WHERE purpose='补饷' AND origin_ref=?
            """,
            (f"dossier:{dossier['id']}",),
        ).fetchall()
    ]
    assert pay_ledger == []
    assert _army_row(db)["arrears"] == pytest.approx(before["arrears"])


def test_identical_payment_fields_two_array_items_stage_twice(game):
    """付款字段完全相同的两个数组项仍各成一案（列表契约，内容相等不合并）。"""
    db, state, _content = game
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    item = {
        "kind": "grant_allocation",
        "grant_action": "协饷",
        "amount": 15,
        "account": "太仓",
        "purpose": "补饷",
        "target_kind": "army",
        "target_id": "guanning",
    }
    candidates = candidates_from_classifier_payload([item, dict(item)], soft=False)
    assert len(candidates) == 2
    ctx = _ctx(
        db, actor, candidates, state.turn,
        message="分别拨关宁军饷十五万两、再拨十五万两。",
        reply="臣遵旨。",
    )
    run_materialize_pipeline(ctx)

    assert db.conn.execute(
        "SELECT COUNT(*) FROM pending_actions WHERE turn=? AND kind='directive'",
        (state.turn,),
    ).fetchone()[0] == 2


def _real_chat_session(db, state, content, monkeypatch, *, scripted, agent_tools=None):
    """本文件 session.chat 真实入口共用装配；stub 仅 classifier/agent/确认边界。"""
    import ming_sim.cli_backend as cb
    import ming_sim.session as session_mod
    from ming_sim.session import GameSession

    tools = agent_tools if agent_tools is not None else []

    def fake_classify(*_a, **_k):
        return list(scripted)

    class FakeAgent:
        def run(self, _msg):
            return SimpleNamespace(
                content="臣遵旨。敕户部发太仓银十五万两协济关宁军前。钦此。",
                tools=list(tools),
            )

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = SimpleNamespace(
        get=lambda _character: FakeAgent(),
        build_draft_line=lambda: "无",
    )
    sess.llm_config = SimpleNamespace(channel="cli", cli_runner="codex")
    sess.temporary_characters = {}
    sess._retrieve_memories_for_message = lambda message: message
    monkeypatch.setattr(session_mod, "_dump_llm_messages", lambda *a, **k: None)
    monkeypatch.setattr(cb, "classify_cli_action_intent", fake_classify)
    for name in (
        "extract_minister_actions",
        "extract_draft_intent",
        "extract_appointment_action",
        "extract_confirmation_intent",
    ):
        monkeypatch.setattr(
            cb, name,
            lambda *a, name=name, **k: (_ for _ in ()).throw(
                AssertionError(f"must not call {name} on explicit draft prefix")
            ),
        )
    return sess


def test_real_chat_explicit_prefix_suppresses_tool_twin_and_durable_one_dossier(
    game, monkeypatch,
):
    """真实 session.chat：draft 协饷升格、tool 孪生抑制，commit/颁布后唯一 durable 扣库销欠。"""
    db, state, content = game
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    _set_guanning_arrears(db, 60, central=60, province=0)
    state.metrics["国库"] = max(int(state.metrics["国库"]), 100)
    treasury_before = int(state.metrics["国库"])
    arrears_before = _army_row(db)
    scripted = candidates_from_classifier_payload({
        "kind": "draft", "draft_action": "拟旨",
        "grant_action": "协饷", "amount": 15, "account": "太仓",
        "purpose": "补饷", "target_kind": "army", "target_id": "guanning",
    }, soft=False)
    twin_tools = [SimpleNamespace(
        tool_name="propose_directive",
        result="__pending_directive__敕户部发太仓银十五万两协济关宁军前。",
        arguments={"decree_text": "敕户部发太仓银十五万两协济关宁军前。"},
    )]
    sess = _real_chat_session(
        db, state, content, monkeypatch, scripted=scripted, agent_tools=twin_tools,
    )

    result = sess.chat(actor, "拟旨如下：准拨关宁军饷十五万两。")
    pending_id = int(getattr(result, "pending_action_id", 0) or 0)
    assert pending_id > 0
    rows = list(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE turn=? AND kind='directive'",
        (state.turn,),
    ).fetchall())
    assert len(rows) == 1
    pending = json.loads(rows[0]["payload_json"])
    assert pending["dossier_action_type"] == "grant_allocation"

    dossier = _close_night_dossier(db, state, content, pending_id)
    _promulgate(db, state, content, dossier["id"])
    moves = [
        m for m in db.list_economy_moves_for_dossier(dossier["id"])
        if m.get("purpose") == "补饷" and m.get("target_id") == "guanning"
    ]
    assert len(moves) == 1
    assert int(moves[0]["delta"]) == -15
    assert int(state.metrics["国库"]) == treasury_before - 15
    after = _army_row(db)
    assert after["arrears"] == pytest.approx(float(arrears_before["arrears"]) - 15)
    assert after["central_pay_arrears"] == pytest.approx(
        float(arrears_before["central_pay_arrears"]) - 15
    )


def test_real_chat_draft_xiexang_plus_punish_tool_keeps_both_pending(
    game, monkeypatch,
):
    """真实 session.chat：draft+协饷 classifier 不得 turn-wide 吞掉带 punish 字段的 tool。

    外部可见：pending 恰两行，dossier_action_type ∈ {grant_allocation, punishment}。
    根因样本：tool 循环层 continue 把整枚 propose_directive 跳过；generic 尾路抑制
    只挡孪生 special_decree，惩处显式字段分支仍须入档。
    """
    db, state, content = game
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    target = next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫", "宗藩")
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
        and ch.name != actor
        and str(getattr(ch, "office", "") or "").strip()
    )
    scripted = candidates_from_classifier_payload({
        "kind": "draft", "draft_action": "拟旨",
        "grant_action": "协饷", "amount": 15, "account": "太仓",
        "purpose": "补饷", "target_kind": "army", "target_id": "guanning",
    }, soft=False)
    punish_tools = [SimpleNamespace(
        tool_name="propose_directive",
        result=f"__pending_directive__着罚{target.name}俸示惩。",
        arguments={
            "decree_text": f"着罚{target.name}俸示惩。",
            "punish_action": "罚俸",
            "target_id": target.name,
            "amount": 120,
        },
    )]
    sess = _real_chat_session(
        db, state, content, monkeypatch, scripted=scripted, agent_tools=punish_tools,
    )

    result = sess.chat(actor, f"拟旨如下：准拨关宁军饷，并罚{target.name}俸。")
    assert int(getattr(result, "pending_action_id", 0) or 0) > 0
    rows = list(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE turn=? AND kind='directive'",
        (state.turn,),
    ).fetchall())
    assert len(rows) == 2
    types = {json.loads(row["payload_json"]).get("dossier_action_type") for row in rows}
    assert types == {"grant_allocation", "punishment"}


def test_explicit_prefix_grant_and_assignment_two_durable_dossiers(game, monkeypatch):
    """真实 session.chat：grant+assignment 一次吐出，commit 后两道独立 durable dossiers。"""
    db, state, content = game
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    scripted = _scripted_xiexang_candidates(
        amount=15, account="太仓", target_id="guanning",
    ) + candidates_from_classifier_payload({
        "kind": "assignment",
        "title": "清查辽饷收支",
        "target_id": "hubu",
        "transaction_category": "钱粮",
    }, soft=False)
    sess = _real_chat_session(db, state, content, monkeypatch, scripted=scripted)

    result = sess.chat(actor, "拟旨如下：拨饷，并另行清查。")
    assert int(getattr(result, "pending_action_id", 0) or 0) > 0
    rows = list(db.conn.execute(
        "SELECT id, payload_json FROM pending_actions WHERE turn=? AND kind='directive'",
        (state.turn,),
    ).fetchall())
    assert len(rows) == 2
    payloads = [json.loads(row["payload_json"]) for row in rows]
    assert {p.get("dossier_action_type") for p in payloads} == {
        "grant_allocation", "assignment",
    }

    pending_ids = [int(row["id"]) for row in rows]
    db.commit_pending_actions(state, content=content, action_ids=pending_ids)
    dossiers = [
        d for d in db.list_decree_dossiers()
        if int(d["pending_action_id"] or 0) in set(pending_ids)
    ]
    assert len(dossiers) == 2
    assert {d["action_type"] for d in dossiers} == {"grant_allocation", "assignment"}


def test_draft_neitang_stays_generic_special_decree(game, monkeypatch):
    """真非协饷 draft（发内帑）不升格 grant：恰一 generic special_decree。"""
    import ming_sim.cli_backend as cb

    db, state, _content = game
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    payload = {
        "kind": "draft", "grant_action": "发内帑", "amount": 15,
        "account": "内库", "target_kind": "character", "target_id": "关宁军",
    }
    candidates = candidates_from_classifier_payload(payload, soft=False)
    monkeypatch.setattr(
        cb,
        "extract_draft_intent_with_roster_heal",
        lambda **_kwargs: {
            "draft_action": "拟旨",
            "draft_text": "准拨，数目另议。",
            "target_candidate": "",
        },
    )
    ctx = _ctx(
        db, actor, candidates, state.turn,
        message="拟一道旨意。",
        reply="准拨，数目另议。",
    )
    run_materialize_pipeline(ctx)
    rows = list(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE turn=? AND kind='directive'",
        (state.turn,),
    ).fetchall())
    assert len(rows) == 1
    pending = json.loads(rows[0]["payload_json"])
    assert pending.get("dossier_action_type") != "grant_allocation"
    assert pending.get("dossier_action_type", "special_decree") == "special_decree"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "kind": "draft", "draft_action": "拟旨", "grant_action": "协饷",
        },
        {
            "kind": "draft", "draft_action": "拟旨", "grant_action": "协饷",
            "amount": 15, "account": "太仓", "purpose": "补饷",
            "target_kind": "army", "target_id": "liaodong",
        },
    ],
    ids=["incomplete_xiexang", "unresolvable_target"],
)
def test_draft_xiexang_incomplete_or_illegal_fail_loud_zero_write(game, payload):
    """残缺/非法协饷 draft：materialize fail-loud，pending/dossier 零增。"""
    from ming_sim.action_materialize import IncompleteXiexangPayloadError

    db, state, _content = game
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    pending_before = db.conn.execute(
        "SELECT COUNT(*) FROM pending_actions WHERE turn=? AND kind='directive'",
        (state.turn,),
    ).fetchone()[0]
    dossier_before = {int(d["id"]) for d in db.list_decree_dossiers()}
    candidates = candidates_from_classifier_payload(payload, soft=False)
    ctx = _ctx(
        db, actor, candidates, state.turn,
        message="拟旨如下：准拨军饷。",
        reply="准拨，数目另议。",
    )
    with pytest.raises((IncompleteXiexangPayloadError, ValueError)):
        run_materialize_pipeline(ctx)
    pending_after = db.conn.execute(
        "SELECT COUNT(*) FROM pending_actions WHERE turn=? AND kind='directive'",
        (state.turn,),
    ).fetchone()[0]
    assert pending_after == pending_before
    assert {int(d["id"]) for d in db.list_decree_dossiers()} == dossier_before


def test_http_chat_issue_stream_pay_decree_advances_month(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
):
    """原轨真 HTTP：召对户部「拨关宁军饷十五万两」→「准」→ issue/stream（必要时 resolve）过月。

    stub 仅 LLM 边界；不得用 store helper 代替收夜/颁布/结算 HTTP 链。
    """
    from fastapi.testclient import TestClient

    import ming_sim.cli_backend as cb
    import web_app
    from tests.test_month_loop_tracer_1468 import (
        _get_state,
        _post_issue_stream,
        _stub_outer_llm_seams,
        _turn_of,
    )
    from tests.test_session_write_queue_1353 import wait_pending_writes

    class _TwoRoundHubuAgent:
        """#1503 独有：召对请拨 + 准后遵旨两轮户部回话。"""

        def __init__(self):
            self._calls = 0

        def run(self, *_a, **_k):
            self._calls += 1
            if self._calls == 1:
                content = "臣请户部发帑十五万两协济关宁军前，请陛下定夺准驳。"
            else:
                content = "臣遵旨。敕户部发太仓银十五万两协济关宁军前。钦此。"
            return SimpleNamespace(content=content, tools=[])

        def get_last_run_output(self):
            return None

    scripted = _scripted_xiexang_candidates(amount=15, account="太仓", target_id="guanning")

    def fake_classify(text, *_a, **_k):
        if str(text or "").strip() == "准":
            return []
        return list(scripted)

    def fake_confirm(player_message, *_a, **_k):
        if str(player_message or "").strip() == "准":
            return "应允"
        return "无"

    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    _stub_outer_llm_seams(monkeypatch)
    # The first grant enters through audience night; the second is a season
    # decision whose selected server option is its legal origin.
    import ming_sim.decree as decree_mod
    extractor_inputs = {}

    def capture_extractor_input(_config, _agno_db, module, **kwargs):
        extractor_inputs[module] = [
            (int(row["id"]), str(row["status"]))
            for row in kwargs["supplemental_context"].get("decree_dossiers") or []
        ]
        return None

    # Observe the structured payload at the real extractor boundary; the outer
    # LLM remains canned by _stub_outer_llm_seams.
    monkeypatch.setattr(
        decree_mod, "create_score_extractor_module_agent", capture_extractor_input,
    )
    decision_report = """本月邸报。
<<DECISION>>
{"title":"再济关宁","context":"关宁欠饷尚重，奏请圣裁","options":[{"label":"发内帑银三十万两济关宁","hint":"军心稍定，内帑益绌","action_type":"grant_allocation","grant_action":"协饷","account":"内库","amount":30,"purpose":"补饷","target_kind":"army","target_id":"guanning","cadence":"一次性"},{"label":"暂缓再拨","hint":"内帑得保，边军仍困"}]}
<<END>>"""
    monkeypatch.setattr(
        decree_mod, "simulate_season_with_payload",
        lambda *a, **k: (decision_report, k.get("simulator_payload") or {}),
    )
    monkeypatch.setattr(cb, "classify_cli_action_intent", fake_classify)
    monkeypatch.setattr(cb, "extract_confirmation_intent", fake_confirm)

    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", game)
    try:
        name = next(
            getattr(ch, "name", key)
            for key, ch in game.content.characters.items()
            if getattr(ch, "office_type", "") == "户部"
            and getattr(ch, "power_id", "ming") == "ming"
            and game.db.get_character_status(getattr(ch, "name", key))[0] == "active"
        )
        canned = _TwoRoundHubuAgent()
        game.session.registry.get = lambda _ch: canned
        if getattr(game.session, "llm_config", None) is not None:
            try:
                game.session.llm_config.channel = "cli"
            except Exception:
                pass

        _set_guanning_arrears(game.db, 60, central=60, province=0)
        game.state.metrics["国库"] = max(int(game.state.metrics["国库"]), 100)
        game.db.save_state(game.state)
        treasury_before = int(game.state.metrics["国库"])
        arrears_before = _army_row(game.db)
        turn_before = int(game.state.turn)

        client = TestClient(web_app.app)
        petition = client.post(
            f"/api/ministers/{name}/chat",
            json={"message": "拨关宁军饷十五万两。"},
        )
        assert petition.status_code == 200, petition.text
        pending_id = int(petition.json().get("pending_action_id") or 0)
        assert pending_id > 0, petition.json()
        wait_pending_writes(game)
        assert int(game.state.metrics["国库"]) == treasury_before
        assert _army_row(game.db)["arrears"] == pytest.approx(arrears_before["arrears"])
        from ming_sim.audience_night import get_open_night
        night = get_open_night(game.db)
        assert night is not None
        approved_ids = {
            int(row["id"])
            for row in game.db.list_night_approved_pending(int(night["id"]))
        }
        assert pending_id not in approved_ids

        confirm = client.post(
            f"/api/ministers/{name}/chat",
            json={"message": "准"},
        )
        assert confirm.status_code == 200, confirm.text
        wait_pending_writes(game)
        assert int(game.state.metrics["国库"]) == treasury_before
        assert _army_row(game.db)["arrears"] == pytest.approx(arrears_before["arrears"])
        night = get_open_night(game.db)
        assert night is not None
        approved_ids = {
            int(row["id"])
            for row in game.db.list_night_approved_pending(int(night["id"]))
        }
        assert pending_id in approved_ids

        body = _post_issue_stream(
            client, expected_turn=turn_before, step="1503 issue/stream",
        )
        if body.get("awaiting_decision"):
            decisions = body.get("decisions") or []
            assert decisions, f"awaiting_decision with empty decisions: {body!r}"
            selected = decisions[0]["options"][0]
            resolved = client.post(
                "/api/decree/resolve_decisions/stream",
                json={"choices": [{
                    "decision_key": decisions[0]["decision_key"],
                    "label": selected["label"],
                }]},
            )
            assert resolved.status_code == 200, resolved.text
            assert "event: error" not in resolved.text, resolved.text
            assert "event: done" in resolved.text, resolved.text
        wait_pending_writes(game)

        after = _get_state(client)
        assert _turn_of(after) == turn_before + 1, after.get("turn")

        dossiers = [
            d for d in game.db.list_decree_dossiers()
            if d["action_type"] == "grant_allocation"
            and d["target_id"] == "guanning"
        ]
        dossier = next(d for d in dossiers if d["pending_action_id"] == pending_id)
        decision_dossier = next(d for d in dossiers if d["id"] != dossier["id"])
        decision_payload = json.loads(game.db.conn.execute(
            "SELECT payload_json FROM decree_dossiers WHERE id=?",
            (decision_dossier["id"],),
        ).fetchone()[0])
        assert decision_payload["decision_key"] == decisions[0]["decision_key"]
        assert decision_dossier["status"] == "closed"
        assert decision_dossier["promulgation_decision"] == "promulgated"
        late_fact = (int(decision_dossier["id"]), "closed")
        assert late_fact in extractor_inputs["issues"]
        assert late_fact in extractor_inputs["internal"]
        assert all(
            late_fact not in extractor_inputs[module]
            for module in ("military_external", "personnel_secret", "relations")
        )
        assert [
            row["decision"]
            for row in game.db.list_decree_dossier_decisions(decision_dossier["id"])
        ] == ["promulgated"]
        moves = game.db.list_economy_moves_for_dossier(dossier["id"])
        pay_moves = [
            m for m in moves
            if m.get("purpose") == "补饷" and m.get("target_id") == "guanning"
        ]
        assert len(pay_moves) == 1, moves
        assert int(pay_moves[0]["delta"]) == -15
        assert pay_moves[0]["account"] == "国库"
        ledger = [
            dict(r) for r in game.db.conn.execute(
                """
                SELECT account, delta, purpose, origin_ref FROM economy_ledger
                WHERE purpose='补饷' AND target_id='guanning' AND origin_ref=?
                """,
                (f"dossier:{dossier['id']}",),
            ).fetchall()
        ]
        assert len(ledger) == 1
        assert int(ledger[0]["delta"]) == -15
        assert ledger[0]["account"] == "国库"
        decision_ledger = [
            dict(r) for r in game.db.conn.execute(
                """
                SELECT account, delta, origin_ref FROM economy_ledger
                WHERE purpose='补饷' AND target_id='guanning' AND origin_ref=?
                """,
                (f"dossier:{decision_dossier['id']}",),
            ).fetchall()
        ]
        assert decision_ledger == [{
            "account": "内库", "delta": -30,
            "origin_ref": f"dossier:{decision_dossier['id']}",
        }]
        logs = [
            dict(row) for row in game.db.conn.execute(
                """
                SELECT * FROM army_logs
                WHERE army_id='guanning' AND field='arrears' AND origin_ref=?
                ORDER BY id DESC
                """,
                (f"dossier:{dossier['id']}",),
            ).fetchall()
        ]
        assert len(logs) == 1
        assert float(logs[0]["delta"]) == pytest.approx(-15)
        after_army = _army_row(game.db)
        assert int(after["metrics"]["国库"]) == 293
        assert int(after["metrics"]["内库"]) == 432
        assert after_army["arrears"] == pytest.approx(16)
        assert after_army["central_pay_arrears"] == pytest.approx(16)
        decision_logs = game.db.conn.execute(
            """
            SELECT delta, new_value FROM army_logs
            WHERE army_id='guanning' AND field='arrears' AND origin_ref=?
            """,
            (f"dossier:{decision_dossier['id']}",),
        ).fetchall()
        assert len(decision_logs) == 1
        assert float(decision_logs[0]["delta"]) == pytest.approx(-30)

    finally:
        try:
            game.session.close()
        except Exception:
            pass
