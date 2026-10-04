"""#1900 ordinary grant.escort living contracts (revoked specialized escort paths retired)."""

from __future__ import annotations

from ming_sim.applier import Provenance
from ming_sim.declaration_dispatch import dispatch_declaration
from tests.test_grant_reconciliation_567 import ORDERED, _actor

def _declare(db, state, declaration, *, night_id=0, chat_turn_id=0):
    return dispatch_declaration(
        db, state, declaration, source=Provenance.system_simulation,
        night_id=int(night_id), chat_turn_id=int(chat_turn_id),
    )


def _escort_entry(db, name, *, tier="协办", role="押解护送"):
    """ADR 0053 押解参与人条目（代码不猜机械档，条目自带）。"""
    return {"character_id": name, "tier": tier, "role": role, "delegator_id": None}

def _dossier_for_pending(db, state, pending_action_id):
    """把一条已应允的 directive 暂存走收夜成案核，返回成案案卷 id。"""
    db.mark_pending_night_approved([int(pending_action_id)])
    db.commit_pending_actions(state, action_ids=[int(pending_action_id)])
    db.ensure_dossiers_for_draft_directives(state)
    row = db.conn.execute(
        "SELECT id FROM decree_dossiers WHERE pending_action_id=? ORDER BY id LIMIT 1",
        (int(pending_action_id),),
    ).fetchone()
    assert row is not None, "该道拨银交办未成案"
    return int(row["id"])



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

    # #1900 J19-R1：交办名单复用 normalize 后，非法档须逐项 invalid_shape，
    # 不得未捕获 ValueError 整份中止；同批合法项继续。入口＝真实 dispatch。
    actor = _actor(db)
    bad_entry = {
        "character_id": actor, "tier": "乱档", "role": "", "delegator_id": None,
    }
    good_escort = {
        "escortees": [_escort_entry(db, actor, tier="协办", role="押解护送")],
        "note": "沿途照关防",
    }
    roster_cases = (
        {"text": "拨银三十万两往陕西赈灾。",
         "participant_roster": [bad_entry], "grant": dict(base)},
        {"text": "拨银三十万两往陕西赈灾。",
         "grant": {**base, "participant_roster": [bad_entry]}},
        {"text": "拨银三十万两往陕西，着人押解。",
         "participant_roster": [bad_entry],
         "grant": {**base, "escort": good_escort}},
        {"text": "拨银三十万两往陕西，着人押解。",
         "grant": {**base, "participant_roster": [bad_entry], "escort": good_escort}},
    )
    for item in roster_cases:
        result = _declare(db, state, {"commissions": [item]})
        assert result.commissions.applied == [], item
        assert [r.category for r in result.commissions.rejected] == ["invalid_shape"], item
        assert any("机械档非法" in (r.reason or "") for r in result.commissions.rejected), item

    batch = _declare(db, state, {"commissions": [
        {"text": "拨银三十万两往陕西赈灾（非法名单）。",
         "participant_roster": [bad_entry], "grant": dict(base)},
        {"text": "拨银三十万两往陕西赈灾（合法）。", "grant": dict(base)},
    ]})
    assert [r.category for r in batch.commissions.rejected] == ["invalid_shape"]
    assert len(batch.commissions.applied) == 1
    assert "escort" not in batch.commissions.applied[0]["payload"]

    # J19 既结：同人主办+协办两条均保留（equality 追加，不按 character_id 裁）
    same = _declare(db, state, {"commissions": [{
        "text": f"拨银，着{actor}押解并统筹。",
        "participant_roster": [{
            "character_id": actor, "tier": "主办", "role": "统筹", "delegator_id": None,
        }],
        "grant": {**base, "escort": good_escort},
    }]})
    assert same.commissions.rejected == []
    roster = same.commissions.applied[0]["payload"]["participant_roster"]
    assert {
        "character_id": actor, "tier": "协办", "role": "押解护送", "delegator_id": None,
    } in roster
    assert {
        "character_id": actor, "tier": "主办", "role": "统筹", "delegator_id": None,
    } in roster


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
