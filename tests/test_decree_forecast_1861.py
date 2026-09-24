"""#1861：召对应允后的夜里逐旨预推，只进暂存，不进账本与可读目录。"""

from __future__ import annotations

import json
import shutil
import threading
from types import SimpleNamespace

import ming_sim.decree as decree_mod
import ming_sim.decree_forecast as forecast_mod
import ming_sim.month_translate as month_translate
from ming_sim.audience_night import mark_actions_night_approved, open_night
from ming_sim.declaration_dispatch import pending_action_decree_ref
from ming_sim.exceptions import LLMUnavailable
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
    sources_before = {
        str(row[0]) for row in db.conn.execute(
            "SELECT source_id FROM character_knowledge_sources",
        )
    }

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
    before_question = "before-question"
    after_question = "after-question"
    decision_block = "<<DECISION>>" + json.dumps({
        "title": "请旨", "context": "待择",
        "options": [{"label": "施行"}, {"label": "暂缓"}],
    }, ensure_ascii=False) + "<<END>>"

    def simulate(_agent, _prompt, **kwargs):
        policies.append(kwargs.get("transport_policy"))
        return before_question + decision_block + after_question

    monkeypatch.setattr(forecast_mod.agents, "run_agent_text", simulate)
    seen_segments = []
    translate_policies = []

    def translate_segment(prompt, _llm_config, **kwargs):
        translate_policies.append(kwargs.get("policy"))
        seen_segments.append(prompt)
        return {"effects": [{"account": "国库", "amount": 1}]}

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
    assert stored[0].declaration.get("effects") == [{"account": "国库", "amount": 1}]
    assert stored[0].verdict["decision"] == "promulgated"
    assert stored[0].questions and stored[0].questions[0]["title"] == "请旨"
    assert isinstance(stored[0].forecast_text, str)
    assert "<<DECISION>>" not in stored[0].forecast_text
    assert db.list_pending_decisions(state.turn) == []
    assert policies and policies[0].retry_429 is False and policies[0].max_attempts == 3
    assert judge_policies and all(
        item is not None and item.retry_429 is False and item.max_attempts == 3
        for item in judge_policies
    )
    assert translate_policies and translate_policies[0].retry_429 is False
    assert translate_policies[0].max_attempts == 3
    assert seen_segments and "<<DECISION>>" not in seen_segments[0]
    assert int(state.metrics["国库"]) == treasury_before
    assert db.conn.execute("SELECT COUNT(*) FROM story_ledger_entries").fetchone()[0] == ledger_before
    assert db.conn.execute("SELECT COUNT(*) FROM decree_dossiers").fetchone()[0] == dossier_before
    assert db.conn.execute(
        "SELECT 1 FROM decree_dossiers WHERE pending_action_id IN (?,?)",
        (first, second),
    ).fetchone() is None

    sources_after = {
        str(row[0]) for row in db.conn.execute(
            "SELECT source_id FROM character_knowledge_sources",
        )
    }
    assert sources_after == sources_before
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


def _policy_payload(actor: str, *, text: str, mode: str = "ordinary") -> dict:
    return {
        "dossier_action_type": "policy", "target_kind": "issue",
        "target_id": "test-policy", "actor": actor, "text": text, "mode": mode,
    }


def test_reapproval_changes_version_and_restarts_only_that_forecast(game, monkeypatch):
    db, state, content = game
    open_night(db, state)
    minister = next(iter(content.characters.values()))
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister.name,
        payload=_policy_payload(minister.name, text="着户部核饷。"),
    )
    modes = []

    def judge(_agent, prompt, **_kwargs):
        dossier = json.loads(prompt)["dossiers"][0]
        modes.append(dossier["mode"])
        return json.dumps({
            "verdicts": [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        })

    monkeypatch.setattr(decree_mod, "run_agent_text", judge)
    monkeypatch.setattr(forecast_mod.agents, "run_agent_text", lambda *_a, **_k: "预推")
    monkeypatch.setattr(
        month_translate, "run_declaration_translate_prompt",
        lambda *_a, **_k: {"commissions": []},
    )
    sess = _sess(db, state, content, monkeypatch, lambda *_a, **_k: {})

    def approve(mode=None):
        intent = {"kind": "confirmation", "confirmation": "应允"}
        if mode is not None:
            intent["mode"] = mode
        sess.apply_cli_conversation_actions(
            minister, "应允。", "臣领旨。",
            has_directive=False, secret_order_id=None,
            preclassified_intent=intent, confirm_target_ids={pending_id},
        )
        assert get_session_write_queue(sess).wait_idle(timeout_s=5)

    approve()
    assert modes == ["ordinary"]
    assert db.staged_declarations.staged_for(pending_action_decree_ref(pending_id, 1))
    assert int(db.conn.execute(
        "SELECT version FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()[0]) == 1

    approve("midzhi")
    assert modes[-1] == "midzhi"
    assert db.staged_declarations.staged_for(pending_action_decree_ref(pending_id, 1)) == ()
    restarted = db.staged_declarations.staged_for(pending_action_decree_ref(pending_id, 2))
    assert len(restarted) == 1 and restarted[0].verdict["decision"] == "promulgated"
    assert int(db.conn.execute(
        "SELECT version FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()[0]) == 2

    calls_before = len(modes)
    approve("midzhi")
    assert len(modes) == calls_before
    assert int(db.conn.execute(
        "SELECT version FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()[0]) == 2
    assert len(db.staged_declarations.staged_for(pending_action_decree_ref(pending_id, 2))) == 1


def test_same_version_reapproval_does_not_rerun_after_exhaustion(game, monkeypatch):
    db, state, content = game
    open_night(db, state)
    minister = next(iter(content.characters.values()))
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister.name,
        payload=_policy_payload(minister.name, text="着户部核饷。"),
    )
    calls = []

    def judge(_agent, _prompt, **_kwargs):
        calls.append(1)
        raise LLMUnavailable("rate limited", status_code=429)

    monkeypatch.setattr(decree_mod, "run_agent_text", judge)
    monkeypatch.setattr(
        forecast_mod.agents, "run_agent_text",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("耗尽不得推演")),
    )
    sess = _sess(db, state, content, monkeypatch, lambda *_a, **_k: {})

    def approve():
        sess.apply_cli_conversation_actions(
            minister, "应允。", "臣领旨。",
            has_directive=False, secret_order_id=None,
            preclassified_intent={"kind": "confirmation", "confirmation": "应允"},
            confirm_target_ids={pending_id},
        )
        assert get_session_write_queue(sess).wait_idle(timeout_s=5)

    approve()
    assert calls == [1]
    assert db.staged_declarations.staged_for(pending_action_decree_ref(pending_id, 1)) == ()
    approve()
    assert calls == [1]
    assert int(db.conn.execute(
        "SELECT version FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()[0]) == 1


def test_held_rejudgments_overlap_instead_of_waiting_in_one_worker(game, monkeypatch):
    db, state, content = game
    state.turn += 1
    ids = []
    for text in ("旧旨甲", "旧旨乙"):
        dossier_id = db.create_decree_dossier(
            state, action_type="policy", decree_text=text,
            target_kind="issue", target_id="test-policy",
            payload={
                "dossier_action_type": "policy", "target_kind": "issue",
                "target_id": "test-policy", "text": text,
            },
        )
        db.conn.execute(
            "UPDATE decree_dossiers SET status='proposed', promulgation_decision='rejected', "
            "held_turn=?, rescript_pending=0 WHERE id=?",
            (state.turn - 1, dossier_id),
        )
        ids.append(dossier_id)
    db.conn.commit()
    open_night(db, state)
    entered = []
    gate = threading.Event()
    lock = threading.Lock()

    def judge(_agent, prompt, **_kwargs):
        dossier = json.loads(prompt)["dossiers"][0]
        return json.dumps({
            "verdicts": [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        })

    def simulate(_agent, _prompt, **_kwargs):
        with lock:
            entered.append(1)
            if len(entered) == 2:
                gate.set()
        assert gate.wait(2)
        return "预推"

    monkeypatch.setattr(decree_mod, "run_agent_text", judge)
    monkeypatch.setattr(forecast_mod.agents, "run_agent_text", simulate)
    monkeypatch.setattr(
        month_translate, "run_declaration_translate_prompt",
        lambda *_a, **_k: {"commissions": []},
    )
    sess = _sess(db, state, content, monkeypatch, lambda *_a, **_k: {})
    assert forecast_mod.schedule_held_decree_forecasts(sess) is True
    assert get_session_write_queue(sess).wait_idle(timeout_s=5)
    assert len(entered) == 2
    for dossier_id in ids:
        staged = db.conn.execute(
            "SELECT status FROM staged_declarations WHERE decree_ref=?",
            (f"dossier:{dossier_id}",),
        ).fetchone()
        assert staged is not None and staged["status"] == "staged"


def test_same_local_ids_on_two_saves_both_stage(game, _game_template_path, monkeypatch, tmp_path):
    from ming_sim.db import GameDB

    db, state, content = game
    minister = next(iter(content.characters.values()))
    copy_path = tmp_path / "save-b.db"
    shutil.copyfile(_game_template_path, copy_path)
    other = GameDB(str(copy_path), content)

    entered = []
    started = threading.Event()
    release = threading.Event()
    entered_lock = threading.Lock()

    def judge(_agent, prompt, **_kwargs):
        with entered_lock:
            entered.append(1)
            if len(entered) >= 2:
                release.set()
        started.set()
        assert release.wait(2)
        dossier = json.loads(prompt)["dossiers"][0]
        return json.dumps({
            "verdicts": [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        })

    monkeypatch.setattr(decree_mod, "run_agent_text", judge)
    monkeypatch.setattr(forecast_mod.agents, "run_agent_text", lambda *_a, **_k: "预推")
    monkeypatch.setattr(
        month_translate, "run_declaration_translate_prompt",
        lambda *_a, **_k: {"commissions": []},
    )
    armed = []
    try:
        for one_db, one_state in ((db, state), (other, other.load_state())):
            night = open_night(one_db, one_state)
            pending_id = one_db.stage_pending_action(
                one_state.turn, kind="directive", action="拟旨",
                minister_name=minister.name,
                payload=_policy_payload(minister.name, text="同号旨"),
            )
            mark_actions_night_approved(
                one_db, [pending_id], night_id=int(night["id"]),
            )
            sess = _sess(one_db, one_state, content, monkeypatch, lambda *_a, **_k: {})
            armed.append((sess, one_db, pending_id, int(night["id"])))
        assert armed[0][2] == armed[1][2]
        assert armed[0][3] == armed[1][3]
        assert forecast_mod.schedule_pending_decree_forecast(
            armed[0][0], armed[0][2], night_id=armed[0][3],
        ) is True
        assert started.wait(2)
        assert forecast_mod.schedule_pending_decree_forecast(
            armed[1][0], armed[1][2], night_id=armed[1][3],
        ) is True
        for sess, one_db, pending_id, _night_id in armed:
            assert get_session_write_queue(sess).wait_idle(timeout_s=5)
            stored = one_db.staged_declarations.staged_for(
                pending_action_decree_ref(pending_id, 1),
            )
            assert len(stored) == 1 and stored[0].verdict["decision"] == "promulgated"
        assert len(entered) == 2
    finally:
        release.set()
        for sess, *_rest in armed:
            get_session_write_queue(sess).wait_idle(timeout_s=5)
        other.close()
