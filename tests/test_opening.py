"""Medium tests (local SQLite): opening data crosses Court without normalization."""

import json
import shutil
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel
from starlette.testclient import TestClient

from ming.web import create_app

from ming.__main__ import main
from ming.middle.court import Court

CONTENT = Path(__file__).parents[1] / "content"


def test_new_game_imports_complete_world_records_and_separates_identities(
    tmp_path: Path, steps, audit,
) -> None:
    with TestClient(create_app(tmp_path)) as client:
        save = client.post("/actions", json={"action": "new"}).json()["save"]
        visible = client.get("/records").json()["entities"]
    ledger = audit(tmp_path / save)
    entities = ledger["entities"]
    # Pinyin keys between content records become the Chinese name they key.
    names = {
        r["id"]: r["name"]
        for filename in ("regions", "powers")
        for r in json.loads((CONTENT / f"{filename}.json").read_text())[filename]
    }

    def canonical(record: dict[str, object]) -> dict[str, object]:
        return {
            k: record["name"]
            if k == "id" and "name" in record
            else names.get(v, v)
            if isinstance(v, str)
            else v
            for k, v in record.items() if k != "appointments"
        }

    for filename, collection in [
        ("characters", "characters"),
        ("characters", "factions"),
        ("regions", "regions"),
        ("buildings", "buildings"),
        ("armies", "armies"),
        ("powers", "powers"),
        ("classes", "classes"),
        ("relation_seed", "events"),
        ("relation_seed", "summaries"),
        ("opening", "accounts"),
        ("opening", "calendar"),
        ("opening", "world"),
        ("official_titles", "offices"),
        ("territories", "territories"),
        ("fiscal_config", "items"),
    ]:
        source = f"{filename}.json/{collection}"
        expected = json.loads((CONTENT / f"{filename}.json").read_text())[collection]
        assert [e["data"] for e in entities if e["source"] == source] == [
            canonical(r) for r in expected
        ]
    assert [e["data"] for e in entities if e["kind"] == "historical_event"] == json.loads(
        (CONTENT / "events.json").read_text()
    )
    dossiers = json.loads((CONTENT / "minister_dossiers.json").read_text())
    assert {e["key"]: e["data"] for e in entities if e["kind"] == "dossier"} == dossiers
    assert [e["key"] for e in entities if e["kind"] == "gazette"] == ["opening"]
    offices = {e["key"]: e["data"] for e in entities if e["kind"] == "office"}
    assert offices["巡抚"]["multiple"] is False
    assert offices["内阁大学士"]["multiple"] is True
    assert {e["kind"] for e in visible} == {"person", "calendar", "gazette"}
    shown = {e["key"]: e["data"] for e in visible if e["kind"] == "person"}
    assert shown.keys() == {e["key"] for e in entities if e["kind"] == "person"}
    visible_fields = {"name", "appointments", "location", "status"}
    assert all(set(data) <= visible_fields for data in shown.values())
    characters = {
        p["name"]: p
        for p in json.loads((CONTENT / "characters.json").read_text())["characters"]
    }
    for name in ["史可法", "徐光启", "黄道周", "练国事", "郭允厚"]:
        assert {k: v for k, v in shown[name].items() if k != "appointments"} == {
            k: v for k, v in canonical(characters[name]).items() if k in visible_fields
        }
        assert [{k: a[k] for k in ("office", "territory")} for a in shown[name]["appointments"]] == characters[name]["appointments"]
    assert shown["孙传庭"]["appointments"] == []
    assert shown["毕自严"]["appointments"] == []
    people = {e["key"]: e["data"] for e in entities if e["kind"] == "person"}
    assert people["毕自严"]["historical_office"] == {"office": "南京户部尚书", "territory": ""}
    assert people["孙传庭"]["historical_office"] == {"office": "吏部稽勋清吏司郎中", "territory": ""}
    territories = {e["key"] for e in entities if e["kind"] == "territory"}
    for person in people.values():
        if former := person.get("historical_office"):
            assert former["office"] in offices
            assert not former["territory"] or former["territory"] in territories
    assert all(shown[name]["appointments"] == [] for name in ("黄道周", "练国事", "何腾蛟", "瞿式耜", "钱龙锡", "刘鸿训", "李标"))
    assert shown["韩爌"]["location"] == "山西"
    assert shown["来宗道"]["appointments"] == [{"office": "礼部尚书", "territory": "", "holders": ["来宗道"]}]
    assert [e["data"]["holders"] for e in entities if e["kind"] == "incumbency" and e["data"]["office"] == "礼部尚书"] == [["来宗道"]]
    assert all({a["office"] for a in shown[name]["appointments"]} <= {"内阁大学士", "中极殿大学士"} for name in ("黄立极", "施凤来", "张瑞图", "李国普"))
    assert shown["曾樱"]["appointments"] == [{"office": "知府", "territory": "南直隶常州府", "holders": ["曾樱"]}]
    assert shown["卢象升"]["location"] == "北直隶 / 京师"
    assert shown["卢象升"]["appointments"] == [{"office": "知府", "territory": "北直隶大名府", "holders": ["卢象升"]}]
    assert not any({"office", "office_type", "office_region", "appointments"} & e["data"].keys() for e in entities if e["kind"] == "person")
    assert ledger["facts"] == []


def test_cli_new_games_never_overwrite_and_missing_game_is_not_created(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], steps
) -> None:
    args = ["new", "--directory", str(tmp_path)]
    main(args)
    first = json.loads(capsys.readouterr().out)
    main(["read", "--db", first["db"], "--identity", "audit"])
    saved = json.loads(capsys.readouterr().out)
    main(args)
    second = json.loads(capsys.readouterr().out)
    assert first["db"] != second["db"]
    main(["read", "--db", first["db"], "--identity", "audit"])
    after = json.loads(capsys.readouterr().out)
    assert after["entities"] == saved["entities"]
    assert after["facts"] == saved["facts"]
    assert len(after["entities"]) > len(first["entities"])
    main(
        ["month", "--db", first["db"], "--model", "test", "--translation-model", "test"]
    )
    month = json.loads(capsys.readouterr().out)
    assert month["date"]["month"] == 11
    main(["read", "--db", first["db"], "--identity", "audit", "--replay"])
    replay = json.loads(capsys.readouterr().out)
    assert (
        next(e["data"]["month"] for e in replay["entities"] if e["kind"] == "calendar")
        == 11
    )
    absent = tmp_path / "absent.sqlite"
    with pytest.raises(FileNotFoundError):
        main(["read", "--db", str(absent)])
    assert not absent.exists()


@pytest.mark.parametrize("broken", ["json", "identity"])
def test_bad_opening_data_leaves_no_partial_world(tmp_path: Path, broken: str) -> None:
    content = tmp_path / "content"
    content.mkdir()
    for file in [*CONTENT.glob("*.json"), CONTENT / "opening_gazette.md"]:
        shutil.copyfile(file, content / file.name)
    if broken == "json":
        (content / "armies.json").write_text("{")
    else:
        path = content / "characters.json"
        data = json.loads(path.read_text())
        del data["characters"][50]["name"]
        path.write_text(json.dumps(data))
    games = tmp_path / "games"
    with pytest.raises(ValueError):
        Court.new_game(games, TestModel(), content)
    (path,) = games.glob("*.sqlite")
    court = Court(path, TestModel())
    assert court.entities("audit") == []
    assert court.facts("audit") == []
    court.close()
