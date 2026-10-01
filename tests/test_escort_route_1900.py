"""#1900 护送关系可由现役声明产生并影响在途拨帑（ADR 0054 逐路查入链）。

Seams:
- 转译声明 ``commissions[].grant.escort`` → ADR 0053 ``participant_roster``＋押解投影
  （押解随拨银旨；代码只 normalize 与校验，不猜机械档）
- 转译声明 ``commissions[].secret_order`` → 密令暂存／成案核；``escort_pending_targets``
  把同夜暗护指向本夜暂存的拨银交办；该拨银收夜成案后由 ``_resolve_covert_escort_carry``
  承接，记在拨银案卷载荷 ``escort_sources``（真实入口里密令先成案、id 更小，关联槽的
  新指旧装不下这个方向；故由后成案者指先成案者，仍单向、不提前成案、不放宽通用校验）
- 转译声明 ``escort_links`` → ``GameDB.add_dossier_links``（关联真源，单向新指旧）
- 转译声明 ``escort_results`` → ``GameDB.record_dossier_escort_result``（逐路实况）
- ``_grant_escort_presence`` / ``list_monthly_grant_reconciliation_targets``
  （对账只读逐路实况，不凭关联、不凭密令整体成败；正常结案不免除本次核账）
- ``build_translation_target_grounding``（实况与安排分离：失护不反写有护）
- 整月密报供料与 ``continuing_dossier_facts``（按各路结果读，不按整体状态推断）
- ``grant_arrival_bounds``（引擎既有押解折损范围；0054 的 clamp 口已随 #1900 退役）
- 重开（restore）逐路无损；不新增目的地现金账户、不二次扣库

验收对照票面「怎么验」：
- 关联真实落库（现役声明能立链）
- 同夜暗护指向同夜暂存拨银（真实顺序：密令应允即先成案、拨银收夜才成案），
  收夜成案后承接落定
- 一令护多路而结果不同 → 各读各路
- 成功护送后结案仍按该路实际有护对账；正常结案仍核本次账
- 关联存在但该路未实际获护 → 不作有护
"""

from __future__ import annotations

import pytest

from ming_sim.applier import Provenance
from ming_sim.db import GameDB, grant_arrival_bounds
from ming_sim.declaration_dispatch import dispatch_declaration
from tests.dossier_test_helpers import TYPED_COVERT_TASK, create_test_secret_order
from tests.test_grant_reconciliation_567 import (
    ORDERED, _actor, _in_transit_grant, _record_recon,
)


def _escort_order(db, state, *, title="护行饷银"):
    """护行密令（新案卷）——关联要求新指旧，故须晚于被护拨帑案卷成案。"""
    order_id = create_test_secret_order(
        db, state, _actor(db), title, "沿途护送，照关防",
        ["护行"], deadline_months=4,
    )
    dossier = db.get_dossier_for_secret_order(order_id)
    return order_id, int(dossier["id"])


def _declare(db, state, declaration, *, night_id=0, chat_turn_id=0):
    return dispatch_declaration(
        db, state, declaration, source=Provenance.system_simulation,
        night_id=int(night_id), chat_turn_id=int(chat_turn_id),
    )


def _escort_entry(db, name, *, tier="协办", role="押解护送"):
    """ADR 0053 押解参与人条目（代码不猜机械档，条目自带）。"""
    return {"character_id": name, "tier": tier, "role": role, "delegator_id": None}


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

    # 坏类型／幻影案卷／拿拨帑案卷充护行人：逐项拒收，不牵连已落的合法项
    bad = _declare(db, state, {"escort_links": [
        {"escort_source_dossier_id": escort_dossier, "target_dossier_id": grant,
         "relation_type": "接应", "note": "非护送口径"},
        {"escort_source_dossier_id": escort_dossier, "target_dossier_id": 999999,
         "relation_type": "护卫", "note": "幻影案卷"},
        {"escort_source_dossier_id": grant, "target_dossier_id": escort_dossier,
         "relation_type": "护卫", "note": "拿拨帑案卷当护行人"},
    ]})
    assert [r.category for r in bad.escort_links.rejected] == [
        "invalid_enum", "hallucinated_id", "hallucinated_id",
    ]
    assert all(r.reason for r in bad.escort_links.rejected)
    assert len(db.list_dossier_links(escort_dossier)) == 1
    assert db.list_dossier_links(grant) == []

    # 0054 单向新指旧仍由写口本身把守（旧案卷指新案卷整批拒收并留痕）
    with pytest.raises(ValueError):
        db.add_dossier_links(grant, [{
            "target_dossier_id": escort_dossier, "relation_type": "护卫", "note": "倒指",
        }])
    assert [link["source_dossier_id"] for link in
            db.list_dossier_links(grant, direction="incoming")] == [escort_dossier]
    assert len(db.list_dossier_link_rejections(grant)) == 1
    assert all(r["reason"] for r in db.list_dossier_link_rejections(grant))


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

    _record_recon(db, state.turn)
    row = db.list_dossier_reconciliations(grant)[-1]
    assert row["escorted"] is False
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

    _record_recon(db, state.turn)
    recon_rows = db.list_dossier_reconciliations(grant)
    row = recon_rows[-1]
    assert row["escorted"] is True
    assert row["escort_source_dossier_id"] == escort_dossier
    assert row["arrived_amount"] > grant_arrival_bounds(ORDERED, escorted=False)[1]

    path = db.path
    db.close()
    reopened = GameDB(path, content=content)
    assert reopened.list_dossier_escort_outcomes(grant) == landed
    assert reopened.list_escort_outcomes_for_source(escort_dossier) == landed
    assert reopened.list_dossier_reconciliations(grant) == recon_rows
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

    _record_recon(db, state.turn)
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
    _record_recon(db, state.turn)
    row = db.list_dossier_reconciliations(grant)[-1]
    assert row["escorted"] is True
    assert row["escort_source_dossier_id"] == escort_dossier


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
    assert [r.category for r in result.escort_results.rejected] == ["invalid_state"]
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
    _record_recon(db, first)
    first_row = db.list_dossier_reconciliations(grant)[-1]
    assert first_row["escorted"] is True
    assert first_row["turn"] == first

    # 次月世界段未报该路 → 该月无实况，按无护口径（不拿上月顶账）
    state.turn = first + 1
    _record_recon(db, state.turn)
    second_row = db.list_dossier_reconciliations(grant)[-1]
    assert second_row["turn"] == first + 1
    assert second_row["escorted"] is False
    assert second_row["arrived_amount"] < first_row["arrived_amount"]
    assert len(db.list_dossier_escort_outcomes(grant)) == 1

    # 次月补报 → 该月按有护对账，两月各读各的
    state.turn = first + 2
    _declare(db, state, {"escort_results": [{
        "dossier_id": grant, "escort_source_dossier_id": escort_dossier,
        "escorted": True, "note": "第三月又有护送",
    }]})
    _record_recon(db, state.turn)
    third_row = db.list_dossier_reconciliations(grant)[-1]
    assert third_row["turn"] == first + 2
    assert third_row["escorted"] is True
    assert third_row["arrived_amount"] == first_row["arrived_amount"]
    assert [r["turn"] for r in db.list_dossier_escort_outcomes(grant)] == [first, first + 2]


# ── 押解默认随拨银旨（owner 2026-09-30 裁定的常态口径） ──────────────────────────
# 平常「拨银三十万去宁远，着某某押解护送」：押解人记在这道拨银旨里，不另立密令、
# 不另挂关联。密令只管另行暗中加派的护送。


def test_same_decree_escort_needs_no_secret_order_and_no_link(game):
    """押解随拨银旨：只报实况即落有护，全库无密令案卷、无案卷关联。"""
    db, state, _content = game
    grant = _in_transit_grant(db, state, escort={"escortees": [_escort_entry(db, _actor(db))],
                                  "note": "押解护送"})
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

    _record_recon(db, state.turn)
    row = db.list_dossier_reconciliations(grant)[-1]
    assert row["escorted"] is True
    assert row["escort_source_dossier_id"] == grant
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
    assert [r.category for r in result.escort_results.rejected] == ["invalid_state"]
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
    _record_recon(db, state.turn)
    row = db.list_dossier_reconciliations(grant)[-1]
    assert row["escorted"] is False


def test_other_dossier_cannot_pose_as_escort_source(game):
    """拿别的事务案卷充这道拨银旨的护行人仍拒收（自身以外只认密令案卷）。"""
    db, state, _content = game
    grant = _in_transit_grant(db, state, escort={"escortees": [_escort_entry(db, _actor(db))]})
    stranger = _in_transit_grant(db, state, text="另一笔在途", target_id="liaodong")
    result = _declare(db, state, {"escort_results": [
        {"dossier_id": grant, "escort_source_dossier_id": stranger,
         "escorted": True, "note": "拿别的事务充护行人"},
    ]})
    assert result.escort_results.applied == []
    assert [r.category for r in result.escort_results.rejected] == ["hallucinated_id"]
    assert db.list_dossier_escort_outcomes(grant) == []


def test_commission_declares_escort_inside_same_grant_decree(game):
    """真实入口：同一道拨银交办里写押解人 → 暂存载荷带上它，且人进本案参与人名册。"""
    db, state, _content = game
    actor = _actor(db)
    state.metrics["内库"] = max(int(state.metrics.get("内库") or 0), ORDERED * 3 + 50)
    result = _declare(db, state, {"commissions": [{
        "text": f"拨银三十万两往陕西，着{actor}押解护送，沿途照关防。",
        "grant": {
            "grant_action": "赈灾", "amount": ORDERED, "account": "内库",
            "target_kind": "region", "target_id": "shaanxi",
            "escort": {
                "escortees": [_escort_entry(db, actor, tier="主办", role="押解护送")],
                "note": "沿途照关防",
            },
        },
    }]})
    assert result.commissions.rejected == []
    staged = result.commissions.applied[0]["payload"]
    assert staged["escort"]["escortees"] == [actor]
    assert staged["escort"]["note"] == "沿途照关防"
    # ADR 0053 单一真源：押解人的职责与机械档进本案参与人名册（不另走平行名单）
    assert staged["participant_roster"] == [{
        "character_id": actor, "tier": "主办", "role": "押解护送", "delegator_id": None,
    }]
    dossier_id = _dossier_for_pending(db, state, int(result.commissions.applied[0]["id"]))
    roster = db.get_decree_dossier(dossier_id)["participant_roster"]
    assert {
        "character_id": actor, "tier": "主办", "role": "押解护送", "delegator_id": None,
    } in roster

    other = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND name!=? ORDER BY name LIMIT 1",
        (actor,),
    ).fetchone()["name"]
    merged = _declare(db, state, {"commissions": [{
        "text": f"再拨一笔，着{actor}押解，{other}知情。",
        "participant_roster": [_escort_entry(db, other, tier="知情", role="知会")],
        "grant": {
            "grant_action": "赈灾", "amount": ORDERED, "account": "内库",
            "target_kind": "region", "target_id": "shaanxi",
            "escort": {
                "escortees": [_escort_entry(db, actor, tier="主办", role="押解护送")],
                "note": "沿途照关防",
            },
        },
    }]})
    assert merged.commissions.rejected == []
    names = {
        entry["character_id"]
        for entry in merged.commissions.applied[0]["payload"]["participant_roster"]
    }
    assert names == {actor, other}


def test_commission_malformed_escort_is_rejected_not_dropped(game):
    """已声明却不是 ADR 0053 条目形状的押解安排 → 逐项拒收，不静默消失。"""
    db, state, _content = game
    state.metrics["内库"] = max(int(state.metrics.get("内库") or 0), ORDERED * 3 + 50)
    base = {
        "grant_action": "赈灾", "amount": ORDERED, "account": "内库",
        "target_kind": "region", "target_id": "shaanxi",
    }
    for escort in (
        "押解",                                   # 声明了却不是对象
        {"escortees": "乔允升"},                    # 条目不是列表
        {"escortees": [_actor(db)]},                # 条目不是 ADR 0053 对象
        {"escortees": [{"character_id": _actor(db)}]},   # 缺机械档
        {"escortees": [_escort_entry(db, _actor(db))], "note": 7},
        {"escortees": []},
    ):
        result = _declare(db, state, {"commissions": [{
            "text": "拨银三十万两往陕西赈灾，着人押解。",
            "grant": {**base, "escort": escort},
        }]})
        assert result.commissions.applied == [], escort
        assert [r.category for r in result.commissions.rejected] == ["invalid_shape"], escort
        assert all(r.reason for r in result.commissions.rejected), escort


def test_commission_escort_names_must_exist(game):
    """押解人须是真实人物：不存在的人名逐项拒收，不静默丢押解。"""
    db, state, _content = game
    state.metrics["内库"] = max(int(state.metrics.get("内库") or 0), ORDERED * 3 + 50)
    result = _declare(db, state, {"commissions": [{
        "text": "拨银三十万两往陕西，着查无此人押解。",
        "grant": {
            "grant_action": "赈灾", "amount": ORDERED, "account": "内库",
            "target_kind": "region", "target_id": "shaanxi",
            "escort": {"escortees": [{
                "character_id": "查无此人", "tier": "协办", "role": "押解",
                "delegator_id": None,
            }]},
        },
    }]})
    assert result.commissions.applied == []
    assert [r.category for r in result.commissions.rejected] == ["hallucinated_id"]


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
    grant = _in_transit_grant(db, state, escort={"escortees": [_escort_entry(db, _actor(db))]})
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


def test_same_decree_escort_declaration_survives_restore(game):
    """重开关档：押解随旨那道的押解声明与逐路实况都还在。"""
    db, state, content = game
    grant = _in_transit_grant(
        db, state, escort={"escortees": [_escort_entry(db, _actor(db))]},
    )
    _declare(db, state, {"escort_results": [
        {"dossier_id": grant, "escorted": True, "note": "押解人随饷同到"},
    ]})
    outcomes = db.list_dossier_escort_outcomes(grant)

    path = db.path
    db.close()
    reopened = GameDB(path, content=content)
    try:
        assert reopened.dossier_declares_escort(grant) is True
        assert reopened.list_dossier_escort_outcomes(grant) == outcomes
        assert reopened._grant_escort_presence(grant, turn=state.turn)[:2] == (True, grant)
    finally:
        reopened.close()


def test_retract_reverses_escort_records_of_that_round(game):
    """召对撤回本轮：该轮新建与覆盖的押解／暗护记录全部逆转，前轮无损。"""
    from tests.conftest import open_hall_turn

    db, state, _content = game
    grant = _in_transit_grant(db, state, escort={"escortees": [_escort_entry(db, _actor(db))]})
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
    # 本轮：另起一道自带押解的拨银 + 覆盖前一轮该路的实况 + 一条新关联
    new_grant = _in_transit_grant(
        db, state, text="另拨一道自带押解", target_id="liaodong",
        escort={"escortees": [_escort_entry(db, minister)]},
    )
    # 走真实分派入口（自带 chat_turn_id）：入口自记撤回前像，测试不手工补日志。
    _declare(db, state, {"escort_results": [
        {"dossier_id": grant, "escort_source_dossier_id": escort_dossier,
         "escorted": False, "note": "本轮改判失护"},
        {"dossier_id": new_grant, "escorted": True, "note": "本轮新报有护"},
    ]}, night_id=int(night_id), chat_turn_id=int(chat_id))
    assert len(db.list_dossier_escort_outcomes(grant)) == 1
    assert db.list_dossier_escort_outcomes(grant)[0]["note"] == "本轮改判失护"
    assert db.list_dossier_escort_outcomes(new_grant)

    db.undo_chat_turn(int(chat_id))

    # 本轮效果全逆转：覆盖回前一轮的值，新报的那道路与新关联一并消失
    assert db.list_dossier_escort_outcomes(grant) == keeper
    assert db.list_dossier_escort_outcomes(new_grant) == []
    assert [link["note"] for link in db.list_dossier_links(escort_dossier)] == ["暗中加派"]


# ── 同夜暗护：密令声明指向本夜暂存的拨银交办，收夜成案后承接（#1900） ──────────


def _covert_escort_commission(db, state, *, staged_id, actor, relation="护卫",
                              note="暗中加派护送该笔赈银", title="暗护赈饷"):
    return {
        "text": "另密令一路暗护该笔赈银。",
        "secret_order": {
            "title": title, "content": "沿途暗中护送该笔赈银",
            "assignee": actor, "tags": ["护行"], "deadline_months": 3,
            "covert_task": dict(TYPED_COVERT_TASK),
            "escort_pending_targets": [
                {"pending_action_id": staged_id, "relation_type": relation, "note": note},
            ],
        },
    }


def _grant_commission(db, state, actor, *, amount=ORDERED, target_id="shaanxi"):
    state.metrics["内库"] = max(int(state.metrics.get("内库") or 0), amount * 3 + 50)
    return {
        "text": f"拨银三十万两往{target_id}赈灾。",
        "grant": {
            "grant_action": "赈灾", "amount": amount, "account": "内库",
            "target_kind": "region", "target_id": target_id,
        },
    }


def _night_turn(db, state, actor, message):
    """开一夜并造一条 active 对话轮（密令声明要求本轮口谕源轮）。"""
    from tests.conftest import open_hall_turn

    night_id, chat_id = open_hall_turn(db, state, actor)
    uid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'emperor', ?)", (actor, state.turn, message),
    ).lastrowid
    mid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'minister', ?)", (actor, state.turn, "臣遵旨。"),
    ).lastrowid
    db.conn.commit()
    db.update_chat_turn_messages(
        int(chat_id), user_message_id=int(uid), minister_message_id=int(mid),
    )
    return int(night_id), int(chat_id)


def _dossier_for_pending(db, state, pending_action_id):
    """把一条已应允的 directive 暂存走收夜成案核，返回成案案卷 id。"""
    db.mark_pending_night_approved([int(pending_action_id)])
    db.commit_pending_actions(state, action_ids=[int(pending_action_id)])
    db.ensure_dossiers_for_draft_directives(state)   # 结束边界成案唯一入口
    row = db.conn.execute(
        "SELECT id FROM decree_dossiers WHERE pending_action_id=? ORDER BY id LIMIT 1",
        (int(pending_action_id),),
    ).fetchone()
    assert row is not None, "该道拨银交办未成案"
    return int(row["id"])


def test_same_night_covert_escort_carries_onto_grant_dossier(game):
    """同夜两道拨银：预推目录用各自暂存标识，成案后逐路实况落回各路。"""
    import json
    from types import SimpleNamespace

    from ming_sim.declaration_dispatch import (
        settle_staged_declarations_in_decree_order,
        stage_declaration,
    )
    from ming_sim.decree_forecast import _pending_snapshot, release_forecast_materials

    db, state, content = game
    actor = _actor(db)
    night_id, chat_id = _night_turn(db, state, actor, "拨银两道，一道押解，一道另密令暗护。")
    state.metrics["内库"] = max(int(state.metrics.get("内库") or 0), ORDERED * 6 + 50)

    ordinary_res = _declare(db, state, {"commissions": [{
        "text": f"拨银三十万两往陕西，着{actor}押解护送。",
        "grant": {
            "grant_action": "赈灾", "amount": ORDERED, "account": "内库",
            "target_kind": "region", "target_id": "shaanxi",
            "escort": {
                "escortees": [_escort_entry(db, actor, tier="主办", role="押解护送")],
                "note": "沿途照关防",
            },
        },
    }]}, night_id=night_id, chat_turn_id=chat_id)
    covert_res = _declare(
        db, state, {"commissions": [_grant_commission(db, state, actor, target_id="liaodong")]},
        night_id=night_id, chat_turn_id=chat_id,
    )
    assert ordinary_res.commissions.rejected == []
    assert covert_res.commissions.rejected == []
    ordinary_pending = int(ordinary_res.commissions.applied[0]["id"])
    covert_pending = int(covert_res.commissions.applied[0]["id"])
    assert db.get_dossier_for_directive(ordinary_pending) is None
    assert db.get_dossier_for_directive(covert_pending) is None

    raw_note = " \n暗护缘由原句 \n"
    raw_title = " \n暗护标题原句 \n"
    secret_res = _declare(db, state, {"commissions": [
        _covert_escort_commission(
            db, state, staged_id=covert_pending, actor=actor,
            note=raw_note, title=raw_title,
        ),
    ]}, night_id=night_id, chat_turn_id=chat_id)
    assert secret_res.commissions.rejected == []
    secret_action_id = int(secret_res.commissions.applied[0]["id"])
    db.mark_pending_night_approved(
        [ordinary_pending, covert_pending, secret_action_id],
        night_id=night_id, source_chat_turn_id=chat_id,
    )
    # 真实顺序：密令应允即落地，拨银拟旨收夜才成案。
    db.commit_pending_actions(state, action_ids=[secret_action_id])
    order = db.list_secret_orders()[0]
    assert order["title"] == raw_title
    escort_dossier = int(db.get_dossier_for_secret_order(int(order["id"]))["id"])
    assert db.get_decree_dossier(escort_dossier)["status"] == "promulgated"

    session = SimpleNamespace(db=db, state=state, content=content)
    ordinary_snap = _pending_snapshot(session, ordinary_pending, night_id)
    covert_snap = _pending_snapshot(session, covert_pending, night_id)
    assert ordinary_snap is not None and covert_snap is not None
    try:
        assert ordinary_snap["decree_ref"] != covert_snap["decree_ref"]
        assert ordinary_snap["this_decree"]["id"] == ordinary_snap["decree_ref"]
        assert covert_snap["this_decree"]["id"] == covert_snap["decree_ref"]
        assert ordinary_snap["this_decree"]["id"] != ordinary_snap["candidate"]["id"]
        assert covert_snap["this_decree"]["id"] != covert_snap["candidate"]["id"]
        ordinary_payload = ordinary_snap["this_decree"]["payload"]
        assert "escort_sources" not in ordinary_payload
        assert ordinary_payload["escort"]["escortees"]
        assert covert_snap["this_decree"]["payload"]["escort_sources"] == [{
            "secret_order_dossier_id": escort_dossier,
            "relation_type": "护卫",
            "note": raw_note,
        }]
    finally:
        release_forecast_materials(ordinary_snap)
        release_forecast_materials(covert_snap)

    for pending_id in (ordinary_pending, covert_pending):
        stored = json.loads(db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
        ).fetchone()["payload_json"])
        assert "escort_sources" not in stored
        assert db.get_dossier_for_directive(pending_id) is None

    stage_declaration(
        db, decree_ref=ordinary_snap["decree_ref"], turn=int(state.turn),
        declaration={"escort_results": [{
            "dossier_id": ordinary_snap["decree_ref"],
            "escorted": False, "note": "此路损耗原句",
        }]},
    )
    stage_declaration(
        db, decree_ref=covert_snap["decree_ref"], turn=int(state.turn),
        declaration={"escort_results": [{
            "dossier_id": covert_snap["decree_ref"],
            "escort_source_dossier_id": escort_dossier,
            "escorted": True, "note": "暗护接应同到",
        }]},
    )

    ordinary_dossier = _dossier_for_pending(db, state, ordinary_pending)
    covert_dossier = _dossier_for_pending(db, state, covert_pending)
    assert escort_dossier < ordinary_dossier
    assert escort_dossier < covert_dossier
    assert db.escort_source_dossiers_of(covert_dossier) == [{
        "secret_order_dossier_id": escort_dossier, "relation_type": "护卫",
        "note": raw_note,
    }]
    assert db.escort_source_dossiers_of(ordinary_dossier) == []
    assert db.list_dossier_links(escort_dossier) == []
    assert db.list_dossier_links(covert_dossier) == []
    assert db.list_escort_link_pairs() == [{
        "source_dossier_id": escort_dossier, "target_dossier_id": covert_dossier,
        "relation_type": "护卫",
    }]

    settled = settle_staged_declarations_in_decree_order(
        db, state, [ordinary_snap["decree_ref"], covert_snap["decree_ref"]],
    )
    assert settled[ordinary_snap["decree_ref"]].escort_results.rejected == []
    assert settled[covert_snap["decree_ref"]].escort_results.rejected == []
    ordinary_outcome = db.list_dossier_escort_outcomes(ordinary_dossier)
    covert_outcome = db.list_dossier_escort_outcomes(covert_dossier)
    assert len(ordinary_outcome) == 1 and len(covert_outcome) == 1
    assert ordinary_outcome[0]["escorted"] is False
    assert ordinary_outcome[0]["escort_source_dossier_id"] == ordinary_dossier
    assert ordinary_outcome[0]["relation_type"] == "押解"
    assert ordinary_outcome[0]["note"] == "此路损耗原句"
    assert covert_outcome[0]["escorted"] is True
    assert covert_outcome[0]["escort_source_dossier_id"] == escort_dossier
    assert covert_outcome[0]["note"] == "暗护接应同到"

    db.apply_dossier_promulgation(state, ordinary_dossier, "promulgated")
    db.apply_dossier_promulgation(state, covert_dossier, "promulgated")
    by_id = {
        int(row["dossier_id"]): row
        for row in db.list_monthly_grant_reconciliation_targets(state.turn)
    }
    assert by_id[ordinary_dossier]["escorted"] is False
    assert by_id[covert_dossier]["escorted"] is True


def test_same_night_covert_audit_reaches_supervision_presence(game):
    """同夜承接的稽核配对也进稽核在场（#1900）：承接不走 0054 槽，在场读口须并读。"""
    db, state, _content = game
    actor = _actor(db)
    night_id, chat_id = _night_turn(db, state, actor, "拨银三十万两往陕西赈灾，另密令沿途稽核。")

    grant_res = _declare(
        db, state, {"commissions": [_grant_commission(db, state, actor)]},
        night_id=night_id, chat_turn_id=chat_id,
    )
    staged_id = int(grant_res.commissions.applied[0]["id"])
    secret_res = _declare(
        db, state, {"commissions": [
            _covert_escort_commission(db, state, staged_id=staged_id, actor=actor,
                                      relation="稽核", note="沿途暗中稽核该笔赈银"),
        ]},
        night_id=night_id, chat_turn_id=chat_id,
    )
    secret_action_id = int(secret_res.commissions.applied[0]["id"])
    db.mark_pending_night_approved(
        [staged_id, secret_action_id], night_id=night_id, source_chat_turn_id=chat_id,
    )
    db.commit_pending_actions(state, action_ids=[secret_action_id])
    order = db.list_secret_orders()[0]
    escort_dossier = int(db.get_dossier_for_secret_order(int(order["id"]))["id"])
    grant_dossier = _dossier_for_pending(db, state, staged_id)
    db.apply_dossier_promulgation(state, grant_dossier, "promulgated")

    assert db.list_escort_link_pairs() == [{
        "source_dossier_id": escort_dossier, "target_dossier_id": grant_dossier,
        "relation_type": "稽核",
    }]
    db.record_monthly_supervision_presence(int(state.turn))
    assert db.dossier_has_supervision_presence(grant_dossier, int(state.turn)) is True


def test_covert_escort_rejects_non_grant_pending_target(game):
    """指向的不是本夜拨帑暂存（幻影 id／非拨帑交办）→ 不承接，不留假关联。"""
    db, state, _content = game
    actor = _actor(db)
    night_id, chat_id = _night_turn(db, state, actor, "另下一道不是拨银的交办，另密令暗护。")

    plain = _declare(db, state, {"commissions": [{
        "text": "着大臣查勘陕西屯田。",
        "assignment": {
            "title": "查勘屯田", "target_id": "policy", "assignee": actor,
        },
    }]}, night_id=night_id, chat_turn_id=chat_id)
    assert plain.commissions.rejected == []
    not_grant = int(plain.commissions.applied[0]["id"])

    secret_res = _declare(
        db, state, {"commissions": [
            _covert_escort_commission(db, state, staged_id=999999, actor=actor,
                                      relation="接应", note="", title="幻影指向"),
            _covert_escort_commission(db, state, staged_id=not_grant, actor=actor,
                                      title="非拨帑指向"),
        ]},
        night_id=night_id, chat_turn_id=chat_id,
    )
    assert [item.category for item in secret_res.commissions.rejected] == [
        "hallucinated_id", "invalid_state",
    ]
    assert secret_res.commissions.applied
    for action_id in [int(a["id"]) for a in secret_res.commissions.applied]:
        db.mark_pending_night_approved([action_id], night_id=night_id)
    db.commit_pending_actions(
        state, action_ids=[int(a["id"]) for a in secret_res.commissions.applied],
    )
    for order in db.list_secret_orders():
        dossier = db.get_dossier_for_secret_order(int(order["id"]))
        dossier_id = int(dossier["id"])
        assert db.list_dossier_links(dossier_id) == []
        assert not dossier["payload"].get("escort_pending_targets")


def test_escort_routes_reach_supply_and_world_materials(game):
    """读取闭环：整月密报供料与世界段材料按各路实况给料，不按整体状态推断。"""
    db, state, _content = game
    from ming_sim.materials import continuing_dossier_facts
    from ming_sim.month_chain import build_secret_orders_supply_feed

    names = [
        str(row["name"]) for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' ORDER BY name",
        ).fetchall()
    ]
    executor, escortee, outsider = names[0], names[1], names[2]
    grant = _in_transit_grant(
        db, state, escort={"escortees": [_escort_entry(db, escortee)]},
    )
    order_id = create_test_secret_order(
        db, state, executor, "护行饷银", "沿途护送，照关防", ["护行"],
        deadline_months=4, excluded_names=[escortee],
    )
    escort_dossier = int(db.get_dossier_for_secret_order(order_id)["id"])
    _declare(db, state, {
        "escort_links": [{
            "escort_source_dossier_id": escort_dossier, "target_dossier_id": grant,
            "relation_type": "护卫", "note": "暗中加派",
        }],
        "escort_results": [{
            "dossier_id": grant, "escort_source_dossier_id": escort_dossier,
            "escorted": False, "note": "此趟遇截折护",
        }],
    })

    route_note = "此趟遇截折护"
    fact = next(f for f in continuing_dossier_facts(db, state.turn) if f["id"] == grant)
    assert fact["escorted"] is False                    # 账本事实：失护
    assert fact["escort_source_dossier_id"] == escort_dossier
    assert fact["escort_relation_type"] == "护卫"
    assert fact["escort_note"] == route_note

    feed = build_secret_orders_supply_feed(db, state, {"facts": {}})
    as_source = next(
        row["escort_routes_as_escort_source"] for row in feed["eligible_dossiers"]
        if int(row["dossier_id"]) == escort_dossier
    )
    assert [(r["dossier_id"], r["escorted"], r["note"]) for r in as_source] == [
        (grant, False, route_note),
    ]
    assert route_note in feed["board"]

    from types import SimpleNamespace
    from ming_sim.materials import (
        character_office_archive_text, grant_route_reader_facts,
        prepare_world_materials, release_material_tree,
    )

    def _route_view(person, dossier_id):
        dossiers = db.list_referenceable_dossiers(person, state.turn)
        rows = [
            item for item in grant_route_reader_facts(db, person, dossiers)
            if int(item["dossier_id"]) == dossier_id
        ]
        assert len(rows) == 1
        return rows[0]

    db.record_dossier_progress(grant, int(state.turn), "在途", "奏报银两仍在途")

    def _board_and_archives():
        prepared = prepare_world_materials(db, state)
        try:
            board = (prepared.root / "盘面" / "全局.txt").read_text(encoding="utf-8")
        finally:
            release_material_tree(prepared.root)
        archives = {
            person: character_office_archive_text(
                db, state, SimpleNamespace(name=person), {},
            )
            for person in (executor, escortee, outsider)
        }
        return board, archives

    board, archives = _board_and_archives()
    assert route_note in board
    assert route_note in archives[executor]
    assert route_note in archives[escortee]
    assert route_note not in archives[outsider]
    executor_view = _route_view(executor, grant)
    escortee_view = _route_view(escortee, grant)
    outsider_view = _route_view(outsider, grant)
    assert executor_view["source_dossier_id"] == escort_dossier
    assert executor_view["note"] == route_note
    assert escortee_view["route_visible"] is True
    assert escortee_view["source_dossier_id"] is None
    assert escortee_view["note"] == route_note
    assert outsider_view["route_visible"] is False
    assert outsider_view["source_dossier_id"] is None
    assert outsider_view["memorial_text"] == "奏报银两仍在途"

    db.record_dossier_escort_result(
        int(state.turn), dossier_id=grant, escort_source_dossier_id=escort_dossier,
        escorted=True, note="此趟改记有护",
    )
    flipped = build_secret_orders_supply_feed(db, state, {"facts": {}})
    assert feed["board"] != flipped["board"]
    flipped_source = next(
        row["escort_routes_as_escort_source"] for row in flipped["eligible_dossiers"]
        if int(row["dossier_id"]) == escort_dossier
    )
    assert [(r["dossier_id"], r["escorted"]) for r in flipped_source] == [(grant, True)]
    board_after, archives_after = _board_and_archives()
    assert board != board_after
    assert archives[executor] != archives_after[executor]
    assert archives[escortee] != archives_after[escortee]
    assert archives[outsider] == archives_after[outsider]
    executor_after = _route_view(executor, grant)
    escortee_after = _route_view(escortee, grant)
    outsider_after = _route_view(outsider, grant)
    assert executor_after["source_dossier_id"] == escort_dossier
    assert executor_after["note"] == "此趟改记有护"
    assert escortee_after["source_dossier_id"] is None
    assert escortee_after["note"] == "此趟改记有护"
    assert outsider_after["route_visible"] is False
    assert outsider_after["source_dossier_id"] is None
    assert outsider_after["memorial_text"] == "奏报银两仍在途"
    assert "此趟改记有护" in archives_after[executor]
    assert "此趟改记有护" in archives_after[escortee]
    assert "此趟改记有护" not in archives_after[outsider]
    assert "奏报银两仍在途" in archives_after[outsider]

    # 正常结案之后，翻已落的逐路实况仍改得到推演账本；对账扫描面不再把它当在途。
    plain = _in_transit_grant(
        db, state, text="本回合押解到达", target_id="liaodong",
        escort={"escortees": [_escort_entry(db, escortee)]},
    )
    plain_note = "押解人随饷同到"
    _declare(db, state, {"escort_results": [{
        "dossier_id": plain, "escorted": True, "note": plain_note,
    }]})
    plain_fact = next(f for f in continuing_dossier_facts(db, state.turn) if f["id"] == plain)
    assert plain_fact["escort_note"] == plain_note
    plain_feed = build_secret_orders_supply_feed(db, state, {"facts": {}})
    assert plain_note in plain_feed["board"]
    plain_board, plain_archives = _board_and_archives()
    assert plain_note in plain_board
    assert plain_note in plain_archives[escortee]
    assert plain_note not in plain_archives[outsider]
    db.record_dossier_execution(plain, "fulfilled", "押解已达", int(state.turn), close=True)
    assert plain not in {
        int(row["dossier_id"])
        for row in db.list_monthly_grant_reconciliation_targets()
    }
    closed_feed = build_secret_orders_supply_feed(db, state, {"facts": {}})
    closed_board, _archives = _board_and_archives()
    db.record_dossier_escort_result(
        int(state.turn), dossier_id=plain, escort_source_dossier_id=plain,
        escorted=False, note="结案后改记失护",
    )
    reopened_feed = build_secret_orders_supply_feed(db, state, {"facts": {}})
    reopened_board, _archives = _board_and_archives()
    assert closed_board != reopened_board
    assert closed_feed["board"] != reopened_feed["board"]
    assert plain not in {
        int(row["dossier_id"])
        for row in db.list_monthly_grant_reconciliation_targets()
    }
