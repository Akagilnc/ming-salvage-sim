"""#493 大臣荐人：网络/见闻裁切与采纳后的可恢复荐人事件。"""

import json

from ming_sim.models import Character
from ming_sim.tools import build_minister_tools


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


def test_minister_recommend_tool_preassembles_two_candidate_types(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩"))
    tools = {tool.__name__: tool for tool in build_minister_tools(
        minister, type("Context", (), {"db": db, "state": state})()
    )}
    listing = tools["list_recommendable_persons"]()
    assert "起复" in listing
    assert "破格差遣" in listing

