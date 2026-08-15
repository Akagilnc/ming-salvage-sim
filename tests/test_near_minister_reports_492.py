"""#492 督抚官缺与近臣回奏的外部 seam。

#1185：不绑定仅测用 result_kind；经 build_return_report / persist_return_report
真实出口断言 source/statement 行为与域 reader 复用。来源元数据集中一条 tracer。
"""

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
        row = next(
            row for row in db.list_office_vacancies() if row["office_title"] == "陕西巡抚"
        )
        assert row["holder_name"] == "胡廷宴"


def test_return_report_source_metadata_contract(game):
    """来源元数据集中 tracer：inquiry 官缺/域 reader、派生规则、unsupported。"""
    db, state, _content = game

    office = build_return_report(db, "陕西巡抚可有？")
    assert office["source_kind"] == "inquiry"
    assert office["source_ref"] == "吏部查访"
    assert "result_kind" not in office

    arrears = build_return_report(db, "各镇欠饷如何？")
    assert arrears["source_kind"] == "inquiry"
    assert arrears["source_ref"] == "查访/armies"

    bandits = build_return_report(db, "流寇势如何？")
    assert bandits["source_kind"] == "inquiry"
    assert bandits["source_ref"] == "查访/powers"

    assert source_kind_for_query("军情如何？") == "firsthand"
    forced = build_return_report(db, "军情如何？", source_ref="伪造来源")
    assert forced["source_kind"] == "inquiry"
    assert forced["source_ref"] == "查访/powers"
    assert "伪造来源" not in forced["source_ref"]

    minister = next(iter(db.content.characters))
    unsupported = persist_return_report(db, state, minister, "请查访宫中流言真假。")
    assert unsupported["source_kind"] == "unsupported"
    assert "result_kind" not in unsupported


def test_office_report_answers_authorized_seeds_and_returns_unknown_elsewhere(game):
    db, _state, _content = game
    authorized = {"陕西巡抚", "三边总督"}
    vacancy_titles = {row["office_title"] for row in db.list_office_vacancies()}
    assert authorized <= vacancy_titles
    known = []
    for title in authorized:
        report = build_return_report(db, f"{title}可有？")
        assert title in report["statement"]
        row = next(r for r in db.list_office_vacancies() if r["office_title"] == title)
        assert row["holder_name"] is None
        known.append(report["statement"])
    # 两个不同未知官缺 → 同一非空 fallback（空串不得混过）
    u1 = build_return_report(db, "两广总督可有？")
    u2 = build_return_report(db, "四川巡抚可有？")
    assert u1["statement"] and u1["statement"] == u2["statement"]
    assert "两广总督" not in u1["statement"] and "四川巡抚" not in u1["statement"]
    assert all(t not in u1["statement"] for t in authorized)
    assert all(u1["statement"] != k for k in known)


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
        for title in vacant_titles:
            assert title in report["statement"]


def test_domain_inquiry_forwards_real_qualitative_readers(game):
    """域 reader 委派：包装原始 bound reader——真调用真返回 + 断言调用/参数。"""
    db, _state, _content = game
    army_calls, power_calls = [], []
    real_army, real_power = db.army_report, db.power_report

    def wrap_army(*a, **k):
        army_calls.append((a, dict(k)))
        return real_army(*a, **k)

    def wrap_power(*a, **k):
        power_calls.append((a, dict(k)))
        return real_power(*a, **k)

    db.army_report, db.power_report = wrap_army, wrap_power  # type: ignore[method-assign]
    arrears = build_return_report(db, "各镇欠饷如何？")
    bandits = build_return_report(db, "流寇势如何？")
    assert len(army_calls) == 1 and army_calls[0][1].get("limit") == 10
    exp_army = str(real_army(limit=10) or "")
    assert arrears["statement"] == exp_army and exp_army and any(c.isdigit() for c in exp_army)
    assert len(power_calls) == 1
    pk = power_calls[0][1]
    assert pk == {"exclude_self": True, "kinds": {"bandit", "bandits", "内乱"}, "audience": True}
    exp_power = str(real_power(**pk) or "")
    assert bandits["statement"] == exp_power and exp_power


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
    assert db.get_character_knowledge(state, first)["events"][-1]["source_id"].startswith(
        "near_minister:"
    )
    assert not any(
        item.get("source_id", "").startswith("near_minister:")
        for item in db.get_character_knowledge(state, second)["events"]
    )


def test_firsthand_witness_matrix(game):
    """firsthand 见闻：匹配/域不符/用词伪造/显式查访覆盖/取最新一条。"""
    db, state, _content = game
    minister = next(iter(db.content.characters))

    # 无见闻 → inquiry
    bare = persist_return_report(db, state, minister, "军情如何？")
    assert bare["source_kind"] == "inquiry"

    # 用词不能伪造 firsthand
    wording = persist_return_report(db, state, minister, "请据见闻说说军情。")
    assert wording["source_kind"] == "inquiry"

    # 无关域见闻不升格
    db.register_character_knowledge_source(
        state, [{"character_id": minister}], "witness", "河工见闻", "河道有报",
        source_id="witness:492:unrelated",
    )
    unrelated = persist_return_report(db, state, minister, "军情如何？")
    assert unrelated["source_kind"] == "inquiry"
    assert unrelated["source_ref"].startswith("查访/")

    # 匹配见闻 → firsthand + body
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
    matched = persist_return_report(db, state, minister, "军情如何？")
    assert matched["source_kind"] == "firsthand"
    assert matched["source_ref"] == "见闻/持久见闻"
    assert matched["statement"] == new_body
    assert matched["statement"] != old_body

    # 显式查访覆盖匹配见闻
    override = persist_return_report(db, state, minister, "请查访军情如何？")
    assert override["source_kind"] == "inquiry"
    assert override["source_ref"] == "查访/powers"


def test_unsupported_inquiry_is_not_persisted_as_false_office_report(game):
    db, state, _content = game
    minister = next(iter(db.content.characters))
    before = db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources"
    ).fetchone()[0]

    report = persist_return_report(db, state, minister, "请查访宫中流言真假。")

    after = db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources"
    ).fetchone()[0]
    assert report["source_kind"] == "unsupported"
    assert after == before


def test_bandit_inquiry_uses_shipped_inner_rebellion_kind(game):
    db, _state, _content = game

    report = build_return_report(db, "流寇势如何？")

    assert "势力未建档" not in report["statement"]
    unknown = build_return_report(db, "两广总督可有？")
    assert report["statement"] != unknown["statement"]
