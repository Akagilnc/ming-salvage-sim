"""结算 payload 的请旨解析与批红选项校验。请旨来自逐旨／世界段推演，不从邸报抽取。"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

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
        event_id = str(obj.get("event_id") or obj.get("origin_ref") or "").strip()
        if event_id:
            decision["event_id"] = event_id
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


def bind_decisions_to_candidate_events(
    decisions: List[Dict[str, object]],
    simulator_payload: object,
) -> List[Dict[str, object]]:
    """Bind decision event_id to the AUTHORITATIVE candidate snapshot (#389).

    The candidate snapshot — not the simulator's free-text echo — is the source of
    truth (#389 裁决：用权威候选快照确定性绑定，不依赖 simulator 回显 event_id）:
    - A simulator-echoed event_id is trusted ONLY if it actually belongs to this
      turn's candidate snapshot (the normal correct-echo path → 行为不变).
    - A missing id, OR an echoed id that is NOT in the snapshot (omitted→misfilled /
      hallucinated), binds on a unique exact title match inside
      simulator_payload.candidate_events. We do not let an off-snapshot id win over
      the snapshot just because the LLM wrote it.
    - Non-event HITL decisions keep no event_id (nothing to bind). An echoed
      off-snapshot id with no unique title match is UNBOUND (event_id removed) — the
      snapshot gives no basis to trust it, and leaving it would let submit_decisions
      write a non-candidate id into the event ledger as 'triggered' (see the inline
      comment on the `elif explicit` branch below). A genuinely absent id with no
      title match simply stays unbound.
    """
    if not decisions:
        return []
    if not isinstance(simulator_payload, dict):
        return [dict(d) for d in decisions]
    raw_candidates = simulator_payload.get("candidate_events")
    if not isinstance(raw_candidates, list):
        return [dict(d) for d in decisions]

    candidate_ids: set[str] = set()
    title_to_ids: Dict[str, List[str]] = {}
    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        event_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or "").strip()
        if not event_id:
            continue
        candidate_ids.add(event_id)
        if title:
            title_to_ids.setdefault(title, []).append(event_id)

    bound: List[Dict[str, object]] = []
    for decision in decisions:
        out = dict(decision)
        explicit = str(out.get("event_id") or "").strip()
        if explicit and explicit in candidate_ids:
            bound.append(out)  # 回显 id 确属本回合候选 → 采信（正常路径行为不变）
            continue
        # #1490/#1492 A：仅当 options 带齐 dossier_id+dossier_decision 时保留
        # dossier: 前缀（真批红待裁）。裸 origin_ref 回填 / LLM 幻觉行照旧解绑，
        # 否则 due-commitment 同形会空对空过先验 → phase2 批红卡死。
        if explicit.startswith("dossier:") and decision_has_rescript_capability(out):
            bound.append(out)
            continue
        # 缺 id，或回显 id 不在权威候选快照里：以快照唯一标题为准（重）绑，不被 LLM 回显牵着走。
        title = str(out.get("title") or "").strip()
        ids = title_to_ids.get(title) or []
        unique_ids = {event_id for event_id in ids if event_id}
        if len(unique_ids) == 1:
            out["event_id"] = next(iter(unique_ids))
        elif explicit:
            # off-snapshot 回显 id 且无唯一标题可绑 → 解绑，不保留这个非候选 id（codex
            # correctness）：留着它会被 submit_decisions 当 'triggered' 写进事件账，若它其实是
            # 一个真实的未来事件 id，就被永久标成已触发、再也进不了候选池（gather_candidate_events
            # 跳过 spawned）。解绑后该选择仍在
            # pending_decisions.choice_json，不污染终态账。正常含【候选内】id 的路径不受影响。
            out.pop("event_id", None)
        bound.append(out)
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
