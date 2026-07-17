"""#491 近臣读心内容：底账分轴、见闻边界与流水线 seam。"""

from dataclasses import replace
import inspect

import ming_sim.mindreading as mindreading
from ming_sim.mindreading import (
    build_mindreading_payload,
    build_scouting_precision_payload,
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


def test_only_the_unique_attendant_slot_can_mindread(game):
    _db, _state, content = game
    for name in ("王体乾", "曹化淳", "高起潜"):
        assert not is_inner_court_attendant(content.characters[name])


def test_inner_court_attendant_rejects_candidate_titles_that_only_contain_the_slot_name(game):
    """Only the current slot, not a similarly worded inner-court title, may mindread."""
    _db, _state, content = game
    candidate = replace(
        content.characters["王承恩"], office="御前近臣候补", office_type="司礼监"
    )

    assert not is_inner_court_attendant(candidate)


def test_mindreading_and_scouting_consume_the_same_precision_contract(game, monkeypatch):
    calls = []

    def shared_precision(target_factor, channel_factor):
        calls.append((target_factor, channel_factor))
        return "隐约"

    monkeypatch.setattr(mindreading, "intelligence_precision", shared_precision)
    db, state, content = game
    reading_payload = build_mindreading_payload(
        db,
        state,
        content.characters["王承恩"],
        content.characters["温体仁"],
        "臣愿担责。",
        target_factor=0.5,
        channel_factor=1.0,
    )
    scouting = build_scouting_precision_payload(0.5, 1.0)

    assert reading_payload["precision"] == "隐约"
    assert scouting == {"source": "锦衣卫查探预留", "precision": "隐约"}
    assert calls == [(0.5, 1.0), (0.5, 1.0)]


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

    def persist_target_ledger(character):
        db.conn.execute(
            "UPDATE characters SET identity=?, loyalty=?, seed_guilt=? WHERE name=?",
            (character.identity, character.loyalty, character.seed_guilt, character.name),
        )
        db.conn.commit()

    loyal_but_not_party = replace(base, identity=15, loyalty=92)
    party_but_not_loyal = replace(base, identity=92, loyalty=15)
    persist_target_ledger(loyal_but_not_party)
    first = build_mindreading_payload(db, state, reader, loyal_but_not_party, reply)
    persist_target_ledger(party_but_not_loyal)
    second = build_mindreading_payload(db, state, reader, party_but_not_loyal, reply)

    assert first["truths"]["潜台词"] != second["truths"]["潜台词"]
    assert "党账淡" in first["truths"]["潜台词"]
    assert "党账深" in second["truths"]["潜台词"]

    db.record_public_knowledge_event(state, "旧闻：有人替他遮掩", "内廷听闻此人旧日行止。")
    persist_target_ledger(loyal_but_not_party)
    with_heard = build_mindreading_payload(db, state, reader, loyal_but_not_party, reply)
    assert with_heard["truths"]["潜台词"] != first["truths"]["潜台词"]


def test_identity_loyalty_are_two_readable_axes(game):
    db, state, content = game
    reader = content.characters["王承恩"]
    base = content.characters["温体仁"]

    def persist_target_ledger(character):
        db.conn.execute(
            "UPDATE characters SET identity=?, loyalty=? WHERE name=?",
            (character.identity, character.loyalty, character.name),
        )
        db.conn.commit()

    loyal_but_not_party = replace(base, identity=15, loyalty=92)
    party_but_not_loyal = replace(base, identity=92, loyalty=15)
    persist_target_ledger(loyal_but_not_party)
    first = build_mindreading_payload(db, state, reader, loyal_but_not_party, "臣愿担责。")
    persist_target_ledger(party_but_not_loyal)
    second = build_mindreading_payload(db, state, reader, party_but_not_loyal, "臣愿担责。")

    assert first["truths"]["关系判断"] == "忠而不党"
    assert second["truths"]["关系判断"] == "党而不忠"


def test_mindreading_reads_current_target_ledger_after_persisted_changes(game):
    db, state, content = game
    reader = content.characters["王承恩"]
    target = content.characters["温体仁"]

    db.conn.execute(
        "UPDATE characters SET identity=?, loyalty=?, seed_guilt=? WHERE name=?",
        (92, 15, '{"crime":"合谋","severity":"重"}', target.name),
    )
    db.conn.commit()

    payload = build_mindreading_payload(db, state, reader, target, "臣愿担责。")

    assert payload["truths"]["关系判断"] == "党而不忠"
    assert "党色极深" in payload["truths"]["党账"]
    assert "合谋" in payload["truths"]["党账"]
    assert "未见深交" in payload["truths"]["君臣账"]


def test_party_ledger_names_db_faction_and_identity_split_for_wen_tiren(game):
    db, state, content = game
    reader = content.characters["王承恩"]
    target = content.characters["温体仁"]

    # The DB is the live ledger; the in-memory roster object may be stale.
    db.conn.execute(
        "UPDATE characters SET faction=?, identity=? WHERE name=?",
        ("皇党", 18, target.name),
    )
    db.conn.commit()

    payload = build_mindreading_payload(db, state, reader, target, "臣愿担责。")

    assert "名义党派：皇党" in payload["truths"]["党账"]
    assert "对本党的认同：几乎不染党色" in payload["truths"]["党账"]


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


def test_mindreading_payload_is_p4_safe_for_parenthesized_person_scores(game):
    db, state, content = game
    reader = content.characters["王承恩"]
    reply = "臣自陈忠诚（98），能力（12），愿为君分忧。"

    payload = build_mindreading_payload(
        db, state, reader, content.characters["温体仁"], reply
    )

    assert "忠诚（98）" not in str(payload)
    assert "能力（12）" not in str(payload)
    assert "已略去" in payload["reply_text"]


def test_mindreading_payload_keeps_reply_boundary_safe_for_ascii_axes(game):
    db, state, content = game
    reader = content.characters["王承恩"]
    reply = "臣自陈 loyalty=98、ability=12，愿为君分忧。"

    payload = build_mindreading_payload(
        db, state, reader, content.characters["温体仁"], reply
    )

    assert "loyalty=98" not in str(payload)
    assert "ability=12" not in str(payload)
    assert "已略去" in payload["reply_text"]


def test_mindreading_reply_text_rejects_approximate_raw_score_prose(game):
    """Player-visible mindreading reply_text must redline approximate score forms."""
    db, state, content = game
    reader = content.characters["王承恩"]
    reply = "此人忠诚接近40，士气不及20，军心跌破30，能力约70，补给在30左右。"

    payload = build_mindreading_payload(
        db, state, reader, content.characters["温体仁"], reply
    )

    assert "接近40" not in payload["reply_text"]
    assert "不及20" not in payload["reply_text"]
    assert "跌破30" not in payload["reply_text"]
    assert "约70" not in payload["reply_text"]
    assert "30左右" not in payload["reply_text"]
    assert "已略去" in payload["reply_text"]


def test_mindreading_reply_text_rejects_residual_approx_raw_score_prose(game):
    """Residual synonym/composition approx forms must redline on the same reply seam."""
    db, state, content = game
    reader = content.characters["王承恩"]
    reply = (
        "此人忠诚大概40，能力约莫70，军心跌破到30，"
        "补给大约在30左右，能力差不多是70，忠诚维持在40。"
    )

    payload = build_mindreading_payload(
        db, state, reader, content.characters["温体仁"], reply
    )

    for leak in (
        "大概40",
        "约莫70",
        "跌破到30",
        "大约在30左右",
        "差不多是70",
        "维持在40",
    ):
        assert leak not in payload["reply_text"], (leak, payload["reply_text"])
    assert "已略去" in payload["reply_text"]
    assert not any(ch.isdigit() for ch in payload["reply_text"])


def test_mindreading_reply_text_rejects_chinese_numeral_and_bare_dao_scores(game):
    """Chinese numerals and bare-到 peer of 至 must redline on mindreading reply_text."""
    db, state, content = game
    reader = content.characters["王承恩"]
    reply = (
        "此人能力约七十，忠诚只有三十，能力增加到50，"
        "能力涨到80，忠诚恢复到50，能力减少到20。"
    )

    payload = build_mindreading_payload(
        db, state, reader, content.characters["温体仁"], reply
    )

    for leak in (
        "约七十",
        "只有三十",
        "增加到50",
        "涨到80",
        "恢复到50",
        "减少到20",
        "七十",
        "三十",
    ):
        assert leak not in payload["reply_text"], (leak, payload["reply_text"])
    assert "已略去" in payload["reply_text"]
    assert not any(ch.isdigit() for ch in payload["reply_text"])
