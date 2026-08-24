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
    """字段缺失 fail-loud：不猜散文、不成案、不落账。"""
    db, state, content = game
    treasury_before = int(state.metrics["国库"])
    before_ids = {int(d["id"]) for d in db.list_decree_dossiers()}
    with pytest.raises(
        ValueError,
        match=r"^拨饷旨意缺少结构化字段：amount/account（不猜散文）$",
    ):
        db.create_decree_dossier(
            state,
            action_type="grant_allocation",
            decree_text="拨关宁军饷十五万两。",
            target_kind="army",
            target_id="guanning",
            payload={
                "dossier_action_type": "grant_allocation",
                "grant_action": "协饷",
                # 缺 amount / account（purpose 由 normalize 补）
            },
            status="proposed",
            commit=False,
        )
    assert int(state.metrics["国库"]) == treasury_before
    after = db.list_decree_dossiers()
    new_grants = [
        d for d in after
        if int(d["id"]) not in before_ids and d.get("action_type") == "grant_allocation"
    ]
    assert new_grants == []


def test_xiexang_incomplete_payload_rejected_before_pending(game):
    """入 pending 前拒不完整协饷载荷（缺 amount/非法 target）。"""
    db, state, content = game
    from ming_sim.action_materialize import stage_grant_allocation_candidate

    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    before_pending = db.list_pending_actions(state.turn, minister_name=actor)

    with pytest.raises(ValueError, match=r"协饷旨意缺少正数 amount"):
        stage_grant_allocation_candidate(
            db, state.turn, actor,
            text="臣请协饷。",
            grant_action="协饷",
            target_kind="army",
            target_id="guanning",
            amount=0,
            account="国库",
        )
    with pytest.raises(ValueError, match=r"协饷旨意 target 无法解析为军队"):
        stage_grant_allocation_candidate(
            db, state.turn, actor,
            text="臣请协饷辽东。",
            grant_action="协饷",
            target_kind="army",
            target_id="liaodong",
            amount=15,
            account="国库",
        )
    with pytest.raises(ValueError, match=r"target_kind 须为 army"):
        stage_grant_allocation_candidate(
            db, state.turn, actor,
            text="臣请协饷。",
            grant_action="协饷",
            target_kind="region",
            target_id="guanning",
            amount=15,
            account="国库",
        )
    after_pending = db.list_pending_actions(state.turn, minister_name=actor)
    assert len(after_pending) == len(before_pending)


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

def test_promulgated_army_pay_debits_and_clears_arrears_once(game):
    """原轨回归：顺颁后国库恰扣 15、guanning 欠饷核减、army_logs 有补饷行。"""
    db, state, content = game
    _set_guanning_arrears(db, 60, central=60, province=0)
    state.metrics["国库"] = max(int(state.metrics["国库"]), 100)
    treasury_before = int(state.metrics["国库"])
    before = _army_row(db)

    ctx = _stage_xiexang(
        db, state.turn, amount=15, target_id="guanning",
        message="拨关宁军饷十五万两。",
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    assert int(state.metrics["国库"]) == treasury_before
    assert _army_row(db)["arrears"] == pytest.approx(before["arrears"])

    _promulgate(db, state, content, dossier["id"])

    moves = db.list_economy_moves_for_dossier(dossier["id"])
    assert len(moves) == 1
    assert int(moves[0]["delta"]) == -15
    assert moves[0]["account"] == "国库"
    assert moves[0]["purpose"] == "补饷"
    assert moves[0]["target_kind"] == "army"
    assert moves[0]["target_id"] == "guanning"
    assert int(state.metrics["国库"]) == treasury_before - 15

    after = _army_row(db)
    assert after["arrears"] == pytest.approx(before["arrears"] - 15)
    assert after["central_pay_arrears"] == pytest.approx(before["central_pay_arrears"] - 15)

    logs = db.conn.execute(
        "SELECT * FROM army_logs WHERE army_id='guanning' AND field='arrears' ORDER BY id DESC"
    ).fetchall()
    assert logs and "补饷" in str(logs[0]["reason"])


def test_promulgation_settle_applies_once_ready_replay_no_double_debit(game):
    """颁布缝落账恰一次；同批 extractor 误产 + ready 重放均不二扣。"""
    db, state, content = game
    _set_guanning_arrears(db, 60, central=60, province=0)
    state.metrics["国库"] = max(int(state.metrics["国库"]), 100)
    treasury_before = int(state.metrics["国库"])

    ctx = _stage_xiexang(db, state.turn, amount=15, target_id="guanning")
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    did = int(dossier["id"])

    # 颁布缝一次消费
    _promulgate(db, state, content, did)
    assert int(state.metrics["国库"]) == treasury_before - 15
    assert len(db.list_economy_moves_for_dossier(did)) == 1
    arrears_after_first = _army_row(db)["arrears"]

    # 同批 extractor 误产（模拟 settle 内 apply_score_extraction）
    apply_score_extraction(
        db, state,
        {
            "economy_moves": [{
                "account": "国库",
                "delta": -15,
                "category": "补饷",
                "reason": "extractor 误产补饷（应被单写者滤掉）",
                "purpose": "补饷",
                "target_kind": "army",
                "target_id": "guanning",
                "origin_ref": f"dossier:{did}",
            }],
        },
        content=content,
    )
    assert int(state.metrics["国库"]) == treasury_before - 15
    assert len(db.list_economy_moves_for_dossier(did)) == 1

    # ready=1 重放：extractor 再吐同一笔；不得二扣。
    # 颁布缝幂等：若再次进入 apply（不应发生，status 已非 proposed），既有流水护栏。
    apply_score_extraction(
        db, state,
        {
            "economy_moves": [{
                "account": "国库",
                "delta": -15,
                "category": "补饷",
                "reason": "恢复重放误产",
                "purpose": "补饷",
                "target_kind": "army",
                "target_id": "guanning",
                "origin_ref": f"dossier:{did}",
            }],
        },
        content=content,
    )
    assert int(state.metrics["国库"]) == treasury_before - 15
    assert len(db.list_economy_moves_for_dossier(did)) == 1
    assert _army_row(db)["arrears"] == pytest.approx(arrears_after_first)

    # 直接再调拨饷消费缝：已有流水则零增量
    spent_again = db._apply_army_pay_grant_effect(
        state, dossier, json.loads(dossier["payload_json"]), did,
    )
    assert spent_again == 15
    assert int(state.metrics["国库"]) == treasury_before - 15
    assert len(db.list_economy_moves_for_dossier(did)) == 1


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
            db, state, narrative="", decree_text="", module=module,
            transit_semantics=[],
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
            module="issues", decree_dossiers=prepassed,
            transit_semantics=[],
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
