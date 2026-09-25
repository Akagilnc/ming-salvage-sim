"""#1844：共同资源先交代先扣、跨类按交代先后、有账封顶、拒收进供料。"""

from __future__ import annotations

import json
import sqlite3

import pytest

from ming_sim.declaration_dispatch import settle_staged_declarations_in_decree_order
from ming_sim.month_translate import dispatch_month_segment


def _settled_declaration(db, decree_ref: str) -> dict:
    row = db.conn.execute(
        "SELECT declaration_json FROM staged_declarations "
        "WHERE decree_ref=? AND status='settled' ORDER BY id LIMIT 1",
        (decree_ref,),
    ).fetchone()
    assert row is not None
    return json.loads(row["declaration_json"])


def _stage_treasury_spend(db, state, *, decree_ref: str, delta: int, reason: str, affair_id: int):
    db.staged_declarations.stage(
        decree_ref=decree_ref,
        declaration={"effects": {"economy_moves": [{
            "origin_ref": f"affair:{affair_id}", "account": "国库", "delta": delta,
            "category": reason, "reason": reason,
        }]}},
        turn=int(state.turn),
        visible_refs={"affairs": [affair_id], "issues": [], "secret_orders": []},
    )


def test_player_decrees_soft_cap_shared_treasury_in_order(game):
    """存量 120，先扣 100、后支 30 → 实扣 100 与实拨 20；名义与实况分别可查。"""
    db, state, _ = game
    affair = db.affairs.open(
        name="争库可见", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    state.metrics["国库"] = 120
    db.save_state(state)
    _stage_treasury_spend(db, state, decree_ref="edict-first", delta=-100,
                          reason="先扣百万", affair_id=affair.id)
    _stage_treasury_spend(db, state, decree_ref="edict-second", delta=-30,
                          reason="后支三十万", affair_id=affair.id)

    results = settle_staged_declarations_in_decree_order(
        db, state, ["edict-first", "edict-second"],
    )

    assert state.metrics["国库"] == 0
    first_moves = results["edict-first"].effects.applied[0]["economy_moves"]
    second_moves = results["edict-second"].effects.applied[0]["economy_moves"]
    assert [m["delta"] for m in first_moves] == [-100]
    assert [m["delta"] for m in second_moves] == [-20]
    assert _settled_declaration(db, "edict-first")["effects"]["economy_moves"][0]["delta"] == -100
    assert _settled_declaration(db, "edict-second")["effects"]["economy_moves"][0]["delta"] == -30
    ledger = db.conn.execute(
        "SELECT category, delta FROM economy_ledger "
        "WHERE category IN ('先扣百万','后支三十万') ORDER BY id"
    ).fetchall()
    assert [(row["category"], row["delta"]) for row in ledger] == [
        ("先扣百万", -100), ("后支三十万", -20),
    ]


def test_player_decree_missing_entity_rejection_persists_for_feed(game, tmp_path):
    """查无实体等确实无法承接的项：逐项拒收留痕，重开后仍可读。"""
    db, state, _ = game
    affair = db.affairs.open(
        name="拒收可见", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    before = int(state.metrics["国库"])
    db.staged_declarations.stage(
        decree_ref="edict-missing",
        declaration={"effects": {"economy_moves": [{
            "origin_ref": f"affair:{affair.id}", "account": "国库", "delta": -1,
            "category": "补饷坏目标", "reason": "查无此军",
            "purpose": "补饷", "target_kind": "army", "target_id": "no-such-army-1844",
        }]}},
        turn=int(state.turn),
        visible_refs={"affairs": [affair.id], "issues": [], "secret_orders": []},
    )
    result = settle_staged_declarations_in_decree_order(db, state, ["edict-missing"])[
        "edict-missing"
    ]
    assert state.metrics["国库"] == before
    rejections = result.effects.applied[0]["economy_moves_rejections"]
    assert rejections
    assert rejections[0]["rejected"] is True
    assert rejections[0]["category"] == "missing_ref"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM rejection_reports WHERE category='missing_ref'"
    ).fetchone()[0] >= 1

    db_path = tmp_path / "reject-reopen.db"
    raw = db.conn.execute("SELECT sql FROM sqlite_master WHERE type='table'").fetchall()
    del raw  # schema already in live db; reopen via backup
    db.conn.execute("VACUUM INTO ?", (str(db_path),))
    reopened = sqlite3.connect(str(db_path))
    reopened.row_factory = sqlite3.Row
    assert reopened.execute(
        "SELECT COUNT(*) FROM rejection_reports WHERE category='missing_ref'"
    ).fetchone()[0] >= 1
    assert reopened.execute(
        "SELECT status FROM staged_declarations WHERE decree_ref='edict-missing'"
    ).fetchone()[0] == "settled"
    reopened.close()


def test_player_decrees_sequential_army_station_reads_updated_roster(game):
    """同一军队先后调遣：后旨读到前旨已变更的名册驻地。"""
    db, state, _ = game
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
    db.staged_declarations.stage(
        decree_ref="army-move-1",
        declaration={"effects": {"army_delta": {army: {
            "origin_ref": f"affair:{affair.id}", "station_region": first_station,
            "reason": "第一道调遣",
        }}}},
        turn=int(state.turn),
        visible_refs={"affairs": [affair.id], "issues": [], "secret_orders": []},
    )
    db.staged_declarations.stage(
        decree_ref="army-move-2",
        declaration={"effects": {"army_delta": {army: {
            "origin_ref": f"affair:{affair.id}", "station_region": second_station,
            "reason": "第二道调遣",
        }}}},
        turn=int(state.turn),
        visible_refs={"affairs": [affair.id], "issues": [], "secret_orders": []},
    )
    settle_staged_declarations_in_decree_order(db, state, ["army-move-1", "army-move-2"])
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
