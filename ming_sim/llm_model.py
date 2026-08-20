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
        # 关思考：按族默认，禁止再续 gpt-5.x 版本清单（#1452 gpt-5.6 曾掉表外→minimal）。
        # 遗留 o1 只认 minimal；gpt-5* / o3 / o4 及未知新族默认 none。
        if model_id.startswith("o1"):
            return "minimal"
        return "none"
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


# #1299/#1310：CLI runner / agent run 失败时玩家可见文案——短、diegetic、可重试；
# 机器横幅只进 provider_message，永不进 content 叙事通道。
CLI_RUNNER_PLAYER_MESSAGE = "通传未达，请稍后再召。"


def cli_runner_unavailable(
    error: BaseException,
    *,
    backend: str = "",
) -> LLMUnavailable:
    """CliChat/runner 自身失败 → typed LLMUnavailable（错误串不得当台词）。"""
    provider = str(error) if error is not None else ""
    code = "llm_cli_error"
    if backend:
        code = f"llm_cli_{backend}"
    return LLMUnavailable(
        CLI_RUNNER_PLAYER_MESSAGE,
        code=code,
        provider_message=provider or CLI_RUNNER_PLAYER_MESSAGE,
    )


def llm_stream_unavailable(provider_message: object = "") -> LLMUnavailable:
    """RunErrorEvent → typed；玩家 message 单源 CLI_RUNNER_PLAYER_MESSAGE。"""
    p = str(provider_message or "").strip() or CLI_RUNNER_PLAYER_MESSAGE
    return LLMUnavailable(CLI_RUNNER_PLAYER_MESSAGE, code="llm_stream_error", provider_message=p)


def create_chat_model(
    llm_config: LLMConfig,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    enable_thinking: bool = False,
    thinking_budget: Optional[int] = None,
    top_p: Optional[float] = None,
    force_json_output: bool = False,
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
        "timeout": llm_config.timeout_seconds,
        "max_retries": 1,
        "role_map": {"system": "system", "user": "user", "assistant": "assistant", "tool": "tool"},
        "extra_body": extra_body,
    }
    # 未显式配置（None/≤0）不发 max_tokens，取提供商官方上限；>0 才注入。
    if max_tokens is not None and int(max_tokens) > 0:
        kwargs["max_tokens"] = int(max_tokens)
    # OpenAI 推理族（gpt-5*/o*）拒 top_p：luna 回 HTTP 400 空 assistant → agno
    # "Unknown model error" / 流式空回（#1452）。temperature 仍可传。
    if top_p is not None and not supports_openai_reasoning_effort(llm_config.model):
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
    from ming_sim.cli_backend import (
        CliChat,
        cli_backend_from_env,
        is_supported_cli_runner,
        supported_cli_runners_text,
    )
    channel = (getattr(llm_config, "channel", "") or "").strip().lower()
    backend = None
    if channel == "cli":
        backend = (getattr(llm_config, "cli_runner", "") or cli_backend_from_env() or "agy").strip().lower()
    elif channel != "api":
        backend = cli_backend_from_env()
    if backend is not None and not is_supported_cli_runner(backend):
        # 显式不支持的 runner 在构造期优雅失败，而非首次 invoke 才抛 raw RuntimeError。
        # 支持名单文案单一真源 = supported_cli_runners_text()（#1256）。
        raise LLMUnavailable(
            f"未知 CLI runner：{backend}（支持 {supported_cli_runners_text()}）"
        )
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


def _run_output_status_is_error(run_output: object) -> bool:
    """agno Agent.run 失败时 status=RunStatus.error（值 'ERROR'），content=str(exc)。

    #1299/#1310：此 status 是 runner/provider 失败的权威信号；不得把 content 当叙事放行。
    """
    status = getattr(run_output, "status", None)
    if status is None:
        return False
    raw = getattr(status, "value", status)
    return str(raw).strip().upper() in {"ERROR", "FAILED"}


def extract_agent_text(run_output: object) -> str:
    missing = object()
    content = getattr(run_output, "content", missing)
    if content is missing:
        text = str(run_output).strip()
    elif content is None:
        text = ""
    else:
        text = str(content).strip()
    # #1299/#1310：治本在缝——ERROR status 翻 typed，错误串永不得进 content 当叙事。
    # fail_if_llm_error 标记集只覆盖 API 认证错，不再是唯一护栏。
    if _run_output_status_is_error(run_output):
        raise LLMUnavailable(
            CLI_RUNNER_PLAYER_MESSAGE,
            code="llm_run_error",
            provider_message=text or "run status=ERROR",
        )
    fail_if_llm_error(text, "LLM 调用")
    return text


def verify_llm_available(llm_config: LLMConfig) -> None:
    """用户主动校验 LLM 配置是否可用（设置页提交等）：调用成功即过，不校验返回内容。"""
    # 仅服务配置校验入口；启动/新开/继续/重置路径不再调用本函数。
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
    # 推理模型（luna/glm/kimi/ds-v4 等）会先耗 thinking tokens；8 会被思考耗尽回空，
    # agno 抛 Unknown model error，好模型被烟测误杀。一次校验成本可忽略，预算放宽。
    agent = Agent(
        name="LLM连通性检查",
        id="llm-smoke-test",
        session_id="llm-smoke-test",
        model=create_chat_model(llm_config, temperature=0, max_tokens=512),
        instructions=["只输出 ok。"],
        markdown=False,
    )
    try:
        run_output = agent.run("输出 ok")
        try:
            extract_agent_text(run_output)
        except LLMUnavailable:
            # docstring 本义：调用成功即过，不校验返回内容。空 content（含 ERROR status
            # 但正文为空——推理耗尽等）不作失败；非空正文的真错（认证标记等）仍上抛。
            content = getattr(run_output, "content", None)
            if content is None or not str(content).strip():
                return
            raise
    except LLMUnavailable:
        raise
    except Exception as error:
        raise llm_unavailable_from_error(error) from error
