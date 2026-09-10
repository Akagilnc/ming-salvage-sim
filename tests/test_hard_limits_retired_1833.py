"""#1833 S3：硬上限撤除与旧供料退役。

Seams: prepare_character_materials / list_materials / read_material,
create_minister_agent (API tools), build_simulator_payload.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ming_sim.materials import list_materials, prepare_character_materials, read_material
from ming_sim.models import CourtContext, LLMConfig
from ming_sim.registry import create_minister_agent
from ming_sim.simulation import build_simulator_payload


def _active_minister(db, content):
    for character in content.characters.values():
        if character.office_type in ("后宫", "宗藩"):
            continue
        if db.get_character_status(character.name)[0] == "active":
            return character
    raise AssertionError("no active minister")


def _ctx(game):
    db, state, _ = game
    return CourtContext(state=state, db=db, previous_summary="")


def test_thirty_night_rounds_of_knowledge_are_not_truncated(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)
    markers = [f"NIGHT_ROUND_{i:02d}_SENTINEL" for i in range(30)]
    for i, marker in enumerate(markers):
        db.record_character_participation(
            state, [character.name], "audience",
            f"夜对第{i}轮", marker, source_id=f"night-round:{i}",
        )

    prepared = prepare_character_materials(
        db, state, character, dest_root=tmp_path / "m",
    )
    seen = read_material(prepared.root, f"人物/{character.name}/见闻.txt")
    for marker in markers:
        assert marker in seen


def test_gazettes_older_than_six_months_are_indexed_in_full(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)
    original_turn, original_year, original_period = state.turn, state.year, state.period
    markers = []
    try:
        for i in range(7):
            state.turn = i + 1
            state.year = 1628
            state.period = i + 1
            marker = f"GAZETTE_MONTH_{i}_FULL"
            markers.append((1628, i + 1, marker))
            db.save_turn_report(state, marker + ("文" * 1600))
    finally:
        state.turn, state.year, state.period = original_turn, original_year, original_period

    prepared = prepare_character_materials(
        db, state, character, dest_root=tmp_path / "m",
    )
    names = list_materials(prepared.root)
    index = read_material(prepared.root, "INDEX.txt")
    for year, period, marker in markers:
        rel = f"公开说法/邸报/{year}年{period}月.txt"
        assert rel in names
        assert rel in index.splitlines()
        body = read_material(prepared.root, rel)
        assert marker in body
        assert len(body) > 1500


def test_api_material_reads_beyond_five_are_not_rejected(game):
    db, state, content = game
    character = _active_minister(db, content)
    captured = {}

    def fake_agent(**kwargs):
        captured.update(kwargs)
        return kwargs

    cfg = LLMConfig(api_key="", base_url="", model="test", channel="api")
    with patch("ming_sim.registry.Agent", side_effect=fake_agent), \
         patch("ming_sim.registry.create_chat_model", return_value=MagicMock()):
        create_minister_agent(character, cfg, _ctx(game), db)

    assert captured.get("tool_call_limit") in (None, 0)
    tools = {fn.__name__: fn for fn in captured["tools"]}
    listing = tools["list_materials"]()
    rels = [line for line in listing.splitlines() if line.strip() and line != "INDEX.txt"]
    assert len(rels) >= 6
    for rel in rels[:6]:
        body = tools["read_material"](rel)
        assert body
        assert not str(body).startswith("无法读取")


def test_simulator_keeps_full_previous_gazette(game):
    db, state, _content = game
    marker = "PREVIOUS_GAZETTE_HEAD_SENTINEL"
    previous = marker + ("章" * 1800) + "PREVIOUS_GAZETTE_TAIL_SENTINEL"
    payload = build_simulator_payload(
        state, db, decree_text="", previous_narrative=previous,
    )
    kept = payload["previous_narrative_tail"]
    assert marker in kept
    assert "PREVIOUS_GAZETTE_TAIL_SENTINEL" in kept
    assert kept == previous
