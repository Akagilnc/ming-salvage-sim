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
import shutil
import subprocess
import tempfile
import threading
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
# CLI runner 默认模型——单一真源(llm_config.cli_model_from_env 复用,别在第二处重写字面量)。
CODEX_DEFAULT_MODEL = "gpt-5.5"
CLAUDE_DEFAULT_MODEL = "claude-opus-4-8"
_CODEX_BIN = os.environ.get("MING_SIM_CODEX_BIN", "codex")
_CODEX_MODEL = os.environ.get("MING_SIM_CODEX_MODEL", CODEX_DEFAULT_MODEL)
# claude -p 独立进程后端：opus/sonnet/haiku。纯文本输出无日志壳。
# 思考预算不在此强加：claude 走自身默认；要限思考由用户自行 export MAX_THINKING_TOKENS
# （claude -p 继承父进程 env，会自动读到），后端不替用户决定。
_CLAUDE_BIN = os.environ.get("MING_SIM_CLAUDE_BIN", "claude")
_CLAUDE_MODEL = os.environ.get("MING_SIM_CLAUDE_MODEL", CLAUDE_DEFAULT_MODEL)
# 纯角色扮演/抽取任务不需要工具；禁掉防 claude 绕去调工具兜圈子。
_CLAUDE_DISALLOWED = ["Bash", "Read", "Edit", "Write", "Glob", "Grep",
                      "WebFetch", "WebSearch", "Task", "NotebookEdit"]
_CLI_BACKENDS = {"agy", "codex", "claude"}


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
    }


def is_supported_cli_runner(name: object) -> bool:
    """runner 名是否是受支持的 CLI 后端（agy / codex / claude）。"""
    return str(name or "").strip().lower() in _CLI_BACKENDS


# ── runner 可执行定位（GUI/.app 启动 PATH 缺失的治本解）────────────────────
# Finder 双击的 .app 只继承 launchd 精简 PATH（无 ~/.local/bin、/opt/homebrew/bin），
# 裸名 exec "codex"/"claude"/"agy" 会 FileNotFoundError——即便用户已按官方装好。
# 解析成绝对路径即治本：用绝对路径 exec 不依赖 PATH。解析顺序见 _resolve_cli_bin。
_EXTRA_BIN_DIRS = [
    os.path.expanduser("~/.local/bin"),       # codex 官方独立安装 / pipx
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


def _run_codex(prompt: str, model: Optional[str] = None, timeout: Optional[float] = None) -> Tuple[str, int]:
    """调 codex exec -（stdin pipe，绝不 positional）。返回 (文本, 尝试次数=1)。

    实测三坑（见 docs/LLM_BACKEND_BENCH.md §9）：
    - `--skip-git-repo-check`：cwd 是非 git 沙箱目录，不加则秒报 "Not inside a trusted directory"。
    - `--ephemeral`：不落盘 session，否则并发多调撞共享 session 状态（rollout thread not found）丢空输出。
    - 干净最终回话在 **stdout**，诊断/日志在 stderr —— 只取 stdout，绝不合并（合并会把
      "OpenAI Codex v…/tokens used" 等日志混进角色回话）。stdout 空时兜底从合并流剥壳。
    reasoning：默认不强加，尊重用户 ~/.codex/config.toml；设 MING_SIM_CODEX_REASONING 才传 -c。"""
    cmd = [_resolve_cli_bin("codex", _CODEX_BIN), "exec", "--model", (model or _CODEX_MODEL)]
    reasoning = (os.environ.get("MING_SIM_CODEX_REASONING") or "").strip()
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


def _run_claude(prompt: str, model: Optional[str] = None, timeout: Optional[float] = None) -> Tuple[str, int]:
    """调 claude -p（独立进程，stdin pipe）。返回 (纯文本, 1)。
    与 codex 不同：claude -p 干净最终回话在 **stdout**，日志/诊断在 stderr，
    故只取 stdout、不合并 stderr（合并会把日志混进角色回话）。
    思考预算不强加：继承父进程 env，用户可自行 export MAX_THINKING_TOKENS。"""
    cmd = [_resolve_cli_bin("claude", _CLAUDE_BIN), "-p", "--model", (model or _CLAUDE_MODEL),
           "--output-format", "text", "--disallowed-tools", *_CLAUDE_DISALLOWED]
    try:
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit,python.lang.security.audit.dangerous-subprocess-use-tainted-env-args
        # 安全审计(Sourcery):list-form argv、无 shell=True;runner 已 allowlist、model 为独立 argv、prompt 走 stdin → 无注入面。
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            timeout=timeout or _AGY_TIMEOUT, cwd=_AGY_CWD,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("claude 调用超时") from exc
    out = (proc.stdout or "").strip()
    # 非零退出 / 空输出 → 抛错，不静默当空回复落库（CMR F2）。
    if proc.returncode != 0 or not out:
        raise RuntimeError(f"claude 调用失败（退出码 {proc.returncode}）：{(proc.stderr or '')[:200]}")
    return out, 1


def _run_backend(prompt: str) -> Tuple[str, int]:
    """按 MING_SIM_LLM_BACKEND 分派到对应 CLI（enrich/secret 等非 CliChat 路径用）。
    未设或非法 → agy（沿用原默认）。"""
    b = cli_backend_from_env()
    if b == "codex":
        return _run_codex(prompt)
    if b == "claude":
        return _run_claude(prompt)
    return _run_agy(prompt)


def _llm_channel(llm_config: Any = None) -> str:
    return (getattr(llm_config, "channel", "") or "").strip().lower()


def _cli_config_parts(llm_config: Any = None) -> Optional[Tuple[str, str, Optional[float]]]:
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
    return runner, model, timeout


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
            runner, model, timeout = parts
            if runner == "codex":
                text, attempts = _run_codex(prompt, model=model or None, timeout=timeout)
            elif runner == "claude":
                text, attempts = _run_claude(prompt, model=model or None, timeout=timeout)
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
# agy 不做 function-calling，唯一缺口在此。解法很简单：
#   玩家用「拟旨/下密令」按钮 = 消息带「拟旨如下：/密令如下：」前缀 = 已表态要下旨，
#   那这一句大臣回话原文就是这道旨/密令，整段入档即可。不用解析圣旨边界。
#   多轮聊出多道 → 颁诏时玩家去重。大臣本就把相关衙门/人等写进回话（原 prompt 行为）。
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
        "new_title": str(obj.get("新标题") or "").strip()[:20],
        "new_content": str(obj.get("新内容") or "").strip(),
        "deadline_months": _int(obj.get("期限月数"), 36),
        "cultivate_skill": str(obj.get("调教技能") or "").strip()[:20],
        "cultivate_trait": str(obj.get("调教性格") or "").strip()[:20],
    }


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
        "是否在口头任免某人（授官/升迁/调任=任命；革职/罢黜/拿问去职=罢免）。"
        "只输出一个 JSON 对象（无代码围栏、无多余字）：\n"
        "{\n"
        '  "任免动作": "无|任命|罢免",  // 皇帝命某人任/升/调某官=任命；命革/罢/黜某人=罢免；都不是=无\n'
        '  "姓名": "",                 // 被任/被免者确切姓名\n'
        '  "官职": ""                  // 任命时所授官职；罢免可空\n'
        "}\n"
        "判定要点：皇帝口语如「着X任/授X为/升X/调X去/革X职/罢X/拿X」即任免；闲谈、议事、"
        "下密令、拟旨都不算。语义判断，别拘字面。无任免 → 任免动作填「无」、其余留空。\n\n"
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
    return {
        "appoint_action": _action,
        "name": str(obj.get("姓名") or "").strip()[:20],
        "office": str(obj.get("官职") or "").strip()[:40],
    }


def extract_confirmation_intent(
    player_message: str,
    minister_reply: str,
    pending_summaries: List[str],
    llm_config: Any = None,
) -> str:
    """皇帝本轮对【上一轮经大臣领命确认、尚未落库的暂存动作】是应允/拒绝/未表态。
    对话确认(ADR 0006 重设计)：应允 → 当场 commit，拒绝 → 丢，无 → 留。失败/无 → 「无」。"""
    summ = "；".join(pending_summaries) or "（无）"
    prompt = (
        "你是信息抽取器，不扮演。皇帝上一轮经大臣领命确认后，有几条【尚未落库的暂存政务动作】"
        "待皇帝定夺。读皇帝这句话，判断他对这些暂存动作的态度：\n"
        "  应允=准/可/照办/就这么办/依卿所奏/便如此；\n"
        "  拒绝=不必/罢了/再议/不准/作罢/算了；\n"
        "  无=没提这些、继续说别的、含糊未表态。\n"
        "只输出一个 JSON（无代码围栏、无多余字）：{\"确认\":\"应允|拒绝|无\"}。语义判断，别拘字面。\n\n"
        "【待皇帝定夺的暂存动作】" + summ + "\n"
        "【皇帝】" + (player_message or "（无）") + "\n"
        "【大臣回话】" + (minister_reply or "（无）") + "\n"
    )
    raw = ""
    try:
        raw, _ = _run_backend_for_config(prompt, llm_config, tag="confirmation")
    except Exception as exc:  # 抽取失败不阻断对话；当未表态，暂存留到颁诏(算同意)
        _log(f"确认意图抽取失败：{exc}")
    obj = _loads_lenient(raw) or {}
    v = str(obj.get("确认") or "无").strip()
    return v if v in {"应允", "拒绝", "无"} else "无"


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
    body = t[i:j + 1]
    try:
        obj = json.loads(body)
    except (ValueError, TypeError):
        # 严格解析失败才做 JSONC 容错（CMR F8）：模型照 prompt 模板回带 // 行注释或尾逗号时救回。
        # 先严格、失败才清洗 —— 合法 JSON 不经正则，避免误伤串值里的 // 或 ,}（如 "x,}"）。
        # `(?<!:)` 避开字符串里的 :// （如 http://）；尾逗号 `,}`/`,]` → `}`/`]`。
        cleaned = re.sub(r"(?<!:)//[^\n]*", "", body)
        cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
        try:
            obj = json.loads(cleaned)
        except (ValueError, TypeError):
            return None
    return obj if isinstance(obj, dict) else None


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
        '    "new_armies": [{"id":"英文小写id","name":"军名","owner_power":"ming","manpower":兵额(整数,如18000),"maintenance_per_turn":月饷万两(整数),"commander":"主将姓名或空","station":"驻地","troop_type":"步/骑/水/车营","火器":0到100整数(火器局/神机营/火器新军给高),"随军大炮":0到12整数门数(炮营/红夷炮新军给几门)}],\n'
        '    "army_delta": {"既有军id":{"manpower":增兵整数,"火器":增量,"随军大炮":门数增量,"reason":""}},\n'
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
    # 建筑 create 缺 region_id 兜底，免得静默落不了地
    for b in (resolve.get("buildings") or []):
        if isinstance(b, dict) and str(b.get("action") or "").lower() == "create" and not b.get("region_id"):
            b["region_id"] = "beizhili"
    return {
        "effect_on_resolve": resolve,
        "ongoing_effects": _d(norm.get("ongoing_effects")),
        "effect_on_fail": _d(norm.get("effect_on_fail")),
    }


def _extract_secret_order(
    player_command: str,
    minister_reply: str,
    default_assignee: str,
    llm_config: Any = None,
) -> Dict[str, Any]:
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
        raw, _attempts = _run_backend_for_config(prompt, llm_config, tag="secret_extract")
    except Exception as exc:  # 提取失败不阻断：退回默认（trace 已在咽喉记下，含 error）
        _log(f"密令提取失败：{exc}")
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
    minister_reply: str, player_message: str = "", default_assignee: str = "", llm_config: Any = None,
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
        out["secret_order"] = _extract_secret_order(secret_intent, reply, default_assignee, llm_config)

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
        model_id = str(getattr(self, "id", "") or "")
        timeout = getattr(self, "timeout", None)
        if self.backend == "codex":
            return _run_codex(prompt, model=model_id, timeout=timeout)
        if self.backend == "claude":
            return _run_claude(prompt, model=model_id, timeout=timeout)
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
        prompt = _messages_to_prompt(messages, response_format)
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
    """读 MING_SIM_LLM_BACKEND，返回 'agy'/'codex'/'claude' 或 None（走原 api 路径）。"""
    val = (os.environ.get("MING_SIM_LLM_BACKEND") or "").strip().lower()
    return val if val in ("agy", "codex", "claude") else None
