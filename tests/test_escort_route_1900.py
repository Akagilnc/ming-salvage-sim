"""#1900 护送关系可由现役声明产生并影响在途拨帑（ADR 0054 逐路查入链）。

Seams:
- 转译声明 ``escort_links`` → ``GameDB.add_dossier_links``（关联真源，单向新指旧）
- 转译声明 ``escort_results`` → ``GameDB.record_dossier_escort_result``（逐路实况）
- ``_grant_escort_presence`` / ``list_monthly_grant_reconciliation_targets``
  （对账只读逐路实况，不凭关联、不凭密令整体成败）
- ``grant_arrival_bounds``（引擎既有押解折损范围；0054 的 clamp 口已随 #1900 退役）
- 重开（restore）逐路无损；不新增目的地现金账户、不二次扣库

验收对照票面「怎么验」：
- 关联真实落库（现役声明能立链）
- 一令护多路而结果不同 → 各读各路
- 成功护送后结案仍按该路实际有护对账
- 关联存在但该路未实际获护 → 不作有护
"""

from __future__ import annotations

import pytest

from ming_sim.applier import Provenance
from ming_sim.db import GameDB, grant_arrival_bounds
from ming_sim.declaration_dispatch import dispatch_declaration
from tests.dossier_test_helpers import create_test_secret_order

ORDERED = 30  # 与 #567 同口径：三十万两量级整数面值


def _actor(db) -> str:
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"])


def _in_transit_grant(db, state, *, amount=ORDERED, text="拨银押解", target_id="shaanxi",
                      escort=None):
    state.metrics["内库"] = max(int(state.metrics.get("内库") or 0), amount * 3 + 50)
    payload = {"account": "内库", "amount": amount, "execution_surface": "in_transit"}
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


def _catalog(db):
    """转译真拿到的权威目标目录：escort_dossier 行的首个 id 即护行密令案卷 id，
    dossier 行的首个 id 即在途拨帑案卷 id。测试据此取 id，不手填。"""
    from ming_sim.audience_translate import build_translation_target_grounding

    escort_dossiers, grants = [], []
    for line in build_translation_target_grounding(db).splitlines():
        parts = line.split("\t")
        if parts[0] == "escort_dossier":
            escort_dossiers.append(int(parts[1]))
        elif parts[0] == "dossier":
            grants.append(int(parts[1]))
    return escort_dossiers, grants


def _record_monthly(db, turn):
    """月度对账真入口：沿途损耗归引擎，本口不接提案。"""
    rows = db.record_monthly_grant_reconciliations(turn)
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

    # 坏类型／幻影案卷逐项拒收，不牵连已落的合法项
    bad = _declare(db, state, {"escort_links": [
        {"escort_source_dossier_id": escort_dossier, "target_dossier_id": grant,
         "relation_type": "接应", "note": "非护送口径"},
        {"escort_source_dossier_id": escort_dossier, "target_dossier_id": 999999,
         "relation_type": "护卫", "note": "幻影案卷"},
        {"escort_source_dossier_id": grant, "target_dossier_id": escort_dossier,
         "relation_type": "护卫", "note": "拿拨帑案卷当护行人"},
    ]})
    assert [r.reason for r in bad.escort_links.rejected] == [
        "护送关联类型须为 护卫／稽核：接应",
        "护送关联须含已存在的护行密令案卷与被护拨帑案卷 id",
        "护送关联须含已存在的护行密令案卷与被护拨帑案卷 id",
    ]
    assert len(db.list_dossier_links(escort_dossier)) == 1
    assert db.list_dossier_links(grant) == []

    # 0054 单向新指旧仍由写口本身把守（旧案卷指新案卷整批拒收并留痕）
    with pytest.raises(ValueError, match="案卷关联只允许新案卷指向旧案卷"):
        db.add_dossier_links(grant, [{
            "target_dossier_id": escort_dossier, "relation_type": "护卫", "note": "倒指",
        }])
    assert [link["source_dossier_id"] for link in
            db.list_dossier_links(grant, direction="incoming")] == [escort_dossier]
    assert [r["reason"] for r in db.list_dossier_link_rejections(grant)] == [
        "案卷关联只允许新案卷指向旧案卷",
    ]


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


def test_ids_come_from_real_catalog_and_land_through_dispatch(game):
    """真实入口：id 取自权威目标目录（不是手填），经分派落库并影响在途实抵。"""
    db, state, _content = game
    grant = _in_transit_grant(db, state)
    _order_id, _dossier = _escort_order(db, state)

    escort_dossiers, grants = _catalog(db)
    assert grant in grants, "在途拨帑案卷须在目录里，否则转译无从指向"
    assert _dossier in escort_dossiers, "护行密令案卷须在目录里（区别于 secret_order id）"
    # 护行主体行的第二个数是 secret_orders.id，与案卷 id 不是同一个值
    from ming_sim.audience_translate import build_translation_target_grounding
    row = next(l for l in build_translation_target_grounding(db).splitlines()
               if l.startswith("escort_dossier") and l.split("\t")[1] == str(_dossier))
    assert int(row.split("\t")[2]) != _dossier

    result = _declare(db, state, {
        "escort_links": [{
            "escort_source_dossier_id": escort_dossiers[0],
            "target_dossier_id": grants[0],
            "relation_type": "护卫", "note": "沿路护送该笔拨帑",
        }],
        "escort_results": [{
            "dossier_id": grants[0],
            "escort_source_dossier_id": escort_dossiers[0],
            "escorted": True, "note": "此路此趟实有护送",
        }],
    })
    assert result.escort_links.rejected == [] and result.escort_results.rejected == []
    assert db.list_dossier_links(escort_dossiers[0])[0]["target_dossier_id"] == grant
    _record_monthly(db, state.turn)
    lo, hi = grant_arrival_bounds(ORDERED, escorted=True)
    row = db.list_dossier_reconciliations(grant)[-1]
    assert row["escorted"] is True
    assert lo <= row["arrived_amount"] <= hi


def test_non_secret_order_dossier_cannot_be_escort_source(game):
    """护行主体必须是密令案卷：拿别的事务案卷充护行人逐项拒收。"""
    db, state, _content = game
    grant = _in_transit_grant(db, state)
    stranger = _in_transit_grant(db, state, text="另一笔在途", target_id="liaodong")
    assert not db.is_secret_order_dossier(grant)
    result = _declare(db, state, {
        "escort_links": [{
            "escort_source_dossier_id": grant, "target_dossier_id": stranger,
            "relation_type": "护卫", "note": "拿拨帑案卷充护行人",
        }],
        "escort_results": [{
            "dossier_id": stranger, "escort_source_dossier_id": grant,
            "escorted": True, "note": "无关联",
        }],
    })
    assert result.escort_links.applied == [] and result.escort_results.applied == []
    assert [r.category for r in result.escort_links.rejected] == ["hallucinated_id"]
    assert [r.category for r in result.escort_results.rejected] == ["hallucinated_id"]
    assert db.list_dossier_links(grant) == []


def test_cross_month_route_reads_own_turn_only(game):
    """跨月口径：上月报的护送实况不替本月顶账；本月无实况即按无护对账。"""
    db, state, _content = game
    grant = _in_transit_grant(db, state)
    _order_id, escort_dossier = _escort_order(db, state)
    _declare(db, state, {
        "escort_links": [{
            "escort_source_dossier_id": escort_dossier, "target_dossier_id": grant,
            "relation_type": "护卫", "note": "沿路护送",
        }],
        "escort_results": [{
            "dossier_id": grant, "escort_source_dossier_id": escort_dossier,
            "escorted": True, "note": "首月实有护送",
        }],
    })
    first = state.turn
    _record_monthly(db, first)
    first_row = db.list_dossier_reconciliations(grant)[-1]
    escort_lo, escort_hi = grant_arrival_bounds(ORDERED, escorted=True)
    assert first_row["escorted"] is True
    assert escort_lo <= first_row["arrived_amount"] <= escort_hi

    # 次月世界段未报该路 → 该月无实况，按无护口径（不拿上月顶账）
    state.turn = first + 1
    _record_monthly(db, state.turn)
    second_row = db.list_dossier_reconciliations(grant)[-1]
    bare_lo, bare_hi = grant_arrival_bounds(ORDERED, escorted=False)
    assert second_row["turn"] == first + 1
    assert second_row["escorted"] is False
    assert bare_lo <= second_row["arrived_amount"] <= bare_hi
    # 逐路历史两行都在，重开无损
    assert len(db.list_dossier_escort_outcomes(grant)) == 1

    # 次月补报 → 该月按有护对账，两月各读各的
    state.turn = first + 2
    _declare(db, state, {"escort_results": [{
        "dossier_id": grant, "escort_source_dossier_id": escort_dossier,
        "escorted": True, "note": "第三月又有护送",
    }]})
    _record_monthly(db, state.turn)
    third_row = db.list_dossier_reconciliations(grant)[-1]
    assert third_row["escorted"] is True
    assert escort_lo <= third_row["arrived_amount"] <= escort_hi
    assert [r["turn"] for r in db.list_dossier_escort_outcomes(grant)] == [first, first + 2]


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


# ── 押解默认随拨银旨（owner 2026-09-30 裁定的常态口径） ──────────────────────────
# 平常「拨银三十万去宁远，着某某押解护送」：押解人记在这道拨银旨里，不另立密令、
# 不另挂关联。密令只管另行暗中加派的护送。


def test_same_decree_escort_needs_no_secret_order_and_no_link(game):
    """押解随拨银旨：只报实况即落有护，全库无密令案卷、无案卷关联。"""
    db, state, _content = game
    grant = _in_transit_grant(db, state, escort={"escortees": [_actor(db)], "note": "押解护送"})
    assert db.dossier_declares_escort(grant)

    result = _declare(db, state, {"escort_results": [
        {"dossier_id": grant, "escorted": True, "note": "押解人随饷同到"},
    ]})
    assert result.escort_results.rejected == []
    landed = db.list_dossier_escort_outcomes(grant)
    assert len(landed) == 1
    assert landed[0]["escorted"] is True
    assert landed[0]["escort_source_dossier_id"] == grant  # 主体＝这道旨自己
    assert landed[0]["relation_type"] == "押解"

    # 没有为这趟护送另立密令，也没有把两条记录互相挂上
    assert db.list_dossier_links(grant) == []
    assert db.list_dossier_links(grant, direction="incoming") == []
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers WHERE secret_order_id IS NOT NULL",
    ).fetchone()["n"] == 0

    _record_monthly(db, state.turn)
    row = db.list_dossier_reconciliations(grant)[-1]
    lo, hi = grant_arrival_bounds(ORDERED, escorted=True)
    assert row["escorted"] is True
    assert lo <= row["arrived_amount"] <= hi
    assert row["arrived_amount"] > grant_arrival_bounds(ORDERED, escorted=False)[1]
    assert row["loss_amount"] == ORDERED - row["arrived_amount"]


def test_escort_result_rejected_when_decree_declares_no_escort(game):
    """该道拨银旨没声明押解 → 不得凭空虚构有护实况（逐项拒收）。"""
    db, state, _content = game
    grant = _in_transit_grant(db, state)
    assert not db.dossier_declares_escort(grant)
    result = _declare(db, state, {"escort_results": [
        {"dossier_id": grant, "escorted": True, "note": "凭空护送"},
    ]})
    assert result.escort_results.applied == []
    assert [r.reason for r in result.escort_results.rejected] == [
        "该道拨银旨未声明押解护送，不得记有护实况",
    ]
    assert db.list_dossier_escort_outcomes(grant) == []


def test_undeclared_escort_route_reconciles_bare(game):
    """对照：没安排护送的拨银即便报了实况也不作有护，按无护口径核账。"""
    db, state, _content = game
    grant = _in_transit_grant(db, state)
    _declare(db, state, {"escort_results": [
        {"dossier_id": grant, "escorted": False, "note": "此路无人护送"},
    ]})
    assert db.list_dossier_escort_outcomes(grant) == []
    targets = db.list_monthly_grant_reconciliation_targets(state.turn)
    assert targets[0]["escorted"] is False
    _record_monthly(db, state.turn)
    row = db.list_dossier_reconciliations(grant)[-1]
    bare_lo, bare_hi = grant_arrival_bounds(ORDERED, escorted=False)
    assert row["escorted"] is False
    assert bare_lo <= row["arrived_amount"] <= bare_hi


def test_other_dossier_cannot_pose_as_escort_source(game):
    """拿别的事务案卷充这道拨银旨的护行人仍拒收（自身以外只认密令案卷）。"""
    db, state, _content = game
    grant = _in_transit_grant(db, state, escort={"escortees": [_actor(db)]})
    stranger = _in_transit_grant(db, state, text="另一笔在途", target_id="liaodong")
    result = _declare(db, state, {"escort_results": [
        {"dossier_id": grant, "escort_source_dossier_id": stranger,
         "escorted": True, "note": "拿别的事务充护行人"},
    ]})
    assert result.escort_results.applied == []
    assert [r.category for r in result.escort_results.rejected] == ["hallucinated_id"]
    assert db.list_dossier_escort_outcomes(grant) == []


def test_commission_declares_escort_inside_same_grant_decree(game):
    """真实入口：同一道拨银交办里写押解人 → 暂存载荷带上它，不另立密令。"""
    db, state, _content = game
    actor = _actor(db)
    state.metrics["内库"] = max(int(state.metrics.get("内库") or 0), ORDERED * 3 + 50)
    result = _declare(db, state, {"commissions": [{
        "text": f"拨银三十万两往陕西，着{actor}押解护送，沿途照关防。",
        "grant": {
            "grant_action": "赈灾", "amount": ORDERED, "account": "内库",
            "target_kind": "region", "target_id": "shaanxi",
            "escort": {"escortees": [actor], "note": "沿途照关防"},
        },
    }]})
    assert result.commissions.rejected == []
    staged = result.commissions.applied[0]["payload"]
    assert staged["escort"]["escortees"] == [actor]
    assert staged["escort"]["note"] == "沿途照关防"

    # 押解人须是真实人物：不存在的人名逐项拒收，不静默丢押解
    bad = _declare(db, state, {"commissions": [{
        "text": "拨银三十万两往陕西，着查无此人押解。",
        "grant": {
            "grant_action": "赈灾", "amount": ORDERED, "account": "内库",
            "target_kind": "region", "target_id": "shaanxi",
            "escort": {"escortees": ["查无此人"]},
        },
    }]})
    assert bad.commissions.applied == []
    assert [r.category for r in bad.commissions.rejected] == ["hallucinated_id"]


def test_commission_without_escort_declares_none(game):
    """没写押解的拨银交办不夹带押解（代码不猜）。"""
    db, state, _content = game
    state.metrics["内库"] = max(int(state.metrics.get("内库") or 0), ORDERED * 3 + 50)
    result = _declare(db, state, {"commissions": [{
        "text": "拨银三十万两往陕西赈灾。",
        "grant": {
            "grant_action": "赈灾", "amount": ORDERED, "account": "内库",
            "target_kind": "region", "target_id": "shaanxi",
        },
    }]})
    assert result.commissions.rejected == []
    assert "escort" not in result.commissions.applied[0]["payload"]


def test_covert_escort_still_goes_through_secret_order_link(game):
    """另行暗中加派：仍走密令案卷 + 0054 单向关联，与押解随旨两路并存。"""
    db, state, _content = game
    grant = _in_transit_grant(db, state, escort={"escortees": [_actor(db)]})
    _order_id, escort_dossier = _escort_order(db, state)
    result = _declare(db, state, {
        "escort_links": [{
            "escort_source_dossier_id": escort_dossier, "target_dossier_id": grant,
            "relation_type": "护卫", "note": "暗中加派护送",
        }],
        "escort_results": [{
            "dossier_id": grant, "escort_source_dossier_id": escort_dossier,
            "escorted": True, "note": "暗护接应同到",
        }],
    })
    assert result.escort_links.rejected == [] and result.escort_results.rejected == []
    landed = db.list_dossier_escort_outcomes(grant)
    assert landed[0]["escort_source_dossier_id"] == escort_dossier
    assert landed[0]["relation_type"] == "护卫"  # 类型取自链，不因该道旨自带押解而改


def test_same_decree_escort_survives_restore(game):
    """重开关档读同一实账：押解随旨的逐路实况与对账行无损。"""
    db, state, content = game
    grant = _in_transit_grant(db, state, escort={"escortees": [_actor(db)]})
    _declare(db, state, {"escort_results": [
        {"dossier_id": grant, "escorted": True, "note": "押解人随饷同到"},
    ]})
    _record_monthly(db, state.turn)
    outcomes = db.list_dossier_escort_outcomes(grant)
    row = db.list_dossier_reconciliations(grant)[-1]

    path = db.path
    db.close()
    reopened = GameDB(path, content=content)
    assert reopened.dossier_declares_escort(grant) is True
    assert reopened.list_dossier_escort_outcomes(grant) == outcomes
    assert reopened.list_dossier_reconciliations(grant) == [row]
    assert reopened._grant_escort_presence(grant, turn=state.turn)[:2] == (True, grant)
    reopened.close()


def test_retract_reverses_escort_records_of_that_round(game):
    """召对撤回本轮：该轮新建与覆盖的押解／暗护记录全部逆转，前轮无损。"""
    from tests.conftest import open_hall_turn

    db, state, _content = game
    grant = _in_transit_grant(db, state, escort={"escortees": [_actor(db)]})
    _order_id, escort_dossier = _escort_order(db, state)
    _declare(db, state, {"escort_links": [{
        "escort_source_dossier_id": escort_dossier, "target_dossier_id": grant,
        "relation_type": "护卫", "note": "暗中加派",
    }]})
    # 前一轮的实况：撤回后必须原样还在
    _declare(db, state, {"escort_results": [
        {"dossier_id": grant, "escorted": True, "note": "首趟押解护成"},
    ]})
    keeper = db.list_dossier_escort_outcomes(grant)

    minister = _actor(db)
    night_id, chat_id = open_hall_turn(db, state, minister)
    uid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'emperor', ?)",
        (minister, state.turn, "着即押解护送。"),
    ).lastrowid
    mid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'minister', ?)",
        (minister, state.turn, "臣遵旨。"),
    ).lastrowid
    db.conn.commit()
    db.update_chat_turn_messages(
        int(chat_id), user_message_id=int(uid), minister_message_id=int(mid),
    )
    before = db.capture_chat_rollback_snapshot()
    # 本轮：另起一道自带押解的拨银 + 覆盖前一轮该路的实况 + 一条新关联
    new_grant = _in_transit_grant(
        db, state, text="另拨一道自带押解", target_id="liaodong",
        escort={"escortees": [minister]},
    )
    _declare(db, state, {"escort_results": [
        {"dossier_id": grant, "escort_source_dossier_id": escort_dossier,
         "escorted": False, "note": "本轮改判失护"},
        {"dossier_id": new_grant, "escorted": True, "note": "本轮新报有护"},
    ]})
    db.record_chat_turn_rollback_diffs(
        int(chat_id), before, db.capture_chat_rollback_snapshot(),
    )
    assert len(db.list_dossier_escort_outcomes(grant)) == 1
    assert db.list_dossier_escort_outcomes(grant)[0]["note"] == "本轮改判失护"
    assert db.list_dossier_escort_outcomes(new_grant)

    db.undo_chat_turn(int(chat_id))

    # 本轮效果全逆转：覆盖回前一轮的值，新报的那道路与新关联一并消失
    assert db.list_dossier_escort_outcomes(grant) == keeper
    assert db.list_dossier_escort_outcomes(new_grant) == []
    assert [link["note"] for link in db.list_dossier_links(escort_dossier)] == ["暗中加派"]
