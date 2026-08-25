"""Shared light GameSession + canned monthly LLM seams (no external model).

Used by full-settlement tracers (#1274 no-edict, #652 judge chain, …).
Only replaces outer LLM factories/calls; production spine stays real.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import ming_sim.decree as decree_mod
import ming_sim.memories as memories
from ming_sim.session import GameSession


def make_light_session(db, state, content):
    """Minimal GameSession shell for advance_without_decree tracers."""
    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.content = content
    session.registry = None
    session.llm_config = None
    session.agno_db = None
    session.deaths_this_turn = []
    session.debuts_this_turn = []
    session.last_decree = ""
    session.last_report = ""
    session._decree_draft_fingerprint = ()
    session._scene_registry = None
    session._beat_generator = None
    session.auto_save = lambda *a, **k: None
    return session


def canned_full_settlement(
    monkeypatch,
    *,
    narrative: str = "本月边情邸报：辽饷催征，流寇未息。",
    decisions: Optional[List[Dict[str, object]]] = None,
    simulator_calls: Optional[list] = None,
    source_spy: Optional[list] = None,
    extract_result: Optional[Dict[str, object]] = None,
    extract_calls: Optional[list] = None,
    modules_seen: Optional[list] = None,
    skip_fixed_flows: bool = False,
    skip_relation_brew: bool = False,
    narrative_fn: Optional[Callable[..., str]] = None,
    extract_fn: Optional[Callable[..., Dict[str, object]]] = None,
) -> list:
    """Replace only external LLM seams; keep production settlement spine.

    extract_result: canned merged extractor payload (English keys).
    narrative_fn(payload, **ctx) → optional dynamic narrative from payload.
    extract_fn(narrative, payload, **ctx) → optional dynamic extract from the
    simulator product (preferred over static extract_result when both given).
    """
    simulator_calls = simulator_calls if simulator_calls is not None else []
    decisions = list(decisions or [])
    canned_extract = dict(extract_result or {})
    last_sim: Dict[str, Any] = {"narrative": narrative, "payload": {}}

    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)

    def _sim(*a, **k):
        payload = k.get("simulator_payload") or (a[10] if len(a) > 10 else None) or {}
        simulator_calls.append({
            "decree_text": a[3] if len(a) > 3 else k.get("decree_text", ""),
            "payload": payload,
        })
        if narrative_fn is not None:
            text = narrative_fn(payload, args=a, kwargs=k)
        else:
            text = narrative
        if decisions:
            blocks = []
            for i, d in enumerate(decisions):
                title = d.get("title") or f"决策{i}"
                opts = d.get("options") or ["准", "不准"]
                opt_lines = "\n".join(f"- {o}" for o in opts)
                blocks.append(
                    f"<<DECISION title=\"{title}\">>\n{opt_lines}\n<</DECISION>>"
                )
            text = text + "\n" + "\n".join(blocks)
        last_sim["narrative"] = text
        last_sim["payload"] = payload
        return text, payload

    monkeypatch.setattr(decree_mod, "simulate_season_with_payload", _sim)
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)

    def _module_agent(*a, **k):
        module = a[2] if len(a) > 2 else k.get("module")
        if modules_seen is not None:
            modules_seen.append(module)
        return object()

    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", _module_agent)

    def _extract(*a, **k):
        if extract_calls is not None:
            extract_calls.append(1)
        if extract_fn is not None:
            dynamic = extract_fn(
                last_sim["narrative"], last_sim["payload"], args=a, kwargs=k,
            ) or {}
            return (dict(dynamic), "out", "in")
        return (dict(canned_extract), "out", "in")

    monkeypatch.setattr(decree_mod, "extract_scores_by_modules_with_agno", _extract)
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "record_chapter_memory", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_ending_summary_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_rescript_draft_agent", lambda *a, **k: object())
    monkeypatch.setattr(
        memories, "run_agent_text", lambda *a, **k: '{"body":"月记","tags":[]}',
    )

    if skip_fixed_flows:
        monkeypatch.setattr(decree_mod, "apply_fixed_period_flows", lambda *_a, **_k: None)

    if skip_relation_brew:
        class _SkipBrewLeg:
            def prepare(self):
                return False

        monkeypatch.setattr(
            decree_mod,
            "_make_relation_brew_runner",
            lambda *_a, **_k: (lambda *_a2, **_k2: _SkipBrewLeg()),
        )

    if source_spy is not None:
        real_settle = decree_mod.settle_with_delta

        def _spy_settle(*a, **k):
            source_spy.append(k.get("source"))
            return real_settle(*a, **k)

        monkeypatch.setattr(decree_mod, "settle_with_delta", _spy_settle)

    return simulator_calls
