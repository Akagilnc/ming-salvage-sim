"""Shared setup seam for rejection-section integration tests.

#1846：原 driver.prepare/settle 仅服务探针与旧 ready 路径；driver 已删。
测试夹具直接走 prepare_resolve_front_half + settle_with_delta（无 ready 重放）。
"""

from __future__ import annotations

import json

from ming_sim.applier import Provenance, RejectedItem, RejectionCollector, atomic
from ming_sim.decree import (
    _open_affair_ids_from_payload,
    _next_attempt,
    mirror_rejections_after_commit,
    prepare_resolve_front_half,
    rejections_jsonl_path,
    secret_dossier_ids_from_secret_orders,
    settle_with_delta,
)
from ming_sim.issues import (
    apply_score_extraction,
    sanitize_delta_shape,
    validate_delta_shape,
)
from ming_sim.models import LLMConfig, TurnPhase
from ming_sim.settlement_payload import (
    _select_secret_orders_for_sim,
    augment_secret_orders_with_due_commitments,
    group_secret_orders_for_sim,
)
from ming_sim.simulation import canonicalize_extraction

# game：conftest 已改为方案 (c) session 模板 + 每案文件拷贝（#1233）。
from tests.conftest import game as game  # noqa: F401

_DETERMINISTIC_LLM = LLMConfig(api_key="", base_url="", model="", channel="api")


def default_settlement_attendant_runner(*, year, period, rejections):
    """#1745：settle 注入边界；真实非空文本，不锁措辞、非生产零宽。"""
    del year, period
    return "递话" if rejections else ""


def install_settlement_attendant_agent_stub(
    monkeypatch, decree_mod, *, text="递话", capture=None,
):
    """#1745：替身下移到真实 runner 的 agent 边界。"""
    class _Out:
        content = text

    class _Agent:
        def run(self, prompt):
            if capture is not None:
                payload = json.loads(prompt)
                capture.append(list(payload.get("rejections") or []))
            return _Out()

    factory = lambda *_a, **_k: _Agent()  # noqa: E731
    if monkeypatch is None:
        setattr(decree_mod, "create_settlement_attendant_agent", factory)
    else:
        monkeypatch.setattr(
            decree_mod,
            "create_settlement_attendant_agent",
            factory,
        )


def run_prepare(db, state, content, *, registry=None, source: Provenance = Provenance.player_decree,
                decree_text: str = "") -> dict:
    """测试夹具：共享 prepare seam → settling + 本月 context。"""
    prepare_resolve_front_half(
        state, db,
        decree_text=decree_text,
        content=content,
        registry=registry,
        source=source,
    )
    ctx = db.get_resolve_context(int(state.turn)) or {}
    return dict(ctx.get("simulator_payload") or {})


def _require_prepared_context(db, state):
    if state.turn_phase != TurnPhase.SETTLING.value:
        raise ValueError(
            "须先 prepare（仅 settling 可 settle；"
            f"当前相位={state.turn_phase!r}）。"
        )
    ctx = db.get_resolve_context(int(state.turn))
    if ctx is None:
        raise ValueError("须先 prepare（本回合无 pending_resolve_context）。")
    return ctx


def _merge_settle_simulator_payload(ctx, *, dossier_ids_at_input) -> dict:
    prev = ctx.get("simulator_payload") if isinstance(ctx, dict) else None
    payload: dict = {
        "decree_dossiers": [
            {"id": dossier_id} for dossier_id in sorted(dossier_ids_at_input)
        ],
        "open_affairs": (
            [dict(row) for row in prev.get("open_affairs", [])]
            if isinstance(prev, dict) and isinstance(prev.get("open_affairs"), list)
            else []
        ),
    }
    if isinstance(prev, dict) and "transit_arrivals" in prev:
        arrivals = prev.get("transit_arrivals")
        payload["transit_arrivals"] = list(arrivals) if isinstance(arrivals, list) else []
    else:
        payload["transit_arrivals"] = []
    return payload


_UNSET = object()


def run_settle(db, state, content, raw_delta, *, narrative="", decree_text="", registry=None,
               source: Provenance = Provenance.player_decree,
               settlement_attendant_runner=_UNSET) -> str:
    """测试夹具：已 prepare 后的确定性 settle（无 ready 重放）。"""
    if raw_delta is None:
        raw_delta = {}
    if not isinstance(raw_delta, dict):
        raise ValueError(f"delta 必须是 object(dict)，实得 {type(raw_delta).__name__}")

    before_turn = state.turn
    ctx = _require_prepared_context(db, state)

    extracted = canonicalize_extraction(raw_delta)
    validate_delta_shape(extracted)
    dossier_ids_at_input = {
        int(row["id"]) for row in db.list_decree_dossiers_for_simulation(before_turn)
    }
    secret_orders_for_sim = group_secret_orders_for_sim(
        _select_secret_orders_for_sim(db)
    )
    secret_orders_for_sim = augment_secret_orders_with_due_commitments(
        secret_orders_for_sim, db, state,
    )
    secret_dossier_ids_at_input = secret_dossier_ids_from_secret_orders(
        db, secret_orders_for_sim,
    )
    simulator_payload = _merge_settle_simulator_payload(
        ctx,
        dossier_ids_at_input=dossier_ids_at_input,
    )
    open_affair_ids_at_input = _open_affair_ids_from_payload(simulator_payload)

    cleaned, rejections = sanitize_delta_shape(extracted)
    validate_delta_shape(cleaned)
    try:
        attempt = _next_attempt(before_turn)
    except Exception:
        attempt = 1
    collector = RejectionCollector(attempt=attempt)
    with atomic(db):
        for section, item, reason in rejections:
            collector.record(
                section,
                RejectedItem(
                    item=item,
                    reason=reason,
                    category="invalid_shape",
                    source=Provenance(source),
                ),
                before_turn,
            )
        collector.flush_to_db(db)
        db.save_resolve_context(
            before_turn, decree_text, narrative, simulator_payload,
            secret_orders=secret_orders_for_sim, relevant_memories=[],
            source=Provenance(source).value,
        )
    mirror_rejections_after_commit(db, collector, rejections_jsonl_path)
    extracted = cleaned

    if settlement_attendant_runner is _UNSET:
        settlement_attendant_runner = default_settlement_attendant_runner

    return settle_with_delta(
        state,
        db,
        extracted,
        before_turn=before_turn,
        content=content,
        registry=registry,
        narrative=narrative,
        decree_text=decree_text,
        extractor_output=json.dumps(extracted, ensure_ascii=False),
        source=source,
        delta_applier=lambda d, s, ex, ct, rg: apply_score_extraction(
            d, s, ex, content=ct, registry=rg, llm_config=_DETERMINISTIC_LLM,
            dossier_ids_at_input=dossier_ids_at_input,
            secret_dossier_ids_at_input=secret_dossier_ids_at_input,
            open_affair_ids_at_input=open_affair_ids_at_input,
        ),
        settlement_attendant_runner=settlement_attendant_runner,
    )


def prepare_then_settle(db, state, content, raw_delta, **kwargs):
    """Test glue: prepare → settle（非生产一站式轨）。"""
    prep_kw = {}
    if "registry" in kwargs:
        prep_kw["registry"] = kwargs["registry"]
    if "source" in kwargs:
        prep_kw["source"] = kwargs["source"]
    run_prepare(db, state, content, **prep_kw)
    from tests.conftest import with_monthly_reports
    settle_kw = dict(kwargs)
    settle_kw.setdefault(
        "settlement_attendant_runner", default_settlement_attendant_runner,
    )
    return run_settle(
        db, state, content, with_monthly_reports(db, raw_delta), **settle_kw,
    )


def rejection_rows(db, turn, section=None, *, columns="section, reason, category, source"):
    sql = f"SELECT {columns} FROM rejection_reports WHERE turn=?"
    args: list = [int(turn)]
    if section is not None:
        sql += " AND section=?"
        args.append(section)
    sql += " ORDER BY id"
    return list(db.conn.execute(sql, args).fetchall())
