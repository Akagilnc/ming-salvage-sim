"""#1900 护送关系可由现役声明产生并影响在途拨帑（ADR 0054 逐路查入链）。

Seams:
- 转译声明 ``escort_links`` → ``GameDB.add_dossier_links``（关联真源，单向新指旧）
- 转译声明 ``escort_results`` → ``GameDB.record_dossier_escort_result``（逐路实况）
- ``_grant_escort_presence`` / ``list_monthly_grant_reconciliation_targets``
  （对账只读逐路实况，不凭关联、不凭密令整体成败）
- ``grant_arrival_bounds`` / ``clamp_grant_arrival_amount``（引擎既有押解折损范围）
- 重开（restore）逐路无损；不新增目的地现金账户、不二次扣库

验收对照票面「怎么验」：
- 关联真实落库（现役声明能立链）
- 一令护多路而结果不同 → 各读各路
- 成功护送后结案仍按该路实际有护对账
- 关联存在但该路未实际获护 → 不作有护
"""

from __future__ import annotations

import pytest

from ming_sim.applier import Provenance, RejectionCollector
from ming_sim.db import GameDB, grant_arrival_bounds
from ming_sim.declaration_dispatch import dispatch_declaration
from tests.dossier_test_helpers import create_test_secret_order

ORDERED = 30  # 与 #567 同口径：三十万两量级整数面值


def _actor(db) -> str:
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"])


def _in_transit_grant(db, state, *, amount=ORDERED, text="拨银押解", target_id="shaanxi"):
    state.metrics["内库"] = max(int(state.metrics.get("内库") or 0), amount * 3 + 50)
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text=text,
        target_kind="region",
        target_id=target_id,
        payload={"account": "内库", "amount": amount, "execution_surface": "in_transit"},
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    assert db.get_decree_dossier(dossier_id)["status"] == "executing"
    return dossier_id


def _escort_order(db, state, *, title="护行饷银"):
    """护行密令（新案卷）——关联要求新指旧，故须晚于被护拨帑案卷成案。"""
    order_id = create_test_secret_order(
        db, state, _actor(db), title, "沿途护送，照关防",
        ["护行"], deadline_months=4,
    )
    dossier = db.get_dossier_for_secret_order(order_id)
    return order_id, int(dossier["id"])


def _declare(db, state, declaration):
    return dispatch_declaration(
        db, state, declaration, source=Provenance.system_simulation,
    )


def _record_monthly(db, turn, generated=None):
    collector = RejectionCollector()
    rows = db.record_monthly_grant_reconciliations(
        turn, generated or [], rejection_collector=collector,
        source=Provenance.player_decree,
    )
    collector.flush_to_db(db)
    db.conn.commit()
    return rows


def test_declaration_lands_escort_link_and_forbids_reverse_direction(game):
    """现役声明能立关联；旧案卷指新案卷仍被 0054 挡下并留痕。"""
    db, state, _content = game
    grant = _in_transit_grant(db, state)
    order_id, escort_dossier = _escort_order(db, state)

    result = _declare(db, state, {"escort_links": [
        {"escort_source_dossier_id": escort_dossier, "target_dossier_id": grant,
         "relation_type": "护卫", "note": "沿路护送该笔拨帑"},
    ]})
    assert result.escort_links.rejected == []
    assert db.list_dossier_links(escort_dossier) == [{
        "id": db.list_dossier_links(escort_dossier)[0]["id"],
        "source_dossier_id": escort_dossier,
        "target_dossier_id": grant,
        "relation_type": "护卫",
        "note": "沿路护送该笔拨帑",
        "created_at": db.list_dossier_links(escort_dossier)[0]["created_at"],
    }]
    assert db.list_dossier_links(grant, direction="incoming")[0]["source_dossier_id"] == escort_dossier

    # 反向（新指旧纪律）与坏类型逐项拒收，不牵连已落的合法项
    bad = _declare(db, state, {"escort_links": [
        {"escort_source_dossier_id": grant, "target_dossier_id": escort_dossier,
         "relation_type": "护卫", "note": "倒指"},
        {"escort_source_dossier_id": escort_dossier, "target_dossier_id": grant,
         "relation_type": "接应", "note": "非护送口径"},
        {"escort_source_dossier_id": escort_dossier, "target_dossier_id": 999999,
         "relation_type": "护卫", "note": "幻影案卷"},
    ]})
    assert [r.reason for r in bad.escort_links.rejected] == [
        "案卷关联只允许新案卷指向旧案卷",
        "护送关联类型须为 护卫／稽核：接应",
        "护送关联须含已存在的两端案卷 id",
    ]
    assert len(db.list_dossier_links(escort_dossier)) == 1


def test_link_alone_is_not_escort(game):
    """关联存在但该路未实际获护 → 不作有护（不得只凭关联当有护）。"""
    db, state, _content = game
    grant = _in_transit_grant(db, state)
    _order_id, escort_dossier = _escort_order(db, state)
    _declare(db, state, {"escort_links": [
        {"escort_source_dossier_id": escort_dossier, "target_dossier_id": grant,
         "relation_type": "护卫", "note": "沿路护送"},
    ]})

    targets = db.list_monthly_grant_reconciliation_targets(state.turn)
    assert targets and targets[0]["escorted"] is False

    _record_monthly(db, state.turn)
    row = db.list_dossier_reconciliations(grant)[-1]
    bare_lo, bare_hi = grant_arrival_bounds(ORDERED, escorted=False)
    assert row["escorted"] is False
    assert bare_lo <= row["arrived_amount"] <= bare_hi
    assert row["loss_amount"] == ORDERED - row["arrived_amount"]


def test_per_route_actual_escort_drives_arrival_and_survives_restore(game):
    """有实护 → 引擎按既有折损范围给有护口径；重开后逐路实况无损。"""
    db, state, content = game
    grant = _in_transit_grant(db, state)
    order_id, escort_dossier = _escort_order(db, state)
    _declare(db, state, {
        "escort_links": [
            {"escort_source_dossier_id": escort_dossier, "target_dossier_id": grant,
             "relation_type": "护卫", "note": "沿路护送"},
        ],
        "escort_results": [
            {"dossier_id": grant, "escort_source_dossier_id": escort_dossier,
             "escorted": True, "note": "该路此趟实有护送，随饷同到"},
        ],
    })

    landed = db.list_dossier_escort_outcomes(grant)
    assert len(landed) == 1
    assert landed[0]["escorted"] is True
    assert landed[0]["relation_type"] == "护卫"  # 类型取自链，不接受声明另报
    assert landed[0]["note"] == "该路此趟实有护送，随饷同到"

    _record_monthly(db, state.turn)
    row = db.list_dossier_reconciliations(grant)[-1]
    lo, hi = grant_arrival_bounds(ORDERED, escorted=True)
    assert row["escorted"] is True
    assert row["escort_source_dossier_id"] == escort_dossier
    assert lo <= row["arrived_amount"] <= hi
    bare_hi = grant_arrival_bounds(ORDERED, escorted=False)[1]
    assert row["arrived_amount"] > bare_hi

    path = db.path
    db.close()
    reopened = GameDB(path, content=content)
    assert reopened.list_dossier_escort_outcomes(grant) == landed
    assert reopened.list_dossier_reconciliations(grant) == [row]
    assert reopened.list_escort_outcomes_for_source(escort_dossier) == landed
    stored = reopened.conn.execute(
        "SELECT status FROM secret_orders WHERE id=?", (order_id,),
    ).fetchone()
    assert stored["status"] in {"active", "in_progress"}
    reopened.close()


def test_one_order_many_routes_reads_each_own_outcome(game):
    """一令护多路而结果不同 → 有成的按有护对账，失护的按无护对账。"""
    db, state, _content = game
    guarded = _in_transit_grant(db, state, text="有护路", target_id="shaanxi")
    lost = _in_transit_grant(db, state, text="失护路", target_id="liaodong")
    _order_id, escort_dossier = _escort_order(db, state)
    _declare(db, state, {
        "escort_links": [
            {"escort_source_dossier_id": escort_dossier, "target_dossier_id": guarded,
             "relation_type": "护卫", "note": "护其一"},
            {"escort_source_dossier_id": escort_dossier, "target_dossier_id": lost,
             "relation_type": "护卫", "note": "护其二"},
        ],
        "escort_results": [
            {"dossier_id": guarded, "escort_source_dossier_id": escort_dossier,
             "escorted": True, "note": "其一护送到"},
            {"dossier_id": lost, "escort_source_dossier_id": escort_dossier,
             "escorted": False, "note": "其二遇截折护"},
        ],
    })

    by_route = {r["dossier_id"]: r for r in db.list_escort_outcomes_for_source(escort_dossier)}
    assert by_route[guarded]["escorted"] is True
    assert by_route[lost]["escorted"] is False

    _record_monthly(db, state.turn)
    guarded_row = db.list_dossier_reconciliations(guarded)[-1]
    lost_row = db.list_dossier_reconciliations(lost)[-1]
    assert guarded_row["escorted"] is True
    assert lost_row["escorted"] is False
    assert guarded_row["arrived_amount"] > lost_row["arrived_amount"]
    assert lost_row["loss_amount"] > guarded_row["loss_amount"]


def test_escorted_route_still_reconciles_after_order_closes(game):
    """成功护送后结案仍按该路实际有护对账（结案不抹逐路实况）。"""
    db, state, _content = game
    grant = _in_transit_grant(db, state)
    order_id, escort_dossier = _escort_order(db, state)
    _declare(db, state, {
        "escort_links": [
            {"escort_source_dossier_id": escort_dossier, "target_dossier_id": grant,
             "relation_type": "护卫", "note": "沿路护送"},
        ],
        "escort_results": [
            {"dossier_id": grant, "escort_source_dossier_id": escort_dossier,
             "escorted": True, "note": "护送毕"},
        ],
    })
    db.close_secret_order(
        order_id, "done", "护行毕，饷银同到", int(state.turn),
    )

    targets = db.list_monthly_grant_reconciliation_targets(state.turn)
    assert targets[0]["escorted"] is True
    _record_monthly(db, state.turn)
    row = db.list_dossier_reconciliations(grant)[-1]
    lo, hi = grant_arrival_bounds(ORDERED, escorted=True)
    assert row["escorted"] is True
    assert lo <= row["arrived_amount"] <= hi


def test_escort_result_requires_link_and_writes_no_destination_account(game):
    """无关联不得记实况；全程无二次扣库、无目的地现金账户。"""
    db, state, _content = game
    grant = _in_transit_grant(db, state)
    _order_id, escort_dossier = _escort_order(db, state)
    before_inner = int(state.metrics["内库"])
    moves_before = db.list_economy_moves_for_dossier(grant)

    result = _declare(db, state, {"escort_results": [
        {"dossier_id": grant, "escort_source_dossier_id": escort_dossier,
         "escorted": True, "note": "凭空护送"},
    ]})
    assert result.escort_results.applied == []
    assert [r.reason for r in result.escort_results.rejected] == [
        "护送实况须先有护卫／稽核案卷关联",
    ]
    assert db.list_dossier_escort_outcomes(grant) == []
    assert int(state.metrics["内库"]) == before_inner
    assert db.list_economy_moves_for_dossier(grant) == moves_before

    # 逐路实况不是目的地账户：国库/内库之外不因护送多出任何余额行
    keys = {str(r["key"]) for r in db.conn.execute("SELECT key FROM metrics").fetchall()}
    assert not any("护送" in k or "escort" in k.lower() for k in keys)


@pytest.mark.parametrize("bad", ["yes", 1, None, []])
def test_escort_result_requires_real_boolean(game, bad):
    """非布尔 escorted 逐项 invalid_shape，不洗成有护也不洗成无护。"""
    db, state, _content = game
    grant = _in_transit_grant(db, state)
    _order_id, escort_dossier = _escort_order(db, state)
    _declare(db, state, {"escort_links": [
        {"escort_source_dossier_id": escort_dossier, "target_dossier_id": grant,
         "relation_type": "护卫", "note": "沿路护送"},
    ]})
    result = _declare(db, state, {"escort_results": [
        {"dossier_id": grant, "escort_source_dossier_id": escort_dossier,
         "escorted": bad, "note": "含糊"},
    ]})
    assert result.escort_results.applied == []
    assert [r.category for r in result.escort_results.rejected] == ["invalid_shape"]
    assert db.list_dossier_escort_outcomes(grant) == []


def test_escort_outcome_is_per_turn_not_cumulative(game):
    """同路跨回合各自记各自的：本回合失护不因上月护成而沿用。"""
    db, state, _content = game
    grant = _in_transit_grant(db, state)
    _order_id, escort_dossier = _escort_order(db, state)
    _declare(db, state, {
        "escort_links": [
            {"escort_source_dossier_id": escort_dossier, "target_dossier_id": grant,
             "relation_type": "护卫", "note": "沿路护送"},
        ],
        "escort_results": [
            {"dossier_id": grant, "escort_source_dossier_id": escort_dossier,
             "escorted": True, "note": "首趟护成"},
        ],
    })
    assert db._grant_escort_presence(grant, turn=state.turn)[:2] == (True, escort_dossier)

    state.turn += 1
    _declare(db, state, {"escort_results": [
        {"dossier_id": grant, "escort_source_dossier_id": escort_dossier,
         "escorted": False, "note": "次趟失护"},
    ]})
    assert db._grant_escort_presence(grant, turn=state.turn)[:2] == (False, escort_dossier)
    assert db._grant_escort_presence(grant, turn=state.turn - 1)[:2] == (True, escort_dossier)
    assert len(db.list_dossier_escort_outcomes(grant)) == 2
