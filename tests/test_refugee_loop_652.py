"""#652：流民环闭合——投贼吃池顶 + 赈济/招抚回流 + 唯一判官成色链。

主测缝：build_simulator_payload / apply_score_extraction / settle_with_delta
／advance_without_decree（可控 LLM seam 真实月结）。
owner A：开仓非回流 producer；只覆盖赈济与招抚屯田；#522 不动。
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from ming_sim.applier import atomic
from ming_sim.constants import (
    BANDIT_ABSORPTION_PERSONS_PER_STRENGTH,
    RECOVERY_OUTCOME_FACTORS,
    RECOVERY_PERSONS_PER_WAN,
)
from ming_sim.db import GameDB, POPULATION_UNIT_PERSONS, grant_arrival_bounds
from ming_sim.decree import settle_with_delta
from ming_sim.issues import apply_score_extraction
from ming_sim.simulation import EXTRACTION_MODULES, build_simulator_payload
from tests.settlement_seam_helpers import canned_full_settlement, make_light_session

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


def _recovery_grant(db, state, *, action="赈灾", amount=30, region_id="shaanxi"):
    state.metrics["内库"] = max(int(state.metrics.get("内库") or 0), amount + 50)
    dossier_id = db.create_decree_dossier(
        state, action_type="grant_allocation",
        decree_text=f"{action}{region_id}",
        target_kind="region", target_id=region_id,
        payload={
            "grant_action": action, "account": "内库", "amount": amount,
            "execution_surface": "immediate", "cadence": "一次性",
        },
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    return dossier_id


def _settle_transfers(state, db, content, narrative="settle"):
    before = state.turn
    settle_with_delta(state, db, {}, before_turn=before, content=content, narrative=narrative)
    return db.get_turn_extraction(before)["extractor_output"]["population_transfers"]


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

def test_simulator_payload_carries_structured_displaced_pool(game):
    db, state, _ = game
    pool = build_simulator_payload(state, db, "", "")["displaced_pool_balances"]
    assert pool["cols"] == ["region_id", "population", "population_unit"]
    rows = {r[0]: (r[1], r[2]) for r in pool["rows"]}
    assert rows["shaanxi"] == (DISPLACED_SHAANXI, POPULATION_UNIT_PERSONS)


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


def test_occupied_region_is_hidden_and_rejected_for_absorption(game):
    db, state, content = game
    pid = "bandit_li_zicheng"
    before_pool = _pop(db, "流民", "shaanxi")
    before_strength = _strength(db, pid)
    db.conn.execute("UPDATE regions SET controlled_by='bandits' WHERE id='shaanxi'")
    db.conn.commit()

    rows = build_simulator_payload(state, db, "", "")["displaced_pool_balances"]["rows"]
    assert all(row[0] != "shaanxi" for row in rows)
    applied = apply_score_extraction(db, state, {
        "bandit_absorptions": [{
            "region_id": "shaanxi", "power_id": pid,
            "requested_count": 10_000, "origin_ref": "盘面自发",
        }],
    }, content, None)
    assert applied["bandit_absorptions"] == []
    assert applied["bandit_absorptions_rejections"][0]["category"] == "missing_ref"
    assert _pop(db, "流民", "shaanxi") == before_pool
    assert _strength(db, pid) == before_strength


def test_bandit_absorption_clamps_pool_strength_and_ceiling(game):
    """超池 clamp；实力按 actual；触 100 上界；空池拒收无正增。"""
    db, state, content = game
    pid = "bandit_li_zicheng"
    before = _strength(db, pid)
    applied = apply_score_extraction(db, state, {
        "bandit_absorptions": [{
            "region_id": "shaanxi", "power_id": pid,
            "requested_count": DISPLACED_SHAANXI + 50_000, "origin_ref": "盘面自发",
        }],
    }, content, None)
    assert not applied["bandit_absorptions_rejections"]
    rec = applied["bandit_absorptions"][0]
    assert rec["actual_count"] == DISPLACED_SHAANXI
    delta = DISPLACED_SHAANXI // BANDIT_ABSORPTION_PERSONS_PER_STRENGTH
    assert rec["strength_delta"] == delta
    assert _pop(db, "流民", "shaanxi") == 0
    assert _strength(db, pid) == min(100, before + delta)

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
    need = 5 * BANDIT_ABSORPTION_PERSONS_PER_STRENGTH
    db.conn.execute(
        "UPDATE classes SET population=? WHERE name='流民' AND region_id='henan'", (need,),
    )
    db.conn.commit()
    apply_score_extraction(db, state, {
        "bandit_absorptions": [{
            "region_id": "henan", "power_id": "bandits",
            "requested_count": need, "origin_ref": "盘面自发",
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
    assert rec["strength_delta"] == clean_req // BANDIT_ABSORPTION_PERSONS_PER_STRENGTH
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


# ── 刀② recovery producer ───────────────────────────────────────────────────

@pytest.mark.parametrize("action", ["赈灾", "招抚屯田"])
def test_recovery_grant_produces_回流_on_settle(game, action):
    db, state, content = game
    amount = 30
    treasury_before = int(state.metrics["内库"])
    dossier_id = _recovery_grant(db, state, action=action, amount=amount)
    row = db.get_decree_dossier(dossier_id)
    assert row["status"] == "closed" and row["execution_outcome"] == "fulfilled"
    assert int(state.metrics["内库"]) == treasury_before - amount
    assert db.list_economy_moves_for_dossier(dossier_id)

    displaced_before, farmer_before = _pop(db, "流民", "shaanxi"), _pop(db, "农民", "shaanxi")
    expected = min(int(round(amount * RECOVERY_PERSONS_PER_WAN)), displaced_before)
    transfers = _settle_transfers(state, db, content, action)
    reflux = _reflux(transfers, dossier_id=dossier_id)
    assert len(reflux) == 1 and reflux[0]["amount"] == expected
    assert _pop(db, "流民", "shaanxi") == displaced_before - expected
    assert _pop(db, "农民", "shaanxi") == farmer_before + expected


def test_paid_recovery_preempts_same_turn_absorption(game):
    db, state, content = game
    db.conn.execute(
        "UPDATE classes SET population=100000 WHERE name='流民' AND region_id='shaanxi'"
    )
    db.conn.commit()
    pid = "bandit_li_zicheng"
    dossier_id = _recovery_grant(db, state, amount=30)
    strength_before = _strength(db, pid)
    before_turn = int(state.turn)
    settle_with_delta(
        state, db, {
            "bandit_absorptions": [{
                "region_id": "shaanxi", "power_id": pid,
                "requested_count": 100_000, "origin_ref": "盘面自发",
            }],
        }, before_turn=before_turn, content=content, narrative="回流先于投贼",
    )
    output = db.get_turn_extraction(before_turn)["extractor_output"]
    reflux = _reflux(output["population_transfers"], dossier_id=dossier_id)
    absorption = output["bandit_absorptions"]
    assert [item["amount"] for item in reflux] == [60_000]
    assert [item["actual_count"] for item in absorption] == [40_000]
    assert _pop(db, "流民", "shaanxi") == 0
    assert _strength(db, pid) == (
        strength_before + 40_000 // BANDIT_ABSORPTION_PERSONS_PER_STRENGTH
    )


def test_two_recovery_dossiers_share_remaining_pool(game):
    db, state, content = game
    db.conn.execute(
        "UPDATE classes SET population=100000 WHERE name='流民' AND region_id='shaanxi'"
    )
    db.conn.commit()
    first = _recovery_grant(db, state, amount=30)
    second = _recovery_grant(db, state, amount=30)
    farmer_before = _pop(db, "农民", "shaanxi")

    reflux = _reflux(_settle_transfers(state, db, content, "双案同省"))
    assert [(r["origin_ref"], r["amount"]) for r in reflux] == [
        (f"dossier:{first}", 60_000),
        (f"dossier:{second}", 40_000),
    ]
    assert _pop(db, "流民", "shaanxi") == 0
    assert _pop(db, "农民", "shaanxi") == farmer_before + 100_000


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_monthly_recovery_uses_each_turn_fixed_payment(game, monkeypatch):
    db, state, content = game
    state.metrics["内库"] = 10_000
    dossier_id = db.create_decree_dossier(
        state, action_type="grant_allocation", decree_text="陕西每月赈济",
        target_kind="region", target_id="shaanxi",
        payload={
            "grant_action": "赈灾", "account": "内库", "amount": 10,
            "execution_surface": "immediate", "cadence": "每月",
        },
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    assert db.get_decree_dossier(dossier_id)["execution_outcome"] == "fulfilled"
    pool_before = _pop(db, "流民", "shaanxi")
    canned_full_settlement(
        monkeypatch, extract_result={}, skip_relation_brew=True,
    )
    session = make_light_session(db, state, content)

    turn_one = int(state.turn)
    session.advance_without_decree()
    first = _reflux(
        db.get_turn_extraction(turn_one)["extractor_output"]["population_transfers"],
        dossier_id=dossier_id,
    )
    turn_two = int(state.turn)
    session.advance_without_decree()
    second = _reflux(
        db.get_turn_extraction(turn_two)["extractor_output"]["population_transfers"],
        dossier_id=dossier_id,
    )

    assert [item["amount"] for item in first] == [20_000]
    assert [item["amount"] for item in second] == [20_000]
    assert _pop(db, "流民", "shaanxi") == pool_before - 40_000
    paid_turns = {
        int(move["turn"])
        for move in db.list_economy_moves_for_dossier(dossier_id)
        if int(move.get("delta") or 0) < 0
    }
    assert {turn_one, turn_two}.issubset(paid_turns)


def test_recovery_fires_once_across_subsequent_settles(game):
    db, state, content = game
    _recovery_grant(db, state, amount=20)
    first = _reflux(_settle_transfers(state, db, content, "一次"))
    assert len(first) == 1
    after = _pop(db, "流民", "shaanxi")
    second = _settle_transfers(state, db, content, "下月")
    assert not _reflux(second)
    assert _pop(db, "流民", "shaanxi") == after


def test_llm_free_回流_rejected_engine_still_lands(game):
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

    _recovery_grant(db, state, amount=15)
    assert _reflux(_settle_transfers(state, db, content, "单核"))


def test_non_recovery_grant_no_回流(game):
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
    assert not _reflux(_settle_transfers(state, db, content, "非回流"))


def test_recovery_without_paid_evidence_produces_nothing(game):
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
    assert not _reflux(_settle_transfers(state, db, content, "无实付"))
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


def _canned_judge(monkeypatch, *, outcome, dossier_id, sim_calls, extract_calls, modules_seen):
    """共享 canned_full_settlement + 本票 issues 抄录/噪声跳过。"""
    if outcome is None:
        narrative = (
            f"本月陕西饥情仍重，案卷 dossier:{dossier_id} 赈银尚在途中押解，"
            f"地方尚未回报办差结局。"
        )
        extract_result: dict = {"dossier_executions": []}
    else:
        note = _NOTE_BY[outcome]
        narrative = (
            f"案卷 dossier:{dossier_id} 陕西赈灾执行结果已明：{note}。"
            f"灾情挤占下成色如上。"
        )
        extract_result = {
            "dossier_executions": [{
                "dossier_id": dossier_id, "outcome": outcome, "note": note,
            }],
        }
    canned_full_settlement(
        monkeypatch,
        narrative=narrative,
        simulator_calls=sim_calls,
        extract_result=extract_result,
        extract_calls=extract_calls,
        modules_seen=modules_seen,
        skip_fixed_flows=True,
        skip_relation_brew=True,
    )


def _assert_two_axis_projection(payload, *, expect_disaster: bool = False):
    assert "execution_two_axis" in payload
    surface = payload["execution_two_axis"]
    dumped = json.dumps(surface, ensure_ascii=False)
    assert "owner_ability" not in dumped
    assert "owner_load" not in dumped
    shaanxi = next(
        (p for p in surface.get("provinces") or [] if p.get("region_id") == "shaanxi"),
        None,
    )
    assert shaanxi is not None, "executing 陕差须出现在 two_axis"
    if expect_disaster:
        assert shaanxi.get("disaster_rows"), "有灾 fixture 时须含灾情占用字段"


def _shaanxi_pool_from_payload(payload) -> int:
    table = payload.get("displaced_pool_balances") or {}
    cols = list(table.get("cols") or [])
    rows = list(table.get("rows") or [])
    try:
        ri = cols.index("region_id")
        pi = cols.index("population")
    except ValueError:
        return 0
    for row in rows:
        if str(row[ri]) == "shaanxi":
            return int(row[pi])
    return 0


def _shaanxi_reflux_causes_from_payload(payload) -> list[dict]:
    """Typed recent_reflux_causes rows for shaanxi only (no text locks)."""
    table = payload.get("recent_reflux_causes") or {}
    cols = list(table.get("cols") or [])
    rows = list(table.get("rows") or [])
    if not cols or not rows:
        return []
    out = []
    for row in rows:
        item = {cols[i]: row[i] for i in range(min(len(cols), len(row)))}
        if str(item.get("region_id") or "") == "shaanxi":
            out.append(item)
    return out


def _expected_recovery(amount: int, outcome: str, pool: int) -> int:
    lo, hi = grant_arrival_bounds(amount, escorted=False)
    silver = (lo + hi) // 2
    factor = float(RECOVERY_OUTCOME_FACTORS[outcome])
    return min(int(round(silver * RECOVERY_PERSONS_PER_WAN * factor)), pool)


@pytest.mark.usefixtures("_offline_scene_beat_generator")
@pytest.mark.parametrize("outcome", ["fulfilled", "degraded", "failed", "transformed"])
def test_judge_chain_outcome_recovery(game, monkeypatch, outcome):
    """无灾成色序：唯一判官装配 + issues 抄录 + recovery（禁 UPDATE 冒充）。

    成色序：fulfilled > degraded > 0；failed == transformed == 0。
    有灾赈灾必折损属 season_simulator 软判契约，本测不冒充。
    """
    db, state, content = game
    amount = 40
    _reset_shaanxi_pool(db)
    dossier_id = _in_transit_recovery_grant(db, state, amount=amount, tag=outcome)

    sim_calls: list = []
    extract_calls: list = []
    modules_seen: list = []
    _canned_judge(
        monkeypatch, outcome=outcome, dossier_id=dossier_id,
        sim_calls=sim_calls, extract_calls=extract_calls, modules_seen=modules_seen,
    )

    displaced_before = _pop(db, "流民", "shaanxi")
    farmer_before = _pop(db, "农民", "shaanxi")
    closed_turn = int(state.turn)

    result = make_light_session(db, state, content).advance_without_decree()
    assert result is not None and result.awaiting is False

    assert len(sim_calls) == 1
    assert len(extract_calls) == 1
    assert set(modules_seen) == set(EXTRACTION_MODULES)
    assert len(modules_seen) == len(EXTRACTION_MODULES)

    _assert_two_axis_projection(sim_calls[0]["payload"], expect_disaster=False)

    row = db.get_decree_dossier(dossier_id)
    assert row["status"] == "closed"
    assert row["execution_outcome"] == outcome
    assert int(row["closed_turn"] or 0) == closed_turn

    expected = _expected_recovery(amount, outcome, displaced_before)
    extraction = db.get_turn_extraction(closed_turn)
    transfers = (extraction or {}).get("extractor_output", {}).get("population_transfers") or []
    actual = sum(int(t.get("amount") or 0) for t in _reflux(transfers, dossier_id=dossier_id))
    assert actual == expected
    assert _pop(db, "流民", "shaanxi") == displaced_before - expected
    assert _pop(db, "农民", "shaanxi") == farmer_before + expected


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_month_settle_carries_disaster_rows_to_judge(game, monkeypatch):
    """月结入口：有灾 + executing 赈灾时 two_axis 灾行进入唯一判官输入。

    有灾必折损是 season_simulator 软判（本测不 canned 冒充成色）。
    """
    db, state, content = game
    _reset_shaanxi_pool(db)
    _insert_shaanxi_disaster(db, state)
    dossier_id = _in_transit_recovery_grant(db, state, amount=40, tag="dis-in")

    sim_calls: list = []
    extract_calls: list = []
    modules_seen: list = []
    # 成色任意——只为走完月结；不借此证「必折损」。
    _canned_judge(
        monkeypatch, outcome="degraded", dossier_id=dossier_id,
        sim_calls=sim_calls, extract_calls=extract_calls, modules_seen=modules_seen,
    )

    result = make_light_session(db, state, content).advance_without_decree()
    assert result is not None and result.awaiting is False
    assert len(sim_calls) == 1
    _assert_two_axis_projection(sim_calls[0]["payload"], expect_disaster=True)


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_post_relief_pool_carries_into_next_month_absorption(game, monkeypatch):
    """跨月池传导：月1 赈济减池；月2 payload 携下降后池；吸收 applier 吃该池落账。"""
    db, state, content = game
    pid = "bandit_li_zicheng"
    _reset_shaanxi_pool(db)
    pool0 = _pop(db, "流民", "shaanxi")
    strength0 = _strength(db, pid)
    dossier_id = _recovery_grant(db, state, amount=30)

    sess = make_light_session(db, state, content)

    # 月1：只走回流，不吸池；回流尚未入近窗前账 → 无陕西赈灾原因行
    sim_m1: list = []
    canned_full_settlement(
        monkeypatch,
        narrative="本月赈银到位，流民渐有归农气象。",
        extract_result={},
        simulator_calls=sim_m1,
        skip_fixed_flows=True,
        skip_relation_brew=True,
    )
    r1 = sess.advance_without_decree()
    assert r1 is not None and r1.awaiting is False
    assert len(sim_m1) == 1
    m1_causes = _shaanxi_reflux_causes_from_payload(sim_m1[0]["payload"])
    assert not any(
        c.get("grant_action") == "赈灾" and c.get("origin_ref") == f"dossier:{dossier_id}"
        for c in m1_causes
    )
    pool_after = _pop(db, "流民", "shaanxi")
    assert pool_after < pool0
    assert _strength(db, pid) == strength0

    # 月2：payload 须见下降后池 + 月1 真实回流原因行；请求按赈前满池，applier 吃现池顶
    sim_m2: list = []
    turn2 = int(state.turn)
    canned_full_settlement(
        monkeypatch,
        narrative="陕西流民池已降，饥民投附仍据现池。",
        extract_result={
            "bandit_absorptions": [{
                "region_id": "shaanxi",
                "power_id": pid,
                "requested_count": pool0,
                "origin_ref": "盘面自发",
            }],
        },
        simulator_calls=sim_m2,
        skip_fixed_flows=True,
        skip_relation_brew=True,
    )
    r2 = sess.advance_without_decree()
    assert r2 is not None and r2.awaiting is False
    assert len(sim_m2) == 1
    assert _shaanxi_pool_from_payload(sim_m2[0]["payload"]) == pool_after
    m2_causes = _shaanxi_reflux_causes_from_payload(sim_m2[0]["payload"])
    assert any(
        c.get("grant_action") == "赈灾" and c.get("origin_ref") == f"dossier:{dossier_id}"
        for c in m2_causes
    )

    extraction = db.get_turn_extraction(turn2)
    absorptions = (extraction or {}).get("extractor_output", {}).get("bandit_absorptions") or []
    assert len(absorptions) == 1
    actual = int(absorptions[0]["actual_count"])
    assert actual == pool_after
    assert actual < pool0
    assert _pop(db, "流民", "shaanxi") == 0
    assert _strength(db, pid) == strength0 + actual // BANDIT_ABSORPTION_PERSONS_PER_STRENGTH


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_no_explicit_outcome_no_judge_fill(game, monkeypatch):
    """无明确结局：issues 空抄录 → 案卷不闭合、无 recovery；调用次数仍为既有一次。

    无灾路径：引擎不得代判官补写结局（有灾赈灾必写结局是判官软契约）。
    """
    db, state, content = game
    amount = 40
    _reset_shaanxi_pool(db)
    dossier_id = _in_transit_recovery_grant(db, state, amount=amount, tag="no-out")
    displaced_before = _pop(db, "流民", "shaanxi")

    sim_calls: list = []
    extract_calls: list = []
    modules_seen: list = []
    _canned_judge(
        monkeypatch, outcome=None, dossier_id=dossier_id,
        sim_calls=sim_calls, extract_calls=extract_calls, modules_seen=modules_seen,
    )

    closed_turn = int(state.turn)
    make_light_session(db, state, content).advance_without_decree()

    assert len(sim_calls) == 1
    assert len(extract_calls) == 1
    assert set(modules_seen) == set(EXTRACTION_MODULES)
    _assert_two_axis_projection(sim_calls[0]["payload"], expect_disaster=False)

    row = db.get_decree_dossier(dossier_id)
    assert row["status"] == "executing"
    assert str(row["execution_outcome"] or "") == ""

    extraction = db.get_turn_extraction(closed_turn)
    transfers = (extraction or {}).get("extractor_output", {}).get("population_transfers") or []
    assert not _reflux(transfers, dossier_id=dossier_id)
    assert _pop(db, "流民", "shaanxi") == displaced_before


def test_legacy_population_unit_skips_absorption_and_recovery(game):
    db, state, content = game
    db.conn.execute("DELETE FROM save_meta WHERE key='population_unit'")
    db.conn.commit()
    assert db.population_unit != POPULATION_UNIT_PERSONS
    assert build_simulator_payload(state, db, "", "")["displaced_pool_balances"]["rows"] == []

    applied = apply_score_extraction(db, state, {
        "bandit_absorptions": [{
            "region_id": "shaanxi", "power_id": "bandits",
            "requested_count": 10, "origin_ref": "盘面自发",
        }],
    }, content, None)
    assert applied["bandit_absorptions"] == [] and applied["bandit_absorptions_rejections"]

    assert db.get_decree_dossier(_recovery_grant(db, state, amount=10))["execution_outcome"] == "fulfilled"
    assert not _reflux(_settle_transfers(state, db, content, "legacy"))


def test_person_only_adapter_skips_recovery_kernel(game):
    """#672：任命/传召 person-only adapter 不得顺带跑 #652 recovery。"""
    from ming_sim.issues import apply_person_changes_only, apply_score_extraction

    db, state, content = game
    _reset_shaanxi_pool(db)
    dossier_id = _recovery_grant(db, state, amount=30)
    displaced_before = _pop(db, "流民", "shaanxi")

    # Person-only path (same shape office/summon uses) must leave recovery untouched.
    apply_person_changes_only(
        db, state,
        [{
            "name": "袁崇焕", "动作": "行止", "transit_to": "beizhili",
            "origin_ref": "盘面自发",
        }],
        content=content, registry=None,
    )
    assert _pop(db, "流民", "shaanxi") == displaced_before

    # Contrast: full settle applier still runs recovery on the same paid grant.
    applied = apply_score_extraction(db, state, {}, content=content)
    reflux = _reflux(applied.get("population_transfers") or [], dossier_id=dossier_id)
    if not reflux:
        # Recovery may land under applied_transfers depending on report shape.
        reflux = [
            t for t in (applied.get("applied_transfers") or [])
            if isinstance(t, dict) and t.get("reason") == "回流"
            and t.get("origin_ref") == f"dossier:{dossier_id}"
        ]
    assert reflux, "full apply_score_extraction must still run recovery"
    assert _pop(db, "流民", "shaanxi") < displaced_before
