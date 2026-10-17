from __future__ import annotations

from types import SimpleNamespace

import pytest

import ming_sim.registry as registry_mod
from ming_sim.audience_night import get_open_night, open_night, present_names_at
from ming_sim.materials import _safe_segment, list_materials, read_material

from tests.test_scene_llm_1836 import _sess

"""#1930：场景提示词撤强制「先读材料查证」；材料照给可读。

Seams:
- GameSession.scene_chat（真实召对入口：宣大臣 + 说一句）
- create_scene_agent 实际装入模型的 instructions / tools
- PreparedMaterials 目录（在场人物材料可读）
"""


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_scene_chat_instructions_drop_forced_material_lookup(game, monkeypatch):
    """从真实入口宣大臣并说话：指令无强制查证前置；同调用材料仍可读。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(get_open_night(db)["id"])
    target = "杨嗣昌"

    captured: dict = {}

    class _CaptureAgent:
        """承接 create_scene_agent 真实装配，不碰 agno Model 构造。"""

        def __init__(self, **kwargs):
            self.instructions = kwargs.get("instructions")
            self.tools = kwargs.get("tools")
            self.model = kwargs.get("model")
            self.num_history_runs = 3
            captured["instructions"] = list(self.instructions or [])
            captured["tools"] = list(self.tools or [])

        def run(self, _message):
            return SimpleNamespace(
                content=f"{target}入殿叩见。臣听候圣裁。", tools=[],
            )

    monkeypatch.setattr(registry_mod, "Agent", _CaptureAgent)
    monkeypatch.setattr(
        registry_mod, "create_chat_model",
        lambda *_a, **_k: SimpleNamespace(materials_dir=None),
    )

    def _factory(*args, **kwargs):
        agent = registry_mod.create_scene_agent(*args, **kwargs)
        prepared = args[1] if len(args) > 1 else kwargs.get("prepared")
        captured["prepared"] = prepared
        return agent

    monkeypatch.setattr("ming_sim.session.create_scene_agent", _factory)
    sess = _sess(db, state, content, llm_config=SimpleNamespace(channel="api"))

    # 真实召对入口：先宣入，再说一句（宣召口令只认封闭前缀，不与后文黏连）。
    sess.scene_chat(f"宣{target}", write_gate=sess._write_gate)
    sess.scene_chat("边饷如何？", write_gate=sess._write_gate)

    assert captured.get("instructions"), "scene_chat must assemble scene agent instructions"
    joined = "\n".join(str(part) for part in captured["instructions"])
    # 票面验收：实际指令不含「先读材料目录查证」类强制前置。
    assert "先读材料目录查证" not in joined
    assert "查证再写入戏文" not in joined

    prepared = captured["prepared"]
    assert target in present_names_at(db, night_id)
    mats = list_materials(prepared.root)
    person_prefix = f"人物/{_safe_segment(target)}/"
    person_paths = [p for p in mats if p.startswith(person_prefix)]
    assert person_paths, f"present minister materials missing under {person_prefix!r}"
    # 材料目录照旧可读：至少能读到该人的一份文本。
    sample = person_paths[0]
    body = read_material(prepared.root, sample)
    assert str(body or "").strip(), f"material unreadable: {sample}"

    tool_names = {
        getattr(t, "__name__", "") or getattr(t, "name", "")
        for t in captured["tools"]
    }
    assert "list_materials" in tool_names
    assert "read_material" in tool_names
