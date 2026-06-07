"""本地 CLI LLM 后端：把 agy / codex 当 LLM，脱离 api key。

探针目标：把游戏 LLM 后端从「api key 调远端」换成「本地自治 CLI agent」。
做法 = 继承 agno 的 OpenAIChat，只覆盖最底层 invoke：
不发 HTTP，改 subprocess 调 agy，把文本输出包成假 ChatCompletion，
交回 agno 原生 _parse_provider_response 解析。agno 全套（解析/流式回退/
消息格式）原样复用，零 function-calling（工具不传，大臣退化成纯文本进谏）。

启用：环境变量 MING_SIM_LLM_BACKEND=agy（或 codex）。
机器依赖：本机已装并登录 agy（~/.local/bin/agy）/ codex。不兼容别的机器——
这是探针的预期，不是缺陷。

调用约定来自 wiki/concepts/codex-bot-conventions.md + cross-model-review.md：
- agy：先暖 keychain（auth 是 race），warm + retry（初试 1 + 最多 3），--sandbox。
- codex：`codex exec -` 必须 stdin pipe，绝不 positional；始终 2>&1。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Type, Union

from agno.models.message import Message
from agno.models.openai import OpenAIChat
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from pydantic import BaseModel

# agy 是自治编程 agent：给它仓库目录当 workspace，它会跑去翻源码/DB 研究问题，
# 行动计划（英文）泄进角色对话 + 元游戏泄漏。给它一个空目录当 cwd，无可探。
_AGY_CWD = os.path.join(tempfile.gettempdir(), "ming_agy_sandbox")
os.makedirs(_AGY_CWD, exist_ok=True)

# agy 单次调用上限（秒）。extractor payload 大 + 自治 agent 启动慢，给足。
_AGY_TIMEOUT = int(os.environ.get("MING_SIM_AGY_TIMEOUT", "300"))
_AGY_BIN = os.environ.get("MING_SIM_AGY_BIN", "agy")
_CODEX_BIN = os.environ.get("MING_SIM_CODEX_BIN", "codex")
_CODEX_MODEL = os.environ.get("MING_SIM_CODEX_MODEL", "gpt-5.5")

_VERBOSE = os.environ.get("MING_SIM_LLM_DEBUG", "") not in ("", "0", "false")

# 结构化 trace：默认开，每次调用追加一行 JSONL，玩完整局可复盘。
# 关：MING_SIM_TRACE=0。路径可改：MING_SIM_TRACE_PATH=...
_TRACE_DISABLED = os.environ.get("MING_SIM_TRACE", "1").strip() in ("0", "false", "no")
_TRACE_PATH = os.environ.get(
    "MING_SIM_TRACE_PATH", f"scripts/runs/cli_trace_{os.getpid()}.jsonl"
)
_TRACE_FIELD_CAP = int(os.environ.get("MING_SIM_TRACE_CAP", "40000"))  # 单字段字符上限
_seq = 0
_trace_announced = False


def _log(msg: str) -> None:
    if _VERBOSE:
        print(f"[cli_backend] {msg}", flush=True)


def _infer_tag(prompt: str) -> str:
    """从 prompt（含 system 段）猜是哪个 agent 在调用，方便复盘。

    判定顺序要紧：simulator/extractor/chapter_memory 的输入都含上月邸报全文，
    （含『月末奏章』等词），故必须用各自唯一标识、且把易被邸报词污染的项前置。
    """
    p = prompt
    if "扮演被皇帝召见" in p or "大臣扮演" in p:
        return "minister"
    # 章节记忆输入也含邸报全文，必须在 simulator 之前、用 起居注+章节+body/tags 认。
    if "起居注" in p and "章节" in p and ('"body"' in p or "tags" in p):
        return "chapter_memory"
    if "module_allowed_fields" in p or "score_extractor" in p or "本月结算抽取" in p:
        return "extractor"
    if "simulator_payload" in p:  # 仅真 simulator 的 user payload 才有
        return "simulator"
    if "诏书" in p and "拟" in p:
        return "decree"
    if "只输出合法 JSON" in p or "整理" in p:
        return "sanitizer"
    return "other"


def _trace(record: Dict[str, Any]) -> None:
    if _TRACE_DISABLED:
        return
    global _trace_announced
    try:
        os.makedirs(os.path.dirname(_TRACE_PATH) or ".", exist_ok=True)
        # 大字段截断，防失控；保留首尾各一半。
        cap = _TRACE_FIELD_CAP
        for k in ("prompt", "response"):
            v = record.get(k)
            if isinstance(v, str) and len(v) > cap:
                record[k] = v[: cap // 2] + f"\n...[截断 {len(v) - cap} 字]...\n" + v[-cap // 2:]
        with open(_TRACE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        if not _trace_announced:
            _trace_announced = True
            print(f"[cli_backend] LLM trace → {_TRACE_PATH}", flush=True)
    except Exception as exc:  # trace 永不应中断游戏
        _log(f"trace 写盘失败：{exc}")


def _warm_keychain() -> None:
    """暖 macOS keychain 路径，缓解 agy headless auth 的 1s race（见 wiki）。"""
    try:
        subprocess.run(
            ["security", "find-generic-password", "-s", "Antigravity Safe Storage"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
        )
    except Exception:
        pass


def _run_agy(prompt: str) -> Tuple[str, int]:
    """调 agy -p --sandbox，warm + retry。返回 (纯文本, 实际尝试次数)。"""
    last = ""
    for attempt in range(1, 5):  # 初试 1 + 最多 retry 3 = 4
        _warm_keychain()
        try:
            proc = subprocess.run(
                [_AGY_BIN, "-p", "--sandbox"],
                input=prompt, capture_output=True, text=True, timeout=_AGY_TIMEOUT,
                cwd=_AGY_CWD,
            )
        except subprocess.TimeoutExpired:
            last = "agy timeout"
            _log(f"attempt {attempt}: timeout")
            continue
        out = (proc.stdout or "") + (proc.stderr or "")
        out = out.strip()
        if "Authentication required" in out or "authentication timed out" in out:
            last = out
            _log(f"attempt {attempt}: auth race，重试")
            continue
        _log(f"attempt {attempt}: ok（{len(out)} chars）")
        return out, attempt
    raise RuntimeError(f"agy 调用失败（warm+retry×4 仍不成）：{last[:200]}")


def _run_codex(prompt: str) -> Tuple[str, int]:
    """调 codex exec -（stdin pipe，绝不 positional）。返回 (文本, 尝试次数=1)。"""
    try:
        proc = subprocess.run(
            [_CODEX_BIN, "exec", "--model", _CODEX_MODEL, "-"],
            input=prompt, capture_output=True, text=True, timeout=_AGY_TIMEOUT,
            cwd=_AGY_CWD,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("codex 调用超时") from exc
    return ((proc.stdout or "") + (proc.stderr or "")).strip(), 1


def _messages_to_prompt(
    messages: List[Message],
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
) -> str:
    """把 agno Message 列表压成单条 prompt。system 在前，对话在后。"""
    parts: List[str] = []
    for m in messages:
        role = getattr(m, "role", "user")
        content = getattr(m, "content", "")
        if content is None:
            continue
        if not isinstance(content, str):
            content = str(content)
        if not content.strip():
            continue
        tag = {"system": "【系统设定】", "user": "【皇帝/输入】", "assistant": "【你此前的回答】",
               "tool": "【工具结果】"}.get(role, f"【{role}】")
        parts.append(f"{tag}\n{content}")
    prompt = "\n\n".join(parts)
    # agy 不支持 response_format；JSON 类 agent 在 prompt 末尾强约束。
    wants_json = False
    if isinstance(response_format, dict) and response_format.get("type") == "json_object":
        wants_json = True
    elif isinstance(response_format, type) and issubclass(response_format, BaseModel):
        wants_json = True
    if wants_json:
        prompt += (
            "\n\n【输出格式硬约束】只输出一个合法 JSON 对象，不要任何前后说明、"
            "不要 markdown 代码围栏、不要注释。第一个字符必须是 {，最后一个字符必须是 }。"
        )
    prompt += (
        "\n\n【执行约束·必读】你**没有**任何文件、目录、数据库、代码、工具或命令可用，也不要去找。"
        "不要描述你打算做什么（如『I will list…』『让我查一下…』）、不要提及 workspace/文件/目录/data/源码/state query 之类。"
        "直接以你所扮演的角色身份，用**中文**给出最终回答；禁止英文，禁止任何旁白或思考过程。"
    )
    return prompt


# agy 自治 agent 偶发把英文行动计划吐进开头，cwd 隔离是治本，这里再剥一层兜底。
_NARRATION_HEAD = re.compile(
    r"^\s*(I will\b|I'll\b|Let me\b|First,|First I|I need to\b|I'm going to\b|I am going to\b|"
    r"Looking at\b|Let's\b|I should\b|To answer\b|Based on the (workspace|directory|files)\b).*$",
    re.IGNORECASE,
)


def _strip_agent_narration(text: str) -> str:
    """剥掉开头若干行英文行动计划 narration，保留真正的角色回答（中文）。"""
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if not ln:
            i += 1
            continue
        # 命中英文行动计划行就跳过；遇到第一行非 narration（通常是中文正文）即停。
        if _NARRATION_HEAD.match(ln):
            i += 1
            continue
        break
    cleaned = "\n".join(lines[i:]).strip()
    return cleaned or text.strip()  # 全被剥光则退回原文，宁可脏不要空


# ── 拟旨 / 下密令入档（CLI 后端）────────────────────────────────────────
# 原版（api key）靠 agno 工具 propose_directive/secret_order，模型 function-call 触发。
# agy 不做 function-calling，唯一缺口在此。解法很简单：
#   玩家用「拟旨/下密令」按钮 = 消息带「拟旨如下：/密令如下：」前缀 = 已表态要下旨，
#   那这一句大臣回话原文就是这道旨/密令，整段入档即可。不用解析圣旨边界。
#   多轮聊出多道 → 颁诏时玩家去重。大臣本就把相关衙门/人等写进回话（原 prompt 行为）。
_DRAFT_PREFIXES = ("拟旨如下：", "拟旨如下:", "拟旨：", "拟旨:")
_SECRET_PREFIXES = ("密令如下：", "密令如下:", "密令：", "密令:")


def _matched_prefix(message: str, prefixes) -> Optional[str]:
    """消息命中某前缀则返回前缀后的正文（玩家那句意图），否则 None。"""
    pm = (message or "").strip()
    for pre in prefixes:
        if pm.startswith(pre):
            return pm[len(pre):].strip()
    return None


def _loads_lenient(raw: str) -> Optional[dict]:
    """容错解析 JSON：剥代码围栏、截首 { 到末 }。失败返回 None。"""
    t = (raw or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    i, j = t.find("{"), t.rfind("}")
    if i == -1 or j == -1 or j <= i:
        return None
    try:
        obj = json.loads(t[i:j + 1])
        return obj if isinstance(obj, dict) else None
    except (ValueError, TypeError):
        return None


def enrich_initiative_effects(title: str, stage: str = "") -> Dict[str, Any]:
    """国策(initiative)立项后 agy 一贯不填效果字段（实测 0/4）。这里聚焦补全：
    按国策标题/现状生成 解决效果(完成回报)/持续效果(月度成本)/失败效果。
    纯数值设计任务（不扮演），与月末 extractor 同款可靠。返回英文 key 的三个 dict。"""
    prompt = (
        "你是历史模拟游戏(明末崇祯)的数值结算设计器，不扮演、不写圣旨。"
        "给下面这条「国策」设计它**办成时**的实质后果，按国策性质选对的产出类型，"
        "只输出一个 JSON（英文结构 key），不要代码围栏、不要别的字：\n"
        "{\n"
        '  "effect_on_resolve": {\n'
        '    "metrics": {"民心": int, "皇威": int, "国库": int},   // 抽象国势回报，按需，可省\n'
        '    "buildings": [{"action":"create","region_id":"省拼音码","name":"","category":"财政/军事/民生/科技/交通/内廷","output_metric":"国库/内库/民心/皇威/","output_amount":int}],\n'
        '    "new_armies": [{"id":"英文小写id","name":"军名","owner_power":"ming","manpower":兵额(整数,如18000),"maintenance_per_turn":月饷万两(整数),"commander":"主将姓名或空","station":"驻地","troop_type":"步/骑/水/车营"}],\n'
        '    "army_delta": {"既有军id":{"manpower":增兵整数,"reason":""}},\n'
        '    "character_status_changes": [{"name":"必须是确切人名","status":"dead/exiled/imprisoned/dismissed/retired","reason":""}]\n'
        "  },\n"
        '  "ongoing_effects": {"economy": [{"account":"国库/内库","delta":负数月度开销,"category":"","reason":""}]},\n'
        '  "effect_on_fail": {"metrics": {"民心": 负int}}\n'
        "}\n"
        "【按国策性质选类型，不要全用 metrics 凑数】：\n"
        "- 营建/办厂/设局/筑堡/设仓/建坞/立学 → buildings.create（科技/军事厂局让推演认军备能力，别只给民心）\n"
        "- 练兵/募营/建新军 → new_armies（给合理兵额/月饷/主将/驻地）\n"
        "- 给既有军扩编/补员 → army_delta\n"
        "- 暗杀/处决/罢黜/流放/下狱某个**确切人物**(含敌酋如皇太极) → character_status_changes(name 必须确切、status 取白名单)\n"
        "- 整顿提威/安民/财政新政 → metrics / economy\n"
        "规则：① 数值朴素(个位到一二十/兵额按史实体量)；② 只有确需周期烧钱的实体才给 ongoing_effects.economy(负)，否则 {}；"
        "③ 不相关的类型留空，别硬塞；④ region_id 拼音码：京师=beizhili 陕西=shaanxi 辽东=liaodong 山东=shandong "
        "河南=henan 南直隶=nanzhili 浙江=zhejiang 福建=fujian 广东=guangdong 湖广=huguang 四川=sichuan 山西=shanxi 江西=jiangxi 云南=yunnan，不确定 beizhili。\n\n"
        "【国策】" + (title or "") + "\n【现状】" + (stage or "（无）") + "\n"
    )
    raw = ""
    try:
        raw, _ = _run_codex(prompt) if cli_backend_from_env() == "codex" else _run_agy(prompt)
    except Exception as exc:  # 补全失败不阻断结算
        _log(f"国策效果补全失败：{exc}")
    _trace({
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "seq": -1, "tag": "issue_enrich", "backend": "agy", "model_id": "enrich",
        "dur_s": 0, "attempts": 1, "wants_json": True,
        "prompt_chars": len(prompt), "resp_chars": len(raw),
        "error": None, "prompt": prompt, "response": raw,
    })
    obj = _loads_lenient(raw) or {}
    try:
        from ming_sim.simulation import _canonical_item_fields
        norm = _canonical_item_fields(obj) if obj else {}
    except Exception:
        norm = obj
    resolve = dict(norm.get("effect_on_resolve") or {})
    # 建筑 create 缺 region_id 兜底，免得静默落不了地
    for b in (resolve.get("buildings") or []):
        if isinstance(b, dict) and str(b.get("action") or "").lower() == "create" and not b.get("region_id"):
            b["region_id"] = "beizhili"
    return {
        "effect_on_resolve": resolve,
        "ongoing_effects": dict(norm.get("ongoing_effects") or {}),
        "effect_on_fail": dict(norm.get("effect_on_fail") or {}),
    }


def _extract_secret_order(player_command: str, minister_reply: str, default_assignee: str) -> Dict[str, Any]:
    """聚焦提取：把密令交代+大臣回话抽成结构化字段。纯抽取任务（不扮演），
    与月末 extractor 同款可靠。失败则退回合理默认。"""
    prompt = (
        "你是一个严谨的信息抽取器，不是大臣，不要扮演、不要写圣旨。\n"
        "下面是皇帝下达的一道密令交代，以及承命大臣的回话。请抽出这道密令的结构化字段，"
        "只输出一个 JSON 对象，不要 markdown 代码围栏、不要 JSON 以外任何字：\n"
        "{\n"
        "  \"标题\": \"≤14字的密令简称，概括任务，如 密查关宁军饷、暗结蒙古诸部\",\n"
        "  \"内容\": \"密令完整任务详情：目标、保密要求、做法\",\n"
        "  \"承办人\": \"实际承办此密令的人名；皇帝或大臣指明谁就填谁，没指明就填 "
        + (default_assignee or "") + "\",\n"
        "  \"期限月数\": 整数，皇帝限了期就填月数（如『三月内结案』填3），没限填0,\n"
        "  \"标签\": [\"相关人名/地区/事项关键词\"]\n"
        "}\n\n"
        "【皇帝密令】" + (player_command or "（无）") + "\n"
        "【大臣回话】" + (minister_reply or "（无）") + "\n"
    )
    raw = ""
    try:
        raw, _attempts = _run_agy(prompt) if cli_backend_from_env() != "codex" else _run_codex(prompt)
    except Exception as exc:  # 提取失败不阻断：退回默认
        _log(f"密令提取失败：{exc}")
    _trace({
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "seq": -1, "tag": "secret_extract", "backend": "agy", "model_id": "extract",
        "dur_s": 0, "attempts": 1, "wants_json": True,
        "prompt_chars": len(prompt), "resp_chars": len(raw),
        "error": None, "prompt": prompt, "response": raw,
    })
    obj = _loads_lenient(raw) or {}
    content = str(obj.get("内容") or "").strip() or (minister_reply or "").strip() or player_command
    title = str(obj.get("标题") or "").strip()[:20] or (player_command or content)[:14]
    assignee = str(obj.get("承办人") or "").strip() or default_assignee
    try:
        deadline = max(0, min(int(obj.get("期限月数") or 0), 36))
    except (TypeError, ValueError):
        deadline = 0
    tags = obj.get("标签")
    tags = [str(t).strip() for t in tags if str(t).strip()] if isinstance(tags, list) else []
    return {"title": title, "content": content, "assignee": assignee,
            "deadline_months": deadline, "tags": tags}


def resolve_minister_actions(
    minister_reply: str, player_message: str = "", default_assignee: str = "",
) -> Dict[str, Any]:
    """玩家上一句带拟旨/密令前缀时入档。
    - 拟旨：大臣回话原文即圣旨草稿（单一文本字段，够用）。
    - 密令：多一次聚焦提取，抽出 标题/内容/承办人/期限/标签（恢复原版 function-call 那几个字段）。
    返回 {decree_text, secret_order}。"""
    out: Dict[str, Any] = {"decree_text": None, "secret_order": None}
    reply = (minister_reply or "").strip()

    draft_intent = _matched_prefix(player_message, _DRAFT_PREFIXES)
    if draft_intent is not None:
        out["decree_text"] = reply or draft_intent or None

    secret_intent = _matched_prefix(player_message, _SECRET_PREFIXES)
    if secret_intent is not None and (reply or secret_intent):
        out["secret_order"] = _extract_secret_order(secret_intent, reply, default_assignee)

    return out


def _fake_completion(text: str, model_id: str) -> ChatCompletion:
    """把纯文本包成 OpenAI ChatCompletion 交给 agno 解析。"""
    msg = ChatCompletionMessage(role="assistant", content=text)
    choice = Choice(index=0, message=msg, finish_reason="stop")
    return ChatCompletion(
        id="cli-backend", choices=[choice], created=0,
        model=model_id, object="chat.completion",
    )


@dataclass
class CliChat(OpenAIChat):
    """agy / codex 当后端。只覆盖 invoke/ainvoke，复用 agno 其余全部逻辑。"""

    backend: str = "agy"

    def _call_cli(self, prompt: str) -> Tuple[str, int]:
        if self.backend == "codex":
            return _run_codex(prompt)
        return _run_agy(prompt)

    def invoke(  # type: ignore[override]
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Any = None,
        compress_tool_results: bool = False,
    ):
        global _seq
        assistant_message.metrics.start_timer()
        # 拟旨/密令不走 agno function-calling（agy 不支持）。大臣照常自然回话；
        # 玩家用拟旨/密令按钮（消息带前缀）时，handler 用 resolve_minister_actions
        # 把这句回话原文整段入档。invoke 只负责出文本。
        prompt = _messages_to_prompt(messages, response_format)
        _seq += 1
        seq = _seq
        tag = _infer_tag(prompt)
        t0 = time.monotonic()
        error = None
        text = ""
        attempts = 0
        try:
            text, attempts = self._call_cli(prompt)
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            dt = round(time.monotonic() - t0, 1)
            assistant_message.metrics.stop_timer()
            _trace({
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "seq": seq, "tag": tag, "backend": self.backend, "model_id": self.id,
                "dur_s": dt, "attempts": attempts, "wants_json": bool(response_format),
                "prompt_chars": len(prompt), "resp_chars": len(text),
                "error": error, "prompt": prompt, "response": text,
            })
            _log(f"#{seq} {tag} {dt}s attempts={attempts} resp={len(text)}c"
                 + (f" ERROR={error}" if error else ""))

        text = _strip_agent_narration(text)
        provider_response = _fake_completion(text, self.id)
        return self._parse_provider_response(provider_response, response_format=response_format)

    async def ainvoke(  # type: ignore[override]
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Any = None,
        compress_tool_results: bool = False,
    ):
        # 探针单线程串行，直接复用同步实现。
        return self.invoke(
            messages, assistant_message, response_format=response_format,
            tools=tools, tool_choice=tool_choice, run_response=run_response,
            compress_tool_results=compress_tool_results,
        )

    def invoke_stream(self, *args, **kwargs):  # type: ignore[override]
        # 底层流式不实现；高层 response_stream 已改为委托非流式 response()。
        raise NotImplementedError("CliChat 不支持底层流式")

    def ainvoke_stream(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError("CliChat 不支持底层流式")

    def response_stream(  # type: ignore[override]
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Any]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        tool_call_limit: Optional[int] = None,
        stream_model_response: bool = True,
        run_response: Any = None,
        send_media_to_model: bool = True,
        compression_manager: Any = None,
    ):
        # agy 一次性出全文，无真增量。把非流式结果当单个 chunk 吐出去，
        # 上游 run_agent_stream_text 的事件循环按一个 RunContent 处理即可。
        yield self.response(
            messages, response_format=response_format, tools=None,
            run_response=run_response,
        )

    async def aresponse_stream(  # type: ignore[override]
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Any]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        tool_call_limit: Optional[int] = None,
        stream_model_response: bool = True,
        run_response: Any = None,
        send_media_to_model: bool = True,
        compression_manager: Any = None,
    ):
        yield self.response(
            messages, response_format=response_format, tools=None,
            run_response=run_response,
        )


def cli_backend_from_env() -> Optional[str]:
    """读 MING_SIM_LLM_BACKEND，返回 'agy'/'codex' 或 None（走原 api 路径）。"""
    val = (os.environ.get("MING_SIM_LLM_BACKEND") or "").strip().lower()
    return val if val in ("agy", "codex") else None
