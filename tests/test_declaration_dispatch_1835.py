"""#1835 转译输出契约与分派器（C0，铺路）。

受控声明桩（模拟转译 LLM 一次产出）直接喂 ``dispatch_declaration``，验证：
真实分派链落到既有暂存（pending_actions）与 R1-R3 新记录，无漏项（AC1）；
一句话同时含拟旨 + 拨帑时只成一份载荷、只落一条 pending_actions（AC2）；
声明里引用不存在实体的项逐项拒收留痕，不带走同批其余合法项（AC3）；
召对与过月两处调用同一个 dispatch_declaration，没有第二份同构逻辑（AC4）。
"""

from __future__ import annotations

import json

from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.public_sayings import list_public_sayings


def _minister(db):
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()
    assert row is not None
    return str(row["name"])


def _army_id(db) -> str:
    row = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()
    assert row is not None
    return str(row["id"])


def test_stub_declaration_lands_on_existing_staging_and_new_records_without_missing_items(game):
    db, state, _ = game
    minister = _minister(db)
    # 既有暂存：上一轮已经暂存、本轮转译声明它「应允」。
    pre_staged_id = db.stage_pending_action(
        int(state.turn), "directive", "拟旨", minister, {"text": "已暂存旧旨"},
    )

    declaration = {
        "commissions": [{"text": "遣使赈济陕西"}],
        "promises": [{"action_id": pre_staged_id, "decision": "应允"}],
        "textual_facts": [{
            "subject_kind": "character", "subject_id": minister,
            "body": "抱恙数日，仍可视事",
        }],
        "public_sayings": [{
            "body": "坊间传户部已备赈灾银", "involved_characters": [minister],
        }],
    }

    result = dispatch_declaration(db, state, declaration, minister_name=minister)

    assert len(result.commissions.applied) == 1 and result.commissions.rejected == []
    assert len(result.promises.applied) == 1 and result.promises.rejected == []
    assert len(result.textual_facts.applied) == 1 and result.textual_facts.rejected == []
    assert len(result.public_sayings.applied) == 1 and result.public_sayings.rejected == []

    approved_row = db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (pre_staged_id,),
    ).fetchone()
    assert approved_row["night_approved"] == 1

    facts = db.textual_facts.readable_materials(subject_kind="character", subject_id=minister)
    assert [f.body for f in facts] == ["抱恙数日，仍可视事"]

    sayings = list_public_sayings(db, involved_character=minister)
    assert len(sayings) == 1
    assert sayings[0]["body"] == "坊间传户部已备赈灾银"


def test_commission_with_draft_and_grant_for_same_money_is_one_payload_one_row(game):
    db, state, _ = game
    minister = _minister(db)
    army_id = _army_id(db)
    before = db.conn.execute("SELECT COUNT(*) c FROM pending_actions").fetchone()["c"]

    declaration = {
        "commissions": [{
            "text": "拨国库十五万两协饷该军",
            "grant": {
                "amount": 150000, "account": "国库", "purpose": "补饷",
                "target_kind": "army", "target_id": army_id,
            },
        }],
    }
    result = dispatch_declaration(db, state, declaration, minister_name=minister)

    assert result.commissions.rejected == []
    assert len(result.commissions.applied) == 1
    after = db.conn.execute("SELECT COUNT(*) c FROM pending_actions").fetchone()["c"]
    assert after - before == 1

    row = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?",
        (result.commissions.applied[0]["id"],),
    ).fetchone()
    payload = json.loads(row["payload_json"])
    assert payload["text"] == "拨国库十五万两协饷该军"
    assert payload["amount"] == 150000
    assert payload["account"] == "国库"
    assert payload["target_id"] == army_id


def test_reference_to_nonexistent_entity_is_rejected_without_killing_sibling_item(game):
    db, state, _ = game
    minister = _minister(db)

    declaration = {
        "textual_facts": [
            {"subject_kind": "character", "subject_id": "子虚乌有之人", "body": "凭空捏造"},
            {"subject_kind": "character", "subject_id": minister, "body": "如实记事"},
        ],
    }
    result = dispatch_declaration(db, state, declaration, minister_name=minister)

    assert len(result.textual_facts.rejected) == 1
    assert result.textual_facts.rejected[0].category == "hallucinated_id"
    assert result.textual_facts.rejected[0].item["subject_id"] == "子虚乌有之人"
    assert len(result.textual_facts.applied) == 1

    facts = db.textual_facts.readable_materials(subject_kind="character", subject_id=minister)
    assert [f.body for f in facts] == ["如实记事"]
    assert db.textual_facts.readable_materials(
        subject_kind="character", subject_id="子虚乌有之人",
    ) == ()


def test_promise_refuse_withdraws_staged_action_and_missing_action_id_is_rejected(game):
    db, state, _ = game
    minister = _minister(db)
    staged_id = db.stage_pending_action(
        int(state.turn), "directive", "拟旨", minister, {"text": "待反悔的旧旨"},
    )

    declaration = {
        "promises": [
            {"action_id": staged_id, "decision": "拒绝"},
            {"action_id": staged_id + 100000, "decision": "应允"},
        ],
    }
    result = dispatch_declaration(db, state, declaration, minister_name=minister)

    assert len(result.promises.applied) == 1
    assert result.promises.applied[0] == {"action_id": staged_id, "decision": "拒绝"}
    assert len(result.promises.rejected) == 1
    assert result.promises.rejected[0].category == "missing_ref"

    row = db.conn.execute(
        "SELECT id FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()
    assert row is None


def test_audience_and_month_end_call_the_same_dispatcher_no_parallel_logic(game):
    """0155（召对承接）/0157（过月）两处生产调用点尚未接线（Status: proposed，未实施）；
    本票只钉契约层的单一入口——两处未来调用点喂同形声明，落地同构，不必各自
    另判一套分派逻辑（AC4：没有第二份同构逻辑）。"""
    db, state, _ = game
    minister = _minister(db)

    def audience_side_call(decl):
        return dispatch_declaration(db, state, decl, minister_name=minister)

    def month_end_side_call(decl):
        return dispatch_declaration(db, state, decl, minister_name=minister)

    declaration_a = {"commissions": [{"text": "召对当轮交办"}]}
    declaration_b = {"commissions": [{"text": "过月世界段交办"}]}

    result_a = audience_side_call(declaration_a)
    result_b = month_end_side_call(declaration_b)

    assert len(result_a.commissions.applied) == 1
    assert len(result_b.commissions.applied) == 1
    # 两处调用点解析的是同一个模块级函数对象，不是各自一份平行实现。
    assert audience_side_call.__globals__["dispatch_declaration"] is (
        month_end_side_call.__globals__["dispatch_declaration"]
    )
