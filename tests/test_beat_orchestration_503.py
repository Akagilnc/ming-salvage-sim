"""#503 开场/收夜 beat 编排——输入路由 / 零形式约束传递 / P4 不喂 / 见闻供给接口。

seam：
- assemble_beat_inputs（输入路由的公开边界，断言输入面：AC2/AC4/AC5 审计）；
- 真实召对会话入口 attach_chat_turn_to_night + close_night（注入 generator/provider）
  对故事账本 DB 的效果（AC1/AC3/AC5 落账正文，PRD #497「最高 seam」）。

不锁文案质量（归 #472/#478）；注入 echo 生成器把路由后的输入回显进账正文，据此断言编排。
"""

from __future__ import annotations

import contextlib
from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace
import threading
import time

import pytest

import web_app
from ming_sim import audience_night as an
from ming_sim import beat_orchestration as bo
from ming_sim.beat_orchestration import (
    BEAT_CLOSE,
    BEAT_ENTER,
    BEAT_EXIT,
    BEAT_OPEN,
    BeatInputs,
    assemble_beat_inputs,
    beat_input_field_names,
)


def test_abandon_running_scene_drains_without_persisting_result():
    """A running LLM Future cannot be cancelled; abort must join it before returning."""
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def slow_gen(inputs: BeatInputs) -> str:
        started.set()
        release.wait(1)
        finished.set()
        return f"body-{inputs.beat_kind}"

    registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=2))
    # Direct task submit: one running future the abandon path must drain.
    registry._submit(7, [(1, BeatInputs(beat_kind=BEAT_OPEN))], slow_gen)
    assert started.wait(1)
    waiter = threading.Thread(target=registry.abandon, args=(7,))
    waiter.start()
    assert waiter.is_alive()
    release.set()
    waiter.join(1)
    assert finished.is_set()
    assert not waiter.is_alive()
    assert not registry.has(7)


def test_join_exception_drains_uncancellable_sibling_before_propagating():
    """#542: join 遇首 Future 异常时仍须 drain 同桶 sibling，排空后再传播原异常。

    seam = ChatTurnSceneRegistry.join 公开边界。
    首 Future 立即失败；后续 Future 已运行且不可取消并阻塞。
    """
    sibling_started = threading.Event()
    release_sibling = threading.Event()
    sibling_finished = threading.Event()
    first_fail = RuntimeError("scene-gen-failed")

    def sibling_gen(inputs: BeatInputs) -> str:
        sibling_started.set()
        assert release_sibling.wait(2), "sibling was not released"
        sibling_finished.set()
        return f"body-{inputs.beat_kind}"

    registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=2))
    # Ordered bucket: fail-first Future, then running uncancellable sibling.
    fail_fut: Future = Future()
    fail_fut.set_exception(first_fail)
    slow_fut = registry._executor.submit(sibling_gen, BeatInputs(beat_kind=BEAT_ENTER))
    assert sibling_started.wait(1), "sibling never started"
    with registry._lock:
        registry._futures[11] = [fail_fut, slow_fut]

    outcome: dict = {}

    def run_join():
        try:
            outcome["result"] = registry.join(11)
        except BaseException as exc:
            outcome["exc"] = exc

    waiter = threading.Thread(target=run_join)
    waiter.start()
    # join must not return/raise while uncancellable sibling is still running.
    waiter.join(0.2)
    assert waiter.is_alive(), "join returned before draining sibling"
    assert "exc" not in outcome and "result" not in outcome
    assert not sibling_finished.is_set()

    release_sibling.set()
    waiter.join(2)
    assert not waiter.is_alive()
    assert sibling_finished.is_set()
    assert outcome.get("exc") is first_fail
    assert "result" not in outcome
    assert not registry.has(11)


def test_web_retry_failed_scene_drain_does_not_hold_write_gate(game):
    """#542: retry except 路径 drain 时 _write_gate 须可被他者取得（真实 retry 入口）。"""
    db, state, content = game
    minister = _active_minister(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    _nid, ctid = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="drain-gate", agno_runs_before=0,
    )
    uid = db.append_chat_message(minister, state.turn, "user", "重试问")
    db.update_chat_turn_messages(ctid, user_message_id=uid)
    db.conn.execute("UPDATE chat_turns SET status='interrupted' WHERE id=?", (ctid,))
    db.conn.commit()
    drain_entered, release_drain = threading.Event(), threading.Event()

    class _Session:
        temporary_characters: set = set()

        def __init__(self):
            self.db, self.state = db, state
            self.content = SimpleNamespace(
                characters={minister: SimpleNamespace(name=minister)},
            )

        def start_chat_turn_scene(self, *_a, **_k): return None
        def join_chat_turn_scene(self, *_a, **_k): return []
        def persist_chat_turn_scene(self, *_a, **_k): return None
        def abandon_chat_turn_scene(self, _ctid):
            drain_entered.set()
            assert release_drain.wait(2)
        def chat(self, *_a, **_k):
            raise RuntimeError("retry llm failed")

    rt = object.__new__(web_app.WebGame)
    rt.session = _Session()
    rt.chat_history = {minister: []}
    rt._write_gate = threading.Lock()
    rt._runtime_write_gate = lambda: rt._write_gate
    rt._audience_turn_in_flight = lambda _n: False
    # 整轮 pending 由 retry 本体持有；尾随不起后台线程。
    from ming_sim.session_write_queue import SessionWriteQueue
    rt._write_queue = SessionWriteQueue()
    rt._write_gate = rt._write_queue.write_gate
    rt._runtime_write_queue = lambda: rt._write_queue  # type: ignore
    rt._mark_pending_write = lambda key=None: rt._write_queue.claim(key=key or ("pending",))  # type: ignore
    rt._complete_pending_write = lambda ticket=None: rt._write_queue.complete(ticket)  # type: ignore
    rt._spawn_pending_write_thread = lambda *a, **k: False
    rt._spawn_extraction_trail = lambda *a, **k: None
    rt.directive_rows = lambda: []
    rt.directive_payload = lambda row: row
    rt.suggestions_for = lambda _c: []
    rt.can_undo_last_chat = lambda _n: False
    rt.pending_action_failures_for = lambda _n: []
    errors: list[BaseException] = []

    def run_retry():
        try:
            rt.retry_interrupted_reply(minister)
        except BaseException as exc:
            errors.append(exc)

    t = threading.Thread(target=run_retry)
    t.start()
    assert drain_entered.wait(2), "retry never entered scene drain"
    assert rt._write_gate.acquire(timeout=0.3), "write gate held during drain"
    rt._write_gate.release()
    release_drain.set()
    t.join(2)
    assert not t.is_alive()
    assert errors and isinstance(errors[0], RuntimeError)


def test_open_and_enter_scene_beats_run_concurrently(game):
    """#542: 无依赖的 open/enter 须真并发（max_active>=2）。"""
    db, state, content = game
    minister = _active_minister(db, content)
    _nid, ctid = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="par-oe", agno_runs_before=0,
    )
    active = max_active = 0
    lock = threading.Lock()
    release = threading.Event()

    def blocking_gen(inputs: BeatInputs) -> str:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        release.wait(1)
        with lock:
            active -= 1
        return f"kind={inputs.beat_kind}"

    registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=4))
    registry.start_open_enter(
        db, state, minister_name=minister, chat_turn_id=ctid,
        beat_generator=blocking_gen,
    )
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        with lock:
            if max_active >= 2:
                break
        time.sleep(0.01)
    release.set()
    kinds = {body.split("=", 1)[-1] for _eid, body in registry.join(ctid)}
    assert kinds == {"open", "enter"} and max_active >= 2


def test_discover_open_enter_tasks_restores_yueci_summon_method(game):
    """#542: discover_open_enter_tasks 从入殿账 tags 恢复真实召法；registry 路径不写死宣入。"""
    db, state, content = game
    minister = _active_minister(db, content)
    night_id, ctid = an.attach_chat_turn_to_night(
        db, state, minister,
        agno_session_id="yueci-discover", agno_runs_before=0,
        summon_method=an.METHOD_YUECI,
    )
    # Ledger tags already carry 越次; discovery must restore it (not METHOD_XUANRU).
    enter_row = next(
        e for e in an.list_ledger(db, night_id)
        if an.TAG_ENTER in (e.get("tags") or [])
        and int(e.get("origin_chat_turn_id") or 0) == int(ctid)
    )
    assert an.METHOD_YUECI in (enter_row.get("tags") or [])

    tasks = bo.discover_open_enter_tasks(
        db, state, minister_name=minister, chat_turn_id=ctid,
    )
    enter_inputs = [inp for _eid, inp in tasks if inp.beat_kind == BEAT_ENTER]
    assert len(enter_inputs) == 1
    assert enter_inputs[0].summon_method == an.METHOD_YUECI

    def echo(inputs: BeatInputs) -> str:
        return f"kind={inputs.beat_kind}|method={inputs.summon_method}"

    registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=2))
    registry.start_open_enter(
        db, state, minister_name=minister, chat_turn_id=ctid,
        beat_generator=echo,
    )
    bodies = [body for _eid, body in registry.join(ctid)]
    assert any(f"method={an.METHOD_YUECI}" in b for b in bodies), bodies
    assert not any(f"method={an.METHOD_XUANRU}" in b and "enter" in b for b in bodies), bodies


def test_start_open_enter_claims_atomically_under_concurrent_calls(game, monkeypatch):
    """#542: 同 chat_turn_id 并发 start_open_enter 至多一轮 discover/submit。"""
    db, state, content = game
    minister = _active_minister(db, content)
    _nid, ctid = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="claim-oe", agno_runs_before=0,
    )
    discover_calls = gen_starts = 0
    lock = threading.Lock()
    real_discover = bo.discover_open_enter_tasks

    def slow_discover(*a, **k):
        nonlocal discover_calls
        with lock:
            discover_calls += 1
        time.sleep(0.05)
        return real_discover(*a, **k)

    monkeypatch.setattr(bo, "discover_open_enter_tasks", slow_discover)

    def counting_gen(inputs: BeatInputs) -> str:
        nonlocal gen_starts
        with lock:
            gen_starts += 1
        return f"kind={inputs.beat_kind}"

    registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=4))
    threads = [
        threading.Thread(
            target=registry.start_open_enter,
            kwargs=dict(
                db=db, state=state, minister_name=minister, chat_turn_id=ctid,
                beat_generator=counting_gen,
            ),
        )
        for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(2)
        assert not t.is_alive()
    kinds = sorted(body.split("=", 1)[-1] for _eid, body in registry.join(ctid))
    assert discover_calls == 1 and gen_starts == 2 and kinds == ["enter", "open"]
    assert not registry.has(ctid)


@pytest.mark.parametrize("mode", ["join", "abandon"])
def test_start_open_enter_discover_vs_drain_no_late_future(game, monkeypatch, mode):
    """#542: start@discover 与 join/abandon 交错——drain 后无迟到 Future/无桶重建。"""
    db, state, content = game
    minister = _active_minister(db, content)
    _nid, ctid = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id=f"drain-{mode}", agno_runs_before=0,
    )
    in_discover, release_discover = threading.Event(), threading.Event()
    real_discover = bo.discover_open_enter_tasks

    def gated_discover(*a, **k):
        in_discover.set()
        assert release_discover.wait(2)
        return real_discover(*a, **k)

    monkeypatch.setattr(bo, "discover_open_enter_tasks", gated_discover)
    gen_starts = 0

    def counting_gen(inputs: BeatInputs) -> str:
        nonlocal gen_starts
        gen_starts += 1
        return f"kind={inputs.beat_kind}"

    registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=4))
    starter = threading.Thread(
        target=registry.start_open_enter,
        kwargs=dict(
            db=db, state=state, minister_name=minister, chat_turn_id=ctid,
            beat_generator=counting_gen,
        ),
    )
    starter.start()
    assert in_discover.wait(2), "start never entered discover"
    if mode == "join":
        assert registry.join(ctid) == []
    else:
        registry.abandon(ctid)
    release_discover.set()
    starter.join(2)
    assert not starter.is_alive()
    assert not registry.has(ctid) and registry.active_turn_ids() == []
    assert gen_starts == 0 and registry.join(ctid) == []


def test_exit_scene_joins_chat_turn_lifecycle_not_sync_generate(game):
    """#542: 退下旁白进 scene lifecycle；dismiss 同步不跑 LLM；join 后才落 body。"""
    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state, time_of_day="戌时", location="乾清宫")
    an.summon_enter(db, night["id"], minister)
    ctid = db.create_chat_turn(state, minister, "exit-life", 0, night_id=night["id"])
    started, release = threading.Event(), threading.Event()
    calls: list[str] = []

    def slow_exit(inputs: BeatInputs) -> str:
        calls.append(inputs.beat_kind)
        started.set()
        assert release.wait(1)
        return "特征化退下旁白"

    registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=2))
    entry_id = an.dismiss_from_audience(
        db, minister, night_id=night["id"], origin_chat_turn_id=ctid, state=state,
        beat_generator=lambda inputs: calls.append("sync") or "同步旁白",
    )
    placeholder = an.list_ledger(db, night["id"])[-1]["body"]
    assert entry_id and "sync" not in calls and placeholder != "特征化退下旁白"
    registry.start_exit(
        db, state, person_name=minister, chat_turn_id=ctid, entry_id=int(entry_id),
        night_id=int(night["id"]), beat_generator=slow_exit,
    )
    assert started.wait(1)
    assert an.list_ledger(db, night["id"])[-1]["body"] == placeholder  # 无迟到补写
    release.set()
    bo.persist_chat_turn_scene(db, registry.join(ctid))
    db.conn.commit()
    assert an.list_ledger(db, night["id"])[-1]["body"] == "特征化退下旁白"
    assert calls == [BEAT_EXIT]


def _active_minister(db, content, *, exclude=None):
    skip = exclude or set()
    for name, ch in content.characters.items():
        if name in skip:
            continue
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if db.get_character_status(name)[0] == "active":
            return name
    raise AssertionError("no active ming minister")


def _echo_generator(inputs: BeatInputs) -> str:
    """路由后输入回显进账正文，供断言编排（非文案质量）。"""
    return "‖".join([
        f"kind={inputs.beat_kind}", f"person={inputs.person_name}",
        f"method={inputs.summon_method}", f"tod={inputs.time_of_day}",
        f"loc={inputs.location}", f"char={inputs.characterization}",
        f"world={inputs.perspectival_world}", f"tension={inputs.court_tension}",
        f"prior={'∥'.join(inputs.prior_appearances)}",
        f"public={'∥'.join(inputs.public_layer)}",
    ])


def _ledger_body(db, night_id, *required_tags):
    need = set(required_tags)
    for e in an.list_ledger(db, night_id):
        if need.issubset(set(e["tags"])):
            return e["body"]
    return None


def _enter_body(db, night_id, person):
    for e in an.list_ledger(db, night_id):
        if an.TAG_ENTER in e["tags"] and person in e["person_names"]:
            return e["body"]
    return None


def _land_reply(db, state, minister, chat_id, night_id, text="臣遵旨。"):
    """回话入档（清在飞态）+ 落抽取水位（清待补），使收夜守卫（在飞/#501 drain）不误挡。"""
    mid = db.append_chat_message(minister, state.turn, "minister", text)
    db.update_chat_turn_messages(chat_id, minister_message_id=int(mid))
    db.settle_story_extraction(int(chat_id), int(night_id), [], 0)


# ── AC1：入殿账随（身份/召法/时地）输入不同而不同；时地取自夜容器持久属性 ──


def test_enter_beat_varies_by_identity_and_method(game):
    db, state, content = game
    a = _active_minister(db, content)
    b = _active_minister(db, content, exclude={a})

    _nid, _cid = an.attach_chat_turn_to_night(
        db, state, a, agno_session_id="sa", agno_runs_before=0,
        time_of_day="戌时", location="乾清宫", summon_method=an.METHOD_XUANRU,
        beat_generator=_echo_generator,
    )
    night = an.get_open_night(db)
    an.attach_chat_turn_to_night(
        db, state, b, agno_session_id="sb", agno_runs_before=0,
        summon_method=an.METHOD_YUECI, beat_generator=_echo_generator,
    )

    body_a = _enter_body(db, night["id"], a)
    body_b = _enter_body(db, night["id"], b)
    assert body_a and body_b
    # 非空且随身份不同而不同
    assert body_a != body_b
    assert f"person={a}" in body_a and f"person={b}" in body_b
    # 随召法不同而不同
    assert f"method={an.METHOD_XUANRU}" in body_a
    assert f"method={an.METHOD_YUECI}" in body_b
    # 时辰/地点取自夜容器持久属性（cmr R7）
    assert "tod=戌时" in body_a and "loc=乾清宫" in body_a
    assert "tod=戌时" in body_b and "loc=乾清宫" in body_b


def test_enter_beat_time_location_from_night_container_not_call_arg(game):
    """cmr R7：入殿账时辰/地点取自夜容器持久属性，非本次 attach 传参。"""
    db, state, content = game
    minister = _active_minister(db, content)
    # 先开夜，持久化 子时/坤宁宫
    an.open_night(db, state, time_of_day="子时", location="坤宁宫")
    # attach 传入不同的 时地——入殿账须反映夜的持久属性，忽略本次传参
    night_id, _cid = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="s", agno_runs_before=0,
        time_of_day="午时", location="偏殿", beat_generator=_echo_generator,
    )
    body = _enter_body(db, night_id, minister)
    assert body and "tod=子时" in body and "loc=坤宁宫" in body
    assert "午时" not in body and "偏殿" not in body


# ── 修复回归（#503 fix r1）：空白兜底 / 不白跑收夜 LLM / 生成抛错零写入 ──


def _blank_generator(inputs):
    return "   \n\t "


def test_whitespace_generator_fails_loud_without_durable_success(game):
    """空模型输出不得由模板冒充 scene 成功。"""
    db, state, content = game
    minister = _active_minister(db, content)
    with pytest.raises(RuntimeError, match="blank output"):
        an.attach_chat_turn_to_night(
            db, state, minister, agno_session_id="s", agno_runs_before=0,
            time_of_day="戌时", location="乾清宫", beat_generator=_blank_generator,
        )
    assert an.get_open_night(db) is None
    assert db.conn.execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0] == 0


def test_close_night_skips_generator_when_body_given_or_already_closed(game):
    """L2：收夜账已给显式 body 或已落账（幂等续跑）时不白跑贵 LLM。"""
    db, state, content = game
    minister = _active_minister(db, content)
    calls = {"n": 0}

    def counting(inputs):
        calls["n"] += 1
        return f"gen:{inputs.beat_kind}"

    night = an.open_night(db, state, time_of_day="戌时", location="乾清宫")
    # 显式 body → 生成器不应被调
    an.close_night(db, state, night_id=night["id"], content=content,
                   body="朕亲宣退朝。", beat_generator=counting)
    assert calls["n"] == 0
    assert _ledger_body(db, night["id"], an.TAG_CLOSE_NIGHT) == "朕亲宣退朝。"
    # 幂等再收：已落收夜账 → 仍不调生成器、不重复落账
    an.close_night(db, state, night_id=night["id"], content=content,
                   beat_generator=counting)
    assert calls["n"] == 0
    closes = [e for e in an.list_ledger(db, night["id"]) if an.TAG_CLOSE_NIGHT in e["tags"]]
    assert len(closes) == 1


def test_enter_generator_raise_on_new_night_leaves_zero_writes(game):
    """L4：新夜路径入殿账生成抛错 → 本次零写入（不留半开夜/悬空对话轮）。"""
    db, state, content = game
    minister = _active_minister(db, content)

    def raise_on_enter(inputs):
        if inputs.beat_kind == bo.BEAT_ENTER:
            raise RuntimeError("enter gen boom")
        return "开夜气氛"

    with pytest.raises(RuntimeError, match="enter gen boom"):
        an.attach_chat_turn_to_night(
            db, state, minister, agno_session_id="s", agno_runs_before=0,
            time_of_day="戌时", location="乾清宫", beat_generator=raise_on_enter,
        )
    # 零写入：无夜、无账、无对话轮
    assert an.get_open_night(db) is None
    assert db.conn.execute("SELECT COUNT(*) AS c FROM audience_nights").fetchone()["c"] == 0
    assert db.conn.execute("SELECT COUNT(*) AS c FROM story_ledger_entries").fetchone()["c"] == 0
    assert db.conn.execute("SELECT COUNT(*) AS c FROM chat_turns").fetchone()["c"] == 0


# ── AC3：开夜账与收夜账正文落地 ──────────────────────────────────────


def test_open_and_close_beat_bodies_land(game):
    db, state, content = game
    minister = _active_minister(db, content)
    night_id, _cid = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="s", agno_runs_before=0,
        time_of_day="戌时", location="乾清宫", beat_generator=_echo_generator,
    )
    open_body = _ledger_body(db, night_id, an.TAG_OPEN_NIGHT)
    assert open_body and open_body.startswith(f"kind={BEAT_OPEN}")
    # 夜级框架账不落人名
    open_entry = next(
        e for e in an.list_ledger(db, night_id) if an.TAG_OPEN_NIGHT in e["tags"]
    )
    assert open_entry["person_names"] == []
    assert "tod=戌时" in open_body and "loc=乾清宫" in open_body

    _land_reply(db, state, minister, _cid, night_id)
    registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=2))
    an.close_night(
        db, state, night_id=night_id, content=content,
        beat_generator=_echo_generator, scene_registry=registry,
    )
    close_body = _ledger_body(db, night_id, an.TAG_CLOSE_NIGHT)
    assert close_body and close_body.startswith(f"kind={BEAT_CLOSE}")


def test_no_generator_keeps_deterministic_fallback(game):
    """无生成器/registry 缺失 = 确定性 open/close 兜底；文案从时地长出，不硬称夜。"""
    db, state, content = game
    minister = _active_minister(db, content)
    night_id, _cid = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="s", agno_runs_before=0,
        time_of_day="戌时", location="乾清宫",
    )
    open_body = _ledger_body(db, night_id, an.TAG_OPEN_NIGHT)
    assert open_body == "乾清宫·戌时，召对启。"
    assert "夜" not in open_body
    enter_body = _enter_body(db, night_id, minister)
    assert enter_body and "kind=" not in enter_body
    _land_reply(db, state, minister, _cid, night_id)
    # 无 beat_generator、无 scene_registry：走空 body close 兜底
    an.close_night(db, state, night_id=night_id, content=content)
    close_body = _ledger_body(db, night_id, an.TAG_CLOSE_NIGHT)
    assert close_body == "退朝，召对到此。"
    assert "夜" not in close_body


def test_production_beat_generator_open_close_fallback_no_night_hardcode():
    """#542 r3：production open/close 确定性正文从时地长出，不硬称夜。"""
    open_with = bo.production_beat_generator(
        BeatInputs(beat_kind=BEAT_OPEN, time_of_day="戌时", location="乾清宫"),
    )
    assert open_with == "乾清宫·戌时，召对启。"
    assert "夜" not in open_with
    open_bare = bo.production_beat_generator(BeatInputs(beat_kind=BEAT_OPEN))
    assert open_bare == "召对启。"
    assert "夜" not in open_bare

    close_with = bo.production_beat_generator(
        BeatInputs(beat_kind=BEAT_CLOSE, time_of_day="戌时", location="乾清宫"),
    )
    assert close_with == "乾清宫·戌时，退朝，召对到此。"
    assert "夜" not in close_with
    close_bare = bo.production_beat_generator(BeatInputs(beat_kind=BEAT_CLOSE))
    assert close_bare == "退朝，召对到此。"
    assert "夜" not in close_bare


def test_auto_close_fallback_body_no_night_hardcode(game):
    """#542 r3：auto-close 空 body 兜底（王承恩代宣）亦不硬称夜。"""
    db, state, content = game
    night = an.open_night(db, state, time_of_day="戌时", location="便殿")
    an.close_night(db, state, night_id=night["id"], content=content, auto=True)
    close_body = _ledger_body(db, night["id"], an.TAG_CLOSE_NIGHT)
    assert close_body == "王承恩代宣退朝，召对到此。"
    assert "夜" not in close_body


@pytest.fixture
def web_game(tmp_path, monkeypatch):
    """真实 WebGame（离线 LLM）——验证生产 _start_chat_turn 接线。"""
    import web_app

    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    # #544 / #1353 r6：高亮判官 LLM 边界离线中和，禁 sk-test 真网。
    monkeypatch.setattr(web_app, "run_highlight_judge", lambda **_k: [])
    game = web_app.WebGame(fresh=False)
    # e2e seam 注入确定性假 scene LLM；测试绝不访问真实模型。
    game.session._beat_generator = _echo_generator
    yield game
    try:
        game.session.close()
    except Exception:
        pass


def test_exit_beat_routes_characterization_and_perspectival_inputs(game):
    """exit 特征化/见闻走 assemble+generator seam；dismiss 只落垫位，不跑同步 LLM。"""
    db, state, _content = game
    seen = []
    night = an.open_night(db, state, time_of_day="戌时", location="乾清宫")
    an.summon_enter(db, night["id"], "毕自严")

    inputs = assemble_beat_inputs(
        db, state, beat_kind=BEAT_EXIT,
        time_of_day=str(night.get("time_of_day") or ""),
        location=str(night.get("location") or ""),
        night_id=int(night["id"]), person_name="毕自严",
        knowledge_provider=_fake_provider("退侍所见"),
    )
    body = bo.run_beat_generator(
        lambda inp: seen.append(inp) or "毕自严整衣趋出。", inputs,
    )
    entry_id = an.dismiss_from_audience(
        db, "毕自严", night_id=night["id"], state=state, body=body,
    )

    assert entry_id
    assert seen[0].beat_kind == "exit"
    assert seen[0].person_name == "毕自严"
    assert seen[0].characterization
    assert "退侍所见" in seen[0].perspectival_world
    assert an.list_ledger(db, night["id"])[-1]["body"] == "毕自严整衣趋出。"


def test_cli_dismiss_routes_exit_through_scene_registry(game, monkeypatch):
    """#542: CLI「退下」进唯一 registry；不跑同步 generate_exit_beat_body。"""
    import ming_sim.cli.terminal as term
    from ming_sim.session import GameSession

    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state, time_of_day="戌时", location="乾清宫")
    an.summon_enter(db, night["id"], minister)
    started, release = threading.Event(), threading.Event()
    calls: list[str] = []

    def slow_exit(inputs: BeatInputs) -> str:
        calls.append(inputs.beat_kind)
        started.set()
        assert release.wait(1)
        return "CLI特征化退下"

    session = GameSession.__new__(GameSession)
    session.db, session.state, session.content = db, state, content
    session.temporary_characters = set()
    session._beat_generator = slow_exit
    session._scene_registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=2))
    worker = threading.Thread(target=term._record_audience_exit, args=(session, minister))
    worker.start()
    assert started.wait(1), "CLI exit never entered registry generator"
    assert an.list_ledger(db, night["id"])[-1]["body"] != "CLI特征化退下"
    release.set()
    worker.join(2)
    assert not worker.is_alive()
    assert an.list_ledger(db, night["id"])[-1]["body"] == "CLI特征化退下"
    assert calls == [BEAT_EXIT]
    assert minister not in an.present_names_at(db, night["id"])


def test_four_beat_scroll_e2e_via_real_player_entries(web_game):
    """#542 票面 e2e：真实玩家入口→假 generator→卷轴四类 role=scene（零真 LLM）。"""
    game = web_game
    minister = _active_minister(game.db, game.content)
    fake_bodies = {
        BEAT_OPEN: "【开场旁白·特征化】夜色初合。",
        BEAT_ENTER: f"【入殿旁白·特征化】{minister}趋入。",
        BEAT_EXIT: f"【退下旁白·特征化】{minister}告退。",
        BEAT_CLOSE: "【收夜旁白·特征化】烛影摇红。",
    }
    fake_gen = lambda inputs: fake_bodies[inputs.beat_kind]
    game.session._beat_generator = fake_gen
    ctid, _snap = game._start_chat_turn(minister)
    night_id = int(game.db.conn.execute(
        "SELECT night_id FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["night_id"])
    uid = game.db.append_chat_message(minister, game.state.turn, "user", "边饷如何？")
    game.db.update_chat_turn_messages(ctid, user_message_id=int(uid))
    entry_id = an.dismiss_from_audience(
        game.db, minister, night_id=night_id, origin_chat_turn_id=int(ctid),
        state=game.state,
    )
    game.session.start_chat_turn_exit_scene(
        minister, int(ctid), int(entry_id), night_id=night_id,
    )
    game.session.persist_chat_turn_scene(game.session.join_chat_turn_scene(int(ctid)))
    game.db.persist_minister_reply(minister, game.state.turn, "臣请据实核账。", int(ctid))
    game.db.settle_story_extraction(int(ctid), night_id, [], 0)
    game.db.conn.commit()
    registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=2))
    an.close_night(
        game.db, game.state, night_id=night_id, content=game.content,
        beat_generator=fake_gen, scene_registry=registry, wait_timeout_s=0.0,
    )
    by_beat = {
        m["beat"]: m for m in an.read_night_scroll(game.db, night_id)
        if m["role"] == "scene" and m["beat"] in {"opening", "entrance", "exit", "closing"}
    }
    assert set(by_beat) == {"opening", "entrance", "exit", "closing"}
    for kind, key in (
        (BEAT_OPEN, "opening"), (BEAT_ENTER, "entrance"),
        (BEAT_EXIT, "exit"), (BEAT_CLOSE, "closing"),
    ):
        assert by_beat[key]["content"] == fake_bodies[kind]


def test_web_start_chat_turn_wires_session_beat_generator(web_game):
    """WebGame._start_chat_turn 接通 session 的 generator owner。"""
    game = web_game
    minister = _active_minister(game.db, game.content)
    ctid, _snap = game._start_chat_turn(minister)
    night_id = int(game.db.conn.execute(
        "SELECT night_id FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["night_id"])
    assert _enter_body(game.db, night_id, minister) == f"宣入{minister}入殿。"
    game.session.persist_chat_turn_scene(game.session.join_chat_turn_scene(ctid))
    enter = _enter_body(game.db, night_id, minister)
    assert enter and minister in enter and enter != f"宣入{minister}入殿。"
    assert "kind=open" in (_ledger_body(game.db, night_id, an.TAG_OPEN_NIGHT) or "")


def test_web_auto_close_uses_session_beat_generator(web_game, monkeypatch):
    """#542: Web 自动收夜走 session._beat_generator，不旁路 production_beat_generator。"""
    game = web_game
    for ctid in list(game.session._scene_registry.active_turn_ids()):
        game.session.abandon_chat_turn_scene(ctid)
    an.open_night(game.db, game.state, time_of_day="戌时", location="乾清宫")
    seen: list[str] = []
    game.session._beat_generator = (
        lambda inputs: seen.append(inputs.beat_kind) or f"session-owned-{inputs.beat_kind}"
    )
    monkeypatch.setattr(
        bo, "production_beat_generator",
        lambda _i: (_ for _ in ()).throw(AssertionError("production bypass")),
    )
    web_app._auto_close_open_night_gate_free(game, inflight_wait_s=0.0)
    assert BEAT_CLOSE in seen and an.get_open_night(game.db) is None


def test_close_night_routes_scene_through_chat_turn_registry(game, monkeypatch):
    """#542 CI2: close scene 进既有 ChatTurnSceneRegistry；无自建 Thread/phase2_errors。"""
    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state, time_of_day="戌时", location="乾清宫")
    registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=2))
    seen_turns: list[int] = []
    real_start = registry.start_close

    def _track_start(db_, state_, **kwargs):
        seen_turns.append(int(kwargs.get("chat_turn_id") or 0))
        return real_start(db_, state_, **kwargs)

    monkeypatch.setattr(registry, "start_close", _track_start)
    before = {t.ident for t in threading.enumerate() if t.ident is not None}
    an.close_night(
        db, state, night_id=int(night["id"]), content=content,
        beat_generator=_echo_generator, scene_registry=registry, wait_timeout_s=0.0,
    )
    leftover = [
        t for t in threading.enumerate()
        if t.ident not in before and t.is_alive() and not t.daemon
        and t is not threading.current_thread()
    ]
    # Registry executor workers may linger briefly; no close_night-owned Thread target.
    assert not any("close" in (t.name or "").lower() for t in leftover)
    assert seen_turns and seen_turns[0] > 0
    close_body = _ledger_body(db, night["id"], an.TAG_CLOSE_NIGHT)
    assert close_body and close_body.startswith(f"kind={BEAT_CLOSE}")
    # Beat failure path: night stays OPEN, no CLOSING residue.
    night2 = an.open_night(db, state, time_of_day="亥时", location="乾清宫")

    def _boom(_inputs):
        raise RuntimeError("registry close boom")

    with pytest.raises(RuntimeError, match="registry close boom"):
        an.close_night(
            db, state, night_id=int(night2["id"]), content=content,
            beat_generator=_boom, scene_registry=registry, wait_timeout_s=0.0,
        )
    failed = an.get_night(db, int(night2["id"]))
    assert failed["status"] == an.NIGHT_STATUS_OPEN
    assert int(failed["close_commit_cursor"] or 0) == 0


def test_advance_without_edict_auto_close_uses_caller_scene_registry(game, monkeypatch):
    """#542 CI6: session.resolve_turn 自动收夜经调用方既有 registry start_close→join 落账。"""
    from ming_sim.session import GameSession

    db, state, content = game
    night = an.open_night(db, state, time_of_day="戌时", location="乾清宫")
    night_id = int(night["id"])
    registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=2))
    seen_start: list[int] = []
    real_start = registry.start_close

    def _track_start(db_, state_, **kwargs):
        seen_start.append(int(kwargs.get("chat_turn_id") or 0))
        return real_start(db_, state_, **kwargs)

    monkeypatch.setattr(registry, "start_close", _track_start)
    beat_gen = lambda inputs: f"decree-advance-close-{inputs.beat_kind}"

    class _Stop(Exception):
        pass

    def _stop_after_close(*_a, **_k):
        raise _Stop("stop-after-auto-close")

    # 收夜后停在结算前：只钉 registry 收夜缝，不跑全链 simulator。
    # session 模块绑定 resolve_directives 名，须 patch session 侧。
    import ming_sim.session as session_mod
    monkeypatch.setattr(session_mod, "resolve_directives", _stop_after_close)

    sess = GameSession.__new__(GameSession)
    sess.db, sess.state, sess.content = db, state, content
    sess.registry = sess.llm_config = sess.agno_db = None
    sess.deaths_this_turn, sess.debuts_this_turn = [], []
    sess.last_decree = sess.last_report = ""
    sess._decree_draft_fingerprint = ()
    sess._scene_registry = registry
    sess._beat_generator = beat_gen
    sess.auto_save = lambda *a, **k: None

    with pytest.raises(_Stop, match="stop-after-auto-close"):
        sess.advance_without_decree(inflight_wait_s=0.0)

    assert seen_start and seen_start[0] > 0
    assert an.get_open_night(db) is None
    close_body = _ledger_body(db, night_id, an.TAG_CLOSE_NIGHT)
    assert close_body == f"decree-advance-close-{BEAT_CLOSE}"


def test_pre_settle_auto_close_scene_failure_keeps_night_open(game, monkeypatch):
    """#542 CI6: pre_settle 自动收夜生成失败走既有收夜失败生命周期上抛，夜保持 OPEN。"""
    from ming_sim.decree import pre_settle

    db, state, content = game
    night = an.open_night(db, state, time_of_day="亥时", location="乾清宫")
    night_id = int(night["id"])
    db.llm_config = object()
    registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=2))

    def _boom(_inputs: BeatInputs) -> str:
        raise RuntimeError("pre_settle close boom")

    monkeypatch.setattr(bo, "create_llm_beat_generator", lambda _cfg: _boom)

    with pytest.raises(RuntimeError, match="pre_settle close boom"):
        pre_settle(state, db, content=content, scene_registry=registry)

    failed = an.get_night(db, night_id)
    assert failed is not None
    assert failed["status"] == an.NIGHT_STATUS_OPEN
    assert int(failed["close_commit_cursor"] or 0) == 0
    assert _ledger_body(db, night_id, an.TAG_CLOSE_NIGHT) is None


def test_cli_exit_cleanup_failure_chains_to_scene_error(game, monkeypatch):
    """#542 CI2: _record_audience_exit cleanup 失败须链到原 scene 异常，不得 pass 吞掉。"""
    import ming_sim.cli.terminal as term
    from ming_sim.session import GameSession

    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state, time_of_day="戌时", location="乾清宫")
    an.summon_enter(db, night["id"], minister)

    def boom_exit(_inputs: BeatInputs) -> str:
        raise RuntimeError("exit scene boom")

    session = GameSession.__new__(GameSession)
    session.db, session.state, session.content = db, state, content
    session.temporary_characters = set()
    session._beat_generator = boom_exit
    session._scene_registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=2))

    real_fail = db.fail_chat_turn

    def boom_fail(ctid):
        real_fail(ctid)
        raise RuntimeError("cleanup boom")

    monkeypatch.setattr(db, "fail_chat_turn", boom_fail)
    with pytest.raises(RuntimeError, match="exit scene boom") as ei:
        term._record_audience_exit(session, minister)
    assert ei.value.__cause__ is not None
    assert "cleanup boom" in str(ei.value.__cause__)


# ── AC2：第二次宣入的组装输入含首次入殿/奏对账目 ─────────────────────


def test_second_summon_inputs_include_prior_enter_and_audience(game):
    db, state, content = game
    a = _active_minister(db, content)
    b = _active_minister(db, content, exclude={a})

    night = an.open_night(db, state, time_of_day="戌时", location="乾清宫")
    an.summon_enter(db, night["id"], a, method=an.METHOD_XUANRU, body="甲首次入殿·惶恐趋入")
    tid = db.create_chat_turn(state, a, "sa", 0, night_id=night["id"])
    mid = db.append_chat_message(a, state.turn, "minister", "臣奏：辽饷积欠三月矣。")
    db.update_chat_turn_messages(tid, minister_message_id=int(mid))

    inputs = assemble_beat_inputs(
        db, state, beat_kind=BEAT_ENTER, night_id=int(night["id"]),
        time_of_day=night["time_of_day"], location=night["location"],
        person_name=a, summon_method=an.METHOD_XUANRU,
    )
    # 首次入殿账 + 奏对回话都在输入面
    assert any("甲首次入殿" in p for p in inputs.prior_appearances)
    assert any("辽饷积欠" in p for p in inputs.prior_appearances)

    # 负向：从未入殿/奏对者，输入面无前情
    inputs_b = assemble_beat_inputs(
        db, state, beat_kind=BEAT_ENTER, night_id=int(night["id"]),
        person_name=b, summon_method=an.METHOD_XUANRU,
    )
    assert inputs_b.prior_appearances == ()


# ── AC4：组装无形式约束参数、无裸数值输入（审计断言）───────────────────


def test_beat_inputs_carry_no_form_constraint_or_naked_number(game):
    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state, time_of_day="戌时", location="乾清宫")
    inputs = assemble_beat_inputs(
        db, state, beat_kind=BEAT_ENTER, night_id=int(night["id"]),
        time_of_day=night["time_of_day"], location=night["location"],
        person_name=minister, summon_method=an.METHOD_XUANRU,
    )
    # 零形式约束：无长度/结构/格式类字段
    names = set(beat_input_field_names())
    forbidden = {"max_length", "length", "min_length", "word_limit",
                 "structure", "format", "template", "few_shot", "style_guide"}
    assert not (names & forbidden)
    # 每个字段皆 str / tuple[str]——结构性保证无裸抽象数值字段
    for name in names:
        value = getattr(inputs, name)
        assert isinstance(value, (str, tuple)), name
        if isinstance(value, tuple):
            assert all(isinstance(x, str) for x in value), name
    # P4：特征化的**来源**锁定为 minister_dossier（客观特征化，无量表轴），
    # 而非带量表轴的 character_context——结构性 source-lock，不盯自由散文关键词。
    from ming_sim.context import minister_dossier
    ch = content.characters[minister]
    assert inputs.characterization == minister_dossier(ch)
    # 未走 character_context：其引擎侧模板前缀「【人物档料】」（含忠诚/党派认同轴）不出现
    assert "【人物档料】" not in inputs.characterization


def test_generator_called_with_only_beat_inputs_no_constraints(game):
    """生成器只收一个 BeatInputs——编排层不向生成施加任何形式约束参数。"""
    db, state, content = game
    minister = _active_minister(db, content)
    seen = {}

    def recording(inputs, *args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        seen["type"] = type(inputs)
        return "x"

    an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="s", agno_runs_before=0,
        time_of_day="戌时", location="乾清宫", beat_generator=recording,
    )
    assert seen["type"] is BeatInputs
    assert seen["args"] == ()
    assert seen["kwargs"] == {}


# ── AC5：见闻真走供给接口 / 不调全知 builder / 投毒被咬住 ─────────────


def _fake_provider(tag):
    def provider(name):
        if not name:
            return {}
        return {
            "world": {"role": f"{name}独有见闻#{tag}"},
            "public_events": [],
            "events": [],
        }
    return provider


def test_enter_input_flows_from_injected_knowledge_provider(game):
    db, state, content = game
    minister = _active_minister(db, content)
    night_id, _cid = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="s", agno_runs_before=0,
        time_of_day="戌时", location="乾清宫",
        beat_generator=_echo_generator, knowledge_provider=_fake_provider("A"),
    )
    body = _enter_body(db, night_id, minister)
    # 见闻输入真来自注入的供给接口（非默认 get_character_knowledge、非全知）
    assert body and f"{minister}独有见闻#A" in body


def test_frame_beats_flow_from_provider_and_vary(game):
    """AC5：开场/收夜组装输入来自供给接口且随之变化（帧 beat 视角=常在员额首席）。"""
    db, state, content = game
    subject = an.resolve_standing_roster(db)[0]
    minister = _active_minister(db, content)

    night_id, _cid = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="s", agno_runs_before=0,
        time_of_day="戌时", location="乾清宫",
        beat_generator=_echo_generator, knowledge_provider=_fake_provider("A"),
    )
    open_a = _ledger_body(db, night_id, an.TAG_OPEN_NIGHT)
    assert f"{subject}独有见闻#A" in open_a

    _land_reply(db, state, minister, _cid, night_id)
    registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=2))
    an.close_night(
        db, state, night_id=night_id, content=content,
        beat_generator=_echo_generator, knowledge_provider=_fake_provider("A"),
        scene_registry=registry,
    )
    close_a = _ledger_body(db, night_id, an.TAG_CLOSE_NIGHT)
    assert f"{subject}独有见闻#A" in close_a

    # 换供给接口内容 → 帧 beat 输入随之变化（投毒版照喂全知只换文案会被此咬住：
    # 无视 provider 的实现产不出这份 per-character 内容）
    n2 = an.open_night(db, state, time_of_day="子时", location="文华殿")
    body_open_b = bo.generate_open_beat_body(
        db, state, time_of_day="子时", location="文华殿",
        beat_generator=_echo_generator, knowledge_provider=_fake_provider("B"),
    )
    assert f"{subject}独有见闻#B" in body_open_b
    assert "独有见闻#A" not in body_open_b
    _ = n2


def test_assembly_never_calls_omniscient_builders(game, monkeypatch):
    """审计断言：组装路径绝不调全知 builder（court_brief / 全员名册类全局块）。"""
    import ming_sim.registry as registry

    def _boom(*a, **k):
        raise AssertionError("组装路径调用了全知 builder（违 ADR 0034）")

    monkeypatch.setattr(registry, "build_court_brief", _boom)
    monkeypatch.setattr(registry, "build_court_roster", _boom)
    monkeypatch.setattr(registry, "build_court_roster_index", _boom)

    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state, time_of_day="戌时", location="乾清宫")
    # 入殿 + 帧 beat 组装都不得踩全知 builder
    inputs = assemble_beat_inputs(
        db, state, beat_kind=BEAT_ENTER, night_id=int(night["id"]),
        person_name=minister, summon_method=an.METHOD_XUANRU,
        knowledge_provider=_fake_provider("A"),
    )
    assert f"{minister}独有见闻#A" in inputs.perspectival_world
    frame = assemble_beat_inputs(
        db, state, beat_kind=BEAT_OPEN, time_of_day="戌时", location="乾清宫",
        knowledge_provider=_fake_provider("A"),
    )
    subject = an.resolve_standing_roster(db)[0]
    assert f"{subject}独有见闻#A" in frame.perspectival_world


def test_court_tension_routed_from_default_provider(game):
    """当下朝局张力经默认见闻供给接口路由（court/security 域），定性口径、无裸数值（P4）。"""
    db, state, content = game
    # 内阁大臣有 court 域见闻——朝局张力应被路由到位
    grand = next(
        n for n, ch in content.characters.items()
        if ch.office_type == "内阁"
        and db.get_character_status(n)[0] == "active"
        and getattr(ch, "power_id", "ming") == "ming"
    )
    night = an.open_night(db, state, time_of_day="戌时", location="乾清宫")
    inputs = assemble_beat_inputs(
        db, state, beat_kind=BEAT_ENTER, night_id=int(night["id"]),
        person_name=grand, summon_method=an.METHOD_XUANRU,
    )
    assert inputs.court_tension  # 非空：真被路由
    # 定性口径（满意/势力档），走 audience=True 定性轨——非裸抽象数值（P4）
    assert "满意" in inputs.court_tension or "势力" in inputs.court_tension


def test_public_layer_excludes_private_whispers(game):
    """本夜公开层账取数只含殿上公开；御前低语（读心/递话）不入侍立者取数区间（PRD R1）。"""
    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state, time_of_day="戌时", location="乾清宫")
    an.append_ledger_entry(
        db, night["id"], person_names=[minister],
        audibility=an.AUDIBILITY_PUBLIC, body="殿上明发：着户部核边饷。", tags=["明旨"],
    )
    an.append_ledger_entry(
        db, night["id"], person_names=[minister],
        audibility=an.AUDIBILITY_PRIVATE, body="王承恩御前低语：此人不可信。", tags=["递话"],
    )
    inputs = assemble_beat_inputs(
        db, state, beat_kind=BEAT_OPEN, time_of_day="戌时", location="乾清宫",
        night_id=int(night["id"]),
    )
    joined = "".join(inputs.public_layer)
    assert "着户部核边饷" in joined
    assert "此人不可信" not in joined


# ── #542 fixer eight-class tracers (PR #1192) ─────────────────────────────


def test_create_llm_beat_generator_isolates_agent_per_call(monkeypatch):
    """C1/T2: each concurrent beat must not share one sticky Agent instance."""
    import importlib.util
    import sys
    from pathlib import Path

    agents: list[object] = []

    class _FakeAgent:
        def __init__(self, **_kwargs):
            agents.append(self)

        def run(self, _prompt):
            return SimpleNamespace(content=f"agent-{id(self)}")

    monkeypatch.setattr("agno.agent.Agent", _FakeAgent)
    monkeypatch.setattr(
        "ming_sim.llm_model.create_chat_model",
        lambda *_a, **_k: object(),
    )
    monkeypatch.setattr(
        "ming_sim.llm_model.extract_agent_text",
        lambda result: str(getattr(result, "content", "") or ""),
    )

    # Fresh module load bypasses autouse offline stub on bo.create_llm_beat_generator.
    mod_name = "ming_sim._beat_orch_factory_probe"
    spec = importlib.util.spec_from_file_location(mod_name, Path(bo.__file__))
    probe = importlib.util.module_from_spec(spec)
    probe.__package__ = "ming_sim"
    sys.modules[mod_name] = probe
    assert spec.loader is not None
    spec.loader.exec_module(probe)

    gen = probe.create_llm_beat_generator(object())
    out_a = gen(BeatInputs(beat_kind=BEAT_OPEN, time_of_day="戌时"))
    out_b = gen(BeatInputs(beat_kind=BEAT_ENTER, person_name="甲"))
    assert len(agents) == 2
    assert agents[0] is not agents[1]
    assert out_a != out_b


def test_start_open_enter_releases_claim_when_discover_raises(game, monkeypatch):
    """C3/T4: discover failure must drop empty claim so same chat_turn_id can retry."""
    db, state, content = game
    minister = _active_minister(db, content)
    _nid, ctid = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="claim-release", agno_runs_before=0,
    )
    registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=2))
    calls = {"n": 0}

    def boom_discover(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("discover boom")
        return []

    monkeypatch.setattr(bo, "discover_open_enter_tasks", boom_discover)
    with pytest.raises(RuntimeError, match="discover boom"):
        registry.start_open_enter(
            db, state, minister_name=minister, chat_turn_id=ctid,
            beat_generator=_echo_generator,
        )
    assert not registry.has(ctid)
    # Same turn can re-claim after the failed discover.
    registry.start_open_enter(
        db, state, minister_name=minister, chat_turn_id=ctid,
        beat_generator=_echo_generator,
    )
    assert calls["n"] == 2
    assert registry.join(ctid) == []


def test_auto_close_entries_skip_generator_when_llm_config_missing(game, monkeypatch):
    """C5/C7: no usable LLM config → do not construct generator; session 真缝同约。"""
    from ming_sim.decree import pre_settle
    from ming_sim.session import GameSession

    db, state, content = game
    assert an.get_open_night(db) is None
    db.llm_config = None
    created = {"n": 0}
    seen_generators: list = []

    def _track(_cfg):
        created["n"] += 1
        raise AssertionError("create_llm_beat_generator must not run without config")

    def _capture_auto_close(*_a, **kwargs):
        seen_generators.append(kwargs.get("beat_generator", "missing"))
        return None

    monkeypatch.setattr(bo, "create_llm_beat_generator", _track)
    monkeypatch.setattr(an, "auto_close_open_night", _capture_auto_close)
    # Import-bound name inside decree module.
    import ming_sim.decree as decree_mod
    monkeypatch.setattr(decree_mod, "auto_close_open_night", _capture_auto_close, raising=False)

    state.turn_phase = "summoning"
    class _Stop(Exception):
        pass

    real_atomic = decree_mod.atomic_and_reload

    @contextlib.contextmanager
    def _stop_atomic(*_a, **_k):
        raise _Stop()
        yield  # pragma: no cover

    monkeypatch.setattr(decree_mod, "atomic_and_reload", _stop_atomic)
    with pytest.raises(_Stop):
        pre_settle(state, db, content=content)
    assert created["n"] == 0
    assert seen_generators and seen_generators[-1] is None

    # #1274 r1：session.resolve_turn 真缝；无 _beat_generator / llm_config 时 beat_generator=None。
    def _stop_resolve(*_a, **_k):
        raise _Stop("stop-after-session-auto-close")

    import ming_sim.session as session_mod
    monkeypatch.setattr(session_mod, "resolve_directives", _stop_resolve)
    monkeypatch.setattr(decree_mod, "atomic_and_reload", real_atomic)
    sess = GameSession.__new__(GameSession)
    sess.db, sess.state, sess.content = db, state, content
    sess.registry = sess.llm_config = sess.agno_db = None
    sess.deaths_this_turn, sess.debuts_this_turn = [], []
    sess.last_decree = sess.last_report = ""
    sess._decree_draft_fingerprint = ()
    sess._scene_registry = sess._beat_generator = None
    sess.auto_save = lambda *a, **k: None
    with pytest.raises(_Stop, match="stop-after-session-auto-close"):
        sess.advance_without_decree(inflight_wait_s=0.0)
    assert created["n"] == 0
    assert seen_generators[-1] is None


def test_enter_beat_inputs_exclude_own_placeholder_entry(game):
    """C8/T9: enter prior/public must not include the target enter entry itself."""
    db, state, content = game
    minister = _active_minister(db, content)
    night_id, ctid = an.attach_chat_turn_to_night(
        db, state, minister,
        agno_session_id="self-prior", agno_runs_before=0,
    )
    enter = next(
        e for e in an.list_ledger(db, night_id)
        if an.TAG_ENTER in (e.get("tags") or [])
        and int(e.get("origin_chat_turn_id") or 0) == int(ctid)
    )
    marker = f"SELF-ENTER-{enter['id']}"
    db.conn.execute(
        "UPDATE story_ledger_entries SET body = ? WHERE id = ?",
        (marker, int(enter["id"])),
    )
    db.conn.commit()

    tasks = bo.discover_open_enter_tasks(
        db, state, minister_name=minister, chat_turn_id=ctid,
    )
    enter_inputs = [inp for _eid, inp in tasks if inp.beat_kind == BEAT_ENTER]
    assert len(enter_inputs) == 1
    prior = "‖".join(enter_inputs[0].prior_appearances)
    public = "‖".join(enter_inputs[0].public_layer)
    assert marker not in prior
    assert marker not in public


def test_exit_beat_inputs_exclude_own_placeholder_entry(game):
    """#542 r5f C1: exit prior/public must not include this beat's own ledger placeholder."""
    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state, time_of_day="戌时", location="乾清宫")
    an.summon_enter(db, night["id"], minister)
    ctid = db.create_chat_turn(state, minister, "exit-self-prior", 0, night_id=night["id"])
    entry_id = an.dismiss_from_audience(
        db, minister, night_id=night["id"], origin_chat_turn_id=ctid, state=state,
    )
    assert entry_id
    marker = f"SELF-EXIT-{entry_id}"
    db.conn.execute(
        "UPDATE story_ledger_entries SET body = ? WHERE id = ?",
        (marker, int(entry_id)),
    )
    db.conn.commit()

    seen: list[BeatInputs] = []

    def capture(inputs: BeatInputs) -> str:
        seen.append(inputs)
        return "特征化退下旁白"

    registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=1))
    registry.start_exit(
        db, state, person_name=minister, chat_turn_id=ctid, entry_id=int(entry_id),
        night_id=int(night["id"]), beat_generator=capture,
    )
    bo.persist_chat_turn_scene(db, registry.join(ctid))
    db.conn.commit()

    assert len(seen) == 1
    prior = "‖".join(seen[0].prior_appearances)
    public = "‖".join(seen[0].public_layer)
    assert marker not in prior
    assert marker not in public


def test_stream_join_and_abandon_do_not_hold_write_gate(monkeypatch):
    """C9/T1/T10: stream success join and failure abandon wait outside write_gate."""
    join_entered = threading.Event()
    release_join = threading.Event()
    abandon_entered = threading.Event()
    release_abandon = threading.Event()
    minister = "测试大臣"

    class _RunOutput:
        def __init__(self, content: str):
            self.content = content
            self.messages = []
            self.tools = []

    class _AgentOk:
        def run(self, *_a, **_k):
            yield SimpleNamespace(event="RunContent", content="臣遵旨。")
            yield _RunOutput("臣遵旨。")

    class _AgentBoom:
        def run(self, *_a, **_k):
            raise RuntimeError("stream boom")
            yield  # pragma: no cover

    class _Session:
        temporary_characters: set = set()

        def __init__(self):
            self.content = SimpleNamespace(
                characters={minister: SimpleNamespace(name=minister)},
            )
            self.registry = SimpleNamespace(get=lambda _c: _AgentOk())
            self._character = lambda name: SimpleNamespace(name=name)
            self._start_cli_action_intent = lambda *_a, **_k: None
            self._finish_cli_action_intent = lambda *_a, **_k: None
            self.apply_cli_conversation_actions = lambda *_a, **_k: {
                "directive": None,
                "secret_order_id": 0,
                "pending_action_id": 0,
                "pending_action_failures": [],
                "directive_confirmation_ambiguous": None,
            }

        def start_chat_turn_scene(self, *_a, **_k):
            return None

        def join_chat_turn_scene(self, _ctid):
            join_entered.set()
            assert release_join.wait(2)
            return []

        def persist_chat_turn_scene(self, *_a, **_k):
            return None

        def abandon_chat_turn_scene(self, _ctid):
            abandon_entered.set()
            assert release_abandon.wait(2)

    class _DB:
        def create_chat_turn(self, *a, **k):
            return 11

        def capture_chat_rollback_snapshot(self):
            return {}

        def record_chat_turn_rollback_diffs(self, *a, **k):
            return None

        def append_chat_message(self, *a, **k):
            return 1

        def update_chat_turn_messages(self, *a, **k):
            return None

        def fail_chat_turn(self, ctid):
            return None

        def load_all_chat_history(self):
            return {}

        def get_last_active_chat_turn(self, *a, **k):
            return None

        def agno_runs_length(self, *a, **k):
            return 0

        def kv_get(self, *a, **k):
            return ""

        def list_pending_actions(self, *a, **k):
            return []

    db = _DB()
    state = SimpleNamespace(turn=1, year=1628, period=1, turn_phase="summoning")
    session = _Session()
    session.db = db
    session.state = state
    session.content = SimpleNamespace(
        characters={minister: SimpleNamespace(name=minister)},
    )
    rt = object.__new__(web_app.WebGame)
    object.__setattr__(rt, "session", session)
    object.__setattr__(rt, "chat_history", {minister: []})
    from ming_sim.session_write_queue import SessionWriteQueue
    q = SessionWriteQueue()
    object.__setattr__(rt, "_write_queue", q)
    object.__setattr__(rt, "_write_gate", q.write_gate)
    rt._runtime_write_gate = lambda: rt._write_gate
    rt._runtime_write_queue = lambda: q
    rt._persistent_chat_minister = lambda _n: True
    rt._audience_turn_in_flight = lambda _n: False
    rt._start_chat_turn = lambda _n: (11, {})
    rt._record_chat_rollback_items = lambda *_a, **_k: None
    rt._chat_payload = lambda *a, **k: {"answer": "臣遵旨。"}
    rt._spawn_extraction_trail = lambda *_a, **_k: None
    rt._trail_mindreading_after_reply = lambda *_a, **_k: None
    rt._complete_pending_write = lambda ticket=None: q.complete(ticket)
    rt._mark_pending_write = lambda key=None: q.claim(key=key or ("pending",))
    monkeypatch.setattr(
        web_app, "_audience_prompt_for_web_chat",
        lambda *_a, **_k: "prompt",
    )
    monkeypatch.setattr(web_app, "fail_if_llm_error", lambda *_a, **_k: None)
    monkeypatch.setattr(web_app, "extract_agent_text", lambda *_a, **_k: "臣遵旨。")
    monkeypatch.setattr(web_app, "_dump_llm_messages", lambda *_a, **_k: None)

    gen = rt.chat_stream(minister, "边饷如何？")
    events: list = []

    def drive():
        for item in gen:
            events.append(item)

    t = threading.Thread(target=drive)
    t.start()
    assert join_entered.wait(2), "stream never joined scene outside commit"
    assert rt._write_gate.acquire(timeout=0.3), "write_gate held during stream join"
    rt._write_gate.release()
    release_join.set()
    t.join(3)
    assert not t.is_alive()

    session.registry = SimpleNamespace(get=lambda _c: _AgentBoom())
    object.__setattr__(rt, "chat_history", {minister: []})
    gen2 = rt.chat_stream(minister, "再问边饷")
    events2: list = []

    def drive2():
        for item in gen2:
            events2.append(item)

    t2 = threading.Thread(target=drive2)
    t2.start()
    assert abandon_entered.wait(2), "stream never abandoned scene"
    assert rt._write_gate.acquire(timeout=0.3), "write_gate held during stream abandon"
    rt._write_gate.release()
    release_abandon.set()
    t2.join(3)
    assert not t2.is_alive()
    assert any(e.get("type") == "error" for e in events2)


def test_web_stream_dismiss_registers_exit_before_join_and_persists(web_game):
    """#542: stream dismiss 先登记 exit、gate 外统一 join，再与 reply 原子落账。

    现码若 join 早于 start_exit，垫位文案残留、exit future 脱轮。
    """
    game = web_game
    minister = _active_minister(game.db, game.content)
    exit_body = f"【退下旁白·特征化】{minister}告退。"
    order: list[str] = []
    join_entered = threading.Event()
    release_join = threading.Event()

    real_start_exit = game.session.start_chat_turn_exit_scene
    real_join = game.session.join_chat_turn_scene

    def tracking_start_exit(*a, **k):
        order.append("start_exit")
        return real_start_exit(*a, **k)

    def tracking_join(ctid):
        order.append("join")
        join_entered.set()
        assert release_join.wait(2), "join was not released"
        return real_join(ctid)

    game.session.start_chat_turn_exit_scene = tracking_start_exit
    game.session.join_chat_turn_scene = tracking_join
    game.session._beat_generator = lambda inputs: (
        exit_body if inputs.beat_kind == BEAT_EXIT else f"body-{inputs.beat_kind}"
    )

    # 类名须为 RunOutput：_chat_stream_payload 按 type(event).__name__ 识别终事件。
    class RunOutput:
        def __init__(self):
            self.content = "臣告退。"
            self.messages = []
            self.tools = [
                SimpleNamespace(tool_name="dismiss_minister", result="__dismiss__"),
            ]

    class _DismissAgent:
        def run(self, *_a, **_k):
            yield SimpleNamespace(event="RunContent", content="臣告退。")
            yield RunOutput()

    game.session.registry.get = lambda _c: _DismissAgent()

    ctid, snap = game._start_chat_turn(minister)
    night_id = int(game.db.conn.execute(
        "SELECT night_id FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["night_id"])
    # 入殿后大臣须在场，dismiss 才能落 exit 垫位。
    if minister not in an.present_names_at(game.db, night_id):
        an.summon_enter(game.db, night_id, minister)

    gate = game._runtime_write_gate()
    # 占住 write_gate：证明 join 等待在 gate 外（与 C9/T1/T10 同纪律）。
    assert gate.acquire(timeout=0.2)
    try:
        result_box: dict = {}

        def run_stream():
            try:
                result_box["payload"] = game._chat_stream_payload(
                    minister, "卿且退下", int(ctid), snap, int(game.state.turn),
                    lambda _d: None, write_gate=gate,
                )
            except BaseException as exc:
                result_box["exc"] = exc

        worker = threading.Thread(target=run_stream)
        worker.start()
        assert join_entered.wait(2), "stream never reached join"
        # join 已进入且 start_exit 必先于 join；gate 仍被本测试持有 → join 不在 gate 内。
        assert order == ["start_exit", "join"], order
        assert gate.locked()
        release_join.set()
        gate.release()
        worker.join(3)
        assert not worker.is_alive()
    finally:
        if gate.locked():
            gate.release()
        release_join.set()

    assert "exc" not in result_box, result_box.get("exc")
    payload = result_box["payload"]
    assert payload["court_action"] == "dismiss"
    assert payload["answer"] == "臣告退。"

    exit_rows = [
        e for e in an.list_ledger(game.db, night_id)
        if an.TAG_EXIT in (e.get("tags") or []) and minister in (e.get("person_names") or [])
    ]
    assert exit_rows, "dismiss must write exit ledger"
    assert exit_rows[-1]["body"] == exit_body
    # 成功路径不得残留脱轮 future。
    assert not game.session._scene_registry.has(int(ctid))


def test_web_stream_exit_overlaps_unfinished_reply_after_dismiss_tool(web_game):
    """#542 C1: dismiss tool 事件出现后立刻 start_exit，与尚未结束的回话流真实重叠。

    seam = WebGame._chat_stream_payload（流式 tool 事件 → scene registry）。
    串行（等回流完再 start_exit）则 barrier 永不汇合、测试失败。
    """
    game = web_game
    minister = _active_minister(game.db, game.content)
    exit_body = f"【退下旁白·重叠】{minister}告退。"
    both_in_flight = threading.Barrier(2, timeout=2.0)
    exit_started = threading.Event()
    reply_still_open = threading.Event()
    order: list[str] = []

    def tracking_exit_gen(inputs: BeatInputs) -> str:
        if inputs.beat_kind != BEAT_EXIT:
            return f"body-{inputs.beat_kind}"
        order.append("exit_gen")
        exit_started.set()
        both_in_flight.wait()  # 与回话流后半段汇合 → 证明同时在飞
        return exit_body

    game.session._beat_generator = tracking_exit_gen

    class ToolCallCompletedEvent:
        """agno 流式 tool 完成事件形态（web_app 按 .tool 读取）。"""

        def __init__(self, tool):
            self.event = "ToolCallCompleted"
            self.tool = tool

    class RunOutput:
        def __init__(self):
            self.content = "臣告退。"
            self.messages = []
            self.tools = [
                SimpleNamespace(tool_name="dismiss_minister", result="__dismiss__"),
            ]

    class _OverlapDismissAgent:
        def run(self, *_a, **_k):
            yield SimpleNamespace(event="RunContent", content="臣")
            yield ToolCallCompletedEvent(
                SimpleNamespace(tool_name="dismiss_minister", result="__dismiss__"),
            )
            # dismiss 已暴露后回话流仍未结束——此处必须与 exit_gen 重叠
            reply_still_open.set()
            order.append("reply_tail")
            both_in_flight.wait()
            yield SimpleNamespace(event="RunContent", content="告退。")
            yield RunOutput()

    game.session.registry.get = lambda _c: _OverlapDismissAgent()

    ctid, snap = game._start_chat_turn(minister)
    night_id = int(game.db.conn.execute(
        "SELECT night_id FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["night_id"])
    if minister not in an.present_names_at(game.db, night_id):
        an.summon_enter(game.db, night_id, minister)

    payload = game._chat_stream_payload(
        minister, "卿且退下", int(ctid), snap, int(game.state.turn),
        lambda _d: None,
    )
    assert payload["court_action"] == "dismiss"
    assert payload["answer"] == "臣告退。"
    assert exit_started.is_set(), "exit never started"
    assert reply_still_open.is_set(), "reply stream never reached post-dismiss tail"
    # exit 已 start 时回话尾仍在飞：两者都进入 barrier 才会放行
    assert "exit_gen" in order and "reply_tail" in order
    exit_rows = [
        e for e in an.list_ledger(game.db, night_id)
        if an.TAG_EXIT in (e.get("tags") or []) and minister in (e.get("person_names") or [])
    ]
    assert exit_rows and exit_rows[-1]["body"] == exit_body
    assert not game.session._scene_registry.has(int(ctid)), "scene must join before open interaction"


def test_session_chat_exit_overlaps_inflight_action_intent(game):
    """#542 C1: 非流式 tools 含 dismiss 后立刻 start_exit，与仍在飞 action_intent 重叠。

    seam = GameSession.chat（run_output.tools → scene registry，先于 finish action_intent）。
    串行（先 join action_intent 再 start_exit）则 barrier 永不汇合、测试失败。
    """
    from concurrent.futures import ThreadPoolExecutor
    from ming_sim.session import GameSession

    db, state, content = game
    minister = _active_minister(db, content)
    night_id, ctid = an.attach_chat_turn_to_night(
        db, state, minister, agno_session_id="exit-overlap-ai", agno_runs_before=0,
    )
    if minister not in an.present_names_at(db, night_id):
        an.summon_enter(db, night_id, minister)

    both_in_flight = threading.Barrier(2, timeout=2.0)
    intent_started = threading.Event()
    exit_started = threading.Event()
    exit_body = f"【退下旁白·意图重叠】{minister}告退。"
    intent_exec = ThreadPoolExecutor(max_workers=1)

    def slow_exit(inputs: BeatInputs) -> str:
        if inputs.beat_kind != BEAT_EXIT:
            return f"body-{inputs.beat_kind}"
        exit_started.set()
        both_in_flight.wait()
        return exit_body

    def start_intent(_character, _message):
        def _classify():
            intent_started.set()
            both_in_flight.wait()
            return {"kind": "none"}

        return intent_exec.submit(_classify)

    class _DismissAgent:
        def run(self, _message):
            return SimpleNamespace(
                content="臣告退。",
                tools=[SimpleNamespace(tool_name="dismiss_minister", result="__dismiss__")],
            )

    class _Reg:
        def get(self, _c):
            return _DismissAgent()

    sess = GameSession.__new__(GameSession)
    sess.db, sess.state, sess.content = db, state, content
    sess.registry = _Reg()
    sess.llm_config = SimpleNamespace(channel="cli")
    sess.temporary_characters = set()
    sess._beat_generator = slow_exit
    sess._scene_registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=2))
    sess._audience_prompt_for_message = lambda message, *a, **k: message
    sess._start_cli_action_intent = start_intent
    # 真 finish：会 future.result()——若 start_exit 在其后，exit 无法与 intent 汇合
    sess._finish_cli_action_intent = GameSession._finish_cli_action_intent.__get__(sess, GameSession)

    try:
        result = GameSession.chat(sess, minister, "卿且退下", chat_turn_id=int(ctid))
        assert result.court_action == "dismiss"
        assert intent_started.is_set() and exit_started.is_set()
        generated = sess.join_chat_turn_scene(int(ctid))
        sess.persist_chat_turn_scene(generated)
        db.conn.commit()
        exit_rows = [
            e for e in an.list_ledger(db, night_id)
            if an.TAG_EXIT in (e.get("tags") or []) and minister in (e.get("person_names") or [])
        ]
        assert exit_rows and exit_rows[-1]["body"] == exit_body
        assert not sess._scene_registry.has(int(ctid))
    finally:
        intent_exec.shutdown(wait=False, cancel_futures=True)


def test_failed_turn_does_not_consume_opening_and_clears_enter_placeholder(game):
    """C12/T13/T16: failed turns lose opening eligibility; enter placeholder is cleared."""
    db, state, content = game
    minister = _active_minister(db, content)
    night_id, ctid = an.attach_chat_turn_to_night(
        db, state, minister,
        agno_session_id="fail-open", agno_runs_before=0,
    )
    assert _enter_body(db, night_id, minister)
    db.fail_chat_turn(int(ctid))
    # Enter bound to failed turn must not remain.
    assert _enter_body(db, night_id, minister) is None

    # Next live turn is the first non-failed timeline turn → rediscover opening.
    # Minister no longer present after failed enter cleanup, so re-attach creates enter.
    _nid2, ctid2 = an.attach_chat_turn_to_night(
        db, state, minister,
        agno_session_id="fail-open-2", agno_runs_before=0,
    )
    tasks = bo.discover_open_enter_tasks(
        db, state, minister_name=minister, chat_turn_id=ctid2,
    )
    kinds = {inp.beat_kind for _eid, inp in tasks}
    assert BEAT_OPEN in kinds
    assert BEAT_ENTER in kinds


def test_close_start_sync_failure_fails_scaffold_and_keeps_night_open(game, monkeypatch):
    """#542 r6e: start_close 在 create scaffold 后同步抛错，调用方仍持 ctid，abandon/fail/OPEN 必跑到。"""
    db, state, content = game
    night = an.open_night(db, state, time_of_day="戌时", location="乾清宫")
    night_id = int(night["id"])
    registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=2))

    def boom_start(_db, _state, **_kwargs):
        raise RuntimeError("start_close sync boom")

    monkeypatch.setattr(registry, "start_close", boom_start)

    with pytest.raises(RuntimeError, match="start_close sync boom"):
        an.close_night(
            db, state, night_id=night_id, content=content,
            beat_generator=_echo_generator, scene_registry=registry,
            wait_timeout_s=0.0,
        )

    failed = an.get_night(db, night_id)
    assert failed is not None
    assert failed["status"] == an.NIGHT_STATUS_OPEN
    assert int(failed["close_commit_cursor"] or 0) == 0
    assert not registry.active_turn_ids()
    rows = db.conn.execute(
        "SELECT status FROM chat_turns WHERE night_id = ? AND minister_name = '收夜'",
        (night_id,),
    ).fetchall()
    assert rows, "scaffold must have been created before start_close threw"
    assert all(str(r["status"]) == "failed" for r in rows)


def test_close_scene_early_phase1_failure_drains_and_reopens(game, monkeypatch):
    """T15: exception after close start through phase-1 must drain/fail scaffold and OPEN."""
    db, state, content = game
    night = an.open_night(db, state, time_of_day="戌时", location="乾清宫")
    night_id = int(night["id"])
    registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=2))
    started = threading.Event()
    release = threading.Event()

    def slow_close(_inputs: BeatInputs) -> str:
        started.set()
        assert release.wait(2)
        return "收夜旁白"

    # crash_after_step=1 fires at end of office commit (phase-1), after start_close.
    with pytest.raises(an.AudienceNightError, match="收夜提交崩溃注入"):
        an.close_night(
            db, state, night_id=night_id, content=content,
            beat_generator=slow_close, scene_registry=registry,
            wait_timeout_s=0.0, crash_after_step=an.CLOSE_STEP_COMMIT_OFFICE,
        )
    release.set()
    failed = an.get_night(db, night_id)
    assert failed["status"] == an.NIGHT_STATUS_OPEN
    assert int(failed["close_commit_cursor"] or 0) == 0
    assert not registry.active_turn_ids()
    # Owned scaffold must not remain generating forever.
    rows = db.conn.execute(
        "SELECT status FROM chat_turns WHERE night_id = ? AND minister_name = '收夜'",
        (night_id,),
    ).fetchall()
    assert rows
    assert all(str(r["status"]) == "failed" for r in rows)


def test_cli_scaffold_exit_failure_deletes_exit_ledger(game, monkeypatch):
    """C11/T12: scaffold-owned CLI exit failure deletes exit placeholder then fails turn."""
    import ming_sim.cli.terminal as term
    from ming_sim.session import GameSession

    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state, time_of_day="戌时", location="乾清宫")
    an.summon_enter(db, night["id"], minister)
    night_id = int(night["id"])

    def boom_exit(_inputs: BeatInputs) -> str:
        raise RuntimeError("scaffold exit boom")

    session = GameSession.__new__(GameSession)
    session.db, session.state, session.content = db, state, content
    session.temporary_characters = set()
    session._beat_generator = boom_exit
    session._scene_registry = bo.ChatTurnSceneRegistry(ThreadPoolExecutor(max_workers=2))

    with pytest.raises(RuntimeError, match="scaffold exit boom"):
        term._record_audience_exit(session, minister)

    exit_rows = [
        e for e in an.list_ledger(db, night_id)
        if an.TAG_EXIT in (e.get("tags") or [])
    ]
    assert exit_rows == [], exit_rows
    # Minister remains present because scaffold exit rolled back.
    assert minister in an.present_names_at(db, night_id)
