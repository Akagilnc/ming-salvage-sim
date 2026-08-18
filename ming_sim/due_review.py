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
from ming_sim.decree_vocabulary import terminal_report_facade
from ming_sim.staged_commitment import (
    ENTRY_KIND_STAGED,
    TODO_STATUS_CONSUMED,
    TODO_STATUS_PENDING,
    list_due_stages_for_scan,
    normalize_commitment_stages,
)

# 玩家可见串禁词（P4 哨兵）
_BANNED_PLAYER_TOKENS = (
    "fulfilled", "degraded", "failed", "transformed", "executing",
    "AWAITING_DECISION", "<<DECISION>>", "EXTRACTION_MODULES",
    "progress_band", "is_terminal", "close=True", "close=False",
)

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


def build_due_review_input(db: Any, todo: Dict[str, object]) -> Dict[str, object]:
    """P5 输入闭集：todo 字段 + stages + list_dossier_progress + 实况；催办/监督缺源=空列表。"""
    commitment_ref = int(todo["commitment_ref"])
    stage_idx = int(todo["stage_idx"])
    meta = _issue_meta(db, commitment_ref)
    stages = meta["stages"]
    branch = resolve_due_review_branch(db, meta["origin_ref"])
    progress_reports: List[Dict[str, object]] = []
    durable_effects: List[Dict[str, object]] = []
    if branch["dossier_id"] is not None:
        # 读端方法属 GameDB 契约面：抛错=代码/schema bug，响亮上抛（ADR 0005），
        # 不得吞成「空证据」误导裁决。催办/监督缺源仍按空列表降级（#624/#625 OOS）。
        progress_reports = list(db.list_dossier_progress(int(branch["dossier_id"])))
        durable_effects = list(
            db.list_economy_moves_for_dossier(int(branch["dossier_id"]))
        ) + list(
            db.list_fiscal_effects_for_dossier(int(branch["dossier_id"]))
        )
    # 催办/监督史尚未建轨（#624/#625 OOS）——空列表降级可判
    urge_history: List[Dict[str, object]] = []
    supervision_history: List[Dict[str, object]] = []
    return {
        "todo": dict(todo),
        "commitment_ref": commitment_ref,
        "stage_idx": stage_idx,
        "due_turn": int(todo.get("due_turn") or 0),
        "criterion_text": str(todo.get("criterion_text") or ""),
        "origin_context": str(todo.get("origin_context") or ""),
        "title": str(meta.get("title") or ""),
        "origin_ref": str(meta.get("origin_ref") or ""),
        "stages": stages,
        "mid_stage": not is_final_stage(stages, stage_idx),
        "branch": branch["branch"],
        "dossier_id": branch["dossier_id"],
        "dossier": branch["dossier"],
        "progress_reports": progress_reports,
        "durable_effects": durable_effects,
        "urge_history": urge_history,
        "supervision_history": supervision_history,
    }


def _strip_banned(text: str) -> str:
    out = str(text or "")
    for token in _BANNED_PLAYER_TOKENS:
        out = out.replace(token, "")
    return out


def _gap_and_statement(review_input: Dict[str, object]) -> tuple[str, str]:
    """0118 最小玩家面：果可见、因不自动。"""
    effects = list(review_input.get("durable_effects") or [])
    reports = list(review_input.get("progress_reports") or [])
    criterion = str(review_input.get("criterion_text") or "").strip() or "所约之事"

    if effects:
        gap = f"「{criterion}」一侧已见实账落地"
    elif reports:
        gap = f"「{criterion}」交付仍有亏欠，表报与实况未尽合"
    else:
        gap = f"「{criterion}」到期未见可核之实绩"

    statement = ""
    if reports:
        last = reports[-1]
        memorial = str(last.get("memorial_text") or "").strip()
        if memorial:
            statement = f"承办人陈词：{memorial}"
    if not statement:
        statement = "承办人陈词：容臣细禀（尚未具状）。"
    # 永不自动翻「因」
    return _strip_banned(gap), _strip_banned(statement)


def project_due_review_scene(
    db: Any,
    todo: Dict[str, object],
    *,
    review_input: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """复命场面投影（ID-13 用词，P4 定性、无数字面板）。"""
    inp = review_input if review_input is not None else build_due_review_input(db, todo)
    origin = str(inp.get("origin_context") or todo.get("origin_context") or "").strip()
    gap_text, statement_text = _gap_and_statement(inp)
    mid = bool(inp.get("mid_stage"))
    phase_hint = "中途复命" if mid else "到期复命"
    origin_bit = f"昔有「{origin}」之约，今期已至。" if origin else "前诺到期，例应复命。"
    scene_text = _strip_banned(
        f"{phase_hint}：{origin_bit}{gap_text}。{statement_text}"
    )
    return {
        "kind": "due_review",
        "entry_kind": str(todo.get("entry_kind") or ENTRY_KIND_STAGED),
        "todo_id": int(todo["id"]),
        "commitment_ref": int(todo["commitment_ref"]),
        "stage_idx": int(todo["stage_idx"]),
        "due_turn": int(todo.get("due_turn") or 0),
        "origin_context": origin,
        "criterion_text": str(todo.get("criterion_text") or ""),
        "mid_stage": mid,
        "gap_text": gap_text,
        "statement_text": statement_text,
        "scene_text": scene_text,
        "branch": str(inp.get("branch") or "no_dossier"),
        "dossier_id": inp.get("dossier_id"),
    }


def list_due_review_scenes(
    db: Any, state: Any = None, *, status: str = TODO_STATUS_PENDING,
) -> List[Dict[str, object]]:
    """次回合召对顶出序：复用 (due_turn, commitment_ref, stage_idx, id)。"""
    todos = db.list_next_audience_todos(status=status)
    # list_next_audience_todos 已按 due_turn, commitment_ref, stage_idx, id 排序
    # 本片只消费分段到期；#623 挽留等 entry_kind 预留位，未知 kind 跳过。
    # #620 写端只产 ENTRY_KIND_STAGED；其它 entry_kind（#623 预留）本片不投影。
    scenes: List[Dict[str, object]] = []
    for todo in todos:
        kind = str(todo.get("entry_kind") or ENTRY_KIND_STAGED)
        if kind != ENTRY_KIND_STAGED:
            continue
        scenes.append(project_due_review_scene(db, todo))
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
    1) 已有 pending todo（含本 settle 刚写、created_turn == turn）——召对前后至 apply；
    2) 本拍将写 todo 的到期段——extract 早于 write_due，须预占，
       已 consumed/rolled 的段不再占窗（中段复核后还权）。
    """
    turn = int(getattr(state, "turn", 0) or 0)
    owned: set[int] = set()

    for todo in db.list_next_audience_todos(status=TODO_STATUS_PENDING):
        meta = _issue_meta(db, int(todo["commitment_ref"]))
        _add_owned_dossier(owned, db, meta["origin_ref"])

    # 非 pending（consumed/rolled）段键：到期扫描不再预占
    finished_keys = {
        (int(t["commitment_ref"]), int(t["stage_idx"]))
        for t in db.list_next_audience_todos()
        if str(t.get("status") or "") != TODO_STATUS_PENDING
    }
    for item in list_due_stages_for_scan(db, turn):
        key = (int(item["commitment_ref"]), int(item["stage_idx"]))
        if key in finished_keys:
            continue
        _add_owned_dossier(owned, db, item.get("origin_ref"))
    return owned


def effect_has_beyond_intent(effect: object) -> bool:
    """#622：效果行同列「旨外恶果/受益」标记（#558 origin 同一载体，非平行轨）。"""
    if not isinstance(effect, dict):
        return False
    raw = effect.get("beyond_intent")
    if raw is None:
        raw = effect.get("旨外")
    return bool(GameDB.coerce_beyond_intent_flag(raw))


def durable_effects_beyond_intent(effects: object) -> bool:
    return any(effect_has_beyond_intent(item) for item in (effects or []))


def decide_due_review_verdict(review_input: Dict[str, object]) -> Dict[str, object]:
    """确定性裁决（不新增 LLM 步）。中段过程态 vs 末段四终值。

    #622：消费效果行旨外标记——有旨外恶果/受益 → transformed；
    有实况无旨外 → fulfilled；无实况有表报 → degraded；皆无 → failed。
    禁另立第二裁决函数。
    """
    mid = bool(review_input.get("mid_stage"))
    effects = list(review_input.get("durable_effects") or [])
    reports = list(review_input.get("progress_reports") or [])
    criterion = str(review_input.get("criterion_text") or "").strip() or "所约之事"
    origin = str(review_input.get("origin_context") or "").strip()

    if mid:
        note = f"中段复核：{criterion}仍在办理"
        if origin:
            note = f"中段复核（{origin}）：{criterion}仍在办理"
        return {
            "outcome": "executing",
            "note": note[:200],
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
    if origin:
        note = f"{note}（原诺：{origin}）"
    return {
        "outcome": outcome,
        "note": note[:200],
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
    if is_terminal and outcome in {"degraded", "transformed"}:
        # #622：奏报轨载承办人假象；progress_band 定性中文；判官真值只在执行格。
        # 进度写失败不得静默：执行格可能已落，分叉态须响亮（P1 / ADR 0005）
        prior = list(db.list_dossier_progress(int(dossier_id)))
        band, memorial = terminal_report_facade(outcome, prior_reports=prior)
        db.record_dossier_progress(
            int(dossier_id), int(state.turn), band, memorial,
            is_terminal=True,
            origin=GameDB.DOSSIER_REPORT_ORIGIN_VERDICT,
            commit=False,
        )
    elif not is_terminal:
        # 中段过程奏报：非终值
        db.record_dossier_progress(
            int(dossier_id), int(state.turn), "在办", note,
            is_terminal=False, commit=False,
        )
    if is_terminal and outcome in GameDB._JOINT_LIABILITY_TRIGGERS:
        db.apply_execution_joint_liability(
            state, int(dossier_id), outcome, reason=note, commit=False,
        )
    return {
        "dossier_id": int(dossier_id),
        "outcome": outcome,
        "close": close,
        "is_terminal": is_terminal,
        "noop": False,
    }


def apply_due_review_for_todo(
    db: Any,
    state: Any,
    todo: Dict[str, object],
    *,
    commit: bool = False,
) -> Dict[str, object]:
    """单条正式复核：落格（有案卷）或只场面消费（无案卷）+ todo 消费。"""
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
    """消费 created_turn < 当前 turn 的 pending todo（经召对窗后的 settle 落格）。"""
    turn = int(getattr(state, "turn", 0) or 0)
    results: List[Dict[str, object]] = []
    pending = db.list_next_audience_todos(status=TODO_STATUS_PENDING)
    for todo in pending:
        if int(todo.get("created_turn") or 0) >= turn:
            continue
        results.append(
            apply_due_review_for_todo(db, state, todo, commit=False)
        )
    if commit and results:
        db.conn.commit()
    return results
