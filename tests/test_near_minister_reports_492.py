"""#492 督抚官缺与近臣回奏的外部 seam。"""

import inspect

from ming_sim.intelligence import build_return_report, persist_return_report, source_kind_for_query


def test_frontier_vacancies_are_seeded_and_restore_from_characters(game):
    db, _state, content = game

    vacancies = {row["office_title"]: row for row in db.list_office_vacancies()}

    assert {"陕西巡抚", "三边总督"} <= vacancies.keys()
    assert vacancies["陕西巡抚"]["holder_name"] is None
    assert vacancies["三边总督"]["holder_name"] is None

    db.conn.execute(
        "UPDATE characters SET office=?, office_type=?, status=? WHERE name=?",
        ("陕西巡抚", "督抚", "active", "胡廷宴"),
    )
    db.conn.commit()
    restored = db.list_office_vacancies()
    restored_row = next(row for row in restored if row["office_title"] == "陕西巡抚")
    assert restored_row["holder_name"] == "胡廷宴"


def test_vacancy_projection_recognises_acting_office_text(game):
    db, _state, _content = game
    for office in ("署理陕西巡抚", "陕西巡抚（署理）"):
        db.conn.execute(
            "UPDATE characters SET office=?, office_type='督抚', status='active' WHERE name='胡廷宴'",
            (office,),
        )
        db.conn.commit()
        row = next(row for row in db.list_office_vacancies() if row["office_title"] == "陕西巡抚")
        assert row["holder_name"] == "胡廷宴"


def test_office_report_answers_authorized_seeds_and_returns_unknown_elsewhere(game):
    db, _state, _content = game

    authorized = {"陕西巡抚", "三边总督"}
    vacancy_titles = {row["office_title"] for row in db.list_office_vacancies()}
    assert authorized <= vacancy_titles

    for title in authorized:
        report = build_return_report(db, f"{title}可有？")
        assert report["source_kind"] == "inquiry"
        assert report["source_ref"] == "吏部查访"
        assert title in report["statement"]
        row = next(r for r in db.list_office_vacancies() if r["office_title"] == title)
        assert row["holder_name"] is None

    # 未授权官缺：不在空缺集合；statement 不含该职衔与虚悬/在任结构事实
    unknown_title = "两广总督"
    assert unknown_title not in vacancy_titles
    unknown = build_return_report(db, f"{unknown_title}可有？")
    assert unknown["source_kind"] == "inquiry"
    assert unknown["source_ref"] == "吏部查访"
    assert unknown_title not in unknown["statement"]
    assert "当前虚悬" not in unknown["statement"]
    assert "现由" not in unknown["statement"]
    assert not any(title in unknown["statement"] for title in authorized)


def test_generic_office_queries_return_current_vacancies(game):
    db, _state, _content = game

    vacant_titles = {
        row["office_title"]
        for row in db.list_office_vacancies()
        if not row.get("holder_name")
    }
    assert {"陕西巡抚", "三边总督"} <= vacant_titles

    for query in ("督抚官缺如何？", "有哪些官缺？"):
        report = build_return_report(db, query)
        assert report["source_kind"] == "inquiry"
        assert report["source_ref"] == "吏部查访"
        # 结构化：当前空缺集合的 office_title 均出现在回奏事实中
        for title in vacant_titles:
            assert title in report["statement"]


def test_return_report_records_source_and_keeps_countable_facts(game, monkeypatch):
    db, _state, _content = game
    # countable facts 由域 reader 整包透传，不在回奏层重写/丢弃
    countable_army = "辽镇兵额12000，欠饷25月，士气低迷"
    monkeypatch.setattr(db, "army_report", lambda **_: countable_army)

    report = build_return_report(
        db,
        "陕西巡抚可有？",
        source_kind="inquiry",
        source_ref="吏部查访",
    )

    assert report["source_kind"] == "inquiry"
    assert report["source_ref"] == "吏部查访"
    assert report["statement"]
    assert "陕西巡抚" in report["statement"]
    assert all(isinstance(value, str) for value in report.values())
    arrears = build_return_report(db, "各镇欠饷如何？")
    assert arrears["source_kind"] == "inquiry"
    assert arrears["source_ref"] == "查访/armies"
    # 可数事实不丢：statement 即域 reader 输出（含兵力/欠饷月数等 countable）
    assert arrears["statement"] == countable_army


def test_report_source_is_derived_from_query_not_caller_label(game):
    db, _state, _content = game

    report = build_return_report(db, "军情如何？", source_ref="伪造来源")

    assert source_kind_for_query("军情如何？") == "firsthand"
    assert report["source_kind"] == "inquiry"
    assert report["source_ref"] == "查访/powers"
    assert "伪造来源" not in report["source_ref"]


def test_domain_reports_reuse_existing_qualitative_readers(game, monkeypatch):
    db, _state, _content = game
    calls = []
    army_reader_out = "军镇欠饷若干"
    power_reader_out = "流寇势弱"
    monkeypatch.setattr(db, "army_report", lambda **kwargs: calls.append("army") or army_reader_out)
    monkeypatch.setattr(db, "power_report", lambda **kwargs: calls.append("power") or power_reader_out)

    arrears = build_return_report(db, "各镇欠饷如何？")
    bandits = build_return_report(db, "流寇势如何？")

    # 复用既有定性读者：调用序 + source_kind/source_ref 域映射 + statement 同源
    assert calls == ["army", "power"]
    assert arrears["source_kind"] == "inquiry"
    assert arrears["source_ref"] == "查访/armies"
    assert arrears["statement"] == army_reader_out
    assert bandits["source_kind"] == "inquiry"
    assert bandits["source_ref"] == "查访/powers"
    assert bandits["statement"] == power_reader_out


def test_return_report_interface_does_not_depend_on_minister_reply():
    signature = inspect.signature(build_return_report)
    assert "minister_reply" not in signature.parameters
    assert build_return_report.parallel_safe is True
    assert build_return_report.dependencies == frozenset()


def test_production_report_is_durable_and_scoped_to_the_questioned_minister(game):
    db, state, _content = game
    first = next(iter(db.content.characters))
    second = next(name for name in db.content.characters if name != first)

    report = persist_return_report(db, state, first, "军情如何？")

    assert report["source_kind"] == "inquiry"
    assert db.get_character_knowledge(state, first)["events"][-1]["source_id"].startswith("near_minister:")
    assert not any(
        item.get("source_id", "").startswith("near_minister:")
        for item in db.get_character_knowledge(state, second)["events"]
    )


def test_firsthand_requires_a_persisted_witness_record(game):
    db, state, _content = game
    minister = next(iter(db.content.characters))
    db.register_character_knowledge_source(
        state, [{"character_id": minister}], "witness", "边地见闻", "边地有报",
        source_id="witness:492:test",
    )

    report = persist_return_report(db, state, minister, "军情如何？")

    assert report["source_kind"] == "firsthand"


def test_firsthand_witness_must_match_questioned_domain(game):
    db, state, _content = game
    minister = next(iter(db.content.characters))
    db.register_character_knowledge_source(
        state, [{"character_id": minister}], "witness", "河工见闻", "河道有报",
        source_id="witness:492:unrelated",
    )

    report = persist_return_report(db, state, minister, "军情如何？")

    assert report["source_kind"] == "inquiry"
    assert report["source_ref"].startswith("查访/")


def test_firsthand_report_uses_the_matching_witness_body(game):
    db, state, _content = game
    minister = next(iter(db.content.characters))
    witness_body = "辽东有报"
    source_id = "witness:492:matching"
    db.register_character_knowledge_source(
        state, [{"character_id": minister}], "witness", "边地见闻", witness_body,
        source_id=source_id,
    )

    report = persist_return_report(db, state, minister, "军情如何？")

    assert report["source_kind"] == "firsthand"
    assert report["source_ref"] == "见闻/持久见闻"
    # statement 与匹配见闻正文结构化同源
    knowledge = db.get_character_knowledge(state, minister)
    witness_bodies = [
        str(item.get("body") or "")
        for item in [*(knowledge.get("events") or []), *(knowledge.get("public_events") or [])]
        if str(item.get("kind") or "") in {"witness", "scout", "firsthand"}
        or str(item.get("source_id") or "") == source_id
    ]
    assert witness_body in witness_bodies
    assert report["statement"] == witness_body
    assert report["statement"] in witness_bodies


def test_question_wording_cannot_create_firsthand_provenance(game):
    db, state, _content = game
    minister = next(iter(db.content.characters))

    report = persist_return_report(db, state, minister, "请据见闻说说军情。")

    assert report["source_kind"] == "inquiry"


def test_explicit_inquiry_overrides_matching_firsthand_witness(game):
    db, state, _content = game
    minister = next(iter(db.content.characters))
    db.register_character_knowledge_source(
        state, [{"character_id": minister}], "witness", "边地见闻", "辽东有报",
        source_id="witness:492:explicit-inquiry",
    )

    report = persist_return_report(db, state, minister, "请查访军情如何？")

    assert report["source_kind"] == "inquiry"
    assert report["source_ref"] == "查访/powers"


def test_unsupported_inquiry_is_not_persisted_as_false_office_report(game):
    db, state, _content = game
    minister = next(iter(db.content.characters))
    before = db.conn.execute("SELECT COUNT(*) FROM character_knowledge_sources").fetchone()[0]

    report = persist_return_report(db, state, minister, "请查访宫中流言真假。")

    after = db.conn.execute("SELECT COUNT(*) FROM character_knowledge_sources").fetchone()[0]
    assert report["source_kind"] == "unsupported"
    assert after == before


def test_bandit_inquiry_uses_shipped_inner_rebellion_kind(game):
    db, _state, _content = game

    report = build_return_report(db, "流寇势如何？")

    assert "势力未建档" not in report["statement"]
    assert "流寇" in report["statement"]


def test_firsthand_report_prefers_newest_matching_durable_witness(game):
    db, state, _content = game
    minister = next(iter(db.content.characters))
    old_body, new_body = "辽东旧报", "辽东新报"
    db.register_character_knowledge_source(
        state, [{"character_id": minister}], "witness", "边地见闻", old_body,
        source_id="witness:old",
    )
    state.turn += 1
    db.register_character_knowledge_source(
        state, [{"character_id": minister}], "witness", "边地见闻", new_body,
        source_id="witness:new",
    )

    report = persist_return_report(db, state, minister, "军情如何？")
    assert report["source_kind"] == "firsthand"
    assert report["source_ref"] == "见闻/持久见闻"
    # 耐久见闻序：turn 最新者优先
    knowledge = db.get_character_knowledge(state, minister)
    witnesses = [
        item
        for item in [*(knowledge.get("events") or []), *(knowledge.get("public_events") or [])]
        if str(item.get("kind") or "") in {"witness", "scout", "firsthand"}
        and str(item.get("body") or "").strip()
    ]
    newest = max(witnesses, key=lambda item: int(item.get("turn") or 0))
    assert newest["body"] == new_body
    assert report["statement"] == newest["body"]
    assert report["statement"] != old_body
