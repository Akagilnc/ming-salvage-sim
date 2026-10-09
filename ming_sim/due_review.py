"""#621 / ADR 0076 到期复核——执行格判官的正式触发形态。

不另立第三判官：到期复核并入既有执行填值路径（record_dossier_execution 适配器），
结算内不新增串行 LLM 步、不置 AWAITING_DECISION / <<DECISION>>。

三拍时序（P4）：
1. settle(T) 确定性写/刷新 next_audience_todos（#620 写端）
2. 次回合召对顶出复命场面（本模块 list_due_review_scenes）
3. settle(T+1) apply_pending_due_reviews 落格并消费 todo
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ming_sim.db import GameDB
from ming_sim.breach_plea import (
    ENTRY_KIND_BREACH_PLEA,
    project_breach_plea_scene,
)
from ming_sim.staged_commitment import (
    ENTRY_KIND_GRACE_PLEA,
    ENTRY_KIND_RUSH_REMONSTRANCE,
    ENTRY_KIND_STAGED,
    TODO_STATUS_CONSUMED,
    TODO_STATUS_PENDING,
    list_due_stages_for_scan,
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

# #624 四缝白名单钉：仅 staged 进 due-review 终裁（由分派矩阵派生，非平行谓词）
DUE_REVIEW_ENTRY_KIND_WHITELIST = frozenset({ENTRY_KIND_STAGED})


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


def is_due_review_entry_kind(entry_kind: object) -> bool:
    """#624 四缝：仅 staged 可投影/apply/占接管窗为到期复核。"""
    return audience_todo_lane(entry_kind) == _AUDIENCE_LANE_STAGED

_DOSSIER_REF_RE = re.compile(r"^dossier:([1-9][0-9]*)$")

_TERMINAL_OUTCOMES = frozenset({"fulfilled", "degraded", "failed", "transformed"})


def parse_dossier_id_from_origin(origin_ref: object) -> Optional[int]:
    text = str(origin_ref or "").strip()
    match = _DOSSIER_REF_RE.match(text)
    if not match:
        return None
    return int(match.group(1))


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
    payload = todo.get("payload_json") or {}
    if isinstance(payload, dict):
        raw = str(payload.get("origin_ref") or "").strip()
        if raw:
            return raw
        did = payload.get("dossier_id")
        try:
            if int(did or 0) > 0:
                return f"dossier:{int(did)}"
        except (TypeError, ValueError):
            pass
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
        meta["title"] = str(todo.get("criterion_text") or "")  # #1897: no truncate
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
        # #625：监督事实底只读注入（解 A）；不改 decide_due_review_verdict。
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


def project_due_review_scene(
    db: Any,
    todo: Dict[str, object],
    *,
    review_input: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """复命场面投影（ID-13 用词，P4 定性、无数字面板）。"""
    inp = review_input if review_input is not None else build_due_review_input(db, todo)
    origin = str(inp.get("origin_context") or todo.get("origin_context") or "")  # #1897: verbatim
    mid = bool(inp.get("mid_stage"))
    entry_kind = str(todo.get("entry_kind") or ENTRY_KIND_STAGED)
    scene_kind = "covert_levy_exposure" if audience_todo_lane(entry_kind) == _AUDIENCE_LANE_COVERT_LEVY else "due_review"
    payload = todo.get("payload_json") or {}
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
        "channels": list(payload.get("channels") or []),
        "fork": dict(payload.get("fork") or {}),
        "army_pay_fact": inp.get("army_pay_fact"),
        "decision": str(payload.get("decision") or ""),
        "shortfall_reopened": reopened,
        "available_dispositions": [] if reopened else ["禁摊派", "默许", "查办"],
    }


def list_due_review_scenes(
    db: Any, state: Any = None, *, status: str = TODO_STATUS_PENDING,
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
            scenes.append(project_breach_plea_scene(db, todo))
        # urge / unknown：不投影为 due-review 场面
    return scenes


def _add_owned_dossier(
    owned: set[int], db: Any, origin_ref: object,
) -> None:
    branch = resolve_due_review_branch(db, origin_ref)
    if branch["branch"] == "dossier" and branch["dossier_id"] is not None:
        owned.add(int(branch["dossier_id"]))


def dossiers_with_pending_due_review(db: Any, state: Any) -> set[int]:
    """接管窗：到期目标案卷仅正式复核可写终值（防 extractor 第二真源）。

    覆盖两段窗：
    1) 已有 pending staged todo（含本 settle 刚写、created_turn == turn）——召对前后至 apply；
    2) 本拍将写 todo 的到期段——extract 早于 write_due，须预占，
       已 consumed/rolled 的段不再占窗（中段复核后还权）。

    kind 分派法：midcourse_breach_plea / 其它 kind **不计入**接管窗。
    """
    turn = int(getattr(state, "turn", 0) or 0)
    owned: set[int] = set()

    for todo in db.list_next_audience_todos(status=TODO_STATUS_PENDING):
        # 仅 staged 占接管窗（breach_plea / urge / unknown 均不占）
        if not is_due_review_entry_kind(todo.get("entry_kind")):
            continue
        cid = int(todo.get("commitment_ref") or 0)
        if cid > 0:
            meta = _issue_meta(db, cid)
            origin = str(meta.get("origin_ref") or "")
        else:
            origin = _todo_origin_ref(todo)
        _add_owned_dossier(owned, db, origin)

    # 非 pending（consumed/rolled）段键：到期扫描不再预占（仅 staged 键）
    finished_keys = {
        (int(t["commitment_ref"]), int(t["stage_idx"]))
        for t in db.list_next_audience_todos()
        if str(t.get("status") or "") != TODO_STATUS_PENDING
        and is_due_review_entry_kind(t.get("entry_kind"))
    }
    from ming_sim.staged_commitment import list_due_grant_report_dossiers_for_scan
    scan_items = list(list_due_stages_for_scan(db, turn))
    scan_items.extend(list_due_grant_report_dossiers_for_scan(db, turn))
    for item in scan_items:
        key = (int(item["commitment_ref"]), int(item["stage_idx"]))
        if key in finished_keys:
            continue
        _add_owned_dossier(owned, db, item.get("origin_ref"))
    return owned


def effect_has_beyond_intent(effect: object) -> bool:
    """#622：效果行同列「旨外恶果/受益」标记（#558 origin 同一载体，非平行轨）。

    #1260：别名读取收敛 simulation 单源（禁手抄 旨外 子集）。
    """
    if not isinstance(effect, dict):
        return False
    from ming_sim.simulation import read_beyond_intent_raw
    raw = read_beyond_intent_raw(effect)
    return bool(GameDB.coerce_beyond_intent_flag(raw))


def durable_effects_beyond_intent(effects: object) -> bool:
    return any(effect_has_beyond_intent(item) for item in (effects or []))


def decide_due_review_verdict(review_input: Dict[str, object]) -> Dict[str, object]:
    """确定性裁决（不新增 LLM 步）。中段过程态 vs 末段四终值。

    #1895：终值只由实况账判——有旨外恶果/受益 → transformed；有实况无旨外 →
    fulfilled；无实况有表报 → degraded；皆无 → failed。代码不再由承办人
    integrity／催办压力派生「失真档」并把判词只往更重方向改写；人物办不办、
    办得多重归模型按其可及事实自己选（#1816 人物场景／月末 run）。
    #622 旨外标记口径不变；0118 对账不翻因。禁另立第二裁决函数。
    """
    mid = bool(review_input.get("mid_stage"))
    effects = list(review_input.get("durable_effects") or [])
    reports = list(review_input.get("progress_reports") or [])
    # #1897：criterion/origin 自由正文原样嵌入判词，禁 strip（空白原文不得换成缺省）。
    criterion = str(review_input.get("criterion_text") or "") or "所约之事"
    origin = str(review_input.get("origin_context") or "")

    if mid:
        note = f"中段复核：{criterion}仍在办理"
        # Emptiness on strip copy; note embeds origin raw bytes (#1834 F16).
        if origin.strip():
            note = f"中段复核（{origin}）：{criterion}仍在办理"
        return {
            "outcome": "executing",
            "note": note,
            "close": False,
            "is_terminal": False,
            "mid_stage": True,
        }

    # 末段终裁：机械读旨外标记（0072 分界；0118 对账不翻因）
    if durable_effects_beyond_intent(effects):
        outcome = "transformed"
        note = f"到期复核：{criterion}名实已乖"
    elif effects:
        outcome = "fulfilled"
        note = f"到期复核：{criterion}已见实绩生根"
    elif reports:
        # 有表报无实账 → 打折走样（果可见缺口，不翻因）
        outcome = "degraded"
        note = f"到期复核：{criterion}表报有之、实绩未充"
    else:
        outcome = "failed"
        note = f"到期复核：{criterion}届期无实绩"
    if origin.strip():
        note = f"{note}（原诺：{origin}）"
    return {
        "outcome": outcome,
        "note": note,
        "close": True,
        "is_terminal": True,
        "mid_stage": False,
    }


def _apply_dossier_verdict(
    db: Any,
    state: Any,
    *,
    dossier_id: int,
    verdict: Dict[str, object],
) -> Dict[str, object]:
    """经既有 record_dossier_execution + 连坐挂载点（仅终值）。"""
    outcome = str(verdict["outcome"])
    note = str(verdict["note"])
    close = bool(verdict["close"])
    is_terminal = bool(verdict["is_terminal"])

    existing = db.get_decree_dossier(int(dossier_id))
    if existing is None:
        return {"rejected": True, "reason": "案卷不存在"}
    # 已有终值且已结案：零重复落账 / 不二次连坐
    prev_outcome = str(existing.get("execution_outcome") or "")
    if (
        existing.get("status") == "closed"
        and prev_outcome in _TERMINAL_OUTCOMES
    ):
        return {
            "dossier_id": int(dossier_id),
            "outcome": prev_outcome,
            "noop": True,
            "reason": "已有终值",
        }
    if existing.get("status") != "executing":
        return {
            "rejected": True,
            "reason": f"案卷不在 executing：{existing.get('status')}",
        }

    db.record_dossier_execution(
        int(dossier_id), outcome, note, int(state.turn),
        close=close, commit=False,
    )
    if is_terminal and outcome in GameDB._JOINT_LIABILITY_TRIGGERS:
        db.apply_execution_joint_liability(
            state, int(dossier_id), outcome, reason=note, commit=False,
        )
    # #628 / 0079：到期复核兑付写信用事件（与 extraction 共调 record_fulfillment_credit）
    credit_rows: list = []
    if is_terminal and outcome == "fulfilled":
        from ming_sim.credit_events import record_fulfillment_credit
        credit_rows = record_fulfillment_credit(
            db, state, dossier_id=int(dossier_id),
        )
    return {
        "dossier_id": int(dossier_id),
        "outcome": outcome,
        "close": close,
        "is_terminal": is_terminal,
        "noop": False,
        "credit_events": credit_rows,
    }



def apply_due_review_for_todo(
    db: Any,
    state: Any,
    todo: Dict[str, object],
    *,
    commit: bool = False,
) -> Dict[str, object]:
    """单条正式复核：仅 staged 落格+消费；其它 lane 按分派闸。"""
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
    verdict = decide_due_review_verdict(inp)
    scene = project_due_review_scene(db, todo, review_input=inp)
    branch = str(inp.get("branch") or "no_dossier")
    exec_result: Dict[str, object] = {}
    if branch == "dossier" and inp.get("dossier_id") is not None:
        exec_result = _apply_dossier_verdict(
            db, state, dossier_id=int(inp["dossier_id"]), verdict=verdict,
        )
    else:
        exec_result = {
            "branch": "no_dossier",
            "forged_dossier": False,
            "outcome": None,
        }

    consumed = db.mark_next_audience_todo_status(
        int(todo["id"]), TODO_STATUS_CONSUMED, commit=False,
    )
    if commit:
        db.conn.commit()
    return {
        "todo_id": int(todo["id"]),
        "entry_kind": kind,
        "branch": branch,
        "mid_stage": bool(verdict.get("mid_stage")),
        "verdict": verdict,
        "execution": exec_result,
        "scene": scene,
        "consumed": bool(consumed),
    }


def apply_pending_due_reviews(
    db: Any, state: Any, *, commit: bool = False,
) -> List[Dict[str, object]]:
    """消费 created_turn < 当前 turn 的 pending todo（经召对窗后的 settle 落格）。

    单一分派：staged 终裁+连坐；breach_plea skip 保留（入 results）；
    urge 交给 #624 consume_pending_urge_audience_todos（本函数不扫）；未知负向闸。
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
            apply_due_review_for_todo(db, state, todo, commit=False)
        )
    if commit and results:
        db.conn.commit()
    return results
