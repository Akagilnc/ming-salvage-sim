"""Perspective-fed memorials and rescript continuations on the existing month run."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from ming_sim.agents import parse_agent_json, run_agent_text
from ming_sim.exceptions import LLMContractError, LLMUnavailable


_TRIAGE_OFFICE_TITLES = frozenset({"内阁首辅", "司礼监掌印太监"})


def triage_officers(db) -> list[dict]:
    """Admit triage officers by exact office title identity — not free-text LIKE."""
    return [dict(row) for row in db.conn.execute(
        "SELECT * FROM characters WHERE status='active' AND power_id='ming' "
        "AND office IN ({placeholders}) ORDER BY name".format(
            placeholders=",".join("?" for _ in _TRIAGE_OFFICE_TITLES),
        ),
        tuple(sorted(_TRIAGE_OFFICE_TITLES)),
    )]


def run_rescript_text(session, *, officers: list, backlog: list, answer: dict | None = None) -> str:
    """External model seam. Reuse role materials and native API/CLI reading tools."""
    from ming_sim.agents import create_rescript_draft_agent
    from ming_sim.llm_transport import audience_transport_policy
    from ming_sim.materials import prepare_character_materials, prepare_world_materials, _character_projection_from_db_row

    if session.llm_config is None:
        raise LLMUnavailable("票拟缺少模型配置", stage="rescript-draft")
    with TemporaryDirectory(prefix="ming-rescript-") as tmp:
        perspectives = []
        for idx, row in enumerate(officers):
            officer = {"name": row["name"], "office": row["office"], "faction": row["faction"]}
            if answer is None:
                prepared = prepare_character_materials(
                    session.db, session.state, _character_projection_from_db_row(row),
                    dest_root=Path(tmp) / str(idx),
                )
                officer.update(materials=str(idx), opening=prepared.opening)
            perspectives.append(officer)
        world = None
        if answer is not None:
            prepared = prepare_world_materials(session.db, session.state, dest_root=Path(tmp) / "world")
            world = {"materials": "world", "opening": prepared.opening}
        agent = create_rescript_draft_agent(session.llm_config, SimpleNamespace(root=Path(tmp)))
        return run_agent_text(
            agent, json.dumps({
                "mode": "answer" if answer is not None else "triage",
                "officers": perspectives, "backlog": backlog, "answer": answer, "world": world,
            }, ensure_ascii=False), tag="rescript-answer" if answer is not None else "rescript-draft",
            transport_policy=audience_transport_policy(),
        )


def _memorial(item: dict, actor: dict) -> dict:
    if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ("title", "context")):
        raise LLMContractError("票拟须提供奏折标题及全文")
    options = item.get("options")
    if not isinstance(options, list) or any(
        not isinstance(o, dict) or not isinstance(o.get("label"), str)
        or not isinstance(o.get("hint", ""), str) for o in options
    ):
        raise LLMContractError("票拟 options 须为拟批与说明的列表")
    return {**item, "actor_name": actor["name"], "actor_office": actor["office"],
            "actor_faction": actor["faction"] or ""}


def produce_memorials(session, chain: dict, *, source) -> None:
    from ming_sim.month_chain import _save_chain
    from ming_sim.applier import atomic

    if chain.get("rescript_drafted"):
        return
    db, state = session.db, session.state
    officers = triage_officers(db)
    backlog = [row for row in db.list_rescript_drafts(status="revision_pending")
               if int(row["answered_turn"]) < int(state.turn)]
    if officers:
        data = parse_agent_json(run_rescript_text(session, officers=officers, backlog=backlog), "rescript-draft")
        actor = next((r for r in officers if r["name"] == data.get("actor_name")), None)
        if actor is None or not isinstance(data.get("items"), list) or not isinstance(data.get("revisions"), list):
            raise LLMContractError("票拟须具名在职分拣人并交 items/revisions")
        items = [_memorial(item, actor) for item in data["items"]]
        originals = {f"rescript_draft:{r['turn']}:{r['idx']}": r for r in backlog}
        revisions = [_memorial(item, actor) for item in data["revisions"]]
        keys = [item.get("decision_key") for item in revisions]
        if any(not isinstance(key, str) for key in keys) or len(keys) != len(set(keys)) or set(keys) != set(originals):
            raise LLMContractError("改票须逐一回指待改原案，不增删原案身份")
    else:
        items, revisions, originals = [], [], {}
    with atomic(db):
        db.append_rescript_drafts(int(state.turn), items, revisions=[
            {**item, "turn": originals[item["decision_key"]]["turn"],
             "idx": originals[item["decision_key"]]["idx"]} for item in revisions
        ])
        chain["rescript_drafted"] = True
        _save_chain(db, int(state.turn), chain, source=source)


def consume_memorial_answers(session, chain: dict, *, source) -> None:
    from ming_sim.month_chain import _save_chain, _ending_from_dispatch_result, _collect_disclosures_from_result
    from ming_sim.month_translate import dispatch_month_segment
    from ming_sim.applier import atomic

    db, state = session.db, session.state
    consumed = chain.setdefault("rescript_consumed", [])
    products = chain.setdefault("rescript_answer_products", {})
    for row in sorted(db.list_rescript_drafts(), key=lambda r: (r["answered_turn"], r["answer_order"])):
        key = f"rescript_draft:{row['turn']}:{row['idx']}"
        if row["status"] != "decided" or row["answered_turn"] != int(state.turn) or key in consumed:
            continue
        answer = {"memorial": row, "decision_key": key, "choice": row["choice"]}
        officers = triage_officers(db)
        # A returned original remains answerable even if both offices became vacant.
        data = products.get(key)
        if data is None:
            data = parse_agent_json(run_rescript_text(session, officers=officers, backlog=[], answer=answer), "rescript-answer")
        disposition = data.get("disposition")
        text = data.get("text")
        if disposition not in {"settled", "revise"} or not isinstance(text, str):
            raise LLMContractError("批语续推须交 disposition 与原文 text")
        midzhi = (row["choice"] or {}).get("action") == "midzhi"
        decree = data.get("decree")
        if midzhi and (disposition != "settled" or not isinstance(decree, dict)
                       or not isinstance(decree.get("text"), str) or not isinstance(decree.get("payload"), dict)
                       or not all(isinstance(decree["payload"].get(k), str) for k in ("dossier_action_type", "target_kind", "target_id"))
                       or text.strip()):
            raise LLMContractError("另旨·中旨须交旨文与载荷，不先写办理效果")
        payload = None
        if midzhi:
            payload = db._normalize_directive_dossier_payload(
                {**decree["payload"], "mode": "midzhi", "decision_key": key,
                 "text": decree["text"]},
                content=session.content, current_turn=int(state.turn),
            )
            action_type = db._directive_dossier_action_type(payload)
            executor_kind, executor_id = db._directive_executor(action_type, payload)
        if key not in products:
            products[key] = data
            _save_chain(db, int(state.turn), chain, source=source)

        def consume(result=None):
            if midzhi:
                ids = db.create_decree_dossiers(
                    state, action_type=action_type,
                    decree_text=decree["text"], target_kind=payload["target_kind"],
                    target_id=payload["target_id"], payload=payload, status="proposed",
                    executor_kind=executor_kind, executor_id=executor_id,
                    due_turn=int(payload.get("due_turn") or 0),
                    participants=payload.get("participant_roster"), commit=False,
                )
                for did in ids:
                    db.add_dossier_endorsement(
                        did, form="御笔手敕", endorser_id="", imperial=True,
                        decision_key=key, source_chat_turn_id=0, commit=False,
                    )
            if disposition == "revise":
                db.conn.execute(
                    "UPDATE pending_decisions SET status='revision_pending' WHERE turn=? AND idx=?",
                    (row["turn"], row["idx"]),
                )
            outcome = _ending_from_dispatch_result(result)
            if outcome is not None:
                chain["declaration_outcome"] = outcome
            _collect_disclosures_from_result(chain, result)
            consumed.append(key)
            products.pop(key)
            _save_chain(db, int(state.turn), chain, source=source)

        if text.strip() and not midzhi:
            dispatch_month_segment(db, state, segment=text, llm_config=session.llm_config,
                                   source=source, alongside=consume)
        else:
            with atomic(db):
                consume()
