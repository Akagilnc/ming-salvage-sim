"""拒收段集成测的薄夹具。

#1846：不复刻已删的 driver 编排。仅：
- prepare_resolve_front_half（生产前半段 seam）
- settle_with_delta + 确定性 applier（生产后半段核，整删归 #1843）
- 默认 attendant runner / rejection_rows 查询
"""

from __future__ import annotations

import json

from ming_sim.applier import Provenance
from ming_sim.decree import prepare_resolve_front_half, settle_with_delta
from ming_sim.issues import apply_score_extraction
from ming_sim.models import LLMConfig
from ming_sim.simulation import canonicalize_extraction

from tests.conftest import game as game  # noqa: F401

_DETERMINISTIC_LLM = LLMConfig(api_key="", base_url="", model="", channel="api")
_UNSET = object()


def default_settlement_attendant_runner(*, year, period, rejections):
    del year, period
    return "递话" if rejections else ""


def install_settlement_attendant_agent_stub(
    monkeypatch, decree_mod, *, text="递话", capture=None,
):
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
            decree_mod, "create_settlement_attendant_agent", factory,
        )


def prepare_then_settle(db, state, content, raw_delta, **kwargs):
    """prepare_resolve_front_half → settle_with_delta（生产 seam，非平行旧入口）。"""
    prep_kw = {}
    if "registry" in kwargs:
        prep_kw["registry"] = kwargs["registry"]
    if "source" in kwargs:
        prep_kw["source"] = kwargs["source"]
    prepare_resolve_front_half(
        state, db, content=content,
        registry=prep_kw.get("registry"),
        source=prep_kw.get("source", Provenance.player_decree),
    )
    from tests.conftest import with_monthly_reports
    return _settle_after_prepare(
        db, state, content, with_monthly_reports(db, raw_delta), **kwargs,
    )


def _settle_after_prepare(db, state, content, raw_delta, **kwargs):
    if raw_delta is None:
        raw_delta = {}
    if not isinstance(raw_delta, dict):
        raise ValueError(f"delta 必须是 object(dict)，实得 {type(raw_delta).__name__}")
    before_turn = int(state.turn)
    extracted = canonicalize_extraction(raw_delta)
    attendant = kwargs.pop("settlement_attendant_runner", _UNSET)
    if attendant is _UNSET:
        attendant = default_settlement_attendant_runner
    source = kwargs.pop("source", Provenance.player_decree)
    registry = kwargs.pop("registry", None)
    narrative = kwargs.pop("narrative", "")
    decree_text = kwargs.pop("decree_text", "")
    if kwargs:
        raise TypeError(f"unexpected settle kwargs: {sorted(kwargs)}")
    return settle_with_delta(
        state, db, extracted,
        before_turn=before_turn,
        content=content,
        registry=registry,
        narrative=narrative,
        decree_text=decree_text,
        extractor_output=json.dumps(extracted, ensure_ascii=False),
        source=source,
        delta_applier=lambda d, s, ex, ct, rg: apply_score_extraction(
            d, s, ex, content=ct, registry=rg, llm_config=_DETERMINISTIC_LLM,
        ),
        settlement_attendant_runner=attendant,
    )


# 兼容旧 import 名：已 prepare 后的 settle
run_settle = _settle_after_prepare


def run_prepare(db, state, content, *, registry=None, source=Provenance.player_decree,
                decree_text: str = "") -> dict:
    """薄包装生产 prepare_resolve_front_half；返回 simulator_payload。"""
    prepare_resolve_front_half(
        state, db, decree_text=decree_text, content=content,
        registry=registry, source=source,
    )
    ctx = db.get_resolve_context(int(state.turn)) or {}
    return dict(ctx.get("simulator_payload") or {})


def rejection_rows(db, turn, section=None, *, columns="section, reason, category, source"):
    query = f"SELECT {columns} FROM rejection_reports WHERE turn=?"
    params: list = [turn]
    if section is not None:
        query += " AND section=?"
        params.append(section)
    return db.conn.execute(query + " ORDER BY id", params).fetchall()
