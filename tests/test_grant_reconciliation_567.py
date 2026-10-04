"""#567 S12 按月对账与押解折损（#461 兑现）。

Seams:
- list_monthly_grant_reconciliation_targets / record_monthly_grant_reconciliations
- grant_arrival_bounds（引擎既有押解折损范围；护行界严于无护行）
- list_dossier_reconciliations（被护案卷×回合键控，restore 无损）
- 玩家月链对账与案卷月度写口
- dossier_executions 适配器经 merge_execution_note 合并对账说明（S10 单写）
- 不改 economy_moves / 国库二次扣

#1900：沿途损耗归引擎核算；本文件实抵取护行口径区间中位，不接提案入参。
"""

from __future__ import annotations

import json

import pytest

import ming_sim.issues as issue_engine
from ming_sim.applier import Provenance
from ming_sim.db import GameDB
from ming_sim.models import TurnPhase
from tests.dossier_test_helpers import create_test_secret_order


ORDERED = 30  # 北极星三路各三十万两量级（引擎以「两」为单位的整数面值）


def _record_recon(db, turn):
    """月度对账：实抵与损耗由引擎给出，本口不接提案。"""
    reports = db.record_monthly_grant_reconciliations(turn)
    db.conn.commit()
    return reports


def _recon_rejections(db):
    """全体拒收查询（#1745：不得以 section 过滤掩盖第二 producer）。"""
    if db.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rejection_reports'"
    ).fetchone() is None:
        return []   # 尚无任何拒收落库，表未建
    return list(db.conn.execute(
        "SELECT section, category, source, reason, item_json "
        "FROM rejection_reports ORDER BY id"
    ).fetchall())


def _actor(db):
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"])


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
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    row = db.get_decree_dossier(dossier_id)
    assert row["status"] == "executing"
    return dossier_id


def _escort_order(db, state, grant_ids, *, tags=None):
    """密令案卷（新）→ 护卫/稽核 指向既有拨饷案卷（旧）。"""
    order_id = create_test_secret_order(db,
        state, _actor(db), "护行饷银", "沿途按月稽核",
        tags or ["护行"], deadline_months=4,
    )
    escort_dossier = db.get_dossier_for_secret_order(order_id)
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
    db.add_dossier_links(escort_id, links)
    # #1900 J18：专用逐路实况账本已退役；关联只答「谁护谁」，核账按无护口径。
    return order_id, escort_id


def _record_monthly(db, state, *, progress=None):
    _record_recon(db, state.turn)
    if progress is not None:
        db.record_monthly_dossier_progress(state.turn, progress)
    db.conn.commit()


def test_escort_progress_stays_on_the_secret_order_and_survives_restore(game):
    """护行密奏挂密令案卷，不写到拨帑案卷上；重开后原文仍在。"""
    db, state, content = game
    bare = _in_transit_grant(db, state, text="无护行路", target_id="liaodong")
    escorted_grant = _in_transit_grant(db, state, text="有护行路", target_id="shaanxi")
    order_id, escort_dossier_id = _escort_order(db, state, [escorted_grant])
    memorial = "护行路已核关防，实银可期"
    _record_monthly(db, state, progress=[{
        "dossier_id": escort_dossier_id,
        "progress_band": "在途核验",
        "memorial_text": memorial,
    }])

    assert db.list_dossier_progress(bare) == []
    assert db.list_dossier_progress(escorted_grant) == []
    progress = db.list_dossier_progress(escort_dossier_id)
    assert [row["memorial_text"] for row in progress] == [memorial]

    path = db.path
    db.close()
    reopened = GameDB(path, content=content)
    assert reopened.list_dossier_progress(escort_dossier_id) == progress
    stored = reopened.conn.execute(
        "SELECT dossier_progress_json FROM secret_orders WHERE id=?", (order_id,),
    ).fetchone()
    assert json.loads(stored["dossier_progress_json"]) == progress
    reopened.close()


def test_close_merges_recon_note_without_second_treasury_debit(game):
    """S10 结案后对账行在账上；不二次扣库、不改原流水。"""
    db, state, content = game
    before_inner = int(state.metrics["内库"])
    gid = _in_transit_grant(db, state, amount=ORDERED)
    after_grant_inner = int(state.metrics["内库"])
    assert after_grant_inner == before_inner - ORDERED
    moves_before = db.list_economy_moves_for_dossier(gid)

    _record_monthly(db, state)
    assert int(state.metrics["内库"]) == after_grant_inner
    assert db.list_economy_moves_for_dossier(gid) == moves_before

    result = issue_engine.apply_score_extraction(
        db, state,
        {"dossier_executions": [{
            "dossier_id": gid,
            "outcome": "fulfilled",
            "note": "赈银押解到达",
        }]},
        content=content,
    )
    assert result["dossier_executions"] == [{"dossier_id": gid, "outcome": "fulfilled"}]
    closed = db.get_decree_dossier(gid)
    assert closed["status"] == "closed"
    row = db.list_dossier_reconciliations(gid)[-1]
    assert row["ordered_amount"] == ORDERED
    assert row["loss_amount"] == ORDERED - row["arrived_amount"]
    # 仍无二次扣库
    assert int(state.metrics["内库"]) == after_grant_inner
    assert db.list_economy_moves_for_dossier(gid) == moves_before


def test_failed_close_reconciles_only_when_the_silver_already_left(game):
    """零出库的失败不核账；已经离开账本的银，不论足额与否，都按实付和逐路实况核。"""
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
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    row = db.get_decree_dossier(dossier_id)
    assert row["status"] == "closed"
    assert row["execution_outcome"] == "failed"
    assert db.list_economy_moves_for_dossier(dossier_id) == []
    turn = int(state.turn)
    assert dossier_id not in {
        int(t["dossier_id"])
        for t in db.list_monthly_grant_reconciliation_targets(turn)
    }

    paid = _in_transit_grant(db, state, text="已出库后办理失败", target_id="liaodong")
    state.metrics["内库"] = 7
    db.conn.execute("UPDATE metrics SET value=7 WHERE key='内库'")
    partial = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text="内帑只剩七两",
        target_kind="region",
        target_id="xuan_da",
        payload={
            "account": "内库", "amount": ORDERED,
            "execution_surface": "in_transit",
        },
    )
    assert [int(move["delta"]) for move in db.list_economy_moves_for_dossier(partial)] == [-7]
    db.apply_dossier_promulgation(state, partial, "promulgated")
    partial_closed = db.get_decree_dossier(partial)
    assert partial_closed["status"] == "closed"
    assert partial_closed["execution_outcome"] == "failed"
    assert int(state.metrics["内库"]) == 0
    _order_id, escort_id = _escort_order(db, state, [paid, partial])
    debits = [int(move["delta"]) for move in db.list_economy_moves_for_dossier(paid)]
    assert debits == [-ORDERED]
    db.record_dossier_execution(
        paid, "failed", "途中未能办结", turn, close=True,
    )
    closed = db.get_decree_dossier(paid)
    assert closed["status"] == "closed"
    assert closed["execution_outcome"] == "failed"
    assert partial not in {
        int(t["dossier_id"]) for t in db.list_monthly_grant_reconciliation_targets()
    }
    assert paid not in {
        int(t["dossier_id"]) for t in db.list_monthly_grant_reconciliation_targets()
    }
    scanned = {
        int(t["dossier_id"]): t
        for t in db.list_monthly_grant_reconciliation_targets(turn)
    }
    assert dossier_id not in scanned
    assert scanned[paid]["escorted"] is False
    assert scanned[paid]["ordered_amount"] == ORDERED
    assert scanned[partial]["escorted"] is False
    assert scanned[partial]["ordered_amount"] == 7
    assert scanned[partial]["escort_source_dossier_id"] is None
    moves_before = db.list_economy_moves_for_dossier(partial)
    reports = {
        int(item["dossier_id"]): item for item in _record_recon(db, turn)
    }
    assert set(reports) == {paid, partial}
    assert reports[paid]["loss_amount"] == ORDERED - reports[paid]["arrived_amount"]
    partial_row = reports[partial]
    assert partial_row["ordered_amount"] == 7
    assert partial_row["loss_amount"] == 7 - partial_row["arrived_amount"]
    assert db.get_decree_dossier(partial)["execution_outcome"] == "failed"
    assert db.list_economy_moves_for_dossier(partial) == moves_before
    assert int(state.metrics["内库"]) == 0
    assert db.list_dossier_reconciliations(dossier_id) == []


def test_settle_entry_lands_engine_arrival_per_route(game, monkeypatch):
    """settle 真入口：引擎逐路给实抵落账、月份推进、无假 awaiting、无拒收噪声。

    #1900 后本口不接提案，断的是「引擎沿途损耗 → 逐路对账行」这条真链。
    """
    from tests.test_month_chain_1843 import _prepare_player_month

    db, state, content = game
    good = _in_transit_grant(db, state, text="陕西赈银", target_id="shaanxi")
    turn_before = int(state.turn)
    session = _prepare_player_month(
        db, state, content, monkeypatch, world=lambda *_a, **_k: "世界段",
        translate=lambda *_a, **_k: {"effects": {}},
    )
    session.resolve_turn(allow_empty_decree=True)
    db.save_turn_report(state, "邸报", public_body="邸报")
    session.resolve_turn(allow_empty_decree=True)

    assert int(state.turn) == turn_before + 1
    assert state.turn_phase != TurnPhase.AWAITING_DECISION.value
    row = db.list_dossier_reconciliations(good)[-1]
    assert row["ordered_amount"] == ORDERED
    assert row["loss_amount"] == ORDERED - row["arrived_amount"]
    assert _recon_rejections(db) == []


def test_empty_targets_no_recon_rows(game):
    """无在途目标 → 零对账行（不落假账）。"""
    db, state, _content = game
    assert db.list_monthly_grant_reconciliation_targets() == []
    assert _record_recon(db, state.turn) == []
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossier_reconciliations"
    ).fetchone()["n"] == 0
    assert _recon_rejections(db) == []


def test_normal_close_same_turn_still_reconciles(game):
    """拨帑正常结案不免除该次核账（#1900）：同回合结案仍按逐路实况落账。"""
    db, state, _content = game
    transit = _in_transit_grant(db, state, text="本回合押解到达", target_id="shaanxi")
    db.record_dossier_execution(
        transit, "fulfilled", "押解已达", int(state.turn), close=True,
    )
    assert db.get_decree_dossier(transit)["status"] == "closed"
    assert [t["dossier_id"] for t in
            db.list_monthly_grant_reconciliation_targets(int(state.turn))] == [transit]
    rows = _record_recon(db, state.turn)
    assert [r["dossier_id"] for r in rows] == [transit]
    assert rows[0]["ordered_amount"] == ORDERED
    assert rows[0]["loss_amount"] == ORDERED - rows[0]["arrived_amount"]


def test_prior_turn_close_is_not_re_reconciled(game):
    """只补本回合那笔核账，不翻历史结案（不重开全部历史案卷）。"""
    db, state, _content = game
    transit = _in_transit_grant(db, state, text="上月押解到达", target_id="shaanxi")
    db.record_dossier_execution(
        transit, "fulfilled", "押解已达", int(state.turn), close=True,
    )
    assert _record_recon(db, int(state.turn))          # 本回合该核的核了
    state.turn = int(state.turn) + 1
    assert _record_recon(db, int(state.turn)) == []      # 次月不回头重核
    assert len(db.list_dossier_reconciliations(transit)) == 1
    # 供料读侧（不带 turn）只看在途，不翻历史结案
    assert db.list_monthly_grant_reconciliation_targets() == []


def test_1745_full_chain_player_state_no_fake_awaiting(game, monkeypatch):
    """#1745 C：全链 canned 结算入口——玩家态无假 awaiting、结构化拒收归属正确。"""
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
    # 五模块 extractor 已退役： canned recon 不再从过月入口落拒收。
    assert _recon_rejections(db) == []


def test_web_state_payload_after_settle(
    tmp_path, monkeypatch, content, _offline_scene_beat_generator,
):
    """全链 canned 结算入口后的 WebGame.state_payload 结构化玩家态。

    自有 WebGame；只咬 phase / pending_decisions / resume_phase2 / settlement_recovery。
    """
    import web_app

    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    monkeypatch.setattr(web_app, "run_highlight_judge", lambda **_k: [])
    game_web = web_app.WebGame(fresh=True)
    monkeypatch.setattr(web_app, "web_game", game_web)
    try:
        db, state = game_web.db, game_web.state
        from tests.test_month_chain_1843 import _prepare_player_month

        turn_before = int(state.turn)
        session = _prepare_player_month(
            db, state, content, monkeypatch, world=lambda *_a, **_k: "世界段",
            translate=lambda *_a, **_k: {"effects": {}},
        )
        session.resolve_turn(allow_empty_decree=True)
        db.save_turn_report(state, "邸报", public_body="邸报")
        session.resolve_turn(allow_empty_decree=True)

        payload = game_web.state_payload()
        turn_blk = payload.get("turn") or {}
        assert int(turn_blk.get("turn") or 0) == turn_before + 1
        assert turn_blk.get("phase") != TurnPhase.AWAITING_DECISION.value
        assert payload.get("pending_decisions") in (None, [])
        assert payload.get("resume_phase2") in (False, None)
        recovery = payload.get("settlement_recovery")
        assert recovery in (None, {}) or isinstance(recovery, dict)
        # 结构化投影：不把拒收明细键塞进 state_payload（P4）；只断键存在性
        assert "rejection_reports" not in payload
        assert db.conn.execute(
            "SELECT COUNT(*) AS n FROM decree_dossier_reconciliations"
        ).fetchone()["n"] == 0
    finally:
        game_web.session.close()
        web_app.web_game = None
