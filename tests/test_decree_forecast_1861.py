"""#1861：召对应允后的夜里逐旨预推，只进暂存，不进账本与可读目录。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import ming_sim.decree as decree_mod
import ming_sim.decree_forecast as forecast_mod
import ming_sim.month_translate as month_translate
from ming_sim.audience_night import open_night
from ming_sim.declaration_dispatch import pending_action_decree_ref
from ming_sim.exceptions import LLMUnavailable
from ming_sim.materials import prepare_character_materials, prepare_world_materials
from ming_sim.models import LLMConfig
from ming_sim.session import GameSession
from ming_sim.session_write_queue import get_session_write_queue
from tests.conftest import offline_empty_audience_translate, stub_audience_translate, stub_scene_agent


def _sess(db, state, content, monkeypatch, translate_fn):
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = LLMConfig(
        api_key="test", base_url="https://example.invalid/v1", model="test-model",
    )
    sess.temporary_characters = {}
    sess.agno_db = None
    sess._beat_generator = None
    sess._scene_registry = None
    sess._write_gate = None
    stub_audience_translate(monkeypatch, translate_fn)
    stub_scene_agent(monkeypatch, SimpleNamespace(
        run=lambda _message: SimpleNamespace(content="臣领旨。", tools=[]),
    ))
    return sess


def test_scene_chat_approval_forecasts_each_decree_without_visible_effect(game, monkeypatch):
    db, state, content = game
    night = open_night(db, state)
    minister = next(iter(content.characters.values()))
    payload = {
        "dossier_action_type": "policy", "target_kind": "issue",
        "target_id": "test-policy", "actor": minister.name, "mode": "ordinary",
    }
    first = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister.name,
        payload={**payload, "text": "甲旨"},
    )
    second = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister.name,
        payload={**payload, "text": "乙旨", "mode": "midzhi"},
    )
    treasury_before = int(state.metrics["国库"])
    ledger_before = db.conn.execute("SELECT COUNT(*) FROM story_ledger_entries").fetchone()[0]
    dossier_before = db.conn.execute("SELECT COUNT(*) FROM decree_dossiers").fetchone()[0]

    def translate_fn(prompt, llm_config):
        return {
            **offline_empty_audience_translate(prompt, llm_config),
            "promises": [
                {"action_id": first, "decision": "应允"},
                {"action_id": second, "decision": "应允"},
            ],
        }

    judge_policies = []

    def judge(_agent, prompt, **kwargs):
        judge_policies.append(kwargs.get("transport_policy"))
        dossier = json.loads(prompt)["dossiers"][0]
        if dossier["decree_text"] == "甲旨":
            raise LLMUnavailable("exhausted", code="http_429", status_code=429)
        assert dossier["mode"] == "midzhi"
        return json.dumps({
            "verdicts": [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        })

    monkeypatch.setattr(decree_mod, "run_agent_text", judge)
    policies = []

    def simulate(_agent, _prompt, **kwargs):
        policies.append(kwargs.get("transport_policy"))
        return "问前交代" + "<<DECISION>>" + json.dumps({
            "title": "请旨", "context": "待择",
            "options": [{"label": "施行"}, {"label": "暂缓"}],
        }, ensure_ascii=False) + "<<END>>" + "问后不得入预算"

    monkeypatch.setattr(forecast_mod.agents, "run_agent_text", simulate)
    seen_segments = []
    translate_policies = []

    def translate_segment(prompt, _llm_config, **kwargs):
        translate_policies.append(kwargs.get("policy"))
        seen_segments.append(prompt)
        return {"effects": [{"account": "国库", "amount": 880011}]}

    monkeypatch.setattr(month_translate, "run_declaration_translate_prompt", translate_segment)
    sess = _sess(db, state, content, monkeypatch, translate_fn)
    sess.scene_chat("两道都准")
    assert get_session_write_queue(sess).wait_idle(timeout_s=5)

    assert db.conn.execute(
        "SELECT 1 FROM staged_declarations WHERE decree_ref=?",
        (pending_action_decree_ref(first, 1),),
    ).fetchone() is None
    staged = db.conn.execute(
        "SELECT declaration_json,status FROM staged_declarations WHERE decree_ref=?",
        (pending_action_decree_ref(second, 1),),
    ).fetchone()
    assert staged is not None and staged["status"] == "staged"
    stored = db.staged_declarations.staged_for(pending_action_decree_ref(second, 1))
    assert stored[0].verdict["decision"] == "promulgated"
    assert stored[0].questions and stored[0].questions[0]["title"] == "请旨"
    assert stored[0].forecast_text is not None and "问前交代" in stored[0].forecast_text
    assert "问后不得入预算" not in stored[0].forecast_text
    assert db.list_pending_decisions(state.turn) == []
    assert policies and policies[0].retry_429 is False and policies[0].max_attempts == 3
    assert judge_policies and all(
        item is not None and item.retry_429 is False and item.max_attempts == 3
        for item in judge_policies
    )
    assert translate_policies and translate_policies[0].retry_429 is False
    assert translate_policies[0].max_attempts == 3
    assert seen_segments and "问后不得入预算" not in seen_segments[0]
    assert int(state.metrics["国库"]) == treasury_before
    assert db.conn.execute("SELECT COUNT(*) FROM story_ledger_entries").fetchone()[0] == ledger_before
    assert db.conn.execute("SELECT COUNT(*) FROM decree_dossiers").fetchone()[0] == dossier_before
    assert db.conn.execute(
        "SELECT 1 FROM decree_dossiers WHERE pending_action_id IN (?,?)",
        (first, second),
    ).fetchone() is None

    character_tree = prepare_character_materials(db, state, minister).root
    world_tree = prepare_world_materials(db, state).root
    readable = "\n".join(
        path.read_text(encoding="utf-8")
        for root in (character_tree, world_tree)
        for path in root.rglob("*")
        if path.is_file()
    )
    assert "880011" not in readable
    assert "问前交代" not in readable
    assert pending_action_decree_ref(second, 1) not in readable
    assert int(night["id"]) > 0


def test_scene_chat_rejection_is_staged_for_later_rescript_not_shown_at_night(
    game, monkeypatch,
):
    db, state, content = game
    open_night(db, state)
    minister = next(iter(content.characters.values()))
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister.name,
        payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "test-policy", "actor": minister.name, "mode": "ordinary",
            "text": "着户部另核辽饷。",
        },
    )

    def translate_fn(prompt, llm_config):
        return {
            **offline_empty_audience_translate(prompt, llm_config),
            "promises": [{"action_id": pending_id, "decision": "应允"}],
        }

    def judge(_agent, prompt, **_kwargs):
        context = json.loads(prompt)
        dossier = context["dossiers"][0]
        faction = context["factions"][0]["name"]
        return json.dumps({"verdicts": [{
            "dossier_id": dossier["id"],
            "decision": "rejected",
            "blocked_layer": "palace_rescript",
            "reason": "越制",
            "primary_opponents": [{"kind": "faction", "key": faction}],
            "gatekeeper_id": None,
            "affected_parties": [{
                "kind": "faction", "key": faction,
                "direction": "negative", "intensity": "weak",
            }],
            "criteria_snapshot": dossier["criteria_snapshot_source"],
        }]})

    monkeypatch.setattr(decree_mod, "run_agent_text", judge)
    monkeypatch.setattr(
        forecast_mod.agents, "run_agent_text",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("打回不得推演")),
    )
    sess = _sess(db, state, content, monkeypatch, translate_fn)
    sess.scene_chat("准这道")
    assert get_session_write_queue(sess).wait_idle(timeout_s=5)

    stored = db.staged_declarations.staged_for(pending_action_decree_ref(pending_id, 1))
    assert len(stored) == 1
    assert stored[0].verdict["decision"] == "rejected"
    assert stored[0].questions is None
    assert stored[0].forecast_text is None
    assert stored[0].declaration == {}
    assert db.list_pending_decisions(state.turn) == []
    assert db.conn.execute(
        "SELECT 1 FROM decree_dossiers WHERE pending_action_id=?", (pending_id,),
    ).fetchone() is None
