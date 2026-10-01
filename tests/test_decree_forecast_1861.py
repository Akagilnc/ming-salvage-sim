"""#1861：召对应允后的夜里逐旨预推，只进暂存，不进账本与可读目录。"""

from __future__ import annotations

import json
import shutil
import threading
from types import SimpleNamespace

import ming_sim.audience_translation as audience_translation
import ming_sim.decree as decree_mod
import ming_sim.decree_forecast as forecast_mod
import ming_sim.month_translate as month_translate
from ming_sim.audience_night import mark_actions_night_approved, open_night
from ming_sim.declaration_dispatch import (
    held_dossier_decree_ref, pending_action_decree_ref, stage_declaration,
)
from ming_sim.exceptions import LLMUnavailable
from ming_sim.models import LLMConfig
from ming_sim.session import GameSession
from ming_sim.session_write_queue import get_session_write_queue
from tests.conftest import (
    offline_empty_audience_translate, own_session_until_game_teardown,
    persist_and_schedule_scene, stub_audience_translate, stub_scene_agent,
)


def _drain(sess) -> None:
    """等本 session 队列真正排空再继续断言或交还夹具。

    不用固定窗口：预推链上的真实工作（材料目录快照落盘 + 逐旨推演）耗时与
    机器负载相关，窗口比工作短就假红——那是测试自造的时钟预算，不是被测契约。
    队列「无在飞票」是唯一完成事实（与 tests/test_audience_background.py 的
    排空口一致）；真挂死由 CI 作业收尾兜。
    """
    get_session_write_queue(sess).wait_idle()


def _track_submits(monkeypatch, cond, futs) -> None:
    real_submit = audience_translation._executor.submit

    def tracking_submit(fn, /, *args, **kwargs):
        fut = real_submit(fn, *args, **kwargs)
        with cond:
            futs.append(fut)
            cond.notify_all()

        def _notify_terminal(_fut) -> None:
            with cond:
                cond.notify_all()

        fut.add_done_callback(_notify_terminal)
        return fut

    monkeypatch.setattr(audience_translation._executor, "submit", tracking_submit)


def _calls_overlapped(cond, entered, futs, need: int) -> bool:
    """True when `need` stub calls are inside together.

    A future still waiting for a worker has not arrived. Return once every
    submitted call has finished, is blocked in the stub, or is queued behind
    workers that are all inside the stub.
    """
    limit = audience_translation._executor._max_workers
    with cond:
        while len(entered) < need:
            inflight = 0
            queued = 0
            for fut in futs:
                if fut.done():
                    continue
                if fut.running():
                    inflight += 1
                else:
                    queued += 1
            # A running call that has not entered can still arrive.
            if inflight > len(entered):
                cond.wait()
                continue
            # A free worker can pick up a queued call.
            if queued and inflight < limit:
                cond.wait()
                continue
            return False
        return True


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
    sess._write_gate = get_session_write_queue(sess).write_gate
    # 轻壳 session 的后台预推腿也归既有夹具排空生命周期：夹具关库前先排空，
    # 否则仍在飞的材料快照会打到已关闭的连接上（sqlite3.ProgrammingError）。
    own_session_until_game_teardown(db, sess)
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
    visible_affair = db.affairs.open(
        name="预推可见", origin="旨意", year=state.year,
        period=state.period, turn=state.turn,
    )
    future_affair_id = visible_affair.id + 1
    treasury_before = int(state.metrics["国库"])
    ledger_before = db.conn.execute(
        "SELECT COUNT(*) FROM story_ledger_entries WHERE source_chat_turn_id IS NULL"
    ).fetchone()[0]
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
        decree_fact = json.loads(_prompt)["this_decree"]
        assert decree_fact["payload"]["target_id"] == "test-policy"
        assert decree_fact["payload"]["mode"] == "midzhi"
        policies.append(kwargs.get("transport_policy"))
        return before_question + decision_block + after_question

    monkeypatch.setattr(forecast_mod.agents, "run_agent_text", simulate)
    translate_policies = []

    def translate_segment(_prompt, _llm_config, **kwargs):
        translate_policies.append(kwargs.get("policy"))
        return {"effects": {"economy_moves": [
            {"origin_ref": f"affair:{visible_affair.id}", "account": "国库", "delta": -1,
             "category": "过月支出", "reason": "可见事务"},
            {"origin_ref": f"affair:{future_affair_id}", "account": "国库", "delta": -1,
             "category": "过月支出", "reason": "预推后新开事务"},
        ]}}

    monkeypatch.setattr(month_translate, "run_declaration_translate_prompt", translate_segment)
    sess = _sess(db, state, content, monkeypatch, translate_fn)
    ctid = db.create_chat_turn(state, "殿上", "scene", 0, night_id=int(night["id"]))
    result = sess.scene_chat("两道都准", chat_turn_id=ctid)
    persist_and_schedule_scene(sess, db, result)
    _drain(sess)

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
    assert visible_affair.id in stored[0].visible_refs["affairs"]
    assert future_affair_id not in stored[0].visible_refs["affairs"]
    assert stored[0].verdict["decision"] == "promulgated"
    assert stored[0].questions and stored[0].questions[0]["title"] == "请旨"
    assert isinstance(stored[0].forecast_text, str)
    assert db.list_pending_decisions(state.turn) == []
    assert policies and policies[0].retry_429 is False and policies[0].max_attempts == 3
    assert judge_policies and all(
        item is not None and item.retry_429 is False and item.max_attempts == 3
        for item in judge_policies
    )
    assert translate_policies and translate_policies[0].retry_429 is False
    assert translate_policies[0].max_attempts == 3
    assert int(state.metrics["国库"]) == treasury_before
    hidden = db.affairs.open(
        name="暂存后新开", origin="世界段", year=state.year,
        period=state.period, turn=state.turn,
    )
    assert hidden.id == future_affair_id
    from ming_sim.declaration_dispatch import settle_staged_declarations_in_decree_order
    settled = settle_staged_declarations_in_decree_order(
        db, state, [pending_action_decree_ref(second, 1)],
    )[pending_action_decree_ref(second, 1)]
    assert int(state.metrics["国库"]) == treasury_before - 1
    rejections = settled.effects.applied[0]["economy_moves_rejections"]
    assert len(rejections) == 1
    assert rejections[0]["item"]["origin_ref"] == f"affair:{hidden.id}"
    # Background translation legitimately adds a conversation entry; forecast must not
    # publish an extra ledger entry of its own.
    assert db.conn.execute(
        "SELECT COUNT(*) FROM story_ledger_entries WHERE source_chat_turn_id IS NULL"
    ).fetchone()[0] == ledger_before
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
    night = open_night(db, state)
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
    ctid = db.create_chat_turn(state, "殿上", "scene", 0, night_id=int(night["id"]))
    result = sess.scene_chat("准这道", chat_turn_id=ctid)
    persist_and_schedule_scene(sess, db, result)
    _drain(sess)

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


def test_repeat_scene_approval_does_not_rerun_exhausted_forecast(game, monkeypatch):
    db, state, content = game
    night = open_night(db, state)
    minister = next(iter(content.characters.values()))
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister.name,
        payload=_policy_payload(minister.name, text="着户部核饷。"),
    )
    calls = []

    def judge(_agent, _prompt, **_kwargs):
        calls.append(1)
        raise LLMUnavailable("rate limited", status_code=429)

    def translate_fn(prompt, llm_config):
        return {
            **offline_empty_audience_translate(prompt, llm_config),
            "promises": [{"action_id": pending_id, "decision": "应允"}],
        }

    monkeypatch.setattr(decree_mod, "run_agent_text", judge)
    monkeypatch.setattr(
        forecast_mod.agents, "run_agent_text",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("耗尽不得推演")),
    )
    sess = _sess(db, state, content, monkeypatch, translate_fn)
    for message in ("准这道", "再准这道"):
        ctid = db.create_chat_turn(state, "殿上", "scene", 0, night_id=int(night["id"]))
        result = sess.scene_chat(message, chat_turn_id=ctid)
        persist_and_schedule_scene(sess, db, result)
        _drain(sess)
        assert calls == [1]
        assert db.staged_declarations.staged_for(pending_action_decree_ref(pending_id, 1)) == ()
    assert calls == [1]
    assert int(db.conn.execute(
        "SELECT night_approved, version FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["night_approved"]) == 1


def test_restored_directive_forecast_uses_its_approved_night(game, monkeypatch):
    db, state, content = game
    night = open_night(db, state)
    minister = next(iter(content.characters.values()))
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister.name,
        payload={"text": "回滚后续推"},
    )
    db.conn.execute(
        "UPDATE pending_actions SET night_approved=1, night_id=? WHERE id=?",
        (int(night["id"]), pending_id),
    )
    db.conn.commit()
    scheduled = []
    monkeypatch.setattr(
        forecast_mod, "schedule_pending_decree_forecast",
        lambda session, action_id, *, night_id: scheduled.append((action_id, night_id)),
    )

    session = _sess(db, state, content, monkeypatch, lambda *_a, **_k: {})
    forecast_mod.schedule_restored_decree_forecasts(session, [pending_id])

    assert scheduled == [(pending_id, int(night["id"]))]


def test_held_rejudgments_overlap_instead_of_waiting_in_one_worker(game, monkeypatch):
    db, state, content = game
    state.turn += 1
    db.save_state(state)
    ids = []
    pending_ids = []
    minister = next(iter(content.characters.values()))
    for text in ("旧旨甲", "旧旨乙"):
        pending_id = db.stage_pending_action(
            state.turn, kind="directive", action="拟旨",
            minister_name=minister.name,
            payload={"dossier_action_type": "policy", "target_kind": "issue",
                     "target_id": "test-policy", "text": text},
        )
        pending_ids.append(pending_id)
        dossier_id = db.create_decree_dossier(
            state, action_type="policy", decree_text=text,
            target_kind="issue", target_id="test-policy",
            pending_action_id=pending_id,
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
        stage_declaration(
            db, decree_ref=pending_action_decree_ref(pending_id, 1),
            declaration={}, turn=int(state.turn) - 1,
            verdict={"decision": "rejected"},
        )
        ids.append(dossier_id)
    db.conn.commit()
    open_night(db, state)
    entered = []
    release = threading.Event()
    cond = threading.Condition()
    futs = []

    def judge(_agent, prompt, **_kwargs):
        dossier = json.loads(prompt)["dossiers"][0]
        return json.dumps({
            "verdicts": [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        })

    def simulate(_agent, _prompt, **_kwargs):
        with cond:
            entered.append(1)
            cond.notify_all()
        release.wait()
        return "预推"

    _track_submits(monkeypatch, cond, futs)
    monkeypatch.setattr(decree_mod, "run_agent_text", judge)
    monkeypatch.setattr(forecast_mod.agents, "run_agent_text", simulate)
    monkeypatch.setattr(
        month_translate, "run_declaration_translate_prompt",
        lambda *_a, **_k: {"commissions": []},
    )
    sess = _sess(db, state, content, monkeypatch, lambda *_a, **_k: {})
    assert forecast_mod.schedule_held_decree_forecasts(sess) is True
    try:
        overlapped = _calls_overlapped(cond, entered, futs, 2)
        release.set()
        _drain(sess)
        assert overlapped
        for dossier_id, pending_id in zip(ids, pending_ids):
            stale_ref = pending_action_decree_ref(pending_id, 1)
            held_ref = held_dossier_decree_ref(dossier_id)
            stale = db.staged_declarations.staged_for(stale_ref)
            fresh = db.staged_declarations.staged_for(held_ref)
            assert stale[0].verdict["decision"] == "rejected"
            assert len(fresh) == 1 and fresh[0].status == "staged"
            assert fresh[0].verdict["decision"] == "promulgated"
            assert dossier_id in fresh[0].visible_refs["dossiers"]
        from ming_sim.month_chain import _settle_edicts

        chain = {}
        _settle_edicts(sess, chain=chain)
        assert all(
            db.get_decree_dossier(dossier_id)["promulgation_decision"] == "promulgated"
            for dossier_id in ids
        )
        for dossier_id, pending_id in zip(ids, pending_ids):
            stale_ref = pending_action_decree_ref(pending_id, 1)
            held_ref = held_dossier_decree_ref(dossier_id)
            assert not db.staged_declarations.is_settled(stale_ref)
            assert db.staged_declarations.is_settled(held_ref)

        # 再次进入月链结算：留中案卷仍保持 dossier 身份，旧 pending-action 暂存不被冒名结算
        _settle_edicts(sess, chain=chain)
        for dossier_id, pending_id in zip(ids, pending_ids):
            stale_ref = pending_action_decree_ref(pending_id, 1)
            held_ref = held_dossier_decree_ref(dossier_id)
            assert not db.staged_declarations.is_settled(stale_ref)
            assert db.staged_declarations.is_settled(held_ref)
            dossier = db.get_decree_dossier(dossier_id)
            assert forecast_mod.decree_ref_for_dossier(db, dossier) == held_ref
        late = db.create_decree_dossier(
            state, action_type="policy", decree_text="预推后", target_kind="issue",
            target_id="test-policy", payload={"text": "预推后"},
        )
        assert late not in fresh[0].visible_refs["dossiers"]
    finally:
        release.set()
        _drain(sess)


def test_same_local_ids_on_two_saves_both_stage(game, _game_template_path, monkeypatch, tmp_path):
    from ming_sim.db import GameDB

    db, state, content = game
    minister = next(iter(content.characters.values()))
    copy_path = tmp_path / "save-b.db"
    shutil.copyfile(_game_template_path, copy_path)
    other = GameDB(str(copy_path), content)

    entered = []
    release = threading.Event()
    cond = threading.Condition()
    futs = []

    def judge(_agent, prompt, *_args, **_kwargs):
        with cond:
            entered.append(1)
            cond.notify_all()
        release.wait()
        dossier = json.loads(prompt)["dossiers"][0]
        return json.dumps({
            "verdicts": [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        })

    _track_submits(monkeypatch, cond, futs)
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
        first_inside = _calls_overlapped(cond, entered, futs, 1)
        assert forecast_mod.schedule_pending_decree_forecast(
            armed[1][0], armed[1][2], night_id=armed[1][3],
        ) is True
        overlapped = _calls_overlapped(cond, entered, futs, 2)
        release.set()
        for sess, *_rest in armed:
            _drain(sess)
        assert first_inside and overlapped
        for sess, one_db, pending_id, _night_id in armed:
            stored = one_db.staged_declarations.staged_for(
                pending_action_decree_ref(pending_id, 1),
            )
            assert len(stored) == 1 and stored[0].verdict["decision"] == "promulgated"
    finally:
        # 无论成败先放行门闩，再把两 session 排空——第二连接由本用例自己持有，
        # 夹具只管第一库；不排空就关它，仍在飞的腿会打到已关闭的连接上。
        release.set()
        for sess, *_rest in armed:
            _drain(sess)
        other.close()
