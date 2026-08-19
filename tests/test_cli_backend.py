"""CLI backend contracts: public resolve/extract/runner seams (backend mocked).

#1185 wave2b: drop private helper unit pins; merge same-seam tracers; assert
typed/structural fields over free Chinese presentation copy. Runner subprocess
stays mocked (no real binary/LLM/network).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from agno.agent import Agent
from agno.models.message import Message
from pydantic import BaseModel

from ming_sim.agents import run_agent_stream_text
import ming_sim.cli_backend as cb
from ming_sim.models import LLMConfig


def _cli_codex_cfg() -> LLMConfig:
    return LLMConfig(
        api_key="cli-backend", base_url="", model="api-fallback",
        channel="cli", cli_runner="codex", cli_model="gpt-5.5",
    )


def _so_json(**fields) -> str:
    base = {
        "标题": "密查",
        "内容": "TASK_BODY",
        "承办人": "",
        "期限月数": 0,
        "标签": [],
    }
    base.update(fields)
    return json.dumps(base, ensure_ascii=False)


def _patch_backend(monkeypatch, payload: str):
    monkeypatch.setattr(cb, "_run_backend", lambda p: (payload, 1))


def _resolve_secret(monkeypatch, reply: str, message: str, *, default="王在晋",
                    payload: str | None = None, secret_context: str = ""):
    if payload is not None:
        _patch_backend(monkeypatch, payload)
    kw = {}
    if secret_context:
        kw["secret_context"] = secret_context
    return cb.resolve_minister_actions(
        reply, message, default_assignee=default, **kw,
    )["secret_order"]


# ── resolve_minister_actions：拟旨/密令前缀分派 ──

def test_draft_prefix_captures_reply():
    reply = "REPLY_DECREE_BODY"
    acts = cb.resolve_minister_actions(
        reply, "拟旨如下：INTENT_DRAFT", default_assignee="毕自严",
    )
    assert acts["decree_text"] == reply
    assert acts["secret_order"] is None


def test_no_prefix_no_action():
    acts = cb.resolve_minister_actions(
        "REPLY_PLAIN", "MSG_PLAIN", default_assignee="王在晋",
    )
    assert acts["decree_text"] is None
    assert acts["secret_order"] is None


def test_secret_prefix_merges_emperor_intent_with_reply(monkeypatch):
    """显式密令前缀 + 大臣回话 → 结构化密令；prompt 同时见御旨与回话。"""
    task, person = "查辽东军饷有无侵冒", "李若琏"
    captured = {}

    def fake_run(prompt):
        captured["prompt"] = prompt
        return (_so_json(
            标题="密查辽东军饷",
            内容=f"{task}，着{person}暗查。",
            承办人=person,
            期限月数=3,
            标签=["辽饷"],
        ), 1)

    monkeypatch.setattr(cb, "_run_backend", fake_run)
    so = cb.resolve_minister_actions(
        f"臣领密旨，可授{person}暗查。",
        f"密令如下：{task}，三月内回奏",
        default_assignee="王在晋",
    )["secret_order"]
    assert so is not None
    assert task in captured["prompt"]
    assert person in captured["prompt"]
    assert task in so["content"] and person in so["content"]
    assert so["assignee"] == person
    assert so["deadline_months"] == 3


def test_secret_exclusion_extracts_people_and_offices(monkeypatch):
    canned = json.dumps({
        "标题": "密查",
        "内容": "查账",
        "承办人": "毕自严",
        "排除对象": {"人物": ["魏忠贤"], "机构": ["司礼监"]},
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_backend", lambda p: (canned, 1))
    result = cb._extract_secret_order("密查账目", "臣领旨", "毕自严")
    assert result["excluded_names"] == ["魏忠贤"]
    assert result["excluded_offices"] == ["司礼监"]
    assert result["excluded_targets"] == {"people": ["魏忠贤"], "offices": ["司礼监"]}


def test_extract_secret_order_preserves_long_title_without_formal_cap(monkeypatch):
    long_title = "查核辽饷转运与沿途侵蚀及军粮实数并追索责任官员"
    assert len(long_title) > 20
    canned = _so_json(标题=long_title, 内容="查明事实并回奏。", 承办人="毕自严", 标签=["辽饷"])

    def fake_json_extractor(prompt, llm_config=None, tag=""):
        return canned, 1

    monkeypatch.setattr(cb, "_run_json_extractor_for_config", fake_json_extractor)
    result = cb._extract_secret_order(
        f"密令如下：{long_title}\n查明事实并回奏。", "臣领密旨", "毕自严",
    )
    assert result["title"] == long_title
    assert len(result["title"]) == len(long_title)


def test_secret_exclusion_recovery_splits_each_explicit_person(monkeypatch):
    monkeypatch.setattr(cb, "_run_backend", lambda _prompt: ("{}", 1))
    result = cb._extract_secret_order(
        "密查此案，瞒住魏忠贤、王体乾和曹化淳，勿使他们知晓。", "臣领旨", "毕自严"
    )
    assert result["excluded_names"] == ["魏忠贤", "王体乾", "曹化淳"]


@pytest.mark.parametrize("wording", ["对魏忠贤保密", "莫让魏忠贤知晓"])
def test_secret_exclusion_recovery_covers_target_first_and_imperative(wording, monkeypatch):
    monkeypatch.setattr(cb, "_run_backend", lambda _prompt: ("{}", 1))
    result = cb._extract_secret_order(f"密查此案，{wording}。", "臣领旨", "毕自严")
    assert result["excluded_names"] == ["魏忠贤"]


def test_secret_exclusion_recovery_covers_common_clause_and_shipped_office(monkeypatch):
    monkeypatch.setattr(cb, "_run_backend", lambda _prompt: ("{}", 1))
    result = cb._extract_secret_order(
        "密查此案，不得告知翰林院编修，亦不许户部尚书过问。", "臣领旨", "毕自严"
    )
    assert "翰林院编修" in result["excluded_offices"]
    assert "户部尚书" in result["excluded_offices"]


def test_secret_exclusion_recovery_covers_non_disclosure_clause(monkeypatch):
    monkeypatch.setattr(cb, "_run_backend", lambda _prompt: ("{}", 1))
    result = cb._extract_secret_order(
        "密查此案，不可令翰林院侍读学士知情。", "臣领旨", "毕自严"
    )
    assert result["excluded_names"] == []
    assert result["excluded_offices"] == ["翰林院侍读学士"]


def test_cli_and_durable_secret_exclusion_share_the_same_parser(game, monkeypatch):
    from ming_sim.db import canonical_secret_order_exclusions

    monkeypatch.setattr(cb, "_run_backend", lambda _prompt: ("{}", 1))
    cli = cb._extract_secret_order("密查账目，不走户部。", "臣领旨", "毕自严")
    people, offices = canonical_secret_order_exclusions(
        game[2], [], [], "密查账目，不走户部。"
    )
    assert cli["excluded_names"] == people == []
    assert cli["excluded_offices"] == offices == ["户部"]


def test_secret_prefix_deadline_only_confirmation_uses_recent_context(monkeypatch):
    """密令按钮只补期限时，从前文召对恢复任务正文（结构：content 含任务+期限+补充）。"""
    task = "查辽东军饷有无侵冒"
    material = "封存兵部辽饷册"
    deadline_bit = "三月内回奏"
    _patch_backend(monkeypatch, _so_json(
        标题="密查辽东军饷", 内容=deadline_bit, 承办人="", 期限月数=3, 标签=["辽饷"],
    ))
    so = _resolve_secret(
        monkeypatch, "臣领旨。", f"密令如下：{deadline_bit}",
        default="孙承宗",
        secret_context=(
            f"皇帝：{task}\n"
            f"大臣：可授李若琏暗查并{material}"
        ),
    )
    assert so is not None
    assert task in so["content"]
    assert deadline_bit in so["content"]
    assert material in so["content"]


@pytest.mark.parametrize(
    "case_id,llm_content,llm_assignee,reply,message,expect_bits,expect_assignee",
    [
        (
            "bad_llm_ack_content",
            "臣领密旨，可授李若琏暗查。",
            "李若琏",
            "臣领密旨，可授李若琏暗查。",
            "密令如下：查辽东军饷有无侵冒，三月内回奏",
            ("查辽东军饷有无侵冒", "李若琏"),
            "李若琏",
        ),
        (
            "partial_drops_deadline_clause",
            "查辽东军饷有无侵冒；着李若琏暗查。",
            "李若琏",
            "臣领密旨，可授李若琏暗查。",
            "密令如下：查辽东军饷有无侵冒，三月内回奏",
            ("查辽东军饷有无侵冒", "三月内回奏", "李若琏"),
            "李若琏",
        ),
        (
            "drops_minister_assignee",
            "查辽东军饷有无侵冒，三月内回奏",
            "",
            "臣领密旨，可授李若琏暗查。",
            "密令如下：查辽东军饷有无侵冒，三月内回奏",
            ("查辽东军饷有无侵冒", "李若琏"),
            "李若琏",
        ),
        (
            "assignee_field_ok_content_drops_name",
            "查辽东军饷有无侵冒，三月内回奏",
            "李若琏",
            "臣领密旨，可授李若琏暗查。",
            "密令如下：查辽东军饷有无侵冒，三月内回奏",
            ("查辽东军饷有无侵冒", "李若琏"),
            "李若琏",
        ),
        (
            "drops_non_assignee_supplements",
            "查辽东军饷有无侵冒，三月内回奏",
            "",
            "臣领密旨，须先封存兵部辽饷册，再密访关宁诸将。",
            "密令如下：查辽东军饷有无侵冒，三月内回奏",
            ("查辽东军饷有无侵冒", "三月内回奏", "封存兵部辽饷册", "密访关宁诸将"),
            "王在晋",
        ),
    ],
    ids=[
        "bad_llm_ack_content",
        "partial_drops_deadline_clause",
        "drops_minister_assignee",
        "assignee_field_ok_content_drops_name",
        "drops_non_assignee_supplements",
    ],
)
def test_secret_prefix_merge_guards(
    monkeypatch, case_id, llm_content, llm_assignee, reply, message,
    expect_bits, expect_assignee,
):
    """密令 merge 守门：坏/残 LLM 正文仍保留御旨与大臣实质补充（公开 resolve）。"""
    so = _resolve_secret(
        monkeypatch, reply, message,
        payload=_so_json(内容=llm_content, 承办人=llm_assignee, 期限月数=3, 标签=["辽饷"]),
    )
    assert so is not None
    for bit in expect_bits:
        assert bit in so["content"], (case_id, bit, so["content"])
    assert so["assignee"] == expect_assignee
    assert so["deadline_months"] == 3


@pytest.mark.parametrize(
    "action_verb,person,reply",
    [
        ("协办", "周延儒", "臣领密旨，可由周延儒协办此事。"),
        ("监督", "周延儒", "臣领密旨，可委周延儒监督此事。"),
        ("处理", "周延儒", "臣领密旨，可委周延儒处理。"),
        ("负责", "李若琏", "臣领密旨，可委李若琏负责。"),
    ],
    ids=["协办", "监督", "处理", "负责"],
)
def test_secret_action_verb_not_swallowed_by_generic_chengban(
    monkeypatch, action_verb, person, reply,
):
    """公开 resolve：LLM 把大臣动作词泛化成『承办』时，协办/监督/处理/负责须各自保留。"""
    task = "查辽东军饷有无侵冒"
    so = _resolve_secret(
        monkeypatch, reply, f"密令如下：{task}",
        payload=_so_json(
            内容=f"{task}，着{person}承办", 承办人=person, 期限月数=3, 标签=["辽饷"],
        ),
    )
    assert so is not None
    assert task in so["content"]
    assert action_verb in so["content"], (action_verb, so["content"])
    assert so["assignee"] == person


def test_secret_assignee_defaults_when_unspecified(monkeypatch):
    so = _resolve_secret(
        monkeypatch, "臣领旨。", "密令如下：去查",
        default="毕自严",
        payload=_so_json(标题="去查", 内容="去查某事"),
    )
    assert so["assignee"] == "毕自严"


def test_secret_ack_only_reply_does_not_force_merge(monkeypatch):
    """纯领命回话无实质补充 → 守门放行合法 LLM 正文，不强制并入领命噪声。"""
    task = "查辽东军饷有无侵冒，着李若琏暗查"
    so = _resolve_secret(
        monkeypatch, "领命。", f"密令如下：{task}",
        payload=_so_json(内容=task, 承办人="李若琏", 期限月数=3),
    )
    assert so is not None
    assert so["content"] == task
    assert "领命" not in so["content"]
    assert so["assignee"] == "李若琏"


@pytest.mark.parametrize(
    "reply",
    [
        "领命：可授李若琏暗查\n并封存兵部辽饷册。",
        "领命，即办。可授李若琏暗查并封存兵部辽饷册。",
        "谨遵。可授李若琏暗查并封存兵部辽饷册，三月内回奏。",
        "遵旨。可授李若琏暗查并封存兵部辽饷册。",
    ],
    ids=["colon_multiline", "领命_即办", "谨遵", "遵旨"],
)
def test_secret_mixed_ack_clauses_stripped_from_persisted_content(monkeypatch, reply):
    """混合领命+实质补充：分句剥领命后守门放行完整 LLM 正文；领命/即办/谨遵/遵旨不得入档。"""
    task, material = "查辽东军饷有无侵冒", "封存兵部辽饷册"
    llm_content = f"{task}，着李若琏暗查并{material}，三月内回奏"
    so = _resolve_secret(
        monkeypatch, reply, f"密令如下：{task}，三月内回奏",
        payload=_so_json(内容=llm_content, 承办人="李若琏", 期限月数=3),
    )
    assert so is not None
    assert so["content"] == llm_content
    assert task in so["content"] and material in so["content"]
    for ack in ("领命", "即办", "谨遵", "遵旨"):
        assert ack not in so["content"], (ack, so["content"])
    assert so["assignee"] == "李若琏"


def test_secret_repeated_assignee_name_accepts_clean_backend_content(monkeypatch):
    """公开 resolve：回话 speaker 前缀重复承办人名时，完整 LLM 正文须原样采纳、不并入噪声回话。"""
    task = "查辽东军饷有无侵冒"
    reply = "李若琏：可委派李若琏暗查并封存兵部辽饷册。"
    llm_content = f"{task}，着李若琏暗查并封存兵部辽饷册"
    so = _resolve_secret(
        monkeypatch, reply, f"密令如下：{task}",
        payload=_so_json(内容=llm_content, 承办人="李若琏", 期限月数=3),
    )
    assert so is not None
    assert so["content"] == llm_content
    assert "李若琏：" not in so["content"]
    assert so["assignee"] == "李若琏"


def test_secret_imperative_assignee_requires_command_boundary(monkeypatch):
    payload = _so_json(内容="查办辽饷", 承办人="")
    so_default = _resolve_secret(
        monkeypatch, "臣领旨。", "密令如下：此密令调查此事",
        default="毕自严", payload=payload,
    )
    assert so_default["assignee"] == "毕自严"
    so_named = _resolve_secret(
        monkeypatch, "臣领旨。", "密令如下：着李若琏查办辽饷",
        default="毕自严", payload=payload,
    )
    assert so_named["assignee"] == "李若琏"


def test_secret_assignee_does_not_drift_to_unvalidated_llm_field(monkeypatch):
    so = _resolve_secret(
        monkeypatch,
        "臣领密旨，可授李若琏暗查。",
        "密令如下：查辽东军饷有无侵冒，三月内回奏",
        payload=_so_json(
            内容="查辽东军饷有无侵冒，三月内回奏；着李若琏暗查。",
            承办人="王在晋", 期限月数=3, 标签=["辽饷"],
        ),
    )
    assert so is not None
    assert so["assignee"] == "李若琏"


def test_secret_assignee_prefers_hint_when_bad_llm_field_survives_merge(monkeypatch):
    so = _resolve_secret(
        monkeypatch,
        "臣领密旨，可授李若琏暗查。",
        "密令如下：查辽东军饷有无侵冒，三月内回奏",
        payload=_so_json(
            内容="查辽东军饷有无侵冒，三月内回奏；着王在晋暗查。",
            承办人="王在晋", 期限月数=3, 标签=["辽饷"],
        ),
    )
    assert so is not None
    assert "王在晋" in so["content"] and "李若琏" in so["content"]
    assert so["assignee"] == "李若琏"


def test_secret_assignee_uses_emperor_imperative_hint_when_llm_blank(monkeypatch):
    so = _resolve_secret(
        monkeypatch, "臣领旨。", "密令如下：着李若琏查辽东军饷有无侵冒",
        payload=_so_json(内容="查辽东军饷有无侵冒，着李若琏暗查。", 承办人="", 期限月数=3),
    )
    assert so is not None
    assert so["assignee"] == "李若琏"


@pytest.mark.parametrize(
    "reply,expect",
    [
        ("臣领密旨，可授曹化淳暗查东厂线索。", "曹化淳"),
        ("可委曹文诏征讨流贼。", "曹文诏"),
    ],
    ids=["cao_huachun", "cao_wenzhao"],
)
def test_secret_assignee_keeps_cao_surname_characters(monkeypatch, reply, expect):
    """公开 resolve：曹姓不得被机关字滤误拒（#397）。"""
    so = _resolve_secret(
        monkeypatch, reply, "密令如下：TASK_BODY",
        default="王在晋",
        payload=_so_json(内容="TASK_BODY", 承办人=""),
    )
    assert so is not None
    assert so["assignee"] == expect


def test_secret_assignee_keeps_wei_and_si_surnames(monkeypatch):
    """公开 resolve：卫/司 作姓保留；锦衣卫/布政司整词仍滤回默认。"""
    blank = _so_json(内容="TASK_BODY", 承办人="")
    so_wei = _resolve_secret(
        monkeypatch, "可授卫景瑗暗查东厂线索。", "密令如下：TASK_BODY",
        default="王在晋", payload=blank,
    )
    assert so_wei["assignee"] == "卫景瑗"
    so_si = _resolve_secret(
        monkeypatch, "可委司马懿督师。", "密令如下：TASK_BODY",
        default="王在晋", payload=blank,
    )
    assert so_si["assignee"] == "司马懿"
    so_jinyi = _resolve_secret(
        monkeypatch, "可授锦衣卫查办。", "密令如下：TASK_BODY",
        default="王在晋", payload=blank,
    )
    assert so_jinyi["assignee"] == "王在晋"
    so_buzheng = _resolve_secret(
        monkeypatch, "可授布政司核对。", "密令如下：TASK_BODY",
        default="王在晋", payload=blank,
    )
    assert so_buzheng["assignee"] == "王在晋"


@pytest.mark.parametrize(
    "reply",
    ["可委派李若琏暗查辽饷。", "可差派李若琏暗查辽饷。"],
    ids=["wei_pai", "chai_pai"],
)
def test_secret_assignee_prefers_long_compound_prefixes(monkeypatch, reply):
    """公开 resolve：可委派/可差派整前缀优先，『派』不并进人名。"""
    so = _resolve_secret(
        monkeypatch, reply, "密令如下：TASK_BODY",
        default="王在晋",
        payload=_so_json(内容="TASK_BODY", 承办人=""),
    )
    assert so is not None
    assert so["assignee"] == "李若琏"


# ── enrich_initiative_effects ──

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
    canned = json.dumps({
        "effect_on_resolve": {"buildings": [{"action": "create", "name": "格致局", "category": "科技"}]},
        "ongoing_effects": {}, "effect_on_fail": {},
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_agy", lambda prompt: (canned, 1))
    out = cb.enrich_initiative_effects("设格致局", "")
    assert out["effect_on_resolve"]["buildings"][0]["region_id"] == "beizhili"


def test_enrich_backend_error_returns_empty_effects(monkeypatch):
    monkeypatch.setattr(cb, "_run_backend", lambda p: (_ for _ in ()).throw(RuntimeError("backend down")))
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    out = cb.enrich_initiative_effects("设格致局", "")
    assert out == {"effect_on_resolve": {}, "ongoing_effects": {}, "effect_on_fail": {}}


def test_enrich_nondict_subfields_guarded(monkeypatch):
    monkeypatch.setattr(
        cb, "_run_backend",
        lambda p: ('{"effect_on_resolve": "坏数据", "ongoing_effects": ["x"], "effect_on_fail": 3}', 1),
    )
    monkeypatch.setattr(cb, "_trace", lambda r: None)
    out = cb.enrich_initiative_effects("设局", "")
    assert out == {"effect_on_resolve": {}, "ongoing_effects": {}, "effect_on_fail": {}}


def test_enrich_trace_records_actual_backend(monkeypatch):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    monkeypatch.setattr(cb, "_run_backend", lambda p: ('{"effect_on_resolve":{}}', 1))
    rec = {}
    monkeypatch.setattr(cb, "_trace", lambda r: rec.update(r))
    cb.enrich_initiative_effects("设局", "")
    assert rec.get("backend") == "codex"


# ── cli_backend_from_env / backend dispatch ──

def test_backend_env(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    assert cb.cli_backend_from_env() is None
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    assert cb.cli_backend_from_env() == "agy"


def test_backend_env_claude(monkeypatch):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "claude")
    assert cb.cli_backend_from_env() == "claude"


@pytest.mark.parametrize(
    "env,attr,out",
    [
        ("claude", "_run_claude", "CLAUDE_OUT"),
        (None, "_run_agy", "AGY_OUT"),
        ("codex", "_run_codex", "CODEX_OUT"),
    ],
)
def test_run_backend_dispatch(monkeypatch, env, attr, out):
    if env is None:
        monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    else:
        monkeypatch.setenv("MING_SIM_LLM_BACKEND", env)
    monkeypatch.setattr(cb, attr, lambda p: (out, 1))
    assert cb._run_backend("x") == (out, 1)


# ── secret extract keep family ──

def test_secret_extract_backend_error_falls_back(monkeypatch):
    monkeypatch.setattr(cb, "_run_backend", lambda p: (_ for _ in ()).throw(RuntimeError("backend down")))
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    acts = cb.resolve_minister_actions(
        "臣领密旨，暗查辽东军饷虚冒事。", "密令如下：查辽东军饷", default_assignee="王在晋",
    )
    so = acts["secret_order"]
    assert so is not None
    assert "查辽东军饷" in so["content"]
    assert "暗查辽东军饷虚冒事" in so["content"]
    assert so["assignee"] == "王在晋"
    assert so["deadline_months"] == 0


def test_secret_extract_recovers_explicit_exclusion_when_backend_omits_it(monkeypatch):
    monkeypatch.setattr(cb, "_run_backend", lambda _p: ('{"标题":"密查","内容":"查账"}', 1))
    result = cb._extract_secret_order("密查账目，瞒住魏忠贤。", "臣领旨", "毕自严")
    assert result["excluded_names"] == ["魏忠贤"]


def test_secret_extract_recovers_office_exclusion_when_backend_fails(monkeypatch):
    monkeypatch.setattr(cb, "_run_backend", lambda _p: ("{}", 1))
    result = cb._extract_secret_order("密查账目，不走户部。", "臣领旨", "毕自严")
    assert result["excluded_offices"] == ["户部"]


def test_secret_extract_merges_office_exclusion_when_backend_omits_it(monkeypatch):
    monkeypatch.setattr(cb, "_run_backend", lambda _p: ('{"标题":"密查","内容":"查账"}', 1))
    result = cb._extract_secret_order("密查账目，勿经户部。", "臣领旨", "毕自严")
    assert result["excluded_offices"] == ["户部"]


def test_secret_extract_classifies_institutional_knowledge_ban_as_office(monkeypatch):
    monkeypatch.setattr(cb, "_run_backend", lambda _p: ("{}", 1))
    result = cb._extract_secret_order("密查账目，勿使户部知晓。", "臣领旨", "毕自严")
    assert result["excluded_names"] == []
    assert result["excluded_offices"] == ["户部"]


def test_secret_extract_classifies_institutional_title_knowledge_ban_as_office(monkeypatch):
    monkeypatch.setattr(cb, "_run_backend", lambda _p: ("{}", 1))
    result = cb._extract_secret_order("密查账目，勿使户部诸官知晓。", "臣领旨", "毕自严")
    assert result["excluded_names"] == []
    assert result["excluded_offices"] == ["户部"]


def test_secret_extract_classifies_office_title_knowledge_ban_as_office(monkeypatch):
    monkeypatch.setattr(cb, "_run_backend", lambda _p: ("{}", 1))
    result = cb._extract_secret_order("密查账目，勿使户部尚书知晓。", "臣领旨", "毕自严")
    assert result["excluded_names"] == []
    assert result["excluded_offices"] == ["户部尚书"]


def test_secret_extract_classifies_grand_secretariat_title_knowledge_ban_as_office(monkeypatch):
    monkeypatch.setattr(cb, "_run_backend", lambda _p: ("{}", 1))
    result = cb._extract_secret_order("密查账目，勿使内阁首辅知晓。", "臣领旨", "毕自严")
    assert result["excluded_names"] == []
    assert result["excluded_offices"] == ["内阁首辅"]


@pytest.mark.parametrize("target", ["翰林院", "翰林院编修"])
def test_secret_extract_classifies_shipped_hanlin_targets_as_offices(monkeypatch, target):
    monkeypatch.setattr(cb, "_run_backend", lambda _p: ("{}", 1))
    result = cb._extract_secret_order(f"密查账目，勿使{target}知晓。", "臣领旨", "毕自严")
    assert result["excluded_names"] == []
    assert result["excluded_offices"] == [target]


# ── runner argv / error contracts (subprocess mocked) ──

class _P:
    def __init__(self, stdout="STDOUT_BODY", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def _capture_run(monkeypatch, proc=None):
    captured = {}
    proc = proc or _P()

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw
        if callable(proc):
            return proc(cmd, **kw)
        return proc

    monkeypatch.setattr(cb.subprocess, "run", fake_run)
    return captured


def test_run_claude_stdout_only(monkeypatch):
    body = "STDOUT_BODY"
    captured = _capture_run(monkeypatch, _P(stdout=body, stderr="LOG_NOISE"))
    out, attempts = cb._run_claude("PROMPT")
    assert out == body and attempts == 1
    assert "-p" in captured["cmd"] and "--model" in captured["cmd"]
    assert "--output-format" in captured["cmd"] and "text" in captured["cmd"]
    assert captured["kw"].get("env") is None


def test_run_codex_flags_and_stdout(monkeypatch):
    body = '{"k": []}'
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    captured = _capture_run(monkeypatch, _P(stdout=body, stderr="OpenAI Codex v0\nlogs"))
    out, n = cb._run_codex("p")
    assert out == body and n == 1
    assert "--skip-git-repo-check" in captured["cmd"]
    assert "--ephemeral" in captured["cmd"]
    assert "-c" not in captured["cmd"]


def test_codex_streaming_runner_degrades_to_oneshot_final(monkeypatch):
    captured = {}
    final = "STREAM_FINAL_BODY"

    class _Stdout:
        def __iter__(self):
            yield json.dumps({"type": "item.started", "item": {"type": "reasoning"}}) + "\n"
            yield json.dumps(
                {"type": "item.completed", "item": {"type": "agent_message", "text": final}}
            ) + "\n"

        def close(self):
            pass

    class _Proc:
        class _Stdin:
            def write(self, text):
                captured["input"] = text

            def close(self):
                captured["stdin_closed"] = True

        stdin = _Stdin()
        stdout = _Stdout()
        stderr = None
        returncode = 0

        def wait(self, timeout=None):
            captured["timeout"] = timeout
            self.returncode = 0
            return ("", "")

        def kill(self):
            captured["killed"] = True

    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    monkeypatch.setattr(cb.subprocess, "Popen", lambda cmd, **kw: captured.update(cmd=cmd, cwd=kw.get("cwd")) or _Proc())
    monkeypatch.setattr(cb, "_trace", lambda rec: None)

    chunks = []
    agent = Agent(
        name="stream-test", id="stream-test",
        model=cb.CliChat(id="gpt-test", backend="codex"),
        instructions=["only body"], markdown=False,
    )
    text = run_agent_stream_text(agent, "PROMPT_STREAM", "simulator", on_text=chunks.append)
    assert text == final
    assert chunks == [final]
    assert "--json" in captured["cmd"] and captured["cmd"][-1] == "-"
    assert "PROMPT_STREAM" in captured["input"]


def test_clichat_codex_response_stream_passes_reasoning_strength(monkeypatch):
    seen = {}

    def fake_chunks(prompt, *, model=None, timeout=None, reasoning_strength=None):
        seen["reasoning_strength"] = reasoning_strength
        yield "STREAM_CHUNK"

    monkeypatch.setattr(cb, "_iter_codex_stream_chunks", fake_chunks)
    chat = cb.CliChat(id="gpt-test", backend="codex", reasoning_strength="low")
    chunks = list(chat.response_stream([Message(role="user", content="PROMPT")]))
    assert [c.content for c in chunks if c.content] == ["STREAM_CHUNK"]
    assert seen["reasoning_strength"] == "low"


def test_api_backend_streaming_emits_real_token_deltas(monkeypatch):
    class _Ev:
        def __init__(self, content=None, is_final=False):
            self.content = content
            self.is_final = is_final

    class _FakeStreamAgent:
        model = SimpleNamespace(id="hermes-test")

        def run(self, prompt, stream=False, stream_events=False):
            assert stream and stream_events
            yield _Ev(content="A")
            yield _Ev(content="B")
            yield _Ev(content="C")
            yield _Ev(content=None, is_final=True)

        def get_last_run_output(self):
            return None

    chunks = []
    text = run_agent_stream_text(
        _FakeStreamAgent(), "PROMPT", "simulator", on_text=chunks.append
    )
    assert text == "ABC"
    assert chunks == ["A", "B", "C"]


def test_codex_stream_watchdog_kills_hung_process(monkeypatch):
    import threading as _t

    killed = _t.Event()

    class _HangStdout:
        def __iter__(self):
            killed.wait(5.0)
            return iter(())

        def close(self):
            pass

    class _Proc:
        class _Stdin:
            def write(self, text):
                pass

            def close(self):
                pass

        stdin = _Stdin()
        stdout = _HangStdout()
        stderr = None
        returncode = 0

        def wait(self, timeout=None):
            return ("", "")

        def kill(self):
            killed.set()
            self.returncode = -9

    monkeypatch.setattr(cb.subprocess, "Popen", lambda *a, **k: _Proc())
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    with pytest.raises(RuntimeError, match="超时"):
        list(cb._iter_codex_stream_chunks("PROMPT", timeout=0.2))
    assert killed.is_set()


def test_codex_final_text_handles_item_completed_shape():
    assert cb._codex_final_text(
        {"type": "item.completed", "item": {"type": "agent_message", "text": "BODY"}}
    ) == "BODY"
    assert cb._codex_final_text(
        {"type": "item.completed", "item": {"type": "reasoning", "text": "DRAFT"}}
    ) == ""
    assert cb._codex_final_text({"type": "agent_message", "message": "TOP"}) == "TOP"


@pytest.mark.parametrize(
    "runner,kwargs,model_flag,timeout",
    [
        ("_run_codex", {"model": "gpt-configured", "timeout": 123}, "gpt-configured", 123),
        ("_run_claude", {"model": "claude-configured", "timeout": 234}, "claude-configured", 234),
    ],
)
def test_run_runner_accepts_config_model_and_timeout(monkeypatch, runner, kwargs, model_flag, timeout):
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    captured = _capture_run(monkeypatch, _P(stdout="STDOUT_BODY"))
    out, n = getattr(cb, runner)("p", **kwargs)
    assert out == "STDOUT_BODY" and n == 1
    assert captured["cmd"][captured["cmd"].index("--model") + 1] == model_flag
    assert captured["kw"]["timeout"] == timeout


def test_run_codex_reasoning_env_optional(monkeypatch):
    monkeypatch.setenv("MING_SIM_CODEX_REASONING", "medium")
    captured = _capture_run(monkeypatch)
    cb._run_codex("p")
    joined = " ".join(captured["cmd"])
    assert "-c" in captured["cmd"]
    assert "model_reasoning_effort" in joined and "medium" in joined


def test_run_codex_maps_reasoning_strength_to_native_effort(monkeypatch):
    monkeypatch.setenv("MING_SIM_CODEX_REASONING", "medium")
    captured = _capture_run(monkeypatch)
    cb._run_codex("p", reasoning_strength="high")
    joined = " ".join(captured["cmd"])
    assert 'model_reasoning_effort="xhigh"' in joined
    assert 'model_reasoning_effort="medium"' not in joined


def test_run_codex_stdout_empty_fallback(monkeypatch):
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    monkeypatch.setattr(
        cb.subprocess, "run",
        lambda cmd, **kw: _P(stdout="", stderr="STDOUT_BODY\nOpenAI Codex v0.125.0\nlogs"),
    )
    out, n = cb._run_codex("p")
    assert out == "STDOUT_BODY"


def test_run_claude_maps_reasoning_strength_to_thinking_tokens(monkeypatch):
    monkeypatch.setenv("MAX_THINKING_TOKENS", "32000")
    captured = _capture_run(monkeypatch)
    out, n = cb._run_claude("p", reasoning_strength="medium")
    assert out == "STDOUT_BODY"
    assert captured["kw"]["env"]["MAX_THINKING_TOKENS"] == "10000"


def test_run_claude_off_reasoning_uses_explicit_minimum_tokens(monkeypatch):
    monkeypatch.setenv("MAX_THINKING_TOKENS", "32000")
    captured = _capture_run(monkeypatch)
    out, n = cb._run_claude("p", reasoning_strength="off")
    assert out == "STDOUT_BODY"
    assert captured["kw"]["env"]["MAX_THINKING_TOKENS"] == "2000"


# ── _resolve_cli_bin / login shell path ──

def test_resolve_cli_bin_found_on_current_path(monkeypatch):
    monkeypatch.setattr(
        cb.shutil, "which",
        lambda name, path=None: "/usr/local/bin/codex" if path is None else None,
    )
    monkeypatch.setattr(cb, "_login_shell_path", lambda: (_ for _ in ()).throw(AssertionError("no")))
    assert cb._resolve_cli_bin("codex", "codex") == "/usr/local/bin/codex"


def test_resolve_cli_bin_found_via_extra_dirs_when_gui_path_bare(monkeypatch):
    monkeypatch.setattr(cb, "_EXTRA_BIN_DIRS", ["/fake/extra/bin"])
    monkeypatch.setattr(cb.os.path, "isdir", lambda p: True)
    home_bin = "/fake/extra/bin/codex"

    def fake_which(name, path=None):
        if path is None:
            return None
        assert "/fake/extra/bin" in path
        return home_bin

    login_calls = {"n": 0}

    def spy_login():
        login_calls["n"] += 1
        return None

    monkeypatch.setattr(cb.shutil, "which", fake_which)
    monkeypatch.setattr(cb, "_login_shell_path", spy_login)
    assert cb._resolve_cli_bin("codex", "codex") == home_bin
    assert login_calls["n"] == 0


def test_resolve_cli_bin_login_shell_path_last_resort(monkeypatch):
    cb._BIN_CACHE.clear()

    def fake_which(name, path=None):
        if path and "/opt/odd/bin" in path:
            return "/opt/odd/bin/codex"
        return None

    monkeypatch.setattr(cb.shutil, "which", fake_which)
    monkeypatch.setattr(cb, "_login_shell_path", lambda: "/opt/odd/bin")
    assert cb._resolve_cli_bin("codex", "codex") == "/opt/odd/bin/codex"


def test_resolve_cli_bin_falls_back_and_miss_not_cached(monkeypatch):
    cb._BIN_CACHE.clear()
    monkeypatch.setattr(cb, "_login_shell_path", lambda: None)
    monkeypatch.setattr(cb.shutil, "which", lambda name, path=None: None)
    assert cb._resolve_cli_bin("codex", "codex") == "codex"
    assert "codex" not in cb._BIN_CACHE
    monkeypatch.setattr(
        cb.shutil, "which",
        lambda name, path=None: "/Users/x/.local/bin/codex" if path is None else None,
    )
    assert cb._resolve_cli_bin("codex", "codex") == "/Users/x/.local/bin/codex"


def test_resolve_cli_bin_caches(monkeypatch):
    cb._BIN_CACHE.clear()
    calls = {"n": 0}

    def fake_which(name, path=None):
        calls["n"] += 1
        return "/abs/codex"

    monkeypatch.setattr(cb.shutil, "which", fake_which)
    monkeypatch.setattr(cb, "_login_shell_path", lambda: None)
    assert cb._resolve_cli_bin("codex", "codex") == "/abs/codex"
    assert cb._resolve_cli_bin("codex", "codex") == "/abs/codex"
    assert calls["n"] == 1


def test_login_shell_path_extracts_from_sentinels_despite_noise(monkeypatch):
    monkeypatch.setattr(cb, "_DISCOVERED_LOGIN_PATH", None)

    class _R:
        stdout = (
            "Warning: /usr/local/bin not writable: skipping\n"
            "<<<CMRPATH>>>/Users/x/.local/bin:/opt/homebrew/bin:/usr/bin<<<ENDPATH>>>\n"
        )
        stderr = ""
        returncode = 0

    monkeypatch.setattr(cb, "_RAW_RUN", lambda *a, **k: _R())
    assert cb._login_shell_path() == "/Users/x/.local/bin:/opt/homebrew/bin:/usr/bin"


def test_login_shell_path_single_dir_not_dropped(monkeypatch):
    monkeypatch.setattr(cb, "_DISCOVERED_LOGIN_PATH", None)

    class _R:
        stdout = "<<<CMRPATH>>>/usr/bin<<<ENDPATH>>>\n"
        stderr = ""
        returncode = 0

    monkeypatch.setattr(cb, "_RAW_RUN", lambda *a, **k: _R())
    assert cb._login_shell_path() == "/usr/bin"


def test_login_shell_path_uses_printenv_not_dollar_path(monkeypatch):
    monkeypatch.setattr(cb, "_DISCOVERED_LOGIN_PATH", None)
    captured = {}

    class _R:
        stdout = "<<<CMRPATH>>>/a/bin:/b/bin<<<ENDPATH>>>"
        stderr = ""
        returncode = 0

    monkeypatch.setattr(cb, "_RAW_RUN", lambda cmd, **kw: captured.update(cmd=cmd) or _R())
    assert cb._login_shell_path() == "/a/bin:/b/bin"
    joined = " ".join(captured["cmd"])
    assert "printenv PATH" in joined
    assert '"$PATH"' not in joined
    assert "-lic" not in captured["cmd"]
    assert {"-l", "-i", "-c"} <= set(captured["cmd"])


def test_resolve_cli_bin_absolutizes_relative_result(monkeypatch):
    monkeypatch.setattr(cb, "_login_shell_path", lambda: None)
    monkeypatch.setattr(
        cb.shutil, "which",
        lambda name, path=None: "./bin/codex" if path is None else None,
    )
    result = cb._resolve_cli_bin("codex", "./bin/codex")
    assert cb.os.path.isabs(result)
    assert result == cb.os.path.abspath("./bin/codex")


@pytest.mark.parametrize(
    "runner,resolved",
    [
        ("_run_codex", "/Users/x/.local/bin/codex"),
        ("_run_claude", "/opt/homebrew/bin/claude"),
        ("_run_agy", "/Users/x/.local/bin/agy"),
    ],
)
def test_run_runner_execs_resolved_abspath(monkeypatch, runner, resolved):
    cb._BIN_CACHE.clear()
    monkeypatch.setattr(cb, "_resolve_cli_bin", lambda name, configured: resolved)
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    seen = {}

    def fake_run(cmd, **kw):
        if cmd and cmd[0] == "security":
            return _P()
        seen["cmd"] = cmd
        return _P(stdout="STDOUT_BODY")

    monkeypatch.setattr(cb.subprocess, "run", fake_run)
    getattr(cb, runner)("p")
    assert seen["cmd"][0] == resolved


# ── extract_minister_actions ──

def test_extract_minister_actions_update(monkeypatch):
    canned = json.dumps({
        "密令动作": "更新", "目标密令编号": 6,
        "新标题": "拨内库补边军欠饷", "新内容": "每月内库百万、半年通计六百万，按月御前领发",
        "期限月数": 6,
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_backend", lambda p: (canned, 1))
    act = cb.extract_minister_actions(
        "记得更新你的密令。是每月100万内库", "臣已记明，改按月月百万",
        [{"id": 6, "title": "拨内库百万补边军欠饷", "content": "限期半年"}], is_consort=False,
    )
    assert act["secret_action"] == "更新"
    assert act["order_id"] == 6
    assert "月月百万" in act["new_content"] or "每月" in act["new_content"]


def test_extract_minister_actions_preserves_long_new_title(monkeypatch):
    long_title = "查核辽饷转运与沿途侵蚀及军粮实数并追索责任官员"
    assert len(long_title) > 20
    canned = json.dumps({
        "密令动作": "更新", "目标密令编号": 6,
        "新标题": long_title, "新内容": "查明事实并回奏",
        "期限月数": 3,
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_backend", lambda p: (canned, 1))
    act = cb.extract_minister_actions(
        "把标题改全些", "臣遵旨",
        [{"id": 6, "title": "旧标题", "content": "旧内容"}], is_consort=False,
    )
    assert act["secret_action"] == "更新"
    assert act["new_title"] == long_title
    assert len(act["new_title"]) == len(long_title)


def test_extract_minister_actions_none(monkeypatch):
    monkeypatch.setattr(cb, "_run_backend", lambda p: ('{"密令动作":"无","目标密令编号":0}', 1))
    act = cb.extract_minister_actions("MSG", "REPLY", [{"id": 6, "title": "x", "content": "y"}])
    assert act["secret_action"] == "无"


def test_extract_minister_actions_cultivate(monkeypatch):
    canned = json.dumps(
        {"密令动作": "无", "目标密令编号": 0, "调教技能": "书法精通", "调教性格": "更温婉"},
        ensure_ascii=False,
    )
    monkeypatch.setattr(cb, "_run_backend", lambda p: (canned, 1))
    act = cb.extract_minister_actions("教你书法，望你更温婉", "妾领旨", [], is_consort=True)
    assert act["cultivate_skill"] == "书法精通"
    assert act["cultivate_trait"] == "更温婉"


def test_extract_minister_actions_backend_error_safe(monkeypatch):
    monkeypatch.setattr(cb, "_run_backend", lambda p: (_ for _ in ()).throw(RuntimeError("backend down")))
    act = cb.extract_minister_actions("随便", "臣以为", [{"id": 6, "title": "x", "content": "y"}])
    assert act["secret_action"] == "无"
    assert act["order_id"] == 0


def test_extract_minister_actions_nonint_ids_floor_to_zero(monkeypatch):
    canned = json.dumps(
        {"密令动作": "催办", "目标密令编号": "六号", "期限月数": "三个月"},
        ensure_ascii=False,
    )
    monkeypatch.setattr(cb, "_run_backend", lambda p: (canned, 1))
    act = cb.extract_minister_actions("催一下", "臣加紧", [{"id": 6, "title": "x", "content": "y"}])
    assert act["secret_action"] == "催办"
    assert act["order_id"] == 0
    assert act["deadline_months"] == 0


def test_extract_minister_actions_unknown_action_floored(monkeypatch):
    canned = json.dumps({"密令动作": "乱填的动作", "目标密令编号": 6}, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_backend", lambda p: (canned, 1))
    act = cb.extract_minister_actions("x", "y", [{"id": 6, "title": "t", "content": "c"}])
    assert act["secret_action"] == "无"


# ── lenient JSON via public extract seam ──

@pytest.mark.parametrize(
    "raw,expect_action,expect_order_id",
    [
        ('{"密令动作":"更新","目标密令编号":6}', "更新", 6),
        ('```json\n{"密令动作":"更新","目标密令编号":6}\n```', "更新", 6),
        ('note {"密令动作":"更新","目标密令编号":6} tail', "更新", 6),
        ("NOT_JSON", "无", 0),
        ("prefix {bad: json,} suffix", "无", 0),
        ('{\n  "密令动作": "更新", // c\n  "目标密令编号": 6,\n}', "更新", 6),
        ('{"密令动作":"更新","目标密令编号":6,}', "更新", 6),
    ],
)
def test_extract_parses_lenient_backend_json(monkeypatch, raw, expect_action, expect_order_id):
    """_loads_lenient 契约经 extract_minister_actions 公开出口观察。"""
    monkeypatch.setattr(cb, "_run_backend", lambda p: (raw, 1))
    act = cb.extract_minister_actions("x", "y", [{"id": 6, "title": "t", "content": "c"}])
    assert act["secret_action"] == expect_action
    assert act["order_id"] == expect_order_id


@pytest.mark.parametrize(
    "raw,expect_new_content",
    [
        # 外层尾逗号/注释迫使走 JSONC cleaner；串内 //、URL、,}、转义引号须原样进入 new_content
        ('{"密令动作":"更新","目标密令编号":6,"新内容":"a//b",}', "a//b"),
        ('{"密令动作":"更新","目标密令编号":6,"新内容":"http://x.com//y",}', "http://x.com//y"),
        ('{"密令动作":"更新","目标密令编号":6,"新内容":"x,}",}', "x,}"),
        ('{"密令动作":"更新","目标密令编号":6,"新内容":"he said \\"hi\\" //x",}', 'he said "hi" //x'),
        (
            '{\n  "密令动作": "更新", // c\n  "目标密令编号": 6,\n  "新内容": "a//b",\n}',
            "a//b",
        ),
    ],
    ids=["slash_in_string", "url_in_string", "comma_brace_in_string",
         "escaped_quote_slash", "comment_plus_slash_string"],
)
def test_extract_lenient_cleaner_preserves_quoted_delimiters(
    monkeypatch, raw, expect_new_content,
):
    """畸形外层分隔迫使 quote-aware 清洗；消费字段 new_content 保留串内精确字节。"""
    monkeypatch.setattr(cb, "_run_backend", lambda p: (raw, 1))
    act = cb.extract_minister_actions("x", "y", [{"id": 6, "title": "t", "content": "c"}])
    assert act["secret_action"] == "更新"
    assert act["order_id"] == 6
    assert act["new_content"] == expect_new_content


def test_extract_preserves_array_trailing_comma_via_loads_path(monkeypatch):
    """数组尾逗号清洗仍可达（dict 根 + 嵌套数组）。"""
    raw = '{"密令动作":"更新","目标密令编号":6,"xs":[1, 2, ]}'
    monkeypatch.setattr(cb, "_run_backend", lambda p: (raw, 1))
    act = cb.extract_minister_actions("x", "y", [{"id": 6, "title": "t", "content": "c"}])
    assert act["secret_action"] == "更新"
    assert act["order_id"] == 6


# ── CliChat public: prompt shape + narration strip + dispatch ──

def test_clichat_invoke_builds_prompt_and_strips_narration(monkeypatch):
    cc = cb.CliChat(id="cli-test", backend="agy")
    seen = {}

    def fake_cli(prompt):
        seen["prompt"] = prompt
        return ("I will check the files.\nBODY_ZH_REPLY", 1)

    monkeypatch.setattr(cc, "_call_cli", fake_cli)
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    captured = {}
    real_fake = cb._fake_completion

    def spy(text, model_id, *a, **k):
        captured["text"] = text
        return real_fake(text, model_id, *a, **k)

    monkeypatch.setattr(cb, "_fake_completion", spy)
    msgs = [
        SimpleNamespace(role="system", content="SYS_ROLE"),
        SimpleNamespace(role="user", content="USER_MSG"),
        SimpleNamespace(role="user", content="   "),
        SimpleNamespace(role="assistant", content=None),
        SimpleNamespace(role="assistant", content="PRIOR_ASST"),
        SimpleNamespace(role="tool", content="TOOL_OUT"),
        SimpleNamespace(role="developer", content=12345),
    ]
    cc.invoke(msgs, Message(role="assistant"))
    p = seen["prompt"]
    # role tags + order (structural markers, not free prose pins beyond tag keys)
    for tag in ("【系统设定】", "【皇帝/输入】", "【你此前的回答】", "【工具结果】", "【developer】"):
        assert tag in p
    assert p.index("【系统设定】") < p.index("【皇帝/输入】")
    assert p.count("【皇帝/输入】") == 1  # blank skipped
    assert "【你此前的回答】" in p and "PRIOR_ASST" in p
    assert "12345" in p
    assert "【执行约束·必读】" in p
    assert captured["text"] == "BODY_ZH_REPLY"


def test_clichat_invoke_all_narration_falls_back_to_original(monkeypatch):
    """全英文 narration 无中文正文 → strip 退回原文，非空 completion 抵达 _fake_completion。"""
    cc = cb.CliChat(id="cli-test", backend="agy")
    raw = "I will do this.\nLet me start."
    monkeypatch.setattr(cc, "_call_cli", lambda p: (raw, 1))
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    captured = {}
    real_fake = cb._fake_completion

    def spy(text, model_id, *a, **k):
        captured["text"] = text
        return real_fake(text, model_id, *a, **k)

    monkeypatch.setattr(cb, "_fake_completion", spy)
    cc.invoke(
        [SimpleNamespace(role="user", content="USER_MSG")],
        Message(role="assistant"),
    )
    assert captured["text"] == raw.strip()
    assert captured["text"]  # nonempty fail-safe, not emptied by strip


def test_clichat_invoke_json_constraint_and_no_constraint(monkeypatch):
    cc = cb.CliChat(id="cli-test", backend="agy")
    seen = []

    def fake_cli(prompt):
        seen.append(prompt)
        return ("{}", 1)

    monkeypatch.setattr(cc, "_call_cli", fake_cli)
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    msgs = [SimpleNamespace(role="user", content="EXTRACT")]
    cc.invoke(msgs, Message(role="assistant"), response_format={"type": "json_object"})
    assert "【输出格式硬约束】" in seen[0]

    class _RF(BaseModel):
        x: int = 0

    cc.invoke(msgs, Message(role="assistant"), response_format=_RF)
    assert "【输出格式硬约束】" in seen[1]

    cc.invoke(msgs, Message(role="assistant"))
    assert "【输出格式硬约束】" not in seen[2]
    assert "【执行约束·必读】" in seen[2]


def test_clichat_invoke_error_traced_and_reraised(monkeypatch):
    """#1299/#1310：runner 失败翻 typed LLMUnavailable；trace 仍记机器原文。"""
    from ming_sim.exceptions import LLMUnavailable
    cc = cb.CliChat(id="cli-test", backend="agy")
    monkeypatch.setattr(cc, "_call_cli", lambda p: (_ for _ in ()).throw(RuntimeError("cli down")))
    traced = {}
    monkeypatch.setattr(cb, "_trace", lambda rec: traced.update(rec))
    with pytest.raises(LLMUnavailable) as ei:
        cc.invoke([SimpleNamespace(role="user", content="x")], Message(role="assistant"))
    assert traced.get("error") == "cli down"
    assert "cli down" in (ei.value.provider_message or "")
    assert "cli down" not in ei.value.message


def test_clichat_call_cli_dispatch(monkeypatch):
    seen = {}

    def fake_codex(p, model=None, timeout=None, **kwargs):
        seen["codex"] = (model, timeout)
        return ("CODEX", 1)

    def fake_claude(p, model=None, timeout=None, **kwargs):
        seen["claude"] = (model, timeout)
        return ("CLAUDE", 1)

    def fake_agy(p, timeout=None):
        seen["agy"] = timeout
        return ("AGY", 1)

    monkeypatch.setattr(cb, "_run_codex", fake_codex)
    monkeypatch.setattr(cb, "_run_claude", fake_claude)
    monkeypatch.setattr(cb, "_run_agy", fake_agy)
    assert cb.CliChat(id="m-codex", backend="codex", timeout=111)._call_cli("p") == ("CODEX", 1)
    assert cb.CliChat(id="m-claude", backend="claude", timeout=222)._call_cli("p") == ("CLAUDE", 1)
    assert cb.CliChat(id="m-agy", backend="agy", timeout=333)._call_cli("p") == ("AGY", 1)
    assert seen["codex"] == ("m-codex", 111)
    assert seen["claude"] == ("m-claude", 222)
    assert seen["agy"] == 333


def test_clichat_call_cli_unknown_backend_raises():
    with pytest.raises(RuntimeError):
        cb.CliChat(id="m", backend="bogus")._call_cli("p")


# ── agy warm+retry / runner fail-loud ──

class _Proc:
    def __init__(self, stdout="", stderr=""):
        self.stdout, self.stderr, self.returncode = stdout, stderr, 0


def _agy_fake(script):
    state = {"agy": 0, "warm": 0}

    def fake_run(cmd, **kw):
        if cmd and cmd[0] == "security":
            state["warm"] += 1
            return _Proc()
        i = state["agy"]
        state["agy"] += 1
        kind, text = script[min(i, len(script) - 1)]
        if kind == "timeout":
            raise cb.subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        if kind == "auth":
            return _Proc(stdout=text or "Authentication required")
        return _Proc(stdout=text)

    return fake_run, state


def test_run_agy_success_first_attempt(monkeypatch):
    fake, state = _agy_fake([("ok", "STDOUT_BODY")])
    monkeypatch.setattr(cb.subprocess, "run", fake)
    out, attempts = cb._run_agy("PROMPT")
    assert out == "STDOUT_BODY" and attempts == 1
    assert state["warm"] >= 1


def test_run_agy_auth_race_then_success(monkeypatch):
    fake, state = _agy_fake([
        ("auth", "Authentication required"),
        ("auth", "authentication timed out"),
        ("ok", "STDOUT_BODY"),
    ])
    monkeypatch.setattr(cb.subprocess, "run", fake)
    out, attempts = cb._run_agy("p")
    assert out == "STDOUT_BODY" and attempts == 3
    assert state["warm"] == 3


def test_run_agy_all_timeout_raises(monkeypatch):
    fake, _ = _agy_fake([("timeout", "")])
    monkeypatch.setattr(cb.subprocess, "run", fake)
    with pytest.raises(RuntimeError, match="warm\\+retry"):
        cb._run_agy("p")


def test_run_agy_all_auth_fail_raises(monkeypatch):
    fake, state = _agy_fake([("auth", "Authentication required")])
    monkeypatch.setattr(cb.subprocess, "run", fake)
    with pytest.raises(RuntimeError):
        cb._run_agy("p")
    assert state["agy"] == 4


@pytest.mark.parametrize("runner", ["_run_codex", "_run_claude"])
def test_run_runner_timeout_raises(monkeypatch, runner):
    def boom(cmd, **kw):
        raise cb.subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    monkeypatch.setattr(cb.subprocess, "run", boom)
    with pytest.raises(RuntimeError, match="超时"):
        getattr(cb, runner)("p")


class _RcProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


@pytest.mark.parametrize(
    "runner,proc",
    [
        ("_run_codex", lambda: _RcProc(stderr="error: auth failed", returncode=1)),
        ("_run_codex", lambda: _RcProc(returncode=0)),  # empty output
        ("_run_claude", lambda: _RcProc(stderr="auth required", returncode=1)),
    ],
)
def test_run_runner_fail_loud_on_bad_exit_or_empty(monkeypatch, runner, proc):
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    monkeypatch.setattr(cb.subprocess, "run", lambda cmd, **kw: proc())
    with pytest.raises(RuntimeError):
        getattr(cb, runner)("p")


def test_run_agy_nonzero_exit_retries_then_raises(monkeypatch):
    state = {"agy": 0, "warm": 0}

    def fake(cmd, **kw):
        if cmd and cmd[0] == "security":
            state["warm"] += 1
            return _RcProc()
        state["agy"] += 1
        return _RcProc(stderr="agy boom", returncode=1)

    monkeypatch.setattr(cb.subprocess, "run", fake)
    with pytest.raises(RuntimeError):
        cb._run_agy("p")
    assert state["agy"] == 4


# ── trace throat ──

@pytest.mark.parametrize(
    "prompt,expect_tag",
    [
        ("你扮演被皇帝召见的大臣，回话……", "minister"),
        ('起居注……本朝章节……"body" tags 整理', "chapter_memory"),
        ("本月结算抽取，输出 delta……", "extractor"),
        ("simulator_payload: 当前盘面 TSV……", "simulator"),
        ("请拟一道诏书，颁行天下", "decree"),
        ("只输出合法 JSON，无多余字", "sanitizer"),
        ("今日天气如何", "other"),
        # 优先级：minister 先于 decree；chapter_memory 先于 extractor（须同框 extractor 标识）
        ("你扮演被皇帝召见的大臣，臣请拟诏书一道……", "minister"),
        (
            '【起居注】崇祯二年……本卷章节……"body": "…" tags: […]'
            " 本月结算抽取 module_allowed_fields score_extractor",
            "chapter_memory",
        ),
    ],
    ids=[
        "minister", "chapter_memory", "extractor", "simulator",
        "decree", "sanitizer", "other",
        "minister_over_decree", "chapter_memory_before_extractor",
    ],
)
def test_run_backend_infers_trace_tag_from_prompt(monkeypatch, prompt, expect_tag):
    """公共咽喉 _run_backend_for_config：tag 空时从 prompt 推断 trace.tag（不直测 helper）。"""
    recs = []
    monkeypatch.setattr(cb, "_trace", lambda rec: recs.append(rec))
    monkeypatch.setattr(
        cb, "_run_codex",
        lambda prompt, model=None, timeout=None, **kwargs: ("ok", 1),
    )
    cb._run_backend_for_config(prompt, _cli_codex_cfg())  # no explicit tag
    assert len(recs) == 1
    assert recs[0]["tag"] == expect_tag


def test_run_backend_for_config_traces_every_call(monkeypatch):
    recs = []
    monkeypatch.setattr(cb, "_trace", lambda rec: recs.append(rec))
    monkeypatch.setattr(cb, "_run_codex", lambda prompt, model=None, timeout=None, **kwargs: ("外臣", 1))
    out, attempts = cb._run_backend_for_config("判官名：后金汗", _cli_codex_cfg(), tag="office_infer")
    assert out == "外臣" and attempts == 1
    assert len(recs) == 1
    r = recs[0]
    assert r["tag"] == "office_infer"
    assert "后金汗" in r["prompt"] and r["response"] == "外臣"
    assert r["backend"] == "codex" and r["error"] is None


def test_run_backend_for_config_passes_reasoning_strength_to_codex(monkeypatch):
    seen = {}

    def fake_codex(prompt, model=None, timeout=None, reasoning_strength=None):
        seen["reasoning_strength"] = reasoning_strength
        return "外臣", 1

    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    monkeypatch.setattr(cb, "_run_codex", fake_codex)
    cfg = SimpleNamespace(
        channel="cli", cli_runner="codex", cli_model="gpt-5.5",
        cli_timeout_seconds=240, reasoning_strength="low",
    )
    cb._run_backend_for_config("判官名：后金汗", cfg, tag="office_infer")
    assert seen["reasoning_strength"] == "low"


def test_run_backend_for_config_traces_on_backend_error(monkeypatch):
    recs = []
    monkeypatch.setattr(cb, "_trace", lambda rec: recs.append(rec))

    def boom(prompt, model=None, timeout=None, **kwargs):
        raise RuntimeError("codex 挂了")

    monkeypatch.setattr(cb, "_run_codex", boom)
    with pytest.raises(RuntimeError):
        cb._run_backend_for_config("任意提示", _cli_codex_cfg(), tag="probe")
    assert len(recs) == 1
    assert recs[0]["error"] and "codex 挂了" in recs[0]["error"]


def test_office_inference_llm_call_is_traced(monkeypatch):
    import ming_sim.db as dbmod
    dbmod._OFFICE_TYPE_LLM_CACHE.clear()
    recs = []
    monkeypatch.setattr(cb, "_trace", lambda rec: recs.append(rec))
    monkeypatch.setattr(cb, "_run_codex", lambda prompt, model=None, timeout=None, **kwargs: ("边镇", 1))
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    got = dbmod.infer_office_type_from_office("绝无此名的杜撰怪衔甲", llm_config=_cli_codex_cfg())
    assert got == "边镇"
    assert len(recs) == 1 and "绝无此名的杜撰怪衔甲" in recs[0]["prompt"]


def test_secret_extract_traces_exactly_once(monkeypatch):
    recs = []
    monkeypatch.setattr(cb, "_trace", lambda rec: recs.append(rec))
    canned = '{"标题":"密查","内容":"查关宁军饷","承办人":"骆养性","期限月数":3,"标签":["关宁"]}'
    monkeypatch.setattr(cb, "_run_agy", lambda prompt, timeout=None: (canned, 1))
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cb._extract_secret_order("密查关宁军饷", "臣遵旨", "骆养性")
    assert len(recs) == 1, f"密令提取应恰好 1 条 trace，实 {len(recs)}"


# ── #1256 cursor / kimi / grok runners ──


def test_cli_backends_include_cursor_kimi_grok():
    assert {"cursor", "kimi", "grok"} <= set(cb._CLI_BACKENDS)
    assert cb.is_supported_cli_runner("cursor")
    assert cb.is_supported_cli_runner("kimi")
    assert cb.is_supported_cli_runner("grok")
    assert not cb.is_supported_cli_runner("opencode")  # 庭裁：走 api 通道，不入 runner 清单


def test_gate_cli_runners_single_source_excludes_agy():
    assert cb.GATE_CLI_RUNNERS == ("codex", "claude", "cursor", "kimi", "grok")
    assert "agy" not in cb.GATE_CLI_RUNNERS
    assert set(cb.GATE_CLI_RUNNERS) <= set(cb._CLI_BACKENDS)


def test_new_runners_not_parallel_safe():
    from ming_sim.models import LLMConfig
    for runner in ("cursor", "kimi", "grok"):
        cfg = LLMConfig(
            api_key="", base_url="", model="m", channel="cli", cli_runner=runner, cli_model="m",
        )
        assert cb.cli_backend_parallel_safe(cfg) is False


def test_cli_backend_from_env_accepts_new_runners(monkeypatch):
    for name in ("cursor", "kimi", "grok"):
        monkeypatch.setenv("MING_SIM_LLM_BACKEND", name)
        assert cb.cli_backend_from_env() == name
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "opencode")
    assert cb.cli_backend_from_env() is None


def test_run_cursor_flags_and_stdout(monkeypatch):
    body = "CURSOR_OK"
    captured = _capture_run(monkeypatch, _P(stdout=body, stderr="noise"))
    out, n = cb._run_cursor("PROMPT_BODY", model="auto")
    assert out == body and n == 1
    cmd = captured["cmd"]
    assert "-p" in cmd
    assert "--output-format" in cmd and cmd[cmd.index("--output-format") + 1] == "text"
    assert "--model" in cmd and cmd[cmd.index("--model") + 1] == "auto"
    assert "--trust" in cmd
    assert "PROMPT_BODY" in cmd  # positional prompt
    assert captured["kw"].get("input") in (None, "")  # not stdin


def test_run_kimi_prompt_flag_no_yolo_stdout_only(monkeypatch):
    body = "KIMI_OK"
    captured = _capture_run(monkeypatch, _P(stdout=body, stderr="kimi version 0.36.1\nTo resume..."))
    out, n = cb._run_kimi("PROMPT_BODY", model="kimi-k2")
    assert out == body and n == 1
    cmd = captured["cmd"]
    assert "-p" in cmd and cmd[cmd.index("-p") + 1] == "PROMPT_BODY"
    assert "--yolo" not in cmd and "-y" not in cmd and "--auto" not in cmd
    assert "-m" in cmd and cmd[cmd.index("-m") + 1] == "kimi-k2"
    # stderr noise must not pollute answer
    assert "resume" not in out.lower()


def test_run_grok_flags_effort_and_plain(monkeypatch):
    body = "GROK_OK"
    captured = _capture_run(monkeypatch, _P(stdout=body, stderr=""))
    out, n = cb._run_grok("PROMPT_BODY", model="grok-4.5", reasoning_strength="medium")
    assert out == body and n == 1
    cmd = captured["cmd"]
    assert "-p" in cmd and cmd[cmd.index("-p") + 1] == "PROMPT_BODY"
    assert "-m" in cmd and cmd[cmd.index("-m") + 1] == "grok-4.5"
    assert "--output-format" in cmd and cmd[cmd.index("--output-format") + 1] == "plain"
    # ticket: effort only low/med/high；medium → med
    assert "--effort" in cmd and cmd[cmd.index("--effort") + 1] == "med"


@pytest.mark.parametrize(
    "env,attr,out",
    [
        ("cursor", "_run_cursor", "CURSOR_OUT"),
        ("kimi", "_run_kimi", "KIMI_OUT"),
        ("grok", "_run_grok", "GROK_OUT"),
    ],
)
def test_run_backend_dispatch_new_runners(monkeypatch, env, attr, out):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", env)
    monkeypatch.setattr(cb, attr, lambda p, **kw: (out, 1))
    assert cb._run_backend("x") == (out, 1)


@pytest.mark.parametrize("runner", ["cursor", "kimi", "grok"])
def test_run_backend_for_config_dispatches_new_runners(monkeypatch, runner):
    from ming_sim.models import LLMConfig

    seen = {}

    def fake(prompt, model=None, timeout=None, reasoning_strength=None, **kw):
        seen["args"] = (prompt, model, timeout, reasoning_strength)
        return (f"{runner}-ok", 1)

    monkeypatch.setattr(cb, f"_run_{runner}", fake)
    cfg = LLMConfig(
        api_key="", base_url="", model="m", channel="cli",
        cli_runner=runner, cli_model="mdl-x", cli_timeout_seconds=12.0,
        reasoning_strength="low",
    )
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    text, n = cb._run_backend_for_config("P", cfg, tag="t")
    assert text == f"{runner}-ok" and n == 1
    assert seen["args"][0] == "P"
    assert seen["args"][1] == "mdl-x"
    assert seen["args"][2] == 12.0


@pytest.mark.parametrize("runner", ["cursor", "kimi", "grok"])
def test_clichat_call_cli_dispatches_new_runners(monkeypatch, runner):
    seen = {}

    def fake(prompt, model=None, timeout=None, reasoning_strength=None, **kw):
        seen["model"] = model
        seen["timeout"] = timeout
        return ("OK", 1)

    monkeypatch.setattr(cb, f"_run_{runner}", fake)
    chat = cb.CliChat(id="mdl", backend=runner, timeout=99)
    assert chat._call_cli("p") == ("OK", 1)
    assert seen["model"] == "mdl" and seen["timeout"] == 99


@pytest.mark.parametrize("runner", ["cursor", "kimi", "grok"])
def test_describe_effective_model_includes_new_runners(runner):
    from ming_sim.models import LLMConfig

    cfg = LLMConfig(
        api_key="", base_url="", model="api-fallback", channel="cli",
        cli_runner=runner, cli_model="live-model",
    )
    assert cb.describe_effective_model(cfg) == f"{runner}/live-model"


@pytest.mark.parametrize("runner", ["_run_cursor", "_run_kimi", "_run_grok"])
def test_new_runner_fail_loud_on_bad_exit(monkeypatch, runner):
    monkeypatch.setattr(
        cb.subprocess, "run",
        lambda cmd, **kw: _RcProc(stderr="auth failed", returncode=1),
    )
    with pytest.raises(RuntimeError):
        getattr(cb, runner)("p")


# ── #1256 S2 gate LLM args / config / evidence ──


def test_gate_llm_config_cli_channel():
    args = SimpleNamespace(channel="cli", runner="kimi", model="kimi-k2", api_key="", base_url="")
    cfg = cb.gate_llm_config_from_args(args)
    assert cfg.channel == "cli"
    assert cfg.cli_runner == "kimi" and cfg.cli_model == "kimi-k2"
    assert cfg.api_key == "" and cfg.base_url == ""


def test_gate_llm_config_api_from_args_not_persisted_shape(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("MING_SIM_API_BASE_URL", raising=False)
    args = SimpleNamespace(
        channel="api", runner="", model="deepseek-v4-flash",
        api_key="sk-test", base_url="https://opencode.ai/zen/v1",
    )
    cfg = cb.gate_llm_config_from_args(args)
    assert cfg.channel == "api"
    assert cfg.model == "deepseek-v4-flash"
    assert cfg.api_key == "sk-test"
    assert cfg.base_url == "https://opencode.ai/zen/v1"
    assert cfg.cli_runner == ""  # api 不写 runner


def test_gate_llm_config_api_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    args = SimpleNamespace(channel="api", runner="", model="m", api_key="", base_url="")
    cfg = cb.gate_llm_config_from_args(args)
    assert cfg.api_key == "sk-env" and cfg.base_url == "https://example.test/v1"


def test_gate_llm_config_cli_requires_runner():
    args = SimpleNamespace(channel="cli", runner="", model="m", api_key="", base_url="")
    with pytest.raises(ValueError, match="--runner"):
        cb.gate_llm_config_from_args(args)


def test_gate_llm_config_api_requires_key_and_url(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("MING_SIM_API_BASE_URL", raising=False)
    args = SimpleNamespace(channel="api", runner="", model="m", api_key="", base_url="")
    with pytest.raises(ValueError, match="api-key|API_KEY"):
        cb.gate_llm_config_from_args(args)
    args.api_key = "sk-x"
    with pytest.raises(ValueError, match="base-url|BASE_URL"):
        cb.gate_llm_config_from_args(args)


def test_gate_evidence_config_honest_cli_and_api():
    cli_args = SimpleNamespace(channel="cli", runner="cursor", model="auto")
    cli_cfg = cb.gate_llm_config_from_args(cli_args)
    cli_block = cb.gate_evidence_config(cli_args, cli_cfg)
    assert cli_block["channel"] == "cli"
    assert cli_block["runner"] == "cursor"
    assert cli_block["model"] == "auto"

    api_args = SimpleNamespace(
        channel="api", runner="codex", model="deepseek-v4-flash",
        api_key="sk", base_url="https://opencode.ai/zen/v1",
    )
    api_cfg = cb.gate_llm_config_from_args(api_args)
    api_block = cb.gate_evidence_config(api_args, api_cfg)
    assert api_block["channel"] == "api"
    assert api_block["runner"] == ""  # api 如实不挂 cli runner 名
    assert api_block["model"] == "deepseek-v4-flash"


def test_add_gate_llm_args_uses_gate_cli_runners():
    import argparse
    p = argparse.ArgumentParser()
    cb.add_gate_llm_args(p)
    # illegal runner rejected; legal accepted
    with pytest.raises(SystemExit):
        p.parse_args(["--runner", "opencode", "--model", "m"])
    ns = p.parse_args(["--runner", "grok", "--model", "grok-4.5", "--channel", "cli"])
    assert ns.runner == "grok" and ns.model == "grok-4.5"
