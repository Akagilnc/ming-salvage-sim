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
from ming_sim.cli_backend import describe_effective_model
from ming_sim.llm_config import for_role as _llm_for_role, is_minimax_base_url
from ming_sim.llm_contract import abort_llm_contract, fail_if_llm_error
from ming_sim.llm_model import create_chat_model, extract_agent_text, llm_stream_unavailable
from ming_sim.models import GameState, LLMConfig, reign_period_label
from ming_sim.token_stats import record_stream_metrics, tlog

_content: Optional[GameContent] = None
_THINKING_STREAM_CHAR_LIMIT = max(0, int(os.environ.get("MING_SIM_THINKING_STREAM_LIMIT", "600") or "0"))
_MINIMAX_SHORT_THINKING_PROMPT = (
    "【MiniMax 推演思考约束】\n"
    "若启用 thinking/reasoning，请极短思考：只列必要因果链，不复述题目、盘面、系统规则或历史常识；"
    "不要写英文分析；不要自我解释“我将如何回答”；思考控制在约 200 个中文字内。"
    "最终正文仍须完整遵守月末奏疏格式与内容要求。"
)


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
    reasoning_streamed_chars = 0
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
                if on_thinking and reasoning_streamed_chars < _THINKING_STREAM_CHAR_LIMIT:
                    remaining = _THINKING_STREAM_CHAR_LIMIT - reasoning_streamed_chars
                    chunk = merged[:remaining]
                    if chunk:
                        on_thinking(chunk)
                        reasoning_streamed_chars += len(chunk)
                    if reasoning_streamed_chars >= _THINKING_STREAM_CHAR_LIMIT:
                        on_thinking("\n〔思考已截断，继续推演中〕\n")
                reasoning_buf.clear()
                reasoning_chars_since_flush = 0
                reasoning_last_print = now
        is_terminal = (
            (hasattr(event, "is_final") and getattr(event, "is_final", False))
            or ev_type in ("RunOutput", "RunCompletedEvent")
        )
        if ev_type == "RunErrorEvent":
            raise llm_stream_unavailable(getattr(event, "content", None))
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
        if on_thinking and reasoning_streamed_chars < _THINKING_STREAM_CHAR_LIMIT:
            remaining = _THINKING_STREAM_CHAR_LIMIT - reasoning_streamed_chars
            chunk = merged[:remaining]
            if chunk:
                on_thinking(chunk)
                reasoning_streamed_chars += len(chunk)
            if reasoning_streamed_chars >= _THINKING_STREAM_CHAR_LIMIT:
                on_thinking("\n〔思考已截断，继续推演中〕\n")
    if chunk_buf:
        merged = "".join(chunk_buf).replace("\n", " ⏎ ")
        tlog(f"[{tag}] …{merged[-160:]}")

    # #671：流式拼合原文不 strip；仅用临时副本判空。
    streamed = "".join(pieces)
    if streamed.strip():
        text = streamed
        fail_if_llm_error(text, "LLM 调用")
    elif final_output is not None:
        text = extract_agent_text(final_output)
        if not text.strip():
            abort_llm_contract(tag, "流式终结事件没有正文 content", "")
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


def create_promulgation_judge_agent(llm_config: LLMConfig, agno_db: SqliteDb) -> Agent:
    """Interim promulgation judge: one isolated call for the whole reviewed batch."""
    del agno_db
    cfg = _llm_for_role(llm_config, "simulator")
    return Agent(
        name="颁布判官",
        id="promulgation-judge",
        model=create_chat_model(cfg, temperature=0.2),
        instructions=[
            "你是 interim 颁布判官，只依据输入快照判断经外廷明发的全部案卷。"
            "派系阻力只能读 leverage 与 agenda，绝不可臆测或使用 satisfaction。",
            "颁布关只属于朝堂三关（票拟、批红、封驳）和朝堂派系；部院、宗藩、"
            "勋戚、军镇、地方士绅等场外阻力只影响执行，绝不能据此打回。",
            "经票拟的合规常务默认顺颁。只有越制破格或绕程序、触犯派系人钱命门、撞上由"
            "gatekeepers 官员名单形成的把关关口三类触发才可打回。中旨本身属绕程序，"
            "须结合输入快照 promulgation_history 差分判断。任免案卷的 "
            "break_rank.is_break_rank=true 是已由档房查品级带钉死的越制破格证据，"
            "须比同盘面寻常任免从严审视，不得重新计算或忽略。皇威越高触发面"
            "越窄、越低越宽；命门级逆鳞不因皇威高而豁免。按把关人的 faction、"
            "courage、integrity 判断，不按派系首领意志判断。案卷 endorsements 是已经说出口并落库的担名事实："
            "会签/当面站台使否决方不好再拖、降低打回倾向；御笔手敕意味着驳回即抗旨，应大幅降低打回倾向。"
            "不得再按皇威判断担名者愿不愿意，也不得忽略或删除这些条目。",
            "每案 held_authorities 是在持授权适用性投影，按 privilege 计否决 "
            "modifier：尚方剑密授＝抗旨阻力降；便宜行事＝免程序阻力；"
            "专差督办＝绕常规节制。收回或投影为空后不再计。",
            "输入快照 promulgation_history 是已落库的中旨与批红强颁前科流水，按各条 marker 读入；"
            "批红强颁是朝堂阻力曾被强行压过的既成事实。有批红强颁前科时，把关人对再发中旨的"
            "封驳更易成立，须比无前科优先打回；无此前科则按常例审中旨。",
            "一次返回一个 JSON object：{\"verdicts\":[...]}，逐案恰好一项。"
            "每项含 dossier_id、decision(promulgated|rejected)。打回还须含 "
            "blocked_layer(cabinet_drafting|palace_rescript|six_offices)、reason、"
            "primary_opponents、gatekeeper_id、criteria_snapshot、affected_parties。"
            "primary_opponents 必须是非空 typed 派系数组，每项须且仅为 "
            "{kind:faction,key:<输入 factions 中的在册派系名>}；不得输出字符串清单。"
            "criteria_snapshot 必须逐字取该案 criteria_snapshot_source 的四键："
            "imperial_authority_band、appointment_tenure、authorization_ids、"
            "endorsement_entry_ids，不得缺键。affected_parties 必须是非空数组，每项须为 "
            "{kind:faction|class,key,direction:positive|negative,intensity:weak|strong}。mode=midzhi 无论顺颁打回"
            "均须给非空 affected_parties；命门类可打回并置 midzhi_unpromulgatable=true，"
            "普通中旨无前科时从严但不得机械地一概打回；有 promulgation_history 批红强颁前科时"
            "与无前科差分，优先打回。",
            "逐一独立判断各 faction/class 对这道判决的真实反应，不得把受害方机械当作"
            "默认反应方。direction 是有符号方向（可正可负），intensity 是强弱；反应为零"
            "就省略该方，不得填默认值。不要调用第二个模型，也不要用公式补算反应。",
            "顺颁不得虚构卡点。只输出 JSON，不写解释。",
        ],
        add_history_to_context=False,
        markdown=False,
    )


def create_decree_writer_agent(llm_config: LLMConfig, agno_db: SqliteDb) -> Agent:
    # 一次性 agent：add_history_to_context=False，无需持久化 → 不传 db，免得每次往
    # <db>.emperor.db 的 agno_sessions 累积 runs 撑爆存档。agno_db 仅保留以兼容调用方。
    del agno_db
    return Agent(
        name="诏书润色官",
        id="decree-writer",
        model=create_chat_model(llm_config, temperature=0.3, top_p=0.9),
        instructions=[_ctx().game_world_prompt, _ctx().decree_writer_prompt],
        add_history_to_context=False,
        markdown=False,
    )


def create_arrival_attendant_agent(llm_config: LLMConfig) -> Agent:
    """#671：抵京候见独立报到声部（王承恩 one-shot；勿复用读心 agent/夜卷）。"""
    return Agent(
        name="王承恩抵京报到",
        id="arrival-attendant",
        model=create_chat_model(llm_config, temperature=0.4),
        instructions=[
            "你是王承恩——御前老太监。用户给出本月新抵京、尚在候旨的结构化名单"
            "（年月、人名、地点、候旨状态）。你据此向皇爷低声递话。",
            "逐人通报本月抵京、候旨、尚未宣入三项事实，自由措辞。",
            "同月多人逐人点到，以递话正文作答。",
        ],
        add_history_to_context=False,
        markdown=False,
    )


def create_mindreading_agent(llm_config: LLMConfig) -> Agent:
    """Create an isolated, one-shot near-attendant reading role.

    #1474：第一版固定王承恩个性（职位制后换）；宁缺毋滥——无真增量则空返回缺席。
    """
    return Agent(
        name="御前近臣读心",
        id="mindreading",
        model=create_chat_model(llm_config, temperature=0.4),
        instructions=[
            # 个性：在场老太监对君低声递话（北极星·乾清宫一夜示范口吻）
            "你是王承恩——自信邸随驾至今的御前老太监，此刻欠身凑在御座边，"
            "只凭用户给出的定性底账、当轮完整回话和你自己的见闻，"
            "以人话向皇爷低声递出大臣未说尽的暗流、隐情、朝局提醒或人事勾连。",
            "有真增量才开口，长短随内容；所说皆从底账、回话与见闻中来。",
            "本轮回话若无暗流、隐情、朝局提醒或人事勾连可递，输出空字符串，本轮缺席。",
            # 正向例句（archive/乾清宫一夜 王承恩递话示范，原句入桩）
            "口吻与分寸如：",
            "「皇爷，这毕尚书三条都是实话。尤其那句『勿令司礼监经手』——"
            "他是当着满殿，替皇爷把那座金矿的命门点了出来，也在提醒皇爷提防那位九千岁。」",
            "「皇爷，这上策的妙处，奴婢替皇爷说透——他不要户部尚书那把椅子，"
            "只要椅子上能办的事。」",
            "「皇爷，这王尚书……不敢明驳皇爷的旨，却拿『连升三级、不合官制』三条道理在拖。」",
        ],
        add_history_to_context=False,
        markdown=False,
    )


def create_relation_judge_agent(llm_config: LLMConfig) -> Agent:
    """#634 召对关系判官（ADR 0082 召对口）：与回话并行的独立机器面短调用。

    读已完成对话记录＋账本全知机面，识别当面边事件。逐拍 prompt 是输出契约
    的唯一真源；factory 只声明职责与事实边界，避免多轮字段随两份提示漂移。"""
    return Agent(
        name="召对关系判官",
        id="relation-judge",
        model=create_chat_model(llm_config, temperature=0.2),
        instructions=[
            "你是召对关系判官。读召对至今已完成的对话记录和当前关系账，"
            "识别当面发生的大臣↔大臣边事件（当面站台作保、表态、结怨、协作等）。",
            "只记对话里真实演出的情节：不虚构、不引申、不从旧账翻旧账；"
            "语境尽量取原文片段。严格遵循本次调用给出的输出契约。",
        ],
        add_history_to_context=False,
        markdown=False,
    )


def create_highlight_judge_agent(llm_config: LLMConfig) -> Agent:
    """#544 / ADR 0045：大臣奏对高亮判官——生成完成后的独立机器面短调用。"""
    return Agent(
        name="高亮判官",
        id="highlight-judge",
        model=create_chat_model(llm_config, temperature=0.2),
        instructions=[
            "你是奏对高亮判官。读大臣已经说完的全文，挑出承重短语清单。",
            "organic markdown（如 **粗体**）只作信号，不要把标记本身当答案。",
            "只输出一个 JSON object：{\"highlights\":[\"短语\",...]}；"
            "短语尽量取原文片段；可为空数组；不要解释、不要其它键。",
        ],
        add_history_to_context=False,
        markdown=False,
    )


def create_audience_extractor_agent(llm_config: LLMConfig) -> Agent:
    """召对叙事抽取员（#501 / ADR 0035）：大臣回话演完后抽取显著故事事实落账。

    同邸报→delta 模式：LLM 只做「机器搬运工」——把已发生的回话叙事结构化，不虚构、
    不改写。开放标签（站台作保/自行退至殿侧等），涉在场变化带机器可读 presence_effect。
    不含背书绑定（#612：背书走收夜 endorsement-only 批处理）。
    """
    return Agent(
        name="召对叙事抽取员",
        id="audience_extractor",
        model=create_chat_model(llm_config, temperature=0.2),
        instructions=[
            "你从一段已经发生的君臣对话（皇帝问话 + 大臣回话 + 当前在场名单）里，抽取**显著的故事事实**，"
            "落成故事账。只搬运对话里真实演出的情节，不虚构、不引申、不复述整段原文。",
            "只输出 JSON，形如 "
            '{"facts":[{"person_names":["甲","乙"],"audibility":"殿上公开",'
            '"body":"一句话记该情节","tags":["站台"],"presence_effect":""}]}。',
            "字段规则：person_names=涉及人（可空数组）；audibility 取 "
            "「殿上公开」或「御前低语」（递话/读心/私语类御前内容标私，缺省公开）；"
            "body=一句中文情节记述；tags=开放短标签数组；presence_effect 仅当该情节"
            "改变某人在场时取 'enter'（入殿/近前）或 'exit'（自行退至殿侧/告退），否则空串。",
            "不要输出 endorsement 或任何案卷绑定字段——背书由收夜专用通道处理。",
            "没有可抽取的显著情节时输出 {\"facts\":[]}。不输出 JSON 以外任何文字。",
        ],
        add_history_to_context=False,
        markdown=False,
    )


def create_endorsement_extractor_agent(llm_config: LLMConfig) -> Agent:
    """收夜 endorsement-only 抽取员（#612 / ADR 0070）：只绑定已说出口的担名，不写故事账。"""
    return Agent(
        name="召对背书绑定员",
        id="endorsement_extractor",
        model=create_chat_model(llm_config, temperature=0.1),
        instructions=[
            "你只做一件事：把本夜对话里已经说出口的会签、当面站台、御笔手敕，"
            "绑定到输入给出的可背书案卷。只输出引用绑定，不重写、不复制故事正文。",
            "只输出 JSON，形如 "
            '{"endorsements":[{"dossier_id":1,"form":"会签","endorser_id":"毕自严",'
            '"imperial":false,"source_chat_turn_id":42}]}。',
            "字段：输入「可背书案卷」以 ref.dossier_id 标识案卷；输出必须用扁平 dossier_id"
            "（取值自对应 ref.dossier_id），不得输出 dossier_ref；"
            "form ∈ {会签,当面站台,御笔手敕}；"
            "会签/当面站台须具名 endorser_id 且 imperial=false；"
            "御笔手敕须 endorser_id 空串且 imperial=true；"
            "source_chat_turn_id 必须是输入 surviving_source_turns 中的 id。",
            "没说出口则不要编造；禁字段：不得输出 facts/body/presence_effect/"
            "audibility/tags/person_names/dossier_ref。"
            "无背书时输出 {\"endorsements\":[]}。不输出 JSON 以外任何文字。",
        ],
        add_history_to_context=False,
        markdown=False,
    )


def _is_cols_rows_table(v: object) -> bool:
    """判断某字段是否 {cols,rows} 二维表（可转 TSV）。"""
    return isinstance(v, dict) and set(v.keys()) == {"cols", "rows"}


def _table_to_tsv(name: str, table: Dict[str, object]) -> str:
    """{cols,rows} → 真 TSV 文本块（tab 分隔、换行分行）。

    放在 json.dumps 之外，避免 \\t/\\n 被 JSON 转义吃掉压缩收益（实测比 dict-of-rows -25%、
    比转义后塞进 JSON 再 -10%）。空表只吐表头行（空）。None → 空串。
    """
    cols = [str(c) for c in (table.get("cols") or [])]
    rows = table.get("rows") or []
    lines = ["\t".join(cols)]
    for r in rows:  # type: ignore[assignment]
        lines.append("\t".join("" if v is None else str(v) for v in r))
    return f"## {name}（TSV，首行列名，tab 分隔）\n" + "\n".join(lines)


def build_simulator_context(simulator_payload: Optional[Dict[str, object]]) -> str:
    """拼 simulator/extractor 共用的盘面前缀段（turn_header + 盘面 TSV 块 + 其余 JSON）。

    缓存关键：simulator 与 extractor 的 system instructions 前缀都是
    `[game_world, simulator_context, ...]`。本函数对二者吐出**字节级一致**的 simulator_context，
    simulator 先跑就把 `game_world + simulator_context` 写进 DeepSeek 前缀缓存，extractor
    再命中。turn_header 文案、取值路径(统一从 payload['turn'])、序列化参数三者两边同源。

    BUG 修复：历史上 simulator 用 state 路径+文案「邸报抬头与正文涉及年月」，extractor 用
    payload['turn']+文案「抽取涉及年月」→ 第一个字节就分叉 → extractor 整段 payload 全 miss。
    实测统一后结算 token -14.7%。

    TSV 优化：`{cols,rows}` 二维表（regions/armies/buildings/court_roster/powers_brief）转**真
    TSV 文本块**（json.dumps 之外，免转义），按「变化最小→最易变」排序——建筑/人物在前，军队/
    地区其次，诏书/记忆/issue 等高频变化字段连同非表字段走尾部 JSON。其余字段（含 factions_brief/
    classes_brief 叙述串、issues/memories 等）维持 JSON。实测表类 -25% token。
    """
    payload = simulator_payload or {}
    turn_header = ""
    # build_simulator_payload 恒带 turn；缺 label 时只走 reign_period_label()，禁西历字面抬头。
    if isinstance(payload.get("turn"), dict):
        t = payload["turn"]
        label = t.get("reign_period_label")
        if not label:
            y, p = t.get("year"), t.get("period")
            if y is not None and p is not None:
                try:
                    label = reign_period_label(int(y), int(p))
                except (TypeError, ValueError):
                    label = ""
            else:
                label = ""
        if label:
            turn_header = (
                f"【本回合年月】{label}（第 {t.get('turn')} 回合）。"
                f"涉及年月时以此为准。\n"
            )

    # 盘面表（{cols,rows}）转 TSV，按「稳→变」排序置前；缺失/非表的跳过。
    table_order = ("buildings", "court_roster", "armies", "regions")
    tsv_blocks: List[str] = []
    consumed: set[str] = set()
    for name in table_order:
        v = payload.get(name)
        if _is_cols_rows_table(v):
            tsv_blocks.append(_table_to_tsv(name, v))  # type: ignore[arg-type]
            consumed.add(name)
    # table_order 未列到、但仍是 {cols,rows} 的表也转 TSV（防新增表字段漏压缩），稳定排序。
    for name in sorted(k for k in payload if k not in consumed and _is_cols_rows_table(payload.get(k))):
        tsv_blocks.append(_table_to_tsv(name, payload[name]))  # type: ignore[arg-type]
        consumed.add(name)

    rest = {k: v for k, v in payload.items() if k not in consumed}
    parts = [turn_header + "【本回合推演输入 simulator_payload】"]
    parts.extend(tsv_blocks)
    parts.append("## 其余字段（JSON）\n" + json.dumps(rest, ensure_ascii=False, sort_keys=False))
    return "\n".join(parts)


def create_season_simulator_agent(
    llm_config: LLMConfig,
    agno_db: SqliteDb,
    state: Optional[GameState] = None,
    db: Optional[object] = None,
    simulator_payload: Optional[Dict[str, object]] = None,
) -> Agent:
    """月末推演日讲官。全量盘面走 user payload，无 tool。
    走 advanced 角色派生：若 advanced_model 已配，用更强模型；否则 fallback 主 model。
    一次性 agent：不传 db，免得 runs 累积撑爆 <db>.emperor.db。"""
    del db, state, agno_db
    cfg = _llm_for_role(llm_config, "simulator")
    tlog(f"[simulator] 使用模型 {describe_effective_model(cfg)}")
    # simulator_context 与 extractor 共用 build_simulator_context → 字节一致 → 暖好 extractor 前缀缓存。
    simulator_context = build_simulator_context(simulator_payload)
    instructions = [_ctx().game_world_prompt, simulator_context, _ctx().season_simulator_prompt]
    if is_minimax_base_url(cfg.base_url):
        instructions.insert(0, _MINIMAX_SHORT_THINKING_PROMPT)

    return Agent(
        name="月末推演日讲官",
        id="season-simulator",
        model=create_chat_model(cfg, temperature=0.9, top_p=0.95, enable_thinking=True),
        instructions=instructions,
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
    del agno_db  # 一次性 agent，不持久化，免撑爆 .emperor.db
    ctx = _ctx()
    prompt = ctx.score_extractor_module_prompts.get(module)
    if not prompt:
        raise RuntimeError(f"未知结算提取模块：{module}")
    cfg = _llm_for_role(llm_config, "extractor")
    tlog(f"[extractor/{module}] 使用模型 {describe_effective_model(cfg)}")
    # 与 simulator 共用同一函数 → simulator_context 字节级一致 → 命中 simulator 暖好的前缀缓存。
    simulator_context = build_simulator_context(simulator_payload)
    supplemental = (
        "【结算补充上下文 extractor_context】\n"
        + json.dumps(supplemental_context or {}, ensure_ascii=False, sort_keys=False)
    )
    return Agent(
        name=f"档房书办-{module}",
        id=f"score-extractor-{module}",
        model=create_chat_model(
            cfg,
            temperature=0.1,
            top_p=0.7,
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
    """非思考 + response_format=json_object 的 fallback 整理器。一次性，不持久化。"""
    del agno_db
    return Agent(
        name="JSON 修复匠",
        id="json-sanitizer",
        model=create_chat_model(
            llm_config,
            temperature=0.0,
            top_p=0.7,
            enable_thinking=False,
            force_json_output=True,
        ),
        instructions=[JSON_SANITIZER_PROMPT],
        add_history_to_context=False,
        markdown=False,
    )


def create_rescript_draft_agent(llm_config: LLMConfig, agno_db: SqliteDb) -> Agent:
    """#656 / ADR 0093 前半：急务分拣＋票拟生成官（phase2 fan-out 第 N+1 路，N=extractor 模块数）。一次性，不持久化。"""
    del agno_db
    ctx = _ctx()
    cfg = _llm_for_role(llm_config, "extractor")
    return Agent(
        name="急务票拟官",
        id="rescript-drafter",
        model=create_chat_model(
            cfg,
            temperature=0.4,
            top_p=0.9,
            enable_thinking=False,
            force_json_output=True,
        ),
        instructions=[ctx.game_world_prompt, ctx.rescript_draft_prompt],
        add_history_to_context=False,
        markdown=False,
    )


def create_chapter_memory_agent(llm_config: LLMConfig, agno_db: SqliteDb) -> Agent:
    """章节记忆：把本回合诏书+邸报+落库效果浓缩成 {body, tags} JSON（body 叙事，tags 召回标签）。
    一次性，不持久化。"""
    del agno_db
    ctx = _ctx()
    return Agent(
        name="起居注史官",
        id="chapter-memory",
        model=create_chat_model(
            llm_config,
            temperature=0.5,
            top_p=0.85,
            enable_thinking=False,
            force_json_output=True,
        ),
        instructions=[ctx.game_world_prompt, ctx.chapter_memory_prompt],
        add_history_to_context=False,
        markdown=False,
    )


def create_ending_summary_agent(llm_config: LLMConfig, agno_db: SqliteDb) -> Agent:
    """国史编纂官：读全程章节记忆 + 结局类型，生成史评式结局总结（纯文本流式）。一次性，不持久化。"""
    del agno_db
    ctx = _ctx()
    return Agent(
        name="国史编纂官",
        id="ending-summary",
        model=create_chat_model(
            llm_config,
            temperature=0.6,
            top_p=0.9,
            enable_thinking=True,
        ),
        instructions=[ctx.game_world_prompt, ctx.ending_summary_prompt],
        add_history_to_context=False,
        markdown=False,
    )


def create_faction_brew_agent(llm_config: LLMConfig, agno_db: SqliteDb) -> Agent:
    """派系态势酿制裁判（#637 S6）：派系级定性聚合摘要，输出 {stance_segment} JSON。
    一次性，不持久化；与关系酿制同一受管批次、每条工作项一个实例（批内并行各自
    独享，不共享运行态）。三不碰（ADR 0084）：不写派系真源、不动满意度/影响力、
    不建认同度。"""
    del agno_db
    ctx = _ctx()
    return Agent(
        name="派系态势酿制裁判",
        id="faction-brew",
        model=create_chat_model(
            llm_config,
            temperature=0.4,
            top_p=0.85,
            enable_thinking=False,
            force_json_output=True,
        ),
        instructions=[ctx.game_world_prompt, ctx.faction_brew_prompt],
        add_history_to_context=False,
        markdown=False,
    )


def create_relation_brew_agent(llm_config: LLMConfig, agno_db: SqliteDb) -> Agent:
    """关系酿制裁判（#636 S5）：两段式摘要增量重酿，输出 {new_foundings, recent_segment} JSON。
    一次性，不持久化；每条关系一个实例（批内并行各自独享，不共享运行态）。"""
    del agno_db
    ctx = _ctx()
    return Agent(
        name="关系酿制裁判",
        id="relation-brew",
        model=create_chat_model(
            llm_config,
            temperature=0.4,
            top_p=0.85,
            enable_thinking=False,
            force_json_output=True,
        ),
        instructions=[ctx.game_world_prompt, ctx.relation_brew_prompt],
        add_history_to_context=False,
        markdown=False,
    )
