"""#621 / ADR 0076 到期复核——实况供料与场面顶出；终值经模型声明写格。

不另立第三判官，不机械替判终值（#1835 J18 / #1895）：到期复核建输入闭集、
顶出复命场面；执行格终值只经既有 dossier_executions 声明写口。结算内不新增
串行 LLM 步、不置 AWAITING_DECISION / <<DECISION>>。

三拍时序（P4）：
1. settle(T) 确定性写/刷新 next_audience_todos（#620 写端）
2. 次回合召对顶出复命场面（本模块 list_due_review_scenes）
3. 模型经声明写执行格；settle 侧 apply_pending_due_reviews 仅在已有终值时消费 todo
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ming_sim.breach_plea import (
    ENTRY_KIND_BREACH_PLEA,
    parse_dossier_id as parse_dossier_id_from_origin,
    project_breach_plea_scene,
)
from ming_sim.staged_commitment import (
    ENTRY_KIND_GRACE_PLEA,
    ENTRY_KIND_RUSH_REMONSTRANCE,
    ENTRY_KIND_STAGED,
    TODO_STATUS_CONSUMED,
    TODO_STATUS_PENDING,
    normalize_commitment_stages,
)

# next_audience_todos.entry_kind 单一分派（#623+#624 合成，禁第二份谓词）：
#   staged       → 到期终裁（due-review 四缝）
#   breach_plea  → 挽留投影 / apply 跳过保留 pending
#   urge         → #624 谏/宽限通道（list_urge / consume_urge）
#   unknown      → 跳过
_AUDIENCE_LANE_STAGED = "staged"
_AUDIENCE_LANE_BREACH_PLEA = "breach_plea"
_AUDIENCE_LANE_URGE = "urge"
_AUDIENCE_LANE_COVERT_LEVY = "covert_levy"
_AUDIENCE_LANE_UNKNOWN = "unknown"

def normalize_audience_entry_kind(entry_kind: object) -> str:
    text = str(entry_kind or ENTRY_KIND_STAGED).strip()
    return text or ENTRY_KIND_STAGED


def audience_todo_lane(entry_kind: object) -> str:
    """entry_kind → 通道分派（唯一谓词）。"""
    kind = normalize_audience_entry_kind(entry_kind)
    if kind == ENTRY_KIND_STAGED:
        return _AUDIENCE_LANE_STAGED
    if kind == ENTRY_KIND_BREACH_PLEA:
        return _AUDIENCE_LANE_BREACH_PLEA
    if kind in (ENTRY_KIND_RUSH_REMONSTRANCE, ENTRY_KIND_GRACE_PLEA):
        return _AUDIENCE_LANE_URGE
    if kind == "covert_levy_exposure":
        return _AUDIENCE_LANE_COVERT_LEVY
    return _AUDIENCE_LANE_UNKNOWN


_TERMINAL_OUTCOMES = frozenset({"fulfilled", "degraded", "failed", "transformed"})


def _issue_meta(db: Any, commitment_ref: int) -> Dict[str, object]:
    row = db.conn.execute(
        "SELECT id, title, origin_ref, stages_json, stage_text FROM issues WHERE id=?",
        (int(commitment_ref),),
    ).fetchone()
    if row is None:
        return {
            "id": int(commitment_ref),
            "title": "",
            "origin_ref": "",
            "stages": [],
            "stage_text": "",
        }
    return {
        "id": int(row["id"]),
        "title": str(row["title"] or ""),
        "origin_ref": str(row["origin_ref"] or ""),
        "stages": normalize_commitment_stages(row["stages_json"]),
        "stage_text": str(row["stage_text"] or ""),
    }


def is_final_stage(stages: List[Dict[str, object]], stage_idx: int) -> bool:
    if not stages:
        # 无段表时本条 todo 视为末段终裁面
        return True
    indices = [int(s["stage_idx"]) for s in stages]
    return int(stage_idx) == max(indices)


def resolve_due_review_branch(
    db: Any, origin_ref: object,
) -> Dict[str, object]:
    """P1 桥：有 executing 案卷 → dossier；否则 no_dossier（不伪造）。"""
    dossier_id = parse_dossier_id_from_origin(origin_ref)
    if dossier_id is None:
        return {"branch": "no_dossier", "dossier_id": None, "dossier": None}
    dossier = db.get_decree_dossier(int(dossier_id))
    if dossier is None:
        return {"branch": "no_dossier", "dossier_id": None, "dossier": None}
    if str(dossier.get("status") or "") != "executing":
        return {
            "branch": "no_dossier",
            "dossier_id": int(dossier_id),
            "dossier": dossier,
        }
    return {
        "branch": "dossier",
        "dossier_id": int(dossier_id),
        "dossier": dossier,
    }


def _todo_origin_ref(todo: Dict[str, object], meta_origin: str = "") -> str:
    """#1783：案卷 due todo（commitment_ref=0）origin 在 payload；承诺 todo 仍读 issue。"""
    payload = todo["payload_json"]
    raw = str(payload.get("origin_ref") or "").strip()
    if raw:
        return raw
    did = payload.get("dossier_id")
    if did is not None and int(did) > 0:
        return f"dossier:{int(did)}"
    return str(meta_origin or "").strip()


def build_due_review_input(db: Any, todo: Dict[str, object]) -> Dict[str, object]:
    """P5 输入闭集：todo 字段 + stages + list_dossier_progress + 实况；催办/监督缺源=空列表。"""
    from ming_sim.urge_lever import (
        collect_urge_history,
        derive_opportunity_band,
        resolve_host_character,
    )

    commitment_ref = int(todo["commitment_ref"])
    stage_idx = int(todo["stage_idx"])
    meta = _issue_meta(db, commitment_ref) if commitment_ref > 0 else {
        "id": 0, "title": "", "origin_ref": "", "stages": [], "stage_text": "",
    }
    # 案卷 due 直挂：title/criterion 已在 todo；无 issue 段表 → 末段
    if commitment_ref <= 0 and not meta.get("title"):
        meta = dict(meta)
        meta["title"] = str(todo.get("criterion_text") or "")
    stages = meta["stages"]
    origin_ref = _todo_origin_ref(todo, str(meta.get("origin_ref") or ""))
    branch = resolve_due_review_branch(db, origin_ref)
    progress_reports: List[Dict[str, object]] = []
    durable_effects: List[Dict[str, object]] = []
    # #625：监督三键空形以 supervision 导出常量为唯一真源。
    from ming_sim.supervision import (
        EMPTY_TRANSFORMATION_TENDENCY_FACTS,
        unpack_supervision_surface,
    )
    supervision_pack = unpack_supervision_surface(None)
    if branch["dossier_id"] is not None:
        # 读端方法属 GameDB 契约面：抛错=代码/schema bug，响亮上抛（ADR 0005），
        # 不得吞成「空证据」误导裁决。催办/监督缺源仍按空列表降级。
        progress_reports = list(db.list_dossier_progress(int(branch["dossier_id"])))
        # #1260：durable_effects 合并单源（economy+fiscal）。
        durable_effects = list(
            db.list_dossier_durable_effects(int(branch["dossier_id"]))
        )
        # #625：监督事实底只读注入（解 A）。
        supervision_pack = unpack_supervision_surface(
            db.build_supervision_judge_surface(int(branch["dossier_id"]))
        )
    supervision_history = list(supervision_pack["supervision_history"])
    loophole_exposures = list(supervision_pack["loophole_exposures"])
    transformation_tendency_facts = dict(
        supervision_pack["transformation_tendency_facts"]
        or EMPTY_TRANSFORMATION_TENDENCY_FACTS
    )
    # #624：催办史唯一填充点；缺源=[]。
    urge_history: List[Dict[str, object]] = collect_urge_history(
        db,
        commitment_ref=commitment_ref,
        dossier_id=branch["dossier_id"],
    )
    host = resolve_host_character(
        db,
        commitment_ref=commitment_ref,
        dossier_id=branch["dossier_id"],
    )
    opportunity_band = derive_opportunity_band(durable_effects)
    army_pay_fact = None
    if branch["dossier_id"] is not None:
        from ming_sim.covert_levy import army_pay_fact_for_dossier
        army_pay_fact = army_pay_fact_for_dossier(db, int(branch["dossier_id"]))
    return {
        "todo": dict(todo),
        "commitment_ref": commitment_ref,
        "stage_idx": stage_idx,
        "due_turn": int(todo.get("due_turn") or 0),
        "criterion_text": str(todo.get("criterion_text") or ""),
        "origin_context": str(todo.get("origin_context") or ""),
        "title": str(meta.get("title") or ""),
        "origin_ref": origin_ref,
        "stages": stages,
        "mid_stage": not is_final_stage(stages, stage_idx),
        "branch": branch["branch"],
        "dossier_id": branch["dossier_id"],
        "dossier": branch["dossier"],
        "progress_reports": progress_reports,
        "durable_effects": durable_effects,
        "army_pay_fact": army_pay_fact,
        "urge_history": urge_history,
        "supervision_history": supervision_history,
        "loophole_exposures": loophole_exposures,
        "transformation_tendency_facts": transformation_tendency_facts,
        "host": host,
        "opportunity_band": opportunity_band,
    }


def _payload_container(payload: Dict[str, object], key: str, kind: type) -> Any:
    """持久 payload 容器成员：缺省（None）为空容器；类型不符响亮失败，不回空。"""
    value = payload.get(key)
    if value is None:
        return kind()
    if not isinstance(value, kind):
        raise ValueError(f"payload.{key} 须为 {kind.__name__}，得 {type(value).__name__}")
    return kind(value)


def project_due_review_scene(
    db: Any,
    todo: Dict[str, object],
    *,
    review_input: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """复命场面投影（ID-13 用词，P4 定性、无数字面板）。"""
    inp = review_input if review_input is not None else build_due_review_input(db, todo)
    # P6 / ADR 0142：origin_context 是自由正文；投影原串，不把 strip 副本当原文。
    origin = str(inp.get("origin_context") or todo.get("origin_context") or "")
    mid = bool(inp.get("mid_stage"))
    entry_kind = str(todo.get("entry_kind") or ENTRY_KIND_STAGED)
    scene_kind = "covert_levy_exposure" if audience_todo_lane(entry_kind) == _AUDIENCE_LANE_COVERT_LEVY else "due_review"
    payload = todo["payload_json"]
    reopened = scene_kind == "covert_levy_exposure" and bool(payload.get("shortfall_reopened"))
    if reopened:
        # A prohibition reminder is a fresh shortfall projection, not a replay
        # of the already-settled exposure and its adjudication materials.
        return {
            "todo_id": int(todo["id"]),
            "commitment_ref": int(todo["commitment_ref"]),
            "stage_idx": int(todo["stage_idx"]),
            "due_turn": int(todo.get("due_turn") or 0),
            "dossier_id": inp.get("dossier_id"),
            "executor_id": str((inp.get("dossier") or {}).get("executor_id") or ""),
            "army_pay_fact": inp.get("army_pay_fact"),
            "decision": str(payload.get("decision") or ""),
            "shortfall_reopened": True,
            "available_dispositions": [],
        }
    return {
        "kind": scene_kind,
        "entry_kind": entry_kind,
        "todo_id": int(todo["id"]),
        "commitment_ref": int(todo["commitment_ref"]),
        "stage_idx": int(todo["stage_idx"]),
        "due_turn": int(todo.get("due_turn") or 0),
        "origin_context": origin,
        "criterion_text": str(todo.get("criterion_text") or ""),
        "mid_stage": mid,
        "branch": str(inp.get("branch") or "no_dossier"),
        "dossier_id": inp.get("dossier_id"),
        "executor_id": str((inp.get("dossier") or {}).get("executor_id") or ""),
        "channels": _payload_container(payload, "channels", list),
        "fork": _payload_container(payload, "fork", dict),
        "army_pay_fact": inp.get("army_pay_fact"),
        "decision": str(payload.get("decision") or ""),
        "shortfall_reopened": reopened,
        "available_dispositions": [] if reopened else ["禁摊派", "默许", "查办"],
    }


def list_due_review_scenes(
    db: Any, *, status: str = TODO_STATUS_PENDING,
) -> List[Dict[str, object]]:
    """次回合召对顶出序：复用 (due_turn, commitment_ref, stage_idx, id)。

    单一分派：staged → 复命场面；breach_plea → 哭谏场面；
    urge（谏/宽限）走 #624 list_urge_audience_scenes；未知跳过。
    """
    todos = db.list_next_audience_todos(status=status)
    # list_next_audience_todos 已按 due_turn, commitment_ref, stage_idx, id 排序
    scenes: List[Dict[str, object]] = []
    for todo in todos:
        lane = audience_todo_lane(todo.get("entry_kind"))
        if lane in (_AUDIENCE_LANE_STAGED, _AUDIENCE_LANE_COVERT_LEVY):
            scenes.append(project_due_review_scene(db, todo))
        elif lane == _AUDIENCE_LANE_BREACH_PLEA:
            scenes.append(project_breach_plea_scene(todo))
        # urge / unknown：不投影为 due-review 场面
    return scenes


def _dossier_terminal_snapshot(db: Any, dossier_id: int) -> Dict[str, object]:
    """读已有执行格终值；不代判。"""
    existing = db.get_decree_dossier(int(dossier_id))
    if existing is None:
        return {"rejected": True, "reason": "案卷不存在"}
    prev_outcome = str(existing.get("execution_outcome") or "")
    if existing.get("status") == "closed" and prev_outcome in _TERMINAL_OUTCOMES:
        return {
            "dossier_id": int(dossier_id),
            "outcome": prev_outcome,
            "noop": True,
            "reason": "已有终值",
            "is_terminal": True,
        }
    return {
        "dossier_id": int(dossier_id),
        "outcome": prev_outcome or None,
        "noop": True,
        "reason": "等待模型声明写格",
        "is_terminal": False,
        "status": existing.get("status"),
    }


def apply_due_review_for_todo(
    db: Any,
    state: Any,
    todo: Dict[str, object],
) -> Dict[str, object]:
    """单条正式复核生命周期：供料/场面已另口；本函数只衔接模型已写终值后的 todo 消费。

    #1835 J18：不机械选终值、不代写执行格；终值只经 dossier_executions 声明写口。
    中段：消费 todo（场面已呈，不关案）。末段无终值：保留 pending，等模型写格。
    """
    kind = normalize_audience_entry_kind(todo.get("entry_kind"))
    lane = audience_todo_lane(kind)
    if lane == _AUDIENCE_LANE_BREACH_PLEA:
        # 法：沉默/未答→跳过保留 pending；反悔/坚持由召对 extraction 真入口结账
        return {
            "todo_id": int(todo.get("id") or 0),
            "entry_kind": kind,
            "skipped": True,
            "reason": "breach_plea_pending_retained",
            "consumed": False,
        }
    if lane != _AUDIENCE_LANE_STAGED:
        # urge / unknown：不得当到期复核落格（#624 四缝 + 负向闸）
        return {
            "todo_id": int(todo.get("id") or 0),
            "rejected": True,
            "reason": "entry_kind 不在 due-review 白名单",
            "entry_kind": kind,
            "consumed": False,
        }

    inp = build_due_review_input(db, todo)
    scene = project_due_review_scene(db, todo, review_input=inp)
    branch = str(inp.get("branch") or "no_dossier")
    mid_stage = bool(inp.get("mid_stage"))
    exec_result: Dict[str, object] = {}
    consumed = False
    dossier_id = inp.get("dossier_id")

    if dossier_id is not None:
        # 模型可能已关案：branch 会成 no_dossier，仍按终值快照衔接消费。
        exec_result = _dossier_terminal_snapshot(db, int(dossier_id))
        if exec_result.get("is_terminal"):
            branch = "dossier"
            consumed = bool(db.mark_next_audience_todo_status(
                int(todo["id"]), TODO_STATUS_CONSUMED, commit=False,
            ))
        elif mid_stage:
            # 中段只消费场面待办，不关案、不写终值。
            consumed = bool(db.mark_next_audience_todo_status(
                int(todo["id"]), TODO_STATUS_CONSUMED, commit=False,
            ))
        elif branch == "dossier":
            # 末段仍在 executing 且无模型终值：保留 pending，不机械替判。
            consumed = False
            exec_result = {
                **exec_result,
                "waiting_model": True,
            }
        else:
            # 案卷已不在 executing 且无终值（如中断态）：只消费待办，不代写。
            consumed = bool(db.mark_next_audience_todo_status(
                int(todo["id"]), TODO_STATUS_CONSUMED, commit=False,
            ))
    else:
        exec_result = {
            "branch": "no_dossier",
            "forged_dossier": False,
            "outcome": None,
        }
        # 无案卷桥：只消费待办，不伪造案卷终值。
        consumed = bool(db.mark_next_audience_todo_status(
            int(todo["id"]), TODO_STATUS_CONSUMED, commit=False,
        ))

    return {
        "todo_id": int(todo["id"]),
        "entry_kind": kind,
        "branch": branch,
        "mid_stage": mid_stage,
        "execution": exec_result,
        "scene": scene,
        "consumed": bool(consumed),
    }


def apply_pending_due_reviews(
    db: Any, state: Any,
) -> List[Dict[str, object]]:
    """处理 created_turn < 当前 turn 的 pending todo（召对窗后的生命周期衔接）。

    单一分派：staged 接模型已写终值后消费；breach_plea skip 保留（入 results）；
    urge 交给 #624 consume_pending_urge_audience_todos（本函数不扫）；未知负向闸。
    不机械替判终值（#1835 J18）。
    """
    turn = int(getattr(state, "turn", 0) or 0)
    results: List[Dict[str, object]] = []
    pending = db.list_next_audience_todos(status=TODO_STATUS_PENDING)
    for todo in pending:
        if int(todo.get("created_turn") or 0) >= turn:
            continue
        lane = audience_todo_lane(todo.get("entry_kind"))
        if lane in (_AUDIENCE_LANE_URGE, _AUDIENCE_LANE_COVERT_LEVY):
            # 通道由普通下旨的 canonical 动作结账；不得被 staged 终裁误消费。
            continue
        # staged / breach_plea / unknown → apply_due_review_for_todo 内分派
        results.append(
            apply_due_review_for_todo(db, state, todo)
        )
    return results
