"""#492 督抚官缺与近臣回奏的外部 seam。"""

import inspect

from ming_sim.intelligence import build_return_report, source_kind_for_query


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


def test_return_report_records_source_without_bare_values(game):
    db, _state, _content = game

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
    assert not any(char.isdigit() for value in report.values() for char in value)


def test_report_source_is_derived_from_query_not_caller_label(game):
    db, _state, _content = game

    report = build_return_report(db, "军情如何？", source_ref="伪造来源")

    assert source_kind_for_query("军情如何？") == "firsthand"
    assert report["source_kind"] == "firsthand"
    assert report["source_ref"] == "见闻/powers"
    assert "伪造来源" not in report["source_ref"]


def test_domain_reports_reuse_existing_qualitative_readers(game, monkeypatch):
    db, _state, _content = game
    calls = []
    monkeypatch.setattr(db, "army_report", lambda **kwargs: calls.append("army") or "军镇欠饷若干")
    monkeypatch.setattr(db, "power_report", lambda **kwargs: calls.append("power") or "流寇势弱")

    arrears = build_return_report(db, "各镇欠饷如何？")
    bandits = build_return_report(db, "流寇势如何？")

    assert calls == ["army", "power"]
    assert arrears["statement"] == "军镇欠饷若干"
    assert bandits["statement"] == "流寇势弱"


def test_return_report_interface_does_not_depend_on_minister_reply():
    signature = inspect.signature(build_return_report)
    assert "minister_reply" not in signature.parameters
    assert build_return_report.parallel_safe is True
    assert build_return_report.dependencies == frozenset()
