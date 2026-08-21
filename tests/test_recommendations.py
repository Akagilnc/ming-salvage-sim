"""#493 大臣荐人：网络/见闻裁切与采纳后的可恢复荐人事件。"""

import json

import pytest

from ming_sim.models import Character
from ming_sim.recommendations import build_recommendation_brief, validate_recommendation_snapshot
from ming_sim.tools import build_minister_tools
from tests.dossier_test_helpers import promulgate_proposed_appointments


def test_recommendation_candidates_are_limited_to_faction_or_character_knowledge(game):
    db, state, content = game
    recommender = next(c for c in content.characters.values() if c.office_type == "兵部")
    same_faction = next(c for c in content.characters.values()
                        if c.name != recommender.name and c.faction == recommender.faction
                        and c.office_type not in ("后宫", "宗藩"))
    hidden = next(c for c in content.characters.values()
                  if c.name not in {recommender.name, same_faction.name}
                  and c.faction != recommender.faction
                  and c.office_type not in ("后宫", "宗藩"))
    db.conn.execute("UPDATE characters SET status='offstage', office='', reason_code='罢居' WHERE name=?", (same_faction.name,))
    db.conn.execute("UPDATE characters SET status='active', office='翰林院编修' WHERE name=?", (hidden.name,))
    db.conn.commit()
    candidates = db.list_recommendation_candidates(state, recommender.name)
    names = {row["name"] for row in candidates}
    assert same_faction.name in names
    assert hidden.name not in names


def test_low_identity_recommender_can_see_high_identity_same_faction_candidate(game):
    db, state, content = game
    recommender = next(c for c in content.characters.values() if c.office_type == "兵部")
    candidate = next(c for c in content.characters.values()
                     if c.name != recommender.name
                     and c.faction == recommender.faction
                     and c.office_type not in ("后宫", "宗藩"))
    db.conn.execute("UPDATE characters SET identity=5 WHERE name=?", (recommender.name,))
    db.conn.execute(
        "UPDATE characters SET identity=95, status='offstage', office='' WHERE name=?",
        (candidate.name,),
    )
    db.conn.commit()

    names = {row["name"] for row in db.list_recommendation_candidates(state, recommender.name)}

    assert candidate.name in names


def test_private_and_public_structured_hearing_exposes_cross_faction_candidate(game):
    db, state, content = game
    recommender = next(c for c in content.characters.values() if c.office_type == "兵部")
    candidates = [c for c in content.characters.values()
                  if c.name != recommender.name
                  and c.faction != recommender.faction
                  and c.office_type not in ("后宫", "宗藩")][:2]
    private_candidate, public_candidate = candidates
    db.conn.execute(
        "UPDATE characters SET status='offstage', office='', reason_code='罢居' "
        "WHERE name IN (?, ?)",
        (private_candidate.name, public_candidate.name),
    )
    db.conn.commit()

    db.register_character_knowledge_source(
        state,
        [{"character_id": recommender.name}, {"character_id": private_candidate.name}],
        "audience",
        "私下议事",
        "大臣亲历",
        source_id="test:private-hearing",
    )
    db.register_character_knowledge_source(
        state,
        [{"character_id": public_candidate.name}],
        "public",
        "公开议事",
        "邸报所载",
        source_id="test:public-hearing",
    )

    names = {row["name"] for row in db.list_recommendation_candidates(state, recommender.name)}

    assert private_candidate.name in names
    assert public_candidate.name in names


def test_public_structured_hearing_exclusion_hides_cross_faction_candidate(game):
    db, state, content = game
    recommender = next(c for c in content.characters.values() if c.office_type == "兵部")
    candidate = next(c for c in content.characters.values()
                     if c.name != recommender.name
                     and c.faction != recommender.faction
                     and c.office_type not in ("后宫", "宗藩"))
    db.conn.execute(
        "UPDATE characters SET status='offstage', office='', reason_code='罢居' WHERE name=?",
        (candidate.name,),
    )
    db.conn.commit()
    db.register_character_knowledge_source(
        state,
        [{"character_id": candidate.name}],
        "public",
        "公开议事",
        "邸报所载",
        source_id="test:excluded-public-hearing",
        excluded_names=[recommender.name],
    )

    names = {row["name"] for row in db.list_recommendation_candidates(state, recommender.name)}

    assert candidate.name not in names


@pytest.mark.parametrize("excluded_target", ["office_type", "office"])
def test_hearing_exclusion_hides_candidate_by_current_position(game, excluded_target):
    db, state, content = game
    recommender = next(c for c in content.characters.values() if c.office_type == "兵部")
    candidate = next(c for c in content.characters.values()
                     if c.name != recommender.name
                     and c.faction != recommender.faction
                     and c.office_type not in ("后宫", "宗藩"))
    db.conn.execute(
        "UPDATE characters SET status='offstage', office='候铨' WHERE name=?",
        (candidate.name,),
    )
    db.conn.commit()
    current = db.conn.execute(
        "SELECT office, office_type FROM characters WHERE name=?", (candidate.name,)
    ).fetchone()
    excluded_office = (
        current["office_type"] if excluded_target == "office_type" else current["office"]
    )
    db.register_character_knowledge_source(
        state,
        [{"character_id": recommender.name}, {"character_id": candidate.name}],
        "public",
        "公开议事",
        "邸报所载",
        source_id=f"test:excluded-{excluded_target}",
        excluded_targets={"offices": [excluded_office]},
    )

    names = {row["name"] for row in db.list_recommendation_candidates(state, recommender.name)}

    assert candidate.name not in names


@pytest.mark.parametrize("excluded_target", ["office_type", "office"])
def test_source_local_exclusion_preserves_same_faction_network_candidate(game, excluded_target):
    db, state, content = game
    recommender = next(c for c in content.characters.values() if c.office_type == "兵部")
    candidate = next(c for c in content.characters.values()
                     if c.name != recommender.name
                     and c.faction == recommender.faction
                     and c.office_type not in ("后宫", "宗藩"))
    db.conn.execute(
        "UPDATE characters SET status='offstage', office='候铨' WHERE name=?",
        (candidate.name,),
    )
    db.conn.commit()
    current = db.conn.execute(
        "SELECT office, office_type FROM characters WHERE name=?", (candidate.name,)
    ).fetchone()
    excluded_office = (
        current["office_type"] if excluded_target == "office_type" else current["office"]
    )
    db.register_character_knowledge_source(
        state,
        [{"character_id": recommender.name}, {"character_id": candidate.name}],
        "public",
        "公开议事",
        "邸报所载",
        source_id=f"test:same-faction-excluded-{excluded_target}",
        excluded_targets={"offices": [excluded_office]},
    )

    names = {row["name"] for row in db.list_recommendation_candidates(state, recommender.name)}

    assert candidate.name in names


def test_same_faction_future_debut_is_not_recommendable(game):
    db, state, content = game
    recommender = next(c for c in content.characters.values() if c.office_type == "兵部")
    future = next(c for c in content.characters.values()
                  if c.name != recommender.name and c.faction == recommender.faction
                  and c.office_type not in ("后宫", "宗藩"))
    db.conn.execute(
        "UPDATE characters SET status='offstage', office='', debut_year=?, debut_month=1 "
        "WHERE name=?",
        (state.year + 1, future.name),
    )
    db.conn.commit()

    names = {row["name"] for row in db.list_recommendation_candidates(state, recommender.name)}

    assert future.name not in names


def test_adopted_recommendation_is_an_auditable_event_after_restore(game):
    db, state, content = game
    recommender = next(c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩"))
    candidate = next(c for c in content.characters.values()
                    if c.name != recommender.name and c.faction == recommender.faction
                    and c.office_type not in ("后宫", "宗藩"))
    db.conn.execute("UPDATE characters SET status='offstage', office='', reason_code='罢居' WHERE name=?", (candidate.name,))
    db.conn.commit()
    rows = db.list_recommendation_candidates(state, recommender.name)
    row = next(row for row in rows if row["name"] == candidate.name)
    db.record_recommendation(state, recommender.name, row, "巡盐御史", "旧任有实绩，罢居后仍可起复")
    restored = db.load_state()
    events = db.list_recommendation_events(restored, recommender.name)
    assert events[0]["recommender"] == recommender.name
    assert events[0]["candidate"] == candidate.name
    assert events[0]["candidate_kind"] == "起复"
    assert events[0]["target_office"] == "巡盐御史"


def test_minister_tools_only_submit_recommendations(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩"))
    tools = {tool.__name__: tool for tool in build_minister_tools(
        minister, type("Context", (), {"db": db, "state": state})()
    )}
    assert "list_recommendable_persons" not in tools
    assert "recommend_person" in tools
    candidate = db.list_recommendation_candidates(state, minister.name)[0]

    payload = tools["recommend_person"](candidate["name"], "巡盐御史", "请予试任")

    assert payload.startswith("__pending_recommendation__")
    assert candidate["name"] in payload


def test_recommend_person_rejects_empty_reason(game):
    """#635：生产 tool 缺省/空白荐词必须当场拒，不得吐 pending 标记。"""
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩"))
    tools = {tool.__name__: tool for tool in build_minister_tools(
        minister, type("Context", (), {"db": db, "state": state})()
    )}
    candidate = db.list_recommendation_candidates(state, minister.name)[0]

    for reason in ("", "   ", None):
        result = tools["recommend_person"](candidate["name"], "巡盐御史", reason)
        assert not str(result).startswith("__pending_recommendation__")
        assert "荐词" in str(result)


def test_recommendation_appointment_preserves_kind_and_restores_both_types(game):
    db, state, content = game
    recommender = next(c for c in content.characters.values()
                       if c.office_type not in ("后宫", "宗藩"))
    candidates = db.list_recommendation_candidates(state, recommender.name)
    offstage = next(row for row in candidates if row["candidate_kind"] == "荐起复")
    active = next(row for row in candidates if row["candidate_kind"] == "荐在职")
    db.conn.execute(
        "UPDATE characters SET status='offstage', office='', reason_code='罢居' WHERE name=?",
        (offstage["name"],),
    )
    db.conn.commit()
    # The staged payload carries the original candidate snapshot; commit must
    # use it instead of reclassifying the candidate after appointment.
    for row, office in ((offstage, "巡盐御史"), (active, "河道总督")):
        action_id = db.stage_pending_action(
            state.turn,
            kind="office",
            action="任命",
            minister_name=recommender.name,
            target_id=None,
            payload={
                "name": row["name"], "office": office,
                "faction": row["faction"], "reason": "荐人采纳",
                "recommendation": {
                    "candidate": row,
                    "recommender": recommender.name,
                },
            },
        )
        result = db.commit_pending_actions(
            state, content=content, registry=None, action_ids=[action_id]
        )
        assert result and result[0]["id"] == action_id
        promulgate_proposed_appointments(db, state, content)

    restored = db.load_state()
    events = db.list_recommendation_events(restored, recommender.name)
    by_candidate = {event["candidate"]: event for event in events}
    assert by_candidate[offstage["name"]]["candidate_kind"] == "起复"
    assert by_candidate[active["name"]]["candidate_kind"] == "在职"


def test_listed_heard_for_selection_candidate_stays_recovery_type_through_context_and_restore(game):
    db, state, content = game
    recommender = next(c for c in content.characters.values()
                       if c.office_type not in ("后宫", "宗藩"))
    candidate = next(c for c in content.characters.values()
                     if c.name != recommender.name and c.faction == recommender.faction
                     and c.office_type not in ("后宫", "宗藩"))
    db.conn.execute(
        "UPDATE characters SET status='active', office='听用候铨', reason_code='被顶替' WHERE name=?",
        (candidate.name,),
    )
    db.conn.commit()

    row = next(row for row in db.list_recommendation_candidates(state, recommender.name)
               if row["name"] == candidate.name)
    assert row["candidate_kind"] == "荐起复"
    assert "荐起复" in build_recommendation_brief(db, state, recommender.name)
    assert validate_recommendation_snapshot(db, state, recommender.name, row)

    restored = db.load_state()
    restored_row = next(row for row in db.list_recommendation_candidates(restored, recommender.name)
                        if row["name"] == candidate.name)
    assert restored_row["candidate_kind"] == "荐起复"
    assert validate_recommendation_snapshot(db, restored, recommender.name, row)


def test_hearing_title_without_displacement_reason_is_not_talent_pool_candidate(game):
    """ADR 0009 人才池 active 分支须同时满足 office 与被顶替缘由。"""
    db, state, content = game
    recommender = next(c for c in content.characters.values()
                       if c.office_type not in ("后宫", "宗藩"))
    candidate = next(c for c in content.characters.values()
                     if c.name != recommender.name and c.faction == recommender.faction
                     and c.office_type not in ("后宫", "宗藩"))
    db.conn.execute(
        "UPDATE characters SET status='active', office='听用候铨', reason_code='登场' WHERE name=?",
        (candidate.name,),
    )
    db.conn.commit()

    row = next(row for row in db.list_recommendation_candidates(state, recommender.name)
               if row["name"] == candidate.name)

    assert row["candidate_kind"] == "荐在职"
