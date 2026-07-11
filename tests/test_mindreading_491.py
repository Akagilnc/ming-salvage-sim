"""#491 近臣读心内容：底账分轴、见闻边界与流水线 seam。"""

from dataclasses import replace
import inspect

from ming_sim.mindreading import (
    build_mindreading_payload,
    intelligence_precision,
    is_inner_court_attendant,
)


def test_reader_is_selected_by_inner_court_post_not_name(game):
    _db, _state, content = game
    wang = content.characters["王承恩"]
    assert is_inner_court_attendant(wang)

    renamed = replace(wang, name="随驾新内官", aliases=[])
    assert is_inner_court_attendant(renamed)
    office_only = replace(wang, name="御前近臣", office="御前近臣", office_type="待铨")
    assert is_inner_court_attendant(office_only)

    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    assert not is_inner_court_attendant(minister)


def test_precision_is_shared_and_target_factor_is_reserved_for_scouting():
    assert intelligence_precision(1.0, 1.0) == intelligence_precision(1.0, 1.0)
    assert intelligence_precision(0.5, 1.0) == "隐约"
    assert intelligence_precision(1.0, 0.5) == "隐约"
    assert intelligence_precision(1.0, 1.0) == "清晰"


def test_mindreading_uses_three_truth_sources_without_naked_values(game):
    db, state, content = game
    reader = content.characters["王承恩"]
    target = content.characters["温体仁"]

    payload = build_mindreading_payload(
        db,
        state,
        reader,
        target,
        minister_reply="臣口称奉公，字里却不断把责任推给同僚。",
    )

    assert payload["reader"] == "王承恩"
    assert payload["target"] == "温体仁"
    assert payload["precision"] == "清晰"
    assert payload["source"] == "见闻"
    assert payload["reply_text"] == "臣口称奉公，字里却不断把责任推给同僚。"
    assert payload["truths"]["党账"]
    assert payload["truths"]["君臣账"]
    assert payload["truths"]["潜台词"] != payload["reply_text"]
    assert "identity" not in str(payload)
    assert "seed_guilt" not in str(payload)
    assert str(target.identity) not in str(payload)
    assert str(target.loyalty) not in str(payload)


def test_same_reply_is_read_through_different_three_source_ledgers(game):
    db, state, content = game
    reader = content.characters["王承恩"]
    base = content.characters["温体仁"]
    reply = "臣愿担责。"

    loyal_but_not_party = replace(base, identity=15, loyalty=92)
    party_but_not_loyal = replace(base, identity=92, loyalty=15)
    first = build_mindreading_payload(db, state, reader, loyal_but_not_party, reply)
    second = build_mindreading_payload(db, state, reader, party_but_not_loyal, reply)

    assert first["truths"]["潜台词"] != second["truths"]["潜台词"]
    assert "党账淡" in first["truths"]["潜台词"]
    assert "党账深" in second["truths"]["潜台词"]

    db.record_public_knowledge_event(state, "旧闻：有人替他遮掩", "内廷听闻此人旧日行止。")
    with_heard = build_mindreading_payload(db, state, reader, loyal_but_not_party, reply)
    assert with_heard["truths"]["潜台词"] != first["truths"]["潜台词"]


def test_identity_loyalty_are_two_readable_axes(game):
    db, state, content = game
    reader = content.characters["王承恩"]
    base = content.characters["温体仁"]

    loyal_but_not_party = replace(base, identity=15, loyalty=92)
    party_but_not_loyal = replace(base, identity=92, loyalty=15)
    first = build_mindreading_payload(db, state, reader, loyal_but_not_party, "臣愿担责。")
    second = build_mindreading_payload(db, state, reader, party_but_not_loyal, "臣愿担责。")

    assert first["truths"]["关系判断"] == "忠而不党"
    assert second["truths"]["关系判断"] == "党而不忠"


def test_reply_is_an_explicit_pipeline_input():
    signature = inspect.signature(build_mindreading_payload)
    assert "minister_reply" in signature.parameters
    assert signature.parameters["minister_reply"].default is inspect.Parameter.empty


def test_reader_eligibility_uses_current_db_office_after_reassignment(game):
    db, state, content = game
    reader = content.characters["王承恩"]
    db.conn.execute(
        "UPDATE characters SET office='礼部尚书', office_type='礼部' WHERE name=?",
        (reader.name,),
    )
    db.conn.commit()

    try:
        build_mindreading_payload(db, state, reader, content.characters["温体仁"], "臣愿担责。")
    except ValueError as exc:
        assert "御前近臣" in str(exc)
    else:
        raise AssertionError("读心资格不能沿用任免前的内存职位")


def test_mindreading_event_title_and_body_are_p4_safe(game):
    db, state, content = game
    reader = content.characters["王承恩"]
    db.record_public_knowledge_event(
        state,
        "民心值：73",
        "忠诚评分98，内廷已知。",
    )

    payload = build_mindreading_payload(
        db, state, reader, content.characters["温体仁"], "臣愿担责。"
    )
    heard = str(payload["reader_context"]["heard"])
    assert "民心值：73" not in heard
    assert "忠诚评分98" not in heard
    assert "已略去" in heard


def test_mindreading_payload_is_p4_safe_when_reply_contains_raw_person_scores(game):
    db, state, content = game
    reader = content.characters["王承恩"]
    reply = "臣自陈忠诚=98，能力: 12，愿为君分忧。"

    payload = build_mindreading_payload(
        db, state, reader, content.characters["温体仁"], reply
    )

    rendered = str(payload)
    assert "忠诚=98" not in rendered
    assert "能力: 12" not in rendered
    assert "已略去" in payload["reply_text"]
