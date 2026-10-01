"""结算 payload 的请旨解析与批红选项校验。请旨来自逐旨／世界段推演，不从邸报抽取。"""

from __future__ import annotations

import json
import re
from typing import (
    TYPE_CHECKING, Dict, List, Mapping, Optional, Sequence, Tuple,
)

from ming_sim.action_clusters import season_option_fields, validate_season_option
from ming_sim.models import effect_dict_has_work

if TYPE_CHECKING:
    from ming_sim.db import GameDB
    from ming_sim.models import GameState

# 批红玩家 disposition 动作枚举（生成端 options 同集）
RESCRIPT_CAPABILITY_DECISIONS = frozenset({
    "force_promulgated", "withdrawn", "hold",
})

# 逐旨／世界段预推的请旨机标；不解析邸报正文。
# 只匹配显式机标本体；邻接 whitespace 属原文，不得一并消费（P6 / #671 / ADR 0142）
_DECISION_RE = re.compile(r"<<DECISION>>\s*(\{.*?\})\s*<<END>>", re.DOTALL)
MAX_DECISIONS_PER_TURN = 5


def bind_decision_options(options: object) -> Dict[str, Dict[str, object]]:
    """Bind normalized labels to stored options, rejecting ambiguous decisions."""
    bound: Dict[str, Dict[str, object]] = {}
    if not isinstance(options, list):
        raise ValueError("decision options 须为 list")
    for option in options:
        if not isinstance(option, dict):
            continue
        label = str(option.get("label") or "").strip()
        if not label or label in bound:
            raise ValueError(f"decision option label 为空或重复：{label!r}")
        bound[label] = option
    return bound


def parse_decision_blocks(text: str) -> List[Dict[str, object]]:
    """读取世界段请旨机标中的决策列表，不改写原文。

    每块须含 title/context/options（2-3 项，每项 label + 可选 hint）。
    解析失败的块忽略，最多取 MAX_DECISIONS_PER_TURN 条。
    """
    decisions: List[Dict[str, object]] = []
    for m in _DECISION_RE.finditer(text or ""):
        if len(decisions) >= MAX_DECISIONS_PER_TURN:
            break
        try:
            obj = json.loads(m.group(1))
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        title = str(obj.get("title") or "").strip()
        raw_opts = obj.get("options")
        if not title or not isinstance(raw_opts, list):
            continue
        options: List[Dict[str, object]] = []
        for o in raw_opts:
            if not isinstance(o, dict):
                continue
            label = str(o.get("label") or "").strip()
            if not label:
                continue
            try:
                action_type = validate_season_option(o)
            except ValueError:
                options = []
                break
            option: Dict[str, object] = {
                "label": label,
                "hint": str(o.get("hint") or "").strip(),
            }
            # Deterministic financial options carry their executable payload;
            # label/hint remain presentation only.
            for key in season_option_fields(action_type):
                if key in o:
                    option[key] = action_type if key == "action_type" else o[key]
            options.append(option)
        try:
            bind_decision_options(options)
        except ValueError:
            continue
        if len(options) < 2:  # 至少给 2 个选项才算有效抉择
            continue
        decision = {
            "title": title,
            "context": str(obj.get("context") or "").strip(),
            "options": options[:3],
        }
        # 事件身份只认请旨块自己的 event_id。origin_ref 是另一条来源，不得冒充
        # 已核对的事件 id（ADR 0115：不从旁路键猜配）。dossier 旧块仍把 origin_ref
        # 填进 event_id，但带上来源标记，世界请旨绑定不把它当快照回显。
        explicit_event_id = str(obj.get("event_id") or "").strip()
        origin_ref = str(obj.get("origin_ref") or "").strip()
        if explicit_event_id:
            decision["event_id"] = explicit_event_id
        elif origin_ref:
            decision["event_id"] = origin_ref
            decision["event_id_from_origin_ref"] = True
        decisions.append(decision)
    return decisions


def parse_rescript_capability_pair(
    option: object,
) -> Optional[Tuple[int, str]]:
    """共享校验器：合法批红能力对 → (正整数 dossier_id, 支持动作枚举)。

    非法（缺字段 / 非正整数 id / 未知 decision / 非 dict）一律 None。
    bind 保留、allowed/matched 构造、decision_has_rescript_capability 均走此缝
    （CodeRabbit Major on #1494：从『非 None』收紧）。
    """
    if not isinstance(option, dict):
        return None
    raw_id = option.get("dossier_id")
    # bool 是 int 子类，须先排除；拒绝 0/负与不可转 int 的值
    if isinstance(raw_id, bool) or raw_id is None:
        return None
    try:
        dossier_id = int(raw_id)
    except (TypeError, ValueError):
        return None
    if dossier_id <= 0:
        return None
    decision = option.get("dossier_decision")
    if not isinstance(decision, str) or decision not in RESCRIPT_CAPABILITY_DECISIONS:
        return None
    return (dossier_id, decision)


def decision_has_rescript_capability(decision: object) -> bool:
    """批红轨识别：options 含至少一对合法能力对（#1490/#1492 A / #1494）。

    仅 event_id 的 dossier: 前缀不够——due-commitment / backlash 等决策块会把
    origin_ref=dossier:N 回填成 event_id，但 options 只有 {label,hint}。那些行
    不是批红待裁，不得按 rescript 轨处理。能力对须经 parse_rescript_capability_pair
    （正整数 id + 支持动作枚举），裸非 None 残对不算。
    """
    if not isinstance(decision, dict):
        return False
    options = decision.get("options") or []
    if not isinstance(options, list):
        return False
    for opt in options:
        if parse_rescript_capability_pair(opt) is not None:
            return True
    return False


def bind_decisions_to_authoritative_snapshot(
    decisions: List[Dict[str, object]],
    snapshot: Sequence[Mapping[str, object]],
) -> List[Dict[str, object]]:
    """Bind each decision's event_id against an AUTHORITATIVE id/title snapshot.

    ADR 0115:5 — 绑定真源＝推送期分配的稳定键（权威快照），绑定由构造与核对保证，
    不靠事后从自由文里捞 id：

    - 回显 id **只在确属本快照时**才认（正常正确回显路径行为不变）。
    - 缺 id 或回显 id 不在快照里：按快照内**唯一同名标题**绑（重），不被回显牵着走。
    - 仍绑不上：解绑（``event_id`` 移除）。该选择仍留在 pending_decisions.choice_json，
      不写事件终态账；绑不上的请旨由供料侧续呈，不在此猜配。

    任何调用方都只应把本函数的输出当作绑定结果，不得再从原文重推。
    """
    bound: List[Dict[str, object]] = []
    snapshot_ids: set[str] = set()
    title_to_ids: Dict[str, List[str]] = {}
    for item in snapshot:
        event_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or "").strip()
        if not event_id:
            continue
        snapshot_ids.add(event_id)
        if title:
            title_to_ids.setdefault(title, []).append(event_id)

    for decision in decisions:
        out = dict(decision)
        explicit = str(out.get("event_id") or "").strip()
        if explicit and explicit in snapshot_ids:
            bound.append(out)
            continue
        title = str(out.get("title") or "").strip()
        ids = {event_id for event_id in (title_to_ids.get(title) or []) if event_id}
        if len(ids) == 1:
            out["event_id"] = next(iter(ids))
        elif explicit:
            out.pop("event_id", None)
        bound.append(out)
    return bound


def bind_decisions_to_candidate_events(
    decisions: List[Dict[str, object]],
    simulator_payload: object,
) -> List[Dict[str, object]]:
    """Bind decision event_id to the AUTHORITATIVE candidate snapshot (#389).

    The candidate snapshot — not the simulator's free-text echo — is the source of
    truth (#389 裁决：用权威候选快照确定性绑定，不依赖 simulator 回显 event_id)：

    - 回显 id 确属本回合候选快照 → 采信（正常路径行为不变）。
    - ``dossier:`` 前缀只在 options 带齐 dossier_id+dossier_decision（真批红待裁）时
      保留；裸 origin_ref 回填 / 幻觉行照旧解绑，否则 due-commitment 同形会空对空过
      先验 → phase2 批红卡死（#1490/#1492 A）。
    - 其余按 :func:`bind_decisions_to_authoritative_snapshot` 的唯一标题规则处理。
    """
    if not decisions:
        return []
    if not isinstance(simulator_payload, dict):
        return [dict(d) for d in decisions]
    raw_candidates = simulator_payload.get("candidate_events")
    if not isinstance(raw_candidates, list):
        return [dict(d) for d in decisions]
    snapshot = [item for item in raw_candidates if isinstance(item, Mapping)]
    kept_dossier = {
        index for index, decision in enumerate(decisions)
        if isinstance(decision, Mapping)
        and str(decision.get("event_id") or "").strip().startswith("dossier:")
        and decision_has_rescript_capability(decision)
    }
    bound = bind_decisions_to_authoritative_snapshot(decisions, snapshot)
    for index, decision in enumerate(decisions):
        if index in kept_dossier:
            bound[index]["event_id"] = str(decision.get("event_id") or "").strip()
    return bound


def list_due_commitments(db: GameDB, state: GameState) -> List[Dict[str, object]]:
    """到期的 form③ 一次性承诺供邸报作者读取；不自动结案。"""
    rows = db.conn.execute(
        """
        SELECT * FROM issues
        WHERE status='active'
          AND commitment_kind != ''
          AND end_turn > 0
          AND end_turn <= ?
        ORDER BY id
        """,
        (int(state.turn),),
    ).fetchall()
    due_commitments: List[Dict[str, object]] = []
    from ming_sim.staged_commitment import should_skip_form3_due_for_staged
    for row in rows:
        if effect_dict_has_work(row["ongoing_effects"]):
            continue
        # #620：仅段派生 end_turn 改道 next_audience_todos；独立 end_turn 待裁保留 form③
        # （不停轮仅约束分段路径，0074/0076）。
        stages_raw = row["stages_json"]
        end_turn_val = int(row["end_turn"] or 0)
        if should_skip_form3_due_for_staged(stages_raw, end_turn_val):
            continue
        due_commitments.append({
            "entry_kind": "due_commitment",
            "issue_id": int(row["id"]),
            "title": str(row["title"] or ""),
            "content": str(row["stage_text"] or row["title"] or "")[:120],
            "origin_ref": str(row["origin_ref"] or ""),
            "turn_issued": int(row["origin_turn"] or 0),
            "due_turn": int(row["end_turn"] or 0),
            "progress": "无持续效果，期限届满。",
            "review_reason": "到期待裁：未来一次性承诺已到期，请提到皇帝面前定夺，不得自动结案。",
        })
    return due_commitments
