"""#623 / ADR 0075 挽留场——松手检测·哭谏·根基分档。

entry_kind = midcourse_breach_plea（坚持撤不另造第二 kind）。
stage_idx = 触发当回合 turn（同承诺先后两次松手各得独立哭谏条）。

kind 分派矩阵（法）：
- list_due_review_scenes：投影哭谏场面
- apply_pending_due_reviews：禁当 staged 终裁；沉默保留 pending
- dossiers_with_pending_due_review：不计入接管窗
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from ming_sim.db import GameDB
from ming_sim.models import loads_effect_dict
from ming_sim.staged_commitment import (
    TODO_STATUS_CONSUMED,
    TODO_STATUS_PENDING,
    normalize_commitment_stages,
)

ENTRY_KIND_BREACH_PLEA = "midcourse_breach_plea"

BREACH_KIND_FUNDING = "funding_cutoff"
BREACH_KIND_MISAPPROPRIATION = "misappropriation"
BREACH_KIND_REMOVE_SPONSOR = "remove_sponsor"
BREACH_KIND_POLICY_REVERSAL = "policy_reversal"

BREACH_KIND_LABELS = {
    BREACH_KIND_FUNDING: "断供",
    BREACH_KIND_MISAPPROPRIATION: "挪用",
    BREACH_KIND_REMOVE_SPONSOR: "撤人",
    BREACH_KIND_POLICY_REVERSAL: "改弦",
}

# 坚持撤时触发 0056 毁约轨的松手类（0041③ 收权·罢差 / 撤人不触发）
_BREACH_KINDS_TRIGGER_0056 = frozenset({
    BREACH_KIND_FUNDING,
    BREACH_KIND_MISAPPROPRIATION,
    BREACH_KIND_POLICY_REVERSAL,
})

FOUNDATION_JUST_STARTED = "just_started"
FOUNDATION_HALFWAY = "halfway"
FOUNDATION_ROOTED = "rooted"

_DOSSIER_REF_RE = re.compile(r"^dossier:([1-9][0-9]*)$")

_META_PREFIX = "breach_plea_meta:"


def parse_dossier_id(origin_ref: object) -> Optional[int]:
    text = str(origin_ref or "").strip()
    match = _DOSSIER_REF_RE.match(text)
    if not match:
        return None
    return int(match.group(1))


def encode_plea_meta(meta: Dict[str, object]) -> str:
    """origin_context 承载机读元数据（场面投影只取 display，不泄 JSON）。"""
    payload = dict(meta or {})
    return _META_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def decode_plea_meta(origin_context: object) -> Dict[str, object]:
    text = str(origin_context or "").strip()
    if not text.startswith(_META_PREFIX):
        return {"display": text, "breach_kind": "", "reason": text}
    raw = text[len(_META_PREFIX):]
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {"display": text, "breach_kind": "", "reason": text}
    if not isinstance(data, dict):
        return {"display": text, "breach_kind": "", "reason": text}
    return data


def commitment_natural_due_turn(row: Any) -> int:
    """承诺自身 due：段表 max due，否则 end_turn；0=无到期上限。"""
    try:
        keys = row.keys()  # sqlite3.Row
    except Exception:
        keys = list(row.keys()) if isinstance(row, dict) else []
    stages_raw = row["stages_json"] if "stages_json" in keys else (
        row.get("stages_json") if isinstance(row, dict) else None
    )
    stages = normalize_commitment_stages(stages_raw)
    if stages:
        return max(int(s["due_turn"]) for s in stages)
    try:
        end_turn = int(row["end_turn"] if "end_turn" in keys else (
            row.get("end_turn") if isinstance(row, dict) else 0
        ) or 0)
    except (TypeError, ValueError):
        end_turn = 0
    return end_turn if end_turn > 0 else 0


def _issue_row(db: Any, commitment_ref: int) -> Any:
    return db.conn.execute(
        "SELECT * FROM issues WHERE id=?", (int(commitment_ref),),
    ).fetchone()


def list_active_commitments(db: Any) -> List[Any]:
    return list(db.conn.execute(
        """
        SELECT * FROM issues
        WHERE status='active'
          AND kind='initiative'
          AND commitment_kind != ''
        ORDER BY id
        """
    ).fetchall())


def _sponsor_names_for_commitment(db: Any, row: Any) -> List[str]:
    names: List[str] = []
    # issue participant_roster
    try:
        roster = json.loads(row["participant_roster"] or "[]")
    except (TypeError, ValueError):
        roster = []
    if isinstance(roster, list):
        for item in roster:
            if isinstance(item, dict) and item.get("tier") == "主办":
                cid = str(item.get("character_id") or "").strip()
                if cid:
                    names.append(cid)
    # dossier roster fallback
    did = parse_dossier_id(row["origin_ref"] if "origin_ref" in row.keys() else "")
    if did is not None:
        dossier = db.get_decree_dossier(int(did))
        if dossier is not None:
            for item in dossier.get("participant_roster") or []:
                if isinstance(item, dict) and item.get("tier") == "主办":
                    cid = str(item.get("character_id") or "").strip()
                    if cid and cid not in names:
                        names.append(cid)
            exec_id = str(dossier.get("executor_id") or "").strip()
            if exec_id and exec_id not in names:
                names.append(exec_id)
    return names


def _dedicated_account(row: Any) -> str:
    """专款账户：stop_condition.专款 / dedicated_account / tags 含 专款:X。"""
    keys = row.keys()
    stop_raw = row["stop_condition"] if "stop_condition" in keys else ""
    stop: Dict[str, object] = {}
    if isinstance(stop_raw, dict):
        stop = stop_raw
    else:
        text = str(stop_raw or "").strip()
        if text.startswith("{"):
            try:
                loaded = json.loads(text)
                if isinstance(loaded, dict):
                    stop = loaded
            except (TypeError, ValueError):
                stop = {}
    for key in ("专款", "dedicated_account", "专款账户"):
        val = str(stop.get(key) or "").strip()
        if val:
            return val
    tags_raw = row["tags"] if "tags" in keys else "[]"
    try:
        tags = json.loads(tags_raw or "[]")
    except (TypeError, ValueError):
        tags = []
    if isinstance(tags, list):
        for tag in tags:
            t = str(tag or "").strip()
            if t.startswith("专款:"):
                return t.split(":", 1)[1].strip()
    return ""


def has_pending_plea(
    db: Any,
    commitment_ref: int,
    *,
    breach_kind: str = "",
) -> bool:
    for todo in db.list_next_audience_todos(status=TODO_STATUS_PENDING):
        if str(todo.get("entry_kind") or "") != ENTRY_KIND_BREACH_PLEA:
            continue
        if int(todo.get("commitment_ref") or 0) != int(commitment_ref):
            continue
        if breach_kind:
            meta = decode_plea_meta(todo.get("origin_context"))
            if str(meta.get("breach_kind") or "") != breach_kind:
                continue
        return True
    return False


def write_breach_plea_todo(
    db: Any,
    state: Any,
    *,
    commitment_ref: int,
    breach_kind: str,
    reason: str = "",
    target_dossier_id: int = 0,
    display: str = "",
    extra: Optional[Dict[str, object]] = None,
    commit: bool = False,
) -> int:
    """松手当回合写挽留 todo。stage_idx=触发 turn。返回新建 id；幂等冲突返回 0。"""
    row = _issue_row(db, int(commitment_ref))
    if row is None or str(row["status"] or "") != "active":
        return 0
    if not str(row["commitment_kind"] or "").strip():
        return 0
    turn = int(getattr(state, "turn", 0) or 0)
    kind = str(breach_kind or "").strip()
    if kind not in BREACH_KIND_LABELS:
        raise ValueError(f"未知松手类型：{kind}")
    label = BREACH_KIND_LABELS[kind]
    due = commitment_natural_due_turn(row)
    # 无自身 due 时 due_turn 挂触发 turn（滚存不靠 due 机械结；到期结账仅 due>trigger）
    due_turn = due if due > 0 else turn
    title = str(row["title"] or "")
    disp = str(display or "").strip() or (
        f"臣工泣谏：皇上于「{title}」有{label}之举，臣的信心一半是皇爷给的，请陛下三思。"
    )
    meta: Dict[str, object] = {
        "breach_kind": kind,
        "reason": str(reason or label)[:400],
        "target_dossier_id": int(target_dossier_id or 0),
        "display": disp[:400],
        "commitment_title": title[:120],
    }
    if extra:
        for k, v in extra.items():
            if k not in meta:
                meta[k] = v
    todo_id = db.insert_next_audience_todo(
        commitment_ref=int(commitment_ref),
        stage_idx=turn,  # 法：触发当回合 turn
        due_turn=int(due_turn),
        criterion_text=label,
        origin_context=encode_plea_meta(meta),
        status=TODO_STATUS_PENDING,
        entry_kind=ENTRY_KIND_BREACH_PLEA,
        created_turn=turn,
        commit=False,
    )
    if commit and todo_id:
        db.conn.commit()
    return int(todo_id or 0)


def project_breach_plea_scene(
    db: Any, todo: Dict[str, object],
) -> Dict[str, object]:
    meta = decode_plea_meta(todo.get("origin_context"))
    breach_kind = str(meta.get("breach_kind") or "")
    label = BREACH_KIND_LABELS.get(breach_kind, str(todo.get("criterion_text") or "松手"))
    display = str(meta.get("display") or "").strip()
    title = str(meta.get("commitment_title") or "")
    if not display:
        display = (
            f"主办哭谏：前诺「{title}」遭{label}，"
            f"臣的信心一半是皇爷给的，求皇上收回成命。"
        )
    # 禁系统词
    for token in (
        "fulfilled", "degraded", "failed", "transformed", "executing",
        "AWAITING_DECISION", "<<DECISION>>", "midcourse_breach_plea",
        "progress_band", "just_started", "halfway", "rooted",
    ):
        display = display.replace(token, "")
    return {
        "kind": "breach_plea",
        "entry_kind": ENTRY_KIND_BREACH_PLEA,
        "todo_id": int(todo["id"]),
        "commitment_ref": int(todo["commitment_ref"]),
        "stage_idx": int(todo["stage_idx"]),
        "due_turn": int(todo.get("due_turn") or 0),
        "breach_kind": breach_kind,
        "criterion_text": str(todo.get("criterion_text") or label),
        "origin_context": display,
        "scene_text": display,
        "channel": "audience_pending",  # 召对待裁通道
    }


def assess_foundation_tier(db: Any, commitment_ref: int) -> str:
    """根基三档：禁完成度数值列；读已过段数 / 已投入 / 实际进度定性 band。"""
    row = _issue_row(db, int(commitment_ref))
    if row is None:
        return FOUNDATION_JUST_STARTED
    stages = normalize_commitment_stages(
        row["stages_json"] if "stages_json" in row.keys() else None
    )
    bar = int(row["bar_value"] or 0)
    # 已过段数：按 bar 映射到段序（定性档界，非独立完成度列）
    stages_passed = 0
    n_stages = len(stages)
    if n_stages <= 0:
        stages_passed = 0
    elif n_stages == 1:
        stages_passed = 1 if bar >= 50 else 0
    else:
        stages_passed = min(n_stages, max(0, int(bar * n_stages // 100)))

    # 已投入（economy|fiscal 流水）
    did = parse_dossier_id(row["origin_ref"] if "origin_ref" in row.keys() else "")
    spent = 0
    if did is not None:
        for mv in db.list_economy_moves_for_dossier(int(did)):
            try:
                delta = int(mv.get("delta") or 0)
            except (TypeError, ValueError):
                delta = 0
            if delta < 0:
                spent += -delta
        for _fx in db.list_fiscal_effects_for_dossier(int(did)):
            spent += 1
    origin = str(row["origin_ref"] or "")
    if origin:
        for r in db.conn.execute(
            "SELECT delta FROM economy_ledger WHERE origin_ref=? AND delta<0",
            (origin,),
        ).fetchall():
            spent += abs(int(r["delta"] or 0))

    # 实际进度定性 band
    band = ""
    if did is not None:
        progress = db.list_dossier_progress(int(did))
        if progress:
            band = str(progress[-1].get("progress_band") or "")

    rooted_bands = {"告成", "已成", "生根", "完工", "就绪"}
    mid_bands = {"在办", "过半", "在途", "推进"}

    if band in rooted_bands or bar >= 70:
        return FOUNDATION_ROOTED
    if n_stages >= 2 and stages_passed >= n_stages:
        return FOUNDATION_ROOTED
    if (
        band in mid_bands
        or (30 <= bar < 70)
        or (n_stages >= 2 and 0 < stages_passed < n_stages)
        or (spent > 0 and bar >= 25)
    ):
        return FOUNDATION_HALFWAY
    return FOUNDATION_JUST_STARTED


def _apply_halfway_national_setback(
    db: Any, state: Any, *, title: str, reason: str, origin_ref: str,
) -> Dict[str, object]:
    """办到一半：国势本身倒退——写侧走既有 issue/metrics 缝（0014 涌现可挂），禁 live-LLM。"""
    # 国势轴：民心/边防类可见倒退（写 metrics + 局势 issue）
    metrics_hit = {"民心": -3, "边防": -2}
    for key, delta in metrics_hit.items():
        cur = int(state.metrics.get(key, 0) or 0)
        state.metrics[key] = max(0, cur + int(delta))
    issue_id = db.insert_issue(
        state,
        kind="situation",
        title=f"{title}·半途而废余波",
        origin_kind="breach_plea",
        origin_ref=origin_ref or f"breach:{title}",
        stage_text="办到一半松手，局势反受其累",
        bar_value=35,
        inertia=-2,
        severity=55,
        ongoing_effects={},
        effect_on_fail={"metrics": {"民心": -1}},
        cancellable="never",
        commit=False,
    )
    # 记一笔 advance 叙事，写侧可查
    db.advance_issue(
        state,
        int(issue_id),
        trigger_kind="breach_plea_setback",
        trigger_ref=origin_ref,
        delta_bar=-5,
        stage_text="国势倒退",
        narrative=str(reason or "办到一半撤诺，沉没投入化为负累")[:400],
        metric_delta=metrics_hit,
        commit=False,
    )
    return {
        "setback_issue_id": int(issue_id),
        "metrics_delta": metrics_hit,
    }


def finalize_persist(
    db: Any,
    state: Any,
    todo: Dict[str, object],
    *,
    commit: bool = False,
) -> Dict[str, object]:
    """坚持撤：根基分档落执行格 + 条件触发 0056 + 消费 todo。"""
    meta = decode_plea_meta(todo.get("origin_context"))
    breach_kind = str(meta.get("breach_kind") or "")
    reason = str(meta.get("reason") or todo.get("criterion_text") or "坚持撤诺")[:400]
    commitment_ref = int(todo["commitment_ref"])
    row = _issue_row(db, commitment_ref)
    title = str(row["title"] if row is not None else meta.get("commitment_title") or "")
    origin_ref = str(row["origin_ref"] if row is not None else "")
    target_dossier_id = int(meta.get("target_dossier_id") or 0)
    if target_dossier_id <= 0:
        parsed = parse_dossier_id(origin_ref)
        target_dossier_id = int(parsed or 0)

    tier = assess_foundation_tier(db, commitment_ref)
    setback: Dict[str, object] = {}
    exec_result: Dict[str, object] = {}

    if tier == FOUNDATION_ROOTED:
        outcome = "degraded"
        note = f"根基已成而撤后续之诺，只失未兑现红利（{reason}）"[:200]
        close = True
    elif tier == FOUNDATION_HALFWAY:
        outcome = "failed"
        note = f"事废：办到一半松手，沉没投入与国势倒退（{reason}）"[:200]
        close = True
        setback = _apply_halfway_national_setback(
            db, state, title=title, reason=reason, origin_ref=origin_ref,
        )
    else:
        outcome = "failed"
        note = f"刚起头撤，所费付诸东流（{reason}）"[:200]
        close = True

    # 0056：仅毁约触发类；幂等认领 cost_identity=breach
    breach_applied = False
    if breach_kind in _BREACH_KINDS_TRIGGER_0056 and target_dossier_id > 0:
        breach_applied = bool(
            db.breach_decree_dossier(
                state, int(target_dossier_id), reason=reason, commit=False,
            )
        )

    # 执行格：若案卷仍 executing 且 0056 未关（或未走 0056），经既有适配器落格
    if target_dossier_id > 0:
        dossier = db.get_decree_dossier(int(target_dossier_id))
        if dossier is not None and str(dossier.get("status") or "") == "executing":
            db.record_dossier_execution(
                int(target_dossier_id), outcome, note, int(state.turn),
                close=close, commit=False,
            )
            if outcome in {"degraded", "failed", "transformed"}:
                db.record_dossier_progress(
                    int(target_dossier_id), int(state.turn), outcome, note,
                    is_terminal=True,
                    origin=GameDB.DOSSIER_REPORT_ORIGIN_VERDICT,
                    commit=False,
                )
            exec_result = {
                "dossier_id": int(target_dossier_id),
                "outcome": outcome,
                "close": close,
            }
        elif dossier is not None:
            # 已由 breach 关闭：补 note 到 interruption 已有；执行格若空则尽量记
            exec_result = {
                "dossier_id": int(target_dossier_id),
                "outcome": str(dossier.get("execution_outcome") or outcome),
                "already_closed": True,
            }
            if not str(dossier.get("execution_outcome") or "").strip():
                try:
                    db.conn.execute(
                        "UPDATE decree_dossiers SET execution_outcome=?, execution_note=? WHERE id=?",
                        (outcome, note, int(target_dossier_id)),
                    )
                except Exception:
                    pass

    # 承诺停 tick
    if row is not None and str(row["status"] or "") == "active":
        db.cancel_issue(state, commitment_ref, narrative=note, commit=False)

    # 0079 信用事件：回绝哭谏 = 辜负（0056 内已对主办写边；此处兜底无案卷时）
    if target_dossier_id <= 0:
        for person in _sponsor_names_for_commitment(db, row) if row is not None else []:
            db.record_relation_edge_event(
                source="皇帝", target=person, event_kind="辜负", context=reason,
                origin=f"issue:{commitment_ref}:breach_plea", turn=state.turn,
                year=state.year, period=state.period,
            )

    consumed = db.mark_next_audience_todo_status(
        int(todo["id"]), TODO_STATUS_CONSUMED, commit=False,
    )
    if commit:
        db.conn.commit()
    return {
        "decision": "persist",
        "todo_id": int(todo["id"]),
        "commitment_ref": commitment_ref,
        "breach_kind": breach_kind,
        "foundation_tier": tier,
        "outcome": outcome,
        "note": note,
        "breach_0056": breach_applied,
        "setback": setback,
        "execution": exec_result,
        "consumed": bool(consumed),
    }


def finalize_regret(
    db: Any,
    state: Any,
    todo: Dict[str, object],
    *,
    commit: bool = False,
) -> Dict[str, object]:
    """反悔：两轨零落账，承诺续跑，消费 todo。"""
    meta = decode_plea_meta(todo.get("origin_context"))
    commitment_ref = int(todo["commitment_ref"])
    reason = str(meta.get("reason") or "皇上收回成命，承诺续跑")
    # 信用：撑腰
    row = _issue_row(db, commitment_ref)
    for person in _sponsor_names_for_commitment(db, row) if row is not None else []:
        db.record_relation_edge_event(
            source="皇帝", target=person, event_kind="撑腰",
            context=f"挽留场反悔：{reason}"[:400],
            origin=f"issue:{commitment_ref}:breach_plea_regret",
            turn=state.turn, year=state.year, period=state.period,
        )
    consumed = db.mark_next_audience_todo_status(
        int(todo["id"]), TODO_STATUS_CONSUMED, commit=False,
    )
    if commit:
        db.conn.commit()
    return {
        "decision": "regret",
        "todo_id": int(todo["id"]),
        "commitment_ref": commitment_ref,
        "breach_kind": str(meta.get("breach_kind") or ""),
        "consumed": bool(consumed),
        "commitment_continues": True,
    }


def expire_breach_pleas_on_due(
    db: Any, state: Any, *, commit: bool = False,
) -> List[Dict[str, object]]:
    """承诺 due 到 → 挽留条目 consumed/失效；不走坚持撤分档、不补 0056/事轴倒退。"""
    turn = int(getattr(state, "turn", 0) or 0)
    results: List[Dict[str, object]] = []
    for todo in db.list_next_audience_todos(status=TODO_STATUS_PENDING):
        if str(todo.get("entry_kind") or "") != ENTRY_KIND_BREACH_PLEA:
            continue
        commitment_ref = int(todo["commitment_ref"])
        row = _issue_row(db, commitment_ref)
        # 承诺已非 active：条目关闭
        if row is None or str(row["status"] or "") != "active":
            db.mark_next_audience_todo_status(
                int(todo["id"]), TODO_STATUS_CONSUMED, commit=False,
            )
            results.append({
                "todo_id": int(todo["id"]),
                "expired": True,
                "reason": "commitment_inactive",
            })
            continue
        natural_due = commitment_natural_due_turn(row)
        if natural_due > 0 and natural_due <= turn:
            db.mark_next_audience_todo_status(
                int(todo["id"]), TODO_STATUS_CONSUMED, commit=False,
            )
            results.append({
                "todo_id": int(todo["id"]),
                "expired": True,
                "reason": "commitment_due",
                "due_turn": natural_due,
            })
    if commit and results:
        db.conn.commit()
    return results


# ── 四类松手检测 ──────────────────────────────────────────────────────


def _scan_funding_cutoff(db: Any, state: Any) -> List[int]:
    """断供：承诺曾有月供流水，而今 ongoing.economy 已空。"""
    written: List[int] = []
    turn = int(getattr(state, "turn", 0) or 0)
    for row in list_active_commitments(db):
        cid = int(row["id"])
        if has_pending_plea(db, cid, breach_kind=BREACH_KIND_FUNDING):
            continue
        ongoing = loads_effect_dict(row["ongoing_effects"] or "{}")
        economy = ongoing.get("economy") if isinstance(ongoing, dict) else None
        has_monthly = isinstance(economy, list) and any(
            isinstance(it, dict) and int(it.get("delta") or 0) != 0 for it in economy
        )
        if has_monthly:
            continue
        origin = str(row["origin_ref"] or "")
        # 须有历史供拨痕迹，避免从未拨款的空 ongoing 误触
        # 历史供拨含本回合已落流水（夹具常同回合先记流水再扫）
        prior_n = 0
        if origin:
            prior_n = int(db.conn.execute(
                "SELECT COUNT(*) AS c FROM economy_ledger WHERE origin_ref=? AND delta<0 AND turn<=?",
                (origin, turn),
            ).fetchone()["c"])
        if prior_n <= 0:
            prior_n = int(db.conn.execute(
                "SELECT COUNT(*) AS c FROM economy_ledger WHERE origin_ref=? AND delta<0 AND turn<=?",
                (f"issue:{cid}", turn),
            ).fetchone()["c"])
        if prior_n <= 0:
            continue
        tid = write_breach_plea_todo(
            db, state,
            commitment_ref=cid,
            breach_kind=BREACH_KIND_FUNDING,
            reason="承诺月供停拨",
            target_dossier_id=int(parse_dossier_id(origin) or 0),
            display=(
                f"主办哭谏：前诺「{row['title']}」月供已断，"
                f"臣的信心一半是皇爷给的，请陛下复其供亿。"
            ),
        )
        if tid:
            written.append(tid)
    return written


def _scan_misappropriation(db: Any, state: Any) -> List[int]:
    """挪用：专款账户本回合被非本承诺流向支用。"""
    written: List[int] = []
    turn = int(getattr(state, "turn", 0) or 0)
    for row in list_active_commitments(db):
        cid = int(row["id"])
        account = _dedicated_account(row)
        if not account:
            continue
        if has_pending_plea(db, cid, breach_kind=BREACH_KIND_MISAPPROPRIATION):
            continue
        origin = str(row["origin_ref"] or "")
        allowed_origins = {origin, f"issue:{cid}"}
        if origin:
            allowed_origins.add(origin)
        rows = db.conn.execute(
            """
            SELECT id, origin_ref, reason, purpose, delta FROM economy_ledger
            WHERE turn=? AND account=? AND delta<0
            """,
            (turn, account),
        ).fetchall()
        diverted = False
        for mv in rows:
            oref = str(mv["origin_ref"] or "")
            if oref in allowed_origins:
                continue
            # 空 origin 或其它用途 = 挪用
            diverted = True
            break
        if not diverted:
            continue
        tid = write_breach_plea_todo(
            db, state,
            commitment_ref=cid,
            breach_kind=BREACH_KIND_MISAPPROPRIATION,
            reason=f"专款「{account}」被挪作他用",
            target_dossier_id=int(parse_dossier_id(origin) or 0),
            display=(
                f"主办哭谏：专款「{account}」本为「{row['title']}」所备，"
                f"今见他流，臣的信心一半是皇爷给的，求陛下守约。"
            ),
        )
        if tid:
            written.append(tid)
    return written


def _character_removed(db: Any, name: str) -> bool:
    row = db.conn.execute(
        "SELECT status, office FROM characters WHERE name=?", (name,),
    ).fetchone()
    if row is None:
        return True
    status = str(row["status"] or "")
    if status in {"dismissed", "dead", "exiled", "imprisoned", "retired", "offstage"}:
        return True
    return False


def _scan_remove_sponsor(db: Any, state: Any) -> List[int]:
    """撤人：主办罢/调（character status 离岗；office_change_records 无 turn 列，不靠其筛当回合）。"""
    written: List[int] = []
    for row in list_active_commitments(db):
        cid = int(row["id"])
        if has_pending_plea(db, cid, breach_kind=BREACH_KIND_REMOVE_SPONSOR):
            continue
        sponsors = _sponsor_names_for_commitment(db, row)
        if not sponsors:
            continue
        removed = [s for s in sponsors if _character_removed(db, s)]
        if not removed:
            continue
        origin = str(row["origin_ref"] or "")
        who = "、".join(removed[:3])
        tid = write_breach_plea_todo(
            db, state,
            commitment_ref=cid,
            breach_kind=BREACH_KIND_REMOVE_SPONSOR,
            reason=f"主办{who}罢调，人亡政息",
            target_dossier_id=int(parse_dossier_id(origin) or 0),
            display=(
                f"臣工哭谏：「{row['title']}」主办{who}已去，"
                f"臣的信心一半是皇爷给的，人亡则政息，请陛下慎之。"
            ),
            extra={"removed_sponsors": removed},
        )
        if tid:
            written.append(tid)
    return written


def scan_and_write_breach_pleas(
    db: Any, state: Any, *, commit: bool = False,
) -> List[int]:
    """结算内扫描断供/挪用/撤人（改弦由 revoke 拦截缝直写）。"""
    written: List[int] = []
    written.extend(_scan_funding_cutoff(db, state))
    written.extend(_scan_misappropriation(db, state))
    written.extend(_scan_remove_sponsor(db, state))
    if commit and written:
        db.conn.commit()
    return written


def try_defer_revoke_to_breach_plea(
    db: Any,
    state: Any,
    *,
    target_dossier_id: int,
    target_issue_id: int = 0,
    reason: str = "",
    commit: bool = False,
) -> Optional[Dict[str, object]]:
    """改弦拦截：目标若挂 active 承诺，只写挽留 todo，返回 defer 信息；否则 None（走原 breach+close）。"""
    commitment_ids: List[int] = []
    if target_dossier_id > 0:
        origin_ref = f"dossier:{int(target_dossier_id)}"
        for iss in db.conn.execute(
            """
            SELECT id FROM issues
            WHERE origin_ref=? AND status='active' AND commitment_kind != ''
            """,
            (origin_ref,),
        ).fetchall():
            commitment_ids.append(int(iss["id"]))
    if target_issue_id > 0:
        row = db.conn.execute(
            "SELECT id, status, commitment_kind FROM issues WHERE id=?",
            (int(target_issue_id),),
        ).fetchone()
        if (
            row is not None
            and str(row["status"] or "") == "active"
            and str(row["commitment_kind"] or "").strip()
        ):
            if int(row["id"]) not in commitment_ids:
                commitment_ids.append(int(row["id"]))
    if not commitment_ids:
        return None
    written: List[int] = []
    for cid in commitment_ids:
        tid = write_breach_plea_todo(
            db, state,
            commitment_ref=cid,
            breach_kind=BREACH_KIND_POLICY_REVERSAL,
            reason=str(reason or "撤回成命")[:400],
            target_dossier_id=int(target_dossier_id or 0),
            display=(
                f"主办泣血陈情：皇上欲撤「"
                f"{_issue_row(db, cid)['title'] if _issue_row(db, cid) is not None else '前诺'}"
                f"」之旨，臣的信心一半是皇爷给的，求陛下收回成命。"
            ),
            extra={"deferred_revoke": True},
        )
        if tid:
            written.append(tid)
    if not written:
        # 已有同 turn 条（UNIQUE）——仍视为 deferred，避免双路径 breach
        return {
            "deferred": True,
            "commitment_ids": commitment_ids,
            "todo_ids": [],
            "reason": "already_pending_or_duplicate",
        }
    if commit:
        db.conn.commit()
    return {
        "deferred": True,
        "commitment_ids": commitment_ids,
        "todo_ids": written,
    }


# ── 召对 extraction 真入口：反悔 / 坚持 ────────────────────────────────


def _pending_breach_pleas(db: Any) -> List[Dict[str, object]]:
    return [
        t for t in db.list_next_audience_todos(status=TODO_STATUS_PENDING)
        if str(t.get("entry_kind") or "") == ENTRY_KIND_BREACH_PLEA
    ]


def _extract_issue_ids(items: object) -> set[int]:
    out: set[int] = set()
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        for key in ("issue_id", "id", "commitment_ref"):
            raw = it.get(key)
            if raw in (None, ""):
                continue
            try:
                out.add(int(raw))
            except (TypeError, ValueError):
                continue
        # target_id like issue:12
        tid = str(it.get("target_id") or "")
        if tid.startswith("issue:"):
            try:
                out.add(int(tid.split(":", 1)[1]))
            except (TypeError, ValueError):
                pass
    return out


def _extract_dossier_ids(items: object) -> set[int]:
    out: set[int] = set()
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        for key in ("dossier_id", "revoke_target_dossier_id"):
            raw = it.get(key)
            if raw in (None, ""):
                continue
            try:
                out.add(int(raw))
            except (TypeError, ValueError):
                continue
        tid = str(it.get("target_id") or "")
        if tid.startswith("dossier:"):
            try:
                out.add(int(tid.split(":", 1)[1]))
            except (TypeError, ValueError):
                pass
        elif tid.isdigit():
            out.add(int(tid))
    return out


def resolve_breach_pleas_from_extraction(
    db: Any,
    state: Any,
    extracted: Dict[str, object],
    *,
    commit: bool = False,
) -> List[Dict[str, object]]:
    """召对/结算 extraction 真入口：识别反悔或坚持后消费哭谏条。

    坚持信号：cancels 命中承诺 / revoke 类目标命中案卷 / 显式 breach_plea_decisions=persist
    反悔信号：economy 续拨本承诺 / issue_advances 推进 / 显式 regret / 加拨 fiscal
    沉默：不在此函数出现 → pending 保留
    """
    if not isinstance(extracted, dict):
        return []
    results: List[Dict[str, object]] = []
    pending = _pending_breach_pleas(db)
    if not pending:
        return []

    # 显式决策表（测试与 scripted 真入口）
    explicit = extracted.get("breach_plea_decisions") or []
    explicit_map: Dict[int, str] = {}
    if isinstance(explicit, list):
        for item in explicit:
            if not isinstance(item, dict):
                continue
            try:
                tid = int(item.get("todo_id") or 0)
            except (TypeError, ValueError):
                tid = 0
            decision = str(item.get("decision") or "").strip()
            if tid > 0 and decision in {"persist", "regret", "坚持", "反悔"}:
                explicit_map[tid] = (
                    "persist" if decision in {"persist", "坚持"} else "regret"
                )

    cancel_ids = _extract_issue_ids(extracted.get("cancels"))
    # 亦认 close_issues 对承诺的关闭为坚持
    cancel_ids |= _extract_issue_ids(extracted.get("close_issues"))
    revoke_dossiers = _extract_dossier_ids(extracted.get("cancels"))
    revoke_dossiers |= _extract_dossier_ids(
        extracted.get("revoke_decree_targets") or []
    )
    # dossier_executions failed 指向同一案卷也可作坚持（少见）
    for it in extracted.get("dossier_executions") or []:
        if not isinstance(it, dict):
            continue
        if str(it.get("outcome") or "") in {"failed", "cancelled", "revoked"}:
            try:
                revoke_dossiers.add(int(it.get("dossier_id")))
            except (TypeError, ValueError):
                pass

    advance_ids = _extract_issue_ids(extracted.get("issue_advances"))
    # economy 续拨：origin 命中
    fund_origins: set[str] = set()
    fund_issue_ids: set[int] = set()
    for it in extracted.get("economy_moves") or []:
        if not isinstance(it, dict):
            continue
        try:
            delta = int(it.get("delta") or 0)
        except (TypeError, ValueError):
            delta = 0
        # 加拨（负方向月供恢复用负 delta 入账，或正 delta 补入国库再拨——认 origin）
        oref = str(it.get("origin_ref") or "")
        if oref:
            fund_origins.add(oref)
        tid = str(it.get("target_id") or "")
        if tid.startswith("issue:"):
            try:
                fund_issue_ids.add(int(tid.split(":", 1)[1]))
            except (TypeError, ValueError):
                pass
        if delta < 0 or str(it.get("purpose") or "") in {"履行承诺", "续拨", "加拨"}:
            if oref.startswith("issue:"):
                try:
                    fund_issue_ids.add(int(oref.split(":", 1)[1]))
                except (TypeError, ValueError):
                    pass

    for todo in pending:
        tid = int(todo["id"])
        cid = int(todo["commitment_ref"])
        meta = decode_plea_meta(todo.get("origin_context"))
        target_did = int(meta.get("target_dossier_id") or 0)
        row = _issue_row(db, cid)
        origin = str(row["origin_ref"] if row is not None else "")

        decision = explicit_map.get(tid)
        if decision is None:
            # 坚持
            if cid in cancel_ids:
                decision = "persist"
            elif target_did > 0 and target_did in revoke_dossiers:
                decision = "persist"
            elif origin and parse_dossier_id(origin) in revoke_dossiers:
                decision = "persist"
            # 反悔
            elif cid in advance_ids or cid in fund_issue_ids:
                decision = "regret"
            elif origin and origin in fund_origins:
                decision = "regret"
            elif f"issue:{cid}" in fund_origins:
                decision = "regret"

        if decision == "persist":
            results.append(finalize_persist(db, state, todo, commit=False))
        elif decision == "regret":
            results.append(finalize_regret(db, state, todo, commit=False))
        # else 沉默：保留 pending

    if commit and results:
        db.conn.commit()
    return results
