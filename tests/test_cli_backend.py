"""CLI 后端确定性逻辑（解析/分派层，不碰 agy 生成本身）。

agy 生成内容非确定、不可断言；但其周围的解析、前缀分派、JSON 规范化全可测。
密令/补全里对 agy 的调用用 monkeypatch 喂固定输出，测纯逻辑。
"""

from __future__ import annotations

import json

import ming_sim.cli_backend as cb


# ── resolve_minister_actions：拟旨/密令前缀分派（拟旨纯逻辑、无 agy）──

def test_draft_prefix_captures_reply():
    reply = "臣领旨。敕谕户部与陕西巡抚洪承畴：发太仓银三万两亲督赈发。钦此。"
    acts = cb.resolve_minister_actions(reply, "拟旨如下：发三万两赈陕西", default_assignee="毕自严")
    assert acts["decree_text"] == reply
    assert acts["secret_order"] is None


def test_no_prefix_no_action():
    acts = cb.resolve_minister_actions("臣以为当从长计议。", "辽东军饷如何？", default_assignee="王在晋")
    assert acts["decree_text"] is None
    assert acts["secret_order"] is None


def test_secret_prefix_extracts_fields(monkeypatch):
    # 密令走聚焦提取 → agy；用 monkeypatch 喂固定 JSON，测解析。
    canned = json.dumps({
        "标题": "密查辽东军饷", "内容": "暗查关宁兵额有无虚冒",
        "承办人": "李若琏", "期限月数": 3, "标签": ["辽东", "军饷"],
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_agy", lambda prompt: (canned, 1))
    acts = cb.resolve_minister_actions(
        "臣领密旨，可授李若琏暗查。", "密令如下：查辽东军饷有无侵冒，三月内回奏",
        default_assignee="王在晋",
    )
    so = acts["secret_order"]
    assert so is not None
    assert so["title"] == "密查辽东军饷"
    assert so["assignee"] == "李若琏"        # 抓到点名的承办人，非默认当前大臣
    assert so["deadline_months"] == 3


def test_secret_assignee_defaults_when_unspecified(monkeypatch):
    canned = json.dumps({"标题": "密查", "内容": "暗查", "承办人": "", "期限月数": 0}, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_agy", lambda prompt: (canned, 1))
    acts = cb.resolve_minister_actions("臣领旨。", "密令如下：去查", default_assignee="毕自严")
    assert acts["secret_order"]["assignee"] == "毕自严"


# ── _loads_lenient：容错 JSON 解析 ──

def test_loads_lenient_plain():
    assert cb._loads_lenient('{"a": 1}') == {"a": 1}


def test_loads_lenient_code_fence():
    assert cb._loads_lenient('```json\n{"a": 2}\n```') == {"a": 2}


def test_loads_lenient_with_prose_around():
    assert cb._loads_lenient('好的，结果：{"a": 3} 完毕') == {"a": 3}


def test_loads_lenient_garbage_none():
    assert cb._loads_lenient("这不是 JSON") is None


# ── enrich_initiative_effects：补全解析（agy monkeypatch）──

def test_enrich_army_parsed_and_normalized(monkeypatch):
    canned = json.dumps({
        "effect_on_resolve": {
            "metrics": {"皇威": 5},
            "new_armies": [{"id": "qinjun", "name": "秦兵", "owner_power": "ming",
                            "manpower": 20000, "maintenance_per_turn": 4, "commander": "孙传庭"}],
        },
        "ongoing_effects": {}, "effect_on_fail": {},
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_agy", lambda prompt: (canned, 1))
    out = cb.enrich_initiative_effects("孙传庭练秦兵", "陕西督练新军")
    armies = out["effect_on_resolve"]["new_armies"]
    assert armies[0]["id"] == "qinjun"
    assert armies[0]["manpower"] == 20000


def test_enrich_building_region_floor(monkeypatch):
    # 建筑 create 缺 region_id → 兜底 beizhili，免得静默落不了地
    canned = json.dumps({
        "effect_on_resolve": {"buildings": [{"action": "create", "name": "格致局", "category": "科技"}]},
        "ongoing_effects": {}, "effect_on_fail": {},
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_agy", lambda prompt: (canned, 1))
    out = cb.enrich_initiative_effects("设格致局", "")
    assert out["effect_on_resolve"]["buildings"][0]["region_id"] == "beizhili"


# ── cli_backend_from_env ──

def test_backend_env(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    assert cb.cli_backend_from_env() is None
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    assert cb.cli_backend_from_env() == "agy"
