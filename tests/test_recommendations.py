from ming_sim.recommendations import lookup_recommendation_candidate
from ming_sim.recommendations import validate_recommendation_snapshot
"""#493 大臣荐人：账上事实可荐与快照校验（#1931 去派系／见闻闸、删整池接口）。

经生产 lookup / validate 接缝；不再保活 list_recommendation_candidates。
"""


def test_future_debut_is_not_recommendable_by_facts(game):
    db, state, content = game
    recommender = next(c for c in content.characters.values() if c.office_type == "兵部")
    future = next(c for c in content.characters.values()
                  if c.name != recommender.name
                  and c.office_type not in ("后宫", "宗藩"))
    db.conn.execute(
        "UPDATE characters SET status='offstage', office='', debut_year=?, debut_month=1 "
        "WHERE name=?",
        (state.year + 1, future.name),
    )
    db.conn.commit()

    assert lookup_recommendation_candidate(
        db, state, future.name, recommender=recommender.name,
    ) is None
    assert not validate_recommendation_snapshot(
        db, state, recommender.name,
        {"name": future.name, "candidate_kind": "荐起复", "basis": "",
         "status": "offstage", "office": "", "faction": future.faction},
    )


def test_displaced_holder_stays_recovery_type_through_validate_and_restore(game):
    db, state, content = game
    recommender = next(c for c in content.characters.values()
                       if c.office_type not in ("后宫", "宗藩"))
    candidate = next(c for c in content.characters.values()
                     if c.name != recommender.name
                     and c.office_type not in ("后宫", "宗藩"))
    db.conn.execute(
        "UPDATE characters SET status='active', office='听用候铨', reason_code='被顶替' WHERE name=?",
        (candidate.name,),
    )
    db.conn.commit()

    row = lookup_recommendation_candidate(
        db, state, candidate.name, recommender=recommender.name,
    )
    assert row is not None
    assert row["candidate_kind"] == "荐起复"
    assert validate_recommendation_snapshot(db, state, recommender.name, row)

    restored = db.load_state()
    restored_row = lookup_recommendation_candidate(
        db, restored, candidate.name, recommender=recommender.name,
    )
    assert restored_row is not None
    assert restored_row["candidate_kind"] == "荐起复"
    assert validate_recommendation_snapshot(db, restored, recommender.name, row)


def test_hearing_title_without_displacement_reason_is_not_talent_pool_candidate(game):
    """ADR 0009 人才池 active 分支须同时满足 office 与被顶替缘由。"""
    db, state, content = game
    recommender = next(c for c in content.characters.values()
                       if c.office_type not in ("后宫", "宗藩"))
    candidate = next(c for c in content.characters.values()
                     if c.name != recommender.name
                     and c.office_type not in ("后宫", "宗藩"))
    db.conn.execute(
        "UPDATE characters SET status='active', office='听用候铨', reason_code='登场' WHERE name=?",
        (candidate.name,),
    )
    db.conn.commit()

    row = lookup_recommendation_candidate(
        db, state, candidate.name, recommender=recommender.name,
    )
    assert row is not None
    assert row["candidate_kind"] == "荐在职"


def test_off_ledger_recommender_fails_snapshot_validate(game):
    """任命前快照与受理共用荐者在册判断。"""
    db, state, content = game
    candidate = next(c for c in content.characters.values()
                     if c.office_type not in ("后宫", "宗藩"))
    row = lookup_recommendation_candidate(db, state, candidate.name)
    assert row is not None
    assert not validate_recommendation_snapshot(db, state, "账外荐者", row)
