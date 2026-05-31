"""Agno Agent 执行与工厂（非大臣类）：run_agent_*、parse_agent_json、
诏书润色/月末推演/打分提取/JSON 修复 agent。L5。

通过 bind_content() 注入 GameContent（取提示词）。
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb

from ming_sim.assets import strip_json_fence
from ming_sim.content import GameContent
from ming_sim.exceptions import LLMContractError, LLMUnavailable
from ming_sim.llm_config import for_role as _llm_for_role
from ming_sim.llm_contract import abort_llm_contract, fail_if_llm_error
from ming_sim.llm_model import create_chat_model, extract_agent_text
from ming_sim.models import GameState, LLMConfig
from ming_sim.token_stats import record_stream_metrics, tlog

_content: Optional[GameContent] = None


def bind_content(content: GameContent) -> None:
    global _content
    _content = content


def _ctx() -> GameContent:
    if _content is None:
        raise RuntimeError("agents.bind_content() 未调用：GameContent 未注入。")
    return _content


# 调试开关：MING_SIM_DUMP_LLM=1 时把每次 agno 调用真实送进 LLM 的 system/user/assistant
# 全文落盘到 scripts/runs/llm_dump_<pid>.log。从 RunOutput.messages 取（=实际 payload，非重建）。
_DUMP_LLM = os.environ.get("MING_SIM_DUMP_LLM", "").strip() in ("1", "true", "yes")
_DUMP_PATH = f"scripts/runs/llm_dump_{os.getpid()}.log"


def _dump_llm_messages(output: Any, tag: str, agent: Optional[Agent] = None) -> None:
    """把这次 run 的完整 messages（含 system prompt）追加写盘。仅 _DUMP_LLM 开时生效。

    非流式：output 即 RunOutput，带 .messages。
    流式：终结事件 RunCompletedEvent 无 .messages，改从 agent.get_last_run_output() 取。"""
    if not _DUMP_LLM:
        return
    msgs = getattr(output, "messages", None)
    if not msgs and agent is not None:
        try:
            last = agent.get_last_run_output()
            msgs = getattr(last, "messages", None)
        except Exception:  # noqa: BLE001 — dump 是调试旁路，任何异常都不该断结算
            msgs = None
    if not msgs:
        return
    lines = [f"\n{'='*80}\n[DUMP] tag={tag}  共 {len(msgs)} 条 message\n{'='*80}"]
    for i, m in enumerate(msgs):
        role = getattr(m, "role", "?")
        content = getattr(m, "content", "")
        if content is None:
            content = ""
        lines.append(f"\n----- #{i} role={role} ({len(str(content))} 字) -----\n{content}")
        # 工具调用也带上
        tcalls = getattr(m, "tool_calls", None)
        if tcalls:
            lines.append(f"\n  [tool_calls] {tcalls}")
    try:
        with open(_DUMP_PATH, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        tlog(f"[{tag}] LLM messages 已 dump → {_DUMP_PATH}")
    except OSError as e:
        tlog(f"[{tag}] dump 写盘失败：{e}")


def run_agent_text(agent: Agent, prompt: str, tag: str) -> str:
    """非流式跑 agent，返回最终完整文本。
    extractor/sanitizer 这类要严格 JSON 的场合用——避免流式 buffer 把 LLM 偶发重发段累加成畸形。"""
    tlog(f"[{tag}] 开始非流式推演（等待完整响应）")
    t0 = time.monotonic()
    output = agent.run(prompt)
    _dump_llm_messages(output, tag)
    text = extract_agent_text(output)
    tlog(f"[{tag}] 完成，{len(text)} 字，用时 {time.monotonic() - t0:.1f}s")
    return text


def run_agent_stream_text(
    agent: Agent,
    prompt: str,
    tag: str,
    on_thinking: Optional[Callable[[str], None]] = None,
    on_text: Optional[Callable[[str], None]] = None,
) -> str:
    """流式跑 agent，按事件实时打到 stdout（带毫秒时间戳），最终返回拼合后的纯文本。

    on_thinking(chunk): 每次思考片段到达时回调（可选）。
    on_text(chunk): 每次正文增量到达时回调（可选）。
    """
    tlog(f"[{tag}] 开始流式推演（首字到达前可能等几秒）")
    pieces: List[str] = []
    final_output = None
    last_print = time.monotonic()
    chunk_buf: List[str] = []
    chars_since_flush = 0
    try:
        stream = agent.run(prompt, stream=True, stream_events=True)
    except TypeError:
        tlog(f"[{tag}] 当前 agno 不支持 stream，退回普通 run")
        text = extract_agent_text(agent.run(prompt))
        if on_text:
            on_text(text)
        return text

    reasoning_buf: List[str] = []
    reasoning_chars_since_flush = 0
    reasoning_last_print = time.monotonic()
    tool_calls = 0
    for event in stream:
        ev_type = type(event).__name__
        # 工具调用事件：记日志 + 把「正在查 X」作为思考片段推给前端
        if ev_type == "ToolCallStartedEvent":
            tool = getattr(event, "tool", None)
            tname = getattr(tool, "tool_name", "?") if tool else "?"
            targs = getattr(tool, "tool_args", {}) if tool else {}
            tool_calls += 1
            tlog(f"[{tag}/工具] 调用 {tname}({targs})")
            if on_thinking:
                on_thinking(f"\n〔查阅 {tname} {targs}〕\n")
            continue
        if ev_type == "ToolCallCompletedEvent":
            tool_res = getattr(event, "tool", None)
            tres = str(getattr(tool_res, "result", "") or "")[:200] if tool_res else ""
            if tres:
                tlog(f"[{tag}/工具结果] {tres!r}")
            continue
        rdelta = getattr(event, "reasoning_content", None)
        if isinstance(rdelta, str) and rdelta:
            reasoning_buf.append(rdelta)
            reasoning_chars_since_flush += len(rdelta)
            now = time.monotonic()
            if reasoning_chars_since_flush >= 120 or (now - reasoning_last_print) >= 1.5:
                merged = "".join(reasoning_buf)
                tlog(f"[{tag}/思考] {merged.replace(chr(10), ' ⏎ ')[-200:]}")
                if on_thinking:
                    on_thinking(merged)
                reasoning_buf.clear()
                reasoning_chars_since_flush = 0
                reasoning_last_print = now
        is_terminal = (
            (hasattr(event, "is_final") and getattr(event, "is_final", False))
            or ev_type in ("RunOutput", "RunCompletedEvent")
        )
        if ev_type == "RunErrorEvent":
            raise LLMUnavailable(
                f"{tag} 流式调用失败：{getattr(event, 'content', None)}",
                code="llm_stream_error",
                provider_message=str(getattr(event, "content", None) or ""),
            )
        if is_terminal:
            final_output = event
            continue
        delta = getattr(event, "content", None)
        if isinstance(delta, str) and delta:
            pieces.append(delta)
            chunk_buf.append(delta)
            chars_since_flush += len(delta)
            if on_text:
                on_text(delta)
            now = time.monotonic()
            if chars_since_flush >= 80 or (now - last_print) >= 1.0:
                merged = "".join(chunk_buf).replace("\n", " ⏎ ")
                tlog(f"[{tag}] …{merged[-160:]}")
                chunk_buf.clear()
                chars_since_flush = 0
                last_print = now

    if reasoning_buf:
        merged = "".join(reasoning_buf)
        tlog(f"[{tag}/思考] {merged.replace(chr(10), ' ⏎ ')[-200:]}")
        if on_thinking:
            on_thinking(merged)
    if chunk_buf:
        merged = "".join(chunk_buf).replace("\n", " ⏎ ")
        tlog(f"[{tag}] …{merged[-160:]}")

    streamed = "".join(pieces).strip()
    if streamed:
        text = streamed
        fail_if_llm_error(text, "LLM 调用")
    elif final_output is not None:
        text = extract_agent_text(final_output)
    else:
        abort_llm_contract(tag, "流式无内容且无终结事件", "")
    tlog(f"[{tag}] 完成，{len(text)} 字，工具调用 {tool_calls} 次")
    # 流式 openai response 无 .usage，monkeypatch 抓不到；从终结事件 metrics 补记 token。
    _dump_llm_messages(final_output, tag, agent=agent)
    if final_output is not None:
        metrics = getattr(final_output, "metrics", None)
        model_id = getattr(getattr(agent, "model", None), "id", None) or "stream"
        record_stream_metrics(str(model_id), metrics, caller_tag=tag)
    return text


def parse_agent_json(raw: str, stage: str) -> Dict[str, Any]:
    text = strip_json_fence(raw)
    # 试 1：原文直解
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    # 试 2：截 {...} 最外层再解
    if data is None:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            abort_llm_contract(stage, "没有返回 JSON object", raw)
        snippet = text[start : end + 1]
        try:
            data = json.loads(snippet)
        except json.JSONDecodeError:
            data = None
        # 试 3：净化 control char（\r\v\f\x00-\x1f 等）后再解
        if data is None:
            cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", snippet)
            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                data = None
        # 试 4：截取首个合法平衡的 {...} 子串（防 LLM 重发拼接）
        if data is None:
            depth = 0
            in_str = False
            esc = False
            best_end = -1
            for i, ch in enumerate(snippet):
                if esc:
                    esc = False
                    continue
                if ch == "\\" and in_str:
                    esc = True
                    continue
                if ch == '"':
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        best_end = i
                        break
            if best_end > 0:
                first_block = snippet[: best_end + 1]
                first_block = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", first_block)
                try:
                    data = json.loads(first_block)
                except json.JSONDecodeError as error:
                    raise LLMContractError(
                        f"{stage} 输出不是合法 JSON：{error}\n原始输出：{raw[:800]}"
                    ) from error
            else:
                raise LLMContractError(
                    f"{stage} 输出不是合法 JSON\n原始输出：{raw[:800]}"
                )
    if not isinstance(data, dict):
        abort_llm_contract(stage, "顶层必须是 JSON object", raw)
    return data


def create_decree_writer_agent(llm_config: LLMConfig, agno_db: SqliteDb) -> Agent:
    return Agent(
        name="诏书润色官",
        id="decree-writer",
        session_id="decree-writer",
        db=agno_db,
        model=create_chat_model(llm_config, temperature=0.3, top_p=0.9, max_tokens=max(1200, llm_config.max_tokens)),
        instructions=[_ctx().game_world_prompt, _ctx().decree_writer_prompt],
        add_history_to_context=False,
        markdown=False,
    )


def build_simulator_context(simulator_payload: Optional[Dict[str, object]]) -> str:
    """拼 simulator/extractor 共用的盘面前缀段（turn_header + payload JSON）。

    缓存关键：simulator 与 extractor 的 system instructions 前缀都是
    `[game_world, simulator_context, ...]`。本函数对二者吐出**字节级一致**的 simulator_context，
    simulator 先跑就把 `game_world + simulator_context` 写进 DeepSeek 前缀缓存，extractor
    再命中。turn_header 文案、取值路径(统一从 payload['turn'])、json.dumps 参数三者两边同源。

    BUG 修复：历史上 simulator 用 state 路径+文案「邸报抬头与正文涉及年月」，extractor 用
    payload['turn']+文案「抽取涉及年月」→ 第一个字节就分叉 → extractor 整段 payload 全 miss。
    实测统一后结算 token -14.7%。
    """
    turn_header = ""
    if simulator_payload and isinstance(simulator_payload.get("turn"), dict):
        t = simulator_payload["turn"]
        turn_header = (
            f"【本回合年月】{t.get('year')} 年 {t.get('period')} 月（第 {t.get('turn')} 回合）。"
            f"涉及年月时以此为准。\n"
        )
    return (
        turn_header
        + "【本回合推演输入 simulator_payload】\n"
        + json.dumps(simulator_payload or {}, ensure_ascii=False, sort_keys=False)
    )


def create_season_simulator_agent(
    llm_config: LLMConfig,
    agno_db: SqliteDb,
    state: Optional[GameState] = None,
    db: Optional[object] = None,
    simulator_payload: Optional[Dict[str, object]] = None,
) -> Agent:
    """月末推演日讲官。全量盘面走 user payload，无 tool。
    走 advanced 角色派生：若 advanced_model 已配，用更强模型；否则 fallback 主 model。"""
    del db, state
    cfg = _llm_for_role(llm_config, "simulator")
    tlog(f"[simulator] 使用模型 {cfg.model}")
    # simulator_context 与 extractor 共用 build_simulator_context → 字节一致 → 暖好 extractor 前缀缓存。
    simulator_context = build_simulator_context(simulator_payload)

    return Agent(
        name="月末推演日讲官",
        id="season-simulator",
        session_id="season-simulator",
        db=agno_db,
        model=create_chat_model(cfg, temperature=0.9, top_p=0.95, max_tokens=cfg.max_tokens, enable_thinking=True),
        instructions=[_ctx().game_world_prompt, simulator_context, _ctx().season_simulator_prompt],
        add_history_to_context=False,
        markdown=False,
    )


def create_score_extractor_agent(llm_config: LLMConfig, agno_db: SqliteDb) -> Agent:
    """打分提取员。走 advanced 角色派生：若 advanced_model 已配，用更强模型。"""
    cfg = _llm_for_role(llm_config, "extractor")
    tlog(f"[extractor] 使用模型 {cfg.model}")
    return Agent(
        name="档房书办",
        id="score-extractor",
        session_id="score-extractor",
        db=agno_db,
        model=create_chat_model(
            cfg,
            temperature=0.1,
            top_p=0.7,
            max_tokens=cfg.max_tokens,
            enable_thinking=False,
            force_json_output=True,
        ),
        instructions=[_ctx().game_world_prompt, _ctx().score_extractor_prompt],
        add_history_to_context=False,
        markdown=False,
    )


def create_score_extractor_module_agent(
    llm_config: LLMConfig,
    agno_db: SqliteDb,
    module: str,
    simulator_payload: Optional[Dict[str, object]] = None,
    supplemental_context: Optional[Dict[str, object]] = None,
) -> Agent:
    """模块化打分提取员。module 对应 GameContent.score_extractor_module_prompts。"""
    ctx = _ctx()
    prompt = ctx.score_extractor_module_prompts.get(module)
    if not prompt:
        raise RuntimeError(f"未知结算提取模块：{module}")
    cfg = _llm_for_role(llm_config, "extractor")
    tlog(f"[extractor/{module}] 使用模型 {cfg.model}")
    # 与 simulator 共用同一函数 → simulator_context 字节级一致 → 命中 simulator 暖好的前缀缓存。
    simulator_context = build_simulator_context(simulator_payload)
    supplemental = (
        "【结算补充上下文 extractor_context】\n"
        + json.dumps(supplemental_context or {}, ensure_ascii=False, sort_keys=False)
    )
    return Agent(
        name=f"档房书办-{module}",
        id=f"score-extractor-{module}",
        session_id=f"score-extractor-{module}",
        db=agno_db,
        model=create_chat_model(
            cfg,
            temperature=0.1,
            top_p=0.7,
            max_tokens=cfg.max_tokens,
            enable_thinking=False,
            force_json_output=True,
        ),
        instructions=[ctx.game_world_prompt, simulator_context, ctx.score_extractor_shared_prompt, supplemental, prompt],
        add_history_to_context=False,
        markdown=False,
    )


JSON_SANITIZER_PROMPT = (
    "你是 JSON 修复匠。下面给你一段被污染的 JSON（可能混了思考过程、```json fence、注释、尾随逗号、"
    "重复字段、Markdown 标题等），请只输出**修复后的合法 JSON 字符串**，不要加任何解释、前后缀或 fence。\n"
    "保持原数据结构与字段不变，只做语法清理。若彻底无法识别为 JSON，请尝试抽取里面最像 JSON 的那一段。\n"
    "请按照 json 格式输出。"
)


def create_json_sanitizer_agent(llm_config: LLMConfig, agno_db: SqliteDb) -> Agent:
    """非思考 + response_format=json_object 的 fallback 整理器。"""
    return Agent(
        name="JSON 修复匠",
        id="json-sanitizer",
        session_id="json-sanitizer",
        db=agno_db,
        model=create_chat_model(
            llm_config,
            temperature=0.0,
            top_p=0.7,
            max_tokens=max(4000, llm_config.max_tokens),
            enable_thinking=False,
            force_json_output=True,
        ),
        instructions=[JSON_SANITIZER_PROMPT],
        add_history_to_context=False,
        markdown=False,
    )


def create_chapter_memory_agent(llm_config: LLMConfig, agno_db: SqliteDb) -> Agent:
    """章节记忆：把本回合诏书+邸报+落库效果浓缩成一段叙事章节（纯文本，非 JSON）。"""
    ctx = _ctx()
    return Agent(
        name="起居注史官",
        id="chapter-memory",
        session_id="chapter-memory",
        db=agno_db,
        model=create_chat_model(
            llm_config,
            temperature=0.5,
            top_p=0.85,
            max_tokens=max(1200, llm_config.max_tokens),
            enable_thinking=False,
        ),
        instructions=[ctx.game_world_prompt, ctx.chapter_memory_prompt],
        add_history_to_context=False,
        markdown=False,
    )


def create_ending_summary_agent(llm_config: LLMConfig, agno_db: SqliteDb) -> Agent:
    """国史编纂官：读全程章节记忆 + 结局类型，生成史评式结局总结（纯文本流式）。"""
    ctx = _ctx()
    return Agent(
        name="国史编纂官",
        id="ending-summary",
        session_id="ending-summary",
        db=agno_db,
        model=create_chat_model(
            llm_config,
            temperature=0.6,
            top_p=0.9,
            max_tokens=max(2400, llm_config.max_tokens),
            enable_thinking=True,
        ),
        instructions=[ctx.game_world_prompt, ctx.ending_summary_prompt],
        add_history_to_context=False,
        markdown=False,
    )
