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

from ming_sim.strict_types import strict_int, strict_sqlite_id

from ming_sim.applier import (
    StoredDocumentError,
    load_stored_list,
)

ENTRY_KIND_STAGED = "staged_commitment"
# #624 / ADR 0078：反催谏 / 求宽限（0075 同款 next_audience_todos 通道；不进 due-review 白名单）
ENTRY_KIND_RUSH_REMONSTRANCE = "rush_remonstrance"
ENTRY_KIND_GRACE_PLEA = "grace_plea"
TODO_STATUS_PENDING = "pending"
TODO_STATUS_CONSUMED = "consumed"
# rolled 写口仍由 mark_next_audience_todo_status 接受（P3 契约）；常量待 #623 超额滚存启用再导出。


def _stage_text_fields(item: Dict[str, object]) -> tuple[str, str] | None:
    """写口前置正文归一化（criterion/origin 别名与回填）——只在写口调用。

    返回 (criterion_text, origin_context)；缺正文或纯空白返回 None，坏类型拒收。
    #1897 / ADR0142：自由正文原样入载体，禁 strip 规范化；``strip`` 只用于空判。
    持久读口不走此面，只认 ``stages_to_json`` 写出的规范四字段（#1897 G）。
    """
    for field in ("criterion_text", "criterion", "origin_context", "origin"):
        if field in item and not isinstance(item[field], str):
            raise TypeError(f"stages.{field} 须为字符串")
    criterion = item.get("criterion_text") or item.get("criterion") or ""
    origin_context = item.get("origin_context") or item.get("origin") or criterion
    if not criterion and origin_context:
        criterion = origin_context
    if not isinstance(criterion, str) or not criterion.strip():
        return None
    if not isinstance(origin_context, str) or not origin_context.strip():
        return None
    return criterion, origin_context


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


def _prepare_stages_for_write(data: Sequence[object]) -> List[object]:
    """写口专用前置归一化：别名／正文回填／已出现值的数字串 → 规范草稿。

    不发明 ``stage_idx``；缺失／空值／非对象原样交给唯一成员门拒收（#1897 G/G2）。
    成员规则只在 ``_commitment_stages_members``，此处不复制拒收。
    """
    prepared: List[object] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            prepared.append(item)
            continue
        draft = dict(item)
        # TypeError（坏类型）仍从写口前置响亮；缺／空白正文不在此拒，交成员门。
        texts = _stage_text_fields(item)
        if texts is not None:
            draft["criterion_text"], draft["origin_context"] = texts
        # due_turn／stage_idx 同形：仅对已出现非空值做数字串→int；空缺原样交成员门。
        # 复用同一 strict_int 调用，不另抽 helper（SQLite 范围仍只在成员门）。
        for field in ("due_turn", "stage_idx"):
            if field not in draft or draft[field] in (None, ""):
                continue
            try:
                draft[field] = strict_int(
                    draft[field], accept_numeric_strings=True,
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(f"stages[{idx}].{field} 须为有限整数") from exc
        prepared.append(draft)
    return prepared


def _commitment_stages_members(data: Sequence[object]) -> List[Dict[str, object]]:
    """分段成员准入唯一权威：写口（前置归一化后）与全部持久读口共用此面。

    只认规范形：四字段齐全，``stage_idx``／``due_turn`` 为真整数（拒数字串），
    正文非空字符串，同一承诺内 ``stage_idx`` 不重复。不设缺省、别名、回填。
    已持久腐坏不得洗成合法身份（#1897 G；函数自身 docstring 旧约同向）。
    ``due_turn`` 复用 ``strict_int``；``stage_idx`` 复用 ``strict_sqlite_id``
    （SQLite UNIQUE 绑定键，#1897 D′）。
    Raises ValueError/TypeError on bad members. Write seam keeps those;
    durable load wraps as StoredDocumentError.
    """
    out: List[Dict[str, object]] = []
    seen: set[int] = set()
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"stages[{idx}] 须为对象")
        if "stage_idx" not in item or item["stage_idx"] in (None, ""):
            raise ValueError(f"stages[{idx}] 缺 stage_idx")
        if "due_turn" not in item or item["due_turn"] in (None, ""):
            raise ValueError(f"stages[{idx}] 缺 due_turn")
        try:
            stage_idx = strict_sqlite_id(
                item["stage_idx"], accept_numeric_strings=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"stages[{idx}].stage_idx 须为有限整数") from exc
        if stage_idx < 0:
            raise ValueError(f"stages[{idx}].stage_idx 须为非负整数")
        if stage_idx in seen:
            raise ValueError(f"stages[{idx}].stage_idx 重复")
        seen.add(stage_idx)
        try:
            due_turn = strict_int(item["due_turn"], accept_numeric_strings=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"stages[{idx}].due_turn 须为有限整数") from exc
        if due_turn <= 0:
            raise ValueError(f"stages[{idx}].due_turn 须为正")
        for field in ("criterion_text", "origin_context"):
            if field not in item:
                raise ValueError(f"stages[{idx}] 缺非空 {field}")
            val = item[field]
            if not isinstance(val, str):
                raise TypeError(f"stages.{field} 须为字符串")
            if not val.strip():
                raise ValueError(f"stages[{idx}] 缺非空 {field}")
        out.append(_stage_record(
            stage_idx=stage_idx, due_turn=due_turn,
            criterion_text=item["criterion_text"],  # type: ignore[arg-type]
            origin_context=item["origin_context"],  # type: ignore[arg-type]
        ))
    out.sort(key=lambda s: (s["stage_idx"], s["due_turn"]))
    return out


def normalize_commitment_stages(raw: object) -> List[Dict[str, object]]:
    """Normalize structured stages payload → durable list（写口／声明入口）。

    缺省（None/""/[]/"[]"）→ 空列表；顶层 JSON/schema 坏形 → ValueError。
    写口可做别名／正文回填／数字串前置归一化，再交唯一成员准入
    ``_commitment_stages_members``（#1897 D／G；ADR0005）。不发明 ``stage_idx``。

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
                f"stages_json 须为 JSON 数组字符串，解析失败：{exc}；原值 {text!r}"
            ) from exc
    if not isinstance(data, (list, tuple)):
        raise ValueError(f"stages_json 须为 JSON 数组，得 {type(data).__name__}")
    if len(data) == 0:
        return []
    return _commitment_stages_members(_prepare_stages_for_write(data))


def load_commitment_stages(raw: object) -> List[Dict[str, object]]:
    """持久 stages_json 唯一真实加载口。

    顶层与成员形状故障一律 StoredDocumentError；成员准入与写口共用
    ``_commitment_stages_members``，但不跑写口前置归一化（#1897 G）。
    """
    data = load_stored_list(raw, label="stages_json")
    try:
        return _commitment_stages_members(data)
    except (TypeError, ValueError) as exc:
        raise StoredDocumentError(str(exc)) from exc


def stages_to_json(stages: object) -> str:
    """Serialize stages for durable DB write.

    顶层缺省／JSON 解码／数组准入 = ``normalize_commitment_stages``（成员面同上）；
    本口只序列化其结果。``None`` / empty / ``[]`` → ``"[]"``。
    """
    normalized = normalize_commitment_stages(stages)
    if not normalized:
        return "[]"
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))


def stages_list_from_source(stages: object) -> List[Dict[str, object]]:
    """Strict serial capture: reuse ``stages_to_json``, never a parallel parser."""
    return json.loads(stages_to_json(stages))


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
    norm = load_commitment_stages(stages)
    if not norm:
        return False
    et = int(end_turn or 0)
    if et <= 0:
        return False
    return et == max(int(s["due_turn"]) for s in norm)


def should_skip_form3_due_for_staged(
    stages_raw: object,
    end_turn: int,
) -> bool:
    """form③ due_commitments 跳过面：仅段派生 end_turn 改道；独立 end_turn 待裁不吞。"""
    norm = load_commitment_stages(stages_raw)
    if not norm:
        return False
    et = int(end_turn or 0)
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
        SELECT id, stages_json
        FROM issues
        WHERE status='active'
          AND commitment_kind != ''
          AND stages_json IS NOT NULL
          AND stages_json != ''
          AND stages_json != '[]'
        ORDER BY id
        """,
        (),
    ).fetchall()
    due: List[Dict[str, object]] = []
    for row in rows:
        stages = load_commitment_stages(row["stages_json"])
        for stage in stages:
            if int(stage["due_turn"]) <= int(turn):
                due.append({
                    "commitment_ref": int(row["id"]),
                    "stage_idx": int(stage["stage_idx"]),
                    "due_turn": int(stage["due_turn"]),
                    "criterion_text": stage["criterion_text"],
                    "origin_context": stage["origin_context"],
                })
    return due


def list_due_grant_report_dossiers_for_scan(
    db: Any, turn: int,
) -> List[Dict[str, object]]:
    """#1783：执行中拨帑案卷 due_turn 到期 → 0076 候选（不另立 issue）。

    commitment_ref=0；stage_idx=dossier_id 作 UNIQUE 去重键；
    payload 携带 dossier_id/origin_ref 供 due_review 桥接。
    复用 DossierStore.get 响亮读口，不平行宽容腐坏 payload（#1897 E1/K2）。
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
        did = int(row["id"])
        dossier = db.dossiers.get(did)
        if dossier is None:
            raise ValueError(f"案卷不存在：{did}")
        payload = dossier["payload"]  # DossierStore.get 经权威解码，必为 dict
        # due_turn 单源：有未来 due 且仍 executing 即到期候选（不另滤 cadence/grant_action）
        due_turn = int(row["due_turn"] or 0)
        # #1897：due 扫描写入待办的自由字段原样透传，禁 strip。
        title = str(payload.get("title") or payload.get("purpose") or "")
        criterion = str(payload.get("ongoing_effects") or "") or title
        origin = str(dossier.get("decree_text") or payload.get("text") or criterion)
        due.append({
            "commitment_ref": 0,
            "stage_idx": did,  # UNIQUE(commitment_ref, stage_idx, entry_kind)
            "due_turn": due_turn,
            "criterion_text": criterion,
            "origin_context": origin,
            # 写端不读 title/顶层 origin_ref；来源在 payload_json。
            "payload_json": {
                "dossier_id": did,
                "origin_ref": f"dossier:{did}",
                "grant_report_deadline": True,
            },
        })
    return due


def list_due_minister_promise_oneshots_for_scan(
    db: Any, state: Any,
) -> List[Dict[str, object]]:
    """#1916：大臣自诺 form③ 到期 → 召对待办投影。

    到期谓词唯一真源＝``settlement_payload.list_due_commitments``；此处只滤
    ``origin_kind=minister_promise`` 并投影 next_audience_todos 字段。
    收尾仍走 close_issues acknowledged。
    """
    from ming_sim.settlement_payload import list_due_commitments

    due: List[Dict[str, object]] = []
    for item in list_due_commitments(db, state):
        if str(item.get("origin_kind") or "") != "minister_promise":
            continue
        criterion = str(item.get("content") or item.get("title") or "")
        origin_ref = str(item.get("origin_ref") or "")
        due.append({
            "commitment_ref": int(item["issue_id"]),
            "stage_idx": 0,
            "due_turn": int(item.get("due_turn") or 0),
            "criterion_text": criterion,
            "origin_context": criterion,
            # 写端只读 commitment_ref/stage/due/criterion/origin_context/payload；
            # 来源载荷走 payload_json.origin_ref（#1916 删无消费者投影）。
            "payload_json": {"origin_ref": origin_ref} if origin_ref else None,
        })
    return due


def write_due_staged_commitment_todos(db: Any, state: Any) -> int:
    """结算内确定性写入次回合召对待办。返回新写入条数。

    待裁载体改道 next_audience_todos；不置 TurnPhase.AWAITING_DECISION，
    不写 <<DECISION>>，不停轮（0074/0076）。
    #1783：并入拨帑案卷 due_turn 直挂（commitment_ref=0），不另立承诺事项。
    #1916：并入大臣自诺 form③ 一次性到期（谓词复用 list_due_commitments）。
    """
    turn = int(getattr(state, "turn", 0) or 0)
    due_stages = list_due_stages_for_scan(db, turn)
    due_stages.extend(list_due_grant_report_dossiers_for_scan(db, turn))
    due_stages.extend(list_due_minister_promise_oneshots_for_scan(db, state))
    if not due_stages:
        return 0
    written = 0
    for item in due_stages:
        created = db.dossiers.insert_next_audience_todo(
            commitment_ref=int(item["commitment_ref"]),
            stage_idx=int(item["stage_idx"]),
            due_turn=int(item["due_turn"]),
            criterion_text=item["criterion_text"],
            origin_context=item["origin_context"],
            status=TODO_STATUS_PENDING,
            entry_kind=ENTRY_KIND_STAGED,
            created_turn=turn,
            payload_json=item.get("payload_json"),
            commit=False,
        )
        if created:
            written += 1
    return written
