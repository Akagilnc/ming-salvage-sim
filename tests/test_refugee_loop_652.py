"""#652：流民环闭合——投贼吃池顶 + 赈济/招抚回流 + 唯一判官成色链。

主测缝：apply_score_extraction /
advance_without_decree（可控 LLM seam 真实月结）。
owner A：开仓非回流 producer；只覆盖赈济与招抚屯田；#522 不动。
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from ming_sim.applier import atomic
from ming_sim.db import GameDB, POPULATION_UNIT_PERSONS
from ming_sim.issues import apply_score_extraction
from tests.month_chain_helpers import canned_full_settlement, make_light_session

FARMER_SHAANXI = 6000000
DISPLACED_SHAANXI = 150000





def _pop(db: GameDB, name: str, region_id: str) -> int:
    row = db.conn.execute(
        "SELECT population FROM classes WHERE name=? AND region_id=?",
        (name, region_id),
    ).fetchone()
    return int(row[0]) if row else 0


def _strength(db: GameDB, power_id: str) -> int:
    return int(db.conn.execute(
        "SELECT military_strength FROM powers WHERE id=?", (power_id,),
    ).fetchone()[0])


def _recovery_grant(db, state, *, action="赈灾", amount=30, region_id="shaanxi", cadence="一次性"):
    state.metrics["内库"] = max(int(state.metrics.get("内库") or 0), amount + 50)
    dossier_id = db.create_decree_dossier(
        state, action_type="grant_allocation",
        decree_text=f"{action}{region_id}",
        target_kind="region", target_id=region_id,
        payload={
            "grant_action": action, "account": "内库", "amount": amount,
            "execution_surface": "immediate", "cadence": cadence,
        },
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    return dossier_id




def _reflux(transfers, *, dossier_id=None):
    out = [t for t in transfers if t.get("reason") == "回流"]
    if dossier_id is not None:
        out = [t for t in out if t.get("origin_ref") == f"dossier:{dossier_id}"]
    return out


def _reset_shaanxi_pool(db):
    db.conn.execute(
        "UPDATE classes SET population=? WHERE name='流民' AND region_id='shaanxi'",
        (DISPLACED_SHAANXI,),
    )
    db.conn.execute(
        "UPDATE classes SET population=? WHERE name='农民' AND region_id='shaanxi'",
        (FARMER_SHAANXI,),
    )
    db.conn.commit()


# ── 刀① 池清单 + 投贼吸收 ───────────────────────────────────────────────────



def _database_path(db: GameDB) -> str:
    return str(db.conn.execute("PRAGMA database_list").fetchone()[2])


def test_standalone_absorption_is_durable_to_second_connection(game):
    db, state, content = game
    before = _pop(db, "流民", "shaanxi")
    applied = apply_score_extraction(db, state, {
        "bandit_absorptions": [{
            "region_id": "shaanxi", "power_id": "bandit_li_zicheng",
            "requested_count": 10_000, "origin_ref": "盘面自发",
        }],
    }, content, None)
    assert applied["bandit_absorptions"][0]["actual_count"] == 10_000
    with sqlite3.connect(_database_path(db)) as reopened:
        assert reopened.execute(
            "SELECT population FROM classes WHERE name='流民' AND region_id='shaanxi'"
        ).fetchone()[0] == before - 10_000


def test_standalone_surcharge_is_durable_to_second_connection(game):
    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="陕西加派",
        target_kind="region", target_id="shaanxi",
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    applied = apply_score_extraction(db, state, {
        "surcharge_decrees": [{
            "region_id": "shaanxi", "monthly_amount": 10.0,
            "origin_ref": f"dossier:{dossier_id}",
        }],
    }, content, None)
    expected = applied["surcharge_decrees"][0]["加派基线"]
    with sqlite3.connect(_database_path(db)) as reopened:
        fiscal = json.loads(reopened.execute(
            "SELECT fiscal FROM regions WHERE id='shaanxi'"
        ).fetchone()[0])
    assert fiscal["settle"]["_meta"]["加派基线"] == expected


def test_outer_atomic_rolls_back_surcharge_and_absorption(game):
    db, state, content = game
    before_pool = _pop(db, "流民", "shaanxi")
    before_fiscal = db.conn.execute(
        "SELECT fiscal FROM regions WHERE id='shaanxi'"
    ).fetchone()[0]
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="陕西加派",
        target_kind="region", target_id="shaanxi",
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    with pytest.raises(RuntimeError):
        with atomic(db):
            apply_score_extraction(db, state, {
                "surcharge_decrees": [{
                    "region_id": "shaanxi", "monthly_amount": 10.0,
                    "origin_ref": f"dossier:{dossier_id}",
                }],
                "bandit_absorptions": [{
                    "region_id": "shaanxi", "power_id": "bandit_li_zicheng",
                    "requested_count": 10_000, "origin_ref": "盘面自发",
                }],
            }, content, None)
            raise RuntimeError("rollback")
    assert _pop(db, "流民", "shaanxi") == before_pool
    assert db.conn.execute(
        "SELECT fiscal FROM regions WHERE id='shaanxi'"
    ).fetchone()[0] == before_fiscal




def test_bandit_absorption_clamps_pool_strength_and_ceiling(game):
    """超池 clamp；实力按 actual；触 100 上界；空池拒收无正增。"""
    db, state, content = game
    pid = "bandit_li_zicheng"
    applied = apply_score_extraction(db, state, {
        "bandit_absorptions": [{
            "region_id": "shaanxi", "power_id": pid,
            "requested_count": DISPLACED_SHAANXI + 50_000, "origin_ref": "盘面自发",
        }],
    }, content, None)
    assert not applied["bandit_absorptions_rejections"]
    rec = applied["bandit_absorptions"][0]
    assert rec["actual_count"] == DISPLACED_SHAANXI
    assert _pop(db, "流民", "shaanxi") == 0

    # 空池再吸 → 拒、实力不动
    empty_str = _strength(db, pid)
    empty = apply_score_extraction(db, state, {
        "bandit_absorptions": [{
            "region_id": "shaanxi", "power_id": pid,
            "requested_count": 1000, "origin_ref": "盘面自发",
        }],
    }, content, None)
    assert empty["bandit_absorptions"] == []
    assert empty["bandit_absorptions_rejections"]
    assert _strength(db, pid) == empty_str

    # 0–100 上界：从 99 吸足量仍停在 100
    db.conn.execute("UPDATE powers SET military_strength=99 WHERE id='bandits'")
    db.conn.execute(
        "UPDATE classes SET population=? WHERE name='流民' AND region_id='henan'",
        (100_000,),
    )
    db.conn.commit()
    apply_score_extraction(db, state, {
        "bandit_absorptions": [{
            "region_id": "henan", "power_id": "bandits",
            "requested_count": 100_000, "origin_ref": "盘面自发",
        }],
    }, content, None)
    assert _strength(db, "bandits") == 100


def test_bandit_absorption_rejects_unknown_fields_keeps_clean_sibling(game):
    """canonical 闭集：同批未知字段项拒收留痕；干净兄弟项照落。"""
    db, state, content = game
    pid = "bandit_li_zicheng"
    before_pool = _pop(db, "流民", "shaanxi")
    before_str = _strength(db, pid)
    clean_req = 10_000
    applied = apply_score_extraction(db, state, {
        "bandit_absorptions": [
            {
                "region_id": "shaanxi", "power_id": pid,
                "requested_count": 20_000, "origin_ref": "盘面自发",
                "bogus_boost": 999,
            },
            {
                "region_id": "shaanxi", "power_id": pid,
                "requested_count": clean_req, "origin_ref": "盘面自发",
            },
        ],
    }, content, None)
    rejections = applied["bandit_absorptions_rejections"]
    assert len(rejections) == 1
    assert rejections[0].get("category") == "invalid_enum"
    assert rejections[0].get("item", {}).get("bogus_boost") == 999
    assert len(applied["bandit_absorptions"]) == 1
    rec = applied["bandit_absorptions"][0]
    assert rec["actual_count"] == clean_req
    assert _pop(db, "流民", "shaanxi") == before_pool - clean_req
    assert _strength(db, pid) == before_str + rec["strength_delta"]


def test_free_positive_bandit_strength_rejected_negative_ok(game):
    db, state, content = game
    pid = "bandit_li_zicheng"
    before, houjin_before = _strength(db, pid), _strength(db, "houjin")
    applied = apply_score_extraction(db, state, {
        "power_updates": {
            pid: {"military_strength": 5, "origin_ref": "盘面自发"},
            "houjin": {"military_strength": 2, "origin_ref": "盘面自发"},
        },
    }, content, None)
    assert any(c.get("rejected") and c.get("power_id") == pid for c in applied["power_changes"])
    assert _strength(db, pid) == before
    assert _strength(db, "houjin") == min(100, houjin_before + 2)

    before2 = _strength(db, pid)
    apply_score_extraction(db, state, {
        "power_updates": {pid: {"military_strength": -3, "origin_ref": "盘面自发"}},
    }, content, None)
    assert _strength(db, pid) == max(0, before2 - 3)


# 回流的正例由下方真实月链 in_transit 用例验证；效果落账入口不再触发。

def test_llm_free_回流_rejected(game):
    db, state, content = game
    free = apply_score_extraction(db, state, {
        "population_transfers": [{
            "source": "流民@shaanxi", "target": "农民@shaanxi",
            "amount": 1000, "reason": "回流", "origin_ref": "盘面自发",
        }],
    }, content, None)
    assert free["population_transfers"] == []
    assert free["population_transfers_rejections"]
    assert _pop(db, "流民", "shaanxi") == DISPLACED_SHAANXI


def _advance_canned_month(db, state, content, monkeypatch):
    """Only external LLM calls are canned; settlement and advancement remain real."""
    canned_full_settlement(monkeypatch, skip_fixed_flows=True)
    session = make_light_session(db, state, content)
    waiting = session.advance_without_decree()
    assert waiting.stage == "gazette"
    turn = state.turn
    db.conn.execute(
        "INSERT INTO turn_reports (turn, year, period, report) VALUES (?, ?, ?, ?)",
        (turn, state.year, state.period, "邸报已成"),
    )
    db.conn.commit()
    assert session.advance_without_decree().advanced is True


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_non_recovery_grant_no_回流(game, monkeypatch):
    db, state, content = game
    state.metrics["内库"] = max(int(state.metrics.get("内库") or 0), 80)
    dossier_id = db.create_decree_dossier(
        state, action_type="grant_allocation", decree_text="项目经费",
        target_kind="issue", target_id="project_dummy",
        payload={
            "grant_action": "项目经费", "account": "内库", "amount": 5,
            "execution_surface": "immediate", "cadence": "一次性",
        },
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    assert db.get_decree_dossier(dossier_id)["execution_outcome"] == "fulfilled"
    assert db.list_economy_moves_for_dossier(dossier_id)
    before = _pop(db, "流民", "shaanxi")
    _advance_canned_month(db, state, content, monkeypatch)
    assert _pop(db, "流民", "shaanxi") == before


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_recovery_without_paid_evidence_produces_nothing(game, monkeypatch):
    db, state, content = game
    dossier_id = _recovery_grant(db, state, amount=30)
    assert db.list_economy_moves_for_dossier(dossier_id)
    db.conn.execute("DELETE FROM economy_ledger WHERE origin_ref=?", (f"dossier:{dossier_id}",))
    db.conn.execute("DELETE FROM decree_dossier_reconciliations WHERE dossier_id=?", (dossier_id,))
    db.conn.execute(
        "UPDATE decree_dossiers SET closed_turn=? WHERE id=?", (state.turn, dossier_id),
    )
    db.conn.commit()
    assert db.list_economy_moves_for_dossier(dossier_id) == []
    before = _pop(db, "流民", "shaanxi")
    _advance_canned_month(db, state, content, monkeypatch)
    assert _pop(db, "流民", "shaanxi") == before


# ── 刀③ 唯一判官链 + 成色序（真实月结全链）────────────────────────────────

_NOTE_BY = {
    "fulfilled": "赈银尽数到位，流民就抚",
    "degraded": "赈银半途折损，仅部分就抚",
    "failed": "押解尽失，赈务无成",
    "transformed": "银两被挪作他用，名实已乖",
}


def _in_transit_recovery_grant(db, state, *, amount=40, region_id="shaanxi", tag="赈"):
    """真实 recovery producer：in_transit 赈灾 → executing + 实付。"""
    state.metrics["内库"] = max(int(state.metrics.get("内库") or 0), amount + 50)
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text=f"赈灾{region_id}-{tag}",
        target_kind="region",
        target_id=region_id,
        region_id=region_id,
        payload={
            "grant_action": "赈灾",
            "account": "内库",
            "amount": amount,
            "execution_surface": "in_transit",
            "cadence": "一次性",
        },
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    row = db.get_decree_dossier(dossier_id)
    assert row["status"] == "executing"
    assert row["execution_outcome"] in ("", None)
    moves = db.list_economy_moves_for_dossier(dossier_id)
    assert moves and any(int(m.get("delta") or 0) < 0 for m in moves)
    return dossier_id


def _insert_shaanxi_disaster(db, state):
    db.insert_issue(
        state,
        kind="situation",
        title="陕西大饥",
        origin_kind="test",
        severity=70,
        region_hint="shaanxi",
        tags=["饥荒"],
        bar_value=10,
        bar_good_meaning="缓",
        bar_bad_meaning="剧",
        stage_text="饥",
        cancellable="never",
        commit=True,
    )


def _canned_judge(monkeypatch, *, outcome, dossier_id, sim_calls):
    """共享 canned_full_settlement + 本票 issues 抄录/噪声跳过。"""
    if outcome is None:
        narrative = (
            f"本月陕西饥情仍重，案卷 dossier:{dossier_id} 赈银尚在途中押解，"
            f"地方尚未回报办差结局。"
        )
    else:
        note = _NOTE_BY[outcome]
        narrative = (
            f"案卷 dossier:{dossier_id} 陕西赈灾执行结果已明：{note}。"
            f"灾情挤占下成色如上。"
        )
    canned_full_settlement(
        monkeypatch,
        narrative=narrative,
        simulator_calls=sim_calls,
        skip_fixed_flows=True,
    )


def _force_in_transit_recovery_grant(db, state, *, amount=40, region_id="shaanxi", tag="赈"):
    """真实强颁：打回后强颁。在途赈灾付银后停在 executing，不留 promulgated。"""
    from tests.dossier_test_helpers import rejected_verdict

    state.metrics["内库"] = max(int(state.metrics.get("内库") or 0), amount + 50)
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text=f"赈灾{region_id}-{tag}",
        target_kind="region",
        target_id=region_id,
        region_id=region_id,
        payload={
            "grant_action": "赈灾",
            "account": "内库",
            "amount": amount,
            "execution_surface": "in_transit",
            "cadence": "一次性",
        },
    )
    db.apply_dossier_verdicts(state, [rejected_verdict(dossier_id)])
    db.apply_dossier_promulgation(state, dossier_id, "force_promulgated")
    row = db.get_decree_dossier(dossier_id)
    assert row["status"] == "executing"
    assert str(row["execution_outcome"] or "") == ""
    assert any(int(move.get("delta") or 0) < 0 for move in db.list_economy_moves_for_dossier(dossier_id))
    return dossier_id


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_recovery_shared_pool_advances_once_after_empty_effect_month(game, monkeypatch):
    """无效果月同省多案仅在推进时分配余池；读档重进不再扣。"""
    db, state, content = game
    db.conn.execute(
        "UPDATE classes SET population=100000 WHERE name='流民' AND region_id='shaanxi'"
    )
    db.conn.commit()
    _recovery_grant(db, state, amount=30)
    _recovery_grant(db, state, amount=30)
    before_farmers = _pop(db, "农民", "shaanxi")
    canned_full_settlement(monkeypatch, skip_fixed_flows=True)
    session = make_light_session(db, state, content)
    waiting = session.advance_without_decree()
    assert waiting.stage == "gazette"
    assert _pop(db, "流民", "shaanxi") == 100000
    closed_turn = state.turn
    db.conn.execute(
        "INSERT INTO turn_reports (turn, year, period, report) VALUES (?, ?, ?, ?)",
        (closed_turn, state.year, state.period, "邸报已成"),
    )
    db.conn.commit()
    # 推进事务在回流之后崩溃：回滚池、重试只执行一次。
    original_next_period = state.next_period
    def fail_advance():
        raise RuntimeError("advance interrupted")
    monkeypatch.setattr(state, "next_period", fail_advance)
    from ming_sim.exceptions import SettlementAbort
    with pytest.raises(SettlementAbort):
        session.advance_without_decree()
    assert _pop(db, "流民", "shaanxi") == 100000
    monkeypatch.setattr(state, "next_period", original_next_period)
    assert session.advance_without_decree().advanced is True
    assert _pop(db, "流民", "shaanxi") == 0
    assert _pop(db, "农民", "shaanxi") == before_farmers + 100000
    from ming_sim.db import GameDB
    loaded = GameDB(_database_path(db), content)
    try:
        assert loaded.load_state().turn == closed_turn + 1
        assert _pop(loaded, "流民", "shaanxi") == 0
        assert _pop(loaded, "农民", "shaanxi") == before_farmers + 100000
    finally:
        loaded.close()


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_monthly_recovery_follows_each_month_actual_payment(game, monkeypatch):
    db, state, content = game
    _reset_shaanxi_pool(db)
    dossier_id = _recovery_grant(db, state, amount=10, cadence="每月")
    canned_full_settlement(monkeypatch)
    session = make_light_session(db, state, content)
    before = _pop(db, "流民", "shaanxi")
    for _ in range(2):
        waiting = session.advance_without_decree()
        assert waiting.stage == "gazette"
        turn = state.turn
        paid = db.conn.execute(
            "SELECT COALESCE(SUM(-delta), 0) FROM economy_ledger "
            "WHERE origin_ref=? AND turn=? AND delta<0",
            (f"dossier:{dossier_id}", turn),
        ).fetchone()[0]
        assert paid > 0
        db.conn.execute(
            "INSERT INTO turn_reports (turn, year, period, report) VALUES (?, ?, ?, ?)",
            (turn, state.year, state.period, "邸报已成"),
        )
        db.conn.commit()
        assert session.advance_without_decree().advanced is True
        after = _pop(db, "流民", "shaanxi")
        assert after < before
        before = after


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_in_transit_relief_stays_executing_before_gazette(game, monkeypatch):
    """次月无旨：真实强颁留下的在途赈灾，经世界段与转译落账，读档后仍在。

    模型替身只接外部调用，不读开场或段文。引擎不代选成败。
    """
    import ming_sim.month_chain as month_chain
    import ming_sim.month_translate as month_translate
    from ming_sim.materials import continuing_dossier_facts
    from ming_sim.models import LLMConfig

    real_world = month_chain.run_world_segment_text
    real_translate = month_translate.translate_month_segment

    db, state, content = game
    amount = 40
    _reset_shaanxi_pool(db)
    state.metrics["内库"] = max(int(state.metrics.get("内库") or 0), amount * 2 + 50)
    shaanxi_id = _force_in_transit_recovery_grant(db, state, amount=amount, tag="west")
    henan_id = _in_transit_recovery_grant(
        db, state, amount=amount, region_id="henan", tag="east",
    )
    state.next_period()
    db.save_state(state)

    sim_calls: list = []
    _canned_judge(
        monkeypatch, outcome="fulfilled", dossier_id=shaanxi_id,
        sim_calls=sim_calls,
    )
    monkeypatch.setattr(month_chain, "run_world_segment_text", real_world)
    monkeypatch.setattr(month_translate, "translate_month_segment", real_translate)

    def _world_model(_agent, _message, tag, **_kwargs):
        if tag == "gazette":
            return '{"title":"邸报","report":"本月赈灾实况。"}'
        assert tag == "world-segment"
        return "handled"

    def _translate_model(_prompt, _llm_config, *, tag, policy=None):
        del _prompt, policy
        assert tag == "month_segment_translate"
        # 本月各效果段不得预支下月回流。
        assert _pop(db, "流民", "shaanxi") == displaced_before
        return {"effects": {"dossier_executions": [{
            "dossier_id": shaanxi_id,
            "outcome": "fulfilled",
            "note": "declared",
        }]}}

    monkeypatch.setattr("ming_sim.agents.run_agent_text", _world_model)
    monkeypatch.setattr(
        month_translate, "run_declaration_translate_prompt", _translate_model,
    )

    displaced_before = _pop(db, "流民", "shaanxi")
    farmer_before = _pop(db, "农民", "shaanxi")
    closed_turn = int(state.turn)
    session = make_light_session(db, state, content)
    session.llm_config = LLMConfig(
        api_key="test", base_url="http://127.0.0.1:9", model="test", channel="api",
    )
    result = session.advance_without_decree()
    assert result is not None and result.awaiting is False
    assert result.advanced is True
    assert int(state.turn) == closed_turn + 1

    loaded = GameDB(_database_path(db), content)
    try:
        loaded_state = loaded.load_state()
        landed = loaded.get_decree_dossier(shaanxi_id)
        assert landed["status"] == "closed"
        assert landed["execution_outcome"] == "fulfilled"
        assert int(landed["closed_turn"] or 0) == closed_turn
        other = loaded.get_decree_dossier(henan_id)
        assert other["status"] == "executing"
        assert str(other["execution_outcome"] or "") == ""
        still = {int(row["id"]) for row in continuing_dossier_facts(loaded, loaded_state.turn)}
        assert henan_id in still and shaanxi_id not in still
        # 回流基线＝**实抵**（652 既定口径）：这道拨帑本回合正常结案，#1900 要求
        # 照常核账，故实抵取引擎沿途折损后的账行，而非出库面额。
        recon = loaded.list_dossier_reconciliations(shaanxi_id)
        assert [int(r["turn"]) for r in recon] == [closed_turn]
        arrived = int(recon[-1]["arrived_amount"])
        assert 0 < arrived < amount
        assert _pop(loaded, "流民", "shaanxi") < displaced_before
        assert _pop(loaded, "农民", "shaanxi") > farmer_before
    finally:
        loaded.close()


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_month_settle_with_disaster_and_executing_relief(game, monkeypatch):
    """月结入口：有灾 + executing 赈灾仍走真实执行链。

    有灾必折损是推演者软判（本测不 canned 冒充成色）。
    """
    db, state, content = game
    _reset_shaanxi_pool(db)
    _insert_shaanxi_disaster(db, state)
    dossier_id = _in_transit_recovery_grant(db, state, amount=40, tag="dis-in")

    sim_calls: list = []
    # 成色任意——只为走完月结；不借此证「必折损」。
    _canned_judge(
        monkeypatch, outcome="degraded", dossier_id=dossier_id,
        sim_calls=sim_calls,
    )

    result = make_light_session(db, state, content).advance_without_decree()
    assert result is not None and result.awaiting is False
    assert result.advanced is False
    assert db.get_decree_dossier(dossier_id)["status"] == "executing"




@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_legacy_population_unit_skips_absorption_and_recovery(game, monkeypatch):
    db, state, content = game
    db.conn.execute("DELETE FROM save_meta WHERE key='population_unit'")
    db.conn.commit()
    assert db.population_unit != POPULATION_UNIT_PERSONS

    applied = apply_score_extraction(db, state, {
        "bandit_absorptions": [{
            "region_id": "shaanxi", "power_id": "bandits",
            "requested_count": 10, "origin_ref": "盘面自发",
        }],
    }, content, None)
    assert applied["bandit_absorptions"] == [] and applied["bandit_absorptions_rejections"]

    assert db.get_decree_dossier(_recovery_grant(db, state, amount=10))["execution_outcome"] == "fulfilled"
    before = _pop(db, "流民", "shaanxi")
    _advance_canned_month(db, state, content, monkeypatch)
    assert _pop(db, "流民", "shaanxi") == before


