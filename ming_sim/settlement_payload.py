"""结算 payload 工具：与事务/恢复/相位无关的纯/准纯函数（#91 coordinator 拆分第一刀）。

从 decree.py 抽出——这些是叶子函数（解析邸报决策块、密令分组承载、已裁决策正文、玩家可见
呈现脱敏 + 注入文案常量），无 state 写 / 无事务 / 无相位转移、从不被测试 monkeypatch，
故可纯搬家、行为保持。decree.py 仍 re-import 它们保 `from ming_sim.decree import X` 公开表面。

真正的事务编排 / 恢复路由 / error-pack / 相位 coordinator 拆分**不在此**——那些函数的契约
是隐式的 `monkeypatch.setattr(decree_mod, ...)`（几十处测试 patch decree 模块级名），跨模块搬会
静默破坏 monkeypatch（测试仍绿但行为变），须配设计讨论决定 patch 焊点与相位守门归属。
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Dict, List, Mapping, Optional, Set, Tuple

from ming_sim.action_clusters import season_option_fields, validate_season_option
from ming_sim.models import effect_dict_has_work

if TYPE_CHECKING:  # GameDB 仅用于 _select_secret_orders_for_sim 的类型注解（已 `from __future__ annotations`
    from ming_sim.db import GameDB  # 惰性字符串）；不在运行时 import db，使本模块运行时零 db 依赖（线上 sourcery）
    from ming_sim.models import GameState

# 批红玩家 disposition 动作枚举（与 _chosen_rescript_actions / 生成端 options 同集）
RESCRIPT_CAPABILITY_DECISIONS = frozenset({
    "force_promulgated", "withdrawn", "hold",
})

CHEAT_NARRATIVE_PREFIX = (
    "【天命强制·结算优先】以下为既成事实，最高优先级，先于一切规则与档位上限。"
    "你必须把它当作本回合百分百已发生的结果，按字面抽满对应结构化增量，"
    "无视合理性、史实、盘面、对手反扑、涨幅上限——它说什么成了就抽什么。"
    "数值类（如「国库增至九千万」）按当前值算差额一次性入账；"
    "局势结案按字面写满 bar 并结案；人物/军队/势力存亡按字面落 status/势力变化。"
    "与下方正常邸报冲突时以本段为准，本段没提的下方照常抽。照字面落库：\n"
)

# HITL 决策点：皇帝亲裁后，把所选选项+自由批语作为「圣意既定」拼到邸报最前喂 extractor。
# 与 cheat 同机制（既成事实、最高优先级），但语气是皇帝御断而非天命强制。
DECISION_NARRATIVE_PREFIX = (
    "【圣意亲裁·结算优先】以下为本回合月末重大抉择，陛下已御笔亲断，最高优先级。"
    "你必须把每条裁断当作百分百已发生的结果，按其方向抽对应结构化增量与事项推进，"
    "与下方正常邸报冲突时以本段为准。各条裁断如下：\n"
)

# 决策块边界标记。simulator 在邸报末尾按规范输出，本回合解析后从 narrative 剥离。
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


def parse_decision_blocks(narrative: str) -> tuple[str, List[Dict[str, object]]]:
    """从邸报抽 <<DECISION>>...<<END>> JSON 块，返回 (剥离后的干净邸报, 决策列表)。

    每块须含 title/context/options（2-3 项，每项 label + 可选 hint）。
    解析失败的块直接丢弃（连同标记一起剥离），不抛断——无决策块视作普通回合。
    最多取 MAX_DECISIONS_PER_TURN 条，超出忽略。
    """
    decisions: List[Dict[str, object]] = []
    for m in _DECISION_RE.finditer(narrative or ""):
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
            option: Dict[str, object] = {
                "label": label,
                "hint": str(o.get("hint") or "").strip(),
            }
            # Deterministic financial options carry their executable payload;
            # label/hint remain presentation only.
            action_type = str(o.get("action_type") or "")
            for key in season_option_fields(action_type):
                if key in o:
                    option[key] = o[key]
            try:
                validate_season_option(option)
            except ValueError:
                options = []
                break
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
    # #671 / P6 / ADR 0142：剥离 DECISION 机标后不得 strip 邸报原文（零删改）
    clean = _DECISION_RE.sub("", narrative or "")
    return clean, decisions


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
            # 跳过 spawned）；season_simulator 也明示非候选抉择不应带 event_id。解绑后该选择仍在
            # pending_decisions.choice_json，不污染终态账。正常含【候选内】id 的路径不受影响。
            out.pop("event_id", None)
        bound.append(out)
    return bound


def group_secret_orders_for_sim(
    rows: List[Dict[str, object]],
) -> Dict[str, List[Dict[str, object]]]:
    """把密令 DB 行按状态分进中文键两组，作喂 extractor 独立 rail 的承载形状（#48 / #883）。

    输入 = db.list_secret_orders 返回的行（含英文 status）；输出 =
    `{"在办": [...], "待核议": [...]}`。英文 status 只用来分组，
    **不当字段进 LLM 输入**（#48：status 不进 LLM——否则下游叙事/UI 会冒出
    「孙承宗密旨（active）」）。条目保留
    id/minister_name/title/content[:120]/turn_issued/due_turn/progress/sim_note，不含 status。
    #1504：待核议组只承载 due_commitment ACK；密令结案不再由 LLM 产出。
    非 active 密令落到此函数时忽略不进任何组。

    #883：本分组只喂 personnel_secret extractor 独立 rail；simulator 公共轨不收密令正文，
    只见 `build_simulator_payload` 派生的扁平 `due_commitments`。
    """
    groups: Dict[str, List[Dict[str, object]]] = {"在办": [], "待核议": []}
    bucket = {"active": "在办"}
    # 调用方输入可能不是 list；此处保持边界容错。
    # 或含非 dict 元素，照 simulation._clean_* 的守门惯例跳过，不让 TypeError 崩在恢复链上。
    if not isinstance(rows, list):
        return groups
    for o in rows:
        if not isinstance(o, dict):
            continue
        key = bucket.get(o.get("status"))
        if key is None:
            continue
        # 字符串字段一律 str() 兜底：损坏存档里若为非字符串（如 content 是整数），切片/落库
        # 不致 TypeError（照 simulation._clean_* 的 `str(item.get(...) or "")` 惯例）。
        groups[key].append({
            "id": int(o.get("id") or 0),
            "minister_name": str(o.get("minister_name") or ""),
            "title": str(o.get("title") or ""),
            "content": str(o.get("content") or "")[:120],
            "turn_issued": o.get("turn_issued") or 0,
            "due_turn": o.get("due_turn") or 0,
            # DB 行的进展在 result；已分组过的旧承载条目在 progress——两者都收，使本函数
            # 能就地重分组旧 list 形状 ctx（恢复端归一，见 _recovered_grouped）。
            "progress": str(o.get("result") or o.get("progress") or ""),
            "sim_note": str(o.get("sim_note") or ""),     # 上轮推演写的副作用
        })
    return groups


def _recovered_grouped(value: object) -> Dict[str, object]:
    """恢复路把存档里的 secret_orders 归一成分组 dict（#48 恢复端闭环）。

    新档已是分组 dict → 原样返回。**部署前存的旧 list 形状 ctx** → 按状态重分组、剥英文
    status（旧条目仍带 status，可据以分桶）：否则把扁平 list 透传给改读 `secret_orders.在办`/
    `待核议` 的新 extractor prompt，HITL 续跑会漏抽密令副作用/结案。其余杂值 → 空 dict。
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return group_secret_orders_for_sim(value)
    return {}


def _select_secret_orders_for_sim(db: GameDB, cap: int = 20) -> List[Dict[str, object]]:
    """选注入月末推演的密令：仅 active。

    到期结案改 settle 尾部机械对账；「待核议」分组现只承载 due_commitment ACK（见 augment）。
    """
    active = db.list_secret_orders(status="active")
    return active[: max(0, int(cap))]


def augment_secret_orders_with_due_commitments(
    secret_orders: object,
    db: GameDB,
    state: GameState,
) -> Dict[str, List[Dict[str, object]]]:
    """把 form③ 到期待裁承诺并入 secret_orders 分组（extractor 轨复用待核议通道）。

    ADR 0013 D3/D9 要求：无 ongoing_effects、仅 end_turn 的未来一次性承诺，到期不 close，
    但要从 active_issues 背景顶成本回合显式待裁输入。本函数在分组的
    `secret_orders["待核议"]` 里追加带 `entry_kind:"due_commitment"` 的条目；
    simulator 轨另由 `build_simulator_payload` 从分组抠出扁平顶层 `due_commitments`
    （公开轨），分组本身只留给 extractor。
    """
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
    if not due_commitments:
        return secret_orders if isinstance(secret_orders, dict) else {}

    groups: Dict[str, List[Dict[str, object]]] = {"在办": [], "待核议": []}
    if isinstance(secret_orders, dict):
        for key, value in secret_orders.items():
            if isinstance(value, list):
                groups[key] = [item for item in value if isinstance(item, dict)]
    pending = groups.setdefault("待核议", [])
    existing_due_ids = {
        int(item["issue_id"])
        for item in pending
        if item.get("entry_kind") == "due_commitment" and item.get("issue_id") is not None
    }
    for item in due_commitments:
        if int(item["issue_id"]) not in existing_due_ids:
            pending.append(item)
    groups.setdefault("在办", [])
    return groups


def iter_secret_order_ids(secret_orders: object) -> List[int]:
    """Return real secret-order ids from the frozen grouped (or flat) batch.

    Skips due_commitment synthetic entries (#48 form③ channel reuse). Accepts
    the grouped dict shape used by personnel_secret rail and the legacy flat
    list shape still seen in old resolve_context rows.
    """
    rows: List[object]
    if isinstance(secret_orders, dict):
        rows = []
        for value in secret_orders.values():
            if isinstance(value, list):
                rows.extend(value)
    elif isinstance(secret_orders, list):
        rows = list(secret_orders)
    else:
        return []
    out: List[int] = []
    seen: Set[int] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        if str(item.get("entry_kind") or "") == "due_commitment":
            continue
        raw = item.get("id") if item.get("id") is not None else item.get("order_id")
        try:
            order_id = int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if order_id <= 0 or order_id in seen:
            continue
        seen.add(order_id)
        out.append(order_id)
    return out


def _format_decision_directive(decisions: List[Dict[str, object]]) -> str:
    """把皇帝已裁的决策点拼成喂 extractor 的「圣意亲裁」正文。
    每条：标题 + 所选选项 label/hint + 自由批语。未裁的跳过。"""
    lines: List[str] = []
    for i, d in enumerate(decisions, 1):
        choice = d.get("choice") or {}
        if not isinstance(choice, dict):
            continue
        label = str(choice.get("label") or "").strip()
        note = str(choice.get("note") or "").strip()
        if not label and not note:
            continue
        title = str(d.get("title") or f"抉择{i}").strip()
        selected = bind_decision_options(d.get("options") or []).get(label)
        # Typed grants are governed by their dossier status, not generic
        # "already happened" prose.  Their note remains an imperial fact.
        if isinstance(selected, Mapping) and selected.get("action_type") == "grant_allocation":
            if note:
                lines.append(f"{i}. 【{title}】朱批：{note}")
            continue
        seg = f"{i}. 【{title}】陛下御断：{label or '（未选预设项）'}"
        hint = str(choice.get("hint") or "").strip()
        if hint:
            seg += f"（倾向：{hint}）"
        if note:
            seg += f"。朱批：{note}"
        lines.append(seg)
    return "\n".join(lines)


def _player_visible_extractor_output(applied: object) -> object:
    if not isinstance(applied, dict):
        return applied
    visible = dict(applied)
    visible.pop("person_changes", None)
    # 拒收项是内部可观测信号（含 rejected/reason/category），不进皇帝可见呈现（P4）。
    visible.pop("faction_delta_rejections", None)
    visible.pop("class_delta_rejections", None)
    visible.pop("population_transfers_rejections", None)  # #649：转移拒收段不进皇帝可见呈现
    visible.pop("surcharge_decrees_rejections", None)  # #650：加派旨拒收仅供内部诊断
    visible.pop("economy_moves_rejections", None)
    visible.pop("validate_shape_rejections", None)
    visible.pop("module_misroute_rejections", None)
    issue_summary = visible.get("issue_summary")
    if isinstance(issue_summary, dict):
        issue_person_changes = issue_summary.get("applied_person_changes")
        if isinstance(issue_person_changes, list) and issue_person_changes:
            direct = visible.get("applied_person_changes")
            merged = list(direct) if isinstance(direct, list) else []
            merged.extend(issue_person_changes)
            visible["applied_person_changes"] = merged
    return _strip_player_internal_fields(visible)


def _strip_player_internal_fields(value: object) -> object:
    if isinstance(value, list):
        return [_strip_player_internal_fields(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _strip_player_internal_fields(item)
            for key, item in value.items()
            if key not in {"item", "report_section", "report_category"}
        }
    return value
