"""Medium tests (local SQLite): opening data crosses Court without normalization."""

import json
import shutil
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel
from starlette.testclient import TestClient

from ming.__main__ import main
from ming.middle.court import Court
from ming.web import create_app

CONTENT = Path(__file__).parents[1] / "content"


@pytest.mark.parametrize("entry", ["cli", "web"])
def test_new_game_imports_complete_world_records_and_separates_identities(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], entry: str, steps, audit,
) -> None:
    if entry == "cli":
        main(["new", "--directory", str(tmp_path)])
        path = Path(json.loads(capsys.readouterr().out)["db"])
        visible = audit(path, identity="emperor")["entities"]
    else:
        with TestClient(create_app(tmp_path)) as client:
            save = client.post("/actions", json={"action": "new"}).json()["save"]
            assert client.get("/state").json()["saves"] == [save]
            visible = client.get("/records").json()["entities"]
            path = tmp_path / save
    entities = audit(path)["entities"]
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
        assert [{k: v for k, v in e["data"].items() if not (collection == "offices" and k == "external")}
                for e in entities if e["source"] == source] == [
            canonical(r) for r in expected
        ]
    assert [e["data"] for e in entities if e["kind"] == "historical_event"] == json.loads(
        (CONTENT / "events.json").read_text()
    )
    expected = {e["key"]: e["data"] for e in entities if e["kind"] == "distance"}
    assert {key: expected["北直隶 / 京师"][key] for key in
            ("山东", "陕西", "南直隶 / 南京", "广东", "辽东 / 宁锦")} == {
        "山东": 900, "陕西": 2650, "南直隶 / 南京": 3445, "广东": 7835, "辽东 / 宁锦": 930,
    }
    assert expected["山东"]["山东"] == 0
    assert expected["山东"]["北直隶 / 京师"] == 900
    dossiers = json.loads((CONTENT / "minister_dossiers.json").read_text())
    assert {e["key"]: e["data"] for e in entities if e["kind"] == "dossier"} == dossiers
    assert [e["key"] for e in entities if e["kind"] == "gazette"] == ["opening"]
    offices = {e["key"]: e["data"] for e in entities if e["kind"] == "office"}
    assert offices["巡抚"]["multiple"] is False
    assert offices["内阁大学士"]["multiple"] is True
    assert {offices[name]["external"] for name in ("巡抚", "知府", "卫指挥使")} == {True}
    assert {offices[name]["external"] for name in ("户部尚书", "南京户部尚书", "内阁大学士")} == {False}
    assert {e["kind"] for e in visible} == {"person", "calendar", "gazette", "incumbency"}
    shown = {e["key"]: e["data"] for e in visible if e["kind"] == "person"}
    assert shown.keys() == {e["key"] for e in entities if e["kind"] == "person"}
    visible_fields = {"name", "appointments", "location", "status", "identity_description", "transit_to", "waiting_audience", "departure_date", "arrival_date", "travel_speed"}
    assert all(set(data) <= visible_fields for data in shown.values())
    characters = {
        p["name"]: p
        for p in json.loads((CONTENT / "characters.json").read_text())["characters"]
    }
    for name in ["史可法", "徐光启", "黄道周", "练国事", "郭允厚"]:
        assert {k: v for k, v in shown[name].items() if k not in {"appointments", "identity_description"}} == {
            k: v for k, v in canonical(characters[name]).items() if k in visible_fields - {"identity_description"}
        }
        assert [{k: a[k] for k in ("office", "territory")} for a in shown[name]["appointments"]] == characters[name]["appointments"]
    assert "identity_description" not in shown["郭允厚"]
    assert "identity_description" in shown["徐光启"]
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
    assert shown["来宗道"]["appointments"] == [{"office": "礼部尚书", "territory": "", "holders": ["来宗道"], "acting": [], "role": "holders"}]
    assert [e["data"]["holders"] for e in entities if e["kind"] == "incumbency" and e["data"]["office"] == "礼部尚书"] == [["来宗道"]]
    assert {a["office"] for a in shown["黄立极"]["appointments"]} == {"内阁大学士", "内阁首辅"}
    assert offices["内阁首辅"]["multiple"] is False
    assert offices["内阁首辅"]["department"] == "内阁"
    assert all({a["office"] for a in shown[name]["appointments"]} <= {"内阁大学士", "中极殿大学士"} for name in ("施凤来", "张瑞图", "李国普"))
    assert shown["曾樱"]["appointments"] == [{"office": "知府", "territory": "南直隶常州府", "holders": ["曾樱"], "acting": [], "role": "holders"}]
    assert shown["卢象升"]["location"] == "北直隶 / 京师"
    assert shown["卢象升"]["appointments"] == [{"office": "知府", "territory": "北直隶大名府", "holders": ["卢象升"], "acting": [], "role": "holders"}]
    assert not any({"office", "office_type", "office_region", "appointments"} & e["data"].keys() for e in entities if e["kind"] == "person")
    court = Court(path, TestModel())
    assert court.facts("audit") == ()
    assert court.entities("audit", replay=True) == court.entities("audit")
    assert court.night(court.open_night()).closed is False
    court.close()


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
        ["month", "--db", first["db"], "--backend", "claude-cli"]
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


def test_build_is_explicit_and_new_games_copy_the_last_successful_template(
    tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str],
    opening_template_db: Path, audit,
) -> None:
    home = tmp_path / "home"
    template = home / ".ming" / "opening.sqlite"
    template.parent.mkdir(parents=True)
    shutil.copyfile(opening_template_db, template)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    content = shutil.copytree(CONTENT, tmp_path / "content")
    path = content / "opening.json"
    opening = json.loads(path.read_text())
    opening["calendar"][0]["year"] = 1628
    path.write_text(json.dumps(opening))
    games = tmp_path / "games"
    original = audit(template)
    previous_id = None
    for rebuild in (False, True, True):
        if rebuild:
            main(["build-opening", "--content", str(content)])
            capsys.readouterr()
        main(["new", "--directory", str(games)])
        court = Court(Path(json.loads(capsys.readouterr().out)["db"]), TestModel())
        calendar = court.calendar()
        assert calendar.data["year"] == (1628 if rebuild else 1627)
        assert calendar.id != previous_id
        previous_id = calendar.id
        before_record = audit(template)
        court.record(calendar.id, [("observation", {"year": 1629})], {"year": 1629})
        assert court.calendar().data["year"] == 1629
        assert audit(template) == before_record
        court.close()
        if not rebuild:
            assert audit(template) == original
            main(["new", "--directory", str(games)])
            other = audit(Path(json.loads(capsys.readouterr().out)["db"]))
            assert next(
                e["data"]["year"] for e in other["entities"] if e["kind"] == "calendar"
            ) == 1627


@pytest.mark.parametrize("broken", ["json", "identity", "missing"])
def test_bad_opening_data_leaves_no_partial_world(
    tmp_path: Path, broken: str, monkeypatch, opening_template_db: Path, audit,
) -> None:
    if broken == "missing":
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        games = tmp_path / "games"
        with pytest.raises(FileNotFoundError):
            main(["new", "--directory", str(games)])
        with TestClient(create_app(games), raise_server_exceptions=False) as client:
            response = client.post("/actions", json={"action": "new"})
            assert response.status_code == 503
            assert client.get("/state").json()["saves"] == []
        assert not games.exists()
        return
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
    template = tmp_path / "template.sqlite"
    shutil.copyfile(opening_template_db, template)
    original = audit(template)
    with pytest.raises(ValueError):
        main(["build-opening", "--content", str(content), "--output", str(template)])
    assert audit(template) == original
    assert list(tmp_path.glob("*.sqlite")) == [template]
    court = Court.new_game(tmp_path / "games", TestModel(), template)
    assert court.calendar().data["month"] == 10
    assert court.night(court.open_night()).closed is False
    court.close()
