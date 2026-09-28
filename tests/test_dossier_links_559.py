
import pytest

from ming_sim.session import GameSession
from ming_sim.skills import bind_content as bind_skills_content
from tests.dossier_test_helpers import TYPED_COVERT_EXTRACT, TYPED_COVERT_TASK, rejected_verdict as _rejected_verdict
from tests.web_audience_test_doubles import HallAdmissionSessionMixin
from web_app import WebGame
from tests.dossier_test_helpers import create_test_secret_order


def _make_dossier(db, state, text):
    return db.create_decree_dossier(
        state,
        action_type="special_decree",
        decree_text=text,
        target_kind="policy",
        target_id=text,
    )


def test_one_protection_dossier_links_three_older_allocations_both_directions(game):
    db, state, _ = game
    targets = [_make_dossier(db, state, name) for name in ("辽东补饷", "宣大补饷", "东江补饷")]
    protection = _make_dossier(db, state, "密令护行三路饷银")

    db.add_dossier_links(
        protection,
        [{"target_dossier_id": target, "relation_type": "护卫", "note": "护送该路饷银"}
         for target in targets],
    )

    assert [row["target_dossier_id"] for row in db.list_dossier_links(protection)] == targets
    assert [db.list_dossier_links(target, direction="incoming")[0]["source_dossier_id"]
            for target in targets] == [protection] * 3
    assert all("status" not in row for row in db.list_dossier_links(protection))


def test_only_confirmed_narrowed_references_are_persisted(game):
    db, state, _ = game
    liaodong = _make_dossier(db, state, "辽东补饷")
    xuanda = _make_dossier(db, state, "宣大补饷")
    protection = _make_dossier(db, state, "只确认护卫辽东")

    db.add_dossier_links(
        protection,
        [{"target_dossier_id": liaodong, "relation_type": "护卫", "note": "确认只护辽东"}],
    )

    assert [row["target_dossier_id"] for row in db.list_dossier_links(protection)] == [liaodong]
    assert db.list_dossier_links(xuanda, direction="incoming") == []












def test_reference_candidates_hide_other_ministers_secret_dossiers(game):
    db, state, _ = game
    draft_id = _make_dossier(db, state, "尚未明发饷案")
    public_id = _make_dossier(db, state, "公开饷案")
    db.record_dossier_decision(public_id, "promulgated")
    other_order = create_test_secret_order(db, state, "卢象升", "密查", "不可外泄", [])
    other_secret = db.get_dossier_for_secret_order(other_order)

    visible = db.list_referenceable_dossiers("孙承宗", state.turn)

    visible_ids = {row["id"] for row in visible}
    assert public_id in visible_ids
    assert draft_id not in visible_ids
    assert other_secret["id"] not in visible_ids
    assert other_secret["id"] in {
        row["id"] for row in db.list_referenceable_dossiers("卢象升", state.turn)
    }


def test_reference_candidates_obey_canonical_disclosure_blacklist(game):
    from ming_sim.knowledge import knowledge_row_visible_to

    db, state, _ = game
    order_id = create_test_secret_order(db, state, "卢象升", "密查辽饷", "不可外泄", [])
    dossier = db.get_dossier_for_secret_order(order_id)
    source_id = f"secret_order_disclosure:{order_id}:test"
    db.record_public_knowledge_event(
        state, "密查辽饷已披露", source_id=source_id, excluded_names=["孙承宗"])
    event = db.conn.execute(
        "SELECT * FROM character_knowledge_events WHERE source_id=?", (source_id,)
    ).fetchone()

    assert knowledge_row_visible_to(db, event, "孙承宗") is False
    assert dossier["id"] not in {
        row["id"] for row in db.list_referenceable_dossiers("孙承宗", state.turn)
    }


def test_confirmed_secret_order_materializes_links_through_pending_commit(game):
    db, state, _ = game
    targets = [_make_dossier(db, state, name) for name in ("辽东补饷", "宣大补饷", "东江补饷")]
    action_id = db.stage_pending_action(
        state.turn, "secret_order", "新建", "孙承宗",
        {"title": "护行三路饷银", "content": "密护三路饷银", "assignee": "孙承宗",
         "covert_task": TYPED_COVERT_TASK,
         "dossier_links": [
             {"target_dossier_id": target, "relation_type": "护卫", "note": "护送该路饷银"}
             for target in targets
         ]},
    )

    applied = db.commit_pending_actions(state, action_ids=[action_id])

    assert [row["id"] for row in applied] == [action_id]
    order = db.list_secret_orders(minister_name="孙承宗")[0]
    dossier = db.get_dossier_for_secret_order(order["id"])
    assert [row["target_dossier_id"] for row in db.list_dossier_links(dossier["id"])] == targets


def test_unknown_target_in_pending_commit_is_rolled_back_and_durably_audited(game):
    db, state, _ = game
    before_orders = len(db.list_secret_orders())
    action_id = db.stage_pending_action(
        state.turn, "secret_order", "新建", "孙承宗",
        {"title": "护行密令", "content": "护送旧案", "assignee": "孙承宗",
         "covert_task": TYPED_COVERT_TASK,
         "dossier_links": [
             {"target_dossier_id": 999999, "relation_type": "护卫", "note": "护送"}
         ]},
    )

    assert db.commit_pending_actions(state, action_ids=[action_id]) == []

    assert len(db.list_secret_orders()) == before_orders
    assert db.list_pending_actions(state.turn, status="failed")[0]["id"] == action_id
    audit = db.list_dossier_link_rejections(pending_action_id=action_id)
    assert audit[-1]["target_dossier_id"] == 999999
    assert "指向不存在案卷" in audit[-1]["reason"]


def test_unknown_target_link_is_rejected_and_audited(game):
    db, state, _ = game
    source = _make_dossier(db, state, "护行密令")

    with pytest.raises(ValueError, match="指向不存在案卷"):
        db.add_dossier_links(
            source,
            [{"target_dossier_id": 999999, "relation_type": "护卫", "note": "护送"}],
        )

    assert db.list_dossier_links(source) == []
    audit = db.list_dossier_link_rejections(source)
    assert audit[-1]["target_dossier_id"] == 999999
    assert "指向不存在案卷" in audit[-1]["reason"]




def test_force_promulgated_rejected_dossier_is_referenceable(game):
    db, state, _ = game
    dossier_id = _make_dossier(db, state, "中旨强颁的旧旨")

    db.apply_dossier_verdicts(state, [_rejected_verdict(dossier_id)])
    db.apply_dossier_promulgation(state, dossier_id, "force_promulgated")

    dossier = db.get_decree_dossier(dossier_id)
    assert dossier["promulgation_decision"] == "rejected"
    assert dossier_id in {
        row["id"] for row in db.list_referenceable_dossiers("孙承宗", state.turn)
    }


def test_withdrawn_rejected_dossier_is_not_referenceable(game):
    db, state, _ = game
    dossier_id = _make_dossier(db, state, "收回的旧旨")
    db.record_dossier_decision(dossier_id, "rejected", reason="驳回")
    db.record_dossier_decision(dossier_id, "withdrawn", reason="收回")
    assert dossier_id not in {row["id"] for row in db.list_referenceable_dossiers("孙承宗", state.turn)}


def test_pending_rejection_does_not_follow_reused_rolled_back_source_id(game):
    db, state, _ = game
    action_id = db.stage_pending_action(
        state.turn, "secret_order", "新建", "孙承宗",
        {"title": "坏引用", "content": "坏引用", "assignee": "孙承宗",
         "covert_task": TYPED_COVERT_TASK, "dossier_links": [
            {"target_dossier_id": 999999, "relation_type": "护卫", "note": "护送"}]},
    )
    assert db.commit_pending_actions(state, action_ids=[action_id]) == []
    reused_id = _make_dossier(db, state, "后建案卷")
    assert db.list_dossier_link_rejections(reused_id) == []
    assert db.list_dossier_link_rejections(pending_action_id=action_id)
