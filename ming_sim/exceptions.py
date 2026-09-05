"""自定义异常。L0 叶子模块。"""

from __future__ import annotations


class ExitGame(Exception):
    pass


class DependencyMismatch(Exception):
    """Installed Python package does not satisfy requirements.txt."""

    def __init__(self, message: str, *, package: str, requirement: str) -> None:
        super().__init__(message)
        self.message = message
        self.package = package
        self.requirement = requirement


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
    def __init__(
        self,
        message: str,
        *,
        raw_value: object = None,
        heal_evidence: object = None,
    ) -> None:
        super().__init__(message)
        self.raw_value = raw_value
        # #1753：颁布判决有界补交耗尽时携带首次+补交坏输出与已合规判决证据。
        self.heal_evidence = heal_evidence


class SettlementAbort(Exception):
    """结算中止可重试（ADR 0008 决定 3/6）。

    extractor 失败 / 结算核代码异常时上抛——绝不静默续跑（半落库 P1 破口）。
    携带 turn / 阶段 / 错误包路径，供上层向玩家提示「本月结算失败，进度已保存，可重试」。
    重试 = 重跑 simulator/extractor（其产出本未持久化），与决定 3 不冲突。
    """

    def __init__(
        self,
        message: str,
        *,
        turn: int,
        stage: str = "extract",
        error_pack_path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.turn = turn
        self.stage = stage
        self.error_pack_path = error_pack_path
