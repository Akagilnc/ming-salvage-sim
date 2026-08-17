"""大臣奏对高亮判官（#544 / ADR 0045）。

生成完成后的独立机器面短调用：读成品全文，输出硬格式 JSON 承重短语清单。
超时/坏输出/判官失败 → 空清单（产品面永不挡回话）；异常边界带日志，不宽吞代码 bug。
不在 Python 侧重写 markdown 剥离（剥离与匹配真源在 web/src/format.ts + 前端匹配链）。
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, List

from ming_sim.exceptions import LLMContractError, LLMUnavailable
from ming_sim.llm_model import extract_agent_text

logger = logging.getLogger(__name__)

# 几秒级上限（ADR 0045：非流式折窗的封顶；超时即回话先行无高亮）
DEFAULT_HIGHLIGHT_JUDGE_TIMEOUT_S = 8.0


def parse_highlight_judge_output(raw: str) -> List[str]:
    """硬格式 JSON → 短语清单；不合规/契约失败 → 空清单（票面授权的坏输出降级）。"""
    text = str(raw or "").strip()
    if not text:
        return []
    from ming_sim.agents import parse_agent_json

    try:
        data = parse_agent_json(text, "高亮判官")
    except (LLMContractError, json.JSONDecodeError, TypeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    items = data.get("highlights")
    if not isinstance(items, list):
        return []
    out: List[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        phrase = item.strip()
        if phrase:
            out.append(phrase)
    return out


def run_highlight_judge(
    *,
    minister_reply: str,
    llm_config: Any,
    agent: Any = None,
    timeout_s: float = DEFAULT_HIGHLIGHT_JUDGE_TIMEOUT_S,
) -> List[str]:
    """同通道短调用；超时/坏输出/判官失败 → []（一层带日志边界，零副作用）。"""
    reply = str(minister_reply or "").strip()
    if not reply:
        return []
    try:
        timeout = float(timeout_s)
    except (TypeError, ValueError):
        timeout = DEFAULT_HIGHLIGHT_JUDGE_TIMEOUT_S
    if timeout <= 0:
        timeout = DEFAULT_HIGHLIGHT_JUDGE_TIMEOUT_S

    def _call() -> List[str]:
        local_agent = agent
        if local_agent is None:
            from ming_sim.agents import create_highlight_judge_agent

            local_agent = create_highlight_judge_agent(llm_config)
        prompt = (
            "下面是大臣已经说完的奏对全文（可能含 organic markdown 标记，可作信号）。"
            "请挑出承重短语清单，只输出 JSON object：{\"highlights\":[\"短语\",...]}。"
            "短语须尽量取原文片段；不要解释。\n\n"
            f"【大臣奏对】\n{reply}"
        )
        output = local_agent.run(prompt)
        raw = extract_agent_text(output) if output is not None else ""
        if not raw and hasattr(output, "content"):
            raw = str(getattr(output, "content") or "")
        return parse_highlight_judge_output(raw)

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(_call)
        try:
            return list(future.result(timeout=timeout))
        except FuturesTimeout:
            # 不 wait 卡住调用方——超时即降级；worker 随进程回收
            future.cancel()
            return []
        except (LLMContractError, LLMUnavailable) as exc:
            logger.warning("highlight judge degraded (contract/unavailable): %s", exc)
            return []
        except Exception as exc:
            # 判官调用失败（模型/provider）→ 产品面空清单；必须留痕，不得与合法空清单不可区分
            logger.warning("highlight judge degraded: %s", exc, exc_info=True)
            return []
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
