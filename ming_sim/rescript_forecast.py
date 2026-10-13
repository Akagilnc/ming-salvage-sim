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
from ming_sim.decree_forecast import _owner_for, dossier_for_decree_ref
from ming_sim.error_pack import write_error_pack

# Same worker pool as the existing model legs, not a second scheduler.
_executor = audience_translation._executor


def _snapshot_session(session):
    """Reuse SQLite backup for isolated model reads, never concurrent live-DB access."""
    tmp = TemporaryDirectory(prefix="ming-rescript-forecast-")
    try:
        path = str(Path(tmp.name) / "snapshot.db")
        session.db.backup_to(path)
        db = GameDB(path, content=copy.deepcopy(session.content), llm_config=session.llm_config)
        return tmp, SimpleNamespace(db=db, state=copy.deepcopy(session.state),
                                    llm_config=session.llm_config, content=db.content)
    except BaseException:
        tmp.cleanup()
        raise


def _identity(kind, ref, row):
    # Compare the supplied choice, not its prose or just its label.
    choice = dict(row["choice"])
    clean_choice = {k: v for k, v in choice.items() if k != "decision_key" and v != ""}
    return kind, ref, json.dumps((row["decision_key"], clean_choice), ensure_ascii=False, sort_keys=True)


def take_forecast(session, kind, ref, row):
    """Wait for the selected candidate; a failed candidate is simply unforecasted."""
    owner = _owner_for(session.db)
    cache = getattr(owner, "_rescript_forecasts", {})
    key = (int(session.state.turn), *_identity(kind, ref, row))
    future = cache.get(key)
    try:
        if future is not None:
            return future.result()  # No timeout, cancellation, or second live call.
    except Exception:
        # The speculative leg recorded the failure; selection falls back to live execution.
        pass
    finally:
        for candidate in list(cache):
            if candidate[:3] == key[:3]:
                del cache[candidate]  # Running unselected calls finish without applying.
    return None


def _run_candidate(session, chain, kind, ref, row):
    if kind != "memorial" and session.llm_config is None:
        from ming_sim.exceptions import LLMUnavailable
        raise LLMUnavailable(
            "续推缺少模型配置",
            stage="world-segment-continue" if kind == "world" else "decree-forecast-continue",
        )
    if kind == "memorial":
        data = rescript_draft.parse_agent_json(rescript_draft.run_rescript_text(
            session, officers=rescript_draft.triage_officers(session.db), backlog=[],
            answer={"memorial": row, "decision_key": ref, "choice": row["choice"]},
        ), "rescript-answer")
        rescript_draft.prepare_memorial_answer(session, row, data)
        return data
    answers = [month_chain._answer_from_row(row)]
    if kind == "world":
        text = month_chain._run_world_continuation_text(session, chain, answers)
    else:
        decree_ref = month_chain._decree_ref_from_question_id(ref)
        text = month_chain._run_decree_continuation_text(
            session, dossier_for_decree_ref(session.db, decree_ref), answers,
        )
    month_chain._split_at_question(text)
    return text


def schedule_forecasts(session, chain, desk):
    """Freeze inputs at presentation; each task owns resources beyond session close."""
    owner = _owner_for(session.db)
    if owner is None or session.llm_config is None:
        return
    cache = getattr(owner, "_rescript_forecasts", None)
    if cache is None:
        cache = owner._rescript_forecasts = {}
    turn = int(session.state.turn)
    for stale in list(cache):
        if stale[0] != turn:
            del cache[stale]
    materials_tmp = None
    shared_world = None
    for row in desk:
        target = month_chain._rescript_target(session, chain, row)
        if target is None:
            continue
        kind, ref = target
        # Shared read-only materials are frozen once per source. The standard
        # TemporaryDirectory lifetime follows the closures that hold it.
        materials = {}
        for option in row["options"]:
            choice = {**option, "decision_key": row["decision_key"]}
            candidate = {**row, "choice": choice}
            key = (turn, *_identity(kind, ref, candidate))
            if key in cache:
                continue
            tmp = None
            frozen_db = None
            try:
                # Reuse SQLite's existing backup seam rather than inventing a parallel
                # material reader. Each call has its own DB, state and temp resources.
                tmp, frozen = _snapshot_session(session)
                frozen_db = frozen.db
                if not materials:
                    from ming_sim.materials import prepare_world_materials
                    from ming_sim.decree_forecast import forecast_snapshot
                    if materials_tmp is None:
                        materials_tmp = TemporaryDirectory(prefix="ming-rescript-materials-")
                    if kind == "decree":
                        decree_ref = month_chain._decree_ref_from_question_id(ref)
                        materials["_rescript_decree_snapshot"] = forecast_snapshot(
                            frozen, dossier_for_decree_ref(frozen_db, decree_ref), decree_ref=decree_ref,
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
                # Error packs identify the original save, while backing up frozen facts.
                frozen_db.path = session.db.path
                frozen_chain = copy.deepcopy(chain)

                def run(frozen=frozen, frozen_chain=frozen_chain, kind=kind, ref=ref,
                        candidate=candidate, tmp=tmp, materials_tmp=materials_tmp):
                    try:
                        return _run_candidate(frozen, frozen_chain, kind, ref, candidate)
                    except Exception as exc:
                        write_error_pack(frozen.db, frozen.state, exc=exc)
                        raise
                    finally:
                        frozen.db.conn.close()
                        tmp.cleanup()

                future = _executor.submit(run)
            except Exception as exc:
                write_error_pack(session.db, session.state, exc=exc)
                if frozen_db is not None:
                    frozen_db.conn.close()
                if tmp is not None:
                    tmp.cleanup()
                future = Future()
                future.set_exception(exc)
            cache[key] = future  # Retain independent finished legs if a sibling pauses recovery.
            future.add_done_callback(lambda done: audience_translation._observe_finished_future(
                done, where="rescript forecast"))


def _prepare_answer_translation(session, row, kind, ref, product):
    from ming_sim.month_translate import prepare_month_segment, _answered_levy_verdicts

    payload, verdicts, decree_ref = {}, [], None
    if kind == "memorial":
        _, text = rescript_draft.validate_answer_product(product)
        if (row["choice"] or {}).get("action") == "midzhi":
            return None  # The original midzhi admission owns this non-effect product.
    else:
        text, _ = month_chain._split_at_question(product)
        if kind == "decree":
            decree_ref = month_chain._decree_ref_from_question_id(ref)
            payload = dossier_for_decree_ref(session.db, decree_ref)["payload"]
        else:
            verdicts = _answered_levy_verdicts(
                session.db, int(session.state.turn), answers=[month_chain._answer_from_row(row)],
            )
    if not text.strip() and not verdicts:
        return None
    return prepare_month_segment(
        session.db, session.state, segment=text, decree_payload=payload,
        llm_config=session.llm_config, answered_verdicts=verdicts, decree_ref=decree_ref,
    )


def prepare_answers(session, chain, rows, *, source):
    """Claim each answer once; model legs run on the existing pool, commits stay short.

    A selected candidate launches translation only after completion: no pool worker
    waits for another worker in the same bounded pool. Other requests can claim new
    answers while these are in flight. Durable raw products remain the retry source.
    Caller holds the existing write gate during admission.
    """
    owner = _owner_for(session.db)
    active = getattr(owner, "_rescript_jobs", None)
    if active is None:
        active = owner._rescript_jobs = {}
    cache = getattr(owner, "_rescript_forecasts", {})
    turn = int(session.state.turn)
    rows = [row for row in rows if (turn, row["decision_key"]) not in active]
    jobs, launches = {}, []
    for row in rows:
        target = month_chain._rescript_target(session, chain, row)
        if target is None:
            continue
        kind, ref = target
        product_key = "rescript_answer_products" if kind == "memorial" else "rescript_continuation_texts"
        product = chain.get(product_key, {}).get(ref)
        result = Future()
        active[(turn, row["decision_key"])] = result
        jobs[result] = (row, kind, ref)
        try:
            tmp, frozen = _snapshot_session(session)
        except Exception as exc:
            result.set_exception(exc)
            continue
        frozen_chain = copy.deepcopy(chain)
        forecast = cache.get((turn, *_identity(kind, ref, row)))

        def work(row=row, kind=kind, ref=ref, product_key=product_key, product=product,
                 frozen=frozen, frozen_chain=frozen_chain, tmp=tmp):
            try:
                if product is None:
                    with owner._write_gate:
                        product = take_forecast(session, kind, ref, row)
                    if product is None:
                        product = _run_candidate(frozen, frozen_chain, kind, ref, row)
                    with owner._write_gate:
                        live = month_chain._load_chain(session.db, turn)
                        live.setdefault(product_key, {})[ref] = product
                        month_chain._save_chain(session.db, turn, live, source=source)
                return _prepare_answer_translation(frozen, row, kind, ref, product)
            finally:
                frozen.db.conn.close()
                tmp.cleanup()

        def launch(_done=None, work=work, result=result, frozen=frozen, tmp=tmp):
            try:
                worker = _executor.submit(work)
            except Exception as exc:
                frozen.db.conn.close()
                tmp.cleanup()
                result.set_exception(exc)
                return

            def complete(done):
                try:
                    result.set_result(done.result())
                except BaseException as exc:
                    result.set_exception(exc)
            worker.add_done_callback(complete)

        if forecast is not None and not forecast.done():
            launches.append(lambda forecast=forecast, launch=launch: forecast.add_done_callback(launch))
        else:
            launches.append(launch)
    return jobs, launches
