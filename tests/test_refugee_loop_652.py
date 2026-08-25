"""#652：流民环闭合——投贼吃池顶 + 赈济/招抚回流 + 唯一判官成色链。

主测缝：build_simulator_payload / apply_score_extraction / settle_with_delta
／advance_without_decree（可控 LLM seam 真实月结）。
owner A：开仓非回流 producer；只覆盖赈济与招抚屯田；#522 不动。
"""

from __future__ import annotations

import json

import pytest

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


def _shaanxi_disaster_rows(payload) -> list:
    surface = payload.get("execution_two_axis") or {}
    for prov in surface.get("provinces") or []:
        if prov.get("region_id") == "shaanxi":
            return list(prov.get("disaster_rows") or [])
    return []


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
    有灾赈灾必折损另见 test_disaster_province_relief_must_degrade。
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
@pytest.mark.parametrize("with_disaster", [True, False])
def test_disaster_province_relief_must_degrade(game, monkeypatch, with_disaster):
    """真实月结：唯一 simulator_fn 读 two_axis 灾行一次判成色；extractor 只抄录。

    有灾 → degraded 且回流 < 无灾 fulfilled 全额；无灾 → fulfilled 全额。
    """
    db, state, content = game
    amount = 40
    _reset_shaanxi_pool(db)
    if with_disaster:
        _insert_shaanxi_disaster(db, state)
    dossier_id = _in_transit_recovery_grant(
        db, state, amount=amount, tag=f"dis-{int(with_disaster)}",
    )
    paid_before = [
        m for m in db.list_economy_moves_for_dossier(dossier_id)
        if int(m.get("delta") or 0) < 0
    ]
    assert paid_before

    sim_calls: list = []
    extract_calls: list = []
    modules_seen: list = []
    box: dict = {}

    def simulator_fn(payload):
        disasters = _shaanxi_disaster_rows(payload)
        _assert_two_axis_projection(payload, expect_disaster=with_disaster)
        assert bool(disasters) is with_disaster
        if disasters:
            outcome = "degraded"
            note = _NOTE_BY["degraded"]
            narrative = (
                f"案卷 dossier:{dossier_id} 本省灾情占尽差务，"
                f"赈务不得全额办成：{note}。"
            )
        else:
            outcome = "fulfilled"
            note = _NOTE_BY["fulfilled"]
            narrative = (
                f"案卷 dossier:{dossier_id} 陕西赈灾无灾挤占，"
                f"{note}。"
            )
        box["outcome"] = outcome
        return {
            "narrative": narrative,
            "extract": {
                "dossier_executions": [{
                    "dossier_id": dossier_id,
                    "outcome": outcome,
                    "note": note,
                }],
            },
        }

    canned_full_settlement(
        monkeypatch,
        simulator_fn=simulator_fn,
        simulator_calls=sim_calls,
        extract_calls=extract_calls,
        modules_seen=modules_seen,
        skip_fixed_flows=True,
        skip_relation_brew=True,
    )

    displaced_before = _pop(db, "流民", "shaanxi")
    farmer_before = _pop(db, "农民", "shaanxi")
    closed_turn = int(state.turn)
    result = make_light_session(db, state, content).advance_without_decree()
    assert result is not None and result.awaiting is False
    assert len(sim_calls) == 1 and len(extract_calls) == 1
    assert set(modules_seen) == set(EXTRACTION_MODULES)

    row = db.get_decree_dossier(dossier_id)
    assert row["status"] == "closed"
    outcome = row["execution_outcome"]
    assert outcome == box["outcome"]

    extraction = db.get_turn_extraction(closed_turn)
    transfers = (extraction or {}).get("extractor_output", {}).get("population_transfers") or []
    actual = sum(int(t.get("amount") or 0) for t in _reflux(transfers, dossier_id=dossier_id))
    full_baseline = _expected_recovery(amount, "fulfilled", displaced_before)
    expected = _expected_recovery(amount, outcome, displaced_before)
    assert actual == expected
    if with_disaster:
        assert outcome != "fulfilled"
        assert actual < full_baseline
    else:
        assert outcome == "fulfilled"
        assert actual == full_baseline
    assert _pop(db, "流民", "shaanxi") == displaced_before - actual
    assert _pop(db, "农民", "shaanxi") == farmer_before + actual
    # 代价照付：实付负向流水不因成色折损而退回
    paid_after = [
        m for m in db.list_economy_moves_for_dossier(dossier_id)
        if int(m.get("delta") or 0) < 0
    ]
    assert paid_after


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_post_relief_bandit_growth_slows_next_month(game, monkeypatch):
    """两月真实月结：同一 simulator_fn 月2 读下降后池决定 requested_count。

    extractor 只抄录；请求/落账/实力增均低于未赈基线。
    """
    db, state, content = game
    pid = "bandit_li_zicheng"
    _reset_shaanxi_pool(db)
    pool0 = _pop(db, "流民", "shaanxi")
    strength0 = _strength(db, pid)
    # 未赈对照：同比例请求在满池上的吸收量（缓存，不另开平行 applier）。
    baseline_request = pool0 // 2
    baseline_actual = min(baseline_request, pool0)
    baseline_delta = baseline_actual // BANDIT_ABSORPTION_PERSONS_PER_STRENGTH
    assert baseline_actual > 0 and baseline_delta > 0

    _recovery_grant(db, state, amount=30)

    sim_calls: list = []
    extract_calls: list = []
    modules_seen: list = []
    month = {"n": 0}
    m2: dict = {}

    def simulator_fn(payload):
        month["n"] += 1
        pool = _shaanxi_pool_from_payload(payload)
        if month["n"] == 1:
            return {
                "narrative": "本月赈银到位，流民渐有归农气象，贼势未及大举。",
                "extract": {},
            }
        # 月2：必须读到下降后的池，一次决定 requested_count（不得写死 pool0）
        m2["pool"] = pool
        req = max(int(pool) // 2, 0)
        m2["request"] = req
        extract: dict = {}
        if req > 0:
            extract = {
                "bandit_absorptions": [{
                    "region_id": "shaanxi",
                    "power_id": pid,
                    "requested_count": req,
                    "origin_ref": "盘面自发",
                }],
            }
        return {
            "narrative": (
                "陕西赈后流民池已降，饥民投附流寇之势回落，"
                "贼股难再按旧速吸纳。"
            ),
            "extract": extract,
        }

    canned_full_settlement(
        monkeypatch,
        simulator_fn=simulator_fn,
        simulator_calls=sim_calls,
        extract_calls=extract_calls,
        modules_seen=modules_seen,
        skip_fixed_flows=True,
        skip_relation_brew=True,
    )

    sess = make_light_session(db, state, content)
    turn1 = int(state.turn)
    r1 = sess.advance_without_decree()
    assert r1 is not None and r1.awaiting is False
    pool_after = _pop(db, "流民", "shaanxi")
    assert pool_after < pool0
    assert _strength(db, pid) == strength0  # 月1 无吸收

    turn2 = int(state.turn)
    assert turn2 == turn1 + 1
    r2 = sess.advance_without_decree()
    assert r2 is not None and r2.awaiting is False
    assert len(sim_calls) == 2 and len(extract_calls) == 2
    assert month["n"] == 2
    assert set(modules_seen) == set(EXTRACTION_MODULES)
    assert m2["pool"] == pool_after
    assert _shaanxi_pool_from_payload(sim_calls[1]["payload"]) == pool_after
    assert m2["request"] < baseline_request

    extraction = db.get_turn_extraction(turn2)
    absorptions = (extraction or {}).get("extractor_output", {}).get("bandit_absorptions") or []
    assert len(absorptions) == 1
    actual = int(absorptions[0]["actual_count"])
    requested = int(absorptions[0]["requested_count"])
    assert requested == m2["request"]
    assert actual == min(requested, pool_after)
    assert actual < baseline_actual
    strength_delta = actual // BANDIT_ABSORPTION_PERSONS_PER_STRENGTH
    assert strength_delta < baseline_delta
    assert _pop(db, "流民", "shaanxi") == pool_after - actual
    assert _strength(db, pid) == strength0 + strength_delta


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

    applied = apply_score_extraction(db, state, {
        "bandit_absorptions": [{
            "region_id": "shaanxi", "power_id": "bandits",
            "requested_count": 10, "origin_ref": "盘面自发",
        }],
    }, content, None)
    assert applied["bandit_absorptions"] == [] and applied["bandit_absorptions_rejections"]

    assert db.get_decree_dossier(_recovery_grant(db, state, amount=10))["execution_outcome"] == "fulfilled"
    assert not _reflux(_settle_transfers(state, db, content, "legacy"))
