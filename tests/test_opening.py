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
    tmp_path: Path, capsys: pytest.CaptureFixture[str], entry: str,
) -> None:
    if entry == "cli":
        main(["new", "--directory", str(tmp_path)])
        path = Path(json.loads(capsys.readouterr().out)["db"])
    else:
        with TestClient(create_app(tmp_path)) as client:
            save = client.post("/actions", json={"action": "new"}).json()["save"]
            assert client.get("/state").json()["saves"] == [save]
            path = tmp_path / save
    court = Court(path, TestModel())
    entities = court.entities("audit")
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
            for k, v in record.items()
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
        ("multiple_offices", "offices"),
        ("offices", "priority"),
        ("fiscal_config", "items"),
    ]:
        source = f"{filename}.json/{collection}"
        expected = json.loads((CONTENT / f"{filename}.json").read_text())[collection]
        assert [e.data for e in entities if e.source == source] == [
            canonical(r) for r in expected
        ]
    assert [e.data for e in entities if e.kind == "event"] == json.loads(
        (CONTENT / "events.json").read_text()
    )
    dossiers = json.loads((CONTENT / "minister_dossiers.json").read_text())
    assert {e.key: e.data for e in entities if e.kind == "dossier"} == dossiers
    assert [e.key for e in entities if e.kind == "gazette"] == ["opening"]
    offices = {e.key: e.data for e in entities if e.kind == "office"}
    assert offices["巡抚"]["multiple"] is False
    assert offices["内阁大学士"]["multiple"] is True
    visible = court.entities("emperor")
    assert {e.kind for e in visible} == {"person", "calendar", "gazette"}
    shown = {e.key: e.data for e in visible if e.kind == "person"}
    assert shown.keys() == {e.key for e in entities if e.kind == "person"}
    visible_fields = {"name", "office", "location", "status"}
    assert all(set(data) <= visible_fields for data in shown.values())
    characters = {
        p["name"]: p
        for p in json.loads((CONTENT / "characters.json").read_text())["characters"]
    }
    assert all(
        p[field] in offices
        for p in characters.values()
        for field in ("office", "historical_office")
        if p.get(field)
    )
    for name in ["史可法", "徐光启", "黄道周", "练国事", "郭允厚"]:
        assert shown[name] == {
            k: v for k, v in canonical(characters[name]).items() if k in visible_fields
        }
    assert court.facts("audit") == []
    assert court.entities("audit", replay=True) == entities
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
        games = tmp_path / "games"
        with pytest.raises(FileNotFoundError):
            main(["new", "--directory", str(games)])
        with TestClient(create_app(games)) as client:
            with pytest.raises(FileNotFoundError):
                client.post("/actions", json={"action": "new"})
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
