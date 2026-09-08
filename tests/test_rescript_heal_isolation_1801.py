"""#1801 r2：三类整批判死改重试、只影响自己（复用 #1746 heal 回路）。

验收缝：generate_rescript_draft（真实入口，无真实 LLM）。
六样：①a 未成形 / ①b-1 utf8 / ①b-2 顶层未知键 / ①c 条目数无上限 /
② 条目字段 / ③ option A shape。
"""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

import ming_sim.rescript_draft as rescript_mod
from ming_sim.rescript_draft import (
    RESCRIPT_OPTION_FIELD_HEAL_RETRIES,
    generate_rescript_draft,
)


_ROSTER = [{"character_id": "毕自严", "tier": "主办", "role": "", "delegator_id": None}]


def _ctx() -> dict:
    return {
        "active_issues": [],
        "region_targets": [{"id": "shaanxi", "name": "陕西", "kind": "腹地"}],
        "army_targets": [
            {"id": "guanning", "name": "关宁军", "station": "宁远"},
        ],
        "gazette": "邸报",
        "triage_actor": {},
        "turn": {},
    }


def _opt(**kw) -> dict:
    base = {
        "label": "拟",
        "hint": "h",
        "action_type": "assignment",
        "target_kind": "region",
        "target_id": "shaanxi",
        "locality_scope": "single",
        "region_id": "shaanxi",
        "assignee_name": "",
        "transaction_category": "督赈",
        "participant_roster": [dict(i) for i in _ROSTER],
    }
    base.update(kw)
    return base


def _item(title: str, *, context: str = "导语", options=None) -> dict:
    return {
        "title": title,
        "context": context,
        "options": options if options is not None else [_opt(label=f"{title}-甲"), _opt(label=f"{title}-乙")],
    }


def _items_json(items: list) -> str:
    return json.dumps({"items": items}, ensure_ascii=False)


def _parse_heal(prompt: object) -> dict:
    assert isinstance(prompt, str) and prompt.strip()
    body = json.loads(prompt)
    assert body.get("kind") == "rescript_option_field_heal"
    assert isinstance(body.get("failures"), list) and body["failures"]
    return body


def _field_map(failure: dict) -> dict:
    out = {}
    for fact in failure.get("field_failures") or []:
        out[str(fact["field"])] = fact
    return out


def _never_fix_llm(first_raw: str):
    tags: list[str] = []
    prompts: list[str] = []

    def _llm(_a, prompt, tag="", prior_messages=None):
        tags.append(tag)
        prompts.append(prompt)
        return first_raw

    return _llm, tags, prompts


# ---------------------------------------------------------------------------
# ①a 未成形（非 items / 围栏外 prose）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw",
    [
        "not-json {",
        "```json\n{\"items\":[]}\n```\n臣请圣裁",
        json.dumps({"nope": []}),
    ],
    ids=["malformed", "fence_prose", "no_items_key"],
)
def test_1801_top_unformed_heals_then_no_drafts(raw, monkeypatch, tmp_path):
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    llm, tags, prompts = _never_fix_llm(raw)
    monkeypatch.setattr(rescript_mod, "run_agent_text", llm)
    assert generate_rescript_draft(object(), _ctx(), turn=101) is None
    assert tags[0] == "rescript-draft"
    assert tags[1:] == ["rescript-draft-heal"] * RESCRIPT_OPTION_FIELD_HEAL_RETRIES
    req = _parse_heal(prompts[1])
    assert req["failures"][0]["scope"] == "top"
    assert req["failures"][0]["exhaust"] == "degrade_month"
    assert "items" in _field_map(req["failures"][0])
    note = tmp_path / "error_packs" / "rescript_draft_degraded" / "turn101.json"
    assert note.is_file()


# ---------------------------------------------------------------------------
# ①b-1 不可编码字符（条目 title）
# ---------------------------------------------------------------------------

def test_1801_item_utf8_heals_then_drops_only_bad_item(monkeypatch, tmp_path):
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    good = _item("陕西告饥")
    bad = _item("\ud800", context="坏 title")
    raw = _items_json([good, bad])
    llm, tags, prompts = _never_fix_llm(raw)
    monkeypatch.setattr(rescript_mod, "run_agent_text", llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=102)
    assert drafts is not None
    assert len(drafts) == 1 and drafts[0]["title"] == good["title"]
    assert "rescript-draft-heal" in tags
    req = _parse_heal(prompts[1])
    assert req["failures"][0]["scope"] == "item"
    assert req["failures"][0]["exhaust"] == "drop_item"
    assert "title" in _field_map(req["failures"][0])


# ---------------------------------------------------------------------------
# ①b-2 顶层未知键
# ---------------------------------------------------------------------------

def test_1801_unknown_top_key_heals_then_ignores_key_keeps_items(monkeypatch, tmp_path):
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    payload = {"items": [_item("陕西告饥"), _item("辽饷")], "summary": "臣请圣裁"}
    raw = json.dumps(payload, ensure_ascii=False)
    llm, tags, prompts = _never_fix_llm(raw)
    monkeypatch.setattr(rescript_mod, "run_agent_text", llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=103)
    assert drafts is not None
    assert [d["title"] for d in drafts] == ["陕西告饥", "辽饷"]
    assert "rescript-draft-heal" in tags
    req = _parse_heal(prompts[1])
    f0 = req["failures"][0]
    assert f0["scope"] == "top"
    assert f0["exhaust"] == "ignore_top_keys"
    assert "summary" in _field_map(f0)
    note = tmp_path / "error_packs" / "rescript_draft_degraded" / "turn103.json"
    note_obj = json.loads(note.read_text(encoding="utf-8"))
    ignored = note_obj.get("ignored_top_keys") or []
    assert ignored and any(
        "summary" in (row.get("missing_fields") or [])
        or any(f.get("field") == "summary" for f in (row.get("field_failures") or []))
        for row in ignored
    )


def test_1801_unknown_top_key_heal_items_empty_must_not_wipe_siblings(monkeypatch, tmp_path):
    """①b-2 成功补交不得因 heal 回 {"items":[]} 清空原合法条目。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    first = json.dumps(
        {"items": [_item("陕西告饥"), _item("辽饷")], "summary": "臣请圣裁"},
        ensure_ascii=False,
    )
    # 补交只回空 items——不得整份替换底稿
    healed = json.dumps({"items": []}, ensure_ascii=False)
    n = {"i": 0}
    tags: list[str] = []

    def _llm(_a, _p, tag="", prior_messages=None):
        tags.append(tag)
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=113)
    assert drafts is not None
    assert [d["title"] for d in drafts] == ["陕西告饥", "辽饷"]
    assert "rescript-draft-heal" in tags


def test_1801_unknown_top_key_heal_omit_key_succeeds_keeps_items(monkeypatch, tmp_path):
    """①b-2：补交响应不再带未知键 → 只剔该键，items 原样呈上（不必耗尽）。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    first = json.dumps(
        {"items": [_item("陕西告饥"), _item("辽饷")], "summary": "臣请圣裁"},
        ensure_ascii=False,
    )
    # heals 空壳且无 summary → 合并期从底稿删 summary
    healed = json.dumps({"heals": []}, ensure_ascii=False)
    n = {"i": 0}

    def _llm(_a, _p, tag="", prior_messages=None):
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=114)
    assert drafts is not None
    assert [d["title"] for d in drafts] == ["陕西告饥", "辽饷"]
    assert n["i"] == 2  # 一次补交即成，未耗尽


# ---------------------------------------------------------------------------
# ①c 条目数无硬上限（owner 令删门；不 raise、不截尾、不触发重试）
# ---------------------------------------------------------------------------

def test_1801_eight_items_all_pass_no_heal_no_trim(monkeypatch, tmp_path):
    """①c：给 8 条 → 8 条全照呈；不报错、不截尾、不进 heal。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    items = [_item(f"条目{i}") for i in range(8)]
    raw = _items_json(items)
    llm, tags, prompts = _never_fix_llm(raw)
    monkeypatch.setattr(rescript_mod, "run_agent_text", llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=104)
    assert drafts is not None
    assert len(drafts) == 8
    assert [d["title"] for d in drafts] == [f"条目{i}" for i in range(8)]
    assert tags == ["rescript-draft"]
    assert "rescript-draft-heal" not in tags
    note = tmp_path / "error_packs" / "rescript_draft_degraded" / "turn104.json"
    assert not note.exists()


# ---------------------------------------------------------------------------
# ② 条目字段非法
# ---------------------------------------------------------------------------

def test_1801_item_missing_context_heals_then_drops_only_item(monkeypatch, tmp_path):
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    good = _item("兄条目")
    bad = {"title": "缺导语", "options": [_opt(label="a"), _opt(label="b")]}
    raw = _items_json([good, bad])
    llm, tags, prompts = _never_fix_llm(raw)
    monkeypatch.setattr(rescript_mod, "run_agent_text", llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=105)
    assert drafts is not None
    assert len(drafts) == 1 and drafts[0]["title"] == good["title"]
    req = _parse_heal(prompts[1])
    assert req["failures"][0]["scope"] == "item"
    assert "context" in _field_map(req["failures"][0])
    assert req["failures"][0]["heal_id"] == "item:1"


# ---------------------------------------------------------------------------
# ③ option A shape（非 object）耗尽只剔该 option
# ---------------------------------------------------------------------------

def test_1801_option_a_shape_heals_then_drops_only_option(monkeypatch, tmp_path):
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    sibling = _opt(label="兄弟")
    frozen = deepcopy(sibling)
    bad_item = _item("急务", options=["not-a-dict", sibling])
    other = _item("其它急务")
    raw = _items_json([bad_item, other])
    llm, tags, prompts = _never_fix_llm(raw)
    monkeypatch.setattr(rescript_mod, "run_agent_text", llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=106)
    assert drafts is not None
    assert len(drafts) == 2
    first = next(d for d in drafts if d["title"] == "急务")
    assert len(first["options"]) == 1
    for k, v in frozen.items():
        assert first["options"][0].get(k) == v
    assert any(d["title"] == "其它急务" for d in drafts)
    req = _parse_heal(prompts[1])
    assert req["failures"][0]["scope"] == "option"
    assert req["failures"][0]["heal_id"] == "0:0"
    assert "option" in _field_map(req["failures"][0])
