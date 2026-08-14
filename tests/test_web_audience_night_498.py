"""#498 召对夜 × web 真实入口 tracer（只 fake LLM 边界，走真实 FastAPI 路由 / SSE）。

真实 WebGame + 真实 FastAPI 路由（httpx.ASGITransport），只把 LLM 边界换成 canned：
- 大臣对话 = 假 agent.run 的 canned 流；
- 月末推演 = 只假 simulator/extractor 这层 LLM 种子，resolve_directives 的 pre-settle /
  结算核 / 推进回合全部真跑；判官 verdict 仍固定为逐案 promulgated，非真实判官行为。

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

_POLICY_FIELDS = {
    "dossier_action_type": "policy",
    "target_kind": "issue",
    "target_id": "test-policy",
}

import web_app
import ming_sim.agents as agents_mod
import ming_sim.decree as decree_mod
import ming_sim.memories as memories_mod
import ming_sim.session as session_mod
from ming_sim import audience_night as an
from ming_sim.models import TurnPhase


class _CannedExtractor:
    """#501 叙事抽取员离线边界：回话尾随 / 收夜前 drain 会调它——默认抽出空 facts
    （不改本文件既有账本/收夜断言，仅把新 LLM 边界中和成离线，与 verify_llm 同理）。"""

    def run(self, _material):
        class _R:
            content = '{"facts":[]}'
        return _R()


class _CannedEndorsementExtractor:
    """#612 夜级 endorsement-only 离线边界：默认空绑定（不改既有收夜断言）。"""

    def run(self, _material):
        class _R:
            content = '{"endorsements":[]}'
        return _R()


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
        yield _RunContent(self.answer)
        if self.started is not None:
            self.started.set()
        if self.allow is not None:
            assert self.allow.wait(5.0), "fake agent 等待放行超时"
        yield RunCompletedEvent()

    def get_last_run_output(self):
        return None


def _fake_settlement_llm(monkeypatch, *, narrative="本月邸报：边饷已清。", delta=None):
    """只 fake 月末推演的 simulator/extractor **LLM 调用**；resolve_directives 结算核（含
    build_extractor_shared_context 这类确定性上下文装配）真跑。"""
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "llm_promulgation_verdicts",
        lambda dossiers, _state, **_kwargs: [
            {"dossier_id": row["id"], "decision": "promulgated"}
            for row in dossiers
        ],
    )
    monkeypatch.setattr(decree_mod, "simulate_season_with_payload",
                        lambda *a, **k: (narrative, k.get("simulator_payload") or {}))
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "extract_scores_by_modules_with_agno",
                        lambda *a, **k: (delta or {}, "out", "in"))
    monkeypatch.setattr(session_mod, "write_decree_with_agno", lambda *a, **k: "奉天承运，诏曰……")
    # 章节记忆的唯一 LLM 输出边界（memories.run_agent_text 仅被 record_chapter_memory 调用）；
    # record_chapter_memory 与其确定性装配仍真跑。
    monkeypatch.setattr(memories_mod, "run_agent_text",
                        lambda *a, **k: '{"body": "本月边饷已清，暗流暗涌。", "tags": ["边饷"]}')


@pytest.fixture
def web_game(tmp_path, monkeypatch):
    """真实 WebGame（新档、temp DB、离线 LLM）。仅 verify_llm 与 runtime 配置被中和。"""
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    monkeypatch.setattr(session_mod, "verify_llm_available", lambda cfg: None)
    # #501：叙事抽取是每条召对夜回话的新 LLM 边界（回话尾随 + 收夜前 drain）——离线中和，
    # 默认抽空 facts，避免本 #498 用例走真实网络。
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda *a, **k: _CannedExtractor())
    monkeypatch.setattr(
        agents_mod, "create_endorsement_extractor_agent",
        lambda *a, **k: _CannedEndorsementExtractor(),
    )
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


async def _await_event(ev: threading.Event, timeout: float = 5.0) -> None:
    """从 async 上下文等一个 threading.Event（不阻塞 event loop）。"""
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, ev.wait, timeout)
    assert ok, "等待信号超时"


async def _wait_for(pred, timeout: float = 3.0) -> None:
    """轮询真实状态直至成立（等真实条件、非固定时序假设）。"""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while not pred():
        assert loop.time() < deadline, "条件未在期限内成立"
        await asyncio.sleep(0)


async def _start_hanging_chat(game, client, minister):
    """经真实 /chat/stream ASGI 请求起一轮回话并卡在生成中（在飞）。
    返回 (chat_task, allow)：chat_task 是仍在跑的 SSE 请求；置位 allow 后回话收尾。"""
    started, allow = threading.Event(), threading.Event()
    game.session.registry.get = lambda ch: _FakeAgent(started=started, allow=allow)
    task = asyncio.create_task(
        client.post(f"/api/ministers/{minister}/chat/stream", json={"message": "边饷如何？"}))
    await _await_event(started)  # 生成已开始 = prologue 已建 generating 在飞轮
    return task, allow


# ── ① AC10 成功等待分支：在飞时触发颁诏 → 回话在超时内落档 → 收夜后颁诏、推进回合 ──
def test_asgi_inflight_reply_lands_then_issue_closes_and_advances(web_game, monkeypatch):
    """AC10「回话完成入档后才收夜再颁诏」：颁诏在真实在飞等待中观测到 generating 轮，
    回话在正超时内落档→在飞清空→颁诏续跑收夜、真实结算核推进回合。"""
    game = web_game
    minister = _active_minister(game)
    _fake_settlement_llm(monkeypatch)
    monkeypatch.setattr("ming_sim.audience_night.DEFAULT_IN_FLIGHT_WAIT_S", 5.0)  # 正超时
    turn_before = int(game.state.turn)

    # 透明观察者：只调真实 list_in_flight_chat_turns、原样返回，同时记录两处转变——
    #   observed_inflight：首个非空真实结果（颁诏 worker 真观测到持久 generating 在飞轮）；
    #   observed_clear：在飞被观测过之后，某次真实结果转空（=颁诏 worker 亲眼看到在飞清空）。
    # 要求放行回话后 observed_clear 才接受颁诏完成 → 咬死 AC10 顺序：回话落档→在飞清空→收夜→颁诏。
    # 「列一次即返回」的 waiter 收夜全程持 write_gate、回话 epilogue 抢不到 gate 落档，其 list 恒非空 →
    # observed_clear 永不置 → 测试按超时红（非仅最终态）。
    observed_inflight = threading.Event()
    observed_clear = threading.Event()
    real_list = an.list_in_flight_chat_turns

    def observe_inflight(*args, **kwargs):
        rows = real_list(*args, **kwargs)
        if rows:
            observed_inflight.set()
        elif observed_inflight.is_set():
            observed_clear.set()
        return rows

    monkeypatch.setattr("ming_sim.audience_night.list_in_flight_chat_turns", observe_inflight)

    async def scenario():
        async with _client() as chat_client, _client() as issue_client:
            chat_task, allow = await _start_hanging_chat(game, chat_client, minister)
            night = an.get_open_night(game.db)
            # 持久化行确认在飞
            assert game.db.conn.execute(
                "SELECT status FROM chat_turns WHERE night_id=?", (night["id"],)).fetchone()["status"] == "generating"
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
            await _await_event(observed_inflight)  # 颁诏 worker 真观测到 generating 在飞轮后
            allow.set()                             # 才在正超时内放行 → 回话落档
            await _await_event(observed_clear)      # 颁诏 worker 又亲眼看到在飞清空（收夜前）

            chat_resp = await chat_task
            issue_resp = await issue_task
            return night, _parse_sse(chat_resp.text), _parse_sse(issue_resp.text)

    night, chat_events, issue_events = asyncio.run(scenario())

    # #499：done 先于读心可见，end 才是终态终止事件。
    assert chat_events[-1]["event"] == "end"
    # 回话真实入档 + 对话轮升 active
    assert game.db.conn.execute(
        "SELECT COUNT(*) AS c FROM chat_messages WHERE minister_name=? AND role='minister'",
        (minister,)).fetchone()["c"] == 1
    assert game.db.conn.execute(
        "SELECT status FROM chat_turns WHERE night_id=?", (night["id"],)).fetchone()["status"] == "active"
    # 颁诏成功（done）+ 真实结算核：收夜封夜 + 推进回合 + 持久化
    assert issue_events[-1]["event"] == "done"
    assert an.get_night(game.db, night["id"])["status"] == "closed"
    assert int(game.state.turn) == turn_before + 1
    assert int(game.db.load_state().turn) == turn_before + 1


# ── ② 对话内应允候选：收夜提交即准旨，月末玩家流零二次准驳 ─────────────
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
    settled = game.db.list_directives_by_turn(turn_before)
    assert any(d["text"] == text for d in settled), "收夜应将已应允候选直接提交并进入月末结算"


def test_web_issue_close_binds_endorsements_gate_free_after_same_night_dossier(web_game, monkeypatch):
    """Real Web settlement tracer: ordinary facts may already be done; close creates
    draft dossiers then runs one gate-free endorsement-only batch. While the
    endorsement agent blocks, concurrent Web chat/story/stage/approve all freeze;
    first-batch failure reopens OPEN and restores admission; retry closes."""
    game = web_game
    minister = _active_minister(game)
    _fake_settlement_llm(monkeypatch)
    night = an.open_night(game.db, game.state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    chat_turn_id = game.db.create_chat_turn(
        game.state, minister, "朕准此旨。", 0, night_id=night_id,
    )
    game.db.persist_minister_reply(minister, int(game.state.turn), "臣愿作保。", chat_turn_id)
    # Scheme A: ordinary story extraction is immediate (already done before close).
    game.db.conn.execute(
        "UPDATE chat_turns SET extract_status='done' WHERE id=?", (chat_turn_id,),
    )
    game.db.conn.commit()
    directive_id = game.db.stage_directive_candidate(
        game.state.turn, minister,
        payload={**_POLICY_FIELDS, "text": "着户部核边饷", "actor": minister},
    )
    game.db.mark_pending_night_approved([directive_id], night_id=night_id)
    calls = []
    gate_free = []
    no_db_tx = []
    entered = threading.Event()
    release = threading.Event()
    turns_before = game.db.conn.execute(
        "SELECT COUNT(*) AS c FROM chat_turns WHERE night_id=?", (night_id,),
    ).fetchone()["c"]
    pending_before = game.db.conn.execute(
        "SELECT COUNT(*) AS c FROM pending_actions WHERE night_id=?", (night_id,),
    ).fetchone()["c"]
    ledger_before = game.db.conn.execute(
        "SELECT COUNT(*) AS c FROM story_ledger_entries WHERE night_id=?", (night_id,),
    ).fetchone()["c"]

    class _TracingEndorsementExtractor:
        def run(self, materials):
            payload = json.loads(materials)
            calls.append(payload)
            # Outer web write gate must not be held during endorsement LLM.
            acquired = game._runtime_write_gate().acquire(blocking=False)
            gate_free.append(acquired)
            if acquired:
                game._runtime_write_gate().release()
            no_db_tx.append(game.db.conn.in_transaction is False)
            entered.set()
            assert release.wait(8.0), "endorsement agent release timeout"
            if len(calls) == 1:
                raise RuntimeError("endorsement boom under CLOSING freeze")
            candidates = payload["可背书案卷"]
            assert len(candidates) == 1
            dossier_id = candidates[0]["ref"]["dossier_id"]
            assert game.db.get_decree_dossier(dossier_id) is not None
            return _RunContent(json.dumps({"endorsements": []}, ensure_ascii=False))

    monkeypatch.setattr(
        agents_mod, "create_endorsement_extractor_agent",
        lambda *a, **k: _TracingEndorsementExtractor(),
    )
    # Real chat path uses registry agent; keep canned so freeze is the only outcome.
    game.session.registry.get = lambda ch: _FakeAgent(answer="臣另有奏。")

    async def first_fail_scenario():
        async with _client() as issue_client, _client() as chat_client:
            issue_task = asyncio.create_task(
                issue_client.post("/api/decree/issue/stream", json={})
            )
            assert await asyncio.to_thread(entered.wait, 8.0)
            # chat / story / stage / approve — all refuse under CLOSING.
            chat_resp = await chat_client.post(
                f"/api/ministers/{minister}/chat/stream",
                json={"message": "另议边饷？"},
            )
            chat_events = _parse_sse(chat_resp.text)
            assert any(ev.get("event") == "error" for ev in chat_events), chat_events
            assert any(
                ev.get("event") == "error" and "收夜中" in str(ev.get("data") or "")
                for ev in chat_events
            ), chat_events
            with pytest.raises(an.AudienceNightError) as story_exc:
                an.append_ledger_entry(
                    game.db, night_id, body="偷渡故事账", tags=["试"],
                )
            assert story_exc.value.code == "night_closing"
            with pytest.raises(an.AudienceNightError) as stage_exc:
                game.db.stage_directive_candidate(
                    game.state.turn, minister,
                    payload={**_POLICY_FIELDS, "text": "偷渡应允", "actor": minister,
                             "target_id": "closing-freeze"},
                )
            assert stage_exc.value.code == "night_closing"
            with pytest.raises(an.AudienceNightError) as approve_exc:
                an.mark_actions_night_approved(game.db, [directive_id], night_id=night_id)
            assert approve_exc.value.code == "night_closing"
            assert an.get_night(game.db, night_id)["status"] == an.NIGHT_STATUS_CLOSING
            assert game.db.conn.execute(
                "SELECT COUNT(*) AS c FROM chat_turns WHERE night_id=?", (night_id,),
            ).fetchone()["c"] == turns_before
            assert game.db.conn.execute(
                "SELECT COUNT(*) AS c FROM pending_actions WHERE night_id=?", (night_id,),
            ).fetchone()["c"] == pending_before
            assert game.db.conn.execute(
                "SELECT COUNT(*) AS c FROM story_ledger_entries WHERE night_id=?", (night_id,),
            ).fetchone()["c"] == ledger_before
            release.set()
            return _parse_sse((await issue_task).text)

    fail_events = asyncio.run(first_fail_scenario())
    assert any(ev.get("event") == "error" for ev in fail_events), fail_events
    reopened = an.get_night(game.db, night_id)
    assert reopened["status"] == an.NIGHT_STATUS_OPEN
    assert int(reopened["close_commit_cursor"] or 0) == 0
    # Failure OPEN restores player admission (stage/story no longer night_closing).
    restored_id = game.db.stage_directive_candidate(
        game.state.turn, minister,
        payload={**_POLICY_FIELDS, "text": "失败后可再暂存", "actor": minister,
                 "target_id": "after-reopen"},
    )
    assert int(restored_id) > 0
    story_id = an.append_ledger_entry(
        game.db, night_id, body="失败重开后故事账", tags=["试"],
    )
    assert int(story_id) > 0

    # Second close attempt succeeds through the same real Web seam.
    entered.clear()
    release = threading.Event()

    async def retry_scenario():
        async with _client() as issue_client:
            issue_task = asyncio.create_task(
                issue_client.post("/api/decree/issue/stream", json={})
            )
            assert await asyncio.to_thread(entered.wait, 8.0)
            release.set()
            return _parse_sse((await issue_task).text)

    events = asyncio.run(retry_scenario())
    assert events[-1]["event"] == "done", events
    assert len(calls) == 2
    assert gate_free == [True, True]
    assert no_db_tx == [True, True]
    assert game.db.get_story_extract_status(chat_turn_id) == "done"
    closed = an.get_night(game.db, night_id)
    assert closed["status"] == an.NIGHT_STATUS_CLOSED
    assert an.night_endorsement_bound(closed)


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
    assert response.status_code == 200
    assert an.get_night(game.db, int(night["id"]))["status"] == "closed"
    closes = [
        row for row in an.list_ledger(game.db, int(night["id"]))
        if an.TAG_CLOSE_NIGHT in (row.get("tags") or [])
    ]
    assert len(closes) == 1
    dossier = game.db.get_dossier_for_directive(directive_id)
    assert dossier is not None
    assert int(game.db.load_state().turn) == turn_before + 1


# ── ③ AC10 fail-closed：真实并发 /chat/stream 挂起在飞 → /decree/issue/stream in-flight 拒 ──
def test_asgi_hanging_chat_makes_issue_fail_closed(web_game, monkeypatch):
    game = web_game
    minister = _active_minister(game)
    monkeypatch.setattr("ming_sim.audience_night.DEFAULT_IN_FLIGHT_WAIT_S", 0.0)

    async def scenario():
        async with _client() as chat_client, _client() as issue_client:
            chat_task, allow = await _start_hanging_chat(game, chat_client, minister)
            night = an.get_open_night(game.db)
            turn_before = int(game.state.turn)

            issue_resp = await issue_client.post("/api/decree/issue/stream", json={})
            issue_events = _parse_sse(issue_resp.text)
            mid_status = an.get_night(game.db, night["id"])["status"]
            mid_turn = int(game.state.turn)
            chat_row = game.db.conn.execute(
                "SELECT status FROM chat_turns WHERE night_id=?", (night["id"],)).fetchone()["status"]

            allow.set()
            chat_resp = await chat_task
            return issue_events, night, turn_before, mid_status, mid_turn, chat_row, chat_resp.text

    issue_events, night, turn_before, mid_status, mid_turn, chat_row, chat_text = asyncio.run(scenario())

    assert night is not None
    # 颁诏经 SSE 报「在飞」in-flight fail-closed
    assert issue_events[-1]["event"] == "error"
    assert "在飞" in (issue_events[-1].get("data") or "")
    assert mid_status == "open"          # 夜保持开
    assert mid_turn == turn_before       # turn 不变
    assert chat_row == "generating"      # 在飞轮仍在
    # 放行后回话正常收尾（#499：end 才是终态终止事件）
    assert _parse_sse(chat_text)[-1]["event"] == "end"


# ── ③ 同步退朝端点 offload 不冻结 event loop（真实 ASGI + 并发在飞 + ticker）──────
def test_sync_advance_endpoint_does_not_stall_event_loop(web_game, monkeypatch):
    game = web_game
    minister = _active_minister(game)
    # 在飞挂起，使退朝端点在 _await_audience_inflight_clear 阻塞约 0.4s（同步等待）
    monkeypatch.setattr("ming_sim.audience_night.DEFAULT_IN_FLIGHT_WAIT_S", 0.4)
    monkeypatch.setattr("ming_sim.audience_night.DEFAULT_IN_FLIGHT_POLL_S", 0.02)

    async def scenario():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        async with _client() as chat_client, _client() as adv_client:
            chat_task, allow = await _start_hanging_chat(game, chat_client, minister)
            t = asyncio.create_task(ticker())
            resp = await adv_client.post("/api/decree/advance_without_edict")
            t.cancel()
            allow.set()
            await chat_task
            return ticks, resp.status_code

    ticks, status = asyncio.run(scenario())
    assert ticks >= 5, f"event loop 被同步端点冻结（ticks={ticks}）"
    assert status == 409  # 在飞超时 fail-closed


# ── ④ TOCTOU：等 gate 期间相位翻到亲裁 → 持锁内权威复查经真实 /chat/stream SSE 拒 ──
def test_asgi_phase_flip_while_waiting_gate_rejected(web_game):
    game = web_game
    minister = _active_minister(game)
    # 装好 fake LLM：删掉持锁内复查时，失败只会因非法开夜/建轮（而非缺 API key 401）。
    game.session.registry.get = lambda ch: _FakeAgent()
    game.state.turn_phase = TurnPhase.SUMMONING.value  # 锁前快速查通过
    nights0, turns0 = _count(game.db, "audience_nights"), _count(game.db, "chat_turns")

    async def scenario():
        async with _client() as client:
            game._write_gate.acquire()  # 扮演结算 worker 持真实 write gate
            try:
                chat_task = asyncio.create_task(
                    client.post(f"/api/ministers/{minister}/chat/stream", json={"message": "边饷如何？"}))
                # 等真实 pending-write 态（锁前查之后、抢 gate 之前）——不替换私有方法，只读真实态
                await _wait_for(lambda: getattr(game, "_pending_writes_count", 0) > 0)
                game.state.turn_phase = TurnPhase.AWAITING_DECISION.value  # 结算翻相位
            finally:
                game._write_gate.release()  # 放真实 gate → chat 抢到后持锁内权威复查
            return _parse_sse((await chat_task).text)

    events = asyncio.run(scenario())

    assert events and events[-1]["event"] == "error"
    assert "结算" in (events[-1].get("data") or "") or "亲裁" in (events[-1].get("data") or "")
    # 外部 DB 末态：零新夜 / 新 chat 轮
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
    assert directive_id not in {row["id"] for row in state.json()["directives"]}
