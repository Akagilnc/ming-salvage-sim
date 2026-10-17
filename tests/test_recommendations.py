from ming_sim.recommendations import list_recommendation_candidates
from ming_sim.recommendations import lookup_recommendation_candidate
from ming_sim.recommendations import validate_recommendation_snapshot
"""#493 大臣荐人：账上事实可荐池与采纳后的可恢复荐人事件（#1931 去派系／见闻闸）。"""


def test_recommendation_candidates_include_cross_faction_by_facts(game):
    db, state, content = game
    recommender = next(c for c in content.characters.values() if c.office_type == "兵部")
    same_faction = next(c for c in content.characters.values()
                        if c.name != recommender.name and c.faction == recommender.faction
                        and c.office_type not in ("后宫", "宗藩"))
    cross = next(c for c in content.characters.values()
                  if c.name not in {recommender.name, same_faction.name}
                  and c.faction != recommender.faction
                  and c.office_type not in ("后宫", "宗藩"))
    db.conn.execute("UPDATE characters SET status='offstage', office='', reason_code='罢居' WHERE name=?", (same_faction.name,))
    db.conn.execute("UPDATE characters SET status='active', office='翰林院编修' WHERE name=?", (cross.name,))
    db.conn.commit()
    candidates = list_recommendation_candidates(db, state, recommender.name)
    names = {row["name"] for row in candidates}
    assert same_faction.name in names
    assert cross.name in names
    assert lookup_recommendation_candidate(
        db, state, cross.name, recommender=recommender.name,
    ) is not None


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

    names = {row["name"] for row in list_recommendation_candidates(db, state, recommender.name)}

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

    names = {row["name"] for row in list_recommendation_candidates(db, state, recommender.name)}

    assert future.name not in names
    assert lookup_recommendation_candidate(
        db, state, future.name, recommender=recommender.name,
    ) is None


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

    row = next(row for row in list_recommendation_candidates(db, state, recommender.name)
               if row["name"] == candidate.name)
    assert row["candidate_kind"] == "荐起复"
    assert validate_recommendation_snapshot(db, state, recommender.name, row)

    restored = db.load_state()
    restored_row = next(row for row in list_recommendation_candidates(db, restored, recommender.name)
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

    row = next(row for row in list_recommendation_candidates(db, state, recommender.name)
               if row["name"] == candidate.name)

    assert row["candidate_kind"] == "荐在职"
