"""#1830 S1：材料目录骨架与两通道读取。

Seams: prepare_character_materials (directory + opening min set),
list_materials/read_material (API), CLI cwd/readonly flags, restore rebuild.
"""

from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from openai.types.chat.chat_completion_message_function_tool_call import (
    ChatCompletionMessageFunctionToolCall,
    Function as ToolFunction,
)

from ming_sim.audience_night import (
    AUDIBILITY_PUBLIC,
    append_ledger_entry,
    open_night,
    summon_enter,
)
from ming_sim.materials import (
    directory_has_raw_world_copy,
    list_materials,
    prepare_character_materials,
    read_material,
)
from ming_sim.models import CourtContext, LLMConfig
from ming_sim.registry import create_minister_agent
from ming_sim.session import GameSession


def _active_minister(db, content, *, office_type=None):
    for character in content.characters.values():
        if character.office_type in ("后宫", "宗藩"):
            continue
        if office_type and character.office_type != office_type:
            continue
        if db.get_character_status(character.name)[0] == "active":
            return character
    raise AssertionError("no active minister")


def _ctx(game):
    db, state, _ = game
    return CourtContext(state=state, db=db, previous_summary="")


def test_prepare_writes_typed_tree_and_index(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)
    dest = tmp_path / "materials"
    prepared = prepare_character_materials(db, state, character, dest_root=dest)

    names = list_materials(prepared.root)
    assert "INDEX.txt" in names
    assert any(p.startswith("人物/") and p.endswith("/经历.txt") for p in names)
    assert any(p.startswith("人物/") and p.endswith("/公事档案.txt") for p in names)
    index = read_material(prepared.root, "INDEX.txt")
    for line in index.splitlines():
        if line.strip():
            assert line.strip() in names
            assert read_material(prepared.root, line.strip())
    assert not directory_has_raw_world_copy(prepared.root, db)


def test_read_material_stays_inside_directory(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)
    prepared = prepare_character_materials(
        db, state, character, dest_root=tmp_path / "m",
    )
    try:
        read_material(prepared.root, "../outside.txt")
        raise AssertionError("expected path confinement")
    except ValueError:
        pass


def test_opening_is_minimum_set_not_full_projection(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)
    prepared = prepare_character_materials(
        db, state, character, dest_root=tmp_path / "m",
    )
    opening = prepared.opening
    assert character.name in opening
    assert character.office in opening
    assert f"{state.year}年{state.period}月" in opening
    assert "正经手事务" in opening
    assert "本场已说的话" in opening
    assert f"【{character.name}此刻所知的天下" not in opening
    blob = "\n".join(
        read_material(prepared.root, path)
        for path in list_materials(prepared.root)
        if path != "INDEX.txt"
    )
    assert blob


def test_api_agent_tool_and_cli_cwd_process_read_same_file(game, tmp_path):
    """API = Agent.run 发出 read_material；CLI = 子进程以材料目录为 cwd 读同一文件。"""
    import ming_sim.cli_backend as cb
    from ming_sim.cli_backend import CliChat, _fake_completion

    db, state, content = game
    character = _active_minister(db, content)
    dest = tmp_path / "m"
    prepared = prepare_character_materials(db, state, character, dest_root=dest)
    rel = next(p for p in list_materials(prepared.root) if p.endswith("经历.txt"))
    expected = read_material(prepared.root, rel)

    class ForcedRead(CliChat):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.trace = []

        def invoke(self, messages, assistant_message, response_format=None, tools=None, **kwargs):
            names = []
            for item in tools or []:
                fn = item.get("function", item) if isinstance(item, dict) else {}
                names.append(fn.get("name") if isinstance(fn, dict) else None)
            assistant_message.metrics.start_timer()
            if "read_material" not in names:
                assistant_message.metrics.stop_timer()
                raise AssertionError("audience agent missing read_material")
            if not self.trace:
                self.trace.append({"tool": "read_material", "path": rel})
                call = ChatCompletionMessageFunctionToolCall(
                    id="call-read-1830",
                    type="function",
                    function=ToolFunction(
                        name="read_material",
                        arguments=json.dumps({"path": rel}, ensure_ascii=False),
                    ),
                )
                assistant_message.metrics.stop_timer()
                return self._parse_provider_response(
                    _fake_completion("", self.id, [call]),
                    response_format=response_format,
                )
            assistant_message.metrics.stop_timer()
            return self._parse_provider_response(
                _fake_completion("已取阅", self.id),
                response_format=response_format,
            )

    model = ForcedRead(id="t", backend="codex", api_key="cli-backend")
    cfg = LLMConfig(api_key="", base_url="", model="t", channel="cli", cli_runner="codex")
    with patch("ming_sim.registry.create_chat_model", return_value=model):
        agent = create_minister_agent(character, cfg, _ctx(game), None)
    output = agent.run("请取阅你的经历材料")
    executions = list(getattr(output, "tools", None) or [])
    assert executions
    read_exec = next(item for item in executions if getattr(item, "tool_name", "") == "read_material")
    assert read_exec.tool_args["path"] == rel
    assert read_exec.result == expected
    assert model.trace == [{"tool": "read_material", "path": rel}]

    cli_out = subprocess.check_output(
        [sys.executable, "-c", f"from pathlib import Path; print(Path({rel!r}).read_text(encoding='utf-8'), end='')"],
        cwd=str(prepared.root),
        text=True,
    )
    assert cli_out == expected

    cmd, _stdin, _env = cb._cli_runner_command(
        "codex", "p", materials_dir=str(prepared.root),
    )
    assert "--sandbox" in cmd and "read-only" in cmd
    assert "--ignore-user-config" in cmd
    cmd, _stdin, _env = cb._cli_runner_command(
        "claude", "p", materials_dir=str(prepared.root),
    )
    joined = " ".join(cmd)
    assert "--allowedTools" in cmd
    assert "Read" in cmd and "Glob" in cmd and "Grep" in cmd
    disallowed_span = joined.split("--disallowedTools", 1)[-1]
    assert "Read" not in disallowed_span.split("--", 1)[0]


def test_audience_agent_exposes_directory_tools_and_min_instructions(game):
    db, state, content = game
    character = _active_minister(db, content)
    captured = {}

    def fake_agent(**kwargs):
        captured.update(kwargs)
        return kwargs

    cfg = LLMConfig(api_key="", base_url="", model="test", channel="cli", cli_runner="codex")
    with patch("ming_sim.registry.Agent", side_effect=fake_agent), \
         patch("ming_sim.registry.create_chat_model", return_value=MagicMock()):
        create_minister_agent(character, cfg, _ctx(game), db)

    instructions = "\n".join(captured["instructions"])
    assert character.name in instructions
    assert f"{state.year}年{state.period}月" in instructions
    assert f"【{character.name}此刻所知的天下" not in instructions
    tool_names = {getattr(fn, "__name__", "") for fn in captured["tools"]}
    assert "list_materials" in tool_names
    assert "read_material" in tool_names
    tools = {fn.__name__: fn for fn in captured["tools"]}
    listing = tools["list_materials"]()
    rel = next(line for line in listing.splitlines() if line.endswith("经历.txt"))
    body = tools["read_material"](rel)
    assert body


def test_audience_prompt_rebuilds_from_directory_and_persisted_turns(game):
    db, state, content = game
    character = _active_minister(db, content)
    night = open_night(db, state, location="乾清宫", time_of_day="戌时")
    summon_enter(db, int(night["id"]), character.name)
    from ming_sim.audience_night import attach_chat_turn_to_night
    _nid, ct = attach_chat_turn_to_night(
        db, state, character.name, agno_session_id="sess", agno_runs_before=0,
    )
    spoken = "SENTINEL_NIGHT_SPOKEN_1830"
    uid = db.append_chat_message(character.name, state.turn, "user", "问边饷")
    db.update_chat_turn_messages(ct, user_message_id=uid)
    mid = db.append_chat_message(character.name, state.turn, "minister", spoken)
    db.update_chat_turn_messages(ct, minister_message_id=mid)
    db.conn.execute("UPDATE chat_turns SET extract_status='done' WHERE id=?", (ct,))
    db.conn.commit()
    append_ledger_entry(
        db, int(night["id"]), person_names=[character.name],
        body=spoken, audibility=AUDIBILITY_PUBLIC,
    )

    session = SimpleNamespace(db=db, state=state, registry=None)
    prompt = GameSession._audience_prompt_for_message(
        session, "下一句", character,
    )
    assert spoken in prompt
    assert "下一句" in prompt
    assert f"【{character.name}此刻所知的天下" not in prompt

    path = str(db.path)
    db.close()
    from ming_sim.db import GameDB
    restored = GameDB(path, content)
    try:
        state2 = restored.load_state()
        character2 = content.characters[character.name]
        session2 = SimpleNamespace(db=restored, state=state2, registry=None)
        prompt2 = GameSession._audience_prompt_for_message(
            session2, "重开后一句", character2,
        )
        assert spoken in prompt2
        prepared = prepare_character_materials(restored, state2, character2)
        assert not directory_has_raw_world_copy(prepared.root, restored)
        rel = next(p for p in list_materials(prepared.root) if p.endswith("经历.txt"))
        assert read_material(prepared.root, rel)
    finally:
        restored.close()
