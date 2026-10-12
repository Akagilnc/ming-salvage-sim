"""Speculate rescript continuations without touching the live ledger (#1847)."""
from __future__ import annotations

import copy
import json
from concurrent.futures import Future
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from ming_sim import audience_translation, month_chain, rescript_draft
from ming_sim.db import GameDB
from ming_sim.decree_forecast import _owner_for
from ming_sim.error_pack import write_error_pack
from ming_sim.rescript_actions import persist_answers

# Same worker pool as the existing model legs, not a second scheduler.
_executor = audience_translation._executor


def _identity(kind, ref, rows):
    # Compare the supplied choice, not its prose or just its label.
    choices = []
    for row in rows:
        choice = dict(row["choice"])
        choices.append((row["decision_key"], {k: v for k, v in choice.items()
                                            if k != "decision_key" and v != ""}))
    return kind, ref, json.dumps(choices, ensure_ascii=False, sort_keys=True)


def take_forecast(session, kind, ref, rows, *, selected=None):
    """Wait for the selected candidate; a failed candidate is simply unforecasted."""
    owner = _owner_for(session.db)
    cache = getattr(owner, "_rescript_forecasts", {})
    key = (int(session.state.turn), *_identity(kind, ref, rows))
    future, speculative = selected if selected is not None else (cache.get(key), True)
    try:
        if future is not None:
            return future.result()  # No timeout, cancellation, or second live call.
    except Exception:
        if not speculative:
            raise  # A live continuation is governed by the month-call recovery boundary.
        # The speculative leg already wrote the original exception to an error pack.
        # The selected live call belongs to the existing month-call recovery boundary.
        pass
    finally:
        for candidate in list(cache):
            if candidate[:3] == key[:3]:
                del cache[candidate]  # Running unselected calls finish without applying.
    return None


def _run_candidate(session, chain, kind, ref, rows):
    if kind == "memorial":
        row = rows[0]
        data = rescript_draft.parse_agent_json(rescript_draft.run_rescript_text(
            session, officers=rescript_draft.triage_officers(session.db), backlog=[],
            answer={"memorial": row, "decision_key": ref, "choice": row["choice"]},
        ), "rescript-answer")
        rescript_draft.validate_answer_product(data)
        return data
    answers = [month_chain._answer_from_row(row) for row in rows]
    if kind == "world":
        text = month_chain._run_world_continuation_text(session, chain, answers)
    else:
        text = month_chain._run_decree_continuation_text(
            session, month_chain._dossier_for_decree_ref(
                session.db, ref[len(month_chain._DECREE_QUESTION_PREFIX):].rpartition(":")[0],
            ), answers,
        )
    month_chain._split_at_question(text)
    return text


def schedule_forecasts(session, chain, desk, *, selected=False):
    """Freeze inputs at presentation; each task owns resources beyond session close."""
    owner = _owner_for(session.db)
    if owner is None or session.llm_config is None:
        return {}
    cache = getattr(owner, "_rescript_forecasts", None)
    if cache is None:
        cache = owner._rescript_forecasts = {}
    turn = int(session.state.turn)
    for stale in list(cache):
        if stale[0] != turn:
            del cache[stale]
    groups = {}
    results = {}
    world_ids = month_chain._world_question_ids(chain, turn)
    for row in desk:
        event = str(row.get("event_id") or "")
        if event.startswith(month_chain._DECREE_QUESTION_PREFIX):
            ref = event[len(month_chain._DECREE_QUESTION_PREFIX):].rpartition(":")[0]
            if any(q.get("event_id") == event for q in session.db.staged_declarations.questions_for(ref)):
                groups[("decree", event)] = [row]
        elif event in world_ids:
            groups[("world", event)] = [row]
        elif not selected and row["kind"] == "rescript_draft":
            groups[("memorial", row["decision_key"])] = [row]
    materials_tmp = None
    shared_world = None
    for (kind, ref), rows in groups.items():
        if selected and ref in chain.get("rescript_continuation_texts", {}):
            continue  # Translation recovery already has the complete model product.
        row = rows[0]
        # Shared read-only materials are frozen once per source. The standard
        # TemporaryDirectory lifetime follows the closures that hold it.
        materials = {}
        for option in ([row["choice"]] if selected else row["options"]):
            choice = {**option, "decision_key": row["decision_key"]}
            candidates = [{**row, "choice": choice}]
            key = (turn, *_identity(kind, ref, candidates))
            if key in cache:
                future = cache[key]
                if not selected:
                    continue
                if not future.done() or future.exception() is None:
                    results[ref] = (future, True)
                    continue
            tmp = TemporaryDirectory(prefix="ming-rescript-forecast-")
            frozen_db = None
            try:
                # Reuse SQLite's existing backup seam rather than inventing a parallel
                # material reader. Each call has its own DB, state and temp resources.
                path = str(Path(tmp.name) / "snapshot.db")
                session.db.backup_to(path)
                frozen_db = GameDB(path, content=copy.deepcopy(session.content), llm_config=session.llm_config)
                frozen = SimpleNamespace(db=frozen_db, state=copy.deepcopy(session.state),
                                         llm_config=session.llm_config, content=frozen_db.content)
                if not materials:
                    from ming_sim.materials import prepare_world_materials
                    from ming_sim.decree_forecast import forecast_snapshot
                    if materials_tmp is None:
                        materials_tmp = TemporaryDirectory(prefix="ming-rescript-materials-")
                    if kind == "decree":
                        decree_ref = ref[len(month_chain._DECREE_QUESTION_PREFIX):].rpartition(":")[0]
                        materials["_rescript_decree_snapshot"] = forecast_snapshot(
                            frozen, month_chain._dossier_for_decree_ref(frozen_db, decree_ref), decree_ref=decree_ref,
                            materials_root=Path(materials_tmp.name) / "world",
                        )
                    else:
                        if shared_world is None:
                            shared_world = prepare_world_materials(
                                frozen_db, frozen.state, dest_root=Path(materials_tmp.name) / "world",
                            )
                        materials["_rescript_world_materials"] = shared_world
                    if kind == "memorial":
                        materials["_rescript_materials_root"] = materials_tmp.name
                frozen.__dict__.update(materials)
                persist_answers(frozen_db, frozen.state, [choice])
                frozen_rows = frozen_db.issues.get_rescript_desk_rows_by_keys(
                    [r["decision_key"] for r in candidates])
                # Error packs identify the original save, while backing up frozen facts.
                frozen_db.path = session.db.path
                frozen_chain = copy.deepcopy(chain)

                def run(frozen=frozen, frozen_chain=frozen_chain, kind=kind, ref=ref,
                        frozen_rows=frozen_rows, tmp=tmp, materials_tmp=materials_tmp):
                    try:
                        return _run_candidate(frozen, frozen_chain, kind, ref, frozen_rows)
                    except Exception as exc:
                        write_error_pack(frozen.db, frozen.state, exc=exc)
                        raise
                    finally:
                        frozen.db.close()
                        tmp.cleanup()

                future = _executor.submit(run)
            except Exception as exc:
                write_error_pack(session.db, session.state, exc=exc)
                if frozen_db is not None:
                    frozen_db.close()
                tmp.cleanup()
                future = Future()
                future.set_exception(exc)
            if selected:
                results[ref] = (future, False)
            cache[key] = future  # Retain independent finished legs if a sibling pauses recovery.
            future.add_done_callback(lambda done: audience_translation._observe_finished_future(
                done, where="rescript forecast"))
    return results
