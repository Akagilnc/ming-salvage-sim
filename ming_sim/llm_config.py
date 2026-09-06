"""LLM 提供商配置：base_url 规范化、提供商检测、LLMConfig 加载。L1。"""

from __future__ import annotations

import getpass
import json
import os
from typing import Dict, Optional

from ming_sim.models import (
    LLMConfig,
    CODEX_DEFAULT_MODEL,
    CLAUDE_DEFAULT_MODEL,
    CLI_DEFAULT_TIMEOUT_SECONDS,
    VALID_CHANNELS,
    API_DEFAULT_TIMEOUT_SECONDS,
    TRANSPORT_DEFAULT_MAX_ATTEMPTS,
    TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS,
    TRANSPORT_DEFAULT_IDLE_TIMEOUT_SECONDS,
)
from ming_sim.paths import user_data_path

RUNTIME_LLM_PATH = user_data_path("runtime_llm.json")

_API_RUNTIME_FIELDS = (
    "base_url",
    "model",
    "api_key",
    "timeout_seconds",
    "thinking_level",
    "advanced_model",
    "advanced_base_url",
    "advanced_api_key",
    "advanced_thinking_level",
    "reasoning_strength",
)
_CLI_RUNTIME_FIELDS = ("runner", "model", "timeout_seconds", "reasoning_strength")
# #1465：transport 统一策略与 API/CLI 槽平级（ADR 0001 槽位契约不动）
_TRANSPORT_RUNTIME_FIELDS = (
    "max_attempts",
    "attempt_timeout_seconds",
    "idle_timeout_seconds",
)

# CLI 通道在内存里用这个占位符填 LLMConfig.api_key（脱 key 运行），它绝不是真实 key。
CLI_BACKEND_PLACEHOLDER = "cli-backend"

# CLI_DEFAULT_TIMEOUT_SECONDS / VALID_CHANNELS 的 canonical 定义已下沉到 models（L0 叶子，#60），
# 此处经上面的 import re-export，保留 `from ming_sim.llm_config import CLI_DEFAULT_TIMEOUT_SECONDS` 既有路径。


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
# 未知键（含旧档残留）由 _api_runtime_slot 只读白名单字段，自然忽略。
_API_NUMERIC_FIELDS = {
    "timeout_seconds": (float, API_DEFAULT_TIMEOUT_SECONDS),
}
_TRANSPORT_NUMERIC_FIELDS = {
    "max_attempts": (int, TRANSPORT_DEFAULT_MAX_ATTEMPTS),
    "attempt_timeout_seconds": (float, TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS),
    "idle_timeout_seconds": (float, TRANSPORT_DEFAULT_IDLE_TIMEOUT_SECONDS),
}


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
        elif k == "advanced_thinking_level":
            out[k] = ""
        elif k == "reasoning_strength":
            out[k] = normalize_reasoning_strength(data.get(k))
        else:
            out[k] = _slot_text(data, k)
    return out


def _cli_runtime_slot(data: Dict[str, object]) -> Dict[str, str]:
    return {
        k: (normalize_reasoning_strength(data.get(k)) if k == "reasoning_strength" else _slot_text(data, k))
        for k in _CLI_RUNTIME_FIELDS
    }


def _transport_runtime_slot(data: Dict[str, object]) -> Dict[str, object]:
    """#1465 transport 段：与 api/cli 平级；缺省填默认，旧档无段不炸。"""
    out: Dict[str, object] = {}
    for k in _TRANSPORT_RUNTIME_FIELDS:
        caster, default = _TRANSPORT_NUMERIC_FIELDS[k]
        out[k] = _slot_number(data.get(k), caster, default)
    return out


def transport_runtime_slot(data: Dict[str, object]) -> Dict[str, object]:
    """#1465 transport 数值解析唯一公开入口（llm_transport 委派，禁平行 _positive_*）。"""
    return _transport_runtime_slot(data)


def _normalize_runtime_llm(data: Dict[str, object]) -> Dict[str, object]:
    channel = str(data.get("channel") or "").strip().lower()
    if channel not in VALID_CHANNELS:
        # 扁平旧配置只有「存在真实 API key」才推断 api。占位符 + 默认数值字段
        # （timeout 等）不算 api 信号，否则旧 CLI-env 存档被误升成显式
        # API、env CLI 后端被忽略，假 key 还会被送上 API 路径。
        channel = "api" if is_real_api_key(data.get("api_key")) else ""
    api_raw = data.get("api")
    cli_raw = data.get("cli")
    transport_raw = data.get("transport")
    api_source = api_raw if isinstance(api_raw, dict) else data
    api = _api_runtime_slot(api_source)
    cli = _cli_runtime_slot(cli_raw if isinstance(cli_raw, dict) else {})
    transport = _transport_runtime_slot(
        transport_raw if isinstance(transport_raw, dict) else {}
    )
    migrated_api_strength = (
        normalize_reasoning_strength(api.get("reasoning_strength"))
        or normalize_reasoning_strength(data.get("reasoning_strength") if channel != "cli" else "")
        or legacy_reasoning_strength(api_source)
    )
    if migrated_api_strength:
        api["reasoning_strength"] = migrated_api_strength
    cli_strength = normalize_reasoning_strength(cli.get("reasoning_strength"))
    active_strength = cli_strength if channel == "cli" else migrated_api_strength
    out = {
        "channel": channel,
        "api": api,
        "cli": cli,
        "transport": transport,
    }
    # Transitional API aliases keep existing callers working while the UI/API
    # slices move to explicit slots. Keep these even when CLI is active.
    out.update(api)
    out["reasoning_strength"] = active_strength
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


def openai_model_id_without_provider(model: str) -> str:
    """剥 provider 前缀（openai/gpt-5.x → gpt-5.x），供推理族识别。"""
    model_id = (model or "").strip().lower()
    if "/" in model_id:
        model_id = model_id.rsplit("/", 1)[-1]
    return model_id


def supports_openai_reasoning_effort(model: str) -> bool:
    # #1461：任意 OpenAI 兼容配置可能带 provider 前缀（openai/gpt-5.x）
    model_id = openai_model_id_without_provider(model)
    return model_id.startswith(("o1", "o3", "o4", "gpt-5"))


REASONING_STRENGTH_CHOICES = (
    {"value": "", "label": "默认"},
    {"value": "off", "label": "关"},
    {"value": "low", "label": "低"},
    {"value": "medium", "label": "中"},
    {"value": "high", "label": "高"},
)


def api_supports_reasoning_strength(base_url: str, model: str) -> bool:
    return (
        supports_openai_reasoning_effort(model)
        or is_dashscope_base_url(base_url)
        or is_minimax_base_url(base_url)
    ) and not is_deepseek_base_url(base_url)


def cli_supports_reasoning_strength(runner: str) -> bool:
    # #1271：懒导入委派 cli_backend 单源（同文件 load_llm_config :251 先例），禁本处手写名单。
    from ming_sim.cli_backend import CLI_REASONING_STRENGTH_RUNNERS
    return str(runner or "").strip().lower() in CLI_REASONING_STRENGTH_RUNNERS


def normalize_thinking_level(level: str) -> str:
    return (level or "").strip()


def normalize_reasoning_strength(value: object) -> str:
    strength = str(value or "").strip().lower()
    return strength if strength in {"off", "low", "medium", "high"} else ""


def legacy_reasoning_strength(data: Dict[str, object]) -> str:
    candidates = []
    if str(data.get("advanced_model") or "").strip():
        candidates.append(data.get("advanced_thinking_level"))
    candidates.append(data.get("thinking_level"))
    for value in candidates:
        legacy = str(value or "").strip().lower()
        if legacy in {"minimal", "disabled", "none"}:
            return "off"
        strength = normalize_reasoning_strength(legacy)
        if strength:
            return strength
    return ""


def cli_model_from_env(runner: str, fallback: str = "") -> str:
    # 默认模型复用 models 的单一真源常量(#60：原懒-import cli_backend 已消，改 top-level import models)。
    if runner == "codex":
        return (os.environ.get("MING_SIM_CODEX_MODEL") or CODEX_DEFAULT_MODEL).strip()
    if runner == "claude":
        return (os.environ.get("MING_SIM_CLAUDE_MODEL") or CLAUDE_DEFAULT_MODEL).strip()
    return fallback


def load_llm_config(
    base_url: str,
    model: str,
    api_key: str = "",
    timeout_seconds: float = API_DEFAULT_TIMEOUT_SECONDS,
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
    normalized_thinking = normalize_thinking_level(thinking_level or os.environ.get("OPENAI_THINKING_LEVEL", ""))
    legacy_reasoning = legacy_reasoning_strength({
        "advanced_model": advanced_model,
        "advanced_thinking_level": advanced_thinking_level or os.environ.get("OPENAI_ADVANCED_THINKING_LEVEL", ""),
        "thinking_level": normalized_thinking,
    })
    reasoning_strength = (
        normalize_reasoning_strength(os.environ.get("MING_SIM_REASONING_STRENGTH", ""))
        or legacy_reasoning
    )
    return LLMConfig(
        api_key=api_key,
        base_url=normalize_openai_base_url(base_url),
        model=model,
        timeout_seconds=timeout_seconds,
        thinking_level=normalized_thinking,
        advanced_model=(advanced_model or "").strip(),
        advanced_base_url=normalize_openai_base_url(adv_base) if adv_base else "",
        advanced_api_key=real_api_key_or_empty(advanced_api_key),
        advanced_thinking_level="",
        reasoning_strength=reasoning_strength,
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
            timeout_seconds=cfg.timeout_seconds,
            thinking_level="",
            advanced_model=cfg.advanced_model,
            advanced_base_url=cfg.advanced_base_url,
            advanced_api_key=cfg.advanced_api_key,
            advanced_thinking_level="",
            reasoning_strength=cfg.reasoning_strength,
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


def save_runtime_llm(
    base_url: str,
    model: str,
    api_key: str,
    timeout_seconds: float = API_DEFAULT_TIMEOUT_SECONDS,
    thinking_level: str = "",
    advanced_model: str = "",
    advanced_base_url: str = "",
    advanced_api_key: str = "",
    advanced_thinking_level: str = "",
    channel: str = "api",
    cli_runner: Optional[str] = None,
    cli_model: Optional[str] = None,
    cli_timeout_seconds: Optional[float] = None,
    reasoning_strength: Optional[str] = None,
    api_reasoning_strength: Optional[str] = None,
    transport_max_attempts: Optional[int] = None,
    transport_attempt_timeout_seconds: Optional[float] = None,
    transport_idle_timeout_seconds: Optional[float] = None,
) -> None:
    """写 data/runtime_llm.json。明文存盘——按用户选择。"""
    os.makedirs(os.path.dirname(RUNTIME_LLM_PATH), exist_ok=True)
    active_channel = (channel or "api").strip().lower()
    if active_channel not in VALID_CHANNELS:
        active_channel = "api"
    existing = load_runtime_llm()
    existing_api = existing.get("api") if isinstance(existing.get("api"), dict) else {}
    existing_cli = existing.get("cli") if isinstance(existing.get("cli"), dict) else {}
    existing_transport = (
        existing.get("transport") if isinstance(existing.get("transport"), dict) else {}
    )
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
            "timeout_seconds": timeout_seconds,
            "thinking_level": normalize_thinking_level(thinking_level),
            "advanced_model": (advanced_model or "").strip(),
            "advanced_base_url": (advanced_base_url or "").strip(),
            "advanced_api_key": (advanced_api_key or "").strip(),
            "advanced_thinking_level": "",
        }
    )
    cli_payload = {
        "runner": (cli_runner if cli_runner is not None else str(existing_cli.get("runner", ""))).strip(),
        "model": (cli_model if cli_model is not None else str(existing_cli.get("model", ""))).strip(),
        "timeout_seconds": (
            cli_timeout_seconds
            if cli_timeout_seconds is not None
            else existing_cli.get("timeout_seconds", "")
        ),
    }
    if reasoning_strength is None:
        strength_source = (
            existing_cli.get("reasoning_strength", "")
            if active_channel == "cli"
            else existing_api.get("reasoning_strength") or existing.get("reasoning_strength", "")
        )
        strength = normalize_reasoning_strength(strength_source)
    else:
        strength = normalize_reasoning_strength(reasoning_strength)
    api_strength = (
        strength
        if active_channel == "api"
        else normalize_reasoning_strength(api_reasoning_strength)
        if api_reasoning_strength is not None
        else normalize_reasoning_strength(existing_api.get("reasoning_strength"))
    )
    if isinstance(api_payload, dict):
        api_payload["reasoning_strength"] = api_strength
    # CLI 槽的 reasoning_strength 像 runner/model/timeout 一样按槽保留：保存 API 通道时不得用
    # API 的空强度覆盖/清掉 CLI 槽已存值（cmr #358 r4：跨通道保存丢失 inactive 槽设置——切回
    # CLI 时无声蒸发）。只有保存 CLI 通道、或显式传入强度且无既存 CLI 值时才用本次 strength 更新。
    if active_channel == "cli":
        cli_strength = strength
    else:
        cli_strength = normalize_reasoning_strength(existing_cli.get("reasoning_strength", ""))
    if cli_strength:
        cli_payload["reasoning_strength"] = cli_strength
    # #1465：transport 段与通道保存正交——显式传入覆盖，否则保留既存/默认（ADR 0001 平级）。
    transport_src = dict(existing_transport)
    if transport_max_attempts is not None:
        transport_src["max_attempts"] = transport_max_attempts
    if transport_attempt_timeout_seconds is not None:
        transport_src["attempt_timeout_seconds"] = transport_attempt_timeout_seconds
    if transport_idle_timeout_seconds is not None:
        transport_src["idle_timeout_seconds"] = transport_idle_timeout_seconds
    transport_payload = _transport_runtime_slot(transport_src)
    payload = {
        "channel": active_channel,
        "reasoning_strength": strength,
        "api": api_payload,
        "cli": cli_payload,
        "transport": transport_payload,
    }
    with open(RUNTIME_LLM_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
