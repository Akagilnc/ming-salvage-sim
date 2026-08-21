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
    with pytest.raises(ValueError, match="拨饷|amount|account|target"):
        db.create_decree_dossier(
            state,
            action_type="grant_allocation",
            decree_text="拨关宁军饷十五万两。",
            target_kind="army",
            target_id="guanning",
            payload={
                "dossier_action_type": "grant_allocation",
                "grant_action": "协饷",
                # 缺 amount / account / purpose
            },
            status="proposed",
            commit=False,
        )
    assert int(state.metrics["国库"]) == treasury_before
    assert db.list_decree_dossiers() == [] or all(
        d.get("action_type") != "grant_allocation" or "协饷" not in str(d.get("payload_json") or "")
        for d in db.list_decree_dossiers()
    )


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
    """国库不足时实扣=库余额（既有 record 路径 clamp）。"""
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
