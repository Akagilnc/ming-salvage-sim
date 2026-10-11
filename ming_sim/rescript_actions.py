"""Persist emperor answers; effects belong to the month-chain continuation."""
from __future__ import annotations
from ming_sim.applier import StoredDocumentError, load_stored_object

import json
from typing import Any

from ming_sim.decree import atomic_and_reload


def canonical_choice(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("批语须为对象")
    choice = dict(raw)
    key = choice.get("decision_key")
    if not isinstance(key, str) or not key:
        raise ValueError("批语缺 decision_key")
    for field in ("label", "hint", "note", "action", "dossier_decision"):
        if field in choice and not isinstance(choice[field], str):
            raise ValueError(f"批语 {field} 须为字符串")
    return choice


def persist_answers(db: Any, state: Any, choices: list, *, content: Any = None) -> None:
    """Validate the entire envelope before writing. Same-body retries are idempotent."""
    requests = [canonical_choice(raw) for raw in choices]
    keys = [item["decision_key"] for item in requests]
    if len(set(keys)) != len(keys):
        raise ValueError("重复 decision_key")
    rows = {r["decision_key"]: r for r in db.issues.get_rescript_desk_rows_by_keys(keys)}
    open_keys = {r["decision_key"] for r in db.issues.list_rescript_desk(int(state.turn))}
    for choice in requests:
        row = rows.get(choice["decision_key"])
        if row is None:
            raise ValueError("decision_key 不在案头")
        if row["choice"]:
            if row["choice"] != choice:
                raise ValueError("已落批语不可改写")
            continue
        if choice["decision_key"] not in open_keys:
            raise ValueError("原案当前不可批")
        event_id = str(row.get("event_id") or "")
        action = choice.get("dossier_decision") or choice.get("action") or ""
        if event_id.startswith("dossier:"):
            legal = {o.get("dossier_decision") for o in row["options"]}
            if action not in legal:
                raise ValueError("打回旨须显式选择合法强颁、收回或留中")
        elif event_id.startswith("deliberation:"):
            if action not in {o.get("action") for o in row["options"]}:
                raise ValueError("无人站台案须显式选择御笔强推或留存")
        else:
            if action not in ({"", "midzhi"} if row["kind"] == "rescript_draft" else {""}):
                raise ValueError("批语不使用旧六动作；另旨·中旨只接急务原案")
            if not (choice.get("label", "").strip() or choice.get("note", "").strip()):
                raise ValueError("批语为空")
            if choice.get("label") and choice["label"] not in {o.get("label") for o in row["options"]}:
                raise ValueError("所选票拟不在原奏折中")
    with atomic_and_reload(db, state, content=content):
        for choice in requests:
            row = rows[choice["decision_key"]]
            if row["choice"]:
                continue
            db.issues.record_rescript_answer(
                json.dumps(choice, ensure_ascii=False), int(state.turn),
                row["source_turn"], row["idx"], row["kind"],
            )
            event_id = str(row.get("event_id") or "")
            from ming_sim.month_chain import _DECREE_QUESTION_PREFIX, _WORLD_QUESTION_PREFIX, _LEVY_PETITION_PREFIX
            if row["kind"] == "decision" and event_id.startswith(_LEVY_PETITION_PREFIX):
                db.record_event_petition_answer(
                    state, event_id[len(_LEVY_PETITION_PREFIX):], choice,
                    {"title": row["title"], "context": row["context"],
                     "options": [opt["label"] for opt in row["options"]]},
                    commit=False,
                )
                continue
            if row["kind"] == "decision" and event_id and not event_id.startswith(
                ("dossier:", "deliberation:", _DECREE_QUESTION_PREFIX, _WORLD_QUESTION_PREFIX)
            ):
                db.record_event_decision_choice(state, event_id, choice, commit=False)


def apply_imperial_deliberation_push(
    db: Any, state: Any, *, target_dossier_id: int, decision_key: str, decree_text: str = "",
) -> int:
    """Reuse the stalled dossier and retain imperial decision-key provenance."""
    did = int(target_dossier_id)
    row = db.dossiers.get(did)
    if not decision_key or row is None or row["status"] != "proposed":
        raise ValueError("御笔强推要求原 proposed 案卷与 decision_key")
    payload = dict(row["payload"])
    if payload.get("deliberation_state") != "stalled":
        raise ValueError("御笔强推只接无人站台原案")
    origin = f"dossier:{did}"
    issue = db.issues.read_apply_imperial_deliberation_push((origin,))
    if issue is None:
        raise ValueError("无人站台原案缺局势记录")
    payload["deliberation_state"] = "backed"
    payload["imperial_push_note"] = decree_text
    db.dossiers.update_payload(did, payload, commit=False)
    db.dossiers.add_endorsement(
        did, form="御笔手敕", endorser_id="", imperial=True,
        decision_key=decision_key, source_chat_turn_id=0, commit=False,
    )
    db.close_issue(state, int(issue["id"]), reason="resolved", narrative=decree_text, commit=False)
    return did
