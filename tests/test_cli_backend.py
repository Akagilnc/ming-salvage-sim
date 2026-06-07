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
