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
from ming_sim.declaration_dispatch import (
    held_dossier_decree_ref, pending_action_decree_ref, stage_declaration,
)
from ming_sim.exceptions import LLMUnavailable
from ming_sim.models import LLMConfig
from ming_sim.session import GameSession
from ming_sim.session_write_queue import get_session_write_queue
from tests.conftest import (
    note_queue_until_game_teardown,
    offline_empty_audience_translate,
    persist_and_schedule_scene,
    stub_audience_translate,
    stub_scene_agent,
)
from tests.test_session_write_queue_1353 import wait_pending_writes


# 两个时限各管一件事，量纲不同，不可合并：
#
# 1. 会合窗口（ModelCallRendezvous._MEET_TIMEOUT_S）——**快速定位**用。它只跨
#    「两条腿的线程启动错峰」，不跨任何真实工作量，故可以卡得很紧：生产真把腿
#    排成串行时，第一条腿等满即放行，用例在数秒内红，并拿到会合的原始观测。
# 2. 排空上限（_DRAIN_TIMEOUT_S）——**挂死探测器**用，**不作通过条件**。它要跨
#    腿的全部真实工作量（DB 落账、转译、暂存），因此必须留足余量：实测在
#    10 核共享机、load average 44 时单次排空要 6–8s，5s 会在忙机上稳定假红
#    （实测 3/3 次误报）。宁可用例在真挂死时多等一会儿，也不接受把机器忙
#    写成回归。代价只在本已失败的用例上支付，且此时会合观测已一并打印。
_DRAIN_TIMEOUT_S = 60


class ModelCallRendezvous:
    """模型替身入口的会合：证明两条腿的**模型调用段**真的同时在飞。

    契约（用例名所指）：留中复判 / 两档隔离的两条腿要能同时在飞，而不是在
    单 worker 里排队。替身在入口会合——只有两条腿都到齐才一起放行，故「会合
    达成」本身就是并行的可失败证据。

    与前几轮被推翻的做法相比：

    * **失败归因只陈述观测到的事实**。「没同时在飞」至少有两种成因——生产把
      腿排成串行，或对端腿在到达模型调用段之前就抛错退出；两者的会合表象
      完全一样。故本会合器不把任何一种写成断言消息里的结论，只报原始计数
      （:meth:`report`），成因由判读者结合 executor 日志里的腿内异常判读。
    * **不无限期等对端**：等不到即记超时并放行本腿，票据照常归还，主线程排空
      照常进行——挂死在结构上不存在，不靠 CI 杀进程收场。
    * 不 sleep 扩窗，不用「elapsed 造失败」，成功路径零墙钟依赖：两条腿都
      到达时不论先后多久都会合上。
    * :attr:`arrived` 数的是真进入模型调用段的腿数，缺席即红字，不靠会合
      顺便推断。
    """

    # 只跨线程启动错峰、不跨真实工作量 → 保持紧档（见 _DRAIN_TIMEOUT_S 的分工）。
    _MEET_TIMEOUT_S = 5.0

    def __init__(self, parties: int = 2) -> None:
        self._parties = parties
        self._all_in = threading.Event()
        self._lock = threading.Lock()
        self._arrived = 0
        self._overlapped = False
        self._timed_out = False

    def meet(self) -> None:
        """一条腿进入模型调用段：等对端到齐；到不齐记超时并放行本腿。"""
        with self._lock:
            self._arrived += 1
            quorum = self._arrived >= self._parties
            if quorum and not self._timed_out:
                self._overlapped = True
                self._all_in.set()
            judged_failed = self._timed_out
        if quorum or judged_failed:
            return
        if not self._all_in.wait(self._MEET_TIMEOUT_S):
            with self._lock:
                self._timed_out = True

    @property
    def arrived(self) -> int:
        """真进入过模型调用段的腿数（缺席即不足，用例断言用）。"""
        with self._lock:
            return self._arrived

    @property
    def overlapped(self) -> bool:
        """两条腿的模型调用段确实同时在飞（到齐那一刻起为真，不因事后超时翻案）。"""
        with self._lock:
            return self._overlapped

    def report(self) -> str:
        """会合的原始观测（不含归因结论）：到达腿数 / 是否同时在飞 / 有无腿等超时。"""
        with self._lock:
            return (
                f"{self._arrived}/{self._parties} 腿到达模型调用段；"
                f"同时在飞={self._overlapped}；有腿等不到对端超时={self._timed_out}"
                f"（等对端上限 {self._MEET_TIMEOUT_S}s）。未同时在飞的成因至少两种："
                "生产把腿排成串行，或对端腿在到达前抛错退出——"
                "腿内异常见 executor 的 'decree forecast: future failed' 日志。"
            )


def _drain_legs(sess, in_flight: "ModelCallRendezvous") -> None:
    """排空并发用例的两条腿；排空不成功时把会合的原始观测一并带进消息。

    排空超时与会合未达成是同一处故障的两个面，缺一面就会把「腿在会合前就
    炸了」读成「生产串行」。两条事实一起报，归因留给判读者。
    """
    queue = get_session_write_queue(sess)
    ok = queue.wait_idle(timeout_s=_DRAIN_TIMEOUT_S)
    assert ok, (
        f"pending writes did not drain in {_DRAIN_TIMEOUT_S}s; "
        f"count={queue.inflight_count()}；会合观测：{in_flight.report()}"
    )


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
    # 断言失败时预推仍在跑；登记后夹具在关库前先排空，任务不越过清理边界。
    note_queue_until_game_teardown(db, get_session_write_queue(sess))
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
    # 有限时排空：真挂死在此报红，不靠 CI job 终线兜底（见 _DRAIN_TIMEOUT_S）。
    wait_pending_writes(sess, timeout_s=_DRAIN_TIMEOUT_S)

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
    wait_pending_writes(sess, timeout_s=30)

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
        wait_pending_writes(sess, timeout_s=_DRAIN_TIMEOUT_S)
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
    in_flight = ModelCallRendezvous()

    def judge(_agent, prompt, **_kwargs):
        dossier = json.loads(prompt)["dossiers"][0]
        return json.dumps({
            "verdicts": [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        })

    def simulate(_agent, _prompt, **_kwargs):
        # 契约（用例名所指）：两条腿的**模型调用段**要同时在飞，不是在单 worker
        # 里排队。替身在此会合——真会合，不是事后拿零工作量区间打分。
        in_flight.meet()
        return "预推"

    monkeypatch.setattr(decree_mod, "run_agent_text", judge)
    monkeypatch.setattr(forecast_mod.agents, "run_agent_text", simulate)
    monkeypatch.setattr(
        month_translate, "run_declaration_translate_prompt",
        lambda *_a, **_k: {"commissions": []},
    )
    sess = _sess(db, state, content, monkeypatch, lambda *_a, **_k: {})
    assert forecast_mod.schedule_held_decree_forecasts(sess) is True
    _drain_legs(sess, in_flight)
    # 两条腿都真跑到了模型调用（缺席即红字），且确实同时在飞——会合在替身
    # 入口达成，生产若把两条腿排进单 worker，替身会合会先到时限报红。
    assert in_flight.arrived == 2, f"两条留中复判腿未都到达：{in_flight.report()}"
    assert in_flight.overlapped, f"两条留中复判腿未重叠：{in_flight.report()}"
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


def test_same_local_ids_on_two_saves_both_stage(game, _game_template_path, monkeypatch, tmp_path):
    from ming_sim.db import GameDB

    db, state, content = game
    minister = next(iter(content.characters.values()))
    copy_path = tmp_path / "save-b.db"
    shutil.copyfile(_game_template_path, copy_path)
    other = GameDB(str(copy_path), content)

    in_flight = ModelCallRendezvous()

    def judge(_agent, prompt, **_kwargs):
        # 同上：两档的判官调用段必须同时在飞。
        in_flight.meet()
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
        # 两档先后紧接着提交，两条腿同时在飞；主线程不等任何腿（#1898）。
        for sess, _one_db, pending_id, night_id in armed:
            assert forecast_mod.schedule_pending_decree_forecast(
                sess, pending_id, night_id=night_id,
            ) is True
        for sess, one_db, pending_id, _night_id in armed:
            _drain_legs(sess, in_flight)
            # 两档各自真落库（缺席即红字，不靠会合判否）。
            stored = one_db.staged_declarations.staged_for(
                pending_action_decree_ref(pending_id, 1),
            )
            assert len(stored) == 1 and stored[0].verdict["decision"] == "promulgated"
        assert in_flight.arrived == 2, f"两档腿未都到达：{in_flight.report()}"
        # 契约：两档腿的模型调用段应同时在飞（原始观测见 report，不在此归因）。
        assert in_flight.overlapped, f"两档腿未重叠：{in_flight.report()}"
    finally:
        # 清理也有限时：正文已红时不得再让排空无限期等（判官 #1898 封驳项）。
        # 清理不追加断言——正文红字才是结论，清理只保证有界返回。
        for sess, *_rest in armed:
            get_session_write_queue(sess).wait_idle(timeout_s=_DRAIN_TIMEOUT_S)
        other.close()
