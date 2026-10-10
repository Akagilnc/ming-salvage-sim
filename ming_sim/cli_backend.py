"""本地 CLI LLM 后端：用已支持的本机 agent runner 调用 LLM，脱离 api key。

探针目标：把游戏 LLM 后端从「api key 调远端」换成「本地自治 CLI agent」。
做法 = 继承 agno 的 OpenAIChat，只覆盖最底层 invoke：
不发 HTTP，改 subprocess 调 agy，把文本输出包成假 ChatCompletion，
交回 agno 原生 _parse_provider_response 解析。agno 全套（解析/流式回退/
消息格式）原样复用，零 function-calling（工具不传，大臣退化成纯文本进谏）。

启用：环境变量 MING_SIM_LLM_BACKEND=<runner>。
机器依赖：本机已安装并登录所选 runner。不兼容别的机器——
这是探针的预期，不是缺陷。

调用约定来自 wiki/concepts/codex-bot-conventions.md + cross-model-review.md：
- agy：先暖 keychain（auth 是 race），Agy 1.2.0 用 `--print=<prompt>`。
- codex：`codex exec -` 必须 stdin pipe，绝不 positional；始终 2>&1。
"""

from __future__ import annotations

import codecs
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple, Type, Union

from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.models.response import ModelResponse
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from pydantic import BaseModel

# CLI runner 默认模型单一真源在 models（L0 叶子），此处 re-export 保留
# `from ming_sim.cli_backend import CODEX_DEFAULT_MODEL` 既有路径（#60）。
from ming_sim.models import CODEX_DEFAULT_MODEL, CLAUDE_DEFAULT_MODEL, LLMConfig
from ming_sim.decree_vocabulary import DIRECTIVE_ACTION_TYPES
from ming_sim.structured_decree import (
    StructuredDecreeCombinationError,
    apply_assembled_to_payload,
    assemble_structured_decree,
    combination_correction_feedback,
    expand_combo_failed_fields,
    structured_decree_prompt_contract,
    validate_structured_decree_combination,
)
from ming_sim.participant_roster import (
    BARE_INSTITUTION_PARTICIPANT_NAMES as _BARE_INSTITUTION_PARTICIPANT_NAMES,
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
_CURSOR_BIN = os.environ.get("MING_SIM_CURSOR_BIN", "cursor-agent")
_KIMI_BIN = os.environ.get("MING_SIM_KIMI_BIN", "kimi")
_GROK_BIN = os.environ.get("MING_SIM_GROK_BIN", "grok")
_PI_BIN = os.environ.get("MING_SIM_PI_BIN", "pi")
# 受支持 CLI runner 单一真源（membership + 文案 + env 回落共用）。
_CLI_BACKENDS = frozenset({"agy", "codex", "claude", "cursor", "kimi", "grok", "pi"})
_MATERIALS_CLI_RUNNERS = _CLI_BACKENDS
# 闸脚本 --runner choices 与公开支持集同源。
GATE_CLI_RUNNERS = ("codex", "claude", "cursor", "kimi", "grok", "pi")
# 前端 CLI Runner 下拉稳定 UI 顺序；membership 仍以 _CLI_BACKENDS 为唯一准入（#1274 W1）。
# GATE_CLI_RUNNERS ⊂ 此序（无 agy）；禁在 menuPage/gameMenu 再硬编一份。
# #1274-qa-y1：pi 紧随 grok（UI_ORDER∩_CLI_BACKENDS → cli_runner_choices 自动带出）。
_CLI_RUNNER_UI_ORDER = ("agy", "codex", "claude", "cursor", "kimi", "grok", "pi")
_CLI_RUNNER_LABELS = {"agy": "agy（Gemini）"}
# 实际消费 --model / cli_model 的 runner（describe_effective_model 用）；agy 走自身 ladder。
_CLI_MODEL_RUNNERS = frozenset({"codex", "claude", "cursor", "kimi", "grok", "pi"})
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
# pi CLI --thinking：off/minimal/low/medium/high/xhigh/max（pi --help 实测）；
# 抽象 off/low/medium/high 与 pi 同名档直传（亦支持 --model provider/id:<thinking> 后缀）。
_PI_THINKING_BY_STRENGTH = {
    "off": "off",
    "low": "low",
    "medium": "medium",
    "high": "high",
}
# 支持 reasoning_strength 传输的 CLI runner 单源（#1271/#1274-y1）：与上方 *_BY_STRENGTH
# 表同缝。有传输表 = 支持；kimi/cursor 无独立档位旗，不入此集（另票/庭裁）。
# 导出 frozenset——llm_config 谓词与 web payload 均消费此名，禁第二处手写名单。
CLI_REASONING_STRENGTH_RUNNERS = frozenset({"codex", "claude", "grok", "pi"})


def cli_runner_choices() -> List[Dict[str, str]]:
    """前端「CLI Runner」下拉的单一真源（有序 {value,label}）。

    membership = _CLI_BACKENDS；顺序 = _CLI_RUNNER_UI_ORDER。menuPage / gameMenu
    经 config 端点共吃此清单，禁各自硬编码 option（#1274 W1 防单页漏更）。
    每次返回独立副本。"""
    return [
        {"value": name, "label": _CLI_RUNNER_LABELS.get(name, name)}
        for name in _CLI_RUNNER_UI_ORDER
        if name in _CLI_BACKENDS
    ]


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
        # agy：模型档由 CLI 自身选择，只提供默认逃生档。
        "agy": [{"value": "", "label": "默认 · gemini"}],
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
        # 尚无策展模型档的 runner 保留 CLI 自身默认。
        "cursor": [{"value": "", "label": "默认"}],
        "kimi": [{"value": "", "label": "默认"}],
        "grok": [{"value": "", "label": "默认"}],
        "pi": [{"value": "", "label": "默认"}],
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
        logger.exception("login shell PATH discovery failed")
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


logger = logging.getLogger(__name__)


def _log(msg: str) -> None:
    if _VERBOSE:
        print(f"[cli_backend] {msg}", flush=True)


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
    except Exception:  # trace 永不应中断游戏，但必须留真因（ADR 0005）
        logger.exception("LLM trace write failed path=%s", _TRACE_PATH)


def _warm_keychain() -> None:
    """暖 macOS keychain 路径，缓解 agy headless auth 的 1s race（见 wiki）。"""
    try:
        subprocess.run(
            ["security", "find-generic-password", "-s", "Antigravity Safe Storage"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
        )
    except Exception:
        logger.exception("keychain warm failed")


# CLI 子进程读循环轮询步长（秒）：只决定「多快发现静默/退出」，不是任何超时预算。
_CLI_POLL_SECONDS = 0.05


def _cli_process_clock() -> float:
    """CLI 增量读循环的取时点（受控推进用；生产恒 time.monotonic）。"""
    return time.monotonic()


@dataclass
class _CliProcessOutcome:
    """子进程收尾事实（退出码 / stderr 诊断 / stdin·管道·终止错），由增量读循环回填。"""

    returncode: Optional[int] = None
    stderr: str = ""
    stdin_error: Optional[BaseException] = None
    stream_error: Optional[BaseException] = None
    terminate_error: Optional[BaseException] = None


def _cli_idle_seconds() -> float:
    """CLI 子进程静默预算：只认 transport 策略 idle（与召对、API 同一权威）。

    该阈值来自设置页那一格（runtime 档 cli.timeout_seconds），经
    resolve_transport_policy 解析（#1465 切片③ owner 2026-09-07）。它说的是「多久
    没有新字节才判这次调用已死」，不是 attempt 总墙钟。
    """
    from ming_sim.llm_transport import resolve_transport_policy

    return float(resolve_transport_policy().idle_timeout_seconds)


def _terminate_cli_process(proc: Any, *, outcome: Optional[_CliProcessOutcome] = None) -> None:
    """收尾子进程：已退时 no-op；否则只 terminate + 有界 wait。

    禁 SIGKILL 升级（共享硬规 #9 / #1834 F47）。终止真异常记入 outcome，
    交调用方响亮失败（#1834 F48），不在此处吞掉。
    """
    if getattr(proc, "poll", lambda: None)() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception as exc:
        # 终止真异常必须留痕；调用方是否另有 stream/stdin 错，不得吞掉本因（F48）。
        logger.warning("CLI 子进程终止失败：%s", exc)
        if outcome is not None:
            if outcome.terminate_error is None:
                outcome.terminate_error = exc
            return
        raise


def _iter_cli_process_lines(
    cmd: List[str],
    *,
    stdin_text: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[str] = None,
    clock: Optional[Callable[[], float]] = None,
    outcome: Optional[_CliProcessOutcome] = None,
) -> Iterator[str]:
    """CLI 子进程增量读单真源：一次子进程 = 一次 attempt，按到达顺序 yield stdout 行。

    - 新字节即活动，刷新活动时刻；静默 ≥ idle 预算 → TransportIdleTimeout（可重试）
      并 terminate 该子进程（空转判据走 llm_transport.check_idle_budget，禁平行实现）。
    - idle 只认 transport 策略（`_cli_idle_seconds`）= 设置页那一格的静默判死阈值。
    - **不设 attempt 总墙钟（宪法 #9）**：只要还有新字节，跨 300s 也不杀；收尾禁 SIGKILL。
    - stderr 并发抽干：否则 codex 等把 stderr 写满 OS pipe 会反压死 stdout。
    - stdin 另起线程喂：大 prompt 超 pipe 缓冲时不与读 stdout 互锁。
    - 活动期 stdout/stderr 真异常与终止真异常记入 outcome，调用方响亮失败（#1834 F48）。
    所有 runner 共用本读法；禁各自复制一套 idle 循环。clock 可注入（受控推进）。
    """
    from ming_sim.llm_transport import TransportPolicy, check_idle_budget

    policy = TransportPolicy(
        idle_timeout_seconds=_cli_idle_seconds(),
    )
    tick = clock or _cli_process_clock
    result = outcome if outcome is not None else _CliProcessOutcome()
    # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit,python.lang.security.audit.dangerous-subprocess-use-tainted-env-args
    # 安全审计(Sourcery):list-form argv、无 shell=True → 不经 shell 解析,无注入面。
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if stdin_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd or _AGY_CWD,
        env=env,
    )
    chunks: "queue.Queue[Tuple[str, Optional[bytes]]]" = queue.Queue()
    stderr_parts: List[str] = []
    workers: List[threading.Thread] = []
    # 收尾开始后管道关闭属正常；活动期读错必须落 outcome（#1834 F48）。
    shutting_down = threading.Event()

    def _read_chunk(stream: Any) -> bytes:
        # read1：已到达的字节立刻交付，不要求凑成一行。无 read1 时退到 read。
        read1 = getattr(stream, "read1", None)
        raw = read1(4096) if callable(read1) else stream.read(4096)
        if not raw:
            return b""
        if isinstance(raw, str):
            return raw.encode("utf-8")
        return bytes(raw)

    def _pump(stream: Any, kind: str) -> None:
        try:
            while True:
                chunk = _read_chunk(stream)
                if not chunk:
                    break
                chunks.put((kind, chunk))
        except Exception as exc:
            # 正常关流契约例外：仅收尾中的管道关闭形状（OSError/ValueError）。
            # shutting_down 只证明进入 finally，不是任意 Exception 的正常化凭据（#1834 F48）；
            # RuntimeError/TypeError 等未知代码故障无论阶段都记 stream_error。
            normal_close = shutting_down.is_set() and isinstance(exc, (OSError, ValueError))
            if normal_close:
                logger.debug("CLI %s 管道读中断（收尾关流）：%s", kind, exc)
            else:
                if result.stream_error is None:
                    result.stream_error = exc
                logger.warning("CLI %s 管道读失败：%s", kind, exc)
        finally:
            # 哨兵必发：否则读循环等不到 EOF，会把收尾误当静默。
            chunks.put((kind, None))

    def _feed_stdin() -> None:
        try:
            payload: Any = stdin_text
            if isinstance(payload, str):
                payload = payload.encode("utf-8")
            proc.stdin.write(payload)
            proc.stdin.close()
        except Exception as exc:
            # 写失败 = 子进程根本没拿到 prompt。任何真异常都记 outcome，禁逃线程
            # excepthook 后主路仍成功（#1834 F48）；OSError/ValueError 既有响亮路径保留。
            result.stdin_error = exc
            logger.warning("CLI stdin 写入失败（prompt 未送达子进程）：%s", exc)

    open_streams = 0
    for stream, kind in ((proc.stdout, "out"), (proc.stderr, "err")):
        if stream is None:
            continue
        open_streams += 1
        worker = threading.Thread(target=_pump, args=(stream, kind), daemon=True)
        worker.start()
        workers.append(worker)
    if stdin_text is not None and proc.stdin is not None:
        feeder = threading.Thread(target=_feed_stdin, daemon=True)
        feeder.start()
        workers.append(feeder)

    last_activity = tick()
    decoders = {
        "out": codecs.getincrementaldecoder("utf-8")("replace"),
        "err": codecs.getincrementaldecoder("utf-8")("replace"),
    }
    def _activity_fault() -> Optional[BaseException]:
        # 活动期已识别故障：stdin/管道任一即可结束等待，禁再走 idle 重试（F48）。
        return result.stdin_error or result.stream_error

    pending_out = ""
    try:
        while open_streams > 0:
            if _activity_fault() is not None:
                break
            try:
                kind, chunk = chunks.get(timeout=_CLI_POLL_SECONDS)
            except queue.Empty:
                if _activity_fault() is not None:
                    break
                check_idle_budget(
                    last_activity_at=last_activity, policy=policy, clock=tick,
                )
                continue
            if chunk is None:
                open_streams -= 1
                tail = decoders[kind].decode(b"", final=True)
                if kind == "err":
                    if tail:
                        stderr_parts.append(tail)
                else:
                    leftover = pending_out + tail
                    pending_out = ""
                    if leftover:
                        yield leftover
                continue
            # 任意新字节即活动（票面「CLI stdout 新字节」）；不要求凑成一行。
            last_activity = tick()
            text = decoders[kind].decode(chunk)
            if kind == "err":
                stderr_parts.append(text)
                continue
            pending_out += text
            while True:
                nl = pending_out.find("\n")
                if nl < 0:
                    break
                line, pending_out = pending_out[: nl + 1], pending_out[nl + 1 :]
                yield line
        # 管道已 EOF 但进程未退：静默同样计入 idle 预算，仍无总墙钟。
        # 已有活动期故障则直接收尾上抛，不把后续 idle/零退出洗成可重试成功。
        while proc.poll() is None and _activity_fault() is None:
            check_idle_budget(
                last_activity_at=last_activity, policy=policy, clock=tick,
            )
            time.sleep(_CLI_POLL_SECONDS)
    finally:
        # 收尾接缝在「任何离开路径」执行：stdin/stream/terminate 一并消费。
        # 并存故障全部留痕；主因上抛，其余不得只停在无人读的字段（#1834 F48）。
        shutting_down.set()
        _terminate_cli_process(proc, outcome=result)
        for worker in workers:
            worker.join(timeout=5)
        result.stderr = "".join(stderr_parts)
        result.returncode = proc.poll()
        fault_parts: List[Tuple[str, BaseException]] = []
        if result.stdin_error is not None:
            fault_parts.append(("stdin 写入", result.stdin_error))
        if result.stream_error is not None:
            fault_parts.append(("管道读", result.stream_error))
        if result.terminate_error is not None:
            fault_parts.append(("子进程终止", result.terminate_error))
        if fault_parts:
            for label, exc in fault_parts[1:]:
                logger.warning("CLI 并存故障（%s）：%s", label, exc)
            label, fault = fault_parts[0]
            raise RuntimeError(f"CLI {label}失败：{fault}") from fault

def _codex_reasoning_effort(reasoning_strength: Optional[str]) -> str:
    if reasoning_strength is None:
        return (os.environ.get("MING_SIM_CODEX_REASONING") or "").strip()
    return _CODEX_REASONING_BY_STRENGTH.get(str(reasoning_strength or "").strip().lower(), "")


def _codex_cmd(
    model: Optional[str] = None,
    *,
    json_events: bool = False,
    reasoning_strength: Optional[str] = None,
    materials_dir: Optional[str] = None,
) -> List[str]:
    cmd = [_resolve_cli_bin("codex", _CODEX_BIN), "exec", "--model", (model or _CODEX_MODEL)]
    reasoning = _codex_reasoning_effort(reasoning_strength)
    if reasoning:
        cmd += ["-c", f'model_reasoning_effort="{reasoning}"']
    if json_events:
        cmd.append("--json")
    cmd += ["--ephemeral", "--skip-git-repo-check"]
    if materials_dir:
        cmd += ["--ignore-user-config", "--sandbox", "read-only"]
    cmd.append("-")
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


def _grok_effort(reasoning_strength: Optional[str]) -> Optional[str]:
    strength = str(reasoning_strength or "").strip().lower()
    return _GROK_EFFORT_BY_STRENGTH.get(strength)


def _pi_thinking(reasoning_strength: Optional[str]) -> Optional[str]:
    strength = str(reasoning_strength or "").strip().lower()
    return _PI_THINKING_BY_STRENGTH.get(strength)


def _cli_runner_command(
    runner: str,
    prompt: str,
    *,
    model: Optional[str] = None,
    reasoning_strength: Optional[str] = None,
    json_events: bool = False,
    materials_dir: Optional[str] = None,
    kimi_agent_file: Optional[str] = None,
) -> Tuple[List[str], Optional[str], Optional[Dict[str, str]]]:
    """runner → (argv, stdin 文本, env)。各 runner 调用约定单真源；执行读法共用 helper。

    实测约定（docs/LLM_BACKEND_BENCH.md §9 / #1256 / #1274-qa-y1）：
    - agy 1.2.0：`--print=<prompt>` 单参数；调用前先暖 keychain（auth race）。
    - codex：`exec -` 必须 stdin pipe（绝不 positional）；`--skip-git-repo-check`
      （沙箱 cwd 非 git）+ `--ephemeral`（并发不撞共享 session）；干净回话在 stdout。
    - claude：`-p --output-format text`，prompt 走 stdin；thinking 预算走 env。
    - cursor / kimi / grok / pi：prompt 走参数（无 stdin 约定），干净答案在 stdout。
    材料目录（#1830 / #1827）：cwd 指向目录；各 runner 只开放读取面或由 prompt
    明确约束只读。Agy 不另建强沙箱，也不写用户 settings。
    """
    if materials_dir and runner not in _MATERIALS_CLI_RUNNERS:
        raise RuntimeError(f"runner 不支持材料目录：{runner}")
    if runner == "agy":
        return [_resolve_cli_bin("agy", _AGY_BIN), f"--print={prompt}"], None, None
    if runner == "codex":
        cmd = _codex_cmd(
            model, json_events=json_events, reasoning_strength=reasoning_strength,
            materials_dir=materials_dir,
        )
        return cmd, prompt, None
    if runner == "claude":
        cmd = [
            _resolve_cli_bin("claude", _CLAUDE_BIN), "-p",
            "--model", (model or _CLAUDE_MODEL),
            "--output-format", "text",
        ]
        if materials_dir:
            # Single native isolation group (verified on host Claude):
            # --restricted ignores user/project/local settings, drops command
            # tools, and confines file tools to cwd; empty mcpServers + strict
            # blocks foreign MCP. Do not use --bare here — it skips keychain auth.
            cmd += [
                "--restricted",
                "--strict-mcp-config",
                "--mcp-config", '{"mcpServers":{}}',
                "--allowedTools", "Read", "Glob", "Grep",
                "--permission-mode", "dontAsk",
            ]
        else:
            cmd += ["--disallowed-tools", *_CLAUDE_DISALLOWED]
        env = None
        if reasoning_strength is not None:
            env = dict(os.environ)
            tokens = _CLAUDE_THINKING_TOKENS_BY_STRENGTH.get(
                str(reasoning_strength or "").strip().lower()
            )
            if tokens:
                env["MAX_THINKING_TOKENS"] = tokens
            else:
                env.pop("MAX_THINKING_TOKENS", None)
        return cmd, prompt, env
    if runner == "cursor":
        cmd = [
            _resolve_cli_bin("cursor", _CURSOR_BIN),
            "-p", "--output-format", "text", "--trust",
        ]
        if materials_dir:
            cmd += ["--mode", "ask", "--sandbox", "enabled"]
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)
        return cmd, None, None
    if runner == "kimi":
        # -p 单用：本机 kimi 0.36.1 实测与 --yolo/--auto 组合会被 parse 拒收。
        cmd = [_resolve_cli_bin("kimi", _KIMI_BIN), "-p", prompt,
               "--output-format", "text"]
        if materials_dir and kimi_agent_file:
            cmd += ["--agent-file", kimi_agent_file]
        if model:
            cmd.extend(["-m", model])
        return cmd, None, None
    if runner == "grok":
        cmd = [_resolve_cli_bin("grok", _GROK_BIN), "-p", prompt,
               "--output-format", "plain"]
        if materials_dir:
            cmd += ["--tools", "Read,Glob,Grep", "--sandbox", "read-only",
                    "--permission-mode", "dontAsk", "--disable-web-search",
                    "--no-subagents"]
        if model:
            cmd.extend(["-m", model])
        effort = _grok_effort(reasoning_strength)
        if effort:
            cmd.extend(["--effort", effort])
        return cmd, None, None
    if runner == "pi":
        # --no-tools：游戏/玩家文本不可注入驱动内置 read/bash/edit/write（#1456）。
        cmd = [_resolve_cli_bin("pi", _PI_BIN), "-p", "--mode", "text", "--no-tools"]
        if materials_dir:
            cmd += ["--tools", "read,grep,find,ls", "--no-session",
                    "--no-extensions", "--no-skills", "--no-prompt-templates",
                    "--no-themes", "--no-context-files", "--no-approve"]
        if model:
            cmd.extend(["--model", model])
        thinking = _pi_thinking(reasoning_strength)
        if thinking is not None:
            cmd.extend(["--thinking", thinking])
        cmd.append(prompt)
        return cmd, None, None
    raise RuntimeError(f"未知 CLI backend：{runner}")


def _iter_cli_runner_text(
    runner: str,
    prompt: str,
    *,
    model: Optional[str] = None,
    reasoning_strength: Optional[str] = None,
    json_events: bool = False,
    clock: Optional[Callable[[], float]] = None,
    materials_dir: Optional[str] = None,
) -> Iterator[str]:
    """跑一次 runner 子进程，产出该次 attempt 的文本。**一次子进程 = 一次 attempt**。

    **活动信号与 content 解耦**：新字节刷新空转时刻是 `_iter_cli_process_lines`
    的事（读到就刷新，跨多久都不杀）；本函数只在该次 attempt 判活之后才把文本交
    出去。故纯文本 runner（agy/claude/pi）**不逐行外抛 stdout**——终包判活前
    不把半截 stdout 当大臣正文送进 delta。终失败按票面走系统层人话（ADR 0046
    否决失败戏内化）。codex `--json` 是结构化事件流（`_codex_event_text` 认字段、
    不读散文，ADR 0142），可照旧边到边出。

    次数只在 llm_transport（run_with_transport / run_transport_stream）；此处禁
    私有 for-attempt 循环。失败按 typed 分类抛，交上层统一重试或终结：
    - 静默超阈值 → TransportIdleTimeout（可重试；_iter_cli_process_lines 抛）
    - 空输出 → llm_empty_output（可重试）
    - stdin 未送达 / 未知非零退出 → RuntimeError（确定性失败，一次不重试；禁从
      成功正文或 stderr 散文抠认证/连接状态）

    静默预算只认 transport 策略 idle（= 设置页那一格的静默判死阈值，CLI 与 API 同权威）。
    """
    from ming_sim.llm_transport import empty_output_failure, transport_failure_unavailable

    if runner == "agy":
        _warm_keychain()  # 操作步骤（缓解 headless auth race），不是重试策略
    kimi_agent_path: Optional[str] = None
    if materials_dir and runner == "kimi":
        handle = tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False)
        try:
            handle.write("---\nname: ming-material-reader\ntools:\n  - Read\n  - Grep\n  - Glob\n---\nRead-only material reviewer. Never write or execute commands.\n")
        finally:
            handle.close()
        kimi_agent_path = handle.name
    try:
        cmd, stdin_text, env = _cli_runner_command(
            runner, prompt, model=model, reasoning_strength=reasoning_strength,
            json_events=json_events, materials_dir=materials_dir,
            kimi_agent_file=kimi_agent_path,
        )
        outcome = _CliProcessOutcome()
        pieces: List[str] = []
        final_text = ""
        for line in _iter_cli_process_lines(
                cmd, stdin_text=stdin_text, env=env,
                cwd=(str(Path(materials_dir).resolve()) if materials_dir else None),
                clock=clock, outcome=outcome,
            ):
            if json_events:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    obj = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                delta = _codex_event_text(obj)
                if delta:
                    pieces.append(delta)
                    # 已确认 stdin 写失败则不再放产出；半流不回卷、不另造缓冲。
                    if outcome.stdin_error is None:
                        yield delta
                    continue
                maybe_final = _codex_final_text(obj)
                if maybe_final:
                    final_text = maybe_final
                continue
            # 纯文本 runner：只入缓冲刷新活动，判活前不外抛（见 docstring）。
            pieces.append(line)
        returncode = int(outcome.returncode or 0)
        stderr = outcome.stderr or ""
        stdout_text = "".join(pieces)
        # stdin/stream/terminate 最终故障只由 _iter_cli_process_lines finally 消费
        # （#1834 F48）；此处不复制第二份判定。途中 json 放流仍看 stdin_error 停供。
        # #1834 F16/F26/F27 / ADR 0142 / #671：
        # - 成功正文保原文；strip 只作判空副本
        # - 不从正文词表猜认证/连接故障
        # - 不从 stderr/横幅猜最终正文；只认 stdout 或结构化终包
        if stdout_text.strip():
            text = stdout_text
        elif final_text.strip():
            text = final_text
        else:
            text = ""
        # 非零退出不洗成瞬断：无 typed status 的失败当确定性失败（#1780 / ADR 0142）。
        if returncode != 0:
            raise RuntimeError(f"{runner} 调用失败（退出码 {returncode}）：{stderr[:200]}")
        if not text.strip():
            raise transport_failure_unavailable(
                empty_output_failure(), attempts=1, exhausted=False,
            )
        # 判活之后才交文本：json 事件流已边到边出过，只补终包兜底；纯文本一次交全。
        if not json_events:
            yield text
        elif not pieces and final_text.strip():
            yield final_text
    finally:
        if kimi_agent_path:
            try:
                os.unlink(kimi_agent_path)
            except FileNotFoundError:
                pass

def _run_cli_runner(
    runner: str,
    prompt: str,
    *,
    model: Optional[str] = None,
    reasoning_strength: Optional[str] = None,
    materials_dir: Optional[str] = None,
) -> Tuple[str, int]:
    """非流路径：读完整文再返回（内部仍增量读，只是不对外 yield）。

    返回 (文本, 1)：一次子进程 = 一次 attempt，次数账归 llm_transport。
    """
    text = "".join(
        _iter_cli_runner_text(
            runner, prompt, model=model,
            reasoning_strength=reasoning_strength,
            materials_dir=materials_dir,
        )
    )
    # 正文已在 _iter_cli_runner_text 判活；此处禁二次 strip（#1834 F16）。
    return text, 1


def _run_agy(prompt: str, *, materials_dir: Optional[str] = None) -> Tuple[str, int]:
    """调 agy --print=<prompt> 一次（warm keychain 仍做；重试归 transport）。"""
    return _run_cli_runner("agy", prompt, materials_dir=materials_dir)


def _run_codex(
    prompt: str,
    model: Optional[str] = None,
    reasoning_strength: Optional[str] = None,
    *,
    materials_dir: Optional[str] = None,
) -> Tuple[str, int]:
    """调 codex exec - 一次；干净最终回话在 stdout（不合并 stderr 日志）。"""
    return _run_cli_runner(
        "codex", prompt, model=model,
        reasoning_strength=reasoning_strength,
        materials_dir=materials_dir,
    )


def _run_claude(
    prompt: str,
    model: Optional[str] = None,
    reasoning_strength: Optional[str] = None,
    *,
    materials_dir: Optional[str] = None,
) -> Tuple[str, int]:
    """调 claude -p 一次；干净回话在 stdout，thinking 预算经 env 显式设置。"""
    return _run_cli_runner(
        "claude", prompt, model=model,
        reasoning_strength=reasoning_strength,
        materials_dir=materials_dir,
    )


def _run_cursor(
    prompt: str,
    model: Optional[str] = None,
    reasoning_strength: Optional[str] = None,  # noqa: ARG001 — 签名对齐；cursor 无 effort 档
    *,
    materials_dir: Optional[str] = None,
) -> Tuple[str, int]:
    """调 cursor-agent -p 一次（#1256）。"""
    return _run_cli_runner("cursor", prompt, model=model, materials_dir=materials_dir)


def _run_kimi(
    prompt: str,
    model: Optional[str] = None,
    reasoning_strength: Optional[str] = None,  # noqa: ARG001 — 签名对齐；kimi -p 无 effort 档
    *,
    materials_dir: Optional[str] = None,
) -> Tuple[str, int]:
    """调 kimi -p 一次（#1256）。"""
    return _run_cli_runner("kimi", prompt, model=model, materials_dir=materials_dir)


def _run_grok(
    prompt: str,
    model: Optional[str] = None,
    reasoning_strength: Optional[str] = None,
    *,
    materials_dir: Optional[str] = None,
) -> Tuple[str, int]:
    """调 Grok Build CLI 一次（#1256；--effort 仅 low/med/high）。"""
    return _run_cli_runner(
        "grok", prompt, model=model,
        reasoning_strength=reasoning_strength,
        materials_dir=materials_dir,
    )


def _run_pi(
    prompt: str,
    model: Optional[str] = None,
    reasoning_strength: Optional[str] = None,
    *,
    materials_dir: Optional[str] = None,
) -> Tuple[str, int]:
    """调本机 pi CLI 一次性非交互出文（#1274-qa-y1）。"""
    return _run_cli_runner(
        "pi", prompt, model=model,
        reasoning_strength=reasoning_strength,
        materials_dir=materials_dir,
    )


def _dispatch_cli_runner(
    runner: str,
    prompt: str,
    *,
    model: Optional[str] = None,
    reasoning_strength: Optional[str] = None,
    materials_dir: Optional[str] = None,
) -> Tuple[str, int]:
    """runner 名 → 该 runner 的单次调用入口。全仓唯一一处 runner 分派链
    （env 分派 / config 分派 / CliChat 分派共用，禁再复制第二份）。"""
    extra = {"materials_dir": materials_dir} if materials_dir else {}
    if runner == "codex":
        return _run_codex(prompt, model=model,
                          reasoning_strength=reasoning_strength, **extra)
    if runner == "claude":
        return _run_claude(prompt, model=model,
                           reasoning_strength=reasoning_strength, **extra)
    if runner == "cursor":
        return _run_cursor(prompt, model=model,
                           reasoning_strength=reasoning_strength, **extra)
    if runner == "kimi":
        return _run_kimi(prompt, model=model,
                         reasoning_strength=reasoning_strength, **extra)
    if runner == "grok":
        return _run_grok(prompt, model=model,
                         reasoning_strength=reasoning_strength, **extra)
    if runner == "pi":
        return _run_pi(prompt, model=model,
                       reasoning_strength=reasoning_strength, **extra)
    if runner == "agy":
        # agy 忽略 --model（走自身 ladder），不给它挂不被消费的 model。
        return _run_agy(prompt, **extra)
    raise RuntimeError(f"未知 CLI backend：{runner}")


def _run_backend(prompt: str) -> Tuple[str, int]:
    """按 MING_SIM_LLM_BACKEND 分派到对应 CLI（enrich/secret 等非 CliChat 路径用）。
    未设或非法时沿用默认 Agy。"""
    return _dispatch_cli_runner(cli_backend_from_env() or "agy", prompt)


def _llm_channel(llm_config: Any = None) -> str:
    return (getattr(llm_config, "channel", "") or "").strip().lower()


def _cli_config_parts(llm_config: Any = None) -> Optional[Tuple[str, str, str]]:
    """CLI 通道的分派要素：runner / model / 推理档。

    不含超时：等多久算死是 transport 策略的事（设置页那一格的静默判死阈值，
    `_cli_idle_seconds`），不再逐调用透传（#1465 切片③）。
    """
    channel = _llm_channel(llm_config)
    if channel != "cli":
        return None
    runner = (getattr(llm_config, "cli_runner", "") or cli_backend_from_env() or "agy").strip().lower()
    if runner not in _CLI_BACKENDS:
        raise RuntimeError(f"未知 CLI backend：{runner}")
    model = (getattr(llm_config, "cli_model", "") or "").strip()
    reasoning_strength = str(getattr(llm_config, "reasoning_strength", "") or "").strip().lower()
    return runner, model, reasoning_strength


def _run_backend_for_config(
    prompt: str, llm_config: Any = None, tag: str = "", *, policy=None,
) -> Tuple[str, int]:
    """runtime CLI 配置优先；没有显式 CLI channel 时保持旧 env/default 行为。

    直接编程路径（职官分类/各 extractor/国策补全/连通性 verify）的唯一咽喉：
    每次调用 try/finally 写一条 trace，谁调都记，不靠各调用方自觉手写。
    （agno 游戏路径走 CliChat.invoke 自有 trace，与此咽喉不重叠。）
    tag 空时记 other；由调用方显式申报，不从自由 prompt 猜身份。

    #1465 切片③：本入口是结算/拟旨等非 Agent CLI extractor 的**次数入口**——
    在此包一次 run_with_transport，operation 调单次子进程；runner 内禁私有重试。"""
    from ming_sim.llm_transport import resolve_transport_policy, run_with_transport

    if _llm_channel(llm_config) == "api":
        raise RuntimeError("显式 API channel 未启用本地 CLI backend")
    parts = _cli_config_parts(llm_config)
    model_id = (parts[1] if parts else "") or _backend_label(llm_config)
    t0 = time.monotonic()
    text, attempts, error = "", 0, None

    def _one_call() -> str:
        if parts is None:
            return _run_backend(prompt)[0]
        runner, model, reasoning_strength = parts
        return _dispatch_cli_runner(
            runner, prompt,
            model=model or None,
            reasoning_strength=reasoning_strength or None,
        )[0]

    try:
        text, attempt_records = run_with_transport(
            _one_call, policy=policy or resolve_transport_policy(),
        )
        attempts = len(attempt_records)
        return text, attempts
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        _trace({
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "seq": -1, "tag": tag or "other",
            "backend": _backend_label(llm_config), "model_id": model_id,
            "dur_s": round(time.monotonic() - t0, 1), "attempts": attempts,
            "wants_json": False,
            "prompt_chars": len(prompt), "resp_chars": len(text),
            "error": error, "prompt": prompt, "response": text,
        })


def _run_api_for_config(
    prompt: str,
    llm_config: Any = None,
    tag: str = "",
    *,
    force_json_output: bool = True,
    temperature: float = 0,
    instructions: Optional[List[str]] = None,
    policy=None,
) -> Tuple[str, int]:
    """API 通道小调用。JSON 抽取默认 force_json；玩家产文传 force_json_output=False（0033）。"""
    from agno.agent import Agent
    from ming_sim.llm_model import create_chat_model, extract_agent_text

    if instructions is None:
        instructions = (
            ["只输出符合要求的 JSON/文本，不要 markdown 代码围栏。"]
            if force_json_output
            else []
        )
    kind = "extractor" if force_json_output else "prose"
    agent = Agent(
        name=f"API{kind}-{tag or 'generic'}",
        id=f"api-{kind}-{tag or 'generic'}",
        session_id=f"api-{kind}-{tag or 'generic'}",
        model=create_chat_model(
            llm_config,
            temperature=temperature,
            force_json_output=force_json_output,
        ),
        instructions=list(instructions),
        markdown=False,
    )
    if policy is None:
        return extract_agent_text(agent.run(prompt)), 1
    from ming_sim.llm_transport import bind_transport_sdk_budget, run_with_transport

    with bind_transport_sdk_budget(agent.model, policy):
        text, attempts = run_with_transport(
            lambda: extract_agent_text(agent.run(prompt)), policy=policy,
        )
    return text, len(attempts)


def _run_json_extractor_for_config(
    prompt: str, llm_config: Any = None, tag: str = "", *, policy=None,
) -> Tuple[str, int]:
    if _llm_channel(llm_config) == "api":
        return _run_api_for_config(prompt, llm_config, tag=tag, policy=policy)
    return _run_backend_for_config(prompt, llm_config, tag=tag, policy=policy)


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


def _messages_to_prompt(
    messages: List[Message],
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    *,
    materials_dir: Optional[str] = None,
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
    if materials_dir:
        prompt += (
            "\n\n【材料】你的材料在当前目录。根目录 INDEX 一行一项。想读哪份自己读。"
            "禁止读取当前材料目录之外的任何内容；不得写入、修改或创建任何文件。"
            "直接以你所扮演的角色身份，用**中文**给出最终回答。"
        )
    else:
        prompt += (
            "\n\n【执行约束·必读】你**没有**任何文件、目录、数据库、代码、工具或命令可用，也不要去找。"
            "不要描述你打算做什么（如『I will list…』『让我查一下…』）、不要提及 workspace/文件/目录/data/源码/state query 之类。"
            "直接以你所扮演的角色身份，用**中文**给出最终回答；禁止英文，禁止任何旁白或思考过程。"
        )
    return prompt


# ── 拟旨 / 下密令入档（CLI 后端）────────────────────────────────────────
# 原版（api key）靠 agno 工具 propose_directive/secret_order，模型 function-call 触发。
# agy/codex/claude 不做 function-calling，唯一缺口在此。玩家用「拟旨/下密令」按钮 =
# 消息带「拟旨如下：/密令如下：」前缀 = 已表态要下旨，据此分派：
#   拟旨：大臣回话原文即这道圣旨草稿，整段入档（单一文本字段，够用；多轮聊出多道 →
#         颁诏时玩家去重）。
#   密令：沿现役声明链（declaration_dispatch）结构化成案；旧 CLI 抽取／拼装／
#         散文解析／落地恢复链已清退（#1897 R1）。候选仍入 pending_actions 确认闸。


# 大臣会话动作抽取（CLI 后端无 function-calling）：
# 不靠关键字白名单（脆、永远漏），交给 LLM 读对话判意图——皇帝本轮对该大臣【现有密令】
# 要做什么（更新内容 / 提交核议 / 催办 / 记进展），以及若是妃嫔有无调教。
# 只在「大臣有 active 密令 或 是妃嫔」时调（省 token）。


def _directive_mode(value: object) -> Optional[str]:
    """Normalize the extractor's typed mode value, never player prose."""
    return {
        "中旨直发": "midzhi",
        "midzhi": "midzhi",
        "普通": "ordinary",
        "ordinary": "ordinary",
    }.get(str(value or "").strip())


def resolve_directive_mode(
    extracted: object = None, existing: object = None,
) -> str:
    """Resolve the typed LLM decision, preserving an existing candidate on edits."""
    for value in (extracted, existing):
        mode = _directive_mode(value)
        if mode is not None:
            return mode
    return "ordinary"


def _draft_intent_character_roster_facts(content: Any) -> str:
    """#1428：把 content.characters 的 name+aliases 编成抽取接地事实块。

    接地=结构化事实注入（ADR 0142）；不在此做散文截断修复/子串归一。
    参与人 character_id 须填规范名；别名仅作识别线索，输出仍归规范名。
    资格与可召面同口径：_is_summonable_court_minister（身份归一∧非宗藩∧非未仕；#1317 r2）。
    无 db 时用 content 静态 power_id（#125 live 翻转不扩）。身份归一另由 _find_existing_minister
    吃（含未仕/宗藩别名）；事实块只供可召朝臣接地，不倾倒待铨诸生。
    """
    characters = getattr(content, "characters", None) if content is not None else None
    if not characters:
        return ""
    from ming_sim.session import _is_summonable_court_minister

    lines: List[str] = []
    for key, ch in characters.items():
        if not _is_summonable_court_minister(ch):
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


def _draft_intent_army_grounding_facts(content: Any) -> str:
    """#1774：把军队身份别名（matching.army_identity_aliases 单源）编成抽取接地事实块。

    与 _draft_intent_character_roster_facts / _pay_order_grounding_facts 同族：
    结构化事实注入（ADR 0142），机面 canonical id 供料合法（ADR 0143）。
    抽取器据此把皇帝的自然说法（「解赴关宁军前」）归一到 @guanning，
    协饷写缝仍走既有 canonical_army_id_exact 精确等值——本块不放宽解析、
    不新增模糊匹配/子串升格，也不把驻地/战区/将领混进身份别名（matching 同规）。
    """
    armies = getattr(content, "armies", None) if content is not None else None
    if not armies:
        return ""
    from ming_sim.matching import army_identity_aliases

    lines: List[str] = []
    for key, army in armies.items():
        army_id = str(getattr(army, "id", None) or key or "").strip()
        if not army_id:
            continue
        name = str(getattr(army, "name", None) or army_id).strip()
        aliases = [
            alias for alias in army_identity_aliases(army)
            if alias not in (army_id, name)
        ]
        head = f"{name}（别名：{'、'.join(aliases)}）" if aliases else name
        lines.append(f"{head}=@{army_id}")
    if not lines:
        return ""
    return (
        "【军队接地事实】协饷旨意的「目标」只填下列 canonical id"
        "（形如 @guanning）；皇帝行文中的军名、别名、军前/所部等说法，"
        "按语义归到所属军的 canonical id；表中无对应之军才留空。\n"
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
    """单条抽取结果中的人物键（character_id + delegator_id/delegator，保序去重）。

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
    return ids


def _known_person_canon(raw: Any, *, db: Any, content: Any) -> Optional[str]:
    """名册内人物 → 规范名；不在册 / 非人 → None。

    与校验缝同口径（_find_existing_minister），禁把生名当合法 prior。
    """
    from ming_sim.session import _find_existing_minister

    cid = str(raw or "").strip()
    if not cid or _is_non_person_participant_name(cid):
        return None
    if content is None or db is None:
        return None
    found = _find_existing_minister(content, cid, db)
    key = str(found or "").strip()
    return key or None


def _roster_dict_entries(roster: Any) -> List[Dict[str, Any]]:
    if not isinstance(roster, list):
        return []
    return [dict(item) for item in roster if isinstance(item, dict)]


def _entry_person_fields(entry: Dict[str, Any]) -> List[tuple[str, str]]:
    """(field, raw_id) for character_id + delegator；保序。"""
    fields: List[tuple[str, str]] = []
    cid = str(entry.get("character_id") or "").strip()
    if cid:
        fields.append(("character_id", cid))
    did = str(
        entry.get("delegator_id") or entry.get("delegator") or ""
    ).strip()
    if did:
        fields.append(("delegator_id", did))
    return fields


def _is_failed_person_slot(raw: Any, *, db: Any, content: Any) -> bool:
    """人物失败槽？normalize 同口径：空/机构/泛称不算；在册人物不算；其余未知人物算。"""
    cid = str(raw or "").strip()
    if not cid or _is_non_person_participant_name(cid):
        return False
    return _known_person_canon(cid, db=db, content=content) is None


def _count_failed_person_slots_in_roster(
    roster: Any, *, db: Any, content: Any,
) -> int:
    n = 0
    for entry in _roster_dict_entries(roster):
        for _field, raw in _entry_person_fields(entry):
            if _is_failed_person_slot(raw, db=db, content=content):
                n += 1
    return n


def _count_failed_person_slots(
    result: Dict[str, Any], *, db: Any, content: Any,
) -> int:
    """首抽结果的人物失败槽数（顶层 roster；机构/泛称排除）。"""
    n = 0
    if "participant_roster" in result:
        n += _count_failed_person_slots_in_roster(
            result.get("participant_roster"), db=db, content=content,
        )
    return n


def _collect_corr_person_ids(roster: Any, *, db: Any, content: Any) -> List[str]:
    """纠错轮 roster 人物规范名（保序，可重复）。"""
    out: List[str] = []
    for entry in _roster_dict_entries(roster):
        for _field, raw in _entry_person_fields(entry):
            known = _known_person_canon(raw, db=db, content=content)
            if known:
                out.append(known)
    return out


def _patch_roster_slots_one_to_one(
    baseline_roster: Any,
    correction_roster: Any,
    *,
    db: Any,
    content: Any,
) -> Optional[List[Any]]:
    """可证明一一对应的结构化槽级修补；对应不明 → None（调用方 escalate）。

    - baseline 形状/顺序/tier/role 冻结
    - 同下标对应：合法槽必须仍是同一人；失败槽取同位置纠错名（须已过结构化人物引用校验）
    - 禁聚合候选池按序回填（增人/重排可静默换人）
    - 纠错新人计入「新人数」，与失败槽数不等 → 不明
    - 多失败槽（含 validator 首错即停只报一个）→ 不明
    - 不把自由正文姓名/别名/前缀子串当身份准入（#1834 F46）
    """
    base_entries = _roster_dict_entries(baseline_roster)
    corr_entries = _roster_dict_entries(correction_roster)
    if not base_entries:
        return []
    # corr 短于 baseline：仅当被截去的尾槽全是机构/空才可（人物槽缺失 → 不明）
    if len(corr_entries) < len(base_entries):
        for entry in base_entries[len(corr_entries):]:
            for _field, raw in _entry_person_fields(entry):
                cid = str(raw or "").strip()
                if cid and not _is_non_person_participant_name(cid):
                    return None

    prior_valid: set[str] = set()
    failed_slots: List[tuple[int, str]] = []  # (entry_idx, field)
    for idx, entry in enumerate(base_entries):
        for field, raw in _entry_person_fields(entry):
            # 机构/泛称：normalize 会丢，不入失败槽、不入 prior_valid
            if not str(raw or "").strip() or _is_non_person_participant_name(raw):
                continue
            known = _known_person_canon(raw, db=db, content=content)
            if known is None:
                failed_slots.append((idx, field))
            else:
                prior_valid.add(known)

    # 本 roster 多未知 → 对应不明（全局闸应已拦；此处保本地不变量）
    if len(failed_slots) > 1:
        return None
    if not failed_slots:
        return [dict(e) for e in base_entries]

    # 纠错轮新人：只认结构化名册引用（_known_person_canon），不扫玩家正文。
    corr_all_ids = _collect_corr_person_ids(corr_entries, db=db, content=content)
    newcomers: List[str] = []
    seen_new: set[str] = set()
    for pid in corr_all_ids:
        if pid in prior_valid or pid in seen_new:
            continue
        seen_new.add(pid)
        newcomers.append(pid)
    if len(newcomers) != len(failed_slots):
        return None

    out: List[Any] = []
    for idx, base_entry in enumerate(base_entries):
        corr_entry = corr_entries[idx] if idx < len(corr_entries) else {}
        entry = dict(base_entry)
        for field, raw in _entry_person_fields(base_entry):
            # 机构/泛称槽：保首抽原值，交 normalize 滤除；不参与同人对应
            if not str(raw or "").strip() or _is_non_person_participant_name(raw):
                continue
            base_known = _known_person_canon(raw, db=db, content=content)
            corr_raw = str(
                corr_entry.get(field)
                or (corr_entry.get("delegator") if field == "delegator_id" else "")
                or ""
            ).strip()
            corr_known = _known_person_canon(corr_raw, db=db, content=content)
            if base_known is None:
                # 失败槽：同位置必须是唯一结构化新人
                if corr_known is None or corr_known not in seen_new:
                    return None
                entry[field] = corr_known
                if field == "delegator_id":
                    entry.pop("delegator", None)
            else:
                # 合法槽：同位置必须仍是同一人（重排 → 不明）
                if corr_known != base_known:
                    return None
                entry[field] = base_known
                if field == "delegator_id":
                    entry.pop("delegator", None)
        out.append(entry)
    # 尾部增人（corr 更长）一律丢弃，不落库、不进池
    return out


def _backfill_healed_participant_refs(
    baseline: Dict[str, Any],
    correction: Dict[str, Any],
    *,
    db: Any,
    content: Any,
) -> Optional[Dict[str, Any]]:
    """首抽权威快照 + 纠错轮一一对应槽级修补；对应不明 → None。

    非参与人字段一律保首抽；纠错轮增人/重排/改档不落库。
    失败槽不变式：顶层 roster 人物失败槽须恰好为 1
    （机构/泛称按 normalize 口径排除）；≠1 → None；唯一失败槽同下标修补。
    人物身份只复用结构化引用校验，不扫自由正文（#1834 F46）。
    """
    # 全局闸：复用 _count_failed_person_slots（禁第三套扫描器）
    if _count_failed_person_slots(baseline, db=db, content=content) != 1:
        return None
    out = dict(baseline)
    base_roster = baseline.get("participant_roster")
    if isinstance(base_roster, list):
        patched = _patch_roster_slots_one_to_one(
            base_roster,
            correction.get("participant_roster"),
            db=db,
            content=content,
        )
        if patched is None:
            return None
        out["participant_roster"] = normalize_draft_person_roster(
            patched, db=db, content=content,
        )
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
    # Roster facts grounding haul: preserve raw when non-empty (#1834 F21).
    raw_facts = "" if roster_facts is None else str(roster_facts)
    facts = raw_facts if raw_facts.strip() else ""
    if facts:
        block += facts if facts.endswith("\n") else facts + "\n"
    return block


def _compose_inworld_fact_report(
    prompt: str,
    *,
    llm_config: Any,
    tag: str,
) -> str:
    """Shared player-lane fact-to-prose call; generated prose is never rewritten.

    #1465 切片③：随手工拟诏 30s 总罩一并删除「剩余预算」墙钟——产文失败仍 typed
    上抛（#1299/#1310 单源），但不再被外层墙截断。
    """
    from ming_sim.exceptions import LLMUnavailable
    from ming_sim.llm_model import cli_runner_unavailable

    def _produce() -> str:
        # 玩家产文：复用 API/CLI 既有接缝；API 关 force_json（0033），不另开平行函数。
        if _llm_channel(llm_config) == "api":
            raw, _ = _run_api_for_config(
                prompt, llm_config, tag=tag,
                force_json_output=False, temperature=0.7, instructions=[],
            )
        else:
            raw, _ = _run_backend_for_config(prompt, llm_config, tag=tag)
        text = str(raw or "")
        # strip 只判空；原文不改写（generated prose is never rewritten）。
        if text.strip():
            return text
        raise cli_runner_unavailable(RuntimeError(f"{tag} 空响"), backend=tag)

    try:
        return _produce()
    except LLMUnavailable:
        raise
    except Exception as exc:
        _log(f"{tag} 产文失败：{exc}")
        raise cli_runner_unavailable(exc, backend=tag) from exc


def compose_unknown_participant_inworld_report(
    names: Optional[List[str]] = None,
    *,
    voice: str = "tongzheng",
    speaker_name: str = "",
    speaker_role: str = "",
    llm_config: Any = None,
) -> str:
    """P7：把查无此人事实喂给 LLM，产大臣/通政司口吻回禀；禁模板当台词。

    产文失败 → typed LLMUnavailable（#1299/#1310/#1452
    失败单源 CLI_RUNNER_PLAYER_MESSAGE），玩家重下这道点名。
    speaker_role：客观档料由调用方给出（0033）；不在此复制档料。
    """
    cleaned = _normalize_unknown_participant_names(names)
    if voice == "minister":
        # Free prose speaker_role → prompt 供料：preserve raw; emptiness on copy (#1834 F21).
        role_raw = str(speaker_role or "")
        if role_raw.strip():
            role = role_raw
        else:
            name = str(speaker_name or "").strip()
            role = f"大臣{name}" if name else "大臣"
    else:
        role = "通政使司官"
    fact = unknown_participant_fact(cleaned)
    prompt = (
        f"你是{role}。根据下列事实，以本职口吻向皇帝回禀。\n"
        f"事实：{fact}\n"
    )
    return _compose_inworld_fact_report(
        prompt,
        llm_config=llm_config,
        tag="participant_escalate_report",
    )


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
    validate_delegations: bool = True,
) -> List[Dict[str, object]]:
    """人物参与人：normalize → 非人滤除 → canon → ADR 0053 校验。

    capture 与召对 materialize 共用；校验失败 raise ValueError（参与人物不存在…）。
    validate_delegations=False：调用方将与既有名单合并后再验委派链（#1897 E1）。
    """
    from ming_sim.action_materialize import DecreeMaterializationValidationError

    if not isinstance(roster, list):
        raise DecreeMaterializationValidationError(
            "参与人须为对象列表",
            failed_fields=("participant_roster",),
            category="invalid_participant_roster",
        )

    try:
        canonical_roster = db._normalize_participant_roster(
            roster, strict_structured=True,
        )
    except ValueError as exc:
        raise DecreeMaterializationValidationError(
            str(exc), failed_fields=("participant_roster",),
        ) from exc
    person_roster: List[Dict[str, object]] = []
    for item in canonical_roster:
        entry = dict(item)
        # canon / DB 读：故障上抛，不转产物
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
    # 委派链与成案/追加同一权威；声明面 as_declaration → 领域拒收（#1897 E1）。
    if validate_delegations:
        db._validate_dossier_delegations(person_roster, as_declaration=True)
    return person_roster


def _apply_validated_roster_to_extract_result(
    result: Dict[str, Any], *, db: Any, content: Any,
) -> Dict[str, Any]:
    """对单条抽取结果的 participant_roster 做 normalize+validate（就地拷贝）。"""
    out = dict(result)
    if "participant_roster" in out and out.get("participant_roster") is not None:
        out["participant_roster"] = normalize_draft_person_roster(
            out.get("participant_roster"), db=db, content=content,
        )
    return out


def _pay_order_grounding_facts(content: Any, db: Any = None) -> str:
    """把既有 canonical 地区/科目词表与结算时点直接教授抽取器；不建立第二映射。

    #1769：欠科目词表进输入侧结构契约（ADR0143/P6）；不在引擎侧改写 LLM 输出。
    科目闭集唯一真源 = pay_order.DUE_SUBJECTS / ARREARS_SUBJECTS。
    """
    from ming_sim.pay_order import (
        ARREARS_SUBJECTS,
        DEFAULT_DUE_PRIORITY,
        DUE_SUBJECTS,
    )

    regions = getattr(content, "regions", None) if content is not None else None
    lines = []
    for key, region in (regions or {}).items():
        rid = str(getattr(region, "id", None) or key or "").strip()
        name = str(getattr(region, "name", None) or "").strip()
        if rid and name:
            lines.append(f"{name}=@{rid}")
    timing = ""
    if db is not None:
        # 整段 game_state 时点读为持久缝：fetch/解码任一失败→代码故障（F39）。
        try:
            state = db.conn.execute(
                "SELECT turn, year, period FROM game_state WHERE id=1"
            ).fetchone()
            if state is not None:
                timing = (
                    f"当前结算时点：turn={int(state['turn'])}，"
                    f"{int(state['year'])}年{int(state['period'])}月。\n"
                )
        except (TypeError, ValueError) as exc:
            raise RuntimeError("game_state 时点持久读失败") from exc
    head = "【pay_order_override 接地事实】"
    if lines:
        head += "地区只能直接使用下列 canonical id，禁别名/自造：\n" + "、".join(lines) + "\n"
    else:
        head += "\n"
    due_set = "/".join(DUE_SUBJECTS)
    arrears_set = "/".join(ARREARS_SUBJECTS)
    default_due = (
        "/".join(DEFAULT_DUE_PRIORITY)
        + "=" + "/".join(str(DEFAULT_DUE_PRIORITY[s]) for s in DEFAULT_DUE_PRIORITY)
    )
    return (
        head + timing
        + f"due_priority 科目∈{due_set}；"
          f"arrears_priority 欠科目∈{arrears_set}；"
          f"due_haircut_bp 科目∈{due_set}。\n"
        + f"priority 数字越小越先；默认{default_due}，"
          "并列按该默认次序稳定排列。相对期限只填 duration_months=N，"
          "不要自行计算 until_turn；该动作 entries 必须非空。\n"
    )


def _ground_relative_pay_order_deadlines(result: Dict[str, Any], db: Any) -> Dict[str, Any]:
    """在既有抽取适配缝把结构化相对月数落成 active-through 绝对 turn。"""
    try:
        row = db.conn.execute("SELECT turn FROM game_state WHERE id=1").fetchone()
        if row is None:
            return result
        current_turn = int(row["turn"])
    except (TypeError, ValueError) as exc:
        raise RuntimeError("game_state.turn 持久读失败") from exc
    if result.get("dossier_action_type") != "pay_order_override":
        return result
    for entry in result.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        if "duration_months" in entry:
            duration = entry.pop("duration_months")
            if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
                raise ValueError(f"override 相对期限 duration_months 须为正整数：{duration!r}")
            entry["until_turn"] = current_turn + duration - 1
        elif "until_turn" in entry and (
            isinstance(entry["until_turn"], bool)
            or not isinstance(entry["until_turn"], int)
            or entry["until_turn"] < current_turn
        ):
            raise ValueError(f"override until_turn 已过期或无效：{entry['until_turn']!r}")
    return result


def _finalize_extract_with_combo(
    result: Dict[str, Any],
    *,
    needs_combo: bool = False,
) -> Dict[str, Any]:
    """结果建成后做组合校验；失败携带 partial + typed 可修字段边界。

    needs_combo 为调用方局部布尔，不写入结果字典。
    """
    if needs_combo:
        try:
            validate_structured_decree_combination(result)
        except StructuredDecreeCombinationError as exc:
            raise StructuredDecreeCombinationError(
                str(exc),
                partial_result=dict(result),
                failed_fields=exc.failed_fields,
            ) from exc
    return result


def _apply_failed_fields_from_correction(
    target: Dict[str, Any],
    corrected: Mapping[str, Any],
    failed_fields: object,
) -> None:
    """只把 failed_fields 边界内结构键从纠错轮写入 target（就地）。"""
    for key in expand_combo_failed_fields(failed_fields):
        if key in corrected:
            target[key] = corrected[key]
        else:
            target.pop(key, None)


def _merge_combo_correction_preserving_roster(
    baseline: Dict[str, Any],
    corrected: Dict[str, Any],
    *,
    failed_fields: Optional[frozenset] = None,
) -> Dict[str, Any]:
    """组合纠错成功：仅采纳 typed 失败字段，保留首抽 participant_roster。

    未失败的动作/目标/承办/类别与旨文、名册一律保留首抽；不另建第二 retry。
    """
    out = dict(baseline)
    top_fields = frozenset(failed_fields or ())
    if top_fields:
        _apply_failed_fields_from_correction(out, corrected, top_fields)
    if "participant_roster" in baseline:
        out["participant_roster"] = baseline["participant_roster"]
    return out


def _revalidate_merged_combo_result(
    result: Dict[str, Any],
    *,
    failed_fields: Optional[frozenset] = None,
) -> None:
    """合并失败字段后重走共同组合校验；仍败则 typed 上抛。"""
    if failed_fields:
        try:
            validate_structured_decree_combination(result)
        except StructuredDecreeCombinationError as exc:
            raise StructuredDecreeCombinationError(
                str(exc),
                partial_result=dict(result),
                failed_fields=exc.failed_fields,
            ) from exc


def _affair_declaration_from_draft_obj(obj: Mapping[str, Any]) -> Dict[str, Any]:
    """Typed 拆旨声明（new|existing）；缺席不猜。本阶段不消费了结。"""
    from ming_sim.entities.affair import ATTACH_BIRTH, declaration_from_payload
    declaration = declaration_from_payload(obj, allowed=ATTACH_BIRTH)
    return {} if declaration is None else {"affair_declaration": dict(declaration)}


def _stamp_split_birth_key(declaration: Mapping[str, Any]) -> Dict[str, Any]:
    """One extract shares one durable new identity; do not infer from name/origin."""
    body = dict(declaration)
    if body.get("attach") != "new" or str(body.get("birth_key") or "").strip():
        return body
    from uuid import uuid4
    body["birth_key"] = f"split:{uuid4().hex}"
    return body


def _draft_intent_open_affair_facts(db: Any) -> str:
    """Structured open-affair list so existing.affair_id is chosen from input, not guessed."""
    if db is None:
        return ""
    rows = db.affairs.list_open()
    if not rows:
        return ""
    lines = [
        json.dumps(
            {"id": int(row.id), "name": row.name, "origin": row.origin},
            ensure_ascii=False,
        )
        for row in rows
    ]
    return (
        "【已开事务】existing 的 affair_id 必须取自下列对象的 id，不得自造。\n"
        + "\n".join(lines)
        + "\n"
    )


def extract_draft_intent_with_roster_heal(
    player_message: Optional[str],
    minister_reply: str,
    llm_config: Any = None,
    *,
    db: Any = None,
    content: Any = None,
    heal_retries: int = DRAFT_PARTICIPANT_HEAL_RETRIES,
    initial_correction: str = "",
) -> Dict[str, Any]:
    """extract → 共同契约组合校验 + 名册校验；失败有界纠错重抽（P5 只走失败路）。

    #1624：组合校验失败只回喂结构契约，不改写自由文本旨文；不得各入口另造 heal。
    组合纠错复用 baseline_result：只更新该次不变式 failed_fields 边界内字段，
    保留首抽 participant_roster 与未失败结构，再走既有名册校验
    （禁合法甲→合法乙、未失败动作/目标/类别静默漂移）。
    自愈只许抄写纠错（修完仍是皇帝所指之人）。真不在册 / 擅自除名 →
    raise UnknownParticipantEscalate（调用方戏内回禀，不落草案）。
    db/content 缺一则只抽不校验名册（与旧 extract 同）；组合校验在 extract 内已做。
    LLM 在纠错路上挂死 → 原样上抛。
    initial_correction（#1769）：成案拒收补交时把失败事实与原产物作为首轮回喂。
    """
    retries = max(0, int(heal_retries))
    correction = str(initial_correction or "")
    pending_unknown: List[str] = []
    prior_ids_at_fail: List[str] = []
    # 首抽权威快照：首次校验失败后冻结，后续失败不得覆写 baseline/闸基线。
    baseline_result: Optional[Dict[str, Any]] = None
    baseline_from_combo = False
    baseline_failed_fields: frozenset = frozenset()

    for attempt in range(retries + 1):
        # llm_config 关键字传：别族 fake_draft(msg, reply, **kw) 形仍合法，
        # 不得因 heal 多塞第 3 位置参把旧 mock 签名整族打爆。
        try:
            result = extract_draft_intent(
                player_message,
                minister_reply,
                llm_config=llm_config,
                content=content,
                pay_order_facts=_pay_order_grounding_facts(content, db),
                correction_feedback=correction,
                db=db,
            )
        except StructuredDecreeCombinationError as exc:
            # 共同契约组合失败：typed 有界重试；首败冻结 partial + 可修字段边界。
            # 纠错轮整包仍可能因未失败字段漂移而组合失败——此时只取 partial 中
            # 原失败边界字段合并回首抽，再共同校验（不把漂移整包当成功结果）。
            partial = getattr(exc, "partial_result", None)
            if baseline_result is None and isinstance(partial, dict):
                baseline_result = dict(partial)
                baseline_from_combo = True
                baseline_failed_fields = frozenset(getattr(exc, "failed_fields", None) or ())
                if attempt >= retries:
                    raise
                correction = combination_correction_feedback(exc)
                _log(f"拟旨结构组合纠错重试 {attempt + 1}/{retries}: {exc}")
                continue
            if (
                baseline_from_combo
                and baseline_result is not None
                and isinstance(partial, dict)
            ):
                result = _merge_combo_correction_preserving_roster(
                    baseline_result,
                    partial,
                    failed_fields=baseline_failed_fields,
                )
                try:
                    _revalidate_merged_combo_result(
                        result,
                        failed_fields=baseline_failed_fields,
                    )
                except StructuredDecreeCombinationError as merged_exc:
                    if attempt >= retries:
                        raise StructuredDecreeCombinationError(
                            str(merged_exc),
                            partial_result=dict(result),
                            failed_fields=merged_exc.failed_fields,
                        ) from merged_exc
                    correction = combination_correction_feedback(merged_exc)
                    _log(
                        f"拟旨结构组合纠错重试 {attempt + 1}/{retries}: {merged_exc}"
                    )
                    continue
                baseline_result = dict(result)
                baseline_from_combo = False
                # 合并已过共同闸：落入下方 roster 路径（勿再 continue）
            else:
                if attempt >= retries:
                    raise
                correction = combination_correction_feedback(exc)
                _log(f"拟旨结构组合纠错重试 {attempt + 1}/{retries}: {exc}")
                continue
        # 组合纠错成功（纠错轮整包已过闸）：只采纳失败字段，再共同校验+roster 闸
        if baseline_from_combo and baseline_result is not None:
            result = _merge_combo_correction_preserving_roster(
                baseline_result,
                result,
                failed_fields=baseline_failed_fields,
            )
            _revalidate_merged_combo_result(
                result,
                failed_fields=baseline_failed_fields,
            )
            baseline_result = dict(result)
            baseline_from_combo = False
        if db is not None:
            result = _ground_relative_pay_order_deadlines(result, db)
        if db is None or content is None:
            return result
        has_roster_field = (
            "participant_roster" in result and result.get("participant_roster") is not None
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
            # 组合路径可能已冻 baseline：仍要记下 pending_unknown 供 backfill。
            if not pending_unknown:
                pending_unknown = _invalid_participant_names_from_error(exc)
                prior_ids_at_fail = _person_ids_from_extract_result(
                    baseline_result if baseline_result is not None else result,
                )
            if baseline_result is None:
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
        # 替换只认结构化人物引用校验；不扫自由正文姓名子串（#1834 F46）。
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
            assert baseline_result is not None
            # 一一对应槽级修补（禁聚合候选池）；对应不明（增人/重排/多未知）→ escalate
            # 纠错轮用原形 result（保留机构槽位形），禁 validated 压缩后再对下标——
            # 机构/泛称被 normalize 丢掉会错位。人物合法性已由 validated 闸证明。
            backfilled = _backfill_healed_participant_refs(
                baseline_result,
                result,
                db=db,
                content=content,
            )
            if backfilled is None:
                raise UnknownParticipantEscalate(pending_unknown)
            return backfilled
        return validated


def _stalled_deliberation_push_facts(db: Any) -> str:
    """#658：自由下旨可强推的 stalled 廷议＋active issue 投影（候选相关切片）。"""
    if db is None:
        return ""
    # #1849：供料库读失败是代码/IO 错，一律响亮上抛（ADR 0005）。此前静默洗成
    # 空事实块，抽取遂在缺御笔强推事实下照常出产、写入口再覆盖原草稿——
    # 失败被消解成合法产物（失败诚实宪法）。
    rows = db.list_decree_dossiers(status="proposed")
    lines: List[str] = []
    for row in rows or []:
        payload = row["payload"]
        if str(payload.get("deliberation_state") or "") != "stalled":
            continue
        did = int(row["id"])
        try:
            issue = db.conn.execute(
                "SELECT id, title FROM issues WHERE origin_ref=? AND status='active' "
                "LIMIT 1",
                (f"dossier:{did}",),
            ).fetchone()
            if issue is None:
                continue
            # #1565/0142：题名只认结构化 title|target_id|既有 issue.title；
            # 正文唯一真源 payload.text，旧档 decree_text 仅作正文承接。
            # 题/正文为 LLM 供料：原话过手，strip 只判空（#1897 E2 / P6）。
            title_raw = (
                payload.get("title")
                or payload.get("target_id")
                or issue["title"]
                or ""
            )
            title = title_raw if isinstance(title_raw, str) else str(title_raw or "")
            body_raw = payload.get("text") or row.get("decree_text") or ""
            body = body_raw if isinstance(body_raw, str) else str(body_raw or "")
            # #658：完整 title/body 供唯一辨认；禁 40 字截断导致同前缀误绑定
            lines.append(
                f"  案卷ID={did} issue#{int(issue['id'])} 题={title} 正文={body}"
            )
        except (TypeError, ValueError, KeyError) as exc:
            # #1849：坏项隔离留痕（ADR 0005：只拒该项、不带走整批，但必须记原因）。
            _log(f"强推案卷事实跳过坏行（dossier={row.get('id')!r}）：{exc}")
            continue
    if not lines:
        return ""
    return (
        "【可御笔强推的议而不决案卷】仅当皇帝明确强推下列事项时填目标案卷ID；"
        "否则目标案卷ID留 null。\n"
        + "\n".join(lines) + "\n"
    )


def extract_draft_intent(
    player_message: Optional[str],
    minister_reply: str,
    llm_config: Any = None,
    content: Any = None,
    correction_feedback: str = "",
    pay_order_facts: str = "",
    db: Any = None,
) -> Dict[str, Any]:
    """LLM 判皇帝本轮是否在口头请大臣拟旨（非显式前缀），返回拟旨意图 + 草案文本 + 目标候选。
    模型答无/非拟旨 → {"draft_action": "无", "draft_text": "", "target_candidate": ""}；
    抽取调用本身失败（LLM 终失败、代码错）一律上抛，不得降级成「无」（#1849 失败诚实）。

    content（#1428）：可选 GameContent；提供时把 characters 的 name+aliases 作结构化
    事实注入抽取 prompt，接地参与人规范名（禁散文守门族）。

    correction_feedback（#1274 V-1）：校验失败回喂的纠错指令；非空时 LLM 挂死响亮上抛。"""
    roster_facts = _draft_intent_character_roster_facts(content)
    army_facts = _draft_intent_army_grounding_facts(content)
    # 纠错反馈可含原旨副本：strip 只判空，不得加工整份运输块（#1897 E2 / P6）。
    if correction_feedback is None:
        correction_block = ""
    elif isinstance(correction_feedback, str):
        correction_block = correction_feedback
    else:
        correction_block = str(correction_feedback)
    if correction_block.strip() and not correction_block.endswith("\n"):
        correction_block += "\n"
    stalled_push_facts = _stalled_deliberation_push_facts(db)
    open_affair_facts = _draft_intent_open_affair_facts(db)
    from ming_sim.action_clusters import (
        assert_action_candidate_shape,
        cluster_fields_prompt,
        project_cluster_fields,
    )
    grant_fields_prompt = cluster_fields_prompt("grant_allocation")

    def _normalize_grant_transport(value: Mapping[str, Any]) -> Dict[str, Any]:
        transport = dict(value)
        # Draft transport historically used 目标ID and Chinese mode labels;
        # canonical FieldSpec validation happens only after those aliases normalize.
        if "target_id" not in transport and "目标" not in transport and "目标ID" in transport:
            transport["target_id"] = transport["目标ID"]
        raw_mode = transport.get("mode", transport.get("颁布方式"))
        if raw_mode not in (None, ""):
            transport["mode"] = _directive_mode(raw_mode) or raw_mode
        normalized = assert_action_candidate_shape({**transport, "kind": "grant_allocation"})
        projected = project_cluster_fields("grant_allocation", normalized)
        if projected.get("grant_action") != "协饷" and not projected.get("target_kind"):
            projected["target_kind"] = "policy"
        return projected

    intent_schema_line = (
        '  "拟旨意图": "无|拟旨",\n'
        '  "动作类型": "policy|approve_reject|assignment|'
        'grant_allocation|authorization|secret_authorization|secret_investigation|'
        'protection|strategy_selection|punishment|pacification|referral|'
        'revoke_decree|revoke_authority|dismiss_assignment|military_order|'
        'pay_order_override",\n'
        '  "entries": [],              // 仅 pay_order_override：偿还序/折发调整清单，\n'
        '                             // 形如 [{"key":"due_haircut_bp_宗禄","value":5000,"duration_months":3}]；\n'
        # 科目闭集展开只在 _pay_order_grounding_facts（同一 prompt 内）一处供料；
        # 此处只给键形状，不再展开第二份（全局 14 DRY）。
        '                             // key∈due_priority_<科目>[@省]|'
        'arrears_priority_<欠科目>[@省]|'
        'due_haircut_bp_<科目>[@省][#province|#central]；'
        'haircut 值=万分数(0,10000]；非该动作留 []\n'
        + grant_fields_prompt
        + '  "目标类型": "",\n'
        '  "目标ID": "",\n'
        '  "地区ID": "",\n'
        '  "施行范围": "",\n'
        '  "事务类别": "",\n'
        '  "承办人": "",\n'
        '  "参与人": [{"character_id":"规范名","tier":"主办|协办|知情","role":"本案职分","delegator_id":null}],\n'
        '  "期限月数": null,           // 军令必填正整数；非军令留 null\n'
        '  "事务声明": {"attach":"new|existing","name":"","origin":"","affair_id":null},\n'
        '  "目标案卷ID": null        // 御笔强推议而不决廷议时填该案卷整数 ID；非此意图留 null\n'
    )
    prompt = (
        "你是信息抽取器，不扮演、不写圣旨。读皇帝这句话 + 大臣回话，判断皇帝**本轮**"
        "是否在口头请大臣拟旨（如「拟旨吧」「你拟一道旨」「帮我起草」「草拟圣旨」等）。"
        "只输出一个 JSON 对象（无代码围栏、无多余字）：\n"
        "{\n"
        + intent_schema_line
        + "}\n"
        "判定要点：皇帝明确让大臣拟旨/起草圣旨→拟旨；仅商议/问询/催办/评论不算。语义判断，别拘字面。\n"
        + structured_decree_prompt_contract() + "\n"
        '非拨帑旨填共同契约目标/属地/事务类别/承办字段及“颁布方式”(普通|中旨直发)；拨帑旨只用 ACTION_CLUSTERS 字段。\n'
        '同一句交办只写一处事务声明（attach 仅 new|existing）；无声明不自建。\n'
        "御笔强推议而不决事项亦归拟旨，并填目标案卷ID。\n\n"
        + correction_block
        + roster_facts
        + army_facts
        + pay_order_facts
        + stalled_push_facts
        + open_affair_facts
        + "【皇帝】" + (player_message or "（无）") + "\n"
        + "【大臣回话】" + (minister_reply or "（无）") + "\n"
    )
    # #1849：抽取调用失败一律上抛。首抽也不例外：
    # 吞掉后这里只当「无拟旨意图」，下游 project 会把失败洗成 special_decree
    # 冒充成功产物（失败诚实宪法）。无意图只在模型真的这样回答时成立。
    raw, _ = _run_backend_for_config(prompt, llm_config, tag="draft_intent")
    # #1849：解析失败/缺意图键/非法意图值都是抽取产物不可用，不是「无意图」；
    # 一律响亮拒收（同 _coerce_draft_target_kind / 动作类型非法的既有契约），
    # 禁再消解成合法无意图让写入口覆盖原草稿。
    from ming_sim.action_materialize import DecreeMaterializationValidationError

    obj = _loads_lenient(raw)
    if not isinstance(obj, dict):
        raise DecreeMaterializationValidationError("拟旨抽取产物不可解析为 JSON 对象")
    if "拟旨意图" not in obj:
        raise DecreeMaterializationValidationError("拟旨抽取产物缺「拟旨意图」")
    _action = str(obj.get("拟旨意图") or "").strip()
    if _action not in {"无", "拟旨"}:
        raise DecreeMaterializationValidationError(f"拟旨意图非法：{_action!r}")
    # #654 H：无意图立即短路，不跑 acting/动作类型/target_kind 校验。
    if _action == "无":
        return {
            "draft_action": "无", "draft_text": "", "target_candidate": "",
        }
    # #658：御笔强推与普通 triad 互斥；并存响亮拒绝，禁止静默吞旨
    from ming_sim.db import (
        classify_directive_structured_kind,
        imperial_push_target_dossier_id,
    )
    # 先把抽取原键投影到权威键，再走单一互斥分类
    _probe: Dict[str, Any] = {}
    _raw_target = obj.get("目标案卷ID")
    if _raw_target is None:
        _raw_target = obj.get("target_dossier_id")
    if _raw_target is not None:
        _probe["target_dossier_id"] = _raw_target
    _act = str(obj.get("动作类型") or "").strip()
    if _act == "grant_allocation":
        _projected = _normalize_grant_transport(obj)
    else:
        _projected = {}
    _tk = str(
        _projected.get("target_kind")
        if _act == "grant_allocation" else obj.get("目标类型") or ""
    ).strip()
    _tid = str(
        _projected.get("target_id") if _act == "grant_allocation" else obj.get("目标ID") or ""
    ).strip()
    if _act:
        _probe["dossier_action_type"] = _act
    if _tk:
        _probe["target_kind"] = _tk
    if _tid:
        _probe["target_id"] = _tid
    kind = classify_directive_structured_kind(_probe) if _probe else "empty"
    if kind == "push":
        push_dossier_id = imperial_push_target_dossier_id(_probe)
        assert push_dossier_id is not None
        # 旨文原话：禁 strip 改写运输值（#1897 E2 / P6）。
        push_reply = minister_reply if isinstance(minister_reply, str) else str(minister_reply or "")
        push_msg = player_message if isinstance(player_message, str) else str(player_message or "")
        push_out: Dict[str, Any] = {
            "draft_action": "拟旨",
            "draft_text": push_reply if push_reply else push_msg,
            "target_candidate": "",
            "target_dossier_id": push_dossier_id,
        }
        push_mode = _directive_mode(obj.get("颁布方式"))
        if push_mode is not None:
            push_out["mode"] = push_mode
        # #1849：非法事务声明是脏产物，不得静默弃声明后照样出成功强推。
        push_declaration = _affair_declaration_from_draft_obj(obj)
        if push_declaration:
            push_out["affair_declaration"] = _stamp_split_birth_key(
                push_declaration["affair_declaration"]
            )
        return push_out
    dossier_action = str(obj.get("动作类型") or "special_decree").strip()
    if dossier_action == "acting_appointment":
        # #529：署理交回既有人事候选链，不经草案 acting_appointment。
        return {"draft_action": "无", "draft_text": "", "target_candidate": ""}
    if dossier_action not in DRAFT_ACTION_TYPES:
        from ming_sim.action_materialize import DecreeMaterializationValidationError
        raise DecreeMaterializationValidationError(
            f"动作类型非法：{dossier_action!r}",
            failed_fields=("dossier_action_type",),
        )
    _tk_raw = _projected.get("target_kind") if dossier_action == "grant_allocation" else obj.get("目标类型")
    target_kind = (
        str(_tk_raw or "").strip()
        if dossier_action == "grant_allocation"
        else _coerce_draft_target_kind(_tk_raw if _tk_raw not in (None, "") else "policy")
    )
    target_id_value = str(
        _projected.get("target_id") if dossier_action == "grant_allocation" else obj.get("目标ID") or ""
    ).strip()
    mode = _directive_mode(
        _projected.get("mode") if dossier_action == "grant_allocation" else obj.get("颁布方式")
    )
    # execution_surface 仅 grant 经 _normalize_grant_transport→project_cluster_fields
    # 投影；禁跨动作无条件透传（#1624）。
    mechanical = {
        "assignee": obj.get("承办人"),
        "deadline_months": obj.get("期限月数"),
        # #653：pay_order_override 结构化载荷随 capture 整道转交（禁旁路）。
        "entries": obj.get("entries"),
    }
    if dossier_action == "grant_allocation":
        mechanical.update(
            (key, item) for key, item in _projected.items()
            if key != "target_kind"
        )
    # #1624：共同契约组装；grant 完整 target 同走 assembler，缺席不洗 none。
    # 组合校验延后到结果建成：失败 partial 仍带首抽 participant_roster。
    needs_combo = (
        dossier_action != "grant_allocation" or bool(target_kind and target_id_value)
    )
    if needs_combo:
        assembled = assemble_structured_decree(
            {
                **obj,
                **mechanical,
                "动作类型": dossier_action,
                "目标类型": target_kind,
                "目标ID": target_id_value,
            },
            validate=False,
        )
        apply_assembled_to_payload(mechanical, assembled)
        target_kind = str(assembled["target_kind"])
        target_id_value = str(assembled["target_id"])
    elif dossier_action == "grant_allocation":
        explicit_scope = _explicit_draft_locality_scope(
            obj.get("施行范围") or _projected.get("locality_scope")
        )
        if explicit_scope is not None:
            mechanical["locality_scope"] = explicit_scope
    if mode is not None:
        mechanical["mode"] = mode
    # 大臣回话为 LLM 旨文：原话过手，strip 只用于判空副本（#1897 E2 / P6）。
    reply_raw = minister_reply if isinstance(minister_reply, str) else str(minister_reply or "")
    # #654 H 已在上方对 _action=="无" 短路；此处仅保留 #653 pay_order 验形。
    # #1849：entries 非法是脏产物，响亮拒收；不得洗成「无意图」让写入口
    # 以 special_decree 覆盖原草稿（失败诚实宪法）。
    if dossier_action == "pay_order_override" and (
        not isinstance(mechanical["entries"], list) or not mechanical["entries"]
    ):
        from ming_sim.action_materialize import DecreeMaterializationValidationError
        raise DecreeMaterializationValidationError(
            "pay_order_override 须有非空 entries 清单",
            failed_fields=("entries",),
        )
    # 大臣回话即草案（原话过手，不因 strip 改写）。
    draft_text = reply_raw
    # #1849：非法事务声明响亮拒收（禁静默弃声明后照样出成功草案）。
    single_declaration = _affair_declaration_from_draft_obj(obj)
    if single_declaration:
        single_declaration = {
            "affair_declaration": _stamp_split_birth_key(
                single_declaration["affair_declaration"]
            )
        }
    single_result = {
        "draft_action": _action, "draft_text": draft_text, "target_candidate": "",
        "dossier_action_type": dossier_action,
        "target_kind": target_kind, "target_id": target_id_value,
        "participant_roster": obj["参与人"] if "参与人" in obj else [],
        **mechanical,
        **single_declaration,
    }
    return _finalize_extract_with_combo(single_result, needs_combo=needs_combo)

# 八值 target_kind 真源在 decree_vocabulary.TARGET_KINDS（#654 / owner A 禁双定义）
from ming_sim.decree_vocabulary import TARGET_KINDS as _VALID_DRAFT_TARGET_KINDS
from ming_sim.execution_pressure import normalize_locality_scope as _normalize_locality_scope


def _coerce_draft_target_kind(raw: object) -> str:
    """#654 r3-B.2：非法 target_kind fail-loud，废除静默改 policy。"""
    from ming_sim.action_materialize import DecreeMaterializationValidationError

    kind = str(raw or "").strip()
    if kind not in _VALID_DRAFT_TARGET_KINDS:
        raise DecreeMaterializationValidationError(
            f"目标类型非法：{kind!r}",
            failed_fields=("target_kind",),
        )
    return kind


def _explicit_draft_locality_scope(raw: object) -> Optional[str]:
    """仅原始非空属地才归一；缺席返回 None（禁止预先洗成显式 none）。"""
    if raw is None or str(raw).strip() == "":
        return None
    return _normalize_locality_scope(raw)


def _manual_special_decree_payload(mode: str) -> Dict[str, object]:
    return {
        "dossier_action_type": "special_decree",
        "target_kind": "policy",
        "target_id": "manual-directive",
        "mode": mode,
        "locality_scope": "none",
    }


def _is_manual_special_decree_fallback(payload: Mapping[str, Any]) -> bool:
    """#1327/#1274 V-1 capture 空载/超时 fallback 同形；#1769 结算重写不得把它当成功拟旨。"""
    return (
        str(payload.get("dossier_action_type") or "").strip() == "special_decree"
        and str(payload.get("target_kind") or "").strip() == "policy"
        and str(payload.get("target_id") or "").strip() == "manual-directive"
        and str(payload.get("locality_scope") or "").strip() == "none"
    )


def capture_manual_directive_payload(
    text: str, llm_config: Any = None, *, existing_mode: object = None,
    db: Any = None, content: Any = None,
) -> Dict[str, object]:
    """Web/CLI 手工下旨共用既有草稿抽取 seam；在写入边界归一人物引用。

    #1327 / #1274 V-1：空载零 LLM 直落 special_decree（无正文）。
    #1465 切片③：外层 30s 总罩已删——长抽取不再被墙钟截断成 special_decree
    fallback（宪法 #9）；次数/空转由 transport 在 runner 侧收口。
    真不在册耗尽 → 通政司戏内回禀 ValueError（不落草案、不除名）；
    回禀产文失败 → typed LLMUnavailable（禁固定戏内模板当台词）。
    #1849：抽取调用失败不再降级 special_decree 冒充成功拟旨，一律响亮上抛。
    special_decree 另有一合法来路：模型真答「无拟旨意图」（产物空，非失败）。
    """
    # 旨文原话过手：strip 只判空，运输/下一次 extract 用原文（#1897 E2 / P6）。
    directive_text = text if isinstance(text, str) else str(text or "")
    fallback_mode = resolve_directive_mode(existing=existing_mode)
    # 空载短路：无正文可抽 → 直落草案结构，零 LLM 调用（P5：禁为省写把可短路 LLM 串回）。
    if not directive_text.strip():
        return _manual_special_decree_payload(fallback_mode)

    prompt = (
        f"请据此拟旨，并从以下已成旨文抽取结构，不得改写：\n{directive_text}"
    )

    def _run_extract() -> Dict[str, Any]:
        # #1274 V-1：extract→validate 有界纠错；db/content 齐时参与人名册自愈。
        return extract_draft_intent_with_roster_heal(
            prompt, directive_text, llm_config=llm_config,
            db=db, content=content,
        )

    captured: Dict[str, Any]
    try:
        captured = _run_extract()
    except UnknownParticipantEscalate as exc:
        # 真不在册：通政司戏内回禀；禁吞 special_decree、禁除名照落。
        report = compose_unknown_participant_inworld_report(
            exc.names,
            voice="tongzheng",
            llm_config=llm_config,
        )
        raise ValueError(report) from exc

    # 其余失败一律响亮上抛：LLM 终失败已由 transport 翻成 typed LLMUnavailable
    # （Web → 结构化 400，禁裸 500），业务 ValueError 原样上抛（CLI 留在审阅循环）。
    # #1849：此处曾用 `except Exception` 把任何失败——含 AttributeError 等代码错误
    # ——降级成 special_decree 冒充成功拟旨（Web 更新草稿后 200 返回）；真实抽取核
    # 内部（extract_draft_intent 首抽）也曾吞错续行，同样洗成 special_decree。
    # 两处皆已删；失败诚实宪法禁此。

    # heal 已 normalize+validate；投影与 #1769 补交共用同一 helper（禁双路径漂移）。
    return project_draft_extract_to_directive_payload(
        captured,
        decree_text=directive_text,
        existing_mode=existing_mode,
        db=db,
        content=content,
    )


def build_draft_admission_resubmit_feedback(
    *,
    failure_reason: str,
    bad_payload: Mapping[str, Any],
    decree_text: str = "",
) -> str:
    """#1769 成案拒收补交回喂：只告诉 LLM 失败事实与原产物（0150 D5-b）。

    结构契约/科目词表已由 extract_draft_intent 主 prompt 注入，不在 correction 再写一份。
    """
    payload_json = json.dumps(dict(bad_payload or {}), ensure_ascii=False, sort_keys=True)
    reason = str(failure_reason or "").strip() or "（未给出具体拒因）"
    # 原旨正文原话过手，禁 strip 改写（#1897 E2 / P6）。
    text = decree_text if isinstance(decree_text, str) else str(decree_text or "")
    parts = [
        "【成案校验失败，请按失败事实与原产物整份重交结构化字段（勿改旨文正文）】\n",
        f"失败事实：{reason}\n",
        f"原产物：{payload_json}\n",
    ]
    if text.strip():
        parts.append(f"原旨正文（不得改写）：{text}\n")
    return "".join(parts)


def project_draft_extract_to_directive_payload(
    captured: Mapping[str, Any],
    *,
    decree_text: str = "",
    existing_mode: object = None,
    db: Any = None,
    content: Any = None,
) -> Dict[str, object]:
    """把 extract_draft_intent 结果投影为 turn_directives.dossier_payload（与手工 capture 同形）。"""
    declared_mode = resolve_directive_mode(
        extracted=captured.get("mode"), existing=existing_mode,
    )
    if captured.get("draft_action") != "拟旨":
        return _manual_special_decree_payload(declared_mode)
    payload: Dict[str, object] = {
        "dossier_action_type": captured.get("dossier_action_type"),
        "target_kind": captured.get("target_kind"),
        "target_id": captured.get("target_id"),
        "mode": declared_mode,
    }
    for field in (
        "amount", "account", "execution_surface", "assignee",
        "deadline_months", "participant_roster", "locality_scope", "entries",
        "target_dossier_id", "affair_declaration",
        "grant_action", "purpose", "cadence",
        "region_id", "transaction_category",
    ):
        if captured.get(field) not in (None, ""):
            payload[field] = captured[field]
    if (
        payload.get("dossier_action_type") == "grant_allocation"
        and payload.get("grant_action") == "协饷"
    ):
        xiexang_kwargs = dict(
            amount=payload.get("amount"),
            account=str(payload.get("account") or ""),
            purpose=str(payload.get("purpose") or ""),
            target_kind=str(payload.get("target_kind") or ""),
            target_id=str(payload.get("target_id") or ""),
            cadence=str(payload.get("cadence") or ""),
        )
        if db is not None:
            from ming_sim.action_materialize import require_materializable_xiexang_payload
            material = require_materializable_xiexang_payload(
                db, text=str(decree_text or ""), **xiexang_kwargs,
            )
            payload.update({k: v for k, v in material.items() if k != "text"})
        else:
            from ming_sim.action_materialize import require_explicit_xiexang_fields
            payload.update(require_explicit_xiexang_fields(**xiexang_kwargs))
    if payload.get("dossier_action_type") == "dismiss_assignment":
        payload["name"] = str(payload.get("target_id") or "").strip()
        payload["_office_action"] = "罢免"
    from ming_sim.db import (
        classify_directive_structured_kind,
        imperial_push_target_dossier_id,
    )
    # #1849：互斥违规（push 与 triad 并存）此前先被 except 洗成 "ordinary" 再走
    # 组装，报出的可能已是别的字段错；禁临时改判，直接响亮上抛（同一 classify
    # 在下方组装后还会再判一次，掩盖只会让真因被别的字段错顶替）。
    pre_kind = classify_directive_structured_kind(payload)
    if pre_kind not in {"push", "empty"} and payload.get("target_kind") not in (None, ""):
        regions_content = getattr(content, "regions", None) if content is not None else None
        conn = None if db is None else db.conn
        assembled = assemble_structured_decree(
            payload,
            conn=conn,
            regions_content=regions_content,
            validate=True,
        )
        apply_assembled_to_payload(payload, assembled)
    kind = classify_directive_structured_kind(payload)
    if kind == "push":
        push_id = imperial_push_target_dossier_id(payload)
        assert push_id is not None
        push_payload: Dict[str, object] = {
            "target_dossier_id": push_id,
            "mode": declared_mode,
        }
        declaration = captured.get("affair_declaration")
        if declaration not in (None, ""):
            push_payload["affair_declaration"] = declaration
        return push_payload
    if kind == "empty":
        return _manual_special_decree_payload(declared_mode)
    return payload


def resubmit_draft_admission_payload(
    decree_text: str,
    *,
    bad_payload: Mapping[str, Any],
    failure_reason: str,
    llm_config: Any = None,
    db: Any = None,
    content: Any = None,
    existing_mode: object = None,
) -> Dict[str, object]:
    """#1769 结算路 B：把成案失败事实与原产物告诉 LLM，重交结构化 payload。

    本函数单次重写；外层（session）按 DRAFT_ADMISSION_RESUBMIT_REWRITES 循环
    （原抽 + 重写 2 = 总计 3）。与 extract 内 heal_retries（组合/名册）独立——
    内部 heal 不冒充成案补交次数。不在引擎侧改写 LLM 输出（0142）。
    """
    from ming_sim.action_materialize import DecreeMaterializationValidationError

    # 补交运输：strip 只判空，原文送下一 LLM（#1897 E2 / P6 / ADR0142）。
    text = decree_text if isinstance(decree_text, str) else str(decree_text or "")
    if not text.strip():
        raise DecreeMaterializationValidationError("补交缺旨文正文")
    feedback = build_draft_admission_resubmit_feedback(
        failure_reason=failure_reason,
        bad_payload=bad_payload,
        decree_text=text,
    )
    prompt = f"请据此拟旨，并从以下已成旨文抽取结构，不得改写：\n{text}"
    try:
        captured = extract_draft_intent_with_roster_heal(
            prompt,
            text,
            llm_config=llm_config,
            db=db,
            content=content,
            initial_correction=feedback,
        )
    except UnknownParticipantEscalate as exc:
        # 已识别的名册产物错：与 capture_manual_directive_payload 同一归一
        # ——产物错走本票 B 路预算/留存，不得升成整月 SettlementAbort 连带好旨。
        # 结算路无召对现场，不另作戏内回禀；只把不在册事实当失败事实回喂下一次重写。
        raise DecreeMaterializationValidationError(exc.fact) from exc
    # #1769 结算路 B：仅「仍为拟旨且非 capture 空载 fallback」才算本轮成功产物。
    # extract 缺拟旨意图/垃圾 → draft_action=无；project 再映成 special_decree
    # fallback——若 replace_payload 会毁掉原 pay_order/grant 并被二次 ensure 成案（P1）。
    # capture 首次空载/超时 fallback 不经本函数，不动。
    if captured.get("draft_action") != "拟旨":
        raise DecreeMaterializationValidationError("结算补交重写未返回拟旨意图")
    payload = project_draft_extract_to_directive_payload(
        captured,
        decree_text=text,
        existing_mode=existing_mode or (bad_payload or {}).get("mode"),
        db=db,
        content=content,
    )
    if _is_manual_special_decree_fallback(payload):
        raise DecreeMaterializationValidationError(
            "结算补交重写落空载 special_decree fallback",
        )
    return payload


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
    """agy / codex 当后端；provider 调用适配后复用 agno 的 tool loop。"""

    backend: str = "agy"
    reasoning_strength: str = ""
    materials_dir: str = ""

    def _call_cli(self, prompt: str) -> Tuple[str, int]:
        """一次子进程。等多久算死归 transport 策略（设置页那一格的静默判死阈值）：
        出字的子进程不被任何总墙钟 SIGKILL，只有静默超阈值才判死重试。"""
        materials = str(getattr(self, "materials_dir", "") or "").strip() or None
        return _dispatch_cli_runner(
            self.backend,
            prompt,
            model=str(getattr(self, "id", "") or ""),
            reasoning_strength=(
                str(getattr(self, "reasoning_strength", "") or "").strip().lower() or None
            ),
            materials_dir=materials,
        )

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
        # 把这句回话原文整段入档。invoke 只负责出文本。
        materials = str(getattr(self, "materials_dir", "") or "").strip() or None
        prompt = _messages_to_prompt(messages, response_format, materials_dir=materials)
        with _TRACE_LOCK:  # 原子自增，防并发丢增量/seq 重复（#83）
            _seq += 1
            seq = _seq
        tag = str(getattr(self, "trace_tag", "") or "").strip() or "other"
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
            from ming_sim.llm_transport import TransportIdleTimeout
            error = str(exc)
            # 已 typed 的可重试瞬断（空转/空输出/连接）原样上浮：套成
            # llm_cli_* 会让 transport 把瞬断误判成确定性失败，一次即终。
            if isinstance(exc, (LLMUnavailable, TransportIdleTimeout)):
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
                "materials_dir": str(getattr(self, "materials_dir", "") or ""),
                "error": error, "prompt": prompt, "response": text,
            })
            _log(f"#{seq} {tag} {dt}s attempts={attempts} resp={len(text)}c"
                 + (f" ERROR={error}" if error else ""))

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
        if response_format is not None:
            # 结构化产出的解析权威在 invoke（_parse_provider_response 吃 response_format）；
            # 流式只累文本，不在此复制一份结构解析。
            yield self.invoke(
                messages, assistant_message, response_format=response_format,
                tools=tools, tool_choice=tool_choice, run_response=run_response,
                compress_tool_results=compress_tool_results,
            )
            return
        materials = str(getattr(self, "materials_dir", "") or "").strip() or None
        prompt = _messages_to_prompt(messages, response_format, materials_dir=materials)
        try:
            # #1465 切片③：空转判死归子进程增量读（新字节即活动，不设总墙钟），
            # 本处只搬 `_iter_cli_runner_text` 已判活的文本 —— 机器横幅不进 delta。
            # codex 走结构化 --json 事件流边到边出；纯文本 runner 判活后一次交全。
            stream = _iter_cli_runner_text(
                self.backend,
                prompt,
                model=str(getattr(self, "id", "") or ""),
                reasoning_strength=str(getattr(self, "reasoning_strength", "") or "").strip().lower() or None,
                json_events=(self.backend == "codex"),
                materials_dir=materials,
            )
            for delta in stream:
                yield ModelResponse(role="assistant", content=str(delta))
        except Exception as exc:
            # #1299/#1310：流式 runner 失败同翻 typed，禁机器横幅进 delta/content。
            # #1465：已 typed 的可重试瞬断原样上浮（同 invoke）。
            from ming_sim.exceptions import LLMUnavailable
            from ming_sim.llm_model import cli_runner_unavailable
            from ming_sim.llm_transport import TransportIdleTimeout
            if isinstance(exc, (LLMUnavailable, TransportIdleTimeout)):
                raise
            raise cli_runner_unavailable(exc, backend=self.backend) from exc

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
    reasoning_strength: str = "high",
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
    return {
        "channel": channel or "cli",
        "runner": runner,
        "model": model,
        "reasoning_strength": str(getattr(cfg, "reasoning_strength", "") or ""),
    }
