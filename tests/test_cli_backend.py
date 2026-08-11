"""CLI 后端确定性逻辑（解析/分派层，不碰 agy 生成本身）。

agy 生成内容非确定、不可断言；但其周围的解析、前缀分派、JSON 规范化全可测。
密令/补全里对 agy 的调用用 monkeypatch 喂固定输出，测纯逻辑。
"""

from __future__ import annotations

import json
import re
import subprocess
import time
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

# runner 定位隔离 fixture（清 _BIN_CACHE + 短路登录 shell）已移到 tests/conftest.py
# 的全局 autouse `_isolate_cli_bin_resolution`，覆盖本模块 + test_llm_channel_config
# 等所有走 _resolve_cli_bin 的 runner 测试（cmr r2 codex X-R1：原只在本模块、漏了它）。


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


def test_secret_prefix_merges_emperor_intent_with_reply(monkeypatch):
    """#397：显式『密令如下：<X>』+ 大臣回话 → LLM 润成完整密令正文，
    不丢御旨（reply 可能只是领命语）、并入大臣补的承办人/要点。"""
    canned = json.dumps({
        "标题": "密查辽东军饷",
        "内容": "查辽东军饷有无侵冒，三月内回奏；着李若琏暗查。",
        "承办人": "李若琏",
        "期限月数": 3,
        "标签": ["辽饷"],
    }, ensure_ascii=False)
    captured = {}

    def fake_run(prompt):
        captured["prompt"] = prompt
        return (canned, 1)

    monkeypatch.setattr(cb, "_run_backend", fake_run)
    acts = cb.resolve_minister_actions(
        "臣领密旨，可授李若琏暗查。", "密令如下：查辽东军饷有无侵冒，三月内回奏",
        default_assignee="王在晋",
    )
    so = acts["secret_order"]
    assert so is not None
    # 抽取 prompt 同时看到皇帝显式旨意与大臣回话（#397 合并润色的入参）
    assert "查辽东军饷有无侵冒" in captured["prompt"]
    assert "臣领密旨，可授李若琏暗查" in captured["prompt"]
    assert "查辽东军饷" in so["content"]          # 御旨不丢（#397）
    assert "李若琏" in so["content"]              # 大臣补充的承办人并入
    assert so["assignee"] == "李若琏"
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
    """Prefix/extract create path must keep full 标题 after formal title-cap removal."""
    long_title = "查核辽饷转运与沿途侵蚀及军粮实数并追索责任官员"
    assert len(long_title) > 20
    canned = json.dumps({
        "标题": long_title,
        "内容": "查明事实并回奏。",
        "承办人": "毕自严",
        "期限月数": 0,
        "标签": ["辽饷"],
    }, ensure_ascii=False)
    def fake_json_extractor(prompt, llm_config=None, tag=""):
        return canned, 1

    monkeypatch.setattr(cb, "_run_json_extractor_for_config", fake_json_extractor)
    result = cb._extract_secret_order(
        "密令如下：查核辽饷转运与沿途侵蚀及军粮实数并追索责任官员\n查明事实并回奏。",
        "臣领密旨",
        "毕自严",
    )
    assert result["title"] == long_title
    assert len(result["title"]) == len(long_title)


def test_secret_exclusion_recovery_splits_each_explicit_person(monkeypatch):
    """LLM omission cannot merge two named people into one ineffective target."""
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
    """CLI recovery keeps an omitted institutional exclusion structured."""
    monkeypatch.setattr(cb, "_run_backend", lambda _prompt: ("{}", 1))

    result = cb._extract_secret_order(
        "密查此案，不得告知翰林院编修，亦不许户部尚书过问。", "臣领旨", "毕自严"
    )

    assert "翰林院编修" in result["excluded_offices"]
    assert "户部尚书" in result["excluded_offices"]


def test_secret_exclusion_recovery_covers_non_disclosure_clause(monkeypatch):
    """不同措辞也必须走与落库相同的机构排除语义。"""
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
    """PR #409 R1 Codex P2：密令按钮只补期限时，仍须从前文召对恢复任务正文。"""
    canned = json.dumps({
        "标题": "密查辽东军饷",
        "内容": "三月内回奏",
        "承办人": "",
        "期限月数": 3,
        "标签": ["辽饷"],
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_backend", lambda p: (canned, 1))
    acts = cb.resolve_minister_actions(
        "臣领旨。",
        "密令如下：三月内回奏",
        default_assignee="孙承宗",
        secret_context=(
            "皇帝：查辽东军饷有无侵冒\n"
            "大臣：可授李若琏暗查并封存兵部辽饷册"
        ),
    )
    so = acts["secret_order"]
    assert so is not None
    assert "查辽东军饷有无侵冒" in so["content"]
    assert "三月内回奏" in so["content"]
    assert "封存兵部辽饷册" in so["content"]


def test_secret_prefix_bad_llm_content_still_keeps_emperor_intent(monkeypatch):
    """#397 Step5 完整性：LLM 返回合法 JSON 但『内容』只剩大臣领命语（丢皇帝显式旨意）
    时，旧码直取该非空内容 → 御旨丢失。须兜底合并：御旨为主、并入 LLM 内容里的大臣补充，
    且结构化承办人/期限仍照常抽出。"""
    canned = json.dumps({
        "标题": "密查辽东军饷",
        "内容": "臣领密旨，可授李若琏暗查。",   # 合法但非空、丢御旨的病态内容
        "承办人": "李若琏",
        "期限月数": 3,
        "标签": ["辽饷"],
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_backend", lambda p: (canned, 1))
    acts = cb.resolve_minister_actions(
        "臣领密旨，可授李若琏暗查。", "密令如下：查辽东军饷有无侵冒，三月内回奏",
        default_assignee="王在晋",
    )
    so = acts["secret_order"]
    assert so is not None
    assert "查辽东军饷有无侵冒" in so["content"]      # 御旨不丢（即便 LLM 给了非空内容）
    assert "李若琏" in so["content"]                  # 大臣补充的承办人/要点保留
    assert so["assignee"] == "李若琏"                 # 结构化承办人仍抽出
    assert so["deadline_months"] == 3


def test_secret_prefix_partial_llm_content_still_keeps_emperor_intent(monkeypatch):
    """#397 Step5 完整性（partial-loss）：LLM『内容』合法非空、保留皇帝旨意前半段并并入大臣
    补充、却丢掉后半段显式条款（漏『三月内回奏』）时，旧 LCS≥半 守门仍判覆盖 → 御旨部分丢失。
    须按分句逐条核验：任一显式分句缺失即走兜底合并，御旨与大臣补充两全。"""
    canned = json.dumps({
        "标题": "密查辽东军饷",
        "内容": "查辽东军饷有无侵冒；着李若琏暗查。",   # 合法非空、留前半段+大臣补充，丢『三月内回奏』
        "承办人": "李若琏",
        "期限月数": 3,
        "标签": ["辽饷"],
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_backend", lambda p: (canned, 1))
    acts = cb.resolve_minister_actions(
        "臣领密旨，可授李若琏暗查。", "密令如下：查辽东军饷有无侵冒，三月内回奏",
        default_assignee="王在晋",
    )
    so = acts["secret_order"]
    assert so is not None
    assert "查辽东军饷有无侵冒" in so["content"]   # 前半段不丢
    assert "三月内回奏" in so["content"]           # 后半段显式条款也不丢（旧守门会漏判）
    assert "李若琏" in so["content"]               # 大臣补充的承办人/要点保留
    assert so["assignee"] == "李若琏"              # 结构化承办人仍抽出
    assert so["deadline_months"] == 3


def test_secret_prefix_llm_keeps_emperor_but_drops_minister_assignee(monkeypatch):
    """#397 Step6 P2：LLM 返回合法 JSON、内容完整保留御旨，但承办人留空、丢掉大臣回话里
    点名的承办人（可授李若琏暗查）→ 不得静默接受该"看起来合法"的输出。须兜底合并：
    御旨不丢、大臣补充的承办人（李若琏）也不丢、且承办人字段被找回（不退回默认召对大臣）。"""
    canned = json.dumps({
        "标题": "密查辽东军饷",
        "内容": "查辽东军饷有无侵冒，三月内回奏",   # 合法、完整保留御旨，但丢掉大臣补充
        "承办人": "",                              # 大臣回话点名的承办人没抽出
        "期限月数": 3,
        "标签": ["辽饷"],
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_backend", lambda p: (canned, 1))
    acts = cb.resolve_minister_actions(
        "臣领密旨，可授李若琏暗查。", "密令如下：查辽东军饷有无侵冒，三月内回奏",
        default_assignee="王在晋",
    )
    so = acts["secret_order"]
    assert so is not None
    assert "查辽东军饷有无侵冒" in so["content"]      # 御旨不丢
    assert "李若琏" in so["content"]                  # 大臣补充的承办人不丢（#397 Step6）
    assert so["assignee"] == "李若琏"                 # 大臣点名的承办人被找回，不退回默认
    assert so["deadline_months"] == 3


def test_secret_assignee_defaults_when_unspecified(monkeypatch):
    """LLM 未指明承办人 → 退回 default_assignee（#397 合并润色路径）。"""
    canned = json.dumps({
        "标题": "去查", "内容": "去查某事", "承办人": "", "期限月数": 0, "标签": [],
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_backend", lambda p: (canned, 1))
    acts = cb.resolve_minister_actions("臣领旨。", "密令如下：去查", default_assignee="毕自严")
    assert acts["secret_order"]["assignee"] == "毕自严"


def test_secret_prefix_llm_keeps_assignee_field_but_drops_from_content_merges(monkeypatch):
    """#397 Step6 R2（Codex P2）：LLM 返回合法 JSON、正文完整保留御旨、承办人字段正确抽出『李若琏』，
    但正文里却把大臣补充的承办人吞掉（无『李若琏』）→ 不得因承办人字段正确就静默接受。
    正文（content）是喂给承办人和结算模拟的任务概要，丢承办人=任务不明；须兜底合并，
    让正文也带上大臣补充（旧 `== _assignee_llm` 让字段正确就放行正文吞掉承办人）。"""
    canned = json.dumps({
        "标题": "密查辽东军饷",
        "内容": "查辽东军饷有无侵冒，三月内回奏",   # 合法、完整御旨，但丢大臣补充的承办人
        "承办人": "李若琏",                        # 承办人字段正确抽出
        "期限月数": 3,
        "标签": ["辽饷"],
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_backend", lambda p: (canned, 1))
    acts = cb.resolve_minister_actions(
        "臣领密旨，可授李若琏暗查。", "密令如下：查辽东军饷有无侵冒，三月内回奏",
        default_assignee="王在晋",
    )
    so = acts["secret_order"]
    assert so is not None
    assert "查辽东军饷有无侵冒" in so["content"]      # 御旨不丢
    assert "李若琏" in so["content"]                  # 正文也带上承办人（不被字段正确就吞掉）
    assert so["assignee"] == "李若琏"                 # 承办人字段仍正确
    assert so["deadline_months"] == 3


def test_secret_prefix_llm_keeps_emperor_but_drops_minister_supplements(monkeypatch):
    """#397 Step6 R3（Codex P1）：LLM 正文合法且完整保留御旨，但丢掉大臣的【非承办人】
    补充要点（如具体做法/步骤）时，不得静默接受。须兜底合并，保留大臣的实质补充。"""
    canned = json.dumps({
        "标题": "密查辽东军饷",
        "内容": "查辽东军饷有无侵冒，三月内回奏",   # 完整保留御旨，但丢大臣补充
        "承办人": "",
        "期限月数": 3,
        "标签": ["辽饷"],
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_backend", lambda p: (canned, 1))
    acts = cb.resolve_minister_actions(
        "臣领密旨，须先封存兵部辽饷册，再密访关宁诸将。",
        "密令如下：查辽东军饷有无侵冒，三月内回奏",
        default_assignee="王在晋",
    )
    so = acts["secret_order"]
    assert so is not None
    assert "查辽东军饷有无侵冒" in so["content"]      # 御旨不丢
    assert "三月内回奏" in so["content"]              # 御旨不丢
    assert "封存兵部辽饷册" in so["content"]          # 大臣补充的要点保留（R3 Codex P1）
    assert "密访关宁诸将" in so["content"]            # 大臣补充的要点保留（R3 Codex P1）


def test_extract_assignee_hint_does_not_corrupt_name_with_trailing_verb():
    """#397 Step6 R2（agy P1）：『可委/可由/请委…』后的人名不得被尾随动作字污染。
    旧贪心 {2,4} 把动作字（调/督/拟…）吞进捕获组、尾部清洗又不收这些字 → 存进
    secret_orders.minister_name 成无法解析的孤儿记录。"""
    assert cb._extract_assignee_hint("臣领密旨，可委李若琏调查此事。") == "李若琏"
    assert cb._extract_assignee_hint("可由袁崇焕督师。") == "袁崇焕"
    assert cb._extract_assignee_hint("请委周延儒拟旨。") == "周延儒"
    assert cb._extract_assignee_hint("可委李标调查此事。") == "李标"
    # 原有意图用例不回归：可授李若琏暗查
    assert cb._extract_assignee_hint("臣领密旨，可授李若琏暗查。") == "李若琏"
    # 句末/标点边界也能正确取整名
    assert cb._extract_assignee_hint("可授李若琏。") == "李若琏"


def test_extract_assignee_hint_keeps_cao_surname_characters():
    """#397 Step6 R3（Codex P2）：_ASSIGNEE_HINT_STOP_RE 不应把『曹』当机关/地名过滤掉
    真实人名（曹化淳/曹文诏）——曹是常见姓而非机关字。"""
    assert cb._extract_assignee_hint("臣领密旨，可授曹化淳暗查东厂线索。") == "曹化淳"
    assert cb._extract_assignee_hint("可委曹文诏征讨流贼。") == "曹文诏"


def test_extract_assignee_hint_greedy_strip_handles_all_verb_tails():
    """#397 Step6 R3（agy P0）：旧非贪心 {2,4}? 在动词首字不在 lookahead 时会把动作字
    吞进名字或丢掉整条线索。新实现：贪心捕获 + 尾部剥动作字，覆盖所有动词尾。"""
    assert cb._extract_assignee_hint("可委周延儒监督此事。") == "周延儒"
    assert cb._extract_assignee_hint("可由周延儒协办此事。") == "周延儒"
    assert cb._extract_assignee_hint("可委周延儒处理。") == "周延儒"
    assert cb._extract_assignee_hint("可委李若琏负责。") == "李若琏"
    assert cb._extract_assignee_hint("可委李标负责。") == "李标"


def test_extract_assignee_action_pulls_verb_after_name():
    """#397 Step6 R4（Codex P1）：_extract_assignee_action 抽出人名之后的动作/职责词。"""
    assert cb._extract_assignee_action("可委周延儒监督此事", "周延儒") == "监督"
    assert cb._extract_assignee_action("可由周延儒协办此事", "周延儒") == "协办"
    assert cb._extract_assignee_action("可委周延儒处理", "周延儒") == "处理"
    assert cb._extract_assignee_action("可委李若琏负责", "李若琏") == "负责"
    assert cb._extract_assignee_action("可授李若琏暗查", "李若琏") == "暗查"
    # 分句止于人名（无动作词）→ 空串，退化为只验人名
    assert cb._extract_assignee_action("可授李若琏", "李若琏") == ""


def test_extract_assignee_action_uses_hint_match_when_name_repeats():
    """#401 R3（Gemini high）：人名若先出现在话头/前文，动作 tail 须从 hint 命中的人名算起。"""
    clause = "李若琏：可委派李若琏暗查并封存兵部辽饷册"
    assert cb._extract_assignee_action(clause, "李若琏") == "暗查"


def test_content_reflects_supplements_rejects_name_only_when_action_dropped():
    """#397 Step6 R4（Codex P1）：assignee-hint 分句带具体动作/职责词时，只保住人名不够——
    动作词被泛化动词（如『承办』）替换即判未覆盖，走兜底合并。"""
    assert cb._content_reflects_minister_supplements("着周延儒承办", "可由周延儒协办此事。") is False
    assert cb._content_reflects_minister_supplements("着周延儒承办", "可委周延儒监督此事。") is False
    assert cb._content_reflects_minister_supplements("着周延儒承办", "可委周延儒处理。") is False
    assert cb._content_reflects_minister_supplements("着李若琏承办", "可委李若琏负责。") is False
    assert cb._content_reflects_minister_supplements("着李标承办", "可委李标负责。") is False


def test_content_reflects_supplements_uses_hint_tail_when_name_repeats():
    """#401 R3（Gemini high）：tail 不能从分句里第一次出现的人名切，否则会误判补充未覆盖。"""
    reply = "李若琏：可委派李若琏暗查并封存兵部辽饷册。"
    assert cb._content_reflects_minister_supplements(
        "着李若琏暗查封存兵部辽饷册", reply) is True


def test_content_reflects_supplements_accepts_when_name_and_action_preserved():
    """#397 Step6 R4 对照面：人名【且】动作词都在正文里 → 判覆盖（不误触合并）。"""
    assert cb._content_reflects_minister_supplements("着李若琏暗查", "可授李若琏暗查。") is True
    assert cb._content_reflects_minister_supplements("着周延儒协办此事", "可由周延儒协办此事。") is True


def test_acknowledgment_only_replies_are_not_material():
    """#401 R1（gemini medium）：纯领命/遵旨等无代词应答整句不得被判 material、不得误触兜底合并。"""
    for ack in ("领命。", "遵旨。", "谨遵。", "谢恩。", "即办。", "即行。", "即遵。", "领旨。", "遵命。"):
        assert cb._minister_material_clauses(ack) == []
        # 大臣无实质补充 → 守门判覆盖（不强制合并）
        assert cb._content_reflects_minister_supplements("着李若琏暗查", ack) is True


def test_mixed_acknowledgment_and_material_replies_ignore_ack_clauses():
    """#401 R2（Sourcery）：混合领命语 + 实质补充时，领命分句不应进入 material。"""
    for reply, content in (
        ("领命，即办。可授李若琏暗查并封存兵部辽饷册。", "着李若琏暗查并封存兵部辽饷册"),
        ("谨遵。可授李若琏暗查并封存兵部辽饷册，三月内回奏。", "着李若琏暗查并封存兵部辽饷册，三月内回奏"),
    ):
        clauses = cb._minister_material_clauses(reply)
        assert clauses
        assert all(all(ack not in c for ack in ("领命", "即办", "谨遵", "遵旨")) for c in clauses)
        assert any("可授李若琏暗查并封存兵部辽饷册" in c for c in clauses)
        assert cb._content_reflects_minister_supplements(content, reply) is True


def test_content_reflects_supplements_rejects_when_tail_material_dropped():
    """#401 R1（codex P2）：assignee 分句在人名+动作词之外仍带实质补充（『并封存兵部辽饷册』）
    时，只留人名+动作词的合法 LLM 输出不得被接受——余下 material 也须在正文里。"""
    assert cb._content_reflects_minister_supplements(
        "着李若琏暗查", "可授李若琏暗查并封存兵部辽饷册。") is False
    # 完整保留（含余下 material）→ 覆盖
    assert cb._content_reflects_minister_supplements(
        "着李若琏暗查并封存兵部辽饷册", "可授李若琏暗查并封存兵部辽饷册。") is True
    # #401 R2（Gemini）：动作词后若有空格，剥掉动作词后仍须能识别「并...」前缀。
    assert cb._content_reflects_minister_supplements(
        "着李若琏暗查封存兵部辽饷册", "可授李若琏暗查 并封存兵部辽饷册。") is True


def test_extract_assignee_hint_keeps_wei_and_si_surnames():
    """#401 R1（CodeRabbit major）：卫/司 是常见姓，单字出现不得被机关滤误拒；
    但 锦衣卫/布政司 等可识别机关词仍滤掉。"""
    assert cb._extract_assignee_hint("可授卫景瑗暗查东厂线索。") == "卫景瑗"
    assert cb._extract_assignee_hint("可委司马懿督师。") == "司马懿"
    # 机关整词仍被滤
    assert cb._extract_assignee_hint("可授锦衣卫查办。") is None
    assert cb._extract_assignee_hint("可授布政司核对。") is None


def test_extract_assignee_hint_prefers_long_compound_prefixes():
    """#401 R2（Codex P1）：可委派/可差派须先吃完整前缀，不能把「派」并进人名。"""
    assert cb._extract_assignee_hint("可委派李若琏暗查辽饷。") == "李若琏"
    assert cb._extract_assignee_hint("可差派李若琏暗查辽饷。") == "李若琏"


def test_extract_imperative_assignee_requires_command_boundary():
    """#401 R2（Codex P1）：普通词里的令/命不得被当作皇帝祈使承办人。"""
    assert cb._extract_imperative_assignee("此密令调查此事") is None
    assert cb._extract_imperative_assignee("奉密令查办辽饷") is None
    assert cb._extract_imperative_assignee("密令如下：着李若琏查办辽饷") == "李若琏"


def test_clause_split_handles_colons_and_newlines():
    """#401 R3（Sourcery）：冒号/换行也是常见结构分隔符。"""
    assert cb._minister_material_clauses("领命：可授李若琏暗查\n并封存兵部辽饷册。") == [
        "可授李若琏暗查", "并封存兵部辽饷册",
    ]


def test_secret_assignee_does_not_drift_to_unvalidated_llm_field(monkeypatch):
    """#401 R1（CodeRabbit major）：LLM 正文留李若琏、承办人字段却填王在晋时，最终承办人
    不得漂移到王在晋——字段须与正文/线索一致才采信。"""
    canned = json.dumps({
        "标题": "密查辽东军饷",
        "内容": "查辽东军饷有无侵冒，三月内回奏；着李若琏暗查。",
        "承办人": "王在晋",
        "期限月数": 3, "标签": ["辽饷"],
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_backend", lambda p: (canned, 1))
    acts = cb.resolve_minister_actions(
        "臣领密旨，可授李若琏暗查。", "密令如下：查辽东军饷有无侵冒，三月内回奏",
        default_assignee="王在晋",
    )
    so = acts["secret_order"]
    assert so is not None
    assert so["assignee"] == "李若琏"


def test_secret_assignee_prefers_hint_when_bad_llm_field_survives_merge(monkeypatch):
    """#401 R1 follow-up：若坏 LLM 正文/字段都写王在晋，但大臣线索指李若琏，兜底合并后
    content 会同时含王在晋和李若琏；此时仍应信线索李若琏，不因王在晋出现在合并正文里采信坏字段。"""
    canned = json.dumps({
        "标题": "密查辽东军饷",
        "内容": "查辽东军饷有无侵冒，三月内回奏；着王在晋暗查。",
        "承办人": "王在晋",
        "期限月数": 3, "标签": ["辽饷"],
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_backend", lambda p: (canned, 1))
    acts = cb.resolve_minister_actions(
        "臣领密旨，可授李若琏暗查。", "密令如下：查辽东军饷有无侵冒，三月内回奏",
        default_assignee="王在晋",
    )
    so = acts["secret_order"]
    assert so is not None
    assert "王在晋" in so["content"]  # merge 保留了 LLM 正文，所以单看 content 会误导
    assert "李若琏" in so["content"]
    assert so["assignee"] == "李若琏"


def test_secret_assignee_uses_emperor_imperative_hint_when_llm_blank(monkeypatch):
    """#401 R1（CodeRabbit major）：皇帝御旨以『着X』指名、LLM 承办人留空时，最终承办人
    用皇帝/正文线索，不盲目退回默认召对大臣。"""
    canned = json.dumps({
        "标题": "密查辽东军饷",
        "内容": "查辽东军饷有无侵冒，着李若琏暗查。",
        "承办人": "",
        "期限月数": 3, "标签": [],
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_backend", lambda p: (canned, 1))
    acts = cb.resolve_minister_actions(
        "臣领旨。", "密令如下：着李若琏查辽东军饷有无侵冒",
        default_assignee="王在晋",
    )
    so = acts["secret_order"]
    assert so is not None
    assert so["assignee"] == "李若琏"


def test_secret_prefix_action_word_dropped_triggers_merge(monkeypatch):
    """#397 Step6 R4 端到端：LLM 正文把大臣的『协办』换成泛化『承办』→ 守门判未覆盖 →
    兜底合并，最终正文保留大臣的实质动作词。"""
    canned = json.dumps({
        "标题": "密查辽东军饷",
        "内容": "查辽东军饷有无侵冒，着周延儒承办",   # 人名在、动作词被泛化动词替换
        "承办人": "周延儒",
        "期限月数": 3,
        "标签": ["辽饷"],
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_backend", lambda p: (canned, 1))
    acts = cb.resolve_minister_actions(
        "臣领密旨，可由周延儒协办此事。", "密令如下：查辽东军饷有无侵冒",
        default_assignee="王在晋",
    )
    so = acts["secret_order"]
    assert so is not None
    assert "查辽东军饷有无侵冒" in so["content"]   # 御旨不丢
    assert "协办" in so["content"]                 # 大臣的动作词保留（R4 Codex P1）
    assert so["assignee"] == "周延儒"


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


# ── claude 后端（claude -p 独立进程，opus/sonnet/haiku）──

def test_backend_env_claude(monkeypatch):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "claude")
    assert cb.cli_backend_from_env() == "claude"


def test_run_claude_stdout_only(monkeypatch):
    """claude -p 输出纯文本无日志壳：只取 stdout，丢 stderr。不强加思考预算。"""
    captured = {}

    class _P:
        stdout = "臣叩首。此旨当如此拟。"
        stderr = "2026-..Z INFO some log noise"
        returncode = 0

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["env"] = kw.get("env")
        return _P()

    monkeypatch.setattr(cb.subprocess, "run", fake_run)
    out, attempts = cb._run_claude("勾陈盘面")
    assert out == "臣叩首。此旨当如此拟。"      # 只 stdout，不混 stderr 日志
    assert attempts == 1
    assert "-p" in captured["cmd"] and "--model" in captured["cmd"]
    assert "--output-format" in captured["cmd"] and "text" in captured["cmd"]
    # 不替用户强设 MAX_THINKING_TOKENS：不传 env（继承父进程），由用户自行 export
    assert captured["env"] is None


def test_run_backend_dispatch_claude(monkeypatch):
    """enrich/secret 用的分派器在 backend=claude 时走 _run_claude。"""
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "claude")
    monkeypatch.setattr(cb, "_run_claude", lambda p: ("CLAUDE_OUT", 1))
    assert cb._run_backend("x") == ("CLAUDE_OUT", 1)


def test_run_backend_dispatch_default_agy(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(cb, "_run_agy", lambda p: ("AGY_OUT", 1))
    assert cb._run_backend("x") == ("AGY_OUT", 1)


def test_run_backend_dispatch_codex(monkeypatch):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    monkeypatch.setattr(cb, "_run_codex", lambda p: ("CODEX_OUT", 1))
    assert cb._run_backend("x") == ("CODEX_OUT", 1)


# ── 失败不阻断结算：enrich / secret 提取后端抛异常时退回安全默认 ──

def test_enrich_backend_error_returns_empty_effects(monkeypatch):
    def boom(p):
        raise RuntimeError("backend down")
    monkeypatch.setattr(cb, "_run_backend", boom)
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    out = cb.enrich_initiative_effects("设格致局", "")
    assert out == {"effect_on_resolve": {}, "ongoing_effects": {}, "effect_on_fail": {}}


def test_secret_extract_backend_error_falls_back(monkeypatch):
    """密令提取调用抛异常时不阻断：内容兜底合并御旨+回话（不丢皇帝显式旨意，#397），
    承办人退回默认。"""
    def boom(p):
        raise RuntimeError("backend down")
    monkeypatch.setattr(cb, "_run_backend", boom)
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    acts = cb.resolve_minister_actions(
        "臣领密旨，暗查辽东军饷虚冒事。", "密令如下：查辽东军饷", default_assignee="王在晋",
    )
    so = acts["secret_order"]
    assert so is not None
    assert "查辽东军饷" in so["content"]            # 御旨不丢（#397）
    assert "暗查辽东军饷虚冒事" in so["content"]    # 大臣回话也并入
    assert so["assignee"] == "王在晋"               # 退回默认承办人
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
    """Institutional wording must not become a nonexistent person blacklist key."""
    monkeypatch.setattr(cb, "_run_backend", lambda _p: ("{}", 1))
    result = cb._extract_secret_order("密查账目，勿使户部诸官知晓。", "臣领旨", "毕自严")
    assert result["excluded_names"] == []
    assert result["excluded_offices"] == ["户部"]


def test_secret_extract_classifies_office_title_knowledge_ban_as_office(monkeypatch):
    """具体官职同样是机构目标，不能落成无效的人名黑名单。"""
    monkeypatch.setattr(cb, "_run_backend", lambda _p: ("{}", 1))

    result = cb._extract_secret_order("密查账目，勿使户部尚书知晓。", "臣领旨", "毕自严")

    assert result["excluded_names"] == []
    assert result["excluded_offices"] == ["户部尚书"]


def test_secret_extract_classifies_grand_secretariat_title_knowledge_ban_as_office(monkeypatch):
    """内阁首辅是职名，不得作为无效人名黑名单持久化。"""
    monkeypatch.setattr(cb, "_run_backend", lambda _p: ("{}", 1))

    result = cb._extract_secret_order("密查账目，勿使内阁首辅知晓。", "臣领旨", "毕自严")

    assert result["excluded_names"] == []
    assert result["excluded_offices"] == ["内阁首辅"]


@pytest.mark.parametrize("target", ["翰林院", "翰林院编修"])
def test_secret_extract_classifies_shipped_hanlin_targets_as_offices(monkeypatch, target):
    """CLI fallback must preserve shipped office types and titles as targets."""
    monkeypatch.setattr(cb, "_run_backend", lambda _p: ("{}", 1))

    result = cb._extract_secret_order(f"密查账目，勿使{target}知晓。", "臣领旨", "毕自严")

    assert result["excluded_names"] == []
    assert result["excluded_offices"] == [target]


# ── codex 后端工程修复（实测撞出来的坑）──

def test_run_codex_flags_and_stdout(monkeypatch):
    """codex 必须 --skip-git-repo-check(非 git cwd 不秒失败) + --ephemeral(并发不撞 session)；
    干净最终输出取 stdout，不混 stderr 日志壳；未设 reasoning env 时不强加 -c。"""
    captured = {}

    class _P:
        stdout = '{"局势推进": []}'                       # 干净输出在 stdout
        stderr = "OpenAI Codex v0.125.0\n…logs…\ntokens used\n100"
        returncode = 0

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return _P()

    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    monkeypatch.setattr(cb.subprocess, "run", fake_run)
    out, n = cb._run_codex("p")
    assert out == '{"局势推进": []}'                       # 只 stdout，丢日志壳
    assert "--skip-git-repo-check" in captured["cmd"]
    assert "--ephemeral" in captured["cmd"]
    assert "-c" not in captured["cmd"]                     # 未设 reasoning 不强加默认


def test_codex_streaming_runner_degrades_to_oneshot_final(monkeypatch):
    """codex 路真实行为（#343 裁决）：codex `exec --json` 无任何 token-delta API，只在生命周期
    末的 `item.completed`/`agent_message` 一次性落地整段邸报。故 codex 流式优雅降级为「最后吐一坨」
    —— 整段 final_text 作为**单个 chunk** 一次性上抛，而非逐块增量。本测试喂 codex 真发的
    final-only 事件（绝不喂 codex 永不发的 `agent_message_delta` 假事件，那是 #244 green-but-hollow）。"""
    captured = {}

    class _Stdout:
        def __iter__(self):
            # codex 真实形态：先是 reasoning/lifecycle item（无正文），末尾 item.completed 带整段正文。
            yield json.dumps({"type": "item.started", "item": {"type": "reasoning"}}) + "\n"
            yield json.dumps(
                {"type": "item.completed", "item": {"type": "agent_message", "text": "邸报一邸报二"}}
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

    def fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        captured["cwd"] = kw.get("cwd")
        return _Proc()

    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    monkeypatch.setattr(cb.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cb, "_trace", lambda rec: None)

    chunks = []
    agent = Agent(
        name="stream-test",
        id="stream-test",
        model=cb.CliChat(id="gpt-test", backend="codex"),
        instructions=["只输出邸报。"],
        markdown=False,
    )
    text = run_agent_stream_text(agent, "请写邸报", "simulator", on_text=chunks.append)

    assert text == "邸报一邸报二"
    # 优雅降级：整段一次性吐 = 单个 chunk，绝非逐块（codex 无 delta API）。
    assert chunks == ["邸报一邸报二"]
    assert "--json" in captured["cmd"]
    assert captured["cmd"][-1] == "-"
    assert "请写邸报" in captured["input"]


def test_clichat_codex_response_stream_passes_reasoning_strength(monkeypatch):
    from agno.models.message import Message

    seen = {}

    def fake_chunks(prompt, *, model=None, timeout=None, reasoning_strength=None):
        seen["reasoning_strength"] = reasoning_strength
        yield "邸报"

    monkeypatch.setattr(cb, "_iter_codex_stream_chunks", fake_chunks)
    chat = cb.CliChat(id="gpt-test", backend="codex", reasoning_strength="low")

    chunks = list(chat.response_stream([Message(role="user", content="请写邸报")]))

    assert [chunk.content for chunk in chunks if chunk.content] == ["邸报"]
    assert seen["reasoning_strength"] == "low"


def test_api_backend_streaming_emits_real_token_deltas(monkeypatch):
    """API/hermes 路真实行为（#343 裁决）：支持 token-delta 的后端（hermes / OpenAI 兼容，
    `agents.run_agent_stream_text` 的 content-delta 循环）真增量出现——多个正文片段逐块经
    on_text 到达、并按到达顺序拼成全文。与 codex 路（一次吐）对照，证明流式与否纯看后端能力。"""

    class _Ev:
        def __init__(self, content=None, is_final=False):
            self.content = content
            self.is_final = is_final

    class _FakeStreamAgent:
        model = SimpleNamespace(id="hermes-test")

        def run(self, prompt, stream=False, stream_events=False):
            assert stream and stream_events
            yield _Ev(content="邸报")
            yield _Ev(content="增量")
            yield _Ev(content="到达")
            yield _Ev(content=None, is_final=True)

        def get_last_run_output(self):
            return None

    chunks = []
    text = run_agent_stream_text(
        _FakeStreamAgent(), "请写邸报", "simulator", on_text=chunks.append
    )

    assert text == "邸报增量到达"
    # 真增量：多个 token-delta 逐块到达（与 codex 单块一次吐相反）。
    assert chunks == ["邸报", "增量", "到达"]


def test_codex_stream_resolution_exhausts_deadline_without_spawn(monkeypatch):
    """Executable resolution is part of the streaming deadline, not pre-work outside it."""
    now = iter((10.0, 10.3))
    spawned = []

    monkeypatch.setattr(cb.time, "monotonic", lambda: next(now))
    monkeypatch.setattr(
        cb, "_resolve_cli_bin", lambda name, configured, deadline=None: "/usr/bin/codex",
    )
    monkeypatch.setattr(cb.subprocess, "Popen", lambda *a, **k: spawned.append(a))

    with pytest.raises(RuntimeError, match="超时"):
        list(cb._iter_codex_stream_chunks("请写邸报", timeout=0.2))
    assert spawned == []


def test_codex_stream_zero_timeout_does_not_spawn(monkeypatch):
    spawned = []

    monkeypatch.setattr(cb.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(
        cb, "_resolve_cli_bin", lambda name, configured, deadline=None: "/usr/bin/codex",
    )
    monkeypatch.setattr(cb.subprocess, "Popen", lambda *a, **k: spawned.append(a))

    with pytest.raises(RuntimeError, match="超时"):
        list(cb._iter_codex_stream_chunks("请写邸报", timeout=0))
    assert spawned == []


def test_codex_stream_watchdog_kills_hung_process(monkeypatch):
    """integrated cmr Gate2 codex correctness：流式读阻塞在 `for raw_line in proc.stdout`，若
    codex 卡死且不关 stdout，proc.wait(timeout) 永远到不了。看门狗须在 run_timeout 到点 kill
    进程，让阻塞读拿到 EOF 退出并抛超时（而非无限挂起）。"""
    import threading as _t

    killed = _t.Event()

    class _HangStdout:
        def __iter__(self):
            killed.wait(5.0)      # 模拟「永不关 stdout」的卡死进程，直到被 kill 才解除
            return iter(())       # kill 后 stdout 给 EOF，读循环结束

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
        list(cb._iter_codex_stream_chunks("请写邸报", timeout=0.2))
    assert killed.is_set()        # 看门狗确实 kill 了卡死进程


def test_codex_final_text_handles_item_completed_shape():
    """integrated cmr Gate2 codex correctness：codex --json 的 item.completed/item.text 形态也要
    被识别为最终正文（防御性兼容，避免真实邸报被当成空输出误判失败）；reasoning/tool item 不当正文。"""
    assert cb._codex_final_text(
        {"type": "item.completed", "item": {"type": "agent_message", "text": "邸报正文"}}
    ) == "邸报正文"
    # 非 agent_message item（reasoning/tool/plan）不被当成正文
    assert cb._codex_final_text(
        {"type": "item.completed", "item": {"type": "reasoning", "text": "推理草稿"}}
    ) == ""
    # 既有顶层 agent_message 形态仍识别（并存不回归）
    assert cb._codex_final_text({"type": "agent_message", "message": "顶层正文"}) == "顶层正文"


def test_run_codex_accepts_config_model_and_timeout(monkeypatch):
    captured = {}

    class _P:
        stdout = "臣领旨。"
        stderr = ""
        returncode = 0

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["timeout"] = kw["timeout"]
        return _P()

    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    monkeypatch.setattr(cb.subprocess, "run", fake_run)

    out, n = cb._run_codex("p", model="gpt-configured", timeout=123)

    assert out == "臣领旨。"
    assert captured["cmd"][captured["cmd"].index("--model") + 1] == "gpt-configured"
    assert 0 < captured["timeout"] <= 123


def test_run_codex_reasoning_env_optional(monkeypatch):
    """设了 MING_SIM_CODEX_REASONING 才传 -c model_reasoning_effort，否则不碰。"""
    captured = {}

    class _P:
        stdout = "x"
        stderr = ""
        returncode = 0

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return _P()

    monkeypatch.setenv("MING_SIM_CODEX_REASONING", "medium")
    monkeypatch.setattr(cb.subprocess, "run", fake_run)
    cb._run_codex("p")
    assert "-c" in captured["cmd"]
    joined = " ".join(captured["cmd"])
    assert "model_reasoning_effort" in joined and "medium" in joined


def test_run_codex_maps_reasoning_strength_to_native_effort(monkeypatch):
    captured = {}

    class _P:
        stdout = "x"
        stderr = ""
        returncode = 0

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return _P()

    monkeypatch.setenv("MING_SIM_CODEX_REASONING", "medium")
    monkeypatch.setattr(cb.subprocess, "run", fake_run)

    cb._run_codex("p", reasoning_strength="high")

    joined = " ".join(captured["cmd"])
    assert 'model_reasoning_effort="xhigh"' in joined
    assert 'model_reasoning_effort="medium"' not in joined


def test_run_codex_stdout_empty_fallback(monkeypatch):
    """stdout 空时兜底：从合并流取 'OpenAI Codex v' 之前的段。"""
    class _P:
        stdout = ""
        stderr = "臣领旨。\nOpenAI Codex v0.125.0\nlogs"
        returncode = 0

    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    monkeypatch.setattr(cb.subprocess, "run", lambda cmd, **kw: _P())
    out, n = cb._run_codex("p")
    assert out == "臣领旨。"


def test_run_claude_accepts_config_model_and_timeout(monkeypatch):
    captured = {}

    class _P:
        stdout = "臣领旨。"
        stderr = ""
        returncode = 0

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["timeout"] = kw["timeout"]
        return _P()

    monkeypatch.setattr(cb.subprocess, "run", fake_run)

    out, n = cb._run_claude("p", model="claude-configured", timeout=234)

    assert out == "臣领旨。"
    assert captured["cmd"][captured["cmd"].index("--model") + 1] == "claude-configured"
    assert 0 < captured["timeout"] <= 234


def test_run_claude_maps_reasoning_strength_to_thinking_tokens(monkeypatch):
    captured = {}

    class _P:
        stdout = "臣领旨。"
        stderr = ""
        returncode = 0

    def fake_run(cmd, **kw):
        captured["env"] = kw.get("env")
        return _P()

    monkeypatch.setenv("MAX_THINKING_TOKENS", "32000")
    monkeypatch.setattr(cb.subprocess, "run", fake_run)

    out, n = cb._run_claude("p", reasoning_strength="medium")

    assert out == "臣领旨。"
    assert captured["env"]["MAX_THINKING_TOKENS"] == "10000"


def test_run_claude_off_reasoning_uses_explicit_minimum_tokens(monkeypatch):
    captured = {}

    class _P:
        stdout = "臣领旨。"
        stderr = ""
        returncode = 0

    def fake_run(cmd, **kw):
        captured["env"] = kw.get("env")
        return _P()

    monkeypatch.setenv("MAX_THINKING_TOKENS", "32000")
    monkeypatch.setattr(cb.subprocess, "run", fake_run)

    out, n = cb._run_claude("p", reasoning_strength="off")

    assert out == "臣领旨。"
    assert captured["env"]["MAX_THINKING_TOKENS"] == "2000"


# ── _resolve_cli_bin：GUI(.app)启动 PATH 缺 ~/.local/bin 时仍定位已装的 runner ──
# Finder 双击的 .app 拿不到登录 shell 的 PATH（只继承 launchd 精简 PATH），
# 裸名 exec "codex" 会 [Errno 2] No such file or directory 即便用户已按官方装好。
# 解析到绝对路径即治本，分级兜底（登录 shell 是**最后**一级，仅前两级都 miss 才 spawn）：
#   现有 PATH → 补常见安装目录(不 spawn) → 登录 shell 真实 PATH → 退回原名(不缓存)。

def test_resolve_cli_bin_found_on_current_path(monkeypatch):
    """当前进程 PATH 就能 which 到 → 直接绝对化，不触发补目录/登录 shell。"""
    monkeypatch.setattr(cb.shutil, "which",
                        lambda name, path=None: "/usr/local/bin/codex" if path is None else None)
    monkeypatch.setattr(cb, "_login_shell_path", lambda: (_ for _ in ()).throw(AssertionError("不该触发")))
    assert cb._resolve_cli_bin("codex", "codex") == "/usr/local/bin/codex"


def test_resolve_cli_bin_found_via_extra_dirs_when_gui_path_bare(monkeypatch):
    """复现 bug：GUI 精简 PATH 下 which 失败，补常见安装目录后命中；
    且此时**不触发登录 shell**（登录 shell 是更后一级的兜底，codex X-R1）。"""
    monkeypatch.setattr(cb, "_EXTRA_BIN_DIRS", ["/fake/extra/bin"])
    monkeypatch.setattr(cb.os.path, "isdir", lambda p: True)
    home_bin = "/fake/extra/bin/codex"

    def fake_which(name, path=None):
        if path is None:
            return None                       # 当前 PATH 找不到
        assert "/fake/extra/bin" in path      # D：真断言补了常见安装目录，不只是"第二次 which"
        return home_bin

    login_calls = {"n": 0}

    def spy_login():
        login_calls["n"] += 1
        return None
    monkeypatch.setattr(cb.shutil, "which", fake_which)
    monkeypatch.setattr(cb, "_login_shell_path", spy_login)
    assert cb._resolve_cli_bin("codex", "codex") == home_bin
    assert login_calls["n"] == 0              # extra-dir 命中时登录 shell 不触发


def test_resolve_cli_bin_login_shell_path_last_resort(monkeypatch):
    """补目录仍找不到 → 问登录 shell 要真实 PATH，再 which。"""
    cb._BIN_CACHE.clear()
    found = {}

    def fake_which(name, path=None):
        if path and "/opt/odd/bin" in path:
            return "/opt/odd/bin/codex"
        return None
    monkeypatch.setattr(cb.shutil, "which", fake_which)
    monkeypatch.setattr(cb, "_login_shell_path", lambda: "/opt/odd/bin")
    assert cb._resolve_cli_bin("codex", "codex") == "/opt/odd/bin/codex"


def test_resolve_cli_bin_falls_back_to_name_when_truly_missing(monkeypatch):
    """彻底找不到 → 退回原名，让 subprocess 抛清晰 FileNotFoundError，不静默。"""
    cb._BIN_CACHE.clear()
    monkeypatch.setattr(cb.shutil, "which", lambda name, path=None: None)
    monkeypatch.setattr(cb, "_login_shell_path", lambda: None)
    assert cb._resolve_cli_bin("codex", "codex") == "codex"


def test_resolve_cli_bin_caches(monkeypatch):
    """解析结果按 runner 名缓存，进程内不重复探测。"""
    cb._BIN_CACHE.clear()
    calls = {"n": 0}

    def fake_which(name, path=None):
        calls["n"] += 1
        return "/abs/codex"
    monkeypatch.setattr(cb.shutil, "which", fake_which)
    monkeypatch.setattr(cb, "_login_shell_path", lambda: None)
    assert cb._resolve_cli_bin("codex", "codex") == "/abs/codex"
    assert cb._resolve_cli_bin("codex", "codex") == "/abs/codex"
    assert calls["n"] == 1                 # 第二次命中缓存，不再 which


# ── _login_shell_path：sentinel 包裹的 PATH 解析鲁棒（gemini G-R1）──

def test_login_shell_path_extracts_from_sentinels_despite_noise(monkeypatch):
    """rc 噪声行(含冒号+斜杠的告警)混进 stdout 时，仍只取 sentinel 内的真实 PATH，
    不被噪声行误匹配。"""
    monkeypatch.setattr(cb, "_DISCOVERED_LOGIN_PATH", None)   # 绕过 autouse 的短路

    class _P:
        stdout = ("Warning: /usr/local/bin not writable: skipping\n"
                  "<<<CMRPATH>>>/Users/x/.local/bin:/opt/homebrew/bin:/usr/bin<<<ENDPATH>>>\n")
        stderr = ""
        returncode = 0
    monkeypatch.setattr(cb, "_RAW_RUN", lambda *a, **k: _P())
    assert cb._login_shell_path() == "/Users/x/.local/bin:/opt/homebrew/bin:/usr/bin"


def test_login_shell_path_single_dir_not_dropped(monkeypatch):
    """单目录 PATH(无 os.pathsep) 也能取出——旧 heuristic 因没有分隔符会漏掉。"""
    monkeypatch.setattr(cb, "_DISCOVERED_LOGIN_PATH", None)

    class _P:
        stdout = "<<<CMRPATH>>>/usr/bin<<<ENDPATH>>>\n"
        stderr = ""
        returncode = 0
    monkeypatch.setattr(cb, "_RAW_RUN", lambda *a, **k: _P())
    assert cb._login_shell_path() == "/usr/bin"


def test_resolve_cli_bin_does_not_cache_miss(monkeypatch):
    """找不到 → 退回原名但**不缓存**；binary 后到能重新解析到真路径（Claude C-R1）。"""
    monkeypatch.setattr(cb, "_login_shell_path", lambda: None)
    monkeypatch.setattr(cb.shutil, "which", lambda name, path=None: None)
    assert cb._resolve_cli_bin("codex", "codex") == "codex"   # 退回原名
    assert "codex" not in cb._BIN_CACHE                       # miss 不进缓存
    # binary 后到：换成能 which 命中，应重解析（而非返回缓存的裸名）
    monkeypatch.setattr(cb.shutil, "which",
                        lambda name, path=None: "/Users/x/.local/bin/codex" if path is None else None)
    assert cb._resolve_cli_bin("codex", "codex") == "/Users/x/.local/bin/codex"


def test_login_shell_path_uses_printenv_not_dollar_path(monkeypatch):
    """用 printenv 取 PATH(shell 无关),不靠 \"$PATH\" 展开——fish 把 $PATH 展开成
    空格分隔会破 _dedup_path 的冒号切分（gemini r2 G-R1）。"""
    monkeypatch.setattr(cb, "_DISCOVERED_LOGIN_PATH", None)
    captured = {}

    class _P:
        stdout = "<<<CMRPATH>>>/a/bin:/b/bin<<<ENDPATH>>>"
        stderr = ""
        returncode = 0

    def fake_raw(cmd, **kw):
        captured["cmd"] = cmd
        return _P()
    monkeypatch.setattr(cb, "_RAW_RUN", fake_raw)
    assert cb._login_shell_path() == "/a/bin:/b/bin"
    joined = " ".join(captured["cmd"])
    assert "printenv PATH" in joined       # shell 无关取法
    assert '"$PATH"' not in joined          # 不靠 shell 的 $PATH 展开
    # flag 分开传,不用组合 -lic(fish 等不支持组合单字符 flag,gemini PR#115 high)
    assert "-lic" not in captured["cmd"]
    assert {"-l", "-i", "-c"} <= set(captured["cmd"])


def test_resolve_cli_bin_absolutizes_relative_result(monkeypatch):
    """which 返回相对路径(相对 MING_SIM_*_BIN 或相对 PATH 项)时，解析结果须绝对化——
    否则 _run_* 用 cwd=_AGY_CWD 跑会按沙箱目录解析、FileNotFoundError（gemini r2 G-R2）。"""
    monkeypatch.setattr(cb, "_login_shell_path", lambda: None)
    monkeypatch.setattr(cb.shutil, "which",
                        lambda name, path=None: "./bin/codex" if path is None else None)
    result = cb._resolve_cli_bin("codex", "./bin/codex")
    assert cb.os.path.isabs(result)                      # 必须绝对
    assert result == cb.os.path.abspath("./bin/codex")


def test_run_codex_execs_resolved_abspath(monkeypatch):
    """_run_codex 用解析出的绝对路径当 argv[0]（修 GUI 启动找不到 codex）。"""
    cb._BIN_CACHE.clear()
    monkeypatch.setattr(cb, "_resolve_cli_bin", lambda name, configured, deadline=None: "/Users/x/.local/bin/codex")
    captured = {}

    class _P:
        stdout = "ok"
        stderr = ""
        returncode = 0

    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    monkeypatch.setattr(cb.subprocess, "run", lambda cmd, **kw: (captured.update(cmd=cmd) or _P()))
    cb._run_codex("p")
    assert captured["cmd"][0] == "/Users/x/.local/bin/codex"


def test_run_claude_execs_resolved_abspath(monkeypatch):
    cb._BIN_CACHE.clear()
    monkeypatch.setattr(cb, "_resolve_cli_bin", lambda name, configured, deadline=None: "/opt/homebrew/bin/claude")
    captured = {}

    class _P:
        stdout = "ok"
        stderr = ""
        returncode = 0

    monkeypatch.setattr(cb.subprocess, "run", lambda cmd, **kw: (captured.update(cmd=cmd) or _P()))
    cb._run_claude("p")
    assert captured["cmd"][0] == "/opt/homebrew/bin/claude"


def test_run_agy_execs_resolved_abspath(monkeypatch):
    cb._BIN_CACHE.clear()
    monkeypatch.setattr(cb, "_resolve_cli_bin", lambda name, configured, deadline=None: "/Users/x/.local/bin/agy")
    seen = {}

    def fake_run(cmd, **kw):
        if cmd and cmd[0] == "security":
            return _Proc()                 # 暖 keychain
        seen["cmd"] = cmd
        return _Proc(stdout="臣领旨。")
    monkeypatch.setattr(cb.subprocess, "run", fake_run)
    cb._run_agy("p")
    assert seen["cmd"][0] == "/Users/x/.local/bin/agy"


@pytest.mark.parametrize("runner", ["agy", "codex", "claude"])
def test_runner_deadline_includes_slow_login_shell_resolution(monkeypatch, runner):
    """真实 adapter 的唯一 deadline 封住 cache-miss 登录 shell，且到期后不 spawn runner。"""
    cb._BIN_CACHE.clear()
    monkeypatch.setattr(cb, "_DISCOVERED_LOGIN_PATH", None)
    monkeypatch.setattr(cb.shutil, "which", lambda *args, **kwargs: None)
    runner_spawns = []

    def slow_login(cmd, **kwargs):
        time.sleep(kwargs["timeout"])
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    def no_runner(cmd, **kwargs):
        runner_spawns.append(cmd)
        raise AssertionError("deadline 到期后不得启动 runner")

    monkeypatch.setattr(cb, "_RAW_RUN", slow_login)
    monkeypatch.setattr(cb.subprocess, "run", no_runner)
    invoke = {"agy": cb._run_agy, "codex": cb._run_codex, "claude": cb._run_claude}[runner]
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="超时"):
        invoke("p", timeout=0.02)
    assert time.monotonic() - started < 0.08
    assert runner_spawns == []


# ── extract_minister_actions：LLM 判会话动作（取代关键字白名单）──

def test_extract_minister_actions_update(monkeypatch):
    import json as _j
    canned = _j.dumps({
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
    """Update extract must not silently hard-truncate 新标题 after formal title-cap removal."""
    import json as _j
    long_title = "查核辽饷转运与沿途侵蚀及军粮实数并追索责任官员"
    assert len(long_title) > 20
    canned = _j.dumps({
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
    act = cb.extract_minister_actions("辽东军情如何", "臣以为当固守", [{"id": 6, "title": "x", "content": "y"}])
    assert act["secret_action"] == "无"

def test_extract_minister_actions_cultivate(monkeypatch):
    import json as _j
    canned = _j.dumps({"密令动作": "无", "目标密令编号": 0, "调教技能": "书法精通", "调教性格": "更温婉"}, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_backend", lambda p: (canned, 1))
    act = cb.extract_minister_actions("教你书法，望你更温婉", "妾领旨", [], is_consort=True)
    assert act["cultivate_skill"] == "书法精通"
    assert act["cultivate_trait"] == "更温婉"


def test_extract_minister_actions_backend_error_safe(monkeypatch):
    """抽取调用抛异常时不阻断对话：吞掉，退回「无」动作。"""
    def boom(p):
        raise RuntimeError("backend down")
    monkeypatch.setattr(cb, "_run_backend", boom)
    act = cb.extract_minister_actions("随便", "臣以为", [{"id": 6, "title": "x", "content": "y"}])
    assert act["secret_action"] == "无"
    assert act["order_id"] == 0


def test_extract_minister_actions_nonint_ids_floor_to_zero(monkeypatch):
    """LLM 把编号/期限填成非数字 → _int 兜底成 0，不炸。"""
    canned = json.dumps(
        {"密令动作": "催办", "目标密令编号": "六号", "期限月数": "三个月"},
        ensure_ascii=False,
    )
    monkeypatch.setattr(cb, "_run_backend", lambda p: (canned, 1))
    act = cb.extract_minister_actions("催一下", "臣加紧", [{"id": 6, "title": "x", "content": "y"}])
    assert act["secret_action"] == "催办"
    assert act["order_id"] == 0
    assert act["deadline_months"] == 0


# ── _infer_tag：从 prompt 猜调用方 agent（trace 复盘用，判定顺序敏感）──

def test_infer_tag_each_branch():
    assert cb._infer_tag("你扮演被皇帝召见的大臣，回话……") == "minister"
    assert cb._infer_tag('起居注……本朝章节……"body" tags 整理') == "chapter_memory"
    assert cb._infer_tag("本月结算抽取，输出 delta……") == "extractor"
    assert cb._infer_tag("simulator_payload: 当前盘面 TSV……") == "simulator"
    assert cb._infer_tag("请拟一道诏书，颁行天下") == "decree"
    assert cb._infer_tag("只输出合法 JSON，无多余字") == "sanitizer"
    assert cb._infer_tag("今日天气如何") == "other"


def test_infer_tag_order_minister_wins_over_decree():
    """大臣回话里常含「诏书/拟」字样，minister 标识必须先判中，不能被 decree 抢。"""
    p = "你扮演被皇帝召见的大臣，臣请拟诏书一道……"
    assert cb._infer_tag(p) == "minister"


def test_infer_tag_chapter_memory_before_extractor():
    """章节记忆输入也含邸报全文，必须在 simulator/extractor 之前用起居注+章节认。"""
    p = '【起居注】崇祯二年……本卷章节……"body": "…" tags: […]'
    assert cb._infer_tag(p) == "chapter_memory"


# ── _messages_to_prompt：agno Message 列表压成单条 prompt ──

def test_messages_to_prompt_role_tags_and_order():
    msgs = [
        SimpleNamespace(role="system", content="你扮演户部尚书"),
        SimpleNamespace(role="user", content="辽饷如何筹措"),
        SimpleNamespace(role="assistant", content="臣前奏如此"),
        SimpleNamespace(role="tool", content="账本：太仓存银三万"),
    ]
    out = cb._messages_to_prompt(msgs)
    assert "【系统设定】" in out and "【皇帝/输入】" in out
    assert "【你此前的回答】" in out and "【工具结果】" in out
    # system 在最前
    assert out.index("【系统设定】") < out.index("【皇帝/输入】")
    # 执行约束尾巴恒在
    assert "【执行约束·必读】" in out


def test_messages_to_prompt_skips_empty_and_none():
    msgs = [
        SimpleNamespace(role="user", content="有效内容"),
        SimpleNamespace(role="user", content="   "),   # 纯空白跳过
        SimpleNamespace(role="assistant", content=None),  # None 跳过
    ]
    out = cb._messages_to_prompt(msgs)
    assert out.count("【皇帝/输入】") == 1     # 只剩有效那条
    assert "【你此前的回答】" not in out


def test_messages_to_prompt_unknown_role_and_nonstr_content():
    msgs = [SimpleNamespace(role="developer", content=12345)]
    out = cb._messages_to_prompt(msgs)
    assert "【developer】" in out      # 未知 role 原样包
    assert "12345" in out             # 非 str 被 str() 化


def test_messages_to_prompt_json_object_constraint():
    msgs = [SimpleNamespace(role="user", content="抽取")]
    out = cb._messages_to_prompt(msgs, response_format={"type": "json_object"})
    assert "【输出格式硬约束】" in out


def test_messages_to_prompt_basemodel_constraint():
    class _RF(BaseModel):
        x: int = 0
    out = cb._messages_to_prompt([SimpleNamespace(role="user", content="抽取")], response_format=_RF)
    assert "【输出格式硬约束】" in out


def test_messages_to_prompt_no_json_no_constraint():
    out = cb._messages_to_prompt([SimpleNamespace(role="user", content="闲聊")])
    assert "【输出格式硬约束】" not in out
    assert "【执行约束·必读】" in out   # 但执行约束仍在


# ── _strip_agent_narration：剥 agy 开头英文行动计划，保中文正文 ──

def test_strip_narration_removes_leading_english():
    text = "I will check the records.\nLet me look at the files.\n臣以为辽东当固守，徐图恢复。"
    assert cb._strip_agent_narration(text) == "臣以为辽东当固守，徐图恢复。"


def test_strip_narration_skips_blank_then_strips():
    text = "\n\nLooking at the workspace files.\n臣领旨。"
    assert cb._strip_agent_narration(text) == "臣领旨。"


def test_strip_narration_pure_chinese_unchanged():
    text = "臣以为当从长计议，先安内而后攘外。"
    assert cb._strip_agent_narration(text) == text


def test_strip_narration_all_narration_falls_back_to_original():
    """全是英文 narration（无中文正文）→ 宁可脏不要空，退回原文。"""
    text = "I will do this.\nLet me start."
    assert cb._strip_agent_narration(text) == text.strip()


# ── _loads_lenient：花括号内非法 JSON 走 except 分支 ──

def test_loads_lenient_braces_but_invalid_json():
    assert cb._loads_lenient("前缀 {坏的: json,} 后缀") is None


# ── _loads_lenient：JSONC 容错须 quote-aware，不误伤串值（#6）──

def test_loads_lenient_jsonc_trailing_comma_stripped():
    """合法 JSONC 恢复：真尾逗号 + 行注释清掉，正常解析。"""
    assert cb._loads_lenient('{"a": 1, // 注释\n"b": 2,}') == {"a": 1, "b": 2}


def test_loads_lenient_preserves_comma_brace_in_string():
    """串值含 ,} 不被尾逗号清洗误伤——只去真正的结构尾逗号（#6 病态边界）。
    旧非 quote-aware 正则把 \"x,}\" 改成 \"x}\"。"""
    assert cb._loads_lenient('{"note":"x,}", "n":1,}') == {"note": "x,}", "n": 1}


def test_loads_lenient_preserves_double_slash_in_string():
    """串值含 // 不被行注释清洗误伤（#6 病态边界）。
    旧 `(?<!:)//` 正则会把无前导冒号的串内 // 当注释剥掉。"""
    assert cb._loads_lenient('{"note":"a//b", "n":1,}') == {"note": "a//b", "n": 1}


def test_loads_lenient_preserves_url_in_string():
    """串值含 :// （URL）保留——回归旧 `(?<!:)` 行为，quote-aware 后天然成立。"""
    assert cb._loads_lenient('{"url":"http://x.com//y", "n":1,}') == {"url": "http://x.com//y", "n": 1}


def test_loads_lenient_array_trailing_comma():
    """数组尾逗号 ,] 也清掉（覆盖尾逗号判定的 ] 臂，#6 cmr R1）。"""
    assert cb._loads_lenient('{"xs":[1, 2, ],}') == {"xs": [1, 2]}


def test_loads_lenient_escaped_quote_then_slashes_in_string():
    """转义引号 \\\" 不结束字符串：其后仍在串内的 // 须保留，不被当注释剥
    （覆盖转义态机 \\\" / \\\\ 臂，#6 cmr R1）。"""
    assert cb._loads_lenient('{"a":"he said \\"hi\\" //x", "n":1,}') == {"a": 'he said "hi" //x', "n": 1}


# ── _run_agy：warm + retry×4（auth race 缓解，wiki 核心 workaround）──

class _Proc:
    def __init__(self, stdout="", stderr=""):
        self.stdout, self.stderr, self.returncode = stdout, stderr, 0


def _agy_fake(script):
    """script: agy 调用每次的结果，('ok'|'auth'|'timeout', text)；security(暖keychain) 恒成功。
    返回 (fake_run, state)，state['agy'] 计 agy 调用次数、state['warm'] 计暖次数。"""
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
    fake, state = _agy_fake([("ok", "臣领旨。辽东当固守。")])
    monkeypatch.setattr(cb.subprocess, "run", fake)
    out, attempts = cb._run_agy("勾陈盘面")
    assert out == "臣领旨。辽东当固守。"
    assert attempts == 1
    assert state["warm"] >= 1          # 调用前暖过 keychain


def test_run_agy_auth_race_then_success(monkeypatch):
    fake, state = _agy_fake([
        ("auth", "Authentication required"),
        ("auth", "authentication timed out"),
        ("ok", "臣以为可行。"),
    ])
    monkeypatch.setattr(cb.subprocess, "run", fake)
    out, attempts = cb._run_agy("p")
    assert out == "臣以为可行。"
    assert attempts == 3               # 前两次 auth race 重试，第三次成
    assert state["warm"] == 3          # 每 attempt 都先暖


def test_run_agy_all_timeout_raises(monkeypatch):
    fake, _ = _agy_fake([("timeout", "")])
    monkeypatch.setattr(cb.subprocess, "run", fake)
    with pytest.raises(RuntimeError, match="warm\\+retry"):
        cb._run_agy("p")


def test_run_agy_retries_share_one_deadline_including_keychain(monkeypatch):
    clock = {"now": 10.0}
    budgets = []

    def monotonic():
        return clock["now"]

    def fake_run(cmd, **kw):
        budgets.append((cmd[0], kw["timeout"]))
        clock["now"] += 0.4
        if cmd[0] == "security":
            return _Proc()
        return _Proc(stdout="Authentication required")

    monkeypatch.setattr(cb.time, "monotonic", monotonic)
    monkeypatch.setattr(cb.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="整体期限"):
        cb._run_agy("p", timeout=1.0)

    assert budgets[0][0] == "security"
    assert budgets[1][0].endswith("agy")
    assert budgets[2][0] == "security"
    assert budgets[0][1] == pytest.approx(1.0)
    assert budgets[1][1] == pytest.approx(0.6)
    assert budgets[2][1] == pytest.approx(0.2)


def test_run_agy_zero_deadline_starts_no_warmup_or_attempt(monkeypatch):
    monkeypatch.setattr(cb.subprocess, "run", lambda *a, **kw: pytest.fail("must not spawn"))
    with pytest.raises(RuntimeError, match="整体期限"):
        cb._run_agy("p", timeout=0)


def test_run_agy_all_auth_fail_raises(monkeypatch):
    fake, state = _agy_fake([("auth", "Authentication required")])
    monkeypatch.setattr(cb.subprocess, "run", fake)
    with pytest.raises(RuntimeError):
        cb._run_agy("p")
    assert state["agy"] == 4           # 初试 1 + retry 3


# ── _run_codex / _run_claude：超时 → RuntimeError ──

def test_run_codex_timeout_raises(monkeypatch):
    def boom(cmd, **kw):
        raise cb.subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    monkeypatch.setattr(cb.subprocess, "run", boom)
    with pytest.raises(RuntimeError, match="超时"):
        cb._run_codex("p")


def test_run_claude_timeout_raises(monkeypatch):
    def boom(cmd, **kw):
        raise cb.subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    monkeypatch.setattr(cb.subprocess, "run", boom)
    with pytest.raises(RuntimeError, match="超时"):
        cb._run_claude("p")


# ── CLI runner 非零退出 / 空输出 → raise（不静默当空回复/角色文本落库，CMR F2）──

class _RcProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def test_run_codex_nonzero_exit_raises(monkeypatch):
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    monkeypatch.setattr(cb.subprocess, "run",
                        lambda cmd, **kw: _RcProc(stderr="error: auth failed", returncode=1))
    with pytest.raises(RuntimeError):
        cb._run_codex("p")


def test_run_codex_empty_output_raises(monkeypatch):
    """退出码 0 但 stdout/stderr 全空 → 也当失败抛，不返回空字符串。"""
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    monkeypatch.setattr(cb.subprocess, "run", lambda cmd, **kw: _RcProc(returncode=0))
    with pytest.raises(RuntimeError):
        cb._run_codex("p")


def test_run_claude_nonzero_exit_raises(monkeypatch):
    monkeypatch.setattr(cb.subprocess, "run",
                        lambda cmd, **kw: _RcProc(stderr="auth required", returncode=1))
    with pytest.raises(RuntimeError):
        cb._run_claude("p")


def test_run_agy_nonzero_exit_retries_then_raises(monkeypatch):
    """agy 非零退出当失败 attempt，warm+retry×4 仍非零 → raise。"""
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


# ── CliChat.invoke：建 prompt → 调 CLI → 剥 narration → 包 completion → agno 解析 ──

def test_clichat_invoke_strips_narration_before_parse(monkeypatch):
    cc = cb.CliChat(id="cli-test", backend="agy")
    monkeypatch.setattr(cc, "_call_cli", lambda p: ("I will check the files.\n臣以为辽东当固守。", 1))
    monkeypatch.setattr(cb, "_trace", lambda rec: None)   # 不写盘
    captured = {}
    real_fake = cb._fake_completion

    def spy(text, model_id):
        captured["text"] = text
        return real_fake(text, model_id)

    monkeypatch.setattr(cb, "_fake_completion", spy)
    msgs = [SimpleNamespace(role="system", content="你扮演大臣"),
            SimpleNamespace(role="user", content="勾陈盘面")]
    cc.invoke(msgs, Message(role="assistant"))
    # 进 _fake_completion 的文本已剥掉英文 narration，只剩中文正文
    assert captured["text"] == "臣以为辽东当固守。"


def test_clichat_invoke_error_traced_and_reraised(monkeypatch):
    cc = cb.CliChat(id="cli-test", backend="agy")

    def boom(p):
        raise RuntimeError("cli down")

    monkeypatch.setattr(cc, "_call_cli", boom)
    traced = {}
    monkeypatch.setattr(cb, "_trace", lambda rec: traced.update(rec))
    with pytest.raises(RuntimeError, match="cli down"):
        cc.invoke([SimpleNamespace(role="user", content="x")], Message(role="assistant"))
    assert traced.get("error") == "cli down"    # finally 段仍记了 error trace


# ── F6 trace backend 实值 / F8 JSONC 容错 / F10 action enum 归一 ──

def test_loads_lenient_strips_jsonc_comments_and_trailing_comma():
    """模型照模板回带 // 注释 + 尾逗号时仍能解析（CMR F8）。"""
    raw = '{\n  "密令动作": "更新", // 皇帝改了内容\n  "目标密令编号": 6,\n}'
    assert cb._loads_lenient(raw) == {"密令动作": "更新", "目标密令编号": 6}


def test_loads_lenient_keeps_url_double_slash():
    """字符串内 :// 不被当注释剥掉。"""
    assert cb._loads_lenient('{"u": "http://x.cn/a"}') == {"u": "http://x.cn/a"}


def test_loads_lenient_valid_json_with_comma_brace_in_value_not_mangled():
    """合法 JSON 串值里含 `,}` 不被尾逗号清洗误伤(先严格解析,失败才清洗)。"""
    assert cb._loads_lenient('{"a": "末尾是逗号和括号,}"}') == {"a": "末尾是逗号和括号,}"}


def test_extract_minister_actions_unknown_action_floored(monkeypatch):
    """LLM 返回枚举外的动作 → 归一为「无」（CMR F10）。"""
    canned = json.dumps({"密令动作": "乱填的动作", "目标密令编号": 6}, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_backend", lambda p: (canned, 1))
    act = cb.extract_minister_actions("x", "y", [{"id": 6, "title": "t", "content": "c"}])
    assert act["secret_action"] == "无"


def test_enrich_nondict_subfields_guarded(monkeypatch):
    """enrich 子段被 LLM 给成非 dict(字符串/数组)时 isinstance 守门归 {}，不抛 ValueError（codexB）。"""
    monkeypatch.setattr(cb, "_run_backend",
                        lambda p: ('{"effect_on_resolve": "坏数据", "ongoing_effects": ["x"], "effect_on_fail": 3}', 1))
    monkeypatch.setattr(cb, "_trace", lambda r: None)
    out = cb.enrich_initiative_effects("设局", "")
    assert out == {"effect_on_resolve": {}, "ongoing_effects": {}, "effect_on_fail": {}}


def test_enrich_trace_records_actual_backend(monkeypatch):
    """trace 的 backend 字段记实际后端，不硬编码 agy（CMR F6）。"""
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    monkeypatch.setattr(cb, "_run_backend", lambda p: ('{"effect_on_resolve":{}}', 1))
    rec = {}
    monkeypatch.setattr(cb, "_trace", lambda r: rec.update(r))
    cb.enrich_initiative_effects("设局", "")
    assert rec.get("backend") == "codex"


def test_clichat_call_cli_dispatch(monkeypatch):
    """CliChat._call_cli 按 backend 字段分派（与 _run_backend 的 env 分派独立）。"""
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
    """直接构造 CliChat(backend=bogus) 时 _call_cli 兜底响亮抛错（defense-in-depth：
    create_chat_model 已在构造前用 is_supported_cli_runner 拦截，但直接构造路径仍可达）。"""
    import pytest
    with pytest.raises(RuntimeError):
        cb.CliChat(id="m", backend="bogus")._call_cli("p")


# ── trace 咽喉：每个经 _run_backend_for_config 的 CLI 调用都必须写日志 ──
# （观测盲区根因：trace 原靠各调用方自觉手写，office_infer/verify/三个 extract 都漏过，
#  导致「cli_trace 空 = 零 LLM」假象、开局慢 5 分钟无人察觉。下沉到咽喉，谁调都记。）

def test_run_backend_for_config_traces_every_call(monkeypatch):
    """咽喉 trace：任何经 _run_backend_for_config 的调用都写且仅写一条 trace，
    携带传入的 tag、prompt、真实 backend/attempts，error 为 None。"""
    recs = []
    monkeypatch.setattr(cb, "_trace", lambda rec: recs.append(rec))
    monkeypatch.setattr(cb, "_run_codex", lambda prompt, model=None, timeout=None, **kwargs: ("外臣", 1))
    out, attempts = cb._run_backend_for_config("判官名：后金汗", _cli_codex_cfg(), tag="office_infer")
    assert out == "外臣" and attempts == 1
    assert len(recs) == 1, f"咽喉应写且仅写 1 条 trace，实 {len(recs)}"
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
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
        reasoning_strength="low",
    )

    cb._run_backend_for_config("判官名：后金汗", cfg, tag="office_infer")

    assert seen["reasoning_strength"] == "low"


def test_run_backend_for_config_traces_on_backend_error(monkeypatch):
    """后端抛错也要留痕：trace 记下 error，再把异常抛给调用方。"""
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
    """端到端：动态生造官名走 LLM 兜底时（use_llm 默认 True），该调用必须留痕——
    这正是当初被漏记、把人误导成『零 LLM』的那条路。"""
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
    """防双写守门：trace 搬到咽喉后，密令提取仍恰好一条（不双写、不漏写）。"""
    recs = []
    monkeypatch.setattr(cb, "_trace", lambda rec: recs.append(rec))
    canned = '{"标题":"密查","内容":"查关宁军饷","承办人":"骆养性","期限月数":3,"标签":["关宁"]}'
    monkeypatch.setattr(cb, "_run_agy", lambda prompt, timeout=None: (canned, 1))
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cb._extract_secret_order("密查关宁军饷", "臣遵旨", "骆养性")
    assert len(recs) == 1, f"密令提取应恰好 1 条 trace，实 {len(recs)}"
