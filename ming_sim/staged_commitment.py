"""#620 / ADR 0074 分段承诺载体。

一条多段里程碑 = 单一 commitment issue（stages_json）。
段到期扫描独立（与 form③ 共享谓词面、不共用其 SQL 结果集），
待裁载体改道 next_audience_todos（次回合召对待办）；
结算不停轮、不接 DECISION/AWAITING_DECISION（0074/0076）。

存储选型（本片定）：
- 段表：issues.stages_json（JSON 数组，挂在单一承诺对象上）
- 待办：next_audience_todos 表（P2 字段集）
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Sequence

ENTRY_KIND_STAGED = "staged_commitment"
# #624 / ADR 0078：反催谏 / 求宽限（0075 同款 next_audience_todos 通道；不进 due-review 白名单）
ENTRY_KIND_RUSH_REMONSTRANCE = "rush_remonstrance"
ENTRY_KIND_GRACE_PLEA = "grace_plea"
TODO_STATUS_PENDING = "pending"
TODO_STATUS_CONSUMED = "consumed"
# rolled 写口仍由 mark_next_audience_todo_status 接受（P3 契约）；常量待 #623 超额滚存启用再导出。


def _stage_text_fields(item: Dict[str, object]) -> tuple[str, str] | None:
    """共同分段正文转换（criterion/origin 别名与回填）——读/写只此一处（#1897 K2）。

    返回 (criterion_text, origin_context)；缺 criterion 时返回 None 由调用方决定
    跳过（读）或拒收（写）。
    """
    # #1897 / ADR0142：自由正文原样入载体，禁 strip 规范化。
    criterion = str(item.get("criterion_text") or item.get("criterion") or "")
    origin_context = str(
        item.get("origin_context") or item.get("origin") or criterion or ""
    )
    if not criterion and origin_context:
        criterion = origin_context
    if not criterion:
        return None
    return criterion, origin_context or criterion


def _stage_record(
    *, stage_idx: int, due_turn: int, criterion_text: str, origin_context: str,
) -> Dict[str, object]:
    """四字段分段记录形状——读/写共用。"""
    return {
        "stage_idx": stage_idx,
        "due_turn": due_turn,
        "criterion_text": criterion_text,
        "origin_context": origin_context,
    }


def _stages_for_write(data: Sequence[object]) -> List[Dict[str, object]]:
    """Stage admission: every item must be a valid stage dict.

    读/写共用此严格面（#1897 E1/K2）：缺省空与显式坏值分开；已持久腐坏
    不得跳段洗成合法身份。整数字段复用 ``strict_int``；正文转换复用
    ``_stage_text_fields``（#1897 K2），不复制别名/回填规则。
    """
    from ming_sim.strict_types import strict_int

    if not isinstance(data, (list, tuple)):
        raise ValueError(f"stages_json 须为 JSON 数组，得 {type(data).__name__}")
    out: List[Dict[str, object]] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"stages[{idx}] 须为对象")
        raw_due = item.get("due_turn")
        if raw_due in (None, ""):
            raise ValueError(f"stages[{idx}] 缺 due_turn")
        try:
            due_turn = strict_int(raw_due, accept_numeric_strings=True)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"stages[{idx}].due_turn 须为有限整数") from exc
        if due_turn <= 0:
            raise ValueError(f"stages[{idx}].due_turn 须为正")
        raw_idx = item.get("stage_idx", idx)
        if raw_idx in (None, ""):
            raw_idx = idx
        try:
            stage_idx = strict_int(raw_idx, accept_numeric_strings=True)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"stages[{idx}].stage_idx 须为有限整数") from exc
        texts = _stage_text_fields(item)
        if texts is None:
            raise ValueError(f"stages[{idx}] 缺 criterion_text")
        criterion, origin_context = texts
        out.append(_stage_record(
            stage_idx=stage_idx, due_turn=due_turn,
            criterion_text=criterion, origin_context=origin_context,
        ))
    out.sort(key=lambda s: (int(s["stage_idx"]), int(s["due_turn"])))
    return out


def normalize_commitment_stages(raw: object) -> List[Dict[str, object]]:
    """Normalize structured stages payload → durable list.

    缺省（None/""/[]/"[]"）→ 空列表；已持久 JSON/schema 腐坏或非数组 → 上抛。
    与写口共用 ``_stages_for_write``，无平行宽容跳段/回填（#1897 E1/K2；ADR0005）。

    分段承诺是机械事实（到期判账），只认显式结构化字段。引擎不得从 LLM 自由
    散文正则反推语义（ADR 0142 / #1897 / #1890）。原 ``parse_staged_year_promise``
    中文数词年诺捕获已删。自由正文原样入载体，禁 strip／截断规范化（#1897）。
    """
    if raw in (None, "", [], ()):
        return []
    data = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text or text == "[]":
            return []
        try:
            data = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"stages_json 须为 JSON 数组字符串，解析失败：{text[:80]!r}"
            ) from exc
    if not isinstance(data, (list, tuple)):
        raise ValueError(f"stages_json 须为 JSON 数组，得 {type(data).__name__}")
    if len(data) == 0:
        return []
    return _stages_for_write(data)


def stages_to_json(stages: object) -> str:
    """Serialize stages for durable DB write.

    顶层缺省／JSON 解码／数组准入唯一权威 = ``normalize_commitment_stages``；
    本口只序列化其结果（#1897 K2）。``None`` / empty / ``[]`` → ``"[]"``。
    """
    normalized = normalize_commitment_stages(stages)
    if not normalized:
        return "[]"
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))



def stages_source_from_issue_item(ni: Dict[str, object]) -> object:
    """Single stages key fallback for new_issues items (stages | stages_json).

    仅真正缺省（None/""）与合法空数组回落 stages_json；显式 ``{}`` 等坏形
    原样交给 ``stages_to_json`` 拒收，不得当缺省洗白（#1897 C1）。
    """
    stages = ni.get("stages")
    if stages not in (None, "", [], ()):
        return stages
    if stages in ([], ()):
        return stages
    return ni.get("stages_json")


def is_stage_derived_end_turn(
    stages: object,
    end_turn: int,
) -> bool:
    """True when end_turn is purely max(stages.due_turn) display-compat (no independent due)."""
    norm = normalize_commitment_stages(stages)
    if not norm:
        return False
    try:
        et = int(end_turn or 0)
    except (TypeError, ValueError):
        return False
    if et <= 0:
        return False
    return et == max(int(s["due_turn"]) for s in norm)


def should_skip_form3_due_for_staged(
    stages_raw: object,
    end_turn: int,
) -> bool:
    """form③ due_commitments 跳过面：仅段派生 end_turn 改道；独立 end_turn 待裁不吞。"""
    norm = normalize_commitment_stages(stages_raw)
    if not norm:
        return False
    try:
        et = int(end_turn or 0)
    except (TypeError, ValueError):
        et = 0
    # 无独立 end_turn：分段只走 next_audience_todos
    if et <= 0:
        return True
    # 段派生展示 end_turn：改道；显式独立 end_turn（≠ max due）：保留 form③
    return is_stage_derived_end_turn(norm, et)


def list_due_stages_for_scan(db: Any, turn: int) -> List[Dict[str, object]]:
    """段到期扫描（独立 SQL；与 form③ 共享「active 承诺 + 到期」谓词语义，不共用结果集）。

    去重键在写端用 (commitment_id, stage_idx)；此处返回全部到期段候选。
    """
    rows = db.conn.execute(
        """
        SELECT id, title, stages_json, origin_ref, origin_turn, stage_text
        FROM issues
        WHERE status='active'
          AND commitment_kind != ''
          AND stages_json IS NOT NULL
          AND stages_json != ''
          AND stages_json != '[]'
        ORDER BY id
        """
    ).fetchall()
    due: List[Dict[str, object]] = []
    for row in rows:
        stages = normalize_commitment_stages(row["stages_json"])
        for stage in stages:
            if int(stage["due_turn"]) <= int(turn):
                due.append({
                    "commitment_ref": int(row["id"]),
                    "stage_idx": int(stage["stage_idx"]),
                    "due_turn": int(stage["due_turn"]),
                    "criterion_text": str(stage["criterion_text"]),
                    "origin_context": str(stage["origin_context"]),
                    "title": str(row["title"] or ""),
                    "origin_ref": str(row["origin_ref"] or ""),
                })
    return due


def list_due_grant_report_dossiers_for_scan(
    db: Any, turn: int,
) -> List[Dict[str, object]]:
    """#1783：执行中拨帑案卷 due_turn 到期 → 0076 候选（不另立 issue）。

    commitment_ref=0；stage_idx=dossier_id 作 UNIQUE 去重键；
    payload 携带 dossier_id/origin_ref 供 due_review 桥接。
    复用 get_decree_dossier 响亮读口，不平行宽容腐坏 payload（#1897 E1/K2）。
    """
    rows = db.conn.execute(
        """
        SELECT id, due_turn, execution_outcome
        FROM decree_dossiers
        WHERE status='executing'
          AND action_type='grant_allocation'
          AND due_turn > 0
          AND due_turn <= ?
        ORDER BY id
        """,
        (int(turn),),
    ).fetchall()
    due: List[Dict[str, object]] = []
    for row in rows:
        if str(row["execution_outcome"] or "").strip():
            continue
        from ming_sim.db import GameDB

        payload = GameDB.parse_engine_payload_json(
            row["payload_json"], surface="decree_dossiers.payload_json",
        )
        # due_turn 单源：有未来 due 且仍 executing 即到期候选（不另滤 cadence/grant_action）
        did = int(row["id"])
        dossier = db.get_decree_dossier(did)
        if dossier is None:
            raise ValueError(f"案卷不存在：{did}")
        payload = dossier.get("payload") or {}
        if not isinstance(payload, dict):
            raise ValueError(f"案卷#{did} payload_json 非对象")
        # due_turn 单源：有未来 due 且仍 executing 即到期候选（不另滤 cadence/grant_action）
        due_turn = int(row["due_turn"] or 0)
        # #1897：due 扫描写入待办的自由字段原样透传，禁 strip。
        title = str(payload.get("title") or payload.get("purpose") or "")
        criterion = str(payload.get("ongoing_effects") or "") or title or "依限奏报"
        origin = str(dossier.get("decree_text") or payload.get("text") or criterion)
        due.append({
            "commitment_ref": 0,
            "stage_idx": did,  # UNIQUE(commitment_ref, stage_idx, entry_kind)
            "due_turn": due_turn,
            "criterion_text": criterion,
            "origin_context": origin,
            "title": title or criterion,
            "origin_ref": f"dossier:{did}",
            "payload_json": {
                "dossier_id": did,
                "origin_ref": f"dossier:{did}",
                "grant_report_deadline": True,
            },
        })
    return due


def write_due_staged_commitment_todos(db: Any, state: Any, *, commit: bool = True) -> int:
    """结算内确定性写入次回合召对待办。返回新写入条数。

    待裁载体改道 next_audience_todos；不置 TurnPhase.AWAITING_DECISION，
    不写 <<DECISION>>，不停轮（0074/0076）。
    #1783：并入拨帑案卷 due_turn 直挂（commitment_ref=0），不另立承诺事项。
    """
    turn = int(getattr(state, "turn", 0) or 0)
    due_stages = list_due_stages_for_scan(db, turn)
    due_stages.extend(list_due_grant_report_dossiers_for_scan(db, turn))
    if not due_stages:
        return 0
    written = 0
    for item in due_stages:
        created = db.insert_next_audience_todo(
            commitment_ref=int(item["commitment_ref"]),
            stage_idx=int(item["stage_idx"]),
            due_turn=int(item["due_turn"]),
            criterion_text=str(item["criterion_text"]),
            origin_context=str(item["origin_context"]),
            status=TODO_STATUS_PENDING,
            entry_kind=ENTRY_KIND_STAGED,
            created_turn=turn,
            payload_json=item.get("payload_json"),
            commit=False,
        )
        if created:
            written += 1
    if commit and written:
        db.conn.commit()
    return written
