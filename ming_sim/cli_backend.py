"""本地 CLI LLM 后端：用已支持的本机 agent runner 调用 LLM，脱离 api key。

探针目标：把游戏 LLM 后端从「api key 调远端」换成「本地自治 CLI agent」。
做法 = 继承 agno 的 OpenAIChat，只覆盖最底层 invoke：
不发 HTTP，改 subprocess 调 agy，把文本输出包成假 ChatCompletion，
交回 agno 原生 _parse_provider_response 解析。agno 全套（解析/流式回退/
消息格式）原样复用，零 function-calling（工具不传，大臣退化成纯文本进谏）。

启用：运行配置声明 channel=cli + cli.runner（设置页或 runtime_llm.json）。
#1902：MING_SIM_LLM_BACKEND 选宿主的旧路已退役——宿主只由运行配置决定。
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
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Type, Union

from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.models.response import ModelResponse
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from pydantic import BaseModel

# CLI runner 默认模型单一真源在 models（L0 叶子），此处 re-export 保留
# `from ming_sim.cli_backend import CODEX_DEFAULT_MODEL` 既有路径（#60）。
from ming_sim.models import CLI_DEFAULT_RUNNER, CODEX_DEFAULT_MODEL, CLAUDE_DEFAULT_MODEL, LLMConfig
# #1902 T4：领域动作集合与 structured_decree 导入已归 draft_intent / decree_vocabulary；
# 传输层不再定义 DRAFT_ACTION_TYPES 或挂领域规则。

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
# 前端 CLI Runner 下拉稳定 UI 顺序；membership 仍以 _CLI_BACKENDS 为唯一准入（#1274 W1）。
# GATE_CLI_RUNNERS ⊂ 此序（无 agy）；禁在 menuPage/gameMenu 再硬编一份。
# #1274-qa-y1：pi 紧随 grok（UI_ORDER∩_CLI_BACKENDS → cli_runner_choices 自动带出）。
_CLI_RUNNER_UI_ORDER = ("agy", "codex", "claude", "cursor", "kimi", "grok", "pi")
_CLI_RUNNER_LABELS = {"agy": "agy（Gemini）"}
# 实际消费 --model / cli_model 的 runner（describe_effective_model 用）；agy 走自身 ladder。
_CLI_MODEL_RUNNERS = _CLI_BACKENDS - {"agy"}
# 闸脚本 --runner choices 与公开支持集同源（UI 序中去掉无 --model 旗的 agy）。
GATE_CLI_RUNNERS = tuple(r for r in _CLI_RUNNER_UI_ORDER if r in _CLI_MODEL_RUNNERS)
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
# 支持 reasoning_strength 传输的 CLI runner 单源（#1271/#1274-y1）：由上方 *_BY_STRENGTH
# 表投影。有传输表 = 支持；kimi/cursor 无独立档位旗，不入此集（另票/庭裁）。
_REASONING_TRANSPORT_BY_RUNNER = {
    "codex": _CODEX_REASONING_BY_STRENGTH,
    "claude": _CLAUDE_THINKING_TOKENS_BY_STRENGTH,
    "grok": _GROK_EFFORT_BY_STRENGTH,
    "pi": _PI_THINKING_BY_STRENGTH,
}
# 导出 frozenset——llm_config 谓词与 web payload 均消费此名，禁第二处手写名单。
CLI_REASONING_STRENGTH_RUNNERS = frozenset(_REASONING_TRANSPORT_BY_RUNNER)
# off 档在传输表中实取 low（两档取值相同）的 runner：界面「最低=低」提示的唯一后端源，同样由表投影。
CLI_REASONING_FLOOR_RUNNERS = frozenset(
    runner for runner, table in _REASONING_TRANSPORT_BY_RUNNER.items()
    if table["off"] == table["low"]
)


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
# 影响，也就不会污染 runner 分派（_run_cli_runner）的 mock 调用计数。
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
        # 硬规9：禁 subprocess.run(timeout=…)——超时路径会 SIGKILL。登录 PATH 探测无期限杀。
        proc = _RAW_RUN(
            [shell, "-l", "-i", "-c", 'printf "<<<CMRPATH>>>"; printenv PATH; printf "<<<ENDPATH>>>"'],
            capture_output=True, text=True,
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
        # 硬规9：禁 timeout=（subprocess.run 超时会 SIGKILL）。keychain 暖探无期限杀。
        subprocess.run(
            ["security", "find-generic-password", "-s", "Antigravity Safe Storage"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
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
    """子进程收尾事实（退出码 / stderr 诊断 / stdin·管道读错），由增量读循环回填。"""

    returncode: Optional[int] = None
    stderr: str = ""
    stdin_error: Optional[BaseException] = None
    stream_error: Optional[BaseException] = None


def _cli_idle_seconds() -> float:
    """CLI 子进程静默预算：只认 transport 策略 idle（与召对、API 同一权威）。

    该阈值来自设置页那一格（runtime 档 cli.timeout_seconds），经
    resolve_transport_policy 解析（#1465 切片③ owner 2026-09-07）。它说的是「多久
    没有新字节才判这次调用已死」，不是 attempt 总墙钟。
    """
    from ming_sim.llm_transport import resolve_transport_policy

    return float(resolve_transport_policy().idle_timeout_seconds)


def _terminate_cli_process(proc: Any) -> None:
    """收尾子进程：已退时 terminate 是 no-op；否则只 SIGTERM，不 SIGKILL（硬规9）。

    wait 短暂未退 → 如实记终止缺口，不另造监督层、不以 kill 兜底。
    """
    try:
        proc.terminate()
    except Exception as exc:
        logger.warning("CLI 子进程 terminate 失败：%s", exc)
        return
    try:
        proc.wait(timeout=5)
    except Exception as exc:
        logger.warning(
            "CLI 子进程 terminate 后仍未退出（终止缺口，不 SIGKILL）：%s", exc,
        )


def _iter_cli_process_lines(
    cmd: List[str],
    *,
    stdin_text: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[str] = None,
    clock: Optional[Callable[[], float]] = None,
    outcome: Optional[_CliProcessOutcome] = None,
    backend: str = "cli",
) -> Iterator[str]:
    """CLI 子进程增量读单真源：一次子进程 = 一次 attempt，按到达顺序 yield stdout 行。

    - 新字节即活动，刷新活动时刻；静默 ≥ idle 预算 → TransportIdleTimeout（可重试）
      并 terminate 该子进程（空转判据走 llm_transport.check_idle_budget，禁平行实现；
      不 SIGKILL，硬规9）。
    - idle 只认 transport 策略（`_cli_idle_seconds`）= 设置页那一格的静默判死阈值。
    - **不设 attempt 总墙钟，收尾不做 SIGKILL 升级（宪法 #9）**：只要还有新字节就不判死；
      收尾只 terminate + wait，失败原样上抛。
    - stderr 并发抽干：否则 codex 等把 stderr 写满 OS pipe 会反压死 stdout。
    - stdin 另起线程喂：大 prompt 超 pipe 缓冲时不与读 stdout 互锁。
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
        except BaseException as exc:
            # 读取失败（含线程内 SystemExit/KeyboardInterrupt/TypeError）记真因交父循环；
            # 不得在工作线程内 re-raise 冒充已传给父调用（threading 只走 excepthook）。
            # finally 仍发哨兵，避免父侧空等。主动 cancel 若已在父侧抛出，以其终态为准。
            if result.stream_error is None:
                result.stream_error = exc
            logger.warning("CLI %s 管道读取失败：%s", kind, exc)
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
        except BaseException as exc:
            # 与 _pump 同：线程内不得只消亡。未知代码/控制异常也记入 stdin_error
            # 交父调用；OSError 由消费者翻 typed，其余原样上浮（ADR 0005）。
            # 不得在工作线程 re-raise 冒充已传给父调用（threading 只走 excepthook）。
            if result.stdin_error is None:
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
    pending_out = ""

    host = str(backend or "cli").strip() or "cli"

    def _raise_recorded_thread_fault() -> None:
        """工作线程已记录的故障立刻升格：不等另一管道 EOF，也不让 idle 改写真因。

        stream_error / stdin_error 同一交接：OSError 族 → typed 宿主 I/O 终失败；
        其余代码/控制异常原样上浮。不得因槽非空改写成可重试空转。
        """
        err = result.stream_error
        if err is not None:
            if isinstance(err, OSError):
                from ming_sim.llm_model import cli_runner_unavailable
                host_exc = RuntimeError(f"CLI 管道读取失败：{err}")
                raise cli_runner_unavailable(host_exc, backend=host) from err
            raise err
        err = result.stdin_error
        if err is not None:
            if isinstance(err, OSError):
                from ming_sim.llm_model import cli_runner_unavailable
                host_exc = RuntimeError(
                    f"{host} 调用失败（prompt 未能写入子进程 stdin）：{err}"
                )
                raise cli_runner_unavailable(host_exc, backend=host) from err
            raise err

    def _has_recorded_thread_fault() -> bool:
        return result.stream_error is not None or result.stdin_error is not None

    try:
        while open_streams > 0:
            # 已知线程故障立刻升格：不等另一管道 EOF，也不让后续 idle 改写成可重试分类。
            _raise_recorded_thread_fault()
            try:
                kind, chunk = chunks.get(timeout=_CLI_POLL_SECONDS)
            except queue.Empty:
                _raise_recorded_thread_fault()
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
                    # 已有线程故障则不把半截正文当成功产出。
                    if leftover and not _has_recorded_thread_fault():
                        yield leftover
                _raise_recorded_thread_fault()
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
                if not _has_recorded_thread_fault():
                    yield line
            _raise_recorded_thread_fault()
        _raise_recorded_thread_fault()
        # 管道已 EOF 但进程未退：静默同样计入 idle 预算，仍无总墙钟。
        while proc.poll() is None:
            _raise_recorded_thread_fault()
            check_idle_budget(
                last_activity_at=last_activity, policy=policy, clock=tick,
            )
            time.sleep(_CLI_POLL_SECONDS)
    finally:
        _terminate_cli_process(proc)
        for worker in workers:
            worker.join(timeout=5)
        result.stderr = "".join(stderr_parts)
        result.returncode = proc.poll()
    # join 后若 feeder 才落盘 stdin_error，仍不得当成功收尾。
    _raise_recorded_thread_fault()

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
    出去。纯文本 runner（agy/claude/pi）**不逐行外抛 stdout**——子进程排干后
    再按退出码／结构化契约分类；禁从自由输出词面判故障（ADR 0142）。codex
    `--json` 是结构化事件流（`_codex_event_text` 认字段、不读散文），可照旧边到边出。

    次数只在 llm_transport（run_with_transport / run_transport_stream）；此处禁
    私有 for-attempt 循环。失败按 typed 分类抛，交上层统一重试或终结：
    - 静默超阈值 → TransportIdleTimeout（可重试；_iter_cli_process_lines 抛）
    - 空输出 → llm_empty_output（可重试）
    - stdin 未送达（线程已记故障，父环 idle 前升格）/ 未知非零退出 →
      cli_runner_unavailable（typed 确定性失败，一次不重试；禁从 stderr 散文抠状态；
      仅此已确证宿主 I/O／退出接缝翻 typed）
    - 宿主未暴露结构化鉴权状态时如实按正文／退出码处理，不另造词表（宿主缺口）

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
                clock=clock, outcome=outcome, backend=runner,
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
        # stream_error / stdin_error 均已在 _iter_cli_process_lines 于 idle 前即时升格；
        # 本生成器完整消费该泵，不另加延后同因兜底（#1902 CLI-RECORDED-THREAD-FAULTS）。
        # #1902 T2 / 锚定宪法：交付保留宿主原正文，不以 strip 改写呈现；
        # 空产出只以「去空白后是否为空」作判定，不把裁剪结果当交付物。
        primary = stdout_text if stdout_text.strip() else final_text
        # 已确证非零退出 → typed 确定性失败（#1780 / ADR 0142）；禁从 stderr 词面分类。
        if returncode != 0:
            from ming_sim.llm_model import cli_runner_unavailable
            host_exc = RuntimeError(
                f"{runner} 调用失败（退出码 {returncode}）：{stderr[:200]}"
            )
            raise cli_runner_unavailable(host_exc, backend=runner) from host_exc
        if not primary.strip():
            raise transport_failure_unavailable(
                empty_output_failure(), attempts=1, exhausted=False,
            )
        # 判活之后才交文本：json 事件流已边到边出过，只补终包兜底；纯文本一次交全。
        if not json_events:
            yield primary
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
    # #1902 T2：原正文交付，不 strip 改写。
    return text, 1


# #1902：七条一行转发（_run_agy/_run_codex/…）退役——它们既不改 argv 也不改行为，
# 只是把同一调用形状抄了七遍。分派点直接落到 _run_cli_runner。


# #1902：runner 名 → 单次调用入口的映射表，取代手写 if/elif 分派链。
# 各宿主的 argv 约定仍只在 _cli_runner_command 一处；此处只回答「这个 runner 调谁」。
# agy 走自身 ladder、不消费 --model，故调用时不带 model/reasoning_strength。
# 存函数名而非函数对象：调用点现取，monkeypatch 替换任一宿主入口仍即时生效
# （测试与探针都靠这条缝注入）。
# 准入名单不在此重抄一份：唯一真源是 _CLI_BACKENDS（见 is_supported_cli_runner）。


def _dispatch_cli_runner(
    runner: str,
    prompt: str,
    *,
    model: Optional[str] = None,
    reasoning_strength: Optional[str] = None,
    materials_dir: Optional[str] = None,
) -> Tuple[str, int]:
    """runner 名 → 该 runner 的单次调用入口。全仓唯一一处 runner 分派点
    （config 分派与 CliChat 分派共用，禁再复制第二份）。"""
    if not is_supported_cli_runner(runner):
        raise RuntimeError(f"未知 CLI backend：{runner}")
    extra = {"materials_dir": materials_dir} if materials_dir else {}
    if runner == "agy":
        return _run_cli_runner(runner, prompt, **extra)
    return _run_cli_runner(
        runner, prompt, model=model, reasoning_strength=reasoning_strength, **extra,
    )


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
    runner = (getattr(llm_config, "cli_runner", "") or CLI_DEFAULT_RUNNER).strip().lower()
    if runner not in _CLI_BACKENDS:
        raise RuntimeError(f"未知 CLI backend：{runner}")
    model = (getattr(llm_config, "cli_model", "") or "").strip()
    reasoning_strength = str(getattr(llm_config, "reasoning_strength", "") or "").strip().lower()
    return runner, model, reasoning_strength


def _run_backend_for_config(
    prompt: str, llm_config: Any = None, tag: str = "", *, policy=None,
) -> Tuple[str, int]:
    """仅 channel=cli 可入；空/api 通道不得落到任何默认 runner（与 create_chat_model 同一通道解释）。

    直接编程路径（职官分类/国策补全/连通性 verify）的 CLI 咽喉：
    每次调用 try/finally 写一条 trace，谁调都记，不靠各调用方自觉手写。
    （agno 游戏路径走 CliChat.invoke 自有 trace，与此咽喉不重叠。）
    tag 只记调用方显式传入的值；空则空，不从 prompt 正文推断。

    #1465 切片③：本入口是结算/拟旨等非 Agent CLI extractor 的**次数入口**——
    在此包一次 run_with_transport，operation 调单次子进程；runner 内禁私有重试。"""
    from ming_sim.llm_transport import resolve_transport_policy, run_with_transport

    parts = _cli_config_parts(llm_config)
    if parts is None:
        raise RuntimeError("非 cli 通道未启用本地 CLI backend")
    runner, model, reasoning_strength = parts
    model_id = model or runner
    t0 = time.monotonic()
    text, attempts, error = "", 0, None

    def _one_call() -> str:
        # 无 Exception→typed 宽包装：命令构造等代码故障原样上浮；
        # 已确证宿主 I/O／退出失败只在 _iter_cli_runner_text 等接缝翻 typed。
        return _dispatch_cli_runner(
            runner, prompt,
            model=model or None,
            reasoning_strength=reasoning_strength or None,
        )[0]

    try:
        resolved_policy = policy or resolve_transport_policy()
        text, attempt_records = run_with_transport(
            _one_call, policy=resolved_policy,
        )
        attempts = len(attempt_records)
        return text, attempts
    except Exception as exc:
        # typed 出口：trace 留 provider_message 原诊断，不写玩家面文案。
        from ming_sim.exceptions import LLMUnavailable as _LLMUnavailable
        if isinstance(exc, _LLMUnavailable) and exc.provider_message:
            error = str(exc.provider_message)
        else:
            error = str(exc)
        raise
    finally:
        _trace({
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "seq": -1, "tag": tag,
            "backend": runner, "model_id": model_id,
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
    # 无论有无显式 policy，model 调用都经 bind 捕获 typed/代码故障原件
    # （#1902：policy=None 裸 run 会让 SDK 把 TypeError 摊成 llm_run_error）。
    from ming_sim.llm_transport import (
        bind_transport_sdk_budget,
        default_transport_policy,
        run_with_transport,
    )

    model = getattr(agent, "model", None)
    if policy is None:
        with bind_transport_sdk_budget(model, default_transport_policy()):
            return extract_agent_text(agent.run(prompt)), 1
    with bind_transport_sdk_budget(model, policy):
        text, attempts = run_with_transport(
            lambda: extract_agent_text(agent.run(prompt)), policy=policy,
        )
    return text, len(attempts)


def _run_json_extractor_for_config(
    prompt: str, llm_config: Any = None, tag: str = "", *, policy=None,
) -> Tuple[str, int]:
    if _llm_channel(llm_config) == "cli":
        return _run_backend_for_config(prompt, llm_config, tag=tag, policy=policy)
    # 空 channel 与 api 同走 API 路径（create_chat_model／cli_backend_active 的现役解释）。
    return _run_api_for_config(prompt, llm_config, tag=tag, policy=policy)


def describe_effective_model(llm_config: Any = None) -> str:
    """日志用：返回该 config **实际调用**的「runner/model」可读串，而非 CLI 通道下的 API-fallback
    占位 `cfg.model`（如 gpt-4o-mini）——后者误导排查（#84）。runner 解析与 create_chat_model 同口径：
    api 通道→cfg.model；cli 通道→真实 runner + 解析后的 cli_model（如 codex/gpt-5.3-codex-spark）。
    注：未显式填 cli_model 时，CliChat.id 可留空（codex 分派再回落 _CODEX_MODEL），故 trace 的 model_id
    可能是空串而本函数已解析出真实默认——本函数是更准的可读标签，不与 trace 的未解析 id 逐字对齐。"""
    channel = _llm_channel(llm_config)
    # #1902：宿主只由运行配置选——空 channel 不再回落环境变量，按 API 通道读 cfg.model。
    runner = (
        (getattr(llm_config, "cli_runner", "") or CLI_DEFAULT_RUNNER).strip().lower()
        if channel == "cli" else None
    )
    if not runner:  # api 通道 / 空 channel：用 cfg.model
        return str(getattr(llm_config, "model", "") or "?")
    # 只有实际吃 --model 的 runner 才追加 /model；agy 忽略 model、走自身 Gemini ladder，
    # 给它挂个不被消费的 cli_model 反而误导（#84 codex），只显示 runner 名。
    if runner in _CLI_MODEL_RUNNERS:
        from ming_sim.llm_config import cli_model_from_env
        model = (str(getattr(llm_config, "cli_model", "") or "").strip()) or cli_model_from_env(runner)
        return f"{runner}/{model}" if model else runner
    return runner


def cli_backend_active(llm_config: Any = None) -> bool:
    """是否处于 CLI 后端路径：仅当运行配置显式 channel=cli 且 runner 合法时为真。

    资格只认 channel + runner 闭集（与 _cli_config_parts 同一权威），不 try/except
    配置投影：未知 runner → False；投影代码故障原样上抛（不得洗成 not-active）。
    """
    channel = _llm_channel(llm_config)
    if channel == "api":
        return False
    if channel == "cli":
        runner = (getattr(llm_config, "cli_runner", "") or CLI_DEFAULT_RUNNER).strip().lower()
        return runner in _CLI_BACKENDS
    return False  # #1902：无显式 channel 即无 CLI 路径（env 选宿主已退役）


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


# 现役密令写口：audience_translate → declaration_dispatch（#1902）。
# 旧「拟旨/密令」前缀分派与 _extract_secret_order 独占链已清退。



# #1902 T4：拟旨抽取 / 名册自愈 / 国策补全等现役领域编排已迁至 ming_sim.draft_intent。
# 本文件只保留 CLI 传输与 runner 适配；禁止在此再挂领域编排副本或兼容转发。

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

    backend: str = CLI_DEFAULT_RUNNER
    reasoning_strength: str = ""
    materials_dir: str = ""

    def _call_cli(self, prompt: str) -> Tuple[str, int]:
        """一次子进程。等多久算死归 transport 策略（设置页那一格的静默判死阈值）：
        不设 attempt 总墙钟；只有静默超阈值才判死重试，收尾只 SIGTERM。"""
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
        # 显式来源＝本轮 RunOutput 上已有的 agent 名；不从 prompt 正文猜类别。
        tag = str(getattr(run_response, "agent_name", "") or "").strip()
        t0 = time.monotonic()
        error = None
        text = ""
        attempts = 0
        try:
            text, attempts = self._call_cli(prompt)
        except BaseException as exc:
            # 已确证宿主 I/O／退出失败在 runner 接缝已翻 typed LLMUnavailable；
            # 未知代码异常原样上浮——不得套成 llm_cli_* 当「模型不可用」
            # （#1902 CLI-UNKNOWN-CODE-FAULTS；失败诚实宪法）。trace 仍记原文。
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
        # #1465 切片③：空转判死归子进程增量读（新字节即活动，不设总墙钟），
        # 本处只搬 `_iter_cli_runner_text` 已判活的文本 —— 机器横幅不进 delta。
        # codex 走结构化 --json 事件流边到边出；纯文本 runner 判活后一次交全。
        # 无 Exception→cli_runner_unavailable 宽包装：已 typed 的宿主/瞬断由
        # runner 接缝上浮；未知代码异常保真（同 invoke / #1902）。
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

    async def ainvoke_stream(self, *args, **kwargs):  # type: ignore[override]
        for response in self.invoke_stream(*args, **kwargs):
            yield response


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
