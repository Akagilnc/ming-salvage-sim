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
from concurrent.futures import ThreadPoolExecutor
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Type, Union

from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.models.response import ModelResponse
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion_message_function_tool_call import (
    ChatCompletionMessageFunctionToolCall,
    Function as ToolFunction,
)
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_chunk import (
    ChoiceDeltaToolCall,
    ChoiceDeltaToolCallFunction,
)
from pydantic import BaseModel

# CLI runner 默认模型单一真源在 models（L0 叶子），此处 re-export 保留
# `from ming_sim.cli_backend import CODEX_DEFAULT_MODEL` 既有路径（#60）。
from ming_sim.models import CODEX_DEFAULT_MODEL, CLAUDE_DEFAULT_MODEL, LLMConfig
from ming_sim.constants import DOSSIER_LINK_TYPES
from ming_sim.decree_vocabulary import DIRECTIVE_ACTION_TYPES
from ming_sim.participant_roster import (
    BARE_INSTITUTION_PARTICIPANT_NAMES as _BARE_INSTITUTION_PARTICIPANT_NAMES,
    INSTITUTION_PARTICIPANT_TOKENS as _ASSIGNEE_HINT_INSTITUTION_TOKENS,
    NON_PERSON_PARTICIPANT_NAMES as _NON_PERSON_PARTICIPANT_NAMES,
    is_non_person_participant_name as _is_non_person_participant_name,
)

# #529 owns interim-office capture/materialization.  Keep the #471 dossier
# vocabulary compatible, but do not let manual/draft extraction create it yet.
DRAFT_ACTION_TYPES = DIRECTIVE_ACTION_TYPES - {"acting_appointment"}

# agy 是自治编程 agent：给它仓库目录当 workspace，它会跑去翻源码/DB 研究问题，
# 行动计划（英文）泄进角色对话 + 元游戏泄漏。给它一个空目录当 cwd，无可探。
_AGY_CWD = os.path.join(tempfile.gettempdir(), "ming_agy_sandbox")
os.makedirs(_AGY_CWD, exist_ok=True)

# agy 单次调用上限（秒）。extractor payload 大 + 自治 agent 启动慢，给足。
_AGY_TIMEOUT = int(os.environ.get("MING_SIM_AGY_TIMEOUT", "300"))
_AGY_BIN = os.environ.get("MING_SIM_AGY_BIN", "agy")
# CODEX_DEFAULT_MODEL / CLAUDE_DEFAULT_MODEL 现 import 自 models（见上，#60）。
_CODEX_BIN = os.environ.get("MING_SIM_CODEX_BIN", "codex")
_CODEX_MODEL = os.environ.get("MING_SIM_CODEX_MODEL", CODEX_DEFAULT_MODEL)
# claude -p 独立进程后端：opus/sonnet/haiku。纯文本输出无日志壳。
# 未配置 reasoning_strength 时继承用户环境；配置后显式设置 Claude thinking 预算。
_CLAUDE_BIN = os.environ.get("MING_SIM_CLAUDE_BIN", "claude")
_CLAUDE_MODEL = os.environ.get("MING_SIM_CLAUDE_MODEL", CLAUDE_DEFAULT_MODEL)
# 纯角色扮演/抽取任务不需要工具；禁掉防 claude 绕去调工具兜圈子。
_CLAUDE_DISALLOWED = ["Bash", "Read", "Edit", "Write", "Glob", "Grep",
                      "WebFetch", "WebSearch", "Task", "NotebookEdit"]
# #1256：cursor / kimi / grok 本机 CLI runner；opencode 庭裁走 api 通道，不入此名单。
_CURSOR_BIN = os.environ.get("MING_SIM_CURSOR_BIN", "cursor-agent")
_KIMI_BIN = os.environ.get("MING_SIM_KIMI_BIN", "kimi")
_GROK_BIN = os.environ.get("MING_SIM_GROK_BIN", "grok")
# 受支持 CLI runner 单一真源（membership + 文案 + env 回落共用）。
_CLI_BACKENDS = frozenset({"agy", "codex", "claude", "cursor", "kimi", "grok"})
# 闸脚本 --runner choices 单一真源（不含 agy：闸形制未用）。脚本 import 此元组，禁各自复制。
GATE_CLI_RUNNERS = ("codex", "claude", "cursor", "kimi", "grok")
# 实际消费 --model / cli_model 的 runner（describe_effective_model 用）；agy 走自身 ladder。
_CLI_MODEL_RUNNERS = frozenset({"codex", "claude", "cursor", "kimi", "grok"})
_CODEX_REASONING_BY_STRENGTH = {
    "off": "low",
    "low": "low",
    "medium": "medium",
    "high": "xhigh",
}
_CLAUDE_THINKING_TOKENS_BY_STRENGTH = {
    "off": "2000",
    "low": "2000",
    "medium": "10000",
    "high": "32000",
}
# grok Build CLI --effort 仅 low/med/high（#1256 票面）；抽象 medium → med。
_GROK_EFFORT_BY_STRENGTH = {
    "off": "low",
    "low": "low",
    "medium": "med",
    "high": "high",
}
# 支持 reasoning_strength 传输的 CLI runner 单源（#1271）：与上方三张 *_BY_STRENGTH
# 表同缝。有传输表 = 支持；kimi/cursor 无独立档位旗，不入此集（另票/庭裁）。
# 导出 frozenset——llm_config 谓词与 web payload 均消费此名，禁第二处手写名单。
CLI_REASONING_STRENGTH_RUNNERS = frozenset({"codex", "claude", "grok"})


def cli_model_choices() -> Dict[str, List[Dict[str, str]]]:
    """每个 CLI runner 的策展模型档——前端「CLI Model」下拉的单一真源。

    每档 {value, label}：value="" = runner 默认档（提交空串走后端默认）；首档恒为默认档。
    默认档 label 用 cli_model_from_env(runner, "") 算「真实 resolved 默认」——它先认
    MING_SIM_{CODEX,CLAUDE}_MODEL env 覆盖、再回落 *_DEFAULT_MODEL 常量，与
    api_menu_status 的 resolved cli_model 同源，故 env 覆盖下 label 不与实际相左（CMR R2）。
    清单来源 = docs/LLM_BACKEND_BENCH.md「可用主力」。下拉只挡常见拼写/大小写错；某档实际
    可用性仍取决于账号类型(ChatGPT vs API key)与 CLI 版本，连通性检查仍是兜底。
    每次返回独立副本，调用方改动不污染下次调用。"""
    # 懒导入避免与 llm_config 的环依赖（llm_config 已懒导入本模块的默认常量）。
    from ming_sim.llm_config import cli_model_from_env
    codex_default = cli_model_from_env("codex", CODEX_DEFAULT_MODEL)
    claude_default = cli_model_from_env("claude", CLAUDE_DEFAULT_MODEL)
    return {
        # codex：默认 gpt-5.5（机理扎实、字段全）；spark 最快、建 issue 满分。
        # gpt-5.4 不入档（bench 偏长且不在「可用主力」；mini 漏 DECISION 块已淘汰）。
        "codex": [
            {"value": "", "label": f"默认 · {codex_default}"},
            {"value": "gpt-5.3-codex-spark", "label": "gpt-5.3-codex-spark · 快"},
        ],
        # claude：默认 opus-4-8；haiku 配 MAX_THINKING_TOKENS≈10k 时与 codex/agy 同档快；
        # sonnet 跑 simulator 5-7 分钟，交互嫌慢，留作离线叙事鉴赏。
        "claude": [
            {"value": "", "label": f"默认 · {claude_default}"},
            {"value": "claude-haiku-4-5", "label": "claude-haiku-4-5 · 快"},
            {"value": "claude-sonnet-4-6", "label": "claude-sonnet-4-6 · 慢，偏离线鉴赏"},
        ],
        # agy：模型档模糊，只给「默认（gemini）」+ 前端「其他(手填)」逃生口。
        "agy": [
            {"value": "", "label": "默认 · gemini"},
        ],
        # #1256 新 runner：策展档未立，只给默认档 + 前端「其他(手填)」逃生；--model 透传。
        "cursor": [
            {"value": "", "label": "默认"},
        ],
        "kimi": [
            {"value": "", "label": "默认"},
        ],
        "grok": [
            {"value": "", "label": "默认"},
        ],
    }


def supported_cli_runners_text() -> str:
    """错误文案用：受支持 runner 名单（单一真源派生，排序稳定）。"""
    return " / ".join(sorted(_CLI_BACKENDS))


def is_supported_cli_runner(name: object) -> bool:
    """runner 名是否是受支持的 CLI 后端（见 _CLI_BACKENDS 单一真源）。"""
    return str(name or "").strip().lower() in _CLI_BACKENDS


# ── runner 可执行定位（GUI/.app 启动 PATH 缺失的治本解）────────────────────
# Finder 双击的 .app 只继承 launchd 精简 PATH（无 ~/.local/bin、/opt/homebrew/bin），
# 裸名 exec "codex"/"claude"/"agy" 会 FileNotFoundError——即便用户已按官方装好。
# 解析成绝对路径即治本：用绝对路径 exec 不依赖 PATH。解析顺序见 _resolve_cli_bin。
_EXTRA_BIN_DIRS = [
    os.path.expanduser("~/.local/bin"),       # codex 官方独立安装 / pipx / cursor-agent
    os.path.expanduser("~/.kimi-code/bin"),   # kimi Code CLI
    os.path.expanduser("~/.grok/bin"),        # Grok Build CLI
    os.path.expanduser("~/.bun/bin"),
    os.path.expanduser("~/.deno/bin"),
    os.path.expanduser("~/.cargo/bin"),
    os.path.expanduser("~/.npm-global/bin"),   # npm -g 自定义前缀
    "/opt/homebrew/bin",                       # Apple Silicon homebrew
    "/usr/local/bin",                          # Intel homebrew / 手装
]
_BIN_CACHE: Dict[str, str] = {}               # runner 名 → 解析后的可执行路径（进程内缓存）
_DISCOVERED_LOGIN_PATH: Optional[str] = None  # 登录 shell PATH，懒发现一次
# 登录 shell 探测走「import 时捕获的原始 run」，不受测试 monkeypatch cb.subprocess.run
# 影响，也就不会污染 _run_agy 等的 mock 调用计数。
_RAW_RUN = subprocess.run


def _login_shell_path() -> Optional[str]:
    """问用户登录 shell 要真实 PATH（GUI/.app 不继承 shell PATH 的**最后**一级兜底）。
    用 sentinel 包裹 printf "$PATH"，正则只取 sentinel 之间的真实 PATH——rc 噪声行
    （含冒号/斜杠的告警）不会被误当 PATH，单目录 PATH（无分隔符）也不会被漏掉。
    缓存一次：探测代价高（会 source rc），且进程内不变。失败返回 None。"""
    global _DISCOVERED_LOGIN_PATH
    if _DISCOVERED_LOGIN_PATH is not None:
        return _DISCOVERED_LOGIN_PATH or None
    discovered = ""
    shell = os.environ.get("SHELL") or "/bin/zsh"
    try:
        # 用 printenv 取已导出的 PATH（shell 无关）：不靠 "$PATH" 展开——fish 把 $PATH
        # 当 list、双引号里展开成空格分隔，会破后面的冒号切分（gemini r2 G-R1）。
        # printenv 是外部命令，读到的是登录 shell 导出的 env PATH（恒冒号分隔）。
        # flag 分开传 -l -i -c：组合形式 -lic 在 fish 等 shell 报错（不支持组合单字符
        # 选项）；分开形式各 shell 通吃，仍由外层 try 兜底（gemini PR#115 high）。
        proc = _RAW_RUN(
            [shell, "-l", "-i", "-c", 'printf "<<<CMRPATH>>>"; printenv PATH; printf "<<<ENDPATH>>>"'],
            capture_output=True, text=True, timeout=8,
        )
        m = re.search(r"<<<CMRPATH>>>(.*?)<<<ENDPATH>>>", proc.stdout or "", re.S)
        if m:
            discovered = m.group(1).strip()
    except Exception:
        discovered = ""
    _DISCOVERED_LOGIN_PATH = discovered
    return discovered or None


def _dedup_path(chunks: List[str]) -> str:
    """把若干 PATH 片段拼成一条去重保序的 search path。"""
    seen: set = set()
    dirs: List[str] = []
    for chunk in chunks:
        for d in chunk.split(os.pathsep):
            if d and d not in seen:
                seen.add(d)
                dirs.append(d)
    return os.pathsep.join(dirs)


def _static_search_path() -> str:
    """当前 PATH + 常见安装目录，去重保序（**不含**登录 shell——那是更后一级兜底，
    避免在 extra-dir 本可命中时也白 spawn 一个 zsh）。"""
    chunks: List[str] = [d for d in _EXTRA_BIN_DIRS if os.path.isdir(d)]
    cur = os.environ.get("PATH", "")
    if cur:
        chunks.append(cur)
    return _dedup_path(chunks)


def _resolve_cli_bin(name: str, configured: str) -> str:
    """runner（agy/codex/claude）解析成可执行绝对路径，**命中才缓存**。分级兜底，
    登录 shell 是最后一级（仅前两级都 miss 才 spawn zsh）：
    1) 现有 PATH which（含 MING_SIM_*_BIN 给的绝对路径）。
    2) 补常见安装目录（~/.local/bin 等）再 which——不 spawn 登录 shell。
    3) 仍 miss → 问登录 shell 要真实 PATH，并入再 which（此时才 spawn zsh）。
    4) 全不中 → 退回原配置名（让 subprocess 抛清晰 FileNotFoundError），**不缓存**，
       binary 之后才装上时下次仍能重新解析（不被裸名负缓存毒住）。"""
    # 锁护缓存读改写：#83 并发首解时只让一个线程跑解析（含可能 spawn 登录 shell），余者待后命中
    # 缓存，免重复 spawn / 竞态写缓存。命中后是一次性开销，串行路径无竞争。
    with _BIN_CACHE_LOCK:
        cached = _BIN_CACHE.get(name)
        if cached:
            return cached
        found = shutil.which(configured)
        if not found:
            found = shutil.which(configured, path=_static_search_path())
        if not found:
            login = _login_shell_path()
            if login:
                found = shutil.which(configured, path=_dedup_path([_static_search_path(), login]))
        if found:
            # 绝对化:configured 是相对路径(相对 MING_SIM_*_BIN / 相对 PATH 项)时 which 会
            # 返回相对串,而 _run_* 用 cwd=_AGY_CWD 跑会按沙箱目录解析→FileNotFoundError;
            # 绝对路径才兑现「解析成可执行绝对路径」的契约(gemini r2 G-R2)。abspath 对已
            # 绝对的路径是 no-op。
            found = os.path.abspath(found)
            _BIN_CACHE[name] = found
            return found
        return configured


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
# #83 月末 extractor 并发：CliChat.invoke 被多线程并发调（codex 后端）。_seq 自增是非原子读改写
# （丢增量→seq 重复）、trace 大行并发写可能交错、_BIN_CACHE 首解可重复 spawn——加锁让这些共享态
# 线程安全（cmr #83 线上 gemini high）。锁只护「计数/写盘/缓存」瞬时段，LLM 调用 _call_cli 在锁外，
# 并发不受影响。串行/形态1 路径下锁无竞争、开销可忽略。
_TRACE_LOCK = threading.Lock()      # 护 _seq 自增 + _trace 写盘 + _trace_announced
_BIN_CACHE_LOCK = threading.Lock()  # 护 _BIN_CACHE 解析+写入（首解只一次，余者命中缓存）


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
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with _TRACE_LOCK:  # 串行化写盘，防并发大行交错损坏 trace（#83）
            with open(_TRACE_PATH, "a", encoding="utf-8") as f:
                f.write(line)
            announce = not _trace_announced
            _trace_announced = True
        if announce:
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


def _run_agy(prompt: str, timeout: Optional[float] = None) -> Tuple[str, int]:
    """调 agy -p --sandbox，warm + retry。返回 (纯文本, 实际尝试次数)。"""
    run_timeout = timeout or _AGY_TIMEOUT
    last = ""
    for attempt in range(1, 5):  # 初试 1 + 最多 retry 3 = 4
        _warm_keychain()
        try:
            # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit,python.lang.security.audit.dangerous-subprocess-use-tainted-env-args
            # 安全审计(Sourcery):list-form argv、无 shell=True → 不经 shell 解析,无注入面。prompt 走 stdin。
            proc = subprocess.run(
                [_resolve_cli_bin("agy", _AGY_BIN), "-p", "--sandbox"],
                input=prompt, capture_output=True, text=True, timeout=run_timeout,
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
        # 非零退出 / 空输出当失败 attempt：不把错误 stderr 当角色回话落库（CMR F2）。
        if proc.returncode != 0 or not out:
            last = f"退出码 {proc.returncode}，输出空或异常：{out[:120]}"
            _log(f"attempt {attempt}: rc={proc.returncode} empty/err，重试")
            continue
        _log(f"attempt {attempt}: ok（{len(out)} chars）")
        return out, attempt
    raise RuntimeError(f"agy 调用失败（warm+retry×4 仍不成）：{last[:200]}")


def _codex_reasoning_effort(reasoning_strength: Optional[str]) -> str:
    if reasoning_strength is None:
        return (os.environ.get("MING_SIM_CODEX_REASONING") or "").strip()
    return _CODEX_REASONING_BY_STRENGTH.get(str(reasoning_strength or "").strip().lower(), "")


def _run_codex(
    prompt: str,
    model: Optional[str] = None,
    timeout: Optional[float] = None,
    reasoning_strength: Optional[str] = None,
) -> Tuple[str, int]:
    """调 codex exec -（stdin pipe，绝不 positional）。返回 (文本, 尝试次数=1)。

    实测三坑（见 docs/LLM_BACKEND_BENCH.md §9）：
    - `--skip-git-repo-check`：cwd 是非 git 沙箱目录，不加则秒报 "Not inside a trusted directory"。
    - `--ephemeral`：不落盘 session，否则并发多调撞共享 session 状态（rollout thread not found）丢空输出。
    - 干净最终回话在 **stdout**，诊断/日志在 stderr —— 只取 stdout，绝不合并（合并会把
      "OpenAI Codex v…/tokens used" 等日志混进角色回话）。stdout 空时兜底从合并流剥壳。
    reasoning：默认不强加，尊重用户 ~/.codex/config.toml；设 MING_SIM_CODEX_REASONING 才传 -c。"""
    cmd = [_resolve_cli_bin("codex", _CODEX_BIN), "exec", "--model", (model or _CODEX_MODEL)]
    reasoning = _codex_reasoning_effort(reasoning_strength)
    if reasoning:
        cmd += ["-c", f'model_reasoning_effort="{reasoning}"']
    cmd += ["--ephemeral", "--skip-git-repo-check", "-"]
    try:
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit,python.lang.security.audit.dangerous-subprocess-use-tainted-env-args
        # 安全审计(Sourcery):list-form argv、无 shell=True;runner 已 allowlist、model 为独立 argv、prompt 走 stdin → 无注入面。
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, timeout=timeout or _AGY_TIMEOUT,
            cwd=_AGY_CWD,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("codex 调用超时") from exc
    out = (proc.stdout or "").strip()
    if not out:  # 兜底：干净段在合并流 "OpenAI Codex v" 之前
        combined = (proc.stdout or "") + (proc.stderr or "")
        out = combined.split("OpenAI Codex v")[0].strip()
    # 非零退出 / 最终空输出 → 抛错，不静默当空回复落库（CMR F2）。
    if proc.returncode != 0 or not out:
        raise RuntimeError(f"codex 调用失败（退出码 {proc.returncode}）：{(proc.stderr or '')[:200]}")
    return out, 1


def _codex_cmd(
    model: Optional[str] = None,
    *,
    json_events: bool = False,
    reasoning_strength: Optional[str] = None,
) -> List[str]:
    cmd = [_resolve_cli_bin("codex", _CODEX_BIN), "exec", "--model", (model or _CODEX_MODEL)]
    reasoning = _codex_reasoning_effort(reasoning_strength)
    if reasoning:
        cmd += ["-c", f'model_reasoning_effort="{reasoning}"']
    if json_events:
        cmd.append("--json")
    cmd += ["--ephemeral", "--skip-git-repo-check", "-"]
    return cmd


def _codex_event_text(obj: object) -> str:
    if not isinstance(obj, dict):
        return ""
    typ = str(obj.get("type") or obj.get("event") or "")
    if "delta" in typ:
        for key in ("delta", "content", "text"):
            value = obj.get(key)
            if isinstance(value, str) and value:
                return value
        nested = obj.get("message")
        if isinstance(nested, dict):
            value = nested.get("delta") or nested.get("content") or nested.get("text")
            return value if isinstance(value, str) else ""
    return ""


def _codex_final_text(obj: object) -> str:
    if not isinstance(obj, dict):
        return ""
    typ = str(obj.get("type") or obj.get("event") or "")
    if "delta" in typ:
        return ""
    # 防御性兼容 codex `--json` 的 item.* 形态（如 {"type":"item.completed",
    # "item":{"type":"agent_message","text":"…"}}）：最终 agent message 可能嵌在 item.text
    # 里。只取 agent_message 类 item，忽略 reasoning/tool/plan item，避免把真实邸报当成空
    # 输出误判失败（codex correctness）。与下面的顶层 message/text 形态并存，互不影响。
    item = obj.get("item")
    if isinstance(item, dict):
        item_type = str(item.get("type") or "")
        if item_type in ("", "agent_message") or "message" in item_type:
            value = item.get("text") or item.get("content") or item.get("message")
            if isinstance(value, str) and value:
                return value
    for key in ("message", "content", "text", "final", "last_message"):
        value = obj.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            nested = value.get("content") or value.get("text") or value.get("message")
            if isinstance(nested, str) and nested:
                return nested
    return ""


def _iter_codex_stream_chunks(
    prompt: str,
    *,
    model: Optional[str] = None,
    timeout: Optional[float] = None,
    reasoning_strength: Optional[str] = None,
) -> Iterator[str]:
    """Run `codex exec --json` and yield agent_message_delta events as they arrive."""
    cmd = _codex_cmd(model, json_events=True, reasoning_strength=reasoning_strength)
    run_timeout = timeout or _AGY_TIMEOUT
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=_AGY_CWD,
        )
    except OSError as exc:
        raise RuntimeError(f"codex 流式调用启动失败：{exc}") from exc

    assert proc.stdout is not None
    if proc.stdin is not None:
        proc.stdin.write(prompt)
        proc.stdin.close()

    pieces: List[str] = []
    final_text = ""
    stderr = ""
    timed_out = False
    # stderr 必须并发抽干（cmr Gate2 F-F）：stdout/stderr 同一阻塞管道模型——codex 往 stderr
    # 写满 OS pipe 缓冲（~64KB）就会卡在写 stderr，stdout 随之断流，下面的 `for raw_line in
    # proc.stdout` 拿不到 EOF 永久阻塞，最后被 watchdog 误杀成「超时」。开 daemon 线程持续读
    # stderr，stdout 循环结束后 join 取诊断文本（不能等读完 stdout 再 read stderr）。
    stderr_parts: List[str] = []

    def _drain_stderr() -> None:
        if proc.stderr is not None:
            try:
                stderr_parts.append(proc.stderr.read())
            except Exception:
                pass

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()
    # 看门狗：流式读取阻塞在 `for raw_line in proc.stdout` 上，下面的 proc.wait(timeout) 要等读
    # 循环结束才执行——若 codex 卡死且不关 stdout，读循环会无限阻塞、那个 timeout 形同虚设
    # (codex correctness)。定时器在 run_timeout 到点 kill 进程，使阻塞读拿到 EOF 退出循环。
    def _kill_on_timeout() -> None:
        nonlocal timed_out
        timed_out = True
        try:
            proc.kill()
        except Exception:
            pass

    watchdog = threading.Timer(run_timeout, _kill_on_timeout)
    watchdog.daemon = True
    watchdog.start()
    try:
        for raw_line in proc.stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            delta = _codex_event_text(obj)
            if delta:
                pieces.append(delta)
                yield delta
                continue
            maybe_final = _codex_final_text(obj)
            if maybe_final:
                final_text = maybe_final
        proc.wait(timeout=run_timeout)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        raise RuntimeError("codex 流式调用超时") from exc
    finally:
        watchdog.cancel()
        # consumer 提前弃用（break/异常/GeneratorExit）时底层 codex 子进程仍在跑 → 泄漏。
        # terminate+wait 兜底（正常路径 proc 已退，terminate 对已退进程是 no-op）（#399 cmr R1 coderabbit Major）。
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
        # 进程已退/被 kill → stderr 关闭 → drain 线程读到 EOF 结束；取其抽到的诊断文本。
        stderr_thread.join(timeout=2)
        stderr = "".join(stderr_parts)

    if timed_out:
        raise RuntimeError(f"codex 流式调用超时（>{run_timeout:.0f}s 未完成，已 kill）")
    text = "".join(pieces).strip() or final_text.strip()
    if proc.returncode != 0 or not text:
        raise RuntimeError(f"codex 流式调用失败（退出码 {proc.returncode}）：{(stderr or '')[:200]}")
    if not pieces and final_text.strip():
        yield final_text.strip()


def _run_codex_stream(
    prompt: str,
    *,
    model: Optional[str] = None,
    timeout: Optional[float] = None,
    reasoning_strength: Optional[str] = None,
    on_text: Optional[Callable[[str], None]] = None,
) -> Tuple[str, int]:
    pieces: List[str] = []
    for delta in _iter_codex_stream_chunks(
        prompt, model=model, timeout=timeout, reasoning_strength=reasoning_strength
    ):
        pieces.append(delta)
        if on_text:
            on_text(delta)
    text = "".join(pieces).strip()
    if not text:
        raise RuntimeError("codex 流式调用失败：输出为空")
    return text, 1


def _run_claude(
    prompt: str,
    model: Optional[str] = None,
    timeout: Optional[float] = None,
    reasoning_strength: Optional[str] = None,
) -> Tuple[str, int]:
    """调 claude -p（独立进程，stdin pipe）。返回 (纯文本, 1)。
    与 codex 不同：claude -p 干净最终回话在 **stdout**，日志/诊断在 stderr，
    故只取 stdout、不合并 stderr（合并会把日志混进角色回话）。
    未配置 reasoning_strength 时继承父进程 env；配置后显式设置 MAX_THINKING_TOKENS。"""
    cmd = [_resolve_cli_bin("claude", _CLAUDE_BIN), "-p", "--model", (model or _CLAUDE_MODEL),
           "--output-format", "text", "--disallowed-tools", *_CLAUDE_DISALLOWED]
    env = None
    if reasoning_strength is not None:
        env = dict(os.environ)
        strength = str(reasoning_strength or "").strip().lower()
        tokens = _CLAUDE_THINKING_TOKENS_BY_STRENGTH.get(strength)
        if tokens:
            env["MAX_THINKING_TOKENS"] = tokens
        else:
            env.pop("MAX_THINKING_TOKENS", None)
    try:
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit,python.lang.security.audit.dangerous-subprocess-use-tainted-env-args
        # 安全审计(Sourcery):list-form argv、无 shell=True;runner 已 allowlist、model 为独立 argv、prompt 走 stdin → 无注入面。
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            timeout=timeout or _AGY_TIMEOUT, cwd=_AGY_CWD, env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("claude 调用超时") from exc
    out = (proc.stdout or "").strip()
    # 非零退出 / 空输出 → 抛错，不静默当空回复落库（CMR F2）。
    if proc.returncode != 0 or not out:
        raise RuntimeError(f"claude 调用失败（退出码 {proc.returncode}）：{(proc.stderr or '')[:200]}")
    return out, 1


def _run_cursor(
    prompt: str,
    model: Optional[str] = None,
    timeout: Optional[float] = None,
    reasoning_strength: Optional[str] = None,  # noqa: ARG001 — 签名与其它 runner 对齐；cursor 无 effort 档
) -> Tuple[str, int]:
    """调 cursor-agent -p --output-format text（#1256）。
    模型 --model 透传；--trust 免非交互 workspace 信任闸；干净输出在 stdout。
    prompt 走 positional（CLI 无 stdin 约定）。"""
    cmd = [
        _resolve_cli_bin("cursor", _CURSOR_BIN),
        "-p", "--output-format", "text", "--trust",
    ]
    if model:
        cmd.extend(["--model", model])
    cmd.append(prompt)
    try:
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit,python.lang.security.audit.dangerous-subprocess-use-tainted-env-args
        # 安全审计:list-form argv、无 shell=True;runner allowlist、model 独立 argv、prompt 为末位 positional。
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout or _AGY_TIMEOUT, cwd=_AGY_CWD,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("cursor 调用超时") from exc
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        raise RuntimeError(f"cursor 调用失败（退出码 {proc.returncode}）：{(proc.stderr or '')[:200]}")
    return out, 1


def _run_kimi(
    prompt: str,
    model: Optional[str] = None,
    timeout: Optional[float] = None,
    reasoning_strength: Optional[str] = None,  # noqa: ARG001 — 签名对齐；kimi -p 无 effort 档
) -> Tuple[str, int]:
    """调 kimi -p（#1256）。
    纪律：-p 单用，禁与 --yolo/--auto 组合（本机 kimi 0.36.1 实测 parse 拒收）；
    干净答案在 stdout，版本/thinking/resume 噪声在 stderr——只取 stdout。
    prompt 走 -p 参数（非 stdin）。"""
    cmd = [_resolve_cli_bin("kimi", _KIMI_BIN), "-p", prompt, "--output-format", "text"]
    if model:
        cmd.extend(["-m", model])
    try:
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit,python.lang.security.audit.dangerous-subprocess-use-tainted-env-args
        # 安全审计:list-form argv、无 shell=True;runner allowlist、model 独立 argv、prompt 为 -p 值。
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout or _AGY_TIMEOUT, cwd=_AGY_CWD,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("kimi 调用超时") from exc
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        raise RuntimeError(f"kimi 调用失败（退出码 {proc.returncode}）：{(proc.stderr or '')[:200]}")
    return out, 1


def _grok_effort(reasoning_strength: Optional[str]) -> Optional[str]:
    strength = str(reasoning_strength or "").strip().lower()
    return _GROK_EFFORT_BY_STRENGTH.get(strength)


def _run_grok(
    prompt: str,
    model: Optional[str] = None,
    timeout: Optional[float] = None,
    reasoning_strength: Optional[str] = None,
) -> Tuple[str, int]:
    """调 Grok Build CLI（#1256 / bench §十二 grok-4.5 腿）。
    -p/--single 单轮；--output-format plain；-m 透传；--effort 仅 low/med/high。
    prompt 走 -p 参数。"""
    cmd = [
        _resolve_cli_bin("grok", _GROK_BIN),
        "-p", prompt,
        "--output-format", "plain",
    ]
    if model:
        cmd.extend(["-m", model])
    effort = _grok_effort(reasoning_strength)
    if effort:
        cmd.extend(["--effort", effort])
    try:
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit,python.lang.security.audit.dangerous-subprocess-use-tainted-env-args
        # 安全审计:list-form argv、无 shell=True;runner allowlist、model/effort 独立 argv、prompt 为 -p 值。
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout or _AGY_TIMEOUT, cwd=_AGY_CWD,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("grok 调用超时") from exc
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        raise RuntimeError(f"grok 调用失败（退出码 {proc.returncode}）：{(proc.stderr or '')[:200]}")
    return out, 1


def _run_backend(prompt: str) -> Tuple[str, int]:
    """按 MING_SIM_LLM_BACKEND 分派到对应 CLI（enrich/secret 等非 CliChat 路径用）。
    未设或非法 → agy（沿用原默认）。"""
    b = cli_backend_from_env()
    if b == "codex":
        return _run_codex(prompt)
    if b == "claude":
        return _run_claude(prompt)
    if b == "cursor":
        return _run_cursor(prompt)
    if b == "kimi":
        return _run_kimi(prompt)
    if b == "grok":
        return _run_grok(prompt)
    return _run_agy(prompt)


def _llm_channel(llm_config: Any = None) -> str:
    return (getattr(llm_config, "channel", "") or "").strip().lower()


def _cli_config_parts(llm_config: Any = None) -> Optional[Tuple[str, str, Optional[float], str]]:
    channel = _llm_channel(llm_config)
    if channel != "cli":
        return None
    runner = (getattr(llm_config, "cli_runner", "") or cli_backend_from_env() or "agy").strip().lower()
    if runner not in _CLI_BACKENDS:
        raise RuntimeError(f"未知 CLI backend：{runner}")
    model = (getattr(llm_config, "cli_model", "") or "").strip()
    raw_timeout = getattr(llm_config, "cli_timeout_seconds", None)
    try:
        timeout = float(raw_timeout) if raw_timeout else None
    except (TypeError, ValueError):
        timeout = None
    reasoning_strength = str(getattr(llm_config, "reasoning_strength", "") or "").strip().lower()
    return runner, model, timeout, reasoning_strength


def _run_backend_for_config(prompt: str, llm_config: Any = None, tag: str = "") -> Tuple[str, int]:
    """runtime CLI 配置优先；没有显式 CLI channel 时保持旧 env/default 行为。

    直接编程路径（职官分类/各 extractor/国策补全/连通性 verify）的唯一咽喉：
    每次调用 try/finally 写一条 trace，谁调都记，不靠各调用方自觉手写。
    （agno 游戏路径走 CliChat.invoke 自有 trace，与此咽喉不重叠。）
    tag 空时退回 _infer_tag(prompt)。"""
    if _llm_channel(llm_config) == "api":
        raise RuntimeError("显式 API channel 未启用本地 CLI backend")
    parts = _cli_config_parts(llm_config)
    model_id = (parts[1] if parts else "") or _backend_label(llm_config)
    t0 = time.monotonic()
    text, attempts, error = "", 0, None
    try:
        if parts is None:
            text, attempts = _run_backend(prompt)
        else:
            runner, model, timeout, reasoning_strength = parts
            if runner == "codex":
                text, attempts = _run_codex(
                    prompt,
                    model=model or None,
                    timeout=timeout,
                    reasoning_strength=reasoning_strength or None,
                )
            elif runner == "claude":
                text, attempts = _run_claude(
                    prompt,
                    model=model or None,
                    timeout=timeout,
                    reasoning_strength=reasoning_strength or None,
                )
            elif runner == "cursor":
                text, attempts = _run_cursor(
                    prompt,
                    model=model or None,
                    timeout=timeout,
                    reasoning_strength=reasoning_strength or None,
                )
            elif runner == "kimi":
                text, attempts = _run_kimi(
                    prompt,
                    model=model or None,
                    timeout=timeout,
                    reasoning_strength=reasoning_strength or None,
                )
            elif runner == "grok":
                text, attempts = _run_grok(
                    prompt,
                    model=model or None,
                    timeout=timeout,
                    reasoning_strength=reasoning_strength or None,
                )
            else:
                text, attempts = _run_agy(prompt, timeout=timeout)
        return text, attempts
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        _trace({
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "seq": -1, "tag": tag or _infer_tag(prompt),
            "backend": _backend_label(llm_config), "model_id": model_id,
            "dur_s": round(time.monotonic() - t0, 1), "attempts": attempts,
            "wants_json": False,
            "prompt_chars": len(prompt), "resp_chars": len(text),
            "error": error, "prompt": prompt, "response": text,
        })


def _run_api_for_config(prompt: str, llm_config: Any = None, tag: str = "") -> Tuple[str, int]:
    """Run a small extraction prompt through the configured API model."""
    from agno.agent import Agent
    from ming_sim.llm_model import create_chat_model, extract_agent_text

    agent = Agent(
        name=f"API抽取器-{tag or 'generic'}",
        id=f"api-extractor-{tag or 'generic'}",
        session_id=f"api-extractor-{tag or 'generic'}",
        model=create_chat_model(
            llm_config, temperature=0, max_tokens=1200, force_json_output=True,
        ),
        instructions=["只输出符合要求的 JSON/文本，不要 markdown 代码围栏。"],
        markdown=False,
    )
    return extract_agent_text(agent.run(prompt)), 1


def _run_json_extractor_for_config(prompt: str, llm_config: Any = None, tag: str = "") -> Tuple[str, int]:
    if _llm_channel(llm_config) == "api":
        return _run_api_for_config(prompt, llm_config, tag=tag)
    return _run_backend_for_config(prompt, llm_config, tag=tag)


def _backend_label(llm_config: Any = None) -> str:
    if _llm_channel(llm_config) == "api":
        return "api"
    try:
        parts = _cli_config_parts(llm_config)
    except RuntimeError:
        parts = None  # 不支持的 runner：trace 标签回落，不让构造崩
    if parts is not None:
        return parts[0] or "agy"
    return cli_backend_from_env() or "agy"


def describe_effective_model(llm_config: Any = None) -> str:
    """日志用：返回该 config **实际调用**的「runner/model」可读串，而非 CLI 通道下的 API-fallback
    占位 `cfg.model`（如 gpt-4o-mini）——后者误导排查（#84）。runner 解析与 create_chat_model 同口径：
    api 通道→cfg.model；cli/legacy-env→真实 runner + 解析后的 cli_model（如 codex/gpt-5.3-codex-spark）。
    注：legacy-env 默认模型下，CliChat.id 留空（_run_codex 再回落 _CODEX_MODEL），故 trace 的 model_id
    可能是空串而本函数已解析出真实默认——本函数是更准的可读标签，不与 trace 的未解析 id 逐字对齐。"""
    channel = _llm_channel(llm_config)
    if channel == "cli":
        runner = (getattr(llm_config, "cli_runner", "") or cli_backend_from_env() or "agy").strip().lower()
    elif channel != "api":
        runner = cli_backend_from_env()  # 空 channel：legacy env 回落
    else:
        runner = None
    if not runner:  # api 通道 / 形态1（空 channel 无 env）：用 cfg.model
        return str(getattr(llm_config, "model", "") or "?")
    # 只有实际吃 --model 的 runner 才追加 /model；agy 忽略 model、走自身 Gemini ladder，
    # 给它挂个不被消费的 cli_model 反而误导（#84 codex），只显示 runner 名。
    if runner in _CLI_MODEL_RUNNERS:
        from ming_sim.llm_config import cli_model_from_env
        model = (str(getattr(llm_config, "cli_model", "") or "").strip()) or cli_model_from_env(runner)
        return f"{runner}/{model}" if model else runner
    return runner


def cli_backend_active(llm_config: Any = None) -> bool:
    """是否处于 CLI 后端路径：显式 channel 直接按其 runner 判，无显式 channel 才看旧 env。"""
    channel = _llm_channel(llm_config)
    if channel == "api":
        return False
    if channel == "cli":
        # 显式 CLI：直接判 runner，不回落 env。否则 bogus runner 误报 active，
        # 执行期 _run_backend_for_config 再调 _cli_config_parts 仍会崩。
        try:
            return _cli_config_parts(llm_config) is not None
        except RuntimeError:
            return False
    return cli_backend_from_env() is not None


# 已证「并发取数无 session 串话」的 CLI runner 白名单：仅 codex（每次 exec 带 --ephemeral，
# 不落盘 session rollout，openai/codex#11435 workaround，#83 立项基础）。claude（claude -p 虽
# 独立进程但并发未实测、有 rate-limit 顾虑）、agy（keychain auth-race，cmr 故意一次只跑一个）暂
# 不在内——验证其并发安全后再加。月末 4-extractor 并行只对本名单启用，其余 runner 串行不变。
_PARALLEL_SAFE_CLI_RUNNERS = {"codex"}


def cli_backend_parallel_safe(llm_config: Any = None) -> bool:
    """月末多 extractor 并发是否安全：实际后端 runner 须在 _PARALLEL_SAFE_CLI_RUNNERS 内（仅 codex）。

    比 cli_backend_active 严：后者「是不是 CLI 后端」，本预言「这个 runner 并发取数安全吗」。
    --ephemeral 隔离只对 codex 成立，故只有 codex 返 True；claude/agy/api/形态1 返 False=串行（#83）。

    runner 解析**精确镜像 create_chat_model**（llm_model.py，extractor 真正用的后端）：
    channel=='cli' → cli_runner or 旧 env or 'agy'；channel=='' → 旧 env（legacy/形态1）；'api' → 无 CLI。
    与 cli_backend_active 用 _cli_config_parts（只认显式 cli channel）不同——否则 legacy env=codex
    会被误判串行（cmr #83 codex R3：门控须与执行端同口径解 runner）。"""
    channel = _llm_channel(llm_config)
    if channel == "api":
        return False
    if channel == "cli":
        runner = (getattr(llm_config, "cli_runner", "") or cli_backend_from_env() or "agy").strip().lower()
    else:
        runner = cli_backend_from_env()  # 空 channel（legacy/形态1）：env 回落，无 env → None
    return runner in _PARALLEL_SAFE_CLI_RUNNERS


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
# agy/codex/claude 不做 function-calling，唯一缺口在此。玩家用「拟旨/下密令」按钮 =
# 消息带「拟旨如下：/密令如下：」前缀 = 已表态要下旨，据此分派：
#   拟旨：大臣回话原文即这道圣旨草稿，整段入档（单一文本字段，够用；多轮聊出多道 →
#         颁诏时玩家去重）。
#   密令（#397/#413/#1274 K1）：交 _extract_secret_order 抽结构化字段；content=
#         御旨+extractor「内容」（reply 不入拼装；大臣实质补充走 schema 字段）；候选先入
#         pending_actions 确认闸门，皇帝应允或回合默认提交时才正式落库。
_DRAFT_PREFIXES = ("拟旨如下：", "拟旨如下:", "拟旨：", "拟旨:")
_SECRET_PREFIXES = ("密令如下：", "密令如下:", "密令：", "密令:")


# 大臣会话动作抽取（CLI 后端无 function-calling）：
# 不靠关键字白名单（脆、永远漏），交给 LLM 读对话判意图——皇帝本轮对该大臣【现有密令】
# 要做什么（更新内容 / 提交核议 / 催办 / 记进展），以及若是妃嫔有无调教。
# 只在「大臣有 active 密令 或 是妃嫔」时调（省 token）。
def extract_minister_actions(
    player_message: str,
    minister_reply: str,
    active_orders: List[Dict[str, Any]],
    is_consort: bool = False,
    llm_config: Any = None,
) -> Dict[str, Any]:
    """LLM 判皇帝本轮对密令/妃嫔的意图，返回结构化动作。失败返回「无」动作。"""
    orders_brief = "；".join(
        f"#{o.get('id')}「{o.get('title', '')}」：{str(o.get('content', ''))[:50]}"
        for o in (active_orders or [])
    ) or "（无）"
    consort_line = (
        '  "调教技能": "", "调教性格": "",   // 仅当此人是妃嫔、且皇帝在调教她(赐技能/改性格)时填，否则空\n'
        if is_consort else ""
    )
    prompt = (
        "你是信息抽取器，不扮演、不写圣旨。读皇帝这句话 + 大臣回话 + 该大臣现有密令清单，"
        "判断皇帝**本轮**对密令"
        + ("（及调教妃嫔）" if is_consort else "")
        + "的意图。只输出一个 JSON 对象（无代码围栏、无多余字）：\n"
        "{\n"
        '  "密令动作": "无|更新|提交核议|催办|记进展",  // 皇帝补充/改/纠正某现有密令的内容或数额=更新；让其呈报办结待核=提交核议；催/加急/限期=催办；问进度并据回话记录=记进展；都不是=无\n'
        '  "目标密令编号": 0,                        // 上述动作针对哪条现有密令的 id（清单里的 #数字）；只有一条时填那条\n'
        '  "新标题": "", "新内容": "", "期限月数": 0,  // 仅"更新"时给：综合皇帝话+大臣回话，写该密令改后的【完整新要旨】\n'
        + consort_line +
        "}\n"
        "判定要点：皇帝口语如「更新/改成/其实是/纠正/补充…」指向某现有密令即「更新」，新内容要把改动并入完整要旨（别只写增量）。语义判断，别拘泥字面措辞。\n\n"
        "【该大臣现有密令】" + orders_brief + "\n"
        "【皇帝】" + (player_message or "（无）") + "\n"
        "【大臣回话】" + (minister_reply or "（无）") + "\n"
    )
    raw = ""
    try:
        raw, _ = _run_backend_for_config(prompt, llm_config, tag="minister_actions")
    except Exception as exc:  # 抽取失败不阻断对话
        _log(f"大臣动作抽取失败：{exc}")
    obj = _loads_lenient(raw) or {}

    def _int(v, hi=10**9):
        try:
            return max(0, min(int(v or 0), hi))
        except (TypeError, ValueError):
            return 0

    # 动作归一到固定枚举：LLM 返回枚举外的串 → 「无」，防按未知动作误操作（CMR F10）。
    # order_id 不在此处强校验 active：消费方（web/session）持 active 清单做范围校验 + 单条兜底。
    _raw_action = str(obj.get("密令动作") or "无").strip()
    _action = _raw_action if _raw_action in {"无", "更新", "提交核议", "催办", "记进展"} else "无"
    return {
        "secret_action": _action,
        "order_id": _int(obj.get("目标密令编号")),
        # Title has no formal length cap (family removed silent 20-char hard trunc).
        "new_title": str(obj.get("新标题") or "").strip(),
        "new_content": str(obj.get("新内容") or "").strip(),
        "deadline_months": _int(obj.get("期限月数"), 36),
        "cultivate_skill": str(obj.get("调教技能") or "").strip()[:20],
        "cultivate_trait": str(obj.get("调教性格") or "").strip()[:20],
    }


def classify_cli_action_intent(
    player_message: str,
    active_orders: Optional[List[Dict[str, Any]]] = None,
    is_consort: bool = False,
    has_pending_draft: bool = False,
    pending_summaries: Optional[List[str]] = None,
    llm_config: Any = None,
    recent_context: str = "",
    current_turn: int = 0,
) -> List[Dict[str, Any]]:
    """召对动作 typed 判断：读皇帝本条消息 + ADR 0028 最近相关召对上下文，不读本轮大臣回话。

    输出契约（#515）：动作候选**列表**（单动作 = 长度 1；认不出/失败 = []）。
    枚举与 kind map 唯一真源 = ming_sim.action_clusters 登记表。
    这条调用可与大臣回话并发；跨轮指代（「这三件事你都办」）靠 recent_context /
    待确认动作解析前轮事项并逐事产候选。LLM 软判坏 shape → []。
    current_turn / GATE_TABLES 契约供交办承诺落到合法 end_turn 与 stop_condition。
    """
    from ming_sim.action_clusters import (
        candidates_from_classifier_payload,
        classifier_json_fields_prompt,
    )
    from ming_sim.constants import GATE_TABLES

    orders_brief = "；".join(
        f"#{o.get('id')}「{o.get('title', '')}」：{str(o.get('content', ''))[:50]}"
        for o in (active_orders or [])
    ) or "（无）"
    pending_brief = "；".join(pending_summaries or []) or "（无）"
    context_block = (recent_context or "").strip() or "（无）"
    # 字段/枚举唯一真源 = 登记表 FieldSpec（#515：禁手写字段副本）
    schema_obj = classifier_json_fields_prompt()
    turn_n = int(current_turn or 0)
    gate_tables = "/".join(GATE_TABLES)
    prompt = (
        "你是召对动作意图分类器，读皇帝本条消息与【最近相关召对】上下文，"
        "不读也不等待大臣本轮回话。"
        "判断本轮是否属于一个或多个政务动作，并抽出可从皇帝话与相关上下文直接确定的结构字段。"
        "单动作输出一个 JSON 对象，多动作输出 JSON 对象数组（无代码围栏、无多余字）：\n"
        + schema_obj + "\n"
        "规则：确认优先于新动作；拟旨优先于任免。\n"
        "跨轮指代（如「这三件事你都办」「三事全允」）须结合最近相关召对上下文与"
        "待确认动作列表解析所指事项，逐事各产一条候选；更新既有候选时填目标候选=该道 id。\n"
        "拿问、下狱、赐死、廷杖、罚俸、削籍、放归、昭雪属惩处，不得判任免罢免。\n"
        "问/令查分界（语义整体判断，禁字样启发）：\n"
        "- 纯问句→动作类型填无（零动作）。含「密查/查访」字样的疑问仍是问，"
        "如「陕西巡抚可有？」「可有人密查陕西军饷？」「着人查访军情如何？」→无。\n"
        "- 含命令词但整体为问（如「命东厂密查其家产的是谁」）→仍无，不得升格密令。\n"
        "- 祈使令查且指向【现有密令】的补充/续查→密令动作=更新（填目标密令编号）："
        "如已有「查其家产」时「再去查他在苏州的田产」→更新原令。\n"
        "- 祈使令查且为真正另案、或无相关现有密令→密令动作=新建："
        "如「你去查他家产」「着东厂密查其家产」。\n"
        "- 不得因出现密查/查访字样就判密令；整体为问则无；"
        "整体为令时按是否指向现有密令选更新或新建。\n"
        "- 更新/催办/提交核议/记进展仅针对【现有密令】；无现有密令时不要硬判这四者"
        "（新建不受此限）。非妃嫔不要硬判调教。\n"
        "交办·责成承诺契约：\n"
        f"- 当前回合={turn_n}。相对期限填期限月数=N（连续N月/三月内）；"
        f"或截止回合填绝对回合号（须 > 当前回合，公式=当前回合+N）。\n"
        f"- 停止条件须为可寻址 dict JSON，key 带表前缀（{gate_tables}），"
        'value 含比较算符，如 {"army.guanning.arrears":"<=0"}；'
        "自然语言军令状须落成该 shape，不得只写散文。\n\n"
        f"【最近相关召对】\n{context_block}\n"
        f"【待确认动作】{pending_brief}\n"
        f"【现有密令】{orders_brief}\n"
        f"【此人是否妃嫔】{'是' if is_consort else '否'}\n"
        f"【本回合是否已有拟旨草案】{'是' if has_pending_draft else '否'}\n"
        "【皇帝】" + (player_message or "（无）") + "\n"
    )
    raw = ""
    try:
        raw, _ = _run_backend_for_config(prompt, llm_config, tag="action_intent")
    except Exception as exc:
        _log(f"召对动作意图判断失败：{exc}")
        return []
    obj = _loads_lenient(raw, accepted_types=(dict, list))
    if obj is None:
        obj = {}
    # 列表契约：对象或 list 均走登记表 soft 归一；坏 shape / 无 → []。
    return candidates_from_classifier_payload(obj, soft=True)


# 对话式拟旨意图抽取（ADR 0006 自然语言路径）：玩家口头「拟旨吧/帮我拟一道旨」时，
# 无显式前缀（_DRAFT_PREFIXES）→ LLM 判出意图 → 进 pending_actions(kind=directive)暂存；
# 大臣回话即草案文本，commit 时再建 turn_directives 条目。
def _directive_mode(value: object) -> Optional[str]:
    """Normalize one mode value; authority precedence belongs to resolve_directive_mode.

    Emperor natural-language declarations count only when unambiguous:
    midzhi keeps prefix-shaped cues; ordinary also accepts full-sentence
    "按普通程序…" style declarations. Silent supplements ("再补一条") stay None
    so existing durable mode wins upstream.
    """
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if (
        normalized in {"中旨直发", "midzhi"}
        or normalized.startswith("中旨直发")
        or any(normalized.startswith(f"{prefix}中旨直发") for prefix in _DRAFT_PREFIXES)
    ):
        return "midzhi"
    if (
        normalized in {"普通", "ordinary"}
        or normalized.startswith("普通")
        or any(normalized.startswith(f"{prefix}普通") for prefix in _DRAFT_PREFIXES)
        or "普通程序" in normalized
    ):
        return "ordinary"
    return None


def resolve_directive_mode(
    emperor_text: object = None, extracted: object = None, existing: object = None,
) -> str:
    """Own mode authority: emperor declaration > existing > extraction > compatibility default."""
    for value in (emperor_text, existing, extracted, "ordinary"):
        mode = _directive_mode(value)
        if mode is not None:
            return mode
    return "ordinary"


def _draft_intent_character_roster_facts(content: Any) -> str:
    """#1428：把 content.characters 的 name+aliases 编成抽取接地事实块。

    接地=结构化事实注入（ADR 0142）；不在此做散文截断修复/子串归一。
    参与人 character_id 须填规范名；别名仅作识别线索，输出仍归规范名。
    资格与 _find_existing_minister / _is_ming_court_minister_character 同口径
    （ming ∧ 非后宫 ∧ 非 candidate）；无 db 时用 content 静态 power_id（#125 live 翻转不扩）。
    """
    characters = getattr(content, "characters", None) if content is not None else None
    if not characters:
        return ""
    from ming_sim.session import _is_ming_court_minister_character

    lines: List[str] = []
    for key, ch in characters.items():
        if not _is_ming_court_minister_character(ch):
            continue
        name = str(getattr(ch, "name", None) or key or "").strip()
        if not name:
            continue
        aliases = [
            str(a).strip()
            for a in (getattr(ch, "aliases", None) or [])
            if str(a).strip() and str(a).strip() != name
        ]
        if aliases:
            lines.append(f"{name}（别名：{'、'.join(aliases)}）")
        else:
            lines.append(name)
    if not lines:
        return ""
    return (
        "【在册人物规范名+别名】参与人 character_id 必须从此表规范名选取；"
        "见到别名须归一为对应规范名；不得截短、不得自造未列之名。\n"
        + "\n".join(lines)
        + "\n"
    )


# #1274 QA V-1：参与人校验失败有界纠错重试（owner 2026-08-20 三连拍板）。
# 宪法：查无此人不告诉皇帝、底下人偷偷划掉=篡改圣旨，绝对禁止。
# 自愈只许修 LLM 自己的抄写错（修完仍是皇帝说的那个人）；真不在册→戏内回禀。
# 1–2 次；happy path 零额外调用。只在「参与人物/委派人不存在」路上触发。
DRAFT_PARTICIPANT_HEAL_RETRIES = 2
_PARTICIPANT_REF_MISSING_RE = re.compile(
    r"(?:参与人物|委派人)不存在[：:]\s*([^。\n]+)"
)


def _normalize_unknown_participant_names(
    names: Optional[List[str]] = None,
) -> List[str]:
    cleaned: List[str] = []
    for raw in names or []:
        name = str(raw or "").strip()
        if name and name not in cleaned:
            cleaned.append(name)
    return cleaned


def unknown_participant_fact(names: Optional[List[str]] = None) -> str:
    """查无此人事实串唯一真源（escalate.fact 与 compose 共用）。"""
    cleaned = _normalize_unknown_participant_names(names)
    shown = "、".join(cleaned) if cleaned else "其人"
    return (
        f"朝中名册查无「{shown}」此人；"
        f"不得擅自将其从参与人中除去或另换他人；"
        f"须回禀陛下，乞陛下明示该如何处置。"
    )


class UnknownParticipantEscalate(Exception):
    """真不在册：自愈耗尽后须戏内回禀，禁除名照落 / 禁静默 409 术语怼玩家。"""

    def __init__(self, names: Optional[List[str]] = None):
        self.names = _normalize_unknown_participant_names(names)
        self.fact = unknown_participant_fact(self.names)
        super().__init__(self.fact)


def is_unknown_participant_ref_error(exc: BaseException) -> bool:
    """校验报「参与人物/委派人不存在」——可回喂 LLM 纠错的失败类。"""
    return bool(_PARTICIPANT_REF_MISSING_RE.search(str(exc) or ""))


def _invalid_participant_names_from_error(exc: BaseException) -> List[str]:
    names: List[str] = []
    for match in _PARTICIPANT_REF_MISSING_RE.finditer(str(exc) or ""):
        name = str(match.group(1) or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _person_ids_from_extract_result(result: Dict[str, Any]) -> List[str]:
    """单条/批抽结果中的人物键（character_id + delegator_id/delegator，保序去重）。

    除名闸 prior/new 同键空间：委派人与主办/协办同属人物参与侧，漏收会把
    「毕自」→「毕自严」的委派人自愈误判 removal_only，或丢合法委派人不触发
    lost_prior_valid。raw `delegator` 与 `delegator_id` 同收（与 normalize 接缝一致）。
    """
    ids: List[str] = []

    def _absorb(roster: Any) -> None:
        if not isinstance(roster, list):
            return
        for item in roster:
            if not isinstance(item, dict):
                continue
            for key in ("character_id", "delegator_id", "delegator"):
                cid = str(item.get(key) or "").strip()
                if cid and cid not in ids:
                    ids.append(cid)

    if "participant_roster" in result:
        _absorb(result.get("participant_roster"))
    for draft in result.get("drafts") or []:
        if isinstance(draft, dict) and "participant_roster" in draft:
            _absorb(draft.get("participant_roster"))
    return ids


_MIN_PERSON_PREFIX_LEN = 2


def _original_input_text(
    player_message: Optional[str], minister_reply: Optional[str],
) -> str:
    """自愈同人接地用的原始输入（皇帝话 + 大臣回话/旨文），非抽取器输出。"""
    parts: List[str] = []
    for raw in (player_message, minister_reply):
        text = str(raw or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


def _roster_identity_forms(canon: str, *, content: Any) -> List[str]:
    """名册事实：规范名 + aliases（与 #1428 事实块同源，机械列表）。"""
    forms: List[str] = []
    name = str(canon or "").strip()
    if name:
        forms.append(name)
    ch = None
    if content is not None:
        chars = getattr(content, "characters", None) or {}
        ch = chars.get(name)
    for raw in getattr(ch, "aliases", None) or []:
        alias = str(raw or "").strip()
        if alias and alias not in forms:
            forms.append(alias)
    return forms


def _all_roster_identity_forms(*, content: Any) -> Dict[str, List[str]]:
    """canon → 规范名+别名列表；供截断前缀唯一性判定。"""
    out: Dict[str, List[str]] = {}
    chars = getattr(content, "characters", None) or {} if content is not None else {}
    for key, ch in chars.items():
        canon = str(key or "").strip()
        if not canon:
            continue
        forms = [canon]
        for raw in getattr(ch, "aliases", None) or []:
            alias = str(raw or "").strip()
            if alias and alias not in forms:
                forms.append(alias)
        out[canon] = forms
    return out


def _person_grounded_in_source(
    person_id: str,
    source_text: str,
    *,
    db: Any,
    content: Any,
    roster_forms: Optional[Dict[str, List[str]]] = None,
) -> bool:
    """窄确定性同人接地：原文出现该人规范名/别名，或可截断前缀且唯一落此人。

    禁散文关键词/第二套抽取语义；只做名册事实上的子串与前缀机械判定。
    """
    text = str(source_text or "")
    if not text:
        return False
    canon = _canon_person_id_key(person_id, db=db, content=content)
    if not canon:
        return False
    forms_index = roster_forms if roster_forms is not None else _all_roster_identity_forms(
        content=content,
    )
    my_forms = forms_index.get(canon) or _roster_identity_forms(canon, content=content)
    for form in my_forms:
        if form and form in text:
            return True
    # 可截断前缀：form 的真前缀（长≥2）出现在原文，且全名册仅此人的 form 命中该前缀
    for form in my_forms:
        if len(form) <= _MIN_PERSON_PREFIX_LEN:
            continue
        for n in range(_MIN_PERSON_PREFIX_LEN, len(form)):
            prefix = form[:n]
            if prefix not in text:
                continue
            owners: set[str] = set()
            for other_canon, other_forms in forms_index.items():
                for other in other_forms:
                    if other == prefix or other.startswith(prefix):
                        owners.add(other_canon)
                        break
            if owners == {canon}:
                return True
    return False


def _replacements_grounded_in_source(
    replacements: List[str],
    *,
    player_message: Optional[str],
    minister_reply: Optional[str],
    db: Any,
    content: Any,
) -> bool:
    """纠错轮每个新参与人须能在原始输入+名册事实上唯一接地；否则 False。"""
    if not replacements:
        return True
    source = _original_input_text(player_message, minister_reply)
    forms_index = _all_roster_identity_forms(content=content)
    for person_id in replacements:
        if not _person_grounded_in_source(
            person_id, source, db=db, content=content, roster_forms=forms_index,
        ):
            return False
    return True


def _backfill_healed_participant_refs(
    baseline: Dict[str, Any],
    healed: Dict[str, Any],
) -> Dict[str, Any]:
    """首抽权威快照：只回填纠错后的参与人引用；其余字段一律保首抽。"""
    out = dict(baseline)
    if "participant_roster" in healed:
        out["participant_roster"] = healed.get("participant_roster")
    base_drafts = baseline.get("drafts")
    healed_drafts = healed.get("drafts")
    if isinstance(base_drafts, list) and isinstance(healed_drafts, list):
        merged: List[Any] = []
        for idx, base_draft in enumerate(base_drafts):
            if not isinstance(base_draft, dict):
                merged.append(base_draft)
                continue
            item = dict(base_draft)
            if idx < len(healed_drafts) and isinstance(healed_drafts[idx], dict):
                h_item = healed_drafts[idx]
                if "participant_roster" in h_item:
                    item["participant_roster"] = h_item.get("participant_roster")
            merged.append(item)
        out["drafts"] = merged
    return out


def build_participant_correction_feedback(
    exc: BaseException, *, roster_facts: str = "",
) -> str:
    """正向纠错指令（P7）：无效名 + 名册事实；只许改正抄写，禁除名/另换。"""
    names = _invalid_participant_names_from_error(exc)
    name_part = "、".join(names) if names else "（见校验）"
    block = (
        f"【纠错】名册无此人：{name_part}。"
        f"请改正为名册中陛下所指之人的正确规范名（须仍是同一人）；"
        f"不得擅自除去或另换他人。\n"
    )
    facts = str(roster_facts or "").strip()
    if facts:
        block += facts if facts.endswith("\n") else facts + "\n"
    return block


def compose_unknown_participant_inworld_report(
    names: Optional[List[str]] = None,
    *,
    voice: str = "tongzheng",
    speaker_name: str = "",
    llm_config: Any = None,
    timeout_s: float | None = None,
) -> str:
    """P7：把查无此人事实喂给 LLM，产大臣/通政司口吻回禀；禁模板当台词。

    timeout_s：有界等待（capture 剩余预算）；None=不另加罩。
    剩余预算≤0、超时或产文失败 → typed LLMUnavailable（#1299/#1310/#1452
    失败单源 CLI_RUNNER_PLAYER_MESSAGE），玩家重下这道点名。
    """
    from ming_sim.exceptions import LLMUnavailable
    from ming_sim.llm_model import cli_runner_unavailable

    cleaned = _normalize_unknown_participant_names(names)
    if voice == "minister" and str(speaker_name or "").strip():
        role = f"大臣{str(speaker_name).strip()}"
    else:
        role = "通政使司官"
    fact = unknown_participant_fact(cleaned)
    prompt = (
        f"你是{role}。根据下列事实，以本职口吻向皇帝回禀（一两句即可）。"
        f"只输出回禀正文，不要标题、不要系统术语、不要 JSON。\n"
        f"事实：{fact}\n"
    )
    if timeout_s is not None and float(timeout_s) <= 0:
        raise cli_runner_unavailable(
            TimeoutError("查无此人回禀无剩余预算"),
            backend="participant_escalate_report",
        )

    def _produce() -> str:
        raw, _ = _run_backend_for_config(
            prompt, llm_config, tag="participant_escalate_report",
        )
        text = str(raw or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
            text = text.strip()
        # 抽取器 JSON / 空响 → 失败；只要非结构化戏内文。
        if text and not text.lstrip().startswith("{"):
            return text
        raise cli_runner_unavailable(
            RuntimeError("查无此人回禀空响或非戏内文"),
            backend="participant_escalate_report",
        )

    try:
        if timeout_s is None:
            return _produce()
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            fut = pool.submit(_produce)
            return fut.result(timeout=float(timeout_s))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    except LLMUnavailable:
        raise
    except Exception as exc:
        _log(f"查无此人回禀产文失败：{exc}")
        raise cli_runner_unavailable(
            exc, backend="participant_escalate_report",
        ) from exc


def _canon_person_id_key(raw: Any, *, db: Any, content: Any) -> Optional[str]:
    """单 id：非人滤除 + _canonical_minister_key → 熟键；与 roster 归一同口径。"""
    from ming_sim.session import _canonical_minister_key

    cid = str(raw or "").strip()
    if not cid or _is_non_person_participant_name(cid):
        return None
    canon = str(_canonical_minister_key(content, cid, db) or "").strip()
    return canon or None


def _canon_person_id_keys(
    ids: Any, *, db: Any, content: Any,
) -> List[str]:
    """生 character_id 列表 → 熟键（非人滤 + canon），保序去重。

    除名闸 prior 侧与 validated 必须同走此接缝，禁平行第三套 id 语义。
    """
    out: List[str] = []
    for raw in ids or []:
        canon = _canon_person_id_key(raw, db=db, content=content)
        if canon and canon not in out:
            out.append(canon)
    return out


def normalize_draft_person_roster(
    roster: Any, *, db: Any, content: Any,
) -> List[Dict[str, object]]:
    """人物参与人：normalize → 非人滤除 → canon → ADR 0053 校验。

    capture 与召对 materialize 共用；校验失败 raise ValueError（参与人物不存在…）。
    """
    if not isinstance(roster, list):
        raise ValueError("参与人须为对象列表")

    canonical_roster = db._normalize_participant_roster(
        roster, strict_structured=True,
    )
    person_roster: List[Dict[str, object]] = []
    for item in canonical_roster:
        entry = dict(item)
        cid = _canon_person_id_key(entry.get("character_id"), db=db, content=content)
        if not cid:
            continue
        entry["character_id"] = cid
        delegator_raw = str(entry.get("delegator_id") or "").strip()
        if delegator_raw:
            delegator = _canon_person_id_key(
                delegator_raw, db=db, content=content,
            )
            entry["delegator_id"] = delegator  # None if 非人
        person_roster.append(entry)
    db._validate_participant_roster_references(person_roster)
    return person_roster


def _apply_validated_roster_to_extract_result(
    result: Dict[str, Any], *, db: Any, content: Any,
) -> Dict[str, Any]:
    """对单条/批抽结果的 participant_roster 做 normalize+validate（就地拷贝）。"""
    out = dict(result)
    if "participant_roster" in out and out.get("participant_roster") is not None:
        out["participant_roster"] = normalize_draft_person_roster(
            out.get("participant_roster"), db=db, content=content,
        )
    drafts = out.get("drafts")
    if isinstance(drafts, list):
        healed_drafts: List[Any] = []
        for draft in drafts:
            if not isinstance(draft, dict):
                healed_drafts.append(draft)
                continue
            item = dict(draft)
            if "participant_roster" in item and item.get("participant_roster") is not None:
                item["participant_roster"] = normalize_draft_person_roster(
                    item.get("participant_roster"), db=db, content=content,
                )
            healed_drafts.append(item)
        out["drafts"] = healed_drafts
    return out


def extract_draft_intent_with_roster_heal(
    player_message: Optional[str],
    minister_reply: str,
    llm_config: Any = None,
    *,
    db: Any = None,
    content: Any = None,
    heal_retries: int = DRAFT_PARTICIPANT_HEAL_RETRIES,
    **extract_kwargs: Any,
) -> Dict[str, Any]:
    """extract → 名册校验；「参与人物不存在」时有界纠错重抽（P5 只走失败路）。

    自愈只许抄写纠错（修完仍是皇帝所指之人）。真不在册 / 擅自除名 →
    raise UnknownParticipantEscalate（调用方戏内回禀，不落草案）。
    db/content 缺一则只抽不校验（与旧 extract 同）。LLM 在纠错路上挂死 → 原样上抛。
    """
    retries = max(0, int(heal_retries))
    correction = ""
    pending_unknown: List[str] = []
    prior_ids_at_fail: List[str] = []
    # 首抽权威快照：首次校验失败后冻结，后续失败不得覆写 baseline/闸基线。
    baseline_result: Optional[Dict[str, Any]] = None
    for attempt in range(retries + 1):
        # llm_config 关键字传：别族 fake_draft(msg, reply, **kw) 形仍合法，
        # 不得因 heal 多塞第 3 位置参把旧 mock 签名整族打爆。
        result = extract_draft_intent(
            player_message,
            minister_reply,
            llm_config=llm_config,
            content=content,
            correction_feedback=correction,
            **extract_kwargs,
        )
        if db is None or content is None:
            return result
        has_roster_field = (
            ("participant_roster" in result and result.get("participant_roster") is not None)
            or any(
                isinstance(d, dict) and "participant_roster" in d
                for d in (result.get("drafts") or [])
            )
        )
        if not has_roster_field:
            # 纠错路上抽掉参与人字段 = 除名企图 → 篡改，回禀
            if pending_unknown:
                raise UnknownParticipantEscalate(pending_unknown)
            return result
        try:
            validated = _apply_validated_roster_to_extract_result(
                result, db=db, content=content,
            )
        except ValueError as exc:
            if not is_unknown_participant_ref_error(exc):
                raise
            # 仅首败冻结基线；重试失败不得洗掉首抽合法参与人/未知名。
            if baseline_result is None:
                pending_unknown = _invalid_participant_names_from_error(exc)
                prior_ids_at_fail = _person_ids_from_extract_result(result)
                baseline_result = dict(result)
            if attempt >= retries:
                raise UnknownParticipantEscalate(pending_unknown) from exc
            roster_facts = _draft_intent_character_roster_facts(content)
            correction = build_participant_correction_feedback(
                exc, roster_facts=roster_facts,
            )
            _log(
                f"拟旨参与人纠错重试 {attempt + 1}/{retries}: {exc}"
            )
            continue
        # 校验过了：若本轮曾因查无而纠错，禁「只删不改」；
        # 亦禁有替换时顺手抹掉本轮已在册的合法参与人。
        # prior 侧须过与 validated 同一条归一后再比（别名→规范名），
        # 禁生/熟键空间错位误杀自愈。
        # 替换须原始输入+名册事实窄确定性同人接地；接不上唯一同人 → escalate。
        if pending_unknown:
            new_ids = _person_ids_from_extract_result(validated)
            prior_raw = [
                i for i in prior_ids_at_fail if i not in pending_unknown
            ]
            prior_valid = _canon_person_id_keys(
                prior_raw, db=db, content=content,
            )
            replacements = [i for i in new_ids if i not in prior_valid]
            lost_prior_valid = not set(prior_valid) <= set(new_ids)
            removal_only = (
                not replacements and set(new_ids) <= set(prior_valid)
            )
            if lost_prior_valid or removal_only:
                raise UnknownParticipantEscalate(pending_unknown)
            if not _replacements_grounded_in_source(
                replacements,
                player_message=player_message,
                minister_reply=minister_reply,
                db=db,
                content=content,
            ):
                raise UnknownParticipantEscalate(pending_unknown)
            # 纠错只回填参与人引用；amount/target/mode/正文等保首抽。
            assert baseline_result is not None
            return _backfill_healed_participant_refs(baseline_result, validated)
        return validated


def extract_draft_intent(
    player_message: Optional[str],
    minister_reply: str,
    llm_config: Any = None,
    has_pending_draft: bool = False,
    existing_draft_text: str = "",
    existing_candidates: Optional[List[Dict[str, Any]]] = None,
    draft_count: int = 1,
    content: Any = None,
    correction_feedback: str = "",
) -> Dict[str, Any]:
    """LLM 判皇帝本轮是否在口头请大臣拟旨（非显式前缀），返回拟旨意图 + 草案文本 + 目标候选。
    失败/无 → {"draft_action": "无", "draft_text": "", "target_candidate": ""}。
    has_pending_draft=True：本回合已有草案暂存，皇帝「补充/修改当前草稿」也归拟旨。
    existing_draft_text 非空时（补充模式）：LLM 输出合并草案，payload 存合并后全文；
    不能用大臣确认回话（「好的，加上…」）覆盖原草案。

    existing_candidates 非空（多道模式，#502）：本夜已有若干独立圣旨候选，LLM 除判拟旨意图/
    合并草案外，还判本轮**新拟独立一道**（target_candidate="新"）还是**补充/修改某一道**
    （target_candidate=该道 id）。指称不明时按候选条数兜底：单条→补那条（沿用 last-write-wins），
    多条→target_candidate="含糊"（交 session 追问哪一道，不静默新建第三道；#502 L7）。
    无候选时 target_candidate 恒空。

    content（#1428）：可选 GameContent；提供时把 characters 的 name+aliases 作结构化
    事实注入抽取 prompt，接地参与人规范名（禁散文守门族）。

    correction_feedback（#1274 V-1）：校验失败回喂的纠错指令；非空时 LLM 挂死响亮上抛。"""
    roster_facts = _draft_intent_character_roster_facts(content)
    correction_block = str(correction_feedback or "").strip()
    if correction_block and not correction_block.endswith("\n"):
        correction_block += "\n"
    if draft_count > 1:
        prompt = (
            "你是信息抽取器，不扮演。皇帝同一句要求拟多道彼此独立的圣旨，大臣已在一段回话中"
            f"拟了内容。请从完整语义中整理出恰好 {draft_count} 道彼此可区分、可独立暂存的成品旨稿。"
            "只输出一个 JSON 对象（无代码围栏、无多余字）：\n"
            '{"成品旨稿": ['
            '{"正文":"第一道完整旨稿","动作类型":"policy","目标类型":"issue","目标ID":"...",'
            '"颁布方式":"普通|中旨直发"},'
            f'{{"正文":"……共 {draft_count} 道","动作类型":"military_order","目标类型":"army",'
            '"目标ID":"...","金额":null,"账户":"","执行面":"immediate|in_transit",'
            '"承办人":"...","期限月数":3,"颁布方式":"普通|中旨直发",'
            '"参与人":[{"character_id":"规范名","tier":"主办|协办|知情","role":"本案职分","delegator_id":null}]}]}\n'
            "不得把同一段文字复制成多道；不得遗漏皇帝要求的任一道拟旨事项。\n\n"
            + correction_block
            + roster_facts
            + "【皇帝】" + (player_message or "（无）") + "\n"
            + "【大臣完整回话】" + (minister_reply or "（无）") + "\n"
        )
        raw = ""
        try:
            raw, _ = _run_backend_for_config(prompt, llm_config, tag="draft_intent")
        except Exception as exc:
            # 纠错重试路上 LLM 挂死响亮上抛（owner：该报）；首抽仍吞掉以免挡对话。
            if correction_block:
                raise
            _log(f"多旨稿抽取失败：{exc}")
        obj = _loads_lenient(raw) or {}
        values = obj.get("成品旨稿") if isinstance(obj, dict) else None
        drafts = []
        seen_texts = set()
        invalid_batch = not isinstance(values, list) or len(values) != draft_count
        for value in values if isinstance(values, list) else []:
            if not isinstance(value, dict):
                invalid_batch = True
                break
            text = str(value.get("正文") or "").strip()
            action = str(value.get("动作类型") or "").strip()
            mode = _directive_mode(value.get("颁布方式"))
            target_kind = str(value.get("目标类型") or "").strip()
            target_id = str(value.get("目标ID") or "").strip()
            if not text or not action or not target_kind or not target_id or mode is None or text in seen_texts:
                invalid_batch = True
                break
            seen_texts.add(text)
            if action == "acting_appointment":
                # #529 署理走既有 pending 人事候选路径应答（0064 任别），不经草案 acting_appointment。
                # 保留原批次位置，避免后续按候选序号消费时错配 sibling。
                drafts.append(None)
                continue
            if action not in DRAFT_ACTION_TYPES:
                invalid_batch = True
                break
            mechanical = {
                target: value.get(source)
                for source, target in (
                    ("金额", "amount"), ("账户", "account"),
                    ("执行面", "execution_surface"), ("承办人", "assignee"),
                    ("期限月数", "deadline_months"),
                )
            }
            drafts.append({
                "draft_action": "拟旨", "draft_text": text,
                "dossier_action_type": action, "target_kind": target_kind,
                "target_id": target_id, "target_candidate": "",
                "mode": mode,
                "participant_roster": value["参与人"] if "参与人" in value else [], **mechanical,
            })
        if invalid_batch or not any(draft is not None for draft in drafts):
            drafts = []
        return {
            "draft_action": "拟旨" if drafts else "无",
            "draft_text": "",
            "drafts": drafts,
            "target_candidate": "",
        }

    _candidates = [c for c in (existing_candidates or []) if c]
    _by_id = {int(c["id"]): c for c in _candidates}
    supplement_hint = (
        "本回合已有草案暂存；如果皇帝是在补充/修改/扩充当前草稿"
        "（如「再补一条」「加上」「改成」「把…去掉」等），也归拟旨。\n"
        if (has_pending_draft or _candidates) else ""
    )
    # 补充模式（has_pending_draft + existing_draft_text）：注入现有草案，要求 LLM 输出合并草案。
    # 直接用大臣回话（可能是「好的，加上…」等确认语）会覆盖原草案——须由 LLM 合并。
    _existing_draft_text = (
        "" if existing_draft_text is None else str(existing_draft_text)
    ).strip()
    _supplement_mode = (has_pending_draft or bool(_candidates)) and (
        bool(_existing_draft_text) or bool(_candidates))
    intent_schema_line = (
        '  "拟旨意图": "无|拟旨",\n'
        '  "动作类型": "policy|approve_reject|assignment|'
        'grant_allocation|authorization|secret_authorization|secret_investigation|'
        'protection|strategy_selection|punishment|pacification|referral|'
        'revoke_decree|revoke_authority|dismiss_assignment|military_order",\n'
        '  "目标类型": "policy|character|office|army|region|issue|account",\n'
        '  "目标ID": "",\n'
        '  "颁布方式": "普通|中旨直发", // 皇帝预先声明中旨直发时选后者\n'
        '  "金额": null,             // 奉旨拨付额填正整数；非拨帑留 null\n'
        '  "账户": "",\n'
        '  "执行面": "immediate|in_transit", // 仅拨帑：账内即时划转或在途执行\n'
        '  "承办人": "",\n'
        '  "参与人": [{"character_id":"规范名","tier":"主办|协办|知情","role":"本案职分","delegator_id":null}],\n'
        '  "期限月数": null' + (
            "," if (_candidates or _supplement_mode) else ""
        ) + '           // 军令必填正整数；非军令留 null\n'
    )
    # 多道模式：加「目标草案」判新拟 vs 补某道 + 现有候选清单（供 LLM 指认）。
    target_schema_line = (
        '  "目标草案": "新"' + (
            "," if _supplement_mode else ""
        ) + '       // 明确另拟独立一道=「新」；补充/修改现有某一道=填该道方括号编号；'
        '想改/补但没指明是哪道=「含糊」\n'
        if _candidates else ""
    )
    merge_schema_line = (
        '  "合并草案": ""   // 仅拟旨时必填：把现有草案与本轮新增/修改指令合并成完整草案；无拟旨意图时留空\n'
        if _supplement_mode else ""
    )
    draft_context = (
        f"【现有草案】{_existing_draft_text}\n"
        if _existing_draft_text else ""
    )
    candidates_context = (
        "【现有候选】\n" + "\n".join(
            f"  [{int(c['id'])}] {str(c.get('summary') or c.get('text') or '')[:40]}"
            for c in _candidates
        ) + "\n"
        if _candidates else ""
    )
    prompt = (
        "你是信息抽取器，不扮演、不写圣旨。读皇帝这句话 + 大臣回话，判断皇帝**本轮**"
        "是否在口头请大臣拟旨（如「拟旨吧」「你拟一道旨」「帮我起草」「草拟圣旨」等）。"
        + supplement_hint
        + "只输出一个 JSON 对象（无代码围栏、无多余字）：\n"
        "{\n"
        + intent_schema_line
        + target_schema_line
        + merge_schema_line
        + "}\n"
        "判定要点：皇帝明确让大臣拟旨/起草圣旨→拟旨；仅商议/问询/催办/评论不算。语义判断，别拘字面。\n\n"
        + correction_block
        + roster_facts
        + draft_context
        + candidates_context
        + "【皇帝】" + (player_message or "（无）") + "\n"
        + "【大臣回话】" + (minister_reply or "（无）") + "\n"
    )
    raw = ""
    try:
        raw, _ = _run_backend_for_config(prompt, llm_config, tag="draft_intent")
    except Exception as exc:
        if correction_block:
            raise
        _log(f"拟旨意图抽取失败：{exc}")
    obj = _loads_lenient(raw) or {}
    if not isinstance(obj, dict):
        obj = {}
    _raw = str(obj.get("拟旨意图") or "无").strip()
    _action = _raw if _raw in {"无", "拟旨"} else "无"
    dossier_action = str(obj.get("动作类型") or "special_decree").strip()
    if dossier_action not in DRAFT_ACTION_TYPES:
        dossier_action = "special_decree"
    target_kind = str(obj.get("目标类型") or "policy").strip()
    if target_kind not in {"policy", "character", "office", "army", "region", "issue", "account"}:
        target_kind = "policy"
    target_id_value = str(obj.get("目标ID") or "").strip()
    mechanical = {
        "amount": obj.get("金额"), "account": obj.get("账户"),
        "execution_surface": obj.get("执行面"),
        "assignee": obj.get("承办人"),
        "deadline_months": obj.get("期限月数"),
    }
    mode = _directive_mode(obj.get("颁布方式"))
    if mode is not None:
        mechanical["mode"] = mode
    merged = str(obj.get("合并草案") or "").strip()
    if _action == "无":
        return {"draft_action": "无", "draft_text": "", "target_candidate": ""}
    if not _candidates:
        # 无候选：沿用单条语义——补充模式合并、否则大臣回话即草案。
        if _supplement_mode:
            draft_text = merged if merged else _existing_draft_text
        else:
            draft_text = (minister_reply or "").strip()
        return {"draft_action": _action, "draft_text": draft_text, "target_candidate": "",
                "dossier_action_type": dossier_action,
                "target_kind": target_kind, "target_id": target_id_value,
                "participant_roster": obj["参与人"] if "参与人" in obj else [], **mechanical}
    # 多道：归一目标——命中候选 id=补那道；「新」=明确另拟；否则含糊兜底（#502 L7）：
    # 单条→补那条（沿用 last-write-wins），**多条不静默新建第三道**→「含糊」交 session 追问哪一道。
    target_raw = str(obj.get("目标草案") or "").strip()
    target_id: Optional[int] = None
    if target_raw and target_raw != "新":
        digits = "".join(ch for ch in target_raw if ch.isdigit())
        if digits and int(digits) in _by_id:
            target_id = int(digits)
    if target_raw == "新":
        target = "新"
    elif target_id is not None:
        target = str(target_id)
    elif len(_by_id) == 1:
        target = str(next(iter(_by_id)))
    else:
        target = "含糊"
    if target == "含糊":
        # 多道并存、改/补目标不明：不落草案，交 session 走结构化含糊追问（对齐 AC5）。
        return {"draft_action": _action, "draft_text": "", "target_candidate": "含糊"}
    if target == "新":
        draft_text = merged if merged else (minister_reply or "").strip()
    else:
        existing = str(_by_id[int(target)].get("text") or "")
        # 补某道：优先合并全文；LLM 未合并时保留原文（避免用确认语覆盖），原文亦空则退回话。
        draft_text = merged if merged else (existing if existing else (minister_reply or "").strip())
    return {
        "draft_action": _action, "draft_text": draft_text, "target_candidate": target,
        "dossier_action_type": dossier_action,
        "target_kind": target_kind, "target_id": target_id_value,
        "participant_roster": obj["参与人"] if "参与人" in obj else [], **mechanical,
    }


# 手工拟诏 capture 总罩（#1327 / #1274 V-1 owner 2026-08-20）：
# 30s 罩住整段 extract+自愈重试；到点仅 special_decree 原文照落（零改参与人=不算篡改）。
MANUAL_DIRECTIVE_CAPTURE_TIMEOUT_S = 30.0


def _manual_special_decree_payload(mode: str) -> Dict[str, object]:
    return {
        "dossier_action_type": "special_decree",
        "target_kind": "policy",
        "target_id": "manual-directive",
        "mode": mode,
    }


def capture_manual_directive_payload(
    text: str, llm_config: Any = None, *, existing_mode: object = None,
    db: Any = None, content: Any = None,
    capture_timeout_s: float | None = None,
) -> Dict[str, object]:
    """Web/CLI 手工下旨共用既有草稿抽取 seam；在写入边界归一人物引用。

    #1327 / #1274 V-1：空载零 LLM 直落 special_decree；非空载 LLM 有界等待（默认 30s
    总罩，自愈重试计入罩内）。超时/挂死 → special_decree 原文照落（不改参与人）。
    真不在册耗尽 → 通政司戏内回禀 ValueError（不落草案、不除名）；
    回禀产文超时/失败 → typed LLMUnavailable（禁固定戏内模板当台词）。
    """
    directive_text = str(text or "").strip()
    fallback_mode = resolve_directive_mode(text, None, existing_mode)
    # 空载短路：无正文可抽 → 直落草案结构，零 LLM 调用（P5：禁为省写把可短路 LLM 串回）。
    if not directive_text:
        return _manual_special_decree_payload(fallback_mode)

    timeout_s = (
        MANUAL_DIRECTIVE_CAPTURE_TIMEOUT_S
        if capture_timeout_s is None
        else float(capture_timeout_s)
    )
    prompt = (
        f"请据此拟旨，并从以下已成旨文抽取结构，不得改写：\n{directive_text}"
    )

    def _run_extract() -> Dict[str, Any]:
        # #1274 V-1：extract→validate 有界纠错；db/content 齐时参与人名册自愈。
        return extract_draft_intent_with_roster_heal(
            prompt, directive_text, llm_config=llm_config,
            db=db, content=content,
        )

    # 有界等待：超时不堵死 HTTP/CLI；后台线程不 join（shutdown wait=False）。
    # 总罩含自愈 + escalate 回禀；回禀只拿剩余预算，超时/失败 → LLMUnavailable。
    captured: Dict[str, Any]
    t0 = time.monotonic()
    try:
        if timeout_s <= 0:
            captured = _run_extract()
        else:
            pool = ThreadPoolExecutor(max_workers=1)
            try:
                fut = pool.submit(_run_extract)
                captured = fut.result(timeout=timeout_s)
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
    except UnknownParticipantEscalate as exc:
        # 真不在册：通政司戏内回禀；禁吞 special_decree、禁除名照落。
        remaining: float | None = None
        if timeout_s > 0:
            remaining = max(0.0, float(timeout_s) - (time.monotonic() - t0))
        report = compose_unknown_participant_inworld_report(
            exc.names,
            voice="tongzheng",
            llm_config=llm_config,
            timeout_s=remaining,
        )
        raise ValueError(report) from exc
    except ValueError:
        # 其它业务 ValueError 原样上抛；禁吞成 special_decree。
        raise
    except Exception as exc:
        # 超时 / 纠错路上 LLM 挂死 → special_decree 原文照落（零改参与人）。
        _log(f"手工拟诏 capture 有界降级 special_decree：{exc}")
        return _manual_special_decree_payload(fallback_mode)

    declared_mode = resolve_directive_mode(text, captured.get("mode"), existing_mode)
    if captured.get("draft_action") != "拟旨":
        return _manual_special_decree_payload(declared_mode)
    payload = {
        "dossier_action_type": captured.get("dossier_action_type"),
        "target_kind": captured.get("target_kind"),
        "target_id": captured.get("target_id"),
        "mode": declared_mode,
    }
    for field in (
        "amount", "account", "execution_surface", "assignee",
        "deadline_months", "participant_roster",
    ):
        if captured.get(field) not in (None, ""):
            payload[field] = captured[field]
    # heal 已 normalize+validate；无 db/content 时保持抽取原样（旧调用兼容）。
    if payload.get("dossier_action_type") == "dismiss_assignment":
        # Manual CLI/Web directives bypass pending office actions, so preserve
        # the same structured materialization fields at this capture seam.
        payload["name"] = str(payload.get("target_id") or "").strip()
        payload["_office_action"] = "罢免"
    if not all(str(payload.get(key) or "").strip() for key in (
        "dossier_action_type", "target_kind", "target_id",
    )):
        return _manual_special_decree_payload(declared_mode)
    return payload


# 任免(office)会话动作抽取：与密令【完全独立】——任免和密令无关，故另起一函数，
# 不并进 extract_minister_actions、不挂密令那个 active gate。随召对触发（任何召对都
# 可能口头派官/罢官，含跟太监说），ungated；过判由「应允才落、拒绝就丢」兜底。
def extract_appointment_action(
    player_message: str,
    minister_reply: str,
    llm_config: Any = None,
) -> Dict[str, Any]:
    """LLM 判皇帝本轮口头是否在任免某人（任命/罢免），返回结构化动作。失败/无 → 「无」。
    只判自然语言；显式「拟旨如下：」里的任免走 extractor 的 office_changes，不在此。"""
    prompt = (
        "你是信息抽取器，不扮演、不写圣旨。读皇帝这句话 + 被召对者回话，判断皇帝**本轮**"
        "是否在口头任免某人（授官/升迁/调任=任命；革职/罢黜=罢免）。"
        "拿问、下狱、赐死、廷杖、罚俸、削籍、放归、昭雪属惩处，不是任免，任免动作填「无」。"
        "只输出一个 JSON 对象（无代码围栏、无多余字）：\n"
        "{\n"
        '  "任免动作": "无|任命|罢免",  // 皇帝命某人任/升/调某官=任命；命革/罢/黜某人=罢免；都不是=无\n'
        '  "姓名": "",                 // 被任/被免者确切姓名\n'
        '  "官职": "",                 // 任命时所授官职；罢免可空\n'
        '  "颁布方式": "普通|中旨直发", // 皇帝明确预声明中旨/特旨钦命时选后者\n'
        '  "任别": ""                  // 署理/兼署/加衔/真除；路径应答「署理」填署理；非任别留空\n'
        "}\n"
        "判定要点：皇帝口语如「着X任/授X为/升X/调X去/革X职/罢X」即任免；"
        "对已拟任免的路径应答「特旨钦命」→任免动作可无、颁布方式=中旨直发；"
        "「署理」→任免动作可无、任别=署理。闲谈、议事、下密令、拟旨、惩处都不算。"
        "语义判断，别拘字面。无任免且无路径应答 → 任免动作填「无」、其余留空。\n\n"
        "【皇帝】" + (player_message or "（无）") + "\n"
        "【回话】" + (minister_reply or "（无）") + "\n"
    )
    raw = ""
    try:
        raw, _ = _run_backend_for_config(prompt, llm_config, tag="appointment")
    except Exception as exc:  # 抽取失败不阻断对话
        _log(f"任免动作抽取失败：{exc}")
    obj = _loads_lenient(raw) or {}
    # 动作归一到固定枚举：枚举外的串 → 「无」，防按未知动作误操作（同密令抽取 CMR F10）。
    # 不收「顶替」字段：顶替/去职由落地核 _displace_duplicate_offices 按 office 文字自动去重处理，
    # 与 extractor 的 office_changes 同一机制（CMR R3：收而不用=capture-but-ignore 不一致）。
    _raw_action = str(obj.get("任免动作") or "无").strip()
    _action = _raw_action if _raw_action in {"无", "任命", "罢免"} else "无"
    result = {
        "appoint_action": _action,
        "name": str(obj.get("姓名") or "").strip()[:20],
        "office": str(obj.get("官职") or "").strip()[:40],
    }
    mode = _directive_mode(obj.get("颁布方式"))
    if mode is not None:
        result["mode"] = mode
    tenure = str(obj.get("任别") or "").strip()
    if tenure in {"真除", "署理", "兼署", "加衔"}:
        result["appointment_tenure"] = tenure
    return result


def extract_confirmation_intent(
    player_message: str,
    minister_reply: str,
    pending_summaries: List[str],
    llm_config: Any = None,
) -> str:
    """皇帝本轮对【上一轮经大臣领命确认、尚未落库的暂存动作】是应允/拒绝/留中/未表态。
    对话确认(ADR 0006 重设计)：应允 → 当场 commit，拒绝 → 丢，留中 → held_over 档，无 → 留。
    失败/无 → 「无」。#525：留中为第三态，豁免默认准，不成案。"""
    compact = re.sub(r"[\s，,。.!！?？；;：:、]+", "", player_message or "")
    if compact:
        reject_hit = any(
            token in compact
            for token in (
                "不准", "不允", "不许", "拒绝", "作罢", "罢了", "不必", "撤了", "撤回", "再议", "算了",
                "不照办", "不可照办", "勿照办", "毋照办", "不要照办",
            )
        )
        approval_stems = ("准奏", "照准", "准了", "照办", "依卿", "如此")
        negated_approval_hit = any(
            token in compact
            for token in (
                "不便如此", "不可如此", "不要如此",
                "不必如此", "不用如此", "无须如此",
            )
        ) or any(
            f"{negator}{stem}" in compact
            for negator in (
                "不", "不可", "不要", "勿", "毋", "别", "莫",
                "不必", "不用", "无须", "不能", "不得", "无法", "难以", "暂缓",
            )
            for stem in approval_stems
        )
        approve_hit = (
            compact in {"准", "可", "允", "好", "行", "善"}
            or any(token in compact for token in ("准奏", "照准", "准了", "照办", "依卿", "便如此", "就这么办"))
        ) and not negated_approval_hit
        approval_needs_semantic_check = approve_hit and any(
            token in compact
            for token in (
                "若", "如果", "倘若", "假若",
                "如何", "怎样", "怎么", "吗", "么",
                "是否", "可否", "能否", "可不可以", "能不能", "要不要",
            )
        )
        if (reject_hit or negated_approval_hit) and not approve_hit:
            return "拒绝"
        if approve_hit and not reject_hit and not approval_needs_semantic_check:
            return "应允"
    summ = "；".join(pending_summaries) or "（无）"
    prompt = (
        "你是信息抽取器，不扮演。皇帝上一轮经大臣领命确认后，有几条【尚未落库的暂存政务动作】"
        "待皇帝定夺。读皇帝这句话，判断他对这些暂存动作的态度：\n"
        "  应允=准/可/照办/就这么办/依卿所奏/便如此；\n"
        "  拒绝=不必/罢了/再议/不准/作罢/算了；\n"
        "  留中=留中/留中不发/先搁置不颁（挂起，非拒绝）；\n"
        "  无=没提这些、继续说别的、含糊未表态。\n"
        "只输出一个 JSON（无代码围栏、无多余字）：{\"确认\":\"应允|拒绝|留中|无\"}。语义判断，别拘字面。\n\n"
        "【待皇帝定夺的暂存动作】" + summ + "\n"
        "【皇帝】" + (player_message or "（无）") + "\n"
        "【大臣回话】" + (minister_reply or "（无）") + "\n"
    )
    raw = ""
    try:
        raw, _ = _run_json_extractor_for_config(prompt, llm_config, tag="confirmation")
    except Exception as exc:  # 抽取失败不阻断对话；当未表态，暂存留到颁诏(算同意)
        _log(f"确认意图抽取失败：{exc}")
    obj = _loads_lenient(raw) or {}
    v = str(obj.get("确认") or "无").strip()
    return v if v in {"应允", "拒绝", "留中", "无"} else "无"


def extract_directive_confirmation(
    player_message: str,
    minister_reply: str,
    candidates: List[Dict[str, Any]],
    llm_config: Any = None,
) -> Dict[str, Any]:
    """多道圣旨并存时（#502），判皇帝口头准驳/留中**指向哪几道**（提案粒度，AC4）。
    返回 {"decision": "应允|拒绝|留中|无|含糊", "target_ids": [id...]}。
    - 意图明确、指名了哪道 → decision=应允/拒绝/留中，target_ids=点名的候选 id。
    - 意图明确、但**没指明是哪道**（多道并存说「准了/留中」）→ decision=含糊、target_ids=[]，
      驱动大臣当场追问澄清（AC5：不静默当「不回→默认同意」）。
    - 没在准驳这些 → decision=无。
    抽取失败按含糊兜底（多道下宁可追问，不误提交）。#525 留中复用同一 target_ids/含糊规则。"""
    by_id = {int(c["id"]): c for c in candidates}
    listing = "\n".join(
        f"  [{int(c['id'])}] {str(c.get('summary') or '')[:40]}" for c in candidates
    )
    prompt = (
        "你是信息抽取器，不扮演。本夜大臣名下有下列**多道各自独立**的圣旨候选待皇帝定夺。"
        "读皇帝这句话，判断他的口头准驳/留中**指向哪几道**：\n"
        "  应允=准/照办这几道；拒绝=不必/作罢这几道；留中=留中/留中不发这几道；"
        "含糊=有准驳或留中意思但没指明是哪道；无=没提这些。\n"
        "只输出一个 JSON（无代码围栏、无多余字）：\n"
        '{"决定":"应允|拒绝|留中|无|含糊","目标编号":[方括号里的候选编号...]}。\n'
        "指向具体某道就填其编号；说「准了/都准/留中」但多道并存又没指明哪道=含糊、目标编号留空。语义判断，别拘字面。\n\n"
        "【候选】\n" + listing + "\n"
        "【皇帝】" + (player_message or "（无）") + "\n"
        "【大臣回话】" + (minister_reply or "（无）") + "\n"
    )
    raw = ""
    try:
        raw, _ = _run_json_extractor_for_config(prompt, llm_config, tag="directive_confirmation")
    except Exception as exc:  # 抽取失败：多道下按含糊兜底（追问，不误提交）
        _log(f"多道准驳指认抽取失败：{exc}")
        return {"decision": "含糊", "target_ids": []}
    obj = _loads_lenient(raw) or {}
    if not isinstance(obj, dict):
        obj = {}
    decision = str(obj.get("决定") or "无").strip()
    if decision not in {"应允", "拒绝", "留中", "无", "含糊"}:
        decision = "无"
    raw_targets = obj.get("目标编号") or []
    target_ids: List[int] = []
    if isinstance(raw_targets, list):
        for t in raw_targets:
            digits = "".join(ch for ch in str(t) if ch.isdigit())
            if digits and int(digits) in by_id and int(digits) not in target_ids:
                target_ids.append(int(digits))
    # 准驳/留中意图明确却没指到任何一道 → 含糊（AC5：不落到静默默认）。
    if decision in {"应允", "拒绝", "留中"} and not target_ids:
        decision = "含糊"
    return {"decision": decision, "target_ids": target_ids}


def _matched_prefix(message: str, prefixes) -> Optional[str]:
    """消息命中某前缀则返回前缀后的正文（玩家那句意图），否则 None。"""
    pm = (message or "").strip()
    for pre in prefixes:
        if pm.startswith(pre):
            return pm[len(pre):].strip()
    return None


def _scan_outside_strings(text: str, handle) -> str:
    """逐字扫描 text，字符串内部（含转义）原样输出；字符串外的字符交给
    handle(text, i, out, n) -> next_i 处理（append 想保留的到 out、返回下一位置）。
    JSONC 清洗的共享底座：字符串/转义态只在此一处维护，避免每趟各写一份状态机。"""
    out: List[str] = []
    in_str = esc = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
        elif ch == '"':
            in_str = True
            out.append(ch)
            i += 1
        else:
            i = handle(text, i, out, n)
    return "".join(out)


def _strip_jsonc(body: str) -> str:
    """quote-aware 清洗 JSONC：剥 // 行注释、去结构尾逗号，但字符串内部一律不动——
    串值里的 //、,}、:// （如 "x,}" / "a//b" / "http://..."）全保留。
    旧实现用裸正则非 quote-aware，会把串内 // 当注释、串内 ,} 当尾逗号误伤（#6）。
    两趟扫描：先剥注释（避免「逗号到右括号之间夹注释」漏判尾逗号），再去尾逗号。"""
    def _strip_comment(t: str, i: int, out: List[str], n: int) -> int:
        if t[i] == "/" and i + 1 < n and t[i + 1] == "/":
            nl = t.find("\n", i)
            return n if nl == -1 else nl  # 跳到行尾（换行本身保留，由下一轮 append）
        out.append(t[i])
        return i + 1

    def _strip_trailing_comma(t: str, i: int, out: List[str], n: int) -> int:
        if t[i] == ",":
            k = i + 1
            while k < n and t[k] in " \t\r\n":
                k += 1
            if k < n and t[k] in "}]":
                return i + 1  # 丢弃结构尾逗号
        out.append(t[i])
        return i + 1

    return _scan_outside_strings(_scan_outside_strings(body, _strip_comment), _strip_trailing_comma)


def _loads_lenient(
    raw: str, *, accepted_types: tuple[type, ...] = (dict,),
) -> Optional[Any]:
    """容错解析 JSON：剥代码围栏并截取首个受理容器。失败返回 None。"""
    t = (raw or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    starts = []
    if dict in accepted_types:
        starts.append((t.find("{"), "}"))
    if list in accepted_types:
        starts.append((t.find("["), "]"))
    starts = [(index, closer) for index, closer in starts if index >= 0]
    if not starts:
        return None
    i, closer = min(starts, key=lambda item: item[0])
    j = t.rfind(closer)
    if j <= i:
        return None
    body = t[i:j + 1]
    try:
        obj = json.loads(body)
    except (ValueError, TypeError):
        # 严格解析失败才做 JSONC 容错（CMR F8）：模型照 prompt 模板回带 // 行注释或尾逗号时救回。
        # 先严格、失败才清洗 —— 合法 JSON 不经清洗器。清洗器 quote-aware：串值里的 //、,}、://
        # 一律不动（#6，旧裸正则会误伤 "x,}"→"x}"、"a//b"→截断）。
        try:
            obj = json.loads(_strip_jsonc(body))
        except (ValueError, TypeError):
            return None
    return obj if isinstance(obj, accepted_types) else None


def enrich_initiative_effects(title: str, stage: str = "", llm_config: Any = None) -> Dict[str, Any]:
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
        '    "new_armies": [{"id":"英文小写id","name":"军名","owner_power":"ming","manpower":兵额(整数,如18000),"pay_source_region":"饷源省region_id如shaanxi","province_pay_share":省份额0到1,"central_pay_share":中央份额0到1,"commander":"主将姓名或空","station":"驻地","troop_type":"步/骑/水/车营","火器":0到100整数(火器局/神机营/火器新军给高),"随军大炮":0到12整数门数(炮营/红夷炮新军给几门)}],   // 明军必须给饷源省+省/中央份额(和=1)，月饷总额由引擎按 manpower 派生，勿列饷额\n'
        '    "army_delta": {"既有军id":{"manpower":增兵整数,"火器":增量,"随军大炮":门数增量,"reason":""}},\n'
        '    "人物变更": [{"name":"必须是确切人名","动作":"处置","status":"dead/exiled/imprisoned/dismissed/retired","reason":""}]\n'
        "  },\n"
        '  "ongoing_effects": {"economy": [{"account":"国库/内库","delta":负数月度开销,"category":"","reason":""}]},\n'
        '  "effect_on_fail": {"metrics": {"民心": 负int}}\n'
        "}\n"
        "【按国策性质选类型，不要全用 metrics 凑数】：\n"
        "- 营建/办厂/设局/筑堡/设仓/建坞/立学 → buildings.create（科技/军事厂局让推演认军备能力，别只给民心）\n"
        "- 练兵/募营/建新军 → new_armies（给合理兵额/主将/驻地；owner_power=\"ming\" 的普通明军必须给 pay_source_region + province_pay_share + central_pay_share，份额和=1；月饷总额由引擎按 manpower 派生）\n"
        "- 给既有军扩编/补员 → army_delta\n"
        "- 暗杀/处决/罢黜/流放/下狱某个**确切人物**(含敌酋如皇太极) → 人物变更(name 必须确切、动作=处置、status 取白名单)\n"
        "- 整顿提威/安民/财政新政 → metrics / economy\n"
        "规则：① 数值朴素(个位到一二十/兵额按史实体量)；② 只有确需周期烧钱的实体才给 ongoing_effects.economy(负)，否则 {}；"
        "③ 不相关的类型留空，别硬塞；④ region_id 拼音码：京师=beizhili 陕西=shaanxi 辽东=liaodong 山东=shandong "
        "河南=henan 南直隶=nanzhili 浙江=zhejiang 福建=fujian 广东=guangdong 湖广=huguang 四川=sichuan 山西=shanxi 江西=jiangxi 云南=yunnan，不确定 beizhili。\n\n"
        "【国策】" + (title or "") + "\n【现状】" + (stage or "（无）") + "\n"
    )
    raw = ""
    try:
        raw, _ = _run_backend_for_config(prompt, llm_config, tag="issue_enrich")
    except Exception as exc:  # 补全失败不阻断结算（trace 已在咽喉记下，含 error）
        _log(f"国策效果补全失败：{exc}")
    obj = _loads_lenient(raw) or {}
    try:
        from ming_sim.simulation import _canonical_item_fields
        norm = _canonical_item_fields(obj) if obj else {}
    except Exception:
        norm = obj
    # isinstance 守门：norm 或其子段被 LLM 给成非 dict 时归 {}，不让 dict("乱填") 抛错
    # 越过上层 floor、把空壳国策放进库（CMR codexB）。
    def _d(v):
        return v if isinstance(v, dict) else {}
    norm = _d(norm)
    resolve = _d(norm.get("effect_on_resolve"))
    # 建筑 create 缺 region_id 兜底，免得静默落不了地。
    # isinstance 守卫：LLM 可能把 buildings 给成真值非 list（true/数字/字符串），`or []` 兜不住
    # （字符串还会逐字符迭代），`for b in 它` 抛 TypeError 崩回合（#117）——同文件 tags 的 list 守卫风格。
    _bld = resolve.get("buildings")
    if not isinstance(_bld, list):
        # 非 list 脏值（true/数字/字符串）：不仅跳迭代，还在源头把 resolve 里重置成 []，免脏值落库
        # （PR#127 gemini：源头清洗，下游虽有守卫但不该存非规范值）。键不存在则不引入。
        _bld = []
        if "buildings" in resolve:
            resolve["buildings"] = _bld
    for b in _bld:
        if isinstance(b, dict) and str(b.get("action") or "").lower() == "create" and not b.get("region_id"):
            b["region_id"] = "beizhili"

    return {
        "effect_on_resolve": resolve,
        "ongoing_effects": _d(norm.get("ongoing_effects")),
        "effect_on_fail": _d(norm.get("effect_on_fail")),
    }


_CLAUSE_SPLIT = re.compile(r"[，,。.；;！!？?、：:\n\r]+")


def _content_reflects_emperor_intent(content: str, emperor_intent: str) -> bool:
    """LLM『内容』是否完整保留皇帝显式旨意（#397 Step5 防丢御旨守门）。

    皇帝旨意常由若干分句（以中英文标点断句）组成，每一分句都是不可吞掉的『一部分』。
    故按分句逐条核验：去空白后每个分句须作为连续子串出现在『内容』里——只留前半段、
    丢掉后半段显式条款（如漏『三月内回奏』）即判未覆盖，走兜底合并。容许 LLM 在分句之外
    增补大臣要点/润色衔接，但不得吞掉任何一分句。旧 LCS≥半 判据会放过半段丢失，已弃用。
    皇帝无显式旨意（前缀后为空）时视为无需守护。"""
    if not emperor_intent:
        return True
    c = re.sub(r"\s+", "", content or "")
    e = re.sub(r"\s+", "", emperor_intent)
    if not e:
        return True
    clauses = [seg for seg in _CLAUSE_SPLIT.split(e) if seg]
    if not clauses:
        return True
    return all(clause in c for clause in clauses)


# ── 密令 content 结构化装配（#1274 K1 / ADR 0142）──
# content = 御旨 + extractor schema「内容」。reply 永不入拼装输入；
# 大臣实质补充必须由 extractor 显式契约字段承载，禁从回话自由散文抠语义。


def assemble_secret_order_content(
    *,
    emperor_intent: str,
    extractor_content: str,
) -> str:
    """密令正文唯一结构化装配：御旨 + extractor「内容」。

    签名故意不含 reply/minister_reply——答奏归对话记录；补全字段（标签/期限）
    走 payload 结构化键，不经本函数自由文本拼装。三路（抽取/暂存合并/更新·哨兵）
    同口径。
    """
    emperor = (emperor_intent or "").strip()
    extracted = (extractor_content or "").strip()
    if extracted and _content_reflects_emperor_intent(extracted, emperor):
        return extracted
    return _merge_secret_content(emperor, extracted)


# 大臣回话里"建议某人承办"的线索：大臣常以"可授/可委/请授 X …"点名承办人。
# LLM 偶发把『承办人』留空、甚至把该人从正文里也抹掉——#397 Step6 须兜底找回，
# 不让大臣补充的承办人被"看起来合法"的 LLM 输出吞掉。只认建议式措辞（可授/请授/可委…），
# 不认皇帝祈使式"着/令"——后者常带机关名（着户部…），会把"户部"误当人名。
# 贪心 {2,4} + 尾部剥动作字（#397 Step6 R3 agy P0）：旧非贪心 {2,4}? 在动词首字不在
# lookahead 时会把动作字吞进名字（如『周延儒监督』→『周延儒监』）或丢掉整条线索
# （如『李若琏负责』→ None）。改为贪心捕获后从尾部剥 _ASSIGNEE_VERB_TAIL_CHARS 中的
# 动词首字（lookahead 扩充 监|协|处|负 覆盖更多动词），保证不漏不脏。
_ASSIGNEE_HINT_RE = re.compile(
    r"(?:可\s*委\s*派|可\s*差\s*派|请\s*委\s*派|请\s*差\s*派|建议\s*委\s*派|建议\s*差\s*派|"
    r"可\s*授|可\s*委|可\s*差|可\s*令|可\s*派|请\s*授|请\s*委|请\s*派|"
    r"建议\s*授|建议\s*委|可\s*由|可\s*命)"
    r"\s*([\u4e00-\u9fa5·]{2,4})"
    r"(?=[，,。.；;！!？?、\s]|暗|密|调|督|拟|领|查|办|为|任|去|往|主|核|理|统|提|巡|镇|守|征|讨|驻|屯|管|行|前|担|监|协|处|负|$)"
)
# 动作动词首字集：greedy 捕获后从尾部剥掉这些字。与 lookahead 的动词字同集——
# lookahead 判定名字后的动词首字、tail strip 剥掉被贪心吞进名字的动词首字（#397 Step6 R3 agy P0）。
_ASSIGNEE_VERB_TAIL_CHARS = frozenset("暗密调督拟领查办为任去往主核理统提巡镇守征讨驻屯管行前担监督协处负责")
# 捕获到机关/地名（含 部/寺/院… 字）的不是人名，跳过。
# 注意：曹是常见姓（曹化淳/曹文诏），不是机关字，故不入此集（#397 Step6 R3 Codex P2）。
# 卫/司 同是常见姓（卫景瑗 / 司马…），单字出现不得误拒——只在构成可识别机关词（锦衣卫 /
# 布政司…）时才拒（#401 R1 CodeRabbit major：旧 [..卫..司..] 把任何含 卫/司 的真名误判机关）。
_ASSIGNEE_HINT_STOP_RE = re.compile(r"[部寺院局省州府县营阁监科室库厂仓]")
# 卫/司 类机关整词：单源 INSTITUTION_PARTICIPANT_TOKENS（participant_roster）。
_ASSIGNEE_HINT_INSTITUTION_RE = re.compile(
    "|".join(re.escape(token) for token in _ASSIGNEE_HINT_INSTITUTION_TOKENS)
)


def _is_institution_like_name(name: str) -> bool:
    """名字是否像机关/地名：含 部/寺/院… 单字，或 锦衣卫/布政司… 整词。

    仅供 assignee-hint / 祈使承办人线索拒识。人物参与人过滤不得复用本函数——
    单字 stop-class 会误伤带姓称谓别名（韩阁老/毕户部/曹太监）。
    非人参与人判定见 participant_roster.is_non_person_participant_name（#1279/#1391）。
    """
    return bool(_ASSIGNEE_HINT_STOP_RE.search(name) or _ASSIGNEE_HINT_INSTITUTION_RE.search(name))


# 兼容旧测/调用：闭集与判定真源在 participant_roster（上表 import 别名）。
# _NON_PERSON_PARTICIPANT_NAMES / _BARE_INSTITUTION_PARTICIPANT_NAMES /
# _is_non_person_participant_name 由模块顶 import 绑定。


def _extract_assignee_hint(text: str) -> Optional[str]:
    """从文本（多为大臣回话）里找"建议某人承办"的人名线索。无则 None。

    #397 Step6 R3（agy P0）：greedy 捕获后从尾部剥动作字——旧非贪心 {2,4}? 在动作首字
    不在 lookahead 时会把动作字吞进名字或丢掉整条线索（如『周延儒监督』→『周延儒监』、
    『李若琏负责』→ None）。"""
    for m in _ASSIGNEE_HINT_RE.finditer(text or ""):
        name = m.group(1).strip()
        while len(name) > 2 and name[-1] in _ASSIGNEE_VERB_TAIL_CHARS:
            name = name[:-1]
        if len(name) >= 2 and not _is_institution_like_name(name):
            return name
    return None


# 皇帝祈使式指名（着/令/命/敕 X …）：从御旨/最终 content 抽承办人。与大臣建议式分开：
# 祈使式常带机关名（着户部…）须过机关滤；后跟副词时（着即办/着速理）排除——加副词起头守门。
# #401 R1（CodeRabbit major codex P2）：御旨常以『着X』指名，LLM 却偶发把承办人字段留空
# 或漂移到默认召对大臣——此函数从皇帝显式旨意找回承办人，供 _choose_assignee 校验。
_ASSIGNEE_IMPERATIVE_RE = re.compile(
    r"(?<![\u4e00-\u9fa5·])(?:着|令|命|敕)\s*([\u4e00-\u9fa5·]{2,4})"
    r"(?=[，,。.；;！!？?、\s]|暗|密|调|督|拟|领|查|办|为|任|去|往|主|核|理|统|提|巡|镇|守|征|讨|驻|屯|管|行|前|担|监|协|处|负|$)"
)
_ASSIGN_NAME_HEAD_ADVERB_RE = re.compile(r"^[即速快立妥当应须且便赶]")


def _extract_imperative_assignee(text: str) -> Optional[str]:
    """从祈使式（着/令/命/敕 X …）里抽承办人。无则 None。"""
    for m in _ASSIGNEE_IMPERATIVE_RE.finditer(text or ""):
        name = m.group(1).strip()
        while len(name) > 2 and name[-1] in _ASSIGNEE_VERB_TAIL_CHARS:
            name = name[:-1]
        if (len(name) >= 2
                and not _ASSIGN_NAME_HEAD_ADVERB_RE.match(name)
                and not _is_institution_like_name(name)):
            return name
    return None


def _choose_assignee(
    assignee_llm: str,
    player_command: str,
    minister_reply: str,
    content: str,
    default_assignee: str,
) -> str:
    """选定承办人：LLM 字段经校验才采信，否则退回经校验线索，最后才默认召对大臣。

    #401 R1（CodeRabbit major）：旧 `assignee = _assignee_llm or _assignee_hint or default`
    盲信任何非空 LLM 字段——正文留李若琏、字段却填王在晋时即漂移。改为：线索取自皇帝
    显式旨意（祈使式）+ 大臣回话（建议式）+ 最终正文；LLM 字段仅当与某条线索一致、或确实
    出现在最终正文里才采信；否则用第一条经校验线索；无线索才退回默认。"""
    hints: List[str] = []
    seen: set = set()
    for h in (
        _extract_imperative_assignee(player_command),
        _extract_assignee_hint(minister_reply),
        _extract_assignee_hint(content),
        _extract_imperative_assignee(content),
    ):
        if h and h not in seen:
            seen.add(h)
            hints.append(h)
    llm = (assignee_llm or "").strip()
    if hints:
        # 多条线索冲突时，按来源优先级取第一条（御旨祈使 > 大臣建议 > 正文）。
        # 不能因为坏 LLM 字段出现在兜底合并后的正文里，就覆盖更权威的显式线索。
        if llm and llm == hints[0]:
            return llm
        return hints[0]
    if llm and len(llm) >= 2 and llm in (content or ""):
        return llm
    return default_assignee


def _split_audience_context(context: str) -> Tuple[str, str]:
    """把召对上下文快照剥成 (皇帝任务文本, "")：去掉「皇帝：/大臣：」角色标签、
    「【本轮确认】…」只保留期限/约束等实质补充。皇帝行=任务正文（作御旨守门输入+兜底种子）。

    #1274 K1 / ADR 0142：大臣行不再并入 content 拼装——实质补充须由 extractor「内容」字段
    承载；第二返回值恒为空串，保留元组形以免调用点分叉。
    """
    entries: List[Tuple[str, str]] = []  # ("e"=皇帝任务行,)
    for raw in (context or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("【本轮确认】"):
            material = _secret_confirmation_material(line.removeprefix("【本轮确认】"))
            if material:
                entries.append(("e", material))
            continue
        if line.startswith("皇帝："):
            task = line[len("皇帝："):].strip()
            if task:
                entries.append(("e", task))
        # 大臣行：不入 content 拼装（extractor 读完整上下文自行抽「内容」）
    # 只取最近的任务跨度：排除同回合更早的无关问答，但保留连续多条相关皇帝任务行。
    # 旧实现从最后一条皇帝行起，能排除「京营操练如何？」这类无关问答，却会丢掉
    # 「先命洪承畴赈灾、再令东厂护银」这种前几轮连续补充的同一密令任务。
    boundary = -1
    for i, (kind, text) in enumerate(entries):
        if kind == "e" and not _secret_context_task_like(text):
            boundary = i
    emperor_indices = [i for i, (kind, _text) in enumerate(entries) if i > boundary and kind == "e"]
    if not emperor_indices:
        emperor_indices = [i for i, (kind, _text) in enumerate(entries) if kind == "e"]
    start = emperor_indices[-1] if emperor_indices else None
    selected_emperor = entries[start][1] if start is not None else ""
    if start is not None:
        for i in reversed(emperor_indices[:-1]):
            prior_text = entries[i][1]
            if not _secret_context_tasks_related(prior_text, selected_emperor):
                break
            start = i
            selected_emperor = prior_text + "\n" + selected_emperor
    span = entries[start:] if start is not None else entries
    emperor_lines = [text for kind, text in span if kind == "e"]
    return "\n".join(emperor_lines), ""


def _secret_context_task_like(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    if not compact:
        return False
    if _secret_context_constraint_like(compact):
        return True
    if re.search(r"[?？]$", compact):
        return False
    return bool(re.search(r"(命|令|着|遣|派|督办|查|暗查|密查|护|封存|截留|赈|再令|另令|须|务必|回奏|月内|日内)", compact))


def _secret_context_tasks_related(prior: str, later: str) -> bool:
    later_compact = re.sub(r"\s+", "", later or "")
    if _secret_context_constraint_like(later_compact):
        return True
    if re.search(r"^(再|另|又|并|仍|复)(令|命|着|遣|派)", later_compact):
        return bool(_secret_context_topic_chars(prior) & _secret_context_topic_chars(later))
    if re.search(r"(月内|日内|回奏|结案|期限)", later_compact) and not re.search(
        r"(命|令|着|遣|派|督办|暗查|密查|查|护|封存|截留|赈)", later_compact
    ):
        return True
    return False


def _secret_context_constraint_like(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    return bool(re.search(r"(机密|保密|不可泄露|不得泄露|不得外泄|不可外泄|勿泄|秘而不宣|勿使.*知晓|不得.*知晓)", compact))


def _secret_context_topic_chars(text: str) -> set:
    compact = re.sub(r"[^\u4e00-\u9fff]", "", text or "")
    compact = re.sub(r"^(再|另|又|并|仍|复)?(令|命|着|遣|派)", "", compact)
    compact = re.sub(
        r"^[\u4e00-\u9fff]{2,4}(?=(督办|暗查|密查|查|护|封存|截留|加操|操练|密访|补|拨))",
        "",
        compact,
    )
    compact = re.sub(
        r"(此事|机密|保密|不可|不得|泄露|外泄|勿泄|秘而不宣|知晓|再|另|又|并|仍|复|令|命|着|遣|派|督办|暗查|密查|查|护|封存|截留|须|务必|回奏|月内|日内|臣|领命|遵旨|谨记|加操|操练)",
        "",
        compact,
    )
    return set(compact)


def _secret_confirmation_material(text: str) -> str:
    material = (text or "").strip()
    if not material:
        return ""
    atoms = (
        "准卿所奏", "按你意思", "照你意思", "就这么办", "便如此", "准奏", "照准",
        "照办", "就按", "就照", "依卿", "依你", "便依", "同意", "卿所奏",
        "你意思", "所奏", "如此", "这么办", "就办", "可", "准", "好", "是",
        "善", "行", "办", "吧", "奏",
    )
    changed = True
    while changed:
        changed = False
        material = re.sub(r"^[\s，,。.!！?？；;：:、]+", "", material)
        for atom in atoms:
            if material.startswith(atom):
                material = material[len(atom):]
                changed = True
                break
    material = re.sub(r"^[\s，,。.!！?？；;：:、]+", "", material).strip()
    return material


def _merge_secret_content(*parts: str) -> str:
    """把皇帝显式旨意 / LLM 内容 / 大臣回话合并成一道密令正文，去重保序。

    #397 Step6：兜底合并须同时保住御旨与大臣补充（承办人/要点），任一非空都并入；
    完全相同的段（去空白后）只留一份，避免 LLM 内容与回话雷同时整段重复。"""
    merged: List[str] = []
    seen: set = set()
    for p in parts:
        chunk = (p or "").strip()
        if not chunk:
            continue
        key = re.sub(r"\s+", "", chunk)
        if key in seen:
            continue
        seen.add(key)
        merged.append(chunk)
    return "\n".join(merged)


def _secret_metadata_from_command(text: str) -> Tuple[List[str], int]:
    tags: List[str] = []
    deadline = 0
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m_tags = re.match(r"^(?:标签|tag|tags)\s*[：:]\s*(.+)$", line, flags=re.IGNORECASE)
        if m_tags:
            for item in re.split(r"[,，、/;；\s]+", m_tags.group(1)):
                cleaned = item.strip()
                if cleaned and cleaned not in tags:
                    tags.append(cleaned)
            continue
        m_deadline = re.match(r"^(?:期限|限期|deadline)\s*[：:]\s*(.+)$", line, flags=re.IGNORECASE)
        if m_deadline:
            match = re.search(r"([+-]?\d+)\s*(?:个)?月", m_deadline.group(1))
            if match:
                deadline = max(0, min(int(match.group(1)), 36))
    return tags, deadline


def _normalize_dossier_link_proposals(
    dossier_candidates: Optional[List[Dict[str, Any]]],
    suggested_links: Any,
) -> Dict[Tuple[int, str], Dict[str, Any]]:
    """Return the one canonical, visible set of dossier-link proposals."""
    candidate_ids = {
        row["id"] for row in (dossier_candidates or [])
        if isinstance(row, dict) and type(row.get("id")) is int
    }
    proposals: Dict[Tuple[int, str], Dict[str, Any]] = {}
    for link in suggested_links if isinstance(suggested_links, list) else []:
        if not isinstance(link, dict) or type(link.get("target_dossier_id")) is not int:
            continue
        target = link["target_dossier_id"]
        relation = str(link.get("relation_type") or "").strip()
        note = str(link.get("note") or "").strip()
        if target in candidate_ids and relation in DOSSIER_LINK_TYPES and note:
            proposals[(target, relation)] = {
                "target_dossier_id": target, "relation_type": relation, "note": note}
    return proposals


def confirm_dossier_links(
    minister_reply: str,
    dossier_candidates: Optional[List[Dict[str, Any]]],
    suggested_links: Any,
    llm_config: Any = None,
) -> List[Dict[str, Any]]:
    """Use one structured semantic verdict to narrow model-suggested links.

    Internal IDs are capabilities only: the verdict may select an ID only from
    both the reader-visible candidates and the producer's structured proposal.
    A failed/ambiguous verdict authorises nothing.
    """
    candidates = {
        int(row["id"]): str(row.get("secret_title") or row.get("decree_text") or "").strip()
        for row in (dossier_candidates or [])
        if isinstance(row, dict) and type(row.get("id")) is int
    }
    proposals = _normalize_dossier_link_proposals(dossier_candidates, suggested_links)
    if not proposals:
        return []
    prompt = (
        "你是案卷关联确认判词，不是对话角色。只依据【大臣最终可见回话】的完整语义判断；"
        "否定、仅引用旧案、模糊复述、长短标题包含歧义、未明确承诺关联，均不得确认。"
        "内部ID只用于输出，不是确认依据。只输出合法JSON："
        "{\"confirmed_links\":[{\"target_dossier_id\":整数,\"relation_type\":\"护卫/稽核/接应\"}]}。\n"
        "【可选提议】\n" + "\n".join(
            f"- #{target} {candidates[target]}；{relation}；{item['note']}"
            for (target, relation), item in proposals.items()
        ) + "\n【大臣最终可见回话】\n" + (minister_reply or "（空）")
    )
    try:
        raw, _ = _run_json_extractor_for_config(prompt, llm_config, tag="dossier_link_confirmation")
        verdict = _loads_lenient(raw) or {}
    except Exception as exc:
        _log(f"案卷关联确认失败：{exc}")
        return []
    if not isinstance(verdict, dict):
        return []
    links = verdict.get("confirmed_links")
    if not isinstance(links, list):
        return []
    confirmed = set()
    for link in links:
        if not isinstance(link, dict) or type(link.get("target_dossier_id")) is not int:
            return []
        relation = link.get("relation_type")
        if relation not in DOSSIER_LINK_TYPES:
            return []
        confirmed.add((link["target_dossier_id"], relation))
    return [item for identity, item in proposals.items() if identity in confirmed]


def _extract_secret_order(
    player_command: str,
    minister_reply: str,
    default_assignee: str,
    llm_config: Any = None,
    force_default_assignee: bool = False,
    dossier_candidates: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """聚焦提取：把密令交代+大臣回话抽成结构化字段。纯抽取任务（不扮演），
    与月末 extractor 同款可靠。失败则退回合理默认。"""
    prompt = (
        "你是一个严谨的信息抽取器，不是大臣，不要扮演、不要写圣旨。\n"
        "下面是皇帝下达的一道密令交代，以及承命大臣的回话。请抽出这道密令的结构化字段，"
        "只输出一个 JSON 对象，不要 markdown 代码围栏、不要 JSON 以外任何字：\n"
        "{\n"
        "  \"标题\": \"密令简称，概括任务，如 密查关宁军饷、暗结蒙古诸部（不硬截长度）\",\n"
        "  \"内容\": \"密令完整任务详情：目标、保密要求、做法；须并入大臣回话中的实质补充"
        "（承办建议/步骤/方法），但不得写入领旨/遵旨/谢恩等答奏套话\",\n"
        "  \"承办人\": \"实际承办此密令的人名；皇帝或大臣指明谁就填谁，没指明就填 "
        + (default_assignee or "") + "\",\n"
        "  \"期限月数\": 整数，皇帝限了期就填月数（如『三月内结案』填3），没限填0,\n"
        "  \"标签\": [\"相关人名/地区/事项关键词\"],\n"
        "  \"排除对象\": {\"人物\": [\"明确说要瞒住的人名\"], \"机构\": [\"不走的衙门\"]},\n"
        "  \"案卷关联\": [{\"目标案卷ID\": 123, \"类型\": \"护卫/稽核/接应\", "
        "\"说明\": \"一句说明\"}]\n"
        "}\n"
        "案卷关联只能填写大臣回话中已明确复述确认、且在下列候选中的具体旧案卷 ID；模糊指代、未确认或没有 ID 时填空列表。\n"
        "【可引用旧案卷】\n" + "\n".join(
            f"- #{int(row['id'])} {row.get('secret_title') or row.get('decree_text') or row.get('action_type') or ''}"
            for row in (dossier_candidates or [])
        ) + "\n\n"
        "【皇帝密令】" + (player_command or "（无）") + "\n"
        "【大臣回话】" + (minister_reply or "（无）") + "\n"
    )
    raw = ""
    confirmation_future = None
    confirmation_pool = None
    if cli_backend_parallel_safe(llm_config) and dossier_candidates:
        # Confirmation reads only the already-visible reply/candidate set, so it
        # can run beside field extraction; extracted proposals are intersected locally below.
        broad_proposals = [
            {"target_dossier_id": int(row["id"]), "relation_type": relation, "note": "待抽取后核对"}
            for row in dossier_candidates for relation in DOSSIER_LINK_TYPES
        ]
        confirmation_pool = ThreadPoolExecutor(max_workers=1)
        confirmation_future = confirmation_pool.submit(
            confirm_dossier_links, minister_reply, dossier_candidates, broad_proposals, llm_config)
    try:
        raw, _attempts = _run_json_extractor_for_config(prompt, llm_config, tag="secret_extract")
    except Exception as exc:  # 提取失败不阻断：退回默认（trace 已在咽喉记下，含 error）
        _log(f"密令提取失败：{exc}")
    finally:
        # The confirmation future remains readable after shutdown.  Owning the
        # executor here guarantees cleanup even if any later normalization raises.
        if confirmation_pool is not None:
            confirmation_pool.shutdown(wait=True)
    obj = _loads_lenient(raw) or {}
    _content_llm = str(obj.get("内容") or "").strip()
    _assignee_llm = str(obj.get("承办人") or "").strip()
    # 上下文合成路径（force_default_assignee，#354 短确认从对话取正文）：player_command 是带
    # 「皇帝：/大臣：」标签的对话快照——剥角色标签得纯御旨任务，作装配输入。
    # #1274 K1 / ADR 0142：content = 御旨 + extractor「内容」；reply 永不入拼装。
    # 大臣实质补充必须出现在 extractor schema「内容」字段（上 prompt 已钉契约）。
    if force_default_assignee:
        _emperor_fallback, _ = _split_audience_context(player_command)
    else:
        _emperor_fallback = player_command
    content = assemble_secret_order_content(
        emperor_intent=_emperor_fallback,
        extractor_content=_content_llm,
    )
    # No formal title hard-cap: keep the full extracted title; only synthesize a
    # short fallback when the extractor omitted 标题 entirely.
    title = str(obj.get("标题") or "").strip() or (content or player_command)[:14]
    # 承办人：LLM 字段经校验才采信（防漂移），否则退回经校验线索（御旨祈使 / 大臣建议 /
    # 最终正文），最后才默认召对大臣（#401 R1 CodeRabbit major：旧 `or` 链盲信任何非空
    # LLM 字段，正文留李若琏、字段填王在晋时即漂移）。
    assignee = default_assignee if force_default_assignee else _choose_assignee(
        _assignee_llm, player_command, minister_reply, content, default_assignee
    )
    raw_deadline = obj.get("期限月数")
    explicit_zero_deadline = raw_deadline in (0, "0")
    try:
        deadline = max(0, min(int(raw_deadline or 0), 36))
    except (TypeError, ValueError):
        deadline = 0
    tags = obj.get("标签")
    tags = [str(t).strip() for t in tags if str(t).strip()] if isinstance(tags, list) else []
    from ming_sim.db import canonical_secret_order_exclusions
    raw_targets = obj.get("排除对象") if isinstance(obj.get("排除对象"), dict) else {}
    raw_people = raw_targets.get("人物", raw_targets.get("people", obj.get("排除名单", [])))
    raw_offices = raw_targets.get("机构", raw_targets.get("offices", []))
    excluded_names, excluded_offices = canonical_secret_order_exclusions(
        None,
        raw_people if isinstance(raw_people, list) else [],
        raw_offices if isinstance(raw_offices, list) else [],
        player_command,
    )
    fallback_tags, fallback_deadline = _secret_metadata_from_command(player_command)
    if not tags:
        tags = fallback_tags
    if not deadline and not explicit_zero_deadline:
        deadline = fallback_deadline
    raw_links = obj.get("案卷关联")
    extracted_proposals = [
        {
            "target_dossier_id": link.get("目标案卷ID"),
            "relation_type": link.get("类型"),
            "note": link.get("说明"),
        }
        for link in raw_links if isinstance(link, dict)
    ] if isinstance(raw_links, list) else []
    proposals = _normalize_dossier_link_proposals(dossier_candidates, extracted_proposals)
    dossier_links = list(proposals.values())
    if confirmation_future is not None:
        try:
            confirmed = {
                (item["target_dossier_id"], item["relation_type"])
                for item in confirmation_future.result()
            }
        except Exception as exc:
            _log(f"案卷关联确认失败：{exc}")
            confirmed = set()
        dossier_links = [
            item for identity, item in proposals.items() if identity in confirmed
        ]
    else:
        dossier_links = confirm_dossier_links(
            minister_reply, dossier_candidates, dossier_links, llm_config=llm_config)
    return {"title": title, "content": content, "assignee": assignee,
            "deadline_months": deadline, "tags": tags, "excluded_names": excluded_names,
            "excluded_offices": excluded_offices, "dossier_links": dossier_links,
            "excluded_targets": {"people": excluded_names, "offices": excluded_offices}}

def resolve_minister_actions(
    minister_reply: str, player_message: str = "", default_assignee: str = "", llm_config: Any = None,
    secret_context: str = "",
    dossier_candidates: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """玩家上一句带拟旨/密令前缀时生成候选。
    - 拟旨：大臣回话原文即圣旨草稿（单一文本字段，够用）。
    - 密令（#397/#1274 K1）：经 _extract_secret_order 结构化装配 content=御旨+extractor
      「内容」（reply 不入拼装）；helper 不抛错，提取失败时兜底仍保留御旨。
    返回 {decree_text, secret_order}。"""
    out: Dict[str, Any] = {"decree_text": None, "secret_order": None}
    reply = (minister_reply or "").strip()

    draft_intent = _matched_prefix(player_message, _DRAFT_PREFIXES)
    if draft_intent is not None:
        out["decree_text"] = reply or draft_intent or None

    secret_intent = _matched_prefix(player_message, _SECRET_PREFIXES)
    if secret_intent is not None and (reply or secret_intent):
        secret_command = secret_intent
        force_default_assignee = False
        if _secret_prefix_needs_recent_context(secret_intent) and (secret_context or "").strip():
            secret_command = (
                (secret_context or "").strip()
                + ("\n【本轮确认】" + secret_intent if secret_intent else "")
            ).strip()
            force_default_assignee = True
        # #397/#1274 K1：显式『密令如下：<X>』的密令正文须留住御旨 X——交
        # _extract_secret_order 结构化装配（御旨+extractor「内容」；reply 不入拼装）。
        out["secret_order"] = _extract_secret_order(
            secret_command, reply, default_assignee, llm_config,
            force_default_assignee=force_default_assignee,
            dossier_candidates=dossier_candidates,
        )

    return out


# 纯确认短句的原子片段：密令按钮当轮若【整句】只由这些片段拼成（如「可，照办」=可+照办、
# 「就按你意思办」=就按+你意思+办），说明本轮没有任务正文，须从前文召对取。锚定全匹配而非子串，
# 避免「可疑之处彻查」这类含确认字的实质命令被误判成纯确认（cmr #354 correctness：旧 exact-set
# 漏「可，照办」——issue US3 点名的确认句——而子串匹配又会误吞实质命令）。
_SECRET_CONFIRM_ATOM_RE = re.compile(
    r"^(?:"
    r"可|准|好|是|善|行|同意|照办|照准|准奏|准卿所奏|卿所奏|所奏|如此|便如此|就这么办|这么办|"
    r"就按|就照|按你意思|照你意思|你意思|依卿|依你|便依|就办|办|吧|奏"
    r")+$"
)


def _secret_prefix_needs_recent_context(secret_intent: str) -> bool:
    """显式密令按钮后只有确认短句/约束短句时，从前文召对取任务正文。"""
    text = (secret_intent or "").strip()
    if not text:
        return True
    compact = re.sub(r"[\s，,。.!！?？；;：:、]+", "", text)
    if re.search(r"(照办|按你意思|照你意思|前议|方才所奏|卿所奏|就按|就照)", compact):
        return True
    has_primary_task = bool(re.search(r"(命|令|着|遣|派|督办|暗查|密查|查|护|封存|截留|赈|加操|操练)", compact))
    has_only_constraint = bool(
        _secret_context_constraint_like(compact)
        or re.search(r"(月内|日内|回奏|结案|限期|期限)", compact)
    ) and not has_primary_task
    if has_only_constraint:
        return True
    if len(compact) > 12:
        return False
    return bool(_SECRET_CONFIRM_ATOM_RE.match(compact))


_CLI_RECOMMENDATION_CALL = re.compile(
    r"\n?\[\[recommend_person:(\{.*?\})\]\]\s*$", re.DOTALL,
)
_CLI_RECOMMENDATION_PREFIX = "[[recommend_person:"


def _cli_prompt(
    messages: List[Message], response_format: object, tools: object,
) -> str:
    """Build one CLI prompt, including instructions derived from offered tools."""
    prompt = _messages_to_prompt(messages, response_format)
    recommendation_schema = next(
        (tool.get("function", tool) for tool in (tools or [])
         if isinstance(tool, dict) and tool.get("function", tool).get("name") == "recommend_person"),
        None,
    )
    if recommendation_schema:
        prompt += (
            "\n\n【荐人调用】只有确要调用此工具时，回答末尾追加"
            f"[[recommend_person:<arguments JSON>]]；arguments 须严格符合以下已提供的工具 schema：{json.dumps(recommendation_schema.get('parameters') or {}, ensure_ascii=False)}"
        )
    return prompt


def _cli_stream_safe_prefix(text: str) -> tuple[str, str]:
    """Release text that cannot belong to a trailing recommendation envelope."""
    marker_at = text.rfind(_CLI_RECOMMENDATION_PREFIX)
    if marker_at >= 0:
        return text[:marker_at], text[marker_at:]
    keep = 0
    for length in range(1, min(len(text), len(_CLI_RECOMMENDATION_PREFIX) - 1) + 1):
        if text.endswith(_CLI_RECOMMENDATION_PREFIX[:length]):
            keep = length
    return (text[:-keep], text[-keep:]) if keep else (text, "")


def _cli_recommendation_call(text: str, tools: object) -> tuple[str, list[ChatCompletionMessageFunctionToolCall]]:
    """Adapt an explicit CLI recommendation envelope into the existing tool seam."""
    offered = next(
        (tool.get("function", tool) for tool in (tools or [])
         if isinstance(tool, dict) and tool.get("function", tool).get("name") == "recommend_person"),
        None,
    )
    match = _CLI_RECOMMENDATION_CALL.search(text) if offered else None
    if not match:
        return text, []
    try:
        payload = json.loads(match.group(1))
    except (TypeError, ValueError):
        return text, []
    schema = offered.get("parameters") or {}
    required = schema.get("required") or []
    properties = schema.get("properties") or {}
    if (not isinstance(payload, dict)
            or any(not str(payload.get(key) or "").strip() for key in required)
            or any(key not in properties for key in payload)):
        return text, []
    call = ChatCompletionMessageFunctionToolCall(
        id="cli-recommendation",
        type="function",
        function=ToolFunction(name=offered["name"], arguments=json.dumps(payload, ensure_ascii=False)),
    )
    return text[:match.start()].rstrip(), [call]


def _fake_completion(
    text: str, model_id: str, tool_calls: list[ChatCompletionMessageFunctionToolCall] | None = None,
) -> ChatCompletion:
    """把纯文本包成 OpenAI ChatCompletion 交给 agno 解析。"""
    msg = ChatCompletionMessage(role="assistant", content=text, tool_calls=tool_calls)
    choice = Choice(index=0, message=msg, finish_reason="stop")
    return ChatCompletion(
        id="cli-backend", choices=[choice], created=0,
        model=model_id, object="chat.completion",
    )


@dataclass
class CliChat(OpenAIChat):
    """agy / codex 当后端；provider 调用适配后复用 agno 的 tool loop。"""

    backend: str = "agy"
    reasoning_strength: str = ""

    def _call_cli(self, prompt: str) -> Tuple[str, int]:
        model_id = str(getattr(self, "id", "") or "")
        timeout = getattr(self, "timeout", None)
        reasoning_strength = str(getattr(self, "reasoning_strength", "") or "").strip().lower() or None
        if self.backend == "codex":
            return _run_codex(prompt, model=model_id, timeout=timeout, reasoning_strength=reasoning_strength)
        if self.backend == "claude":
            return _run_claude(prompt, model=model_id, timeout=timeout, reasoning_strength=reasoning_strength)
        if self.backend == "cursor":
            return _run_cursor(prompt, model=model_id, timeout=timeout, reasoning_strength=reasoning_strength)
        if self.backend == "kimi":
            return _run_kimi(prompt, model=model_id, timeout=timeout, reasoning_strength=reasoning_strength)
        if self.backend == "grok":
            return _run_grok(prompt, model=model_id, timeout=timeout, reasoning_strength=reasoning_strength)
        if self.backend == "agy":
            return _run_agy(prompt, timeout=timeout)
        raise RuntimeError(f"未知 CLI backend：{self.backend}")

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
        prompt = _cli_prompt(messages, response_format, tools)
        with _TRACE_LOCK:  # 原子自增，防并发丢增量/seq 重复（#83）
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
            # #1299/#1310：runner 自身失败翻成 typed LLMUnavailable，
            # 错误串不得进 content 当叙事（agno 吞 Exception 会把 str(e) 塞 content）。
            from ming_sim.exceptions import LLMUnavailable
            from ming_sim.llm_model import cli_runner_unavailable
            error = str(exc)
            if isinstance(exc, LLMUnavailable):
                raise
            raise cli_runner_unavailable(exc, backend=self.backend) from exc
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
        text, tool_calls = _cli_recommendation_call(text, tools)
        provider_response = (
            _fake_completion(text, self.id, tool_calls)
            if tool_calls else _fake_completion(text, self.id)
        )
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

    def invoke_stream(  # type: ignore[override]
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Any = None,
        compress_tool_results: bool = False,
    ):
        if self.backend != "codex" or response_format is not None:
            yield self.invoke(
                messages, assistant_message, response_format=response_format,
                tools=tools, tool_choice=tool_choice, run_response=run_response,
                compress_tool_results=compress_tool_results,
            )
            return
        prompt = _cli_prompt(messages, response_format, tools)
        held = ""
        try:
            stream = _iter_codex_stream_chunks(
                prompt,
                model=str(getattr(self, "id", "") or ""),
                timeout=getattr(self, "timeout", None),
                reasoning_strength=str(getattr(self, "reasoning_strength", "") or "").strip().lower() or None,
            )
            for delta in stream:
                ready, held = _cli_stream_safe_prefix(held + str(delta))
                if ready:
                    yield ModelResponse(role="assistant", content=ready)
        except Exception as exc:
            # #1299/#1310：流式 runner 失败同翻 typed，禁机器横幅进 delta/content。
            from ming_sim.exceptions import LLMUnavailable
            from ming_sim.llm_model import cli_runner_unavailable
            if isinstance(exc, LLMUnavailable):
                raise
            raise cli_runner_unavailable(exc, backend=self.backend) from exc
        text, tool_calls = _cli_recommendation_call(held, tools)
        if text:
            yield ModelResponse(role="assistant", content=text)
        if tool_calls:
            yield ModelResponse(
                role="assistant",
                tool_calls=[
                    ChoiceDeltaToolCall(
                        index=index,
                        id=call.id,
                        type=call.type,
                        function=ChoiceDeltaToolCallFunction(
                            name=call.function.name,
                            arguments=call.function.arguments,
                        ),
                    )
                    for index, call in enumerate(tool_calls)
                ],
            )

    async def ainvoke_stream(self, *args, **kwargs):  # type: ignore[override]
        for response in self.invoke_stream(*args, **kwargs):
            yield response

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
        **kwargs: Any,  # 吸掉 agno 演进新增的 kwarg(如 after_tool_results)，免 override 签名漂移炸 CI
    ):
        yield from super().response_stream(
            messages, response_format=response_format, tools=tools,
            tool_choice=tool_choice, tool_call_limit=tool_call_limit,
            stream_model_response=stream_model_response, run_response=run_response,
            send_media_to_model=send_media_to_model,
            compression_manager=compression_manager, **kwargs,
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
        **kwargs: Any,  # 吸掉 agno 演进新增的 kwarg(如 after_tool_results)，免 override 签名漂移炸 CI
    ):
        async for response in super().aresponse_stream(
            messages, response_format=response_format, tools=tools,
            tool_choice=tool_choice, tool_call_limit=tool_call_limit,
            stream_model_response=stream_model_response, run_response=run_response,
            send_media_to_model=send_media_to_model,
            compression_manager=compression_manager, **kwargs,
        ):
            yield response


def cli_backend_from_env() -> Optional[str]:
    """读 MING_SIM_LLM_BACKEND，返回受支持 runner 名或 None（走原 api 路径）。
    名单单一真源 = _CLI_BACKENDS（#1256 收敛，禁再硬编码枚举）。"""
    val = (os.environ.get("MING_SIM_LLM_BACKEND") or "").strip().lower()
    return val if val in _CLI_BACKENDS else None


# ── 闸脚本 LLM 参数/配置（#1256）：四脚本共用，禁各自复制 choices/_config ──


def add_gate_llm_args(parser: Any) -> None:
    """给闸脚本 argparse 加 --channel/--runner/--model/--base-url/--api-key。

    --runner choices = GATE_CLI_RUNNERS 单一真源；channel=cli 时必填 runner，
    channel=api 时 runner 可空（api_key/base_url 由参数或 env 注入，不落库）。
    """
    parser.add_argument(
        "--channel", choices=("cli", "api"), default="cli",
        help="执行通道：cli=本机 runner；api=OpenAI 兼容（ds-flash/OpenCode Go 等）",
    )
    parser.add_argument(
        "--runner", choices=GATE_CLI_RUNNERS, default="",
        help="CLI runner（channel=cli 时必填；channel=api 时忽略）",
    )
    parser.add_argument("--model", required=True, help="模型名（cli 透传 --model；api 透传 model）")
    parser.add_argument(
        "--base-url", default="",
        help="api 通道 base_url；空则读 OPENAI_BASE_URL / MING_SIM_API_BASE_URL",
    )
    parser.add_argument(
        "--api-key", default="",
        help="api 通道 key；空则读 OPENAI_API_KEY / MING_SIM_API_KEY（不落库）",
    )


def gate_llm_config_from_args(
    args: Any,
    *,
    max_tokens: int = 6000,
    reasoning_strength: str = "high",
    cli_timeout_seconds: float = 600.0,
) -> LLMConfig:
    """四闸脚本 _config/_cfg 单一实现：按 channel 构造 LLMConfig。

    channel=cli → runner 必填，api_key/base_url 空。
    channel=api → key/base_url 由 args 或 env 注入（OPENAI_* / MING_SIM_API_*），
    model 透传；runner 不写入 config。
    """
    channel = str(getattr(args, "channel", "") or "cli").strip().lower() or "cli"
    model = str(getattr(args, "model", "") or "").strip()
    if not model:
        raise ValueError("--model is required")
    if channel == "api":
        api_key = (
            str(getattr(args, "api_key", "") or "").strip()
            or (os.environ.get("OPENAI_API_KEY") or "").strip()
            or (os.environ.get("MING_SIM_API_KEY") or "").strip()
        )
        base_url = (
            str(getattr(args, "base_url", "") or "").strip()
            or (os.environ.get("OPENAI_BASE_URL") or "").strip()
            or (os.environ.get("MING_SIM_API_BASE_URL") or "").strip()
        )
        if not api_key:
            raise ValueError("channel=api requires --api-key or OPENAI_API_KEY/MING_SIM_API_KEY")
        if not base_url:
            raise ValueError(
                "channel=api requires --base-url or OPENAI_BASE_URL/MING_SIM_API_BASE_URL"
            )
        return LLMConfig(
            api_key=api_key,
            base_url=base_url,
            model=model,
            channel="api",
            max_tokens=max_tokens,
            reasoning_strength=reasoning_strength,
        )
    if channel != "cli":
        raise ValueError(f"unsupported --channel: {channel}")
    runner = str(getattr(args, "runner", "") or "").strip().lower()
    if not runner:
        raise ValueError("--runner is required when --channel=cli")
    if runner not in GATE_CLI_RUNNERS:
        raise ValueError(f"unsupported --runner: {runner} (choices={GATE_CLI_RUNNERS})")
    return LLMConfig(
        api_key="",
        base_url="",
        model=model,
        channel="cli",
        cli_runner=runner,
        cli_model=model,
        cli_timeout_seconds=cli_timeout_seconds,
        max_tokens=max_tokens,
        reasoning_strength=reasoning_strength,
    )


def require_fresh_cli_trace(cfg: LLMConfig) -> Optional[Path]:
    """CLI 通道强制新鲜 MING_SIM_TRACE_PATH；api 通道返回 None。

    四闸脚本共用单源（#1256）；禁用各自复制守卫。行为对齐原 561 变体
    （MING_SIM_TRACE 用 .strip().lower()）。
    """
    if cfg.channel != "cli":
        return None
    trace_setting = os.environ.get("MING_SIM_TRACE_PATH", "").strip()
    if not trace_setting or os.environ.get("MING_SIM_TRACE", "1").strip().lower() in {
        "0", "false", "no",
    }:
        raise RuntimeError("set MING_SIM_TRACE_PATH to a fresh path with CLI tracing enabled")
    trace_path = Path(trace_setting).resolve()
    if trace_path.exists():
        raise RuntimeError(f"CLI trace path must be fresh: {trace_path}")
    return trace_path


def gate_evidence_config(args: Any, cfg: Any) -> Dict[str, Any]:
    """证据 JSON 的 config 块：channel/runner/model 如实（#1256）。"""
    channel = str(getattr(cfg, "channel", "") or getattr(args, "channel", "") or "").strip().lower()
    runner = ""
    if channel == "cli":
        runner = str(
            getattr(cfg, "cli_runner", "") or getattr(args, "runner", "") or ""
        ).strip().lower()
    model = str(
        getattr(cfg, "cli_model", "")
        or getattr(cfg, "model", "")
        or getattr(args, "model", "")
        or ""
    ).strip()
    block: Dict[str, Any] = {
        "channel": channel or "cli",
        "runner": runner,
        "model": model,
        "reasoning_strength": str(getattr(cfg, "reasoning_strength", "") or ""),
    }
    if getattr(cfg, "max_tokens", None) is not None:
        block["max_tokens"] = int(cfg.max_tokens)
    return block
