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
    indexed = {(e.kind, e.key): e.data for e in entities}
    assert indexed[("army", "关宁军 / 宁锦防线")]["station_region"] == "辽东 / 宁锦"
    assert indexed[("class", "北直隶 / 京师·农民")]["region_id"] == "北直隶 / 京师"
    assert indexed[("person", "徐光启")]["location"] == "南直隶 / 南京"
    assert indexed[("army", "关宁军 / 宁锦防线")]["owner_power"] == "大明"
    assert indexed[("region", "北直隶 / 京师")]["controlled_by"] == "大明"
    assert indexed[("world", "天下")]["imperial_prestige"] == 20
    assert indexed[("world", "天下")]["public_support"] == 50
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
        ("multiple_offices", "offices"),
        ("offices", "priority"),
    ]:
        source = f"{filename}.json/{collection}"
        expected = json.loads((CONTENT / f"{filename}.json").read_text())[collection]
        imported = [e.data for e in entities if e.source == source]
        assert len(imported) == len(expected)
        reference_fields = {
            "id",
            "region_id",
            "station_region",
            "location",
            "office_region",
            "power_id",
            "owner_power",
            "controller",
            "controlled_by",
        }
        for original, actual in zip(expected, imported, strict=True):
            assert {k: v for k, v in actual.items() if k not in reference_fields} == {
                k: v for k, v in original.items() if k not in reference_fields
            }
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
            k: v for k, v in indexed[("person", name)].items() if k in visible_fields
        }
    assert court.facts("audit") == []
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
