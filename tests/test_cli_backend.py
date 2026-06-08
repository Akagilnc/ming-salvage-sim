"""CLI 后端确定性逻辑（解析/分派层，不碰 agy 生成本身）。

agy 生成内容非确定、不可断言；但其周围的解析、前缀分派、JSON 规范化全可测。
密令/补全里对 agy 的调用用 monkeypatch 喂固定输出，测纯逻辑。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from agno.models.message import Message
from pydantic import BaseModel

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
    """密令提取调用抛异常时不阻断：内容退回大臣回话，标题/承办人有合理兜底。"""
    def boom(p):
        raise RuntimeError("backend down")
    monkeypatch.setattr(cb, "_run_backend", boom)
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    acts = cb.resolve_minister_actions(
        "臣领密旨，暗查辽东军饷虚冒事。", "密令如下：查辽东军饷", default_assignee="王在晋",
    )
    so = acts["secret_order"]
    assert so is not None
    assert so["content"] == "臣领密旨，暗查辽东军饷虚冒事。"   # 退回大臣回话原文
    assert so["assignee"] == "王在晋"                          # 退回默认承办人
    assert so["deadline_months"] == 0


# ── 底层流式不实现（高层 response_stream 委托非流式）──

def test_clichat_low_level_stream_not_implemented():
    cc = cb.CliChat(id="m", backend="agy")
    with pytest.raises(NotImplementedError):
        cc.invoke_stream()
    with pytest.raises(NotImplementedError):
        cc.ainvoke_stream()


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


def test_clichat_call_cli_dispatch(monkeypatch):
    """CliChat._call_cli 按 backend 字段分派（与 _run_backend 的 env 分派独立）。"""
    monkeypatch.setattr(cb, "_run_codex", lambda p: ("CODEX", 1))
    monkeypatch.setattr(cb, "_run_claude", lambda p: ("CLAUDE", 1))
    monkeypatch.setattr(cb, "_run_agy", lambda p: ("AGY", 1))
    assert cb.CliChat(id="m", backend="codex")._call_cli("p") == ("CODEX", 1)
    assert cb.CliChat(id="m", backend="claude")._call_cli("p") == ("CLAUDE", 1)
    assert cb.CliChat(id="m", backend="agy")._call_cli("p") == ("AGY", 1)
