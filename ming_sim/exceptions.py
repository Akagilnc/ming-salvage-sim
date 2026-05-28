"""自定义异常。L0 叶子模块。"""

from __future__ import annotations


class ExitGame(Exception):
    pass


class LLMUnavailable(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "llm_unavailable",
        provider_message: str = "",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.provider_message = provider_message or message
        self.status_code = status_code


class LLMContractError(Exception):
    pass
