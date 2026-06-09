"""LLM 提供商配置：base_url 规范化、提供商检测、LLMConfig 加载。L1。"""

from __future__ import annotations

import getpass
import json
import os
from typing import Dict, Optional

from ming_sim.models import LLMConfig
from ming_sim.paths import user_data_path

RUNTIME_LLM_PATH = user_data_path("runtime_llm.json")
RUNTIME_GAME_PATH = user_data_path("runtime_game.json")

# 游戏玩法设置默认值（全局，跨局共享）。
GAME_SETTINGS_DEFAULTS = {
    "hitl_min_decisions": 1,  # 每回合 simulator 至少产出的重大决策点数（0=不强制，宁缺毋滥）
}

_API_RUNTIME_FIELDS = (
    "base_url",
    "model",
    "api_key",
    "max_tokens",
    "timeout_seconds",
    "thinking_level",
    "advanced_model",
    "advanced_base_url",
    "advanced_api_key",
    "advanced_thinking_level",
)
_CLI_RUNTIME_FIELDS = ("runner", "model", "timeout_seconds")

# CLI 通道在内存里用这个占位符填 LLMConfig.api_key（脱 key 运行），它绝不是真实 key。
CLI_BACKEND_PLACEHOLDER = "cli-backend"

# CLI 子进程默认超时（秒）。与 LLMConfig.cli_timeout_seconds 默认对齐；CLI 通道的
# timeout 单一真源——别拿 API 的 timeout_seconds（默认 180）当 CLI 子进程超时（codex R1）。
CLI_DEFAULT_TIMEOUT_SECONDS = 300.0

# 合法执行通道集合——单一真源,新增通道只改这里（#55）。
VALID_CHANNELS = frozenset({"api", "cli"})


def is_real_api_key(value: object) -> bool:
    """真实 API key？空、占位符 cli-backend、保留-sentinel `__keep__` 都不算。
    所有「该不该按 api 通道推断 / 是否已配 key」的判断统一走这里（单一真源）。
    `__keep__` 是 web 层「保留当前」sentinel,绝不是真实 key——在此单点拦截,防它被
    存盘 / 送上 OpenAI client / 误触发 api 通道（Red Team #51-57）。"""
    key = str(value or "").strip()
    return bool(key and key != CLI_BACKEND_PLACEHOLDER and key != "__keep__")


def real_api_key_or_empty(value: object) -> str:
    """任何会流向 HTTP/OpenAI client 的 key 赋值都过这里：真实 key 原样，
    占位符/空归一成空串。fallback 链写成 real_api_key_or_empty(adv) or real_api_key_or_empty(main)。"""
    key = str(value or "").strip()
    return key if is_real_api_key(key) else ""


def _slot_text(data: Dict[str, object], key: str) -> str:
    value = data.get(key, "")
    return "" if value is None else str(value)


# API slot 的数值字段保持 JSON 数值类型（int/float），让 preserve-save 与 fresh-save 产出
# 同一形态、load 归一也统一类型（#53）。default 与 save_runtime_llm 签名默认对齐。
_API_NUMERIC_FIELDS = {"max_tokens": (int, 8000), "timeout_seconds": (float, 180.0)}


def _slot_number(value: object, caster, default):
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        return caster(value)
    except (TypeError, ValueError):
        try:
            return caster(float(value))  # "4096.0" / 含小数的字符串兜底
        except (TypeError, ValueError):
            return default


def _api_runtime_slot(data: Dict[str, object]) -> Dict[str, object]:
    out: Dict[str, object] = {}
    for k in _API_RUNTIME_FIELDS:
        if k in _API_NUMERIC_FIELDS:
            caster, default = _API_NUMERIC_FIELDS[k]
            out[k] = _slot_number(data.get(k), caster, default)
        else:
            out[k] = _slot_text(data, k)
    return out


def _cli_runtime_slot(data: Dict[str, object]) -> Dict[str, str]:
    return {k: _slot_text(data, k) for k in _CLI_RUNTIME_FIELDS}


def _normalize_runtime_llm(data: Dict[str, object]) -> Dict[str, object]:
    channel = str(data.get("channel") or "").strip().lower()
    if channel not in VALID_CHANNELS:
        # 扁平旧配置只有「存在真实 API key」才推断 api。占位符 + 默认数值字段
        # （max_tokens/timeout 等）不算 api 信号，否则旧 CLI-env 存档被误升成显式
        # API、env CLI 后端被忽略，假 key 还会被送上 API 路径。
        channel = "api" if is_real_api_key(data.get("api_key")) else ""
    api_raw = data.get("api")
    cli_raw = data.get("cli")
    api = _api_runtime_slot(api_raw if isinstance(api_raw, dict) else data)
    cli = _cli_runtime_slot(cli_raw if isinstance(cli_raw, dict) else {})
    out = {"channel": channel, "api": api, "cli": cli}
    # Transitional API aliases keep existing callers working while the UI/API
    # slices move to explicit slots. Keep these even when CLI is active.
    out.update(api)
    return out


def normalize_openai_base_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


def is_deepseek_base_url(base_url: str) -> bool:
    return "deepseek.com" in base_url.lower()


def is_dashscope_base_url(base_url: str) -> bool:
    return "dashscope" in base_url.lower() or "aliyuncs" in base_url.lower()


def is_minimax_base_url(base_url: str) -> bool:
    lowered = base_url.lower()
    return "minimaxi.com" in lowered or "minimax.io" in lowered


def provider_extra_body(base_url: str) -> Optional[Dict[str, object]]:
    if is_deepseek_base_url(base_url):
        return {"thinking": {"type": "disabled"}}
    if is_dashscope_base_url(base_url):
        return {"enable_thinking": False}
    if is_minimax_base_url(base_url):
        return {"thinking": {"type": "disabled"}}
    return None


def supports_openai_reasoning_effort(model: str) -> bool:
    model_id = model.lower()
    return model_id.startswith(("o1", "o3", "o4", "gpt-5"))


def normalize_thinking_level(level: str) -> str:
    return (level or "").strip()


def cli_model_from_env(runner: str, fallback: str = "") -> str:
    # 默认模型复用 cli_backend 的单一真源常量,不重写字面量（#55）。
    from ming_sim.cli_backend import CODEX_DEFAULT_MODEL, CLAUDE_DEFAULT_MODEL
    if runner == "codex":
        return (os.environ.get("MING_SIM_CODEX_MODEL") or CODEX_DEFAULT_MODEL).strip()
    if runner == "claude":
        return (os.environ.get("MING_SIM_CLAUDE_MODEL") or CLAUDE_DEFAULT_MODEL).strip()
    return fallback


def load_llm_config(
    base_url: str,
    model: str,
    api_key: str = "",
    timeout_seconds: float = 180.0,
    thinking_level: str = "",
    advanced_model: str = "",
    advanced_base_url: str = "",
    advanced_api_key: str = "",
    advanced_thinking_level: str = "",
) -> LLMConfig:
    api_key = (api_key or os.environ.get("OPENAI_API_KEY", "")).strip()
    # 探针：MING_SIM_LLM_BACKEND=agy|codex 时走本地 CLI，无需 api key。
    # CLI 通道下 api_key 留空——占位符只在 create_chat_model 构造 CliChat 时注入，
    # 不让 magic-string 进 LLMConfig.api_key、不流经任何 key 路径。
    from ming_sim.cli_backend import cli_backend_from_env
    cli_runner = cli_backend_from_env()
    if cli_runner is not None:
        api_key = ""  # CLI 模式不要 API key
    else:
        # API 模式才要真实 key：占位符不算，空则索要/报错，别拿假 key 探 OpenAI。
        if not is_real_api_key(api_key):
            api_key = ""
        if not api_key:
            api_key = getpass.getpass("请输入 API key（不会保存，回车取消）：").strip()
        if not is_real_api_key(api_key):
            # 手敲的也复验：占位符当真 key 同样拒掉。
            api_key = ""
        if not api_key:
            raise SystemExit("未提供 API key，无法使用 LLM。")
    adv_base = (advanced_base_url or "").strip()
    return LLMConfig(
        api_key=api_key,
        base_url=normalize_openai_base_url(base_url),
        model=model,
        timeout_seconds=timeout_seconds,
        thinking_level=normalize_thinking_level(thinking_level or os.environ.get("OPENAI_THINKING_LEVEL", "")),
        advanced_model=(advanced_model or "").strip(),
        advanced_base_url=normalize_openai_base_url(adv_base) if adv_base else "",
        advanced_api_key=real_api_key_or_empty(advanced_api_key),
        advanced_thinking_level=normalize_thinking_level(
            advanced_thinking_level or os.environ.get("OPENAI_ADVANCED_THINKING_LEVEL", "")
        ),
        channel="cli" if cli_runner else "api",
        cli_runner=cli_runner or "",
        cli_model=cli_model_from_env(cli_runner or "", model),
        # CLI 子进程超时用 CLI 默认，不沿用 API 的 timeout_seconds（codex R1 #2）。
        cli_timeout_seconds=CLI_DEFAULT_TIMEOUT_SECONDS,
    )


# 角色 → 用 advanced model 还是 main model。
# 推演 / 打分 是回合结算的核心叙事 + 结构化抽取，最吃模型能力，单独走 advanced。
# 其余 agent（大臣对话、诏书润色、记忆检索、JSON 修复、聊天记忆抽取）保持 main，省钱保缓存。
_ADVANCED_ROLES = frozenset({"simulator", "extractor"})


def for_role(cfg: LLMConfig, role: str) -> LLMConfig:
    """按 agent 角色派生 LLMConfig：advanced 角色用 advanced_model（若已配），其余用 main model。
    advanced_model 为空时返回原 cfg（无任何替换）。"""
    if role in _ADVANCED_ROLES and (cfg.advanced_model or "").strip():
        adv_base = (cfg.advanced_base_url or "").strip() or cfg.base_url
        # advanced/主 key 回落都过 real_api_key_or_empty（防御性：CLI 通道下 cfg.api_key
        # 现已是空串，占位符只活在 create_chat_model 构造 CliChat 那一刻）。
        adv_key = real_api_key_or_empty(cfg.advanced_api_key) or real_api_key_or_empty(cfg.api_key)
        return LLMConfig(
            api_key=adv_key,
            base_url=adv_base,
            model=cfg.advanced_model.strip(),
            max_tokens=cfg.max_tokens,
            timeout_seconds=cfg.timeout_seconds,
            thinking_level=cfg.advanced_thinking_level,
            advanced_model=cfg.advanced_model,
            advanced_base_url=cfg.advanced_base_url,
            advanced_api_key=cfg.advanced_api_key,
            advanced_thinking_level=cfg.advanced_thinking_level,
            channel=cfg.channel,
            cli_runner=cfg.cli_runner,
            cli_model=cfg.cli_model,
            cli_timeout_seconds=cfg.cli_timeout_seconds,
        )
    return cfg


def load_runtime_llm() -> Dict[str, object]:
    """读 data/runtime_llm.json。缺/坏返回空 dict。"""
    if not os.path.isfile(RUNTIME_LLM_PATH):
        return {}
    try:
        with open(RUNTIME_LLM_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return _normalize_runtime_llm(data)


def load_runtime_game() -> Dict[str, object]:
    """读 data/runtime_game.json（全局玩法设置）。缺/坏字段回落默认。"""
    data: Dict[str, object] = {}
    if os.path.isfile(RUNTIME_GAME_PATH):
        try:
            with open(RUNTIME_GAME_PATH, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}
    out: Dict[str, object] = dict(GAME_SETTINGS_DEFAULTS)
    try:
        out["hitl_min_decisions"] = max(0, min(5, int(data.get("hitl_min_decisions", out["hitl_min_decisions"]))))
    except (TypeError, ValueError):
        pass
    return out


def save_runtime_game(hitl_min_decisions: int) -> Dict[str, object]:
    """写 data/runtime_game.json。clamp 到 [0,5]。返回落盘后的设置。"""
    os.makedirs(os.path.dirname(RUNTIME_GAME_PATH), exist_ok=True)
    payload = {"hitl_min_decisions": max(0, min(5, int(hitl_min_decisions)))}
    with open(RUNTIME_GAME_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return payload


def save_runtime_llm(
    base_url: str,
    model: str,
    api_key: str,
    max_tokens: int = 8000,
    timeout_seconds: float = 180.0,
    thinking_level: str = "",
    advanced_model: str = "",
    advanced_base_url: str = "",
    advanced_api_key: str = "",
    advanced_thinking_level: str = "",
    channel: str = "api",
    cli_runner: Optional[str] = None,
    cli_model: Optional[str] = None,
    cli_timeout_seconds: Optional[float] = None,
) -> None:
    """写 data/runtime_llm.json。明文存盘——按用户选择。"""
    os.makedirs(os.path.dirname(RUNTIME_LLM_PATH), exist_ok=True)
    active_channel = (channel or "api").strip().lower()
    if active_channel not in VALID_CHANNELS:
        active_channel = "api"
    existing = load_runtime_llm()
    existing_api = existing.get("api") if isinstance(existing.get("api"), dict) else {}
    existing_cli = existing.get("cli") if isinstance(existing.get("cli"), dict) else {}
    api_inputs = (
        base_url,
        model,
        api_key,
        thinking_level,
        advanced_model,
        advanced_base_url,
        advanced_api_key,
        advanced_thinking_level,
    )
    preserve_api = active_channel == "cli" and not any((value or "").strip() for value in api_inputs)
    api_payload = (
        _api_runtime_slot(existing_api)
        if preserve_api
        else {
            "base_url": (base_url or "").strip(),
            "model": (model or "").strip(),
            "api_key": (api_key or "").strip(),
            "max_tokens": max_tokens,
            "timeout_seconds": timeout_seconds,
            "thinking_level": normalize_thinking_level(thinking_level),
            "advanced_model": (advanced_model or "").strip(),
            "advanced_base_url": (advanced_base_url or "").strip(),
            "advanced_api_key": (advanced_api_key or "").strip(),
            "advanced_thinking_level": normalize_thinking_level(advanced_thinking_level),
        }
    )
    payload = {
        "channel": active_channel,
        "api": api_payload,
        "cli": {
            "runner": (cli_runner if cli_runner is not None else str(existing_cli.get("runner", ""))).strip(),
            "model": (cli_model if cli_model is not None else str(existing_cli.get("model", ""))).strip(),
            "timeout_seconds": (
                cli_timeout_seconds
                if cli_timeout_seconds is not None
                else existing_cli.get("timeout_seconds", "")
            ),
        },
    }
    with open(RUNTIME_LLM_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
