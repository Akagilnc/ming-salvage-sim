"""Medium tests (local SQLite): opening data crosses Court without normalization."""

import json
import shutil
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from ming.__main__ import main
from ming.middle.court import Court

CONTENT = Path(__file__).parents[1] / "content"


def test_new_game_imports_complete_world_records_and_separates_identities(
    tmp_path: Path,
) -> None:
    court = Court.new_game(tmp_path, TestModel())
    entities = court.entities("audit")
    expected_count = 0
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
    ]:
        source = f"{filename}.json/{collection}"
        expected = json.loads((CONTENT / f"{filename}.json").read_text())[collection]
        assert [e.data for e in entities if e.source == source] == expected
        expected_count += len(expected)
    dossiers = json.loads((CONTENT / "minister_dossiers.json").read_text())
    assert {e.key: e.data for e in entities if e.kind == "dossier"} == dossiers
    assert len(entities) == expected_count + len(dossiers)
    visible = court.entities("emperor")
    assert {e.key for e in visible} == {e.key for e in entities if e.kind == "person"}
    assert all(set(e.data) <= {"name", "office", "location", "status"} for e in visible)
    shown = {e.key: e.data for e in visible}
    assert shown["史可法"] == {
        "name": "史可法",
        "office": "诸生（应天府学）",
        "status": "active",
    }
    assert shown["徐光启"] == {
        "name": "徐光启",
        "office": "",
        "location": "nanzhili",
        "status": "offstage",
    }
    assert shown["黄道周"] == {
        "name": "黄道周",
        "office": "翰林院编修",
        "location": "beizhili",
    }
    assert shown["练国事"] == {
        "name": "练国事",
        "office": "巡抚",
        "location": "shaanxi",
        "status": "active",
    }
    assert shown["郭允厚"] == {
        "name": "郭允厚",
        "office": "户部尚书",
        "location": "beizhili",
    }
    assert court.facts("audit") == []
    court.close()


def test_cli_new_games_never_overwrite_and_missing_game_is_not_created(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["new", "--directory", str(tmp_path)]
    main(args)
    first = json.loads(capsys.readouterr().out)
    saved = Path(first["db"]).read_bytes()
    main(args)
    second = json.loads(capsys.readouterr().out)
    assert first["db"] != second["db"]
    assert Path(first["db"]).read_bytes() == saved
    main(["read", "--db", first["db"], "--identity", "audit"])
    assert len(json.loads(capsys.readouterr().out)["entities"]) > len(first["entities"])
    absent = tmp_path / "absent.sqlite"
    with pytest.raises(FileNotFoundError):
        main(["decree", "着史可法办理赈灾。", "--db", str(absent)])
    assert not absent.exists()


@pytest.mark.parametrize("broken", ["json", "identity"])
def test_bad_opening_data_leaves_no_partial_world(tmp_path: Path, broken: str) -> None:
    content = tmp_path / "content"
    content.mkdir()
    for file in CONTENT.glob("*.json"):
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
