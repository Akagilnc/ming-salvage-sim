"""#651 暗渠摊派：结构化候选、两轨落账、揭破待裁与普通下旨消费。

本模块不从任何叙事文本猜案卷、军队、通道或处置。所有关联均来自既有外键/结构化
origin_ref；真实效果仍由 settlement 的 canonical applier 落账。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping

ENTRY_KIND = "covert_levy_exposure"
DECISIONS = frozenset({"禁摊派", "默许", "查办"})


def _issue_for_dossier(db: Any, dossier_id: int) -> int:
    row = db.conn.execute(
        "SELECT id FROM issues WHERE origin_ref=? ORDER BY id LIMIT 1",
        (f"dossier:{int(dossier_id)}",),
    ).fetchone()
    return int(row["id"]) if row is not None else 0


def build_covert_levy_candidates(db: Any) -> List[Dict[str, object]]:
    """装配案卷所指军队的欠饷事实；是否形成摊派完全交给判官。"""
    rows = db.conn.execute(
        """SELECT d.id dossier_id,d.target_id army_id,a.arrears,
                  a.consecutive_pay_shortfall_months
           FROM decree_dossiers d JOIN armies a ON a.id=d.target_id
           WHERE d.status='executing' AND d.target_kind='army' ORDER BY d.id"""
    ).fetchall()
    out: List[Dict[str, object]] = []
    for row in rows:
        did = int(row["dossier_id"])
        if _issue_for_dossier(db, did) <= 0:
            continue
        out.append({
            "dossier_id": did,
            "army_id": str(row["army_id"]),
            "arrears": float(row["arrears"] or 0),
            "consecutive_pay_shortfall_months": int(
                row["consecutive_pay_shortfall_months"] or 0
            ),
        })
    return out


def _pending_exposure(db: Any, dossier_id: int) -> Dict[str, object] | None:
    for todo in db.list_next_audience_todos(status="pending"):
        if todo.get("entry_kind") == ENTRY_KIND and int(todo["payload_json"].get("dossier_id") or 0) == dossier_id:
            return todo
    return None


def apply_structured_decisions(db: Any, state: Any, extracted: Dict[str, object]) -> None:
    """消费普通下旨的结构化三选。错案、无 pending、重复消费均响亮失败。"""
    for item in extracted.get("covert_levy_decisions") or []:
        if not isinstance(item, Mapping) or type(item.get("dossier_id")) is not int:
            raise ValueError("暗渠处置须携带结构化 dossier_id")
        did = int(item["dossier_id"])
        decision = str(item.get("decision") or "")
        if decision not in DECISIONS:
            raise ValueError("暗渠处置须为禁摊派/默许/查办")
        todo = _pending_exposure(db, did)
        if todo is None:
            raise ValueError(f"案卷 {did} 无待裁暗渠揭破")
        patch: Dict[str, object] = {"decision": decision, "decided_turn": int(state.turn)}
        if decision == "查办":
            person = str(item.get("person_name") or "").strip()
            if not person:
                raise ValueError("查办须携带结构化 person_name")
            patch["person_name"] = person
            # 代价走既有人物评定入口，不在此直写人物。
            extracted.setdefault("人物变更", []).append({
                "name": person, "动作": "评定", "loyalty": -5,
                "reason": "暗渠摊派查办", "origin_ref": f"dossier:{did}",
            })
        db.mark_next_audience_todo_status(int(todo["id"]), "consumed", payload_patch=patch, commit=False)


def materialize_structured_verdicts(db: Any, state: Any, extracted: Dict[str, object]) -> None:
    """判官显式 verdict 才物化；代码只验证候选，不代判。奏报与实况严格分轨。"""
    candidates = {int(c["dossier_id"]): c for c in build_covert_levy_candidates(db)}
    for item in extracted.get("covert_levy_verdicts") or []:
        if not isinstance(item, Mapping) or type(item.get("dossier_id")) is not int:
            raise ValueError("暗渠判定须携带结构化 dossier_id")
        did = int(item["dossier_id"])
        if did not in candidates:
            raise ValueError(f"案卷 {did} 不在暗渠候选集")
        # 已被禁者不再物化；这个事实直接来自持久 todo payload，restore 后仍成立。
        blocked = any(t.get("entry_kind") == ENTRY_KIND and
                      int(t["payload_json"].get("dossier_id") or 0) == did and
                      t["payload_json"].get("decision") == "禁摊派"
                      for t in db.list_next_audience_todos(status="consumed"))
        if blocked:
            continue
        if item.get("formed") is not True:
            continue
        report = item.get("report")
        transfer = item.get("population_transfer")
        economy = item.get("economy_move")
        if not isinstance(report, Mapping) or not isinstance(transfer, Mapping) or not isinstance(economy, Mapping):
            raise ValueError("形成暗渠须同时给出奏报、人口转移和财政实况")
        db.record_dossier_progress(did, int(state.turn), str(report.get("progress_band") or "在办"),
                                   str(report.get("memorial_text") or ""), commit=False)
        origin = f"dossier:{did}"
        tr = dict(transfer); tr.update({"reason": "摊派", "origin_ref": origin})
        eco = dict(economy); eco.update({"origin_ref": origin, "beyond_intent": True})
        extracted.setdefault("population_transfers", []).append(tr)
        extracted.setdefault("economy_moves", []).append(eco)


def write_exposure_todos(db: Any, state: Any) -> int:
    """聚合稽核、检举、民变三路真实信号；fork 不成立或无信号绝不揭破。"""
    written = 0
    for row in db.conn.execute("SELECT id FROM decree_dossiers ORDER BY id").fetchall():
        did = int(row["id"])
        fork = db.read_dossier_fork_state(did)
        if not fork["fork"]:
            continue
        channels: List[str] = []
        audit = db.conn.execute(
            "SELECT 1 FROM decree_dossier_links WHERE target_dossier_id=? AND relation_type='稽核' LIMIT 1", (did,)
        ).fetchone()
        if audit is not None: channels.append("稽核")
        den = db.conn.execute("SELECT 1 FROM faction_denunciations WHERE target_dossier_id=? LIMIT 1", (did,)).fetchone()
        if den is not None: channels.append("检举")
        if not channels:
            continue
        issue_id = _issue_for_dossier(db, did)
        if issue_id <= 0:
            continue
        created = db.insert_next_audience_todo(
            commitment_ref=issue_id, stage_idx=did, due_turn=int(state.turn),
            criterion_text="暗渠摊派揭破待裁", origin_context="案卷实况与奏报有异",
            entry_kind=ENTRY_KIND, created_turn=int(state.turn),
            payload_json={"dossier_id": did, "channels": channels, "fork": fork}, commit=False)
        written += int(bool(created))
    return written
