"""LLM 提供商配置：base_url 规范化、提供商检测、LLMConfig 加载。L1。"""

from __future__ import annotations

import getpass
import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

from ming_sim.models import (
    LLMConfig,
    CODEX_DEFAULT_MODEL,
    CLAUDE_DEFAULT_MODEL,
    CLI_DEFAULT_RUNNER,
    CLI_DEFAULT_TIMEOUT_SECONDS,
    VALID_CHANNELS,
    API_DEFAULT_TIMEOUT_SECONDS,
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
    "default_headers",  # #1794：附加请求头表（名→值）；空表＝现状
)
# cli.timeout_seconds = 设置页那一格 = 静默判死阈值（#1465 切片③ owner 2026-09-07）。
_CLI_RUNTIME_FIELDS = ("runner", "model", "timeout_seconds", "reasoning_strength")
# #1465：transport 统一策略与 API/CLI 槽平级（ADR 0001 槽位契约不动）。空转阈值不在本段：
# 它的真源是 CLI 槽的 timeout_seconds（设置页那一格），CLI 与 API 同吃，见
# cli_idle_timeout_seconds。

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


def _slot_header_table(value: object) -> Dict[str, str]:
    """#1794 附加请求头表：名→值。非整表 dict 视为空表；不校验头名/值语义。"""
    if not isinstance(value, dict):
        return {}
    return {str(k): "" if v is None else str(v) for k, v in value.items()}


# API slot 的数值字段保持 JSON 数值类型（int/float），让 preserve-save 与 fresh-save 产出
# 同一形态、load 归一也统一类型（#53）。default 与 save_runtime_llm 签名默认对齐。
# 未知键（含旧档残留）由 _api_runtime_slot 只读白名单字段，自然忽略。
_API_NUMERIC_FIELDS = {
    "timeout_seconds": (float, API_DEFAULT_TIMEOUT_SECONDS),
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
        if k in {"reasoning_strength", "thinking_level", "advanced_thinking_level"} and k not in data:
            continue
        if k in _API_NUMERIC_FIELDS:
            caster, default = _API_NUMERIC_FIELDS[k]
            out[k] = _slot_number(data.get(k), caster, default)
        elif k == "advanced_thinking_level":
            out[k] = ""
        elif k == "reasoning_strength":
            out[k] = normalize_reasoning_strength(data.get(k))
        elif k == "default_headers":
            out[k] = _slot_header_table(data.get(k))
        else:
            out[k] = _slot_text(data, k)
    return out


def _cli_runtime_slot(data: Dict[str, object]) -> Dict[str, str]:
    return {
        k: (normalize_reasoning_strength(data.get(k)) if k == "reasoning_strength" else _slot_text(data, k))
        for k in _CLI_RUNTIME_FIELDS
        if k != "reasoning_strength" or k in data
    }


def cli_idle_timeout_seconds(data: Dict[str, object]) -> float:
    """静默判死阈值（秒）解析唯一权威：设置页那一格 = runtime 档 cli.timeout_seconds。

    「距上次新内容这么久没有新动静，就判这次调用已死并重试」——CLI 子进程与 API 流
    共用这一个阈值（#1465 切片③ owner 2026-09-07 拍）。缺段 / 非数 / 非正数一律回落
    CLI_DEFAULT_TIMEOUT_SECONDS；调用方禁第二处 clamp。
    """
    cli = data.get("cli") if isinstance(data, dict) else None
    source = cli if isinstance(cli, dict) else {}
    value = _slot_number(source.get("timeout_seconds"), float, CLI_DEFAULT_TIMEOUT_SECONDS)
    if not (isinstance(value, (int, float)) and value > 0):
        value = CLI_DEFAULT_TIMEOUT_SECONDS
    return float(value)


def _normalize_runtime_llm(data: Dict[str, object]) -> Dict[str, object]:
    """只认 channel / api / cli 槽；不迁移扁平旧输入，不复制顶层 API alias。"""
    channel = str(data.get("channel") or "").strip().lower()
    if channel not in VALID_CHANNELS:
        channel = ""
    api_raw = data.get("api")
    cli_raw = data.get("cli")
    api_raw = api_raw if isinstance(api_raw, dict) else {}
    cli_raw = cli_raw if isinstance(cli_raw, dict) else {}
    # Reading must not turn absent fields into saved explicit defaults.
    api = _api_runtime_slot(api_raw)
    cli = _cli_runtime_slot(cli_raw)
    active_slot = cli if channel == "cli" else api
    active_strength = normalize_reasoning_strength(
        active_slot.get("reasoning_strength", legacy_reasoning_strength(api) if channel != "cli" else "")
    )
    return {
        "channel": channel,
        "api": api,
        "cli": cli,
        "reasoning_strength": active_strength,
    }


def normalize_openai_base_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


def is_deepseek_base_url(base_url: str) -> bool:
    return "deepseek.com" in base_url.lower()


def is_deepseek_model(model: str) -> bool:
    """模型 id 属 DeepSeek 系（含 deepseek/ 前缀与 bare deepseek-* id）。"""
    raw = (model or "").strip().lower()
    if not raw:
        return False
    if raw.startswith("deepseek/"):
        return True
    return openai_model_id_without_provider(model).startswith("deepseek")


def is_dashscope_base_url(base_url: str) -> bool:
    return "dashscope" in base_url.lower() or "aliyuncs" in base_url.lower()


def is_minimax_base_url(base_url: str) -> bool:
    lowered = base_url.lower()
    return "minimaxi.com" in lowered or "minimax.io" in lowered


def provider_extra_body(base_url: str, model: str = "") -> Optional[Dict[str, object]]:
    """Provider 默认 extra_body。

    #1797：DeepSeek 全系关思考——模型 id 决定「要不要关」，键按端点实测分派。
    dashscope/minimax 端点分派必须在 DeepSeek 模型短路之前：
    「非 deepseek.com」不得一律当 Nous 中转。
    - deepseek.com + DeepSeek 系：{"thinking": {"type": "disabled"}}
    - dashscope/aliyuncs（含 DeepSeek 系）：{"enable_thinking": False}
    - minimax（含 DeepSeek 系）：{"thinking": {"type": "disabled"}}
    - 其余中转 + DeepSeek 系：{"reasoning": {"enabled": False}}
      （thinking.disabled 在 Nous/hermes 无效；reasoning.enabled=false 有效）
    """
    # 端点既有键优先：DeepSeek 系跑在百炼/minimax 上仍映射该端点键。
    if is_dashscope_base_url(base_url):
        return {"enable_thinking": False}
    if is_minimax_base_url(base_url):
        return {"thinking": {"type": "disabled"}}
    if is_deepseek_model(model):
        if is_deepseek_base_url(base_url):
            return {"thinking": {"type": "disabled"}}
        return {"reasoning": {"enabled": False}}
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


def _api_runtime_value(runtime: Dict[str, object], key: str, fallback: str) -> str:
    """从 runtime['api'] 槽取字段；档里没有才回落入口入参/env。

    数值槽（timeout_seconds）由调用方另走数值解析，不受这里的字符串化影响。
    """
    api = runtime.get("api") if isinstance(runtime.get("api"), dict) else {}
    value = api.get(key)
    if value is None:
        return fallback
    text = str(value)
    if not text and key not in {"thinking_level", "advanced_thinking_level"}:
        return fallback
    # 占位符 / 保留 sentinel 不当真实 key：stale cli-backend 或 __keep__ 不得
    # 覆盖入口带来的真实 env key（否则 api 通道启动被清空报「未配 API key」）。
    if key.endswith("api_key") and not is_real_api_key(text):
        return fallback
    return text


def llm_config_from_runtime(
    runtime: Dict[str, Any],
    *,
    base_url: str,
    model: str,
    api_key: str,
    timeout_seconds: float,
    thinking_level: str,
    advanced_model: str,
    advanced_base_url: str,
    advanced_api_key: str,
    advanced_thinking_level: str,
) -> LLMConfig:
    """runtime json + 命令行/API 入参 → LLMConfig（#1902 单一投影真源）。

    WebGame 建局与 CLI 建局共用；web 侧不再留第二份同名实现。
    宿主只由运行档声明：channel + cli.runner；环境变量旧路（#1902 已退役）不参与。

    **入参只是回落值，运行档优先**（#1902 F1）：地址、模型、key、超时、思考档与
    advanced 槽一律先取运行档，档里没有才用入口传入/env 的值。此前这段「档覆盖入参」
    的落差只写在 WebGame 里、游戏 CLI 直接把入参当最终值——同一份运行档经两端建局
    得到不同执行事实（CLI 跑默认地址/默认模型/API 超时，Web 跑保存值）。落差归本
    函数一处，两端入口不再各自拼档。
    """
    channel = str(runtime.get("channel") or "").strip().lower()
    if channel not in VALID_CHANNELS:
        # #1902：档里没写通道时按 cli 槽是否已声明 runner 判；旧 env 选宿主的路已退役。
        channel = "cli" if isinstance(runtime.get("cli"), dict) and str(
            (runtime.get("cli") or {}).get("runner") or ""
        ).strip() else "api"
    api_slot = runtime.get("api") if isinstance(runtime.get("api"), dict) else {}
    cli_slot = runtime.get("cli") if isinstance(runtime.get("cli"), dict) else {}
    cli_runner = str(cli_slot.get("runner") or CLI_DEFAULT_RUNNER).strip().lower()
    cli_model = str(cli_slot.get("model") or cli_model_from_env(cli_runner, model)).strip()
    base_url = _api_runtime_value(runtime, "base_url", base_url)
    model = _api_runtime_value(runtime, "model", model)
    api_key = _api_runtime_value(runtime, "api_key", api_key)
    # 超时是数值槽：api 槽有值就用槽值（两端同一口径），否则回落入口/env 入参。
    # #1902 S3：与 load 路径共用 _slot_number，不另维平行浮点取值。
    timeout_seconds = _slot_number(
        api_slot.get("timeout_seconds"),
        float,
        _slot_number(timeout_seconds, float, API_DEFAULT_TIMEOUT_SECONDS),
    )
    # A present empty slot is an explicit default, not an environment fallback.
    thinking_level = _api_runtime_value(
        runtime, "thinking_level", thinking_level or os.environ.get("OPENAI_THINKING_LEVEL", ""),
    )
    advanced_thinking_level = _api_runtime_value(
        runtime, "advanced_thinking_level",
        advanced_thinking_level or os.environ.get("OPENAI_ADVANCED_THINKING_LEVEL", ""),
    )
    advanced_model = _api_runtime_value(runtime, "advanced_model", advanced_model)
    advanced_base_url = _api_runtime_value(runtime, "advanced_base_url", advanced_base_url)
    advanced_api_key = _api_runtime_value(runtime, "advanced_api_key", advanced_api_key)
    legacy_reasoning = (
        legacy_reasoning_strength({
            "advanced_model": advanced_model,
            "advanced_thinking_level": advanced_thinking_level,
            "thinking_level": thinking_level,
        })
        if channel != "cli"
        else ""
    )
    strength_slot = cli_slot if channel == "cli" else api_slot
    reasoning_strength = normalize_reasoning_strength(
        strength_slot.get("reasoning_strength", legacy_reasoning)
    )
    if "reasoning_strength" in strength_slot:
        # The unified selector owns both tiers, including the explicit default.
        thinking_level = advanced_thinking_level = ""
    # 无 saved CLI timeout 时回落 CLI 默认，不回落 API request timeout。
    cli_timeout = _slot_number(cli_slot.get("timeout_seconds"), float, CLI_DEFAULT_TIMEOUT_SECONDS)
    if channel == "cli":
        api_key = ""  # CLI 通道不要 API key；占位符在 create_chat_model 构造 CliChat 时注入
    elif not is_real_api_key(api_key):
        # 占位符不当真 key：清空让下游空检查报「未配 API key」，
        # 而不是拿假 key 去探 OpenAI（误导性 412）。
        api_key = ""
    # #1794：附加头只属 API 槽。
    default_headers = dict(api_slot.get("default_headers") or {})
    return LLMConfig(
        api_key=api_key,
        base_url=normalize_openai_base_url(base_url),
        model=model,
        timeout_seconds=timeout_seconds,
        thinking_level=normalize_thinking_level(thinking_level),
        advanced_model=(advanced_model or "").strip(),
        advanced_base_url=normalize_openai_base_url(advanced_base_url) if advanced_base_url else "",
        advanced_api_key=real_api_key_or_empty(advanced_api_key),
        advanced_thinking_level="",
        reasoning_strength=reasoning_strength,
        channel=channel,
        cli_runner=cli_runner,
        cli_model=cli_model,
        cli_timeout_seconds=cli_timeout,
        default_headers=default_headers,
    )


def resolve_api_key(api_key: str = "") -> str:
    """入参/env 都没有真实 key 时当面索要一次；仍无则 SystemExit。

    唯一「向人要 key」的地方（#1902）：API-only 直调路（闸脚本）与游戏 CLI 入口
    在 API 通道缺 key 时共用此缝，禁各自再写一份 getpass。
    """
    key = (api_key or os.environ.get("OPENAI_API_KEY", "")).strip()
    if not is_real_api_key(key):
        key = ""
    if not key:
        key = getpass.getpass("请输入 API key（不会保存，回车取消）：").strip()
    if not is_real_api_key(key):
        # 手敲的也复验：占位符当真 key 同样拒掉。
        key = ""
    if not key:
        raise SystemExit("未提供 API key，无法使用 LLM。")
    return key


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
    """按 OpenAI 兼容参数构一份 API 通道配置（闸脚本等 API-only 直调用）。

    #1902：本函数不再按 MING_SIM_LLM_BACKEND 选宿主，也不读运行档——CLI 通道的
    配置一律走运行档投影（load_runtime_llm + llm_config_from_runtime），游戏
    CLI 入口与 Web 建局共用那条路；这里只服务「明确只跑 API」的直调。
    """
    api_key = resolve_api_key(api_key)
    adv_base = (advanced_base_url or "").strip()
    normalized_thinking = normalize_thinking_level(thinking_level or os.environ.get("OPENAI_THINKING_LEVEL", ""))
    legacy_reasoning = legacy_reasoning_strength({
        "advanced_model": advanced_model,
        "advanced_thinking_level": advanced_thinking_level or os.environ.get("OPENAI_ADVANCED_THINKING_LEVEL", ""),
        "thinking_level": normalized_thinking,
    })
    reasoning_strength = normalize_reasoning_strength(
        os.environ.get("MING_SIM_REASONING_STRENGTH", legacy_reasoning)
    )
    if "MING_SIM_REASONING_STRENGTH" in os.environ:
        normalized_thinking = ""
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
        channel="api",
        cli_runner="",
        cli_model=cli_model_from_env("", model),
        # 静默判死阈值用 CLI 槽默认，不沿用 API 的 timeout_seconds（codex R1 #2）。
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
            default_headers=dict(cfg.default_headers or {}),
        )
    return cfg


def load_runtime_llm() -> Dict[str, object]:
    """读 data/runtime_llm.json。

    缺档／合法空 → {}（入口可按既有契约回落）。
    读／解析失败与缺档分判：保留真实原因并明示后，仍回落 {}——不另立 fail-fast，
    也不新增整档校验／修档／迁移或第二配置。
    不做 isfile 等元数据预判：预判失败会把权限等真读故障洗成缺档。
    """
    try:
        with open(RUNTIME_LLM_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        # 真缺档：合法空，不挂故障。
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        # 坏档／读失败 ≠ 缺档：保留真实异常对象明示后再回落，禁无痕洗成空配置。
        logger.warning(
            "runtime_llm load failed path=%s", RUNTIME_LLM_PATH,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return {}
    if not isinstance(data, dict):
        err = TypeError(
            f"runtime_llm top-level {type(data).__name__}, expected dict"
        )
        logger.warning(
            "runtime_llm load failed path=%s", RUNTIME_LLM_PATH,
            exc_info=(type(err), err, None),
        )
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
    default_headers: Optional[Dict[str, str]] = None,
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
    # #1794：头表未显式传入时保留既存（旧客户端省略字段不得擦掉）。
    headers_payload = (
        _slot_header_table(default_headers)
        if default_headers is not None
        else _slot_header_table(existing_api.get("default_headers"))
    )
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
            "default_headers": headers_payload,
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
            else existing_api.get("reasoning_strength", "")
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
    if (
        "reasoning_strength" in existing_api
        or (active_channel == "api" and reasoning_strength is not None)
        or api_reasoning_strength is not None
    ):
        api_payload["reasoning_strength"] = api_strength
    # CLI 槽的 reasoning_strength 像 runner/model/timeout 一样按槽保留：保存 API 通道时不得用
    # API 的空强度覆盖/清掉 CLI 槽已存值（cmr #358 r4：跨通道保存丢失 inactive 槽设置——切回
    # CLI 时无声蒸发）。只有保存 CLI 通道、或显式传入强度且无既存 CLI 值时才用本次 strength 更新。
    if active_channel == "cli":
        cli_strength = strength
    else:
        cli_strength = normalize_reasoning_strength(existing_cli.get("reasoning_strength", ""))
    if "reasoning_strength" in existing_cli or (active_channel == "cli" and reasoning_strength is not None):
        cli_payload["reasoning_strength"] = cli_strength
    payload = {
        "channel": active_channel,
        "reasoning_strength": strength,
        "api": api_payload,
        "cli": cli_payload,
    }
    with open(RUNTIME_LLM_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
