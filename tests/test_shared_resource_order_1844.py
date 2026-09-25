"""#1844：共同资源先交代先扣、跨类按交代先后、有账封顶、拒收进供料。"""

from __future__ import annotations

import json
import sqlite3

import pytest

from ming_sim.declaration_dispatch import pending_action_decree_ref
from ming_sim.month_translate import dispatch_month_segment
from tests.test_month_chain_1843 import _enter_player_month


def _settled_declaration(db, decree_ref: str) -> dict:
    row = db.conn.execute(
        "SELECT declaration_json FROM staged_declarations "
        "WHERE decree_ref=? AND status='settled' ORDER BY id LIMIT 1",
        (decree_ref,),
    ).fetchone()
    assert row is not None
    return json.loads(row["declaration_json"])


def _stage_player_edict(db, state, minister, affair_id, effects, text):
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "month-chain", "actor": minister, "mode": "ordinary",
            "text": text,
        },
    )
    ref = pending_action_decree_ref(pending_id, 1)
    db.staged_declarations.stage(
        decree_ref=ref,
        declaration={"effects": effects},
        turn=int(state.turn),
        verdict={"decision": "promulgated"},
        visible_refs={"affairs": [affair_id], "issues": [], "secret_orders": []},
    )
    return ref


def test_player_decrees_soft_cap_shared_treasury_in_order(game, monkeypatch):
    """两旨争库走玩家过月：先旨按当时国库封顶扣尽，后旨实拨为 0；暂存保留名义。"""
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="争库可见", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    state.metrics["国库"] = 500_000
    db.save_state(state)
    first_ref = _stage_player_edict(
        db, state, minister, affair.id,
        {"economy_moves": [{
            "origin_ref": f"affair:{affair.id}", "account": "国库", "delta": -10**12,
            "category": "先扣尽库", "reason": "先扣尽库",
        }]},
        "先扣尽库",
    )
    second_ref = _stage_player_edict(
        db, state, minister, affair.id,
        {"economy_moves": [{
            "origin_ref": f"affair:{affair.id}", "account": "国库", "delta": -30,
            "category": "后支三十万", "reason": "后支三十万",
        }]},
        "后支三十万",
    )

    _enter_player_month(db, state, content, monkeypatch)

    assert _settled_declaration(db, first_ref)["effects"]["economy_moves"][0]["delta"] == -10**12
    assert _settled_declaration(db, second_ref)["effects"]["economy_moves"][0]["delta"] == -30
    first = db.conn.execute(
        "SELECT delta, balance_after FROM economy_ledger WHERE category='先扣尽库'"
    ).fetchall()
    assert len(first) == 1
    assert int(first[0]["delta"]) < 0
    assert int(first[0]["delta"]) != -10**12
    assert int(first[0]["balance_after"]) == 0
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='后支三十万' AND delta != 0"
    ).fetchone()[0] == 0


def test_player_decree_missing_entity_rejection_persists_for_feed(game, monkeypatch, tmp_path):
    """查无实体的项从玩家过月逐项拒收留痕，重开后仍可读。"""
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="拒收可见", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    ref = _stage_player_edict(
        db, state, minister, affair.id,
        {"economy_moves": [{
            "origin_ref": f"affair:{affair.id}", "account": "国库", "delta": -1,
            "category": "补饷坏目标", "reason": "查无此军",
            "purpose": "补饷", "target_kind": "army", "target_id": "no-such-army-1844",
        }]},
        "补饷坏目标",
    )
    _enter_player_month(db, state, content, monkeypatch)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='补饷坏目标' AND delta != 0"
    ).fetchone()[0] == 0
    assert db.conn.execute(
        "SELECT COUNT(*) FROM rejection_reports WHERE category='missing_ref' AND item_json LIKE '%no-such-army-1844%'"
    ).fetchone()[0] >= 1

    db_path = tmp_path / "reject-reopen.db"
    db.conn.execute("VACUUM INTO ?", (str(db_path),))
    reopened = sqlite3.connect(str(db_path))
    reopened.row_factory = sqlite3.Row
    assert reopened.execute(
        "SELECT COUNT(*) FROM rejection_reports WHERE category='missing_ref' AND item_json LIKE '%no-such-army-1844%'"
    ).fetchone()[0] >= 1
    assert reopened.execute(
        "SELECT status FROM staged_declarations WHERE decree_ref=?",
        (ref,),
    ).fetchone()[0] == "settled"
    reopened.close()


def test_player_decrees_sequential_army_station_reads_updated_roster(game, monkeypatch):
    """同一军队先后调遣走玩家过月：后旨读到前旨已变更的名册驻地。"""
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="调遣可见", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    army = "jingying"
    start = db.conn.execute(
        "SELECT station_region FROM armies WHERE id=?", (army,),
    ).fetchone()[0]
    assert start
    regions = [
        row[0] for row in db.conn.execute(
            "SELECT id FROM regions WHERE id != ? ORDER BY id LIMIT 2", (start,),
        )
    ]
    assert len(regions) == 2
    first_station, second_station = regions
    _stage_player_edict(
        db, state, minister, affair.id,
        {"army_delta": {army: {
            "origin_ref": f"affair:{affair.id}", "station_region": first_station,
            "reason": "第一道调遣",
        }}},
        "第一道调遣",
    )
    _stage_player_edict(
        db, state, minister, affair.id,
        {"army_delta": {army: {
            "origin_ref": f"affair:{affair.id}", "station_region": second_station,
            "reason": "第二道调遣",
        }}},
        "第二道调遣",
    )
    _enter_player_month(db, state, content, monkeypatch)
    assert db.conn.execute(
        "SELECT station_region FROM armies WHERE id=?", (army,),
    ).fetchone()[0] == second_station
    logs = db.conn.execute(
        "SELECT old_value, new_value FROM army_logs "
        "WHERE army_id=? AND field='station_region' ORDER BY id",
        (army,),
    ).fetchall()
    assert len(logs) >= 2
    assert logs[-2]["new_value"] == first_station
    assert logs[-1]["old_value"] == first_station
    assert logs[-1]["new_value"] == second_station


@pytest.mark.parametrize(
    ("order", "expected_arrears"),
    [
        ("arrears_then_pay", 0),
        ("pay_then_arrears", 10),
    ],
)
def test_world_segment_cross_category_order_by_declaration(game, order, expected_arrears):
    """先加欠饷再拨款清欠按交代先后；对调先后时按当时存量，不因类别段序颠倒。"""
    db, state, _ = game
    db.conn.execute("UPDATE armies SET arrears=0, province_pay_arrears=0, central_pay_arrears=0 WHERE id='jingying'")
    db.conn.commit()
    state.metrics["国库"] = 100
    arrears_effect = {"army_delta": {"jingying": {
        "origin_ref": "盘面自发", "arrears": 10, "reason": "京营加欠",
    }}}
    pay_effect = {"economy_moves": [{
        "origin_ref": "盘面自发", "account": "国库", "delta": -10,
        "category": "补饷", "reason": "清欠拨款",
        "purpose": "补饷", "target_kind": "army", "target_id": "jingying",
    }]}
    effects = (
        [arrears_effect, pay_effect] if order == "arrears_then_pay"
        else [pay_effect, arrears_effect]
    )
    dispatch_month_segment(
        db, state, segment="跨类欠饷与拨款",
        translate_fn=lambda _request, _config: {"effects": effects},
    )
    arrears = float(db.conn.execute(
        "SELECT arrears FROM armies WHERE id='jingying'"
    ).fetchone()[0])
    assert arrears == pytest.approx(expected_arrears)
    if order == "arrears_then_pay":
        assert state.metrics["国库"] == 90
        paid = db.conn.execute(
            "SELECT SUM(delta) FROM economy_ledger WHERE reason='清欠拨款'"
        ).fetchone()[0]
        assert paid == -10
    else:
        assert state.metrics["国库"] == 100
        assert db.conn.execute(
            "SELECT COUNT(*) FROM economy_ledger WHERE reason='清欠拨款' AND delta != 0"
        ).fetchone()[0] == 0


def test_world_segment_cross_category_order_survives_reopen(game, tmp_path):
    """过月落账后重开：欠饷已清与拒收一致性仍在。"""
    db, state, _ = game
    db.conn.execute("UPDATE armies SET arrears=0, province_pay_arrears=0, central_pay_arrears=0 WHERE id='jingying'")
    db.conn.commit()
    state.metrics["国库"] = 50
    dispatch_month_segment(
        db, state, segment="先欠后清后重开",
        translate_fn=lambda _r, _c: {"effects": [
            {"army_delta": {"jingying": {
                "origin_ref": "盘面自发", "arrears": 10, "reason": "加欠",
            }}},
            {"economy_moves": [{
                "origin_ref": "盘面自发", "account": "国库", "delta": -10,
                "category": "补饷", "reason": "清欠",
                "purpose": "补饷", "target_kind": "army", "target_id": "jingying",
            }]},
            {"economy_moves": [{
                "origin_ref": "盘面自发", "account": "国库", "delta": -1,
                "category": "坏项", "reason": "查无",
                "purpose": "补饷", "target_kind": "army", "target_id": "ghost-army-1844",
            }]},
        ]},
    )
    assert float(db.conn.execute(
        "SELECT arrears FROM armies WHERE id='jingying'"
    ).fetchone()[0]) == pytest.approx(0)
    assert state.metrics["国库"] == 40
    assert db.conn.execute(
        "SELECT COUNT(*) FROM rejection_reports WHERE category='missing_ref'"
    ).fetchone()[0] >= 1

    db_path = tmp_path / "cross-reopen.db"
    db.conn.execute("VACUUM INTO ?", (str(db_path),))
    reopened = sqlite3.connect(str(db_path))
    reopened.row_factory = sqlite3.Row
    assert float(reopened.execute(
        "SELECT arrears FROM armies WHERE id='jingying'"
    ).fetchone()[0]) == pytest.approx(0)
    assert reopened.execute(
        "SELECT COUNT(*) FROM rejection_reports WHERE category='missing_ref'"
    ).fetchone()[0] >= 1
    assert reopened.execute(
        "SELECT SUM(delta) FROM economy_ledger WHERE reason='清欠'"
    ).fetchone()[0] == -10
    reopened.close()
