"""#652：流民环闭合——投贼吃池顶 + 赈济/招抚回流 + 灾情判决折减。

canonical＝ADR 0087/0088/0092/0116/0142/0143 + owner A（开仓非回流 producer；
只覆盖赈济与招抚屯田；#522 pacification 不动）。

主测缝：build_simulator_payload / apply_score_extraction / settle_with_delta——
只测外部行为，不打内部桩。
"""

from __future__ import annotations

import json

import pytest

from ming_sim.constants import (
    BANDIT_ABSORPTION_PERSONS_PER_STRENGTH,
    RECOVERY_OUTCOME_FACTORS,
    RECOVERY_PERSONS_PER_WAN,
)
from ming_sim.db import GameDB, POPULATION_UNIT_PERSONS
from ming_sim.decree import settle_with_delta
from ming_sim.issues import apply_score_extraction
from ming_sim.simulation import build_simulator_payload

# ── 独立 oracle（content 冻结 seed 字面）──────────────────────────────────────
FARMER_SHAANXI = 6000000
DISPLACED_SHAANXI = 150000


def _pop(db: GameDB, name: str, region_id: str) -> int:
    row = db.conn.execute(
        "SELECT population FROM classes WHERE name=? AND region_id=?",
        (name, region_id),
    ).fetchone()
    return int(row[0]) if row else 0


def _strength(db: GameDB, power_id: str) -> int:
    row = db.conn.execute(
        "SELECT military_strength FROM powers WHERE id=?", (power_id,),
    ).fetchone()
    return int(row[0]) if row else 0


def _recovery_grant(db, state, *, action="赈灾", amount=30, region_id="shaanxi",
                    surface="immediate", account="内库"):
    state.metrics[account] = max(int(state.metrics.get(account) or 0), amount + 50)
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text=f"{action}{region_id}",
        target_kind="region",
        target_id=region_id,
        payload={
            "grant_action": action,
            "account": account,
            "amount": amount,
            "execution_surface": surface,
            "cadence": "一次性",
        },
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    return dossier_id


# ── 刀① simulator 池清单 + 投贼吸收 ──────────────────────────────────────────

def test_simulator_payload_carries_structured_displaced_pool(game):
    """接口层省级流民池清单进 simulator；与 DB classes 流民行一致。"""
    db, state, _content = game
    payload = build_simulator_payload(state, db, "", "")
    pool = payload["displaced_pool_balances"]
    assert pool["cols"] == ["region_id", "population", "population_unit"]
    rows = {r[0]: (r[1], r[2]) for r in pool["rows"]}
    assert "shaanxi" in rows
    assert rows["shaanxi"] == (DISPLACED_SHAANXI, POPULATION_UNIT_PERSONS)
    # 契约在结构化清单；classes_brief 定性投影另缝，不在此锁措辞。


def test_bandit_absorption_clamps_to_pool_and_raises_strength(game):
    """请求>池 → actual=池、池扣光、实力按 actual 换算。"""
    db, state, content = game
    power_id = "bandit_li_zicheng"
    before_str = _strength(db, power_id)
    requested = DISPLACED_SHAANXI + 50_000
    applied = apply_score_extraction(db, state, {
        "bandit_absorptions": [{
            "region_id": "shaanxi",
            "power_id": power_id,
            "requested_count": requested,
            "origin_ref": "盘面自发",
        }],
    }, content, None)
    assert not applied["bandit_absorptions_rejections"]
    rec = applied["bandit_absorptions"][0]
    assert rec["actual_count"] == DISPLACED_SHAANXI
    assert rec["strength_delta"] == DISPLACED_SHAANXI // BANDIT_ABSORPTION_PERSONS_PER_STRENGTH
    assert _pop(db, "流民", "shaanxi") == 0
    assert _strength(db, power_id) == min(
        100, before_str + rec["strength_delta"],
    )


def test_bandit_absorption_empty_pool_rejects_and_no_strength_gain(game):
    """池=0 时请求>0 → 拒收、无正增实力。"""
    db, state, content = game
    power_id = "bandit_li_zicheng"
    db.conn.execute(
        "UPDATE classes SET population=0 WHERE name='流民' AND region_id='shaanxi'"
    )
    db.conn.commit()
    before_str = _strength(db, power_id)
    applied = apply_score_extraction(db, state, {
        "bandit_absorptions": [{
            "region_id": "shaanxi",
            "power_id": power_id,
            "requested_count": 5000,
            "origin_ref": "盘面自发",
        }],
    }, content, None)
    assert applied["bandit_absorptions"] == []
    assert applied["bandit_absorptions_rejections"]
    assert _strength(db, power_id) == before_str


def test_free_positive_bandit_strength_rejected_without_absorption(game):
    """无吸收路径的流寇实力正增被拒；负增量（剿股）仍可落。"""
    db, state, content = game
    power_id = "bandit_li_zicheng"
    before = _strength(db, power_id)
    houjin_before = _strength(db, "houjin")
    applied = apply_score_extraction(db, state, {
        "power_updates": {
            power_id: {"military_strength": 5, "origin_ref": "盘面自发"},
            "houjin": {"military_strength": 2, "origin_ref": "盘面自发"},
        },
    }, content, None)
    bandit_rejects = [
        c for c in applied["power_changes"]
        if c.get("rejected") and c.get("power_id") == power_id
    ]
    assert bandit_rejects
    assert _strength(db, power_id) == before
    # 非流寇正增仍可
    assert _strength(db, "houjin") == min(100, houjin_before + 2)

    # 剿股负增量
    before2 = _strength(db, power_id)
    applied2 = apply_score_extraction(db, state, {
        "power_updates": {
            power_id: {"military_strength": -3, "origin_ref": "盘面自发"},
        },
    }, content, None)
    assert not any(
        c.get("rejected") and c.get("power_id") == power_id
        for c in applied2["power_changes"]
    )
    assert _strength(db, power_id) == max(0, before2 - 3)


def test_bandit_strength_clamps_at_100(game):
    """old+δ 触 100 上界。"""
    db, state, content = game
    power_id = "bandits"
    db.conn.execute(
        "UPDATE powers SET military_strength=99 WHERE id=?", (power_id,),
    )
    db.conn.commit()
    # 足够大的吸收以请求 +5 点
    need = 5 * BANDIT_ABSORPTION_PERSONS_PER_STRENGTH
    db.conn.execute(
        "UPDATE classes SET population=? WHERE name='流民' AND region_id='shaanxi'",
        (need,),
    )
    db.conn.commit()
    apply_score_extraction(db, state, {
        "bandit_absorptions": [{
            "region_id": "shaanxi",
            "power_id": power_id,
            "requested_count": need,
            "origin_ref": "盘面自发",
        }],
    }, content, None)
    assert _strength(db, power_id) == 100


# ── 刀② typed recovery producer ─────────────────────────────────────────────

def test_relief_grant_produces_回流_on_settle(game):
    """typed 赈灾 + 已付成本 + 执行判决 → 一流民→农民回流；钱面有扣。"""
    db, state, content = game
    amount_wan = 30
    treasury_before = int(state.metrics["内库"])
    dossier_id = _recovery_grant(
        db, state, action="赈灾", amount=amount_wan, surface="immediate",
    )
    row = db.get_decree_dossier(dossier_id)
    assert row["status"] == "closed"
    assert row["execution_outcome"] == "fulfilled"
    assert int(state.metrics["内库"]) == treasury_before - amount_wan

    displaced_before = _pop(db, "流民", "shaanxi")
    farmer_before = _pop(db, "农民", "shaanxi")
    expected = int(round(amount_wan * RECOVERY_PERSONS_PER_WAN * RECOVERY_OUTCOME_FACTORS["fulfilled"]))
    expected = min(expected, displaced_before)

    report_or_applied = settle_with_delta(
        state, db, {}, before_turn=state.turn, content=content, narrative="赈灾落地",
    )
    # settle 返回 report 字符串或副作用在 DB；读 turn_extraction
    turn = state.turn - 1  # settle 已 next_period
    extraction = db.get_turn_extraction(turn)
    assert extraction is not None
    transfers = extraction["extractor_output"]["population_transfers"]
    reflux = [t for t in transfers if t.get("reason") == "回流"]
    assert len(reflux) == 1
    assert reflux[0]["origin_ref"] == f"dossier:{dossier_id}"
    assert reflux[0]["amount"] == expected
    assert _pop(db, "流民", "shaanxi") == displaced_before - expected
    assert _pop(db, "农民", "shaanxi") == farmer_before + expected


def test_resettlement_grant_action_also_produces_回流(game):
    """招抚屯田同为 recovery 身份。"""
    db, state, content = game
    dossier_id = _recovery_grant(
        db, state, action="招抚屯田", amount=10, surface="immediate",
    )
    settle_with_delta(
        state, db, {}, before_turn=state.turn, content=content, narrative="招抚屯田",
    )
    turn = state.turn - 1
    transfers = db.get_turn_extraction(turn)["extractor_output"]["population_transfers"]
    reflux = [t for t in transfers if t.get("reason") == "回流"]
    assert len(reflux) == 1
    assert reflux[0]["origin_ref"] == f"dossier:{dossier_id}"


def test_recovery_fires_once_across_subsequent_settles(game):
    """同一 closed recovery 案卷只在 closed_turn 当月出回流；下月 settle 不双扣。"""
    db, state, content = game
    _recovery_grant(db, state, action="赈灾", amount=20, surface="immediate")
    settle_with_delta(
        state, db, {}, before_turn=state.turn, content=content, narrative="一次",
    )
    after_first = _pop(db, "流民", "shaanxi")
    first_turn = state.turn - 1
    first_reflux = [
        t for t in db.get_turn_extraction(first_turn)["extractor_output"]["population_transfers"]
        if t.get("reason") == "回流"
    ]
    assert len(first_reflux) == 1

    settle_with_delta(
        state, db, {}, before_turn=state.turn, content=content, narrative="下月",
    )
    second_turn = state.turn - 1
    second_transfers = db.get_turn_extraction(second_turn)["extractor_output"]["population_transfers"]
    assert not any(t.get("reason") == "回流" for t in second_transfers)
    assert _pop(db, "流民", "shaanxi") == after_first


def test_llm_free_回流_rejected_engine_still_lands(game):
    """internal 自由回流拒收；单核仍可落地。"""
    db, state, content = game
    free = apply_score_extraction(db, state, {
        "population_transfers": [{
            "source": "流民@shaanxi",
            "target": "农民@shaanxi",
            "amount": 1000,
            "reason": "回流",
            "origin_ref": "盘面自发",
        }],
    }, content, None)
    assert free["population_transfers"] == []
    assert free["population_transfers_rejections"]
    assert _pop(db, "流民", "shaanxi") == DISPLACED_SHAANXI

    _recovery_grant(db, state, action="赈灾", amount=15, surface="immediate")
    settle_with_delta(
        state, db, {}, before_turn=state.turn, content=content, narrative="单核",
    )
    turn = state.turn - 1
    transfers = db.get_turn_extraction(turn)["extractor_output"]["population_transfers"]
    assert any(t.get("reason") == "回流" for t in transfers)


def test_non_recovery_grant_no_回流(game):
    """非 RECOVERY_GRANT_ACTIONS 的拨帑（项目经费）即使足额扣库+fulfilled 也不产回流。"""
    db, state, content = game
    state.metrics["内库"] = max(int(state.metrics.get("内库") or 0), 80)
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text="项目经费",
        target_kind="issue",
        target_id="project_dummy",
        payload={
            "grant_action": "项目经费",
            "account": "内库",
            "amount": 5,
            "execution_surface": "immediate",
            "cadence": "一次性",
        },
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    row = db.get_decree_dossier(dossier_id)
    assert row["status"] == "closed"
    assert row["execution_outcome"] == "fulfilled"
    assert db.list_economy_moves_for_dossier(dossier_id), "夹具须实付入账"

    settle_with_delta(
        state, db, {}, before_turn=state.turn, content=content, narrative="非回流",
    )
    turn = state.turn - 1
    extraction = db.get_turn_extraction(turn)
    transfers = (extraction or {}).get("extractor_output", {}).get("population_transfers") or []
    assert not any(t.get("reason") == "回流" for t in transfers)


def test_recovery_without_paid_evidence_produces_nothing(game):
    """无实付证据（零 ledger、零对账）→ settle 后即使 closed+fulfilled 也不产回流。"""
    db, state, content = game
    dossier_id = _recovery_grant(
        db, state, action="赈灾", amount=30, surface="immediate",
    )
    row = db.get_decree_dossier(dossier_id)
    assert row["status"] == "closed"
    assert row["execution_outcome"] == "fulfilled"
    assert db.list_economy_moves_for_dossier(dossier_id), "成案须先有实付再剥离"
    db.conn.execute(
        "DELETE FROM economy_ledger WHERE origin_ref=?",
        (f"dossier:{dossier_id}",),
    )
    db.conn.execute(
        "DELETE FROM decree_dossier_reconciliations WHERE dossier_id=?",
        (dossier_id,),
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET closed_turn=? WHERE id=?",
        (state.turn, dossier_id),
    )
    db.conn.commit()
    assert db.list_economy_moves_for_dossier(dossier_id) == []
    assert db.list_dossier_reconciliations(dossier_id) == []
    displaced_before = _pop(db, "流民", "shaanxi")

    before_turn = state.turn
    settle_with_delta(
        state, db, {}, before_turn=before_turn, content=content, narrative="无实付",
    )
    transfers = db.get_turn_extraction(before_turn)["extractor_output"]["population_transfers"]
    assert not any(t.get("reason") == "回流" for t in transfers)
    assert _pop(db, "流民", "shaanxi") == displaced_before


# ── 刀③ 灾情判决折减序 ──────────────────────────────────────────────────────

def test_worse_execution_outcome_yields_less_recovery(game):
    """同成本同池：较差结构化执行判决 → settle 后回流更少。"""
    db, state, content = game
    amount_wan = 40

    def _run(outcome: str) -> int:
        # 每 outcome：重置省池 → 新案 → 改写 outcome → settle_with_delta 真入口。
        db.conn.execute(
            "UPDATE classes SET population=? WHERE name='流民' AND region_id='shaanxi'",
            (DISPLACED_SHAANXI,),
        )
        db.conn.execute(
            "UPDATE classes SET population=? WHERE name='农民' AND region_id='shaanxi'",
            (FARMER_SHAANXI,),
        )
        db.conn.commit()
        state.metrics["内库"] = max(int(state.metrics.get("内库") or 0), amount_wan + 50)

        dossier_id = db.create_decree_dossier(
            state,
            action_type="grant_allocation",
            decree_text=f"赈灾-{outcome}-{state.turn}",
            target_kind="region",
            target_id="shaanxi",
            payload={
                "grant_action": "赈灾",
                "account": "内库",
                "amount": amount_wan,
                "execution_surface": "immediate",
                "cadence": "一次性",
            },
        )
        db.apply_dossier_promulgation(state, dossier_id, "promulgated")
        db.conn.execute(
            "UPDATE decree_dossiers SET execution_outcome=?, closed_turn=? WHERE id=?",
            (outcome, state.turn, dossier_id),
        )
        db.conn.commit()
        before_turn = state.turn
        settle_with_delta(
            state, db, {}, before_turn=before_turn, content=content,
            narrative=f"判决{outcome}",
        )
        transfers = db.get_turn_extraction(before_turn)["extractor_output"]["population_transfers"]
        reflux = [
            t for t in transfers
            if t.get("reason") == "回流" and t.get("origin_ref") == f"dossier:{dossier_id}"
        ]
        return int(reflux[0]["amount"]) if reflux else 0

    full = _run("fulfilled")
    degraded = _run("degraded")
    failed = _run("failed")
    assert full > degraded > 0
    assert failed == 0
    assert full == int(round(amount_wan * RECOVERY_PERSONS_PER_WAN * 1.0))
    assert degraded == int(round(amount_wan * RECOVERY_PERSONS_PER_WAN * 0.5))


def test_legacy_population_unit_skips_absorption_and_recovery(game):
    """legacy 万口径：吸收拒收；有实付 recovery 案 settle 亦不产回流。"""
    db, state, content = game
    db.conn.execute("DELETE FROM save_meta WHERE key='population_unit'")
    db.conn.commit()
    assert db.population_unit != POPULATION_UNIT_PERSONS

    applied = apply_score_extraction(db, state, {
        "bandit_absorptions": [{
            "region_id": "shaanxi",
            "power_id": "bandits",
            "requested_count": 10,
            "origin_ref": "盘面自发",
        }],
    }, content, None)
    assert applied["bandit_absorptions"] == []
    assert applied["bandit_absorptions_rejections"]

    # recovery 单核同样门控：实付+fulfilled 在 legacy 档仍零回流
    dossier_id = _recovery_grant(
        db, state, action="赈灾", amount=10, surface="immediate",
    )
    assert db.get_decree_dossier(dossier_id)["execution_outcome"] == "fulfilled"
    before_turn = state.turn
    settle_with_delta(
        state, db, {}, before_turn=before_turn, content=content, narrative="legacy",
    )
    transfers = db.get_turn_extraction(before_turn)["extractor_output"]["population_transfers"]
    assert not any(t.get("reason") == "回流" for t in transfers)
