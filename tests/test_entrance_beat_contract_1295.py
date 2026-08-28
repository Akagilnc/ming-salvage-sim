"""#1295/#1314(2)/#1561 entrance beat 契约——JSON materials、beat_kind、年月键与输入边界。

seam：
- 入殿材料面（assemble_beat_inputs + generator 投喂 JSON）：不含玩家问话；
- open-beat JSON materials 的 typed 场面事实；
- open/enter 与 exit/close 的年月键发射闸。

不比较生成正文或 prompt 措辞；不动编排缝 / registry 生命周期。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ming_sim import audience_night as an
from ming_sim import beat_orchestration as bo
from ming_sim.beat_orchestration import (
    BEAT_CLOSE,
    BEAT_ENTER,
    BEAT_EXIT,
    BEAT_OPEN,
    BeatInputs,
    assemble_beat_inputs,
)


def _load_fresh_beat_module(monkeypatch, *, capture: dict):
    """绕过 conftest 对 create_llm_beat_generator 的 offline stub，直读生产模块。"""

    class _FakeAgent:
        def __init__(self, **kwargs):
            capture.setdefault("agents", []).append(kwargs)

        def run(self, prompt):
            capture.setdefault("prompts", []).append(prompt)
            return SimpleNamespace(content="【入殿气象】帘外风动。")

    monkeypatch.setattr("agno.agent.Agent", _FakeAgent)
    monkeypatch.setattr(
        "ming_sim.llm_model.create_chat_model",
        lambda *_a, **_k: object(),
    )
    monkeypatch.setattr(
        "ming_sim.llm_model.extract_agent_text",
        lambda result: str(getattr(result, "content", "") or ""),
    )

    mod_name = "ming_sim._beat_orch_entrance_contract_probe"
    spec = importlib.util.spec_from_file_location(mod_name, Path(bo.__file__))
    probe = importlib.util.module_from_spec(spec)
    probe.__package__ = "ming_sim"
    sys.modules[mod_name] = probe
    assert spec.loader is not None
    spec.loader.exec_module(probe)
    return probe


def _active_minister(db, content, *, exclude=None):
    skip = exclude or set()
    for name, ch in content.characters.items():
        if name in skip:
            continue
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if db.get_character_status(name)[0] == "active":
            return name
    raise AssertionError("no active ming minister")


def test_entrance_materials_exclude_player_utterance(game, monkeypatch):
    """#1295 负向：entrance 材料面不含玩家问话（输入边界）。

    场景：本夜已有一轮玩家问话 + 大臣回话；二次入殿组装与 LLM 投喂材料
    只可带大臣回话/入殿账，不得夹带玩家问话原文。
    """
    db, state, content = game
    minister = _active_minister(db, content)
    player_q = "卿以为边饷当如何措置？——玩家专属问话标记1295"
    minister_a = "臣请先核太仓实数。——大臣回话标记1295"

    night = an.open_night(db, state, time_of_day="戌时", location="乾清宫")
    an.summon_enter(
        db, night["id"], minister, method=an.METHOD_XUANRU, body="首次入殿·趋至丹墀",
    )
    tid = db.create_chat_turn(state, minister, "s-1295", 0, night_id=night["id"])
    uid = db.append_chat_message(minister, state.turn, "user", player_q)
    mid = db.append_chat_message(minister, state.turn, "minister", minister_a)
    db.update_chat_turn_messages(tid, user_message_id=int(uid), minister_message_id=int(mid))

    # 组装边界：prior 含大臣回话与入殿账，不含玩家问话
    inputs = assemble_beat_inputs(
        db, state, beat_kind=BEAT_ENTER, night_id=int(night["id"]),
        time_of_day=night["time_of_day"], location=night["location"],
        person_name=minister, summon_method=an.METHOD_XUANRU,
    )
    prior_joined = "‖".join(inputs.prior_appearances)
    public_joined = "‖".join(inputs.public_layer)
    assert "大臣回话标记1295" in prior_joined
    assert "首次入殿" in prior_joined
    assert "玩家专属问话标记1295" not in prior_joined
    assert "玩家专属问话标记1295" not in public_joined
    assert player_q not in prior_joined and player_q not in public_joined

    # generator 投喂 JSON 同样不含玩家问话
    capture: dict = {}
    probe = _load_fresh_beat_module(monkeypatch, capture=capture)
    gen = probe.create_llm_beat_generator(object())
    gen(inputs)

    assert capture.get("prompts"), "generator never received materials"
    materials_raw = capture["prompts"][0]
    assert "玩家专属问话标记1295" not in materials_raw
    assert player_q not in materials_raw
    # 大臣回话仍可在二次入殿材料中（已发生史实，非预演）
    assert "大臣回话标记1295" in materials_raw

    payload = json.loads(materials_raw)
    assert payload.get("场景节点") == BEAT_ENTER
    blob = json.dumps(payload, ensure_ascii=False)
    assert "玩家专属问话标记1295" not in blob


def test_open_beat_llm_receives_structured_scene_materials(monkeypatch):
    """#1561：open-beat 验收只断 JSON materials 中 typed 场面事实。"""
    capture: dict = {}
    probe = _load_fresh_beat_module(monkeypatch, capture=capture)
    facts = ('{"dossier_id": 651, "channels": ["稽核"], "scene_text": ""}',)
    probe.create_llm_beat_generator(object())(
        BeatInputs(beat_kind=BEAT_OPEN, time_of_day="戌时", location="乾清宫",
                   audience_scenes=facts)
    )
    payload = json.loads(capture["prompts"][0])
    assert payload["待呈御前的结构化场面事实"] == list(facts)


@pytest.mark.parametrize("beat_kind", [BEAT_OPEN, BEAT_ENTER])
def test_llm_materials_include_reign_period_label_for_open_enter(monkeypatch, beat_kind):
    """#1294/#1313 r4：create_llm_beat_generator 材料面投喂当期年月（open/enter 且非空）。"""
    capture: dict = {}
    probe = _load_fresh_beat_module(monkeypatch, capture=capture)
    gen = probe.create_llm_beat_generator(object())
    label = "天启七年十月"
    gen(BeatInputs(
        beat_kind=beat_kind,
        time_of_day="戌时",
        location="乾清宫",
        person_name="杨嗣昌" if beat_kind == BEAT_ENTER else "",
        reign_period_label=label,
    ))
    assert capture.get("prompts"), "generator never received materials"
    payload = json.loads(capture["prompts"][0])
    assert payload.get("当期年月") == label
    assert payload.get("场景节点") == beat_kind


@pytest.mark.parametrize("beat_kind", [BEAT_EXIT, BEAT_CLOSE])
def test_llm_materials_exclude_reign_period_label_for_exit_close(monkeypatch, beat_kind):
    """#1313 r4b：exit/close 材料面不得含「当期年月」（即便字段被误填）。"""
    capture: dict = {}
    probe = _load_fresh_beat_module(monkeypatch, capture=capture)
    gen = probe.create_llm_beat_generator(object())
    gen(BeatInputs(
        beat_kind=beat_kind,
        time_of_day="戌时",
        location="乾清宫",
        person_name="杨嗣昌" if beat_kind == BEAT_EXIT else "",
        # 故意塞非空：发射闸须按 beat_kind 拒绝，不能仅靠空串默认
        reign_period_label="天启七年十月",
    ))
    assert capture.get("prompts"), "generator never received materials"
    payload = json.loads(capture["prompts"][0])
    assert "当期年月" not in payload
    assert payload.get("场景节点") == beat_kind


@pytest.mark.parametrize("beat_kind", [BEAT_OPEN, BEAT_ENTER])
def test_llm_materials_omit_empty_reign_period_label_for_open_enter(monkeypatch, beat_kind):
    """#1313 r4b：open/enter 但 label 空/空白时亦不发射「当期年月」键。"""
    capture: dict = {}
    probe = _load_fresh_beat_module(monkeypatch, capture=capture)
    gen = probe.create_llm_beat_generator(object())
    gen(BeatInputs(
        beat_kind=beat_kind,
        time_of_day="戌时",
        location="乾清宫",
        person_name="杨嗣昌" if beat_kind == BEAT_ENTER else "",
        reign_period_label="   ",
    ))
    assert capture.get("prompts"), "generator never received materials"
    payload = json.loads(capture["prompts"][0])
    assert "当期年月" not in payload
    assert payload.get("场景节点") == beat_kind
