from __future__ import annotations
from ming_sim.settlement.dossier import apply_dossier_promulgation
import json
from ming_sim.settlement import SettlementContext, settle_delta
from ming_sim.settlement.views import view
from ming_sim.db import GameDB
from ming_sim.models import TurnPhase
from tests.dossier_test_helpers import create_test_secret_order
from tests.readback_helpers import active_character_name as _actor
import ming_sim.settlement.run as issue_engine
"""#567 S12 按月对账与押解折损（#461 兑现；#1900 退役提案/clamp 口）。

Seams:
- list_monthly_grant_reconciliation_targets / record_monthly_grant_reconciliations
- grant_arrival_bounds 中位（护行界严于无护行）
- list_dossier_reconciliations（被护案卷×回合键控，restore 无损）
- 玩家月链对账与案卷月度写口
- 对账不增补 dossier_executions 的执行原文
- 不改 economy_moves / 国库二次扣
"""






ORDERED = 30  # 北极星三路各三十万两量级（引擎以「两」为单位的整数面值）


def _record_recon(db, turn):
    """直调引擎中位对账写口（#1900：不接提案）。"""
    return db.record_monthly_grant_reconciliations(turn)




def _in_transit_grant(db, state, *, amount=ORDERED, text="拨银押解", target_id="shaanxi",
                      escort=None):
    state.metrics["内库"] = max(int(state.metrics.get("内库") or 0), amount * 3 + 50)
    payload = {
        "account": "内库", "amount": amount, "execution_surface": "in_transit",
    }
    if escort is not None:
        payload["escort"] = escort
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text=text,
        target_kind="region",
        target_id=target_id,
        payload=payload,
    )
    apply_dossier_promulgation(db, state, dossier_id, "promulgated")
    row = db.dossiers.get(dossier_id)
    assert row["status"] == "executing"
    return dossier_id


def _escort_order(db, state, grant_ids, *, tags=None):
    """密令案卷（新）→ 护卫/稽核 指向既有拨饷案卷（旧）。"""
    order_id = create_test_secret_order(db,
        state, _actor(db), "护行饷银", "沿途按月稽核",
        tags or ["护行"], deadline_months=4,
    )
    escort_dossier = db.dossiers.get_for_secret_order(order_id)
    escort_id = int(escort_dossier["id"])
    # 关联要求新→旧：密令案卷 id 须大于被护拨饷 id
    links = [
        {
            "target_dossier_id": int(gid),
            "relation_type": "护卫",
            "note": f"护送案卷{gid}",
        }
        for gid in grant_ids
    ]
    db.dossiers.add_links(escort_id, links)
    return order_id, escort_id


def _record_monthly(db, state, *, progress=None):
    _record_recon(db, state.turn)
    if progress is not None:
        db.record_monthly_dossier_progress(state.turn, progress)
    db.conn.commit()


def test_per_route_storage_restore_without_retired_escort_accounting(game):
    """W4 核账恒为无护（接续 #1873）；密令进展独立落账并可恢复。"""

    db, state, content = game
    bare = _in_transit_grant(db, state, text="无护行路", target_id="liaodong")
    escorted_grant = _in_transit_grant(db, state, text="有护行路", target_id="shaanxi")
    order_id, escort_dossier_id = _escort_order(db, state, [escorted_grant])

    turn = state.turn
    _record_monthly(db, state, progress=[{
        "dossier_id": escort_dossier_id,
        "progress_band": "在途核验",
        "memorial_text": "护行路已核关防，实银可期",
    }])

    bare_rows = db.dossiers.reconciliations(bare)
    escort_rows = db.dossiers.reconciliations(escorted_grant)
    assert len(bare_rows) == 1 and bare_rows[0]["turn"] == turn
    assert len(escort_rows) == 1 and escort_rows[0]["turn"] == turn
    assert bare_rows[0]["arrived_amount"] == 16
    assert escort_rows[0]["arrived_amount"] == 16
    assert bare_rows[0]["escorted"] is False
    assert escort_rows[0]["escorted"] is False
    assert escort_rows[0]["escort_source_dossier_id"] is None

    # 无护行：不对拨饷案卷写进展；有护行：进展挂密令案卷（#566 容器）
    assert db.dossiers.list_dossier_progress(bare) == []
    assert db.dossiers.list_dossier_progress(escorted_grant) == []
    progress = db.dossiers.list_dossier_progress(escort_dossier_id)
    assert len(progress) == 1
    assert progress[0]["memorial_text"] == "护行路已核关防，实银可期"

    # restore 逐路无损
    path = db.path
    db.conn.close()
    reopened = GameDB(path, content=content)
    assert reopened.dossiers.reconciliations(bare) == bare_rows
    assert reopened.dossiers.reconciliations(escorted_grant) == escort_rows
    assert reopened.dossiers.list_dossier_progress(escort_dossier_id) == progress
    stored = reopened.conn.execute(
        "SELECT dossier_progress_json FROM secret_orders WHERE id=?", (order_id,),
    ).fetchone()
    assert json.loads(stored["dossier_progress_json"]) == progress
    reopened.conn.close()


def test_close_merges_recon_note_without_second_treasury_debit(game):
    """S10 结案同源读对账；不二次扣库、不改原流水；执行说明原文原样。"""

    db, state, content = game
    before_inner = int(state.metrics["内库"])
    gid = _in_transit_grant(db, state, amount=ORDERED)
    after_grant_inner = int(state.metrics["内库"])
    assert after_grant_inner == before_inner - ORDERED
    moves_before = db.reign.list_economy_moves_for_origin(f"dossier:{int(gid)}")

    _record_monthly(db, state)
    assert int(state.metrics["内库"]) == after_grant_inner
    assert db.reign.list_economy_moves_for_origin(f"dossier:{int(gid)}") == moves_before

    result = settle_delta(
        state, db,
        {"dossier_executions": [{
            "dossier_id": gid,
            "outcome": "fulfilled",
            "note": "赈银押解到达",
        }]},
        SettlementContext(content=content),
    )
    assert view(result, "dossier_executions") == [{"dossier_id": gid, "outcome": "fulfilled", "source_item": {"dossier_id": gid, "outcome": "fulfilled", "note": "赈银押解到达"}}]
    closed = db.dossiers.get(gid)
    assert closed["status"] == "closed"
    note = closed["execution_note"]
    assert note == "赈银押解到达"
    recon = db.dossiers.reconciliations(gid)[-1]
    assert recon["arrived_amount"] == 16
    # 仍无二次扣库
    assert int(state.metrics["内库"]) == after_grant_inner
    assert db.reign.list_economy_moves_for_origin(f"dossier:{int(gid)}") == moves_before


def test_underfunded_closed_grants_excluded_from_monthly_targets(game):
    """成案当回合不足额 failed+close 者不进月度对账扫描面。"""
    db, state, _content = game
    state.metrics["内库"] = 0
    db.conn.execute("UPDATE metrics SET value=0 WHERE key='内库'")
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text="内帑无银",
        target_kind="region",
        target_id="shaanxi",
        payload={
            "account": "内库", "amount": 10,
            "execution_surface": "in_transit",
        },
    )
    apply_dossier_promulgation(db, state, dossier_id, "promulgated")
    row = db.dossiers.get(dossier_id)
    assert row["status"] == "closed"
    targets = db.list_monthly_grant_reconciliation_targets()
    assert dossier_id not in {int(t["dossier_id"]) for t in targets}


def test_full_chain_player_state_no_fake_awaiting(game, monkeypatch):
    """全链 canned 结算入口——玩家态无假 awaiting。"""
    from tests.test_month_chain_1843 import _prepare_player_month

    db, state, content = game
    turn0 = int(state.turn)
    session = _prepare_player_month(db, state, content, monkeypatch)
    result = session.advance_without_decree()
    assert result is not None
    assert result.awaiting is False
    assert not (result.decisions or [])
    assert int(state.turn) == turn0
    assert state.turn_phase != TurnPhase.AWAITING_DECISION.value
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossier_reconciliations"
    ).fetchone()["n"] == 0


def test_prior_turn_close_is_not_re_reconciled(game):
    """只补本回合那笔核账，不翻历史结案（不重开全部历史案卷）。"""
    db, state, _content = game
    transit = _in_transit_grant(db, state, text='上月押解到达', target_id='shaanxi')
    assert _record_recon(db, int(state.turn))
    db.dossiers.record_execution(transit, 'fulfilled', '押解已达', int(state.turn), close=True)
    state.turn = int(state.turn) + 1
    assert _record_recon(db, int(state.turn)) == []
    assert len(db.dossiers.reconciliations(transit)) == 1
    assert db.list_monthly_grant_reconciliation_targets() == []
