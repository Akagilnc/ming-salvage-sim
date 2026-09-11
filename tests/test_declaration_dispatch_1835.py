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


def test_promise_referencing_action_id_belonging_to_another_night_is_rejected(game):
    """AC3 的引用不存在实体拒收，对「id 真实存在但不属本声明所在夜」同样成立
    （ADR 0155：转译只认「本夜暂存清单」）——不能因为 id 恰巧撞上另一夜真实
    存在的暂存动作就误批它。"""
    db, state, _ = game
    minister = _minister(db)
    other_night_id = 987654321
    staged_id = db.stage_pending_action(
        int(state.turn), "directive", "拟旨", minister, {"text": "另一夜的暂存"},
    )
    db.conn.execute(
        "UPDATE pending_actions SET night_id=? WHERE id=?", (other_night_id, staged_id),
    )
    db.conn.commit()

    declaration = {"promises": [{"action_id": staged_id, "decision": "应允"}]}
    result = dispatch_declaration(
        db, state, declaration, minister_name=minister, night_id=0,
    )

    assert result.promises.applied == []
    assert len(result.promises.rejected) == 1
    assert result.promises.rejected[0].category == "missing_ref"
    row = db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()
    assert row["night_approved"] == 0


def test_on_scene_person_status_change_lands_and_rejects_nonexistent_person(game):
    db, state, _ = game
    minister = _minister(db)

    declaration = {
        "on_scene_facts": [
            {"name": minister, "动作": "处置", "status": "imprisoned", "reason": "下狱待勘"},
            {"name": "子虚乌有之人", "动作": "处置", "status": "dead", "reason": "凭空捏造"},
        ],
    }
    result = dispatch_declaration(db, state, declaration, minister_name=minister)

    assert len(result.on_scene_facts.applied) == 1
    assert len(result.on_scene_facts.rejected) == 1
    status, _ = db.get_character_status(minister)
    assert status == "imprisoned"


def test_presence_enter_and_exit_land_on_night_ledger_no_night_context_rejects(game):
    db, state, content = game
    minister = _minister(db)
    from ming_sim.audience_night import open_night

    night = open_night(db, state)
    night_id = int(night["id"])

    declaration = {
        "presence": [
            {"person_name": minister, "effect": "enter"},
            {"person_name": minister, "effect": "exit"},
        ],
    }
    result = dispatch_declaration(db, state, declaration, night_id=night_id)
    assert len(result.presence.applied) == 2
    assert result.presence.rejected == []

    no_night_result = dispatch_declaration(db, state, declaration, night_id=0)
    assert no_night_result.presence.applied == []
    assert len(no_night_result.presence.rejected) == 2


def test_scene_fact_speaker_segment_lands_with_audibility_and_bad_audibility_is_rejected(game):
    db, state, _ = game
    minister = _minister(db)
    from ming_sim.audience_night import open_night

    night = open_night(db, state)
    night_id = int(night["id"])

    declaration = {
        "scene_facts": [
            {"body": "臣领旨。", "audibility": "殿上公开", "person_names": [minister]},
            {"body": "低声私语", "audibility": "非法可闻性"},
        ],
    }
    result = dispatch_declaration(db, state, declaration, night_id=night_id)
    assert len(result.scene_facts.applied) == 1
    assert len(result.scene_facts.rejected) == 1


def test_edge_event_lands_and_rejects_unknown_kind(game):
    db, state, _ = game
    ministers = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 2"
    ).fetchall()
    assert len(ministers) == 2
    a, b = str(ministers[0]["name"]), str(ministers[1]["name"])

    declaration = {
        "edge_events": [
            {"source": a, "target": b, "event_kind": "撑腰", "context": "当殿举荐"},
            {"source": a, "target": b, "event_kind": "不存在的类目", "context": "…"},
        ],
    }
    result = dispatch_declaration(db, state, declaration)
    assert len(result.edge_events.applied) == 1
    assert len(result.edge_events.rejected) == 1
    assert result.edge_events.rejected[0].category == "hallucinated_id"


def test_protagonist_lands_and_rejects_nonexistent_person(game):
    db, state, _ = game
    minister = _minister(db)

    ok = dispatch_declaration(db, state, {"protagonist": {"person_name": minister}})
    assert ok.protagonist.applied == [{"person_name": minister}]

    bad = dispatch_declaration(db, state, {"protagonist": {"person_name": "子虚乌有之人"}})
    assert bad.protagonist.applied == []
    assert len(bad.protagonist.rejected) == 1
