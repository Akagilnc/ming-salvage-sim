"""#626 / ADR 0075 承诺所系反噬涌现硬门。

方案 a（#625 形制）：代码侧确定性硬门，挂邸报前 auto_trigger 既有挂点；
直读承诺/判决/暴露，find_any_issue_by_origin 幂等；不碰 trigger_gate。

与 #623 切割：#623 当回合全国通用余波（metrics 直击 + breach_halfway_setback）
不回撤；本模块只落绑定源承诺的后续事件。同一松手不双扣。

分档：触发侧重算 assess_foundation_tier，零新列；唯 halfway 触发。

P7：硬门只落结构化事实（origin_ref/source_kind/commitment 链接/trigger_ref/
metrics 账）；玩家可见文案由既有叙事 LLM 步从特征化输入长出（与 new_issues
同格）。『与 #625 用语区分』以特征约束传给叙事步，不落代码文案常量。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

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


def classify_backlash_source(*, execution_outcome: object) -> Optional[str]:
    """执行格终值 → 触发源类；非本片执行格源返回 None。

    总纲：只读结构化执行格。事废不在此判别——事废=consumed 哭谏绑定
    （#623 结构化既判，见 trigger 硬门 path ①）。执行格 failed 默认 failed_terminal。
    """
    outcome = str(execution_outcome or "").strip()
    if outcome == "transformed":
        return SOURCE_DEFORMATION_EXPOSURE
    if outcome == "failed":
        return SOURCE_FAILED_TERMINAL
    return None


def assert_no_backlash_banned_tokens(text: object, *, surface: str) -> None:
    raw = str(text or "")
    for token in BACKLASH_BANNED_PLAYER_TOKENS:
        if token in raw:
            raise AssertionError(f"{surface} 裸露禁词：{token!r}")


def parse_backlash_origin_ref(origin_ref: object) -> tuple[int, str]:
    """origin_ref → (commitment_id, source_kind)；非法则 (0, "")."""
    raw = str(origin_ref or "").strip()
    parts = raw.split(":")
    if len(parts) != 3 or parts[0] != "commitment":
        return 0, ""
    try:
        cid = int(parts[1])
    except (TypeError, ValueError):
        return 0, ""
    kind = str(parts[2] or "").strip()
    if kind not in SOURCE_KINDS:
        return 0, ""
    return cid, kind


def build_backlash_narrative_features(db: Any) -> List[Dict[str, object]]:
    """特征化输入包：供既有叙事 LLM 步（simulator/extractor）长出玩家文案。

    与 new_issues LLM 路径同格——引擎只供结构化事实与呈现约束，不供成句模板。
    『与 #625 用语区分』经 presentation_constraints.avoid_phrases 传入，非 bar 常量。
    """
    rows = db.conn.execute(
        """
        SELECT i.id, i.origin_ref, i.title,
               (
                   SELECT a.trigger_ref FROM issue_advances a
                   WHERE a.issue_id = i.id
                     AND a.trigger_kind = 'commitment_backlash'
                   ORDER BY a.id DESC LIMIT 1
               ) AS trigger_ref
        FROM issues i
        WHERE i.origin_kind = ? AND i.status = 'active'
        ORDER BY i.id
        """,
        (BACKLASH_ORIGIN_KIND,),
    ).fetchall()
    features: List[Dict[str, object]] = []
    for row in rows:
        origin_ref = str(row["origin_ref"] or "")
        cid, source_kind = parse_backlash_origin_ref(origin_ref)
        commitment_title = ""
        if cid > 0:
            crow = db.conn.execute(
                "SELECT title FROM issues WHERE id=?", (cid,),
            ).fetchone()
            if crow is not None:
                commitment_title = str(crow["title"] or "")
        if not commitment_title:
            # 回退：硬门可能以源承诺 title 作 issue 标题链接（仍是既有事实，非新模板）
            commitment_title = str(row["title"] or "")
        trigger_ref = str(row["trigger_ref"] or "")
        if not trigger_ref and cid > 0:
            trigger_ref = f"issue:{cid}"
        features.append({
            "issue_id": int(row["id"]),
            "commitment_ref": int(cid),
            "commitment_title": commitment_title,
            "source_kind": source_kind,
            "origin_ref": origin_ref,
            "trigger_ref": trigger_ref,
            "metrics_delta": dict(BACKLASH_NAMED_METRICS),
            # 特征约束→叙事步：与 #625 bar「反噬平息/坐大」区分；禁系统词入玩家面
            "presentation_constraints": {
                "avoid_phrases": ["反噬平息", "反噬坐大"],
                "banned_system_tokens": [
                    "commitment_backlash",
                    "foundation_tier",
                    "breach_verdict",
                    "failed_terminal",
                    "deformation_exposure",
                ],
            },
        })
    return features
