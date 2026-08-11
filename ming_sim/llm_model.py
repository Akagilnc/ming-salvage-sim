"""LLM 模型与 Agno DB 工厂、agent 输出文本提取。L2。"""

from __future__ import annotations

from typing import Dict, Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from openai import APIConnectionError, APIStatusError, APITimeoutError

from ming_sim.exceptions import LLMUnavailable
from ming_sim.llm_config import (
    CLI_BACKEND_PLACEHOLDER,
    is_dashscope_base_url,
    is_deepseek_base_url,
    is_minimax_base_url,
    provider_extra_body,
    supports_openai_reasoning_effort,
)
from ming_sim.llm_contract import fail_if_llm_error
from ming_sim.models import LLMConfig
from ming_sim.token_stats import install_token_stats_patch

_OPENAI_REASONING_BY_STRENGTH = {
    "low": "low",
    "medium": "medium",
    "high": "high",
}
_THINKING_BUDGET_BY_STRENGTH = {
    "low": 2000,
    "medium": 10000,
    "high": 32000,
}


def _openai_reasoning_effort(model: str, reasoning_strength: str, thinking_level: str, enable_thinking: bool) -> str:
    if reasoning_strength == "off":
        model_id = (model or "").strip().lower()
        return "none" if model_id.startswith(("gpt-5.1", "gpt-5.2", "gpt-5.4", "gpt-5.5")) else "minimal"
    if reasoning_strength:
        return _OPENAI_REASONING_BY_STRENGTH.get(reasoning_strength, "")
    if thinking_level:
        return thinking_level
    if enable_thinking:
        return "medium"
    return ""


def _extract_provider_error(error: Exception) -> tuple[str, str, int | None]:
    code = getattr(error, "code", None) or type(error).__name__
    message = str(error)
    status_code = getattr(error, "status_code", None)
    response = getattr(error, "response", None)
    if response is not None:
        try:
            payload = response.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            inner = payload.get("error")
            if isinstance(inner, dict):
                code = inner.get("code") or inner.get("type") or code
                message = inner.get("message") or message
            else:
                code = payload.get("code") or payload.get("type") or code
                message = payload.get("message") or payload.get("detail") or message
    return str(code), str(message), int(status_code) if status_code is not None else None


def llm_unavailable_from_error(error: Exception, stage: str = "LLM 连通性检查") -> LLMUnavailable:
    provider_code, provider_message, status_code = _extract_provider_error(error)
    if isinstance(error, APITimeoutError):
        code = "llm_timeout"
    elif isinstance(error, APIConnectionError):
        code = "llm_connection_error"
    elif isinstance(error, APIStatusError):
        code = f"llm_http_{status_code or 'error'}"
    else:
        code = "llm_error"
    return LLMUnavailable(
        f"{stage}失败：{provider_message}",
        code=code,
        provider_message=provider_message,
        status_code=status_code,
    )


def create_chat_model(
    llm_config: LLMConfig,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    enable_thinking: bool = False,
    thinking_budget: Optional[int] = None,
    top_p: Optional[float] = None,
    force_json_output: bool = False,
    max_retries: int = 1,
) -> OpenAIChat:
    install_token_stats_patch()
    reasoning_strength = (getattr(llm_config, "reasoning_strength", "") or "").strip().lower()
    extra_body = provider_extra_body(llm_config.base_url)
    wants_thinking = enable_thinking or reasoning_strength in {"low", "medium", "high"}
    disables_thinking = reasoning_strength == "off"
    if is_dashscope_base_url(llm_config.base_url) and (wants_thinking or disables_thinking):
        # 推演/评估类 agent 需要深思,开 qwen thinking
        extra_body = {"enable_thinking": not disables_thinking}
        budget = _THINKING_BUDGET_BY_STRENGTH.get(reasoning_strength)
        if budget is not None:
            extra_body["thinking_budget"] = budget
        elif thinking_budget is not None and not disables_thinking:
            extra_body["thinking_budget"] = int(thinking_budget)
    elif enable_thinking and is_deepseek_base_url(llm_config.base_url):
        extra_body = {}  # deepseek-v4 默认深思,清掉 disabled
    elif is_minimax_base_url(llm_config.base_url) and (wants_thinking or disables_thinking):
        # 统一推理强度优先：off→disabled、低/中/高→adaptive。仅在没有统一强度（遗留
        # enable_thinking 路）时才看旧 thinking_level，否则遗留 thinking_level=disabled 会作
        # 隐藏旋钮把用户选的「中/高」压回 disabled（#358 cmr）。
        if disables_thinking:
            thinking_type = "disabled"
        elif reasoning_strength in {"low", "medium", "high"}:
            thinking_type = "adaptive"
        else:
            thinking_type = (llm_config.thinking_level or "adaptive").strip().lower()
            if thinking_type not in {"adaptive", "disabled"}:
                thinking_type = "adaptive"
        extra_body = {"thinking": {"type": thinking_type}, "reasoning_split": True}
    kwargs: Dict[str, object] = {
        "id": llm_config.model,
        "api_key": llm_config.api_key,
        "base_url": llm_config.base_url,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout": llm_config.timeout_seconds,
        "max_retries": max_retries,
        "role_map": {"system": "system", "user": "user", "assistant": "assistant", "tool": "tool"},
        "extra_body": extra_body,
    }
    if top_p is not None:
        kwargs["top_p"] = top_p
    if force_json_output:
        # qwen / OpenAI 兼容协议：强制输出标准 JSON 字符串
        # 走 extra_body 透传给 dashscope；prompt 里必须含 "json" 字样
        if extra_body is None:
            extra_body = {}
        extra_body["response_format"] = {"type": "json_object"}
        kwargs["extra_body"] = extra_body
    if supports_openai_reasoning_effort(llm_config.model):
        effort = _openai_reasoning_effort(
            llm_config.model, reasoning_strength, llm_config.thinking_level, enable_thinking
        )
        if effort:
            kwargs["reasoning_effort"] = effort
    # 探针：新配置用 channel 显式选择执行通道；未声明 channel 的旧路径暂沿用 env fallback。
    # CliChat 继承 OpenAIChat，吃同一套 kwargs；reasoning_effort 等 CLI 无关字段被忽略。
    from ming_sim.cli_backend import CliChat, cli_backend_from_env, is_supported_cli_runner
    channel = (getattr(llm_config, "channel", "") or "").strip().lower()
    backend = None
    if channel == "cli":
        backend = (getattr(llm_config, "cli_runner", "") or cli_backend_from_env() or "agy").strip().lower()
    elif channel != "api":
        backend = cli_backend_from_env()
    if backend is not None and not is_supported_cli_runner(backend):
        # 显式不支持的 runner 在构造期优雅失败，而非首次 invoke 才抛 raw RuntimeError。
        raise LLMUnavailable(f"未知 CLI runner：{backend}（支持 agy / codex / claude）")
    if backend is not None:
        kwargs.pop("reasoning_effort", None)  # CLI 后端不需要，且可能干扰父类校验
        cli_model = (getattr(llm_config, "cli_model", "") or "").strip()
        if cli_model:
            kwargs["id"] = cli_model
        elif channel == "cli":
            # 空 cli_model 不许把 API model 名（kwargs["id"]=llm_config.model）漏给
            # codex/claude 的 --model（RT2）：回落 runner 默认（agy 无 --model→空串）。
            from ming_sim.llm_config import cli_model_from_env
            kwargs["id"] = cli_model_from_env(backend)
        else:
            kwargs["id"] = ""
        cli_timeout = getattr(llm_config, "cli_timeout_seconds", None)
        if cli_timeout:
            kwargs["timeout"] = cli_timeout
        # 占位符只在这一刻注入：满足 OpenAIChat 父类构造（非空 api_key），
        # CliChat 走 CLI 从不用它。LLMConfig.api_key 对 CLI 通道永远是空串，
        # 所以这个 magic-string 不流经任何 key 处理/上报路径。
        kwargs["api_key"] = (kwargs.get("api_key") or "").strip() or CLI_BACKEND_PLACEHOLDER
        kwargs["reasoning_strength"] = (getattr(llm_config, "reasoning_strength", "") or "").strip().lower()
        return CliChat(backend=backend, **kwargs)
    return OpenAIChat(**kwargs)


def create_agno_db(sqlite_path: str) -> SqliteDb:
    return SqliteDb(
        db_file=sqlite_path,
        session_table="agno_sessions",
        memory_table="agno_memories",
    )


def extract_agent_text(run_output: object) -> str:
    missing = object()
    content = getattr(run_output, "content", missing)
    if content is missing:
        text = str(run_output).strip()
    elif content is None:
        text = ""
    else:
        text = str(content).strip()
    fail_if_llm_error(text, "LLM 调用")
    return text


def verify_llm_available(llm_config: LLMConfig) -> None:
    """检查 LLM 是否可用：调用成功（HTTP 200，不抛异常）即算通过，不校验返回内容。"""
    # fresh start 会在验证后删除旧主 DB；CLI 通道也必须真实 smoke，避免 runner 缺失/未登录时先删库。
    from ming_sim.cli_backend import _run_backend_for_config, cli_backend_from_env
    channel = (getattr(llm_config, "channel", "") or "").strip().lower()
    if channel == "cli" or (channel != "api" and cli_backend_from_env() is not None):
        try:
            raw, _ = _run_backend_for_config("输出 ok", llm_config, tag="verify")
            fail_if_llm_error(str(raw), "LLM 连通性检查")
        except LLMUnavailable:
            raise
        except Exception as error:
            raise llm_unavailable_from_error(error) from error
        return
    agent = Agent(
        name="LLM连通性检查",
        id="llm-smoke-test",
        session_id="llm-smoke-test",
        model=create_chat_model(llm_config, temperature=0, max_tokens=8),
        instructions=["只输出 ok。"],
        markdown=False,
    )
    try:
        extract_agent_text(agent.run("输出 ok"))
    except LLMUnavailable:
        raise
    except Exception as error:
        raise llm_unavailable_from_error(error) from error
