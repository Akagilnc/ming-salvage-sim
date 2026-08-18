"""#626 / ADR 0075 承诺所系反噬涌现硬门。

方案 a（#625 形制）：代码侧确定性硬门，挂邸报前 auto_trigger 既有挂点；
直读承诺/判决/暴露，find_any_issue_by_origin 幂等；不碰 trigger_gate。

与 #623 切割：#623 当回合全国通用余波（metrics 直击 + breach_halfway_setback）
不回撤；本模块只落绑定源承诺的后续事件。同一松手不双扣。

分档：触发侧重算 assess_foundation_tier，零新列；唯 halfway 触发。
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

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

# 呈现面：与 #625 bar「反噬平息/坐大」区分
BACKLASH_BAR_GOOD = "所系余波已平"
BACKLASH_BAR_BAD = "所系局势恶化"

# 玩家可见面禁词（AC6 哨兵；含系统词 + #625 反制 bar 用语）
BACKLASH_BANNED_PLAYER_TOKENS = (
    "commitment_backlash",
    "foundation_tier",
    "assess_foundation_tier",
    "trigger_commitment_backlash",
    "breach_verdict",
    "failed_terminal",
    "deformation_exposure",
    "BACKLASH_NAMED_METRICS",
    "反噬平息",
    "反噬坐大",
    "反噬涌现",
    "supervision_countermeasure",
)


def backlash_origin_ref(commitment_id: int, source_kind: str) -> str:
    """幂等键：一承诺一源一类至多一条。"""
    kind = str(source_kind or "").strip()
    if kind not in SOURCE_KINDS:
        raise ValueError(f"unknown backlash source_kind: {source_kind!r}")
    return f"commitment:{int(commitment_id)}:{kind}"


def classify_backlash_source(
    *,
    execution_outcome: object,
    execution_note: object,
) -> Optional[str]:
    """执行格终值 → 触发源类；非本片三类返回 None。"""
    outcome = str(execution_outcome or "").strip()
    note = str(execution_note or "")
    if outcome == "transformed":
        return SOURCE_DEFORMATION_EXPOSURE
    if outcome == "failed":
        # #623 场面判词「事废」落 note；其余 failed = 烂尾终值（#621）
        if "事废" in note:
            return SOURCE_BREACH_VERDICT
        return SOURCE_FAILED_TERMINAL
    return None


def assert_no_backlash_banned_tokens(text: object, *, surface: str) -> None:
    raw = str(text or "")
    for token in BACKLASH_BANNED_PLAYER_TOKENS:
        if token in raw:
            raise AssertionError(f"{surface} 裸露禁词：{token!r}")


def build_backlash_copy(
    *,
    commitment_title: str,
    source_kind: str,
) -> Tuple[str, str, str]:
    """玩家可见 title / stage / narrative；禁系统词与 #625 反制用语。"""
    title_base = str(commitment_title or "前诺").strip() or "前诺"
    title = f"{title_base}所系余波"
    if source_kind == SOURCE_DEFORMATION_EXPOSURE:
        stage = f"{title_base}名实已乖，所系之局反受其累。"
        narrative = f"变形暴露后，{title_base}牵动的局势恶化。"
    elif source_kind == SOURCE_BREACH_VERDICT:
        stage = f"半途撤手，{title_base}所系之局反受其累。"
        narrative = f"事废之后，{title_base}牵动的沉没投入化为负累。"
    else:
        stage = f"{title_base}终至不济，所系之局反受其累。"
        narrative = f"烂尾之后，{title_base}牵动的局势恶化。"
    return title[:80], stage[:120], narrative[:400]
