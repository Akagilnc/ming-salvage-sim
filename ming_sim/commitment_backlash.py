"""#626 / ADR 0075 承诺所系反噬涌现硬门。

方案 a（#625 形制）：代码侧确定性硬门，挂邸报前 auto_trigger 既有挂点；
直读承诺/判决/暴露，find_any_issue_by_origin 幂等；不碰 trigger_gate。

与 #623 切割：#623 当回合全国通用余波（metrics 直击 + breach_halfway_setback）
不回撤；本模块只落绑定源承诺的后续事件。同一松手不双扣。

分档：触发侧重算 assess_foundation_tier，零新列；唯 halfway 触发。

P7：硬门只落结构化事实（origin_ref/source_kind/commitment 链接/trigger_ref/
metrics 账）；玩家可见文案由既有叙事 LLM 步生成。
"""

from __future__ import annotations

from typing import Dict, Optional

# 涌现 origin 与 #625 反制隔离
BACKLASH_ORIGIN_KIND = "commitment_backlash"

# 三类触发源（机读；不入玩家可见面）
SOURCE_BREACH_VERDICT = "breach_verdict"          # 事废判决（#623）
SOURCE_FAILED_TERMINAL = "failed_terminal"        # 烂尾终值（#621）
SOURCE_DEFORMATION_EXPOSURE = "deformation_exposure"  # 变形暴露（#622）

SOURCE_KINDS = frozenset({
    SOURCE_BREACH_VERDICT,
    SOURCE_FAILED_TERMINAL,
    SOURCE_DEFORMATION_EXPOSURE,
})

# 具名 metrics 集合（承诺所系一锤子；与 #623 民心-3/皇威-2 直击分立，禁同套双扣）
BACKLASH_NAMED_METRICS: Dict[str, int] = {"民心": -1, "皇威": -1}

def backlash_origin_ref(commitment_id: int, source_kind: str) -> str:
    """幂等键：一承诺一源一类至多一条。"""
    kind = str(source_kind or "").strip()
    if kind not in SOURCE_KINDS:
        raise ValueError(f"unknown backlash source_kind: {source_kind!r}")
    return f"commitment:{int(commitment_id)}:{kind}"


def classify_backlash_source(*, execution_outcome: object) -> Optional[str]:
    """执行格终值 → 触发源类；非本片执行格源返回 None。

    总纲：只读结构化执行格。事废不在此判别——事废=todo.payload_json.verdict
    =='persist' 既判痕迹（#623 finalize_persist；见 trigger 硬门 path ①；
    consumed 单独不得作既判证据）。执行格 failed 默认 failed_terminal。
    """
    outcome = str(execution_outcome or "").strip()
    if outcome == "transformed":
        return SOURCE_DEFORMATION_EXPOSURE
    if outcome == "failed":
        return SOURCE_FAILED_TERMINAL
    return None
