"""#498 召对夜 × web 真实入口 tracer（只 fake LLM 边界，走真实 FastAPI 路由 / SSE）。

真实 WebGame + 真实 FastAPI 路由（httpx.ASGITransport），只把 LLM 边界换成 canned：
- 大臣对话 = 假 agent.run 的 canned 流；
- 月末链的模型边界以 canned 结果替代；pre-settle / 推进回合仍走生产路径；
  判官 verdict 固定为逐案 promulgated，非真实判官行为。

外部行为断言（HTTP/SSE + DB 末态），不钉内部 helper 结构。

覆盖：
- 完成回话 SSE 入档→颁诏 SSE：真实结算核收夜、推进 turn、持久化（AC8/AC10 happy）；
- 挂起在飞（真实并发 /chat/stream ASGI 请求）→ 真实 /decree/issue/stream in-flight fail-closed
  SSE、夜开、turn 不变、chat 轮仍 generating；放行后 chat SSE 收到 done（AC10）；
- 同步退朝端点 offload：阻塞在飞等待期间 async ticker 持续前进（真实 ASGI）；
- 等 gate 期间相位翻到亲裁（TOCTOU）→ 持锁内权威复查经真实 /chat/stream SSE 拒、零新夜/新 chat 轮；
- 已成案旨无公开拟诏、改稿、删除工作面。
"""

from __future__ import annotations

import asyncio
import json
import threading

import httpx
import pytest
from ming_sim.exceptions import LLMUnavailable
from ming_sim.audience_translate import _default_translate_runner as _real_audience_translate_runner
from tests.conftest import stub_audience_translate, stub_scene_agent

_POLICY_FIELDS = {
    "dossier_action_type": "policy",
    "target_kind": "issue",
    "target_id": "test-policy",
}

import web_app
import ming_sim.agents as agents_mod
import ming_sim.decree as decree_mod
import ming_sim.session as session_mod
from ming_sim import audience_night as an
from ming_sim.models import TurnPhase
from ming_sim.session import ChatTurnResult


# ── canned LLM 边界（唯一 fake）────────────────────────────────────────
class _RunContent:
    event = "RunContent"

    def __init__(self, content: str):
        self.content = content


class RunCompletedEvent:  # 类名须为 RunOutput / RunCompletedEvent（web_app 按 type(event).__name__ 判终帧）
    content = ""
    tools: list = []


class _FakeAgent:
    """canned 大臣回话流。started：yield 首帧后置位（=生成已开始，prologue 已建在飞轮）；
    allow：非空则在首帧与终帧之间阻塞（挂起在飞），待置位再收尾。"""

    def __init__(self, started: threading.Event | None = None, allow: threading.Event | None = None,
                 answer: str = "臣已知悉，边饷当速清。"):
        self.started = started
        self.allow = allow
        self.answer = answer

    def run(self, *args, **kwargs):
        # 接受 stream 旗（生产 scene transport 同形）
        yield _RunContent(self.answer)
        if self.started is not None:
            self.started.set()
        if self.allow is not None:
            self.allow.wait()
        yield RunCompletedEvent()

    def get_last_run_output(self):
        return None


def _fake_settlement_llm(monkeypatch, *, narrative="本月邸报：边饷已清。", delta=None):
    """替换月链中的拟诏、世界段、转译和邸报模型调用；其余结算路径真跑。"""
    monkeypatch.setattr(
        decree_mod, "llm_promulgation_verdicts",
        lambda dossiers, _state, **_kwargs: [
            {"dossier_id": row["id"], "decision": "promulgated"}
            for row in dossiers
        ],
    )
    monkeypatch.setattr(session_mod, "write_decree_with_agno", lambda *a, **k: "奉天承运，诏曰……")
    monkeypatch.setattr(
        "ming_sim.month_chain.run_world_segment_text", lambda *a, **k: narrative,
    )
    monkeypatch.setattr(
        "ming_sim.month_chain.run_gazette_text",
        lambda *a, **k: ("邸报", narrative),
    )
    monkeypatch.setattr(
        "ming_sim.month_translate.translate_month_segment",
        lambda *a, **k: {"effects": {}},
    )
    monkeypatch.setattr(
        "ming_sim.decree_forecast.produce_forecast_product",
        lambda *_a, **_k: {
            "verdict": {"decision": "promulgated"},
            "declaration": {"effects": {}},
            "questions": None,
            "forecast_text": narrative,
            "visible_refs": {},
        },
    )


@pytest.fixture
def web_game(tmp_path, monkeypatch, _offline_scene_beat_generator):
    """真实 WebGame（新档、temp DB）；构造即不连 LLM，仅 runtime 与动作级 LLM 边界中和。

    显式 opt-in `_offline_scene_beat_generator`：在 GameSession.__init__ 前注入确定性
    beat factory，避免 sk-test 401；实例仍走生产 ChatTurnSceneRegistry。

    允许 canned seam（定义真源 / runtime lookup，本 fixture 唯一 fake 面）：

    - #1842：收夜不再起 endorsement-only 批

    - web_app.run_highlight_judge → 回话 done 后高亮判官（#544；禁 sk-test 真网）
    - _fake_settlement_llm：decree 判官/推演/抽取/拟诏
    - load_runtime_llm 配置中和
    - registry.get → 大臣回话流（_FakeAgent，按测例挂起）
    不 patch auto-close / 结算核。
    """
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})

    # #544 / #1353 r6：高亮判官同属回话后 LLM 边界——离线中和，禁 sk-test 打真 OpenAI。
    monkeypatch.setattr(web_app, "run_highlight_judge", lambda **_k: [])
    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", game)
    yield game
    try:
        game.session.close()
    except Exception:
        pass


def _active_minister(game) -> str:
    for name, ch in game.content.characters.items():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if game.db.get_character_status(name)[0] == "active":
            return name
    raise AssertionError("no active ming minister")


def _count(db, table: str) -> int:
    return int(db.conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=web_app.app), base_url="http://t")


def test_persisted_reply_before_translation_admission_has_no_retry_button(web_game):
    """A complete reply is not an exhausted translation until the job actually fails."""
    game = web_game
    night = an.open_night(game.db, game.state, location="乾清宫", time_of_day="夜")
    ctid = game.db.create_chat_turn(
        game.state, "殿上", "sess", 0, night_id=int(night["id"]),
    )
    game.db.persist_minister_reply("殿上", int(game.state.turn), "臣领旨。", ctid)

    async def scenario():
        async with _client() as client:
            before = (await client.get("/api/audience/chat")).json()
            retry = await client.post("/api/audience/translation/retry", json={"chat_turn_id": ctid})
            return before, retry

    before, retry = asyncio.run(scenario())
    assert before["translation_retries"] == []
    assert retry.status_code == 404




@pytest.mark.parametrize("night_status", [an.NIGHT_STATUS_CLOSING, an.NIGHT_STATUS_CLOSED])
def test_pending_translation_retries_original_round_after_night_seal(web_game, monkeypatch, night_status):
    """A sealed night keeps its failed source round repairable before month advance."""
    game = web_game
    night = an.open_night(game.db, game.state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    ctid = game.db.create_chat_turn(game.state, "殿上", "sess", 0, night_id=nid)
    game.db.persist_minister_reply("殿上", int(game.state.turn), "臣领旨。", ctid)
    game.db.mark_story_extraction_pending(ctid)
    an._set_night_fields(game.db, nid, status=night_status)
    stub_audience_translate(monkeypatch)

    async def retry():
        async with _client() as client:
            return await client.post("/api/audience/translation/retry", json={"chat_turn_id": ctid})

    response = asyncio.run(retry())
    assert response.status_code == 200
    assert response.json()["extract_status"] == "done"
    assert game.pending_translation_retries(chat_turn_id=ctid) == []
    assert [row["body"] for row in game.db.conn.execute(
        "SELECT body FROM story_ledger_entries WHERE source_chat_turn_id=?", (ctid,),
    )] == ["臣领旨。"]
    assert an.get_night(game.db, nid)["status"] == night_status


@pytest.mark.parametrize("failure", ["code", "429", "503", "timeout"])
def test_translation_failure_retry_and_undo_through_audience_http(web_game, monkeypatch, request, failure, tmp_path):
    """The source turn owns the failed translation across retry and retraction."""
    game = web_game
    stub_scene_agent(monkeypatch, _FakeAgent(answer="臣领旨。"))

    calls: list[float] = []
    waits: list[float] = []
    clock = {"now": 0.0}
    retry_waiting = threading.Event()
    resume_retry = threading.Event()
    if failure == "code":
        def exhausted(_prompt, _config):
            raise RuntimeError("translation unavailable")
        stub_audience_translate(monkeypatch, exhausted)
    else:
        from dataclasses import replace
        import ming_sim.cli_backend as cli_backend
        import ming_sim.llm_config as llm_config_mod
        import ming_sim.llm_transport as transport
        path = tmp_path / "runtime_llm.json"
        path.write_text(json.dumps({"transport": {"max_attempts": 5, "retry_interval_seconds": 1}}), encoding="utf-8")
        monkeypatch.setattr(llm_config_mod, "RUNTIME_LLM_PATH", str(path))
        game.session.llm_config = replace(game.session.llm_config, channel="cli", cli_runner="agy")

        def wait(seconds):
            waits.append(seconds)
            if len(waits) == 1:
                retry_waiting.set()
                assert resume_retry.wait(3), "translation retry was not released"
            clock["now"] += seconds

        def failed_call(_runner, _prompt, **_kwargs):
            calls.append(clock["now"])
            if failure == "timeout":
                raise LLMUnavailable("timeout", code="llm_timeout")
            raise LLMUnavailable("provider failed", code="llm_run_error", status_code=int(failure))

        monkeypatch.setattr(transport, "_sleep_retry_interval", wait)
        monkeypatch.setattr(cli_backend, "_dispatch_cli_runner", failed_call)
        stub_audience_translate(monkeypatch, _real_audience_translate_runner)

    async def send():
        async with _client() as client:
            return await client.post("/api/audience/chat/stream", json={"message": "边饷如何？"})

    async def inspect():
        async with _client() as client:
            return (await client.get("/api/audience/chat")).json()

    async def inspect_scroll():
        async with _client() as client:
            return (await client.get("/api/audience/scroll")).json()

    response = asyncio.run(send())
    assert response.status_code == 200
    if failure in {"503", "timeout"}:
        try:
            assert retry_waiting.wait(3)
            early = asyncio.run(inspect())
            assert len(early["translation_retries"]) == 1
            assert all(not row["retryable"] for row in early["translation_retries"])
        finally:
            resume_retry.set()
    assert game._runtime_write_queue().wait_idle()

    failed = asyncio.run(inspect())
    if failure != "code":
        assert calls, failed
    assert len(failed["translation_retries"]) == 1
    ctid = failed["translation_retries"][0]["chat_turn_id"]
    assert failed["translation_retries"][0]["retryable"] is True
    assert failed["translation_retries"][0]["error_pack_path"]
    scroll = asyncio.run(inspect_scroll())
    assert scroll["translation_retries"] == failed["translation_retries"]
    if failure != "code":
        assert calls == ([0.0] if failure == "429" else [0.0, 5.0, 10.0])
        assert waits == ([] if failure == "429" else [5.0, 5.0])
    if failure == "code":
        source_positions = [
            (index, item["role"], item["chat_turn_id"])
            for index, item in enumerate(failed["history"])
            if item.get("chat_turn_id") == ctid
        ]
        assert source_positions
        async def fail_again():
            async with _client() as client:
                return await client.post(
                    "/api/audience/translation/retry", json={"chat_turn_id": ctid},
                )

        failed_retry = asyncio.run(fail_again())
        assert failed_retry.status_code == 200
        assert failed_retry.json()["retryable"] is True
        game.session.close()
        game = web_app.WebGame(fresh=False)
        request.addfinalizer(game.session.close)
        monkeypatch.setattr(web_app, "web_game", game)
        reopened = asyncio.run(inspect())
        assert [
            (index, item["role"], item["chat_turn_id"])
            for index, item in enumerate(reopened["history"])
            if item.get("chat_turn_id") == ctid
        ] == source_positions
        assert [row["chat_turn_id"] for row in reopened["translation_retries"]] == [ctid]
        assert game._runtime_write_queue().wait_idle()
    turns_before_retry = _count(game.db, "chat_turns")

    if failure == "code":
        started = threading.Event()
        release = threading.Event()

        def delayed(_prompt, _config):
            started.set()
            assert release.wait(3), "late translation was not released"
            return {}

        stub_audience_translate(monkeypatch, delayed)

        async def undo_during_retry():
            async with _client() as client:
                retry_task = asyncio.create_task(client.post(
                    "/api/audience/translation/retry", json={"chat_turn_id": ctid},
                ))
                try:
                    assert await asyncio.to_thread(started.wait, 3)
                    undo = await asyncio.wait_for(client.post("/api/audience/chat/undo"), 2)
                finally:
                    release.set()
                retry = await retry_task
                retracted = (await client.get("/api/audience/chat")).json()
                stale = await client.post(
                    "/api/audience/translation/retry", json={"chat_turn_id": ctid},
                )
                return undo, retry, retracted, stale

        undo, retry, retracted, stale = asyncio.run(undo_during_retry())
        assert undo.status_code == 200
        assert retry.status_code == 200
        assert retracted["translation_retries"] == []
        assert all(item.get("chat_turn_id") != ctid for item in retracted["history"])
        assert _count(game.db, "chat_turns") == turns_before_retry
        assert game.db.conn.execute(
            "SELECT status FROM chat_turns WHERE id=?", (ctid,),
        ).fetchone()["status"] == "undone"
        assert game.db.conn.execute(
            "SELECT COUNT(*) AS c FROM story_ledger_entries WHERE source_chat_turn_id=?",
            (ctid,),
        ).fetchone()["c"] == 0
        assert stale.status_code == 404
        return

    stub_audience_translate(monkeypatch)

    async def retry_and_undo():
        async with _client() as client:
            retry = await client.post("/api/audience/translation/retry", json={"chat_turn_id": ctid})
            healed = (await client.get("/api/audience/chat")).json()
            turns_after_retry = _count(game.db, "chat_turns")
            source_segments_after_retry = game.db.conn.execute(
                "SELECT body FROM story_ledger_entries WHERE source_chat_turn_id=?",
                (ctid,),
            ).fetchall()
            undo = await client.post("/api/audience/chat/undo")
            retracted = (await client.get("/api/audience/chat")).json()
            stale = await client.post("/api/audience/translation/retry", json={"chat_turn_id": ctid})
            return retry, healed, turns_after_retry, source_segments_after_retry, undo, retracted, stale

    retry, healed, turns_after_retry, source_segments_after_retry, undo, retracted, stale = asyncio.run(retry_and_undo())
    assert retry.status_code == 200
    assert healed["translation_retries"] == []
    assert turns_after_retry == turns_before_retry
    assert [row["body"] for row in source_segments_after_retry] == ["臣领旨。"]
    assert undo.status_code == 200
    assert retracted["translation_retries"] == []
    assert game.db.conn.execute(
        "SELECT COUNT(*) AS c FROM story_ledger_entries WHERE source_chat_turn_id=?", (ctid,),
    ).fetchone()["c"] == 0
    assert stale.status_code == 404


def _parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    for block in text.strip().split("\n\n"):
        cur: dict = {}
        for line in block.splitlines():
            if line.startswith("event:"):
                cur["event"] = line[len("event:"):].strip()
            elif line.startswith("data:"):
                cur["data"] = line[len("data:"):].strip()
        if cur:
            events.append(cur)
    return events


async def _await_event_or_task(ev: threading.Event, task: asyncio.Task) -> None:
    """成功事件或 worker 终态均可唤醒；worker 异常原样传播，不把失败藏成挂起。

    事件与 task 同时终态时仍消费 task 异常——不得因 ev 先置位而吞掉 worker 失败。
    """
    while not ev.is_set() and not task.done():
        await asyncio.sleep(0)
    if task.done():
        exc = task.exception()
        if exc is not None:
            raise exc
        if not ev.is_set():
            raise AssertionError("worker finished without expected success event")
        return
    # ev 已置位且 task 仍在跑（如 started 后 hang on allow）——成功会合。


async def _drain_tasks(*tasks: asyncio.Task) -> None:
    """排空全部任务并消费异常；永不向外抛，避免 finally 收尾替换主体原错。"""
    for task in tasks:
        if task is None:
            continue
        if not task.done():
            try:
                await task
            except BaseException:
                pass
            continue
        if task.cancelled():
            continue
        # 已完成：仍消费 exception，避免「never retrieved」且不抛出。
        task.exception()


async def _wait_for(pred) -> None:
    """轮询真实状态直至成立；永久不成立 → CI job 终线。"""
    while not pred():
        await asyncio.sleep(0)


async def _start_hanging_chat(game, client, minister, monkeypatch):
    """经真实 /chat/stream ASGI 请求起一轮回话并卡在生成中（在飞）。
    返回 (chat_task, allow)：chat_task 是仍在跑的 SSE 请求；置位 allow 后回话收尾。

    责任移交：成功返回后由调用方持有 allow/task 全持有期释放。
    移交前（等 started）失败：task 正常失败已终态；取消等非终态路径仍可能挂在 allow，
    故本 helper 在 raise 前 release+drain，不把半移交资源留给调用方。
    """
    started, allow = threading.Event(), threading.Event()
    agent = _FakeAgent(started=started, allow=allow)
    # #1842：殿上 scene_chat 双桩——与 registry 同注入 agent
    stub_scene_agent(monkeypatch, agent)
    task = asyncio.create_task(
        client.post("/api/audience/chat/stream", json={"message": "边饷如何？"}))
    try:
        # 生成已开始，或 chat worker 已终态（失败须传播，不得只等 started）。
        await _await_event_or_task(started, task)
    except BaseException:
        # 移交前失败：释放 allow 并排空；已终态则 drain 只消费，不替换原错。
        allow.set()
        await _drain_tasks(task)
        raise
    return task, allow


# ── ① AC10 成功等待分支：在飞时触发颁诏 → 回话在超时内落档 → 收夜后颁诏、推进回合 ──


# ── ② 对话内应允候选：收夜提交即准旨，月末玩家流零二次准驳 ─────────────






# ── ③ #1353 K10a：挂起在飞不按 elapsed 造 409；工人终态后过月续跑 ──


# ── ③ 同步退朝端点 offload 不冻结 event loop（真实 ASGI + 并发在飞 + ticker）──────


# ── ④ TOCTOU：等 gate 期间相位翻到亲裁 → 持锁内权威复查经真实 /chat/stream SSE 拒 ──
def test_asgi_phase_flip_while_waiting_gate_rejected(web_game, monkeypatch):
    game = web_game
    minister = _active_minister(game)
    # 装好 fake LLM：删掉持锁内复查时，失败只会因非法开夜/建轮（而非缺 API key 401）。
    _agent = _FakeAgent()
    stub_scene_agent(monkeypatch, _agent)
    game.state.turn_phase = TurnPhase.SUMMONING.value  # 锁前快速查通过
    nights0, turns0 = _count(game.db, "audience_nights"), _count(game.db, "chat_turns")

    async def scenario():
        async with _client() as client:
            game._write_gate.acquire()  # 扮演结算 worker 持真实 write gate
            try:
                chat_task = asyncio.create_task(
                    client.post("/api/audience/chat/stream", json={"message": "边饷如何？"}))
                # 等真实 pending-write 态（锁前查之后、抢 gate 之前）——不替换私有方法，只读真实态
                await _wait_for(lambda: getattr(game, "_pending_writes_count", 0) > 0)
                game.state.turn_phase = TurnPhase.AWAITING_DECISION.value  # 结算翻相位
            finally:
                game._write_gate.release()  # 放真实 gate → chat 抢到后持锁内权威复查
            return _parse_sse((await chat_task).text)

    events = asyncio.run(scenario())

    # 相位拒绝：SSE error + 零新夜/新 chat（wire 无 phase code；不改生产协议）。
    assert events and events[-1]["event"] == "error"
    assert _count(game.db, "audience_nights") == nights0
    assert _count(game.db, "chat_turns") == turns0


# ── ⑤ 已成案旨无公开拟诏、改稿、删除工作面 ─────────────────────────────
def test_asgi_dossiered_directive_has_no_retired_review_surface(web_game):
    game = web_game
    directive_id = game.db.add_directive(
        game.state, None, "着户部核边饷", "手动新增",
        dossier_payload=_POLICY_FIELDS,
    )
    game.db.ensure_dossiers_for_draft_directives(game.state)

    registered_paths = {route.path for route in web_app.app.routes}
    assert "/api/decree/write" not in registered_paths

    async def scenario():
        async with _client() as client:
            return (
                await client.patch(
                    f"/api/directives/{directive_id}", json={"text": "改稿"},
                ),
                await client.delete(f"/api/directives/{directive_id}"),
                await client.get("/api/game/state"),
            )

    edit, delete, state = asyncio.run(scenario())
    assert edit.status_code == 404
    assert delete.status_code == 409
    body = state.json()
    # 候选列表仍滤掉已成案（list_directives 语义不变）
    assert directive_id not in {row["id"] for row in body["directives"]}
    # #1764：已成案·待盖玺只读投影（0051 proposed）；不另立事实源
    cased = body.get("cased_directives") or []
    match = next((row for row in cased if int(row["id"]) == int(directive_id)), None)
    assert match is not None
    assert int(match["dossier_id"]) > 0
    assert match["dossier_status"] == "proposed"
    assert match["source"] == "手动新增"
    assert "着户部核边饷" in str(match["text"])

def test_asgi_inflight_reply_lands_then_issue_closes_and_advances(web_game, monkeypatch):
    """AC10「回话完成入档后才收夜再颁诏」：#1353 过月屏障等 chat 整轮票清零后收夜再颁诏。

    顺序：挂起 chat（持票）→ issue 进屏障等票 → 放行回话落档/放票 → 收夜→颁诏推进。
    """
    game = web_game
    minister = _active_minister(game)
    _fake_settlement_llm(monkeypatch)
    turn_before = int(game.state.turn)

    # 观测队列：issue 进 barrier 时 inflight>0；放行后票清、收夜可走。
    observed_ticket_inflight = threading.Event()
    observed_ticket_clear = threading.Event()
    q = game._runtime_write_queue()
    real_wait_prior = q.wait_prior

    def observe_wait_prior(ticket):
        if q.inflight_count() > 1:  # barrier 票 + chat 票
            observed_ticket_inflight.set()
        result = real_wait_prior(ticket)
        # wait_prior 返回 = 该票 priors 已清。后序 trail（seq>barrier）可仍 open（P5），
        # 不得用总 inflight<=1 判清——只核无 seq < barrier 的 prior。
        if observed_ticket_inflight.is_set():
            with q._cond:
                priors = [seq for seq in q._open if seq < ticket.seq]
            if not priors:
                observed_ticket_clear.set()
        return result

    monkeypatch.setattr(q, "wait_prior", observe_wait_prior)

    async def scenario():
        async with _client() as chat_client, _client() as issue_client:
            # 取得 chat 所有权后即进入释放责任区间——观察/断言/写入均在 try 内。
            chat_task, allow = await _start_hanging_chat(game, chat_client, minister, monkeypatch)
            issue_task = None
            try:
                night = an.get_open_night(game.db)
                # 持久化行确认在飞
                assert game.db.conn.execute(
                    "SELECT status FROM chat_turns WHERE night_id=?", (night["id"],)).fetchone()["status"] == "generating"
                assert int(game._pending_writes_count) >= 1
                # 预置 draft 候选（应允/默认同意路径）；draft 而非 pending，回话 epilogue 无待确认项、
                # 不触发确认抽取 LLM。
                game.db.upsert_pending_directive(
                    game.state.turn, minister, payload={
                        "text": "着户部核边饷", "actor": minister,
                        "dossier_action_type": "policy",
                        "target_kind": "issue", "target_id": "border-pay",
                    })
                game.db.commit_pending_actions(game.state, kind_filter="directive")

                issue_task = asyncio.create_task(issue_client.post("/api/decree/issue/stream", json={}))
                # 屏障见票或 issue 终态；失败不挂死。
                await _await_event_or_task(observed_ticket_inflight, issue_task)
                allow.set()                                   # 放行回话落档 + 放票
                await _await_event_or_task(observed_ticket_clear, issue_task)

                chat_resp = await chat_task
                issue_resp = await issue_task
                return night, _parse_sse(chat_resp.text), _parse_sse(issue_resp.text)
            finally:
                # 持有 chat allow：先释放，再排空已创建 sibling；收尾不抛，保留主体原错。
                allow.set()
                await _drain_tasks(chat_task, issue_task)

    night, chat_events, issue_events = asyncio.run(scenario())

    # 回话 done 先于流结束；end 表示回话尾随写入已 join。
    assert chat_events[-1]["event"] == "end"
    # 回话真实入档 + 对话轮升 active（#1849 reopen：殿上唯一入口）
    assert game.db.conn.execute(
        "SELECT COUNT(*) AS c FROM chat_messages WHERE minister_name=? AND role='minister'",
        ("殿上",)).fetchone()["c"] == 1
    assert game.db.conn.execute(
        "SELECT status FROM chat_turns WHERE night_id=?", (night["id"],)).fetchone()["status"] == "active"
    # 颁诏成功（done）+ 真实结算核：收夜封夜 + 推进回合 + 持久化
    assert issue_events[-1]["event"] == "done"
    assert an.get_night(game.db, night["id"])["status"] == "closed"
    assert int(game.state.turn) == turn_before + 1
    assert int(game.db.load_state().turn) == turn_before + 1


def test_night_approved_directive_closes_into_month_end_without_second_review(web_game, monkeypatch):
    game = web_game
    minister = _active_minister(game)
    _fake_settlement_llm(monkeypatch)
    turn_before = int(game.state.turn)
    text = "着户部核边饷，限三月完报"

    # #502 的真实「对话内已应允」持久态：候选仍 pending，但归属本夜且 night_approved=1；
    # 本 tracer 从该依赖交付态起，经玩家真实收夜/月末入口验证后半链，不直接 commit。
    night = an.open_night(game.db, game.state, location="乾清宫", time_of_day="夜")
    directive_id = game.db.stage_directive_candidate(
        game.state.turn, minister,
        payload={**_POLICY_FIELDS, "text": text, "actor": minister},
    )
    assert an.mark_actions_night_approved(game.db, [directive_id], night_id=int(night["id"])) == 1

    async def scenario():
        async with _client() as client:
            return _parse_sse((await client.post("/api/decree/issue/stream", json={})).text)

    events = asyncio.run(scenario())

    assert events[-1]["event"] == "done"
    assert not ({"confirm", "reject", "pending_review"} & {event["event"] for event in events})
    assert an.get_night(game.db, int(night["id"]))["status"] == "closed"
    assert int(game.state.turn) == turn_before + 1
    assert not game.db.list_night_approved_pending(int(night["id"]), kind="directive")
    rows = game.db.conn.execute(
        "SELECT status, text FROM turn_directives WHERE turn=?",
        (turn_before,),
    ).fetchall()
    assert any(str(row["text"] or "") == text for row in rows), rows



def test_legacy_pending_only_advances_to_durable_dossier_without_review_api(web_game, monkeypatch):
    """Legacy saves with only turn_directives.status=pending remain operable at the
    same end-turn service seam; retired player confirm/reject routes stay absent."""
    game = web_game
    minister = _active_minister(game)
    _fake_settlement_llm(monkeypatch)
    turn_before = int(game.state.turn)
    night = an.open_night(game.db, game.state, location="乾清宫", time_of_day="夜")
    directive_id = game.db.add_directive(
        game.state, None, "着户部核边饷", "legacy-chat", actor=minister,
        status="pending", dossier_payload={**_POLICY_FIELDS},
    )
    dossiered_id = game.db.add_directive(
        game.state, None, "已成案旨", "legacy-approved", actor=minister,
        status="draft", dossier_payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "already-dossiered",
        },
    )
    game.db._ensure_directive_dossier(
        game.state, dossiered_id, "已成案旨", {
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "already-dossiered",
        },
    )

    registered_paths = {route.path for route in web_app.app.routes}
    assert "/api/directives/{directive_id}/confirm" not in registered_paths
    assert "/api/directives/{directive_id}/reject" not in registered_paths

    async def scenario():
        async with _client() as client:
            state = (await client.get("/api/game/state")).json()
            advance = await client.post("/api/decree/advance_without_edict")
            return state, advance

    state_payload, response = asyncio.run(scenario())
    assert dossiered_id not in {row["id"] for row in state_payload["directives"]}
    # #1855：夜未收时真 HTTP 状态口投影 audience（非手造轻壳）
    assert state_payload["reopen_landing"] == "audience"
    assert response.status_code == 200
    assert an.get_night(game.db, int(night["id"]))["status"] == "closed"
    dossier = game.db.get_dossier_for_directive(directive_id)
    assert dossier is not None
    assert int(game.db.load_state().turn) == turn_before + 1
    # #1855：推进后落本月盘面（复用本案真实过月，不另造 mock 伪全链）
    assert game.state_payload()["reopen_landing"] == "month"


def test_asgi_hanging_chat_issue_waits_for_worker_terminal(web_game, monkeypatch):
    """#1353 K10a：在飞回话挂起时颁诏等待工人终态，不按墙钟伪造 in_flight 409。

    顺序：挂起 chat → 起 issue（阻塞等在飞）→ 放行 chat → issue 消费终态续跑。
    """
    game = web_game
    minister = _active_minister(game)
    _fake_settlement_llm(monkeypatch)
    monkeypatch.setattr("ming_sim.audience_night.DEFAULT_IN_FLIGHT_POLL_S", 0.02)
    turn_before = int(game.state.turn)

    # 观测：issue 真进屏障并见到 chat 票后，才断言「未伪造成 elapsed 409」。
    observed_ticket_inflight = threading.Event()
    q = game._runtime_write_queue()
    real_wait_prior = q.wait_prior

    def observe_wait_prior(ticket):
        if q.inflight_count() > 1:  # barrier 票 + chat 票
            observed_ticket_inflight.set()
        return real_wait_prior(ticket)

    monkeypatch.setattr(q, "wait_prior", observe_wait_prior)

    async def scenario():
        async with _client() as chat_client, _client() as issue_client:
            # 取得 chat 所有权后即进入释放责任区间——观察/断言均在 try 内。
            chat_task, allow = await _start_hanging_chat(game, chat_client, minister, monkeypatch)
            issue_task = None
            try:
                night = an.get_open_night(game.db)
                assert game.db.conn.execute(
                    "SELECT status FROM chat_turns WHERE night_id=?",
                    (night["id"],),
                ).fetchone()["status"] == "generating"
                # 预置 draft（与 AC10 成功案同缝）：工人终态后须能真实续跑到 done，
                # 不得靠「任意 error」冒充非伪造 in-flight。
                game.db.upsert_pending_directive(
                    game.state.turn, minister, payload={
                        "text": "着户部核边饷", "actor": minister,
                        "dossier_action_type": "policy",
                        "target_kind": "issue", "target_id": "border-pay",
                    })
                game.db.commit_pending_actions(game.state, kind_filter="directive")

                issue_task = asyncio.create_task(
                    issue_client.post("/api/decree/issue/stream", json={})
                )
                await _await_event_or_task(observed_ticket_inflight, issue_task)
                assert not issue_task.done(), (
                    "issue must wait for chat ticket, not forge elapsed 409"
                )

                allow.set()
                chat_resp = await chat_task
                issue_resp = await issue_task
                return night, _parse_sse(issue_resp.text), _parse_sse(chat_resp.text)
            finally:
                # 持有 chat allow：先释放，再排空已创建 sibling；收尾不抛，保留主体原错。
                allow.set()
                await _drain_tasks(chat_task, issue_task)

    night, issue_events, chat_events = asyncio.run(scenario())
    assert night is not None
    assert chat_events[-1]["event"] == "end"
    # 非伪造 in-flight：等待期间 issue 未完成（scenario 内）；工人终态后续跑成功。
    assert issue_events[-1]["event"] == "done", issue_events
    assert an.get_night(game.db, night["id"])["status"] == "closed"
    assert int(game.state.turn) == turn_before + 1
    assert int(game.db.load_state().turn) == turn_before + 1


def test_sync_advance_endpoint_does_not_stall_event_loop(web_game, monkeypatch):
    game = web_game
    minister = _active_minister(game)
    _fake_settlement_llm(monkeypatch)
    # 在飞挂起：退朝经队列屏障等 chat 票（#1353 K10a 不造 409）
    monkeypatch.setattr("ming_sim.audience_night.DEFAULT_IN_FLIGHT_POLL_S", 0.02)

    async def scenario():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        async with _client() as chat_client, _client() as adv_client:
            # 取得 chat 所有权后即进入释放责任区间；sibling 尚未创建时按实际存在收尾。
            chat_task, allow = await _start_hanging_chat(game, chat_client, minister, monkeypatch)
            t = None
            adv_task = None
            try:
                t = asyncio.create_task(ticker())
                adv_task = asyncio.create_task(
                    adv_client.post("/api/decree/advance_without_edict")
                )
                # 等待期间 event loop 须继续跑 ticker（端点已 offload）
                while ticks < 5:
                    await asyncio.sleep(0)
                mid_ticks = ticks
                allow.set()
                await chat_task
                resp = await adv_task
                return mid_ticks, ticks, resp.status_code
            finally:
                # 持有 chat allow：先释放，再排空已创建 sibling；收尾不抛，保留主体原错。
                allow.set()
                if t is not None:
                    t.cancel()
                await _drain_tasks(chat_task, adv_task, t)

    mid_ticks, ticks, status = asyncio.run(scenario())
    assert mid_ticks >= 5, f"event loop 被同步端点冻结（mid_ticks={mid_ticks}）"
    assert ticks >= mid_ticks
    # #1353 K10a：工人终态后继续，不按在飞 elapsed 造 409
    assert status == 200, f"advance after chat terminal expected 200, got {status}"
