"""#1235 T2 — 点即入 + 未了续跑 + 真失败另形（ADR 0149）。

接缝（票庭 r1 / 票面三义）：
1. 点即入：真实颁布/退朝入口受理后状态口立即 settlement_display + 点击前四键
   （capture 在 await/close 之前；T1 载体，禁第二 flag）
2. 未了续跑：未落账回话（已回话待 story 抽取）退朝/颁布 → 不 409 打回；
   服务端按既有收夜→结算次序自动接续至月完或 awaiting
3. 真失败另形：drain/收夜真失败 → fail-closed 人话 + 展示态退出
   （清快照；终态 ≠ 未了在办）
4. AC3 不回归：settling 恢复 / pending_decisions 下发不被本刀弄断
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from types import SimpleNamespace

import httpx
import pytest

import web_app
import ming_sim.agents as agents_mod
import ming_sim.decree as decree_mod
import ming_sim.memories as memories_mod
import ming_sim.mindreading as mindreading_mod
import ming_sim.session as session_mod
from ming_sim import audience_night as an
from ming_sim.models import TurnPhase
from ming_sim.month_open_snapshot import MONTH_OPEN_KEYS


# ── 轻量 canned 边界（与 #498 web tracer 同形，仅中和 LLM）────────────────


class _CannedExtractor:
    def run(self, _material):
        class _R:
            content = '{"facts":[]}'
        return _R()


class _BoomExtractor:
    def run(self, _material):
        raise RuntimeError("抽取持续失败·真失败注入")


class _CannedEndorsementExtractor:
    def run(self, _material):
        class _R:
            content = '{"endorsements":[]}'
        return _R()


class _CannedMindreadingAgent:
    def run(self, _material):
        class _R:
            content = "近臣低声：此人心里另有盘算。"
        return _R()


def _fake_settlement_llm(monkeypatch, *, narrative="本月邸报：边饷已清。", delta=None):
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "llm_promulgation_verdicts",
        lambda dossiers, _state, **_kwargs: [
            {"dossier_id": row["id"], "decision": "promulgated"}
            for row in dossiers
        ],
    )
    monkeypatch.setattr(
        decree_mod, "simulate_season_with_payload",
        lambda *a, **k: (narrative, k.get("simulator_payload") or {}),
    )
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: (delta or {}, "out", "in"),
    )
    monkeypatch.setattr(session_mod, "write_decree_with_agno", lambda *a, **k: "奉天承运，诏曰……")
    monkeypatch.setattr(
        memories_mod, "run_agent_text",
        lambda *a, **k: '{"body": "本月边饷已清，暗流暗涌。", "tags": ["边饷"]}',
    )


@pytest.fixture
def web_game(tmp_path, monkeypatch, _offline_scene_beat_generator):
    """真实 WebGame；LLM 边界 canned。与 #498 fixture 同形。"""
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda *a, **k: _CannedExtractor())
    monkeypatch.setattr(
        agents_mod, "create_endorsement_extractor_agent",
        lambda *a, **k: _CannedEndorsementExtractor(),
    )
    monkeypatch.setattr(
        mindreading_mod, "create_mindreading_agent",
        lambda *a, **k: _CannedMindreadingAgent(),
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


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_app.app), base_url="http://t",
    )


def _click_before(state) -> dict[str, int]:
    return {k: int(state.metrics[k]) for k in MONTH_OPEN_KEYS}


def _open_night_with_unextracted_reply(game, minister, reply="臣愿肩起此事。"):
    """票面夹具：开夜 + 回话已落、story 抽取未落（extract_status 待补）。"""
    db, state = game.db, game.state
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    an.ensure_summon_enter(db, nid, minister)
    ctid = db.create_chat_turn(state, minister, "sess-1235", 0, night_id=nid)
    db.persist_minister_reply(minister, int(state.turn), reply, ctid)
    assert db.count_pending_story_extractions(night_id=nid) >= 1
    return nid, ctid


def _runtime_payload(db, state):
    """轻壳 state_payload（与 T1 同形）。"""
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(
        db=db,
        state=state,
        content=SimpleNamespace(characters={}),
        previous_summary="",
        last_decree="",
        last_report="",
        pending_count=lambda: 0,
        pending_decisions=lambda: [],
        victory=lambda: {"status": "ongoing", "summary": ""},
    )
    runtime.directive_rows = lambda: []
    runtime.issue_payloads = lambda: []
    runtime.legacies_payload = lambda: []
    runtime.closed_this_turn_payloads = lambda: []
    runtime.map_nodes = lambda: []
    runtime.ending_payload = lambda: None
    runtime.public_character = lambda c: {"name": getattr(c, "name", "")}
    runtime.character_power_id = lambda c: "ming"
    return runtime.state_payload()


# ── 1. 未了续跑：未落账回话退朝不 409，自动接续至月完 ────────────────────


def test_advance_with_unextracted_reply_accepts_and_continues(web_game, monkeypatch):
    """AC1：存在未落账回话时退朝 → 不打回/409；收夜 drain 后自动推进。"""
    game = web_game
    minister = _active_minister(game)
    _fake_settlement_llm(monkeypatch)
    before = _click_before(game.state)
    turn_before = int(game.state.turn)
    nid, _ctid = _open_night_with_unextracted_reply(game, minister)
    assert game.db.get_month_open_snapshot(turn_before) is None

    # 观测：close 前点即入已 capture 点击前四键（可证时序，非恒真 sanity）
    saw_capture = {}
    real_close = web_app._auto_close_open_night_gate_free

    def _close_observing(g, **kw):
        saw_capture["snap"] = g.db.get_month_open_snapshot(int(g.state.turn))
        return real_close(g, **kw)

    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", _close_observing)

    async def go():
        async with _client() as client:
            return await client.post("/api/decree/advance_without_edict")

    resp = asyncio.run(go())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 月完：快照过期、展示态清；夜已封
    assert int(game.state.turn) == turn_before + 1
    assert an.get_night(game.db, nid)["status"] == an.NIGHT_STATUS_CLOSED
    assert game.db.get_month_open_snapshot(turn_before) is None
    assert body["state"]["turn"]["settlement_display"] is False
    assert saw_capture.get("snap") == before


def test_issue_with_unextracted_reply_accepts_and_continues(web_game, monkeypatch):
    """AC1 颁布入口：未落账回话 → 不 409；自动收夜+结算接续。"""
    game = web_game
    minister = _active_minister(game)
    _fake_settlement_llm(monkeypatch)
    turn_before = int(game.state.turn)
    nid, _ctid = _open_night_with_unextracted_reply(game, minister)
    # 颁布至少一条草案（与生产拟诏门槛同）
    game.db.add_directive(
        game.state, None, "着户部核边饷", "t1235", actor=minister,
        status="draft",
        dossier_payload={
            "dossier_action_type": "policy",
            "target_kind": "issue",
            "target_id": "border-pay-1235",
        },
    )

    async def go():
        async with _client() as client:
            return await client.post("/api/decree/issue", json={})

    resp = asyncio.run(go())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 完成或 awaiting 皆可；不得 409 打回
    assert "awaiting_decision" in body or "report" in body or "decree" in body
    assert an.get_night(game.db, nid)["status"] == an.NIGHT_STATUS_CLOSED
    if body.get("awaiting_decision"):
        assert game.db.get_month_open_snapshot(turn_before) is not None
        payload = game.state_payload()
        assert payload["turn"]["settlement_display"] is True
    else:
        assert int(game.state.turn) == turn_before + 1


# ── 2. 点即入：capture 先于 await/close（失败前已入核账，失败后出展示态）──


def test_web_entry_captures_before_await_close(web_game, monkeypatch):
    """点即入时序：入口一受理即 capture；await 抛错前快照已在。"""
    game = web_game
    before = _click_before(game.state)
    turn = int(game.state.turn)
    captured_at = {}

    from ming_sim.audience_night import AudienceNightError

    def _boom_close(_g, **_k):
        snap = _g.db.get_month_open_snapshot(int(_g.state.turn))
        captured_at["before_await"] = snap
        raise AudienceNightError(
            "收夜中止：本夜仍有未完成回话（在飞/挂起），chat_turn_ids=[9]。夜保持开启，可原地重试。",
            code="in_flight_chat",
        )

    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", _boom_close)

    async def go():
        async with _client() as client:
            return await client.post("/api/decree/advance_without_edict")

    resp = asyncio.run(go())
    assert resp.status_code == 409, resp.text
    # 受理时已 capture（await 前快照 = 点击前四键）
    assert captured_at["before_await"] == before
    # 真失败后展示态退出
    assert game.db.get_month_open_snapshot(turn) is None
    assert game.state_payload()["turn"]["settlement_display"] is False
    detail = resp.json()["detail"]
    text = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
    assert "未完成回话" in text or "在飞" in text


# ── 3. 真失败另形：pending 抽取仍失败 → 人话 + 展示态退出 ──────────────


def test_true_failure_pending_extraction_exits_display(web_game, monkeypatch, tmp_path):
    """AC2 / #1353 fold-in：drain 真失败 → 失败单源 + settlement_display 退出（≠ 未了在办）。"""
    from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE

    game = web_game
    minister = _active_minister(game)
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    # 持续失败的抽取员 → drain 失败单源
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda *a, **k: _BoomExtractor())
    before = _click_before(game.state)
    turn = int(game.state.turn)
    nid, ctid = _open_night_with_unextracted_reply(game, minister)

    # 观测：await 通过后 close 前应已 capture
    saw_capture = {}

    real_close = web_app._auto_close_open_night_gate_free

    def _close_observing(g, **kw):
        saw_capture["snap"] = g.db.get_month_open_snapshot(int(g.state.turn))
        return real_close(g, **kw)

    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", _close_observing)

    async def go():
        async with _client() as client:
            return await client.post("/api/decree/advance_without_edict")

    resp = asyncio.run(go())
    # 欠账类 409 已删；advance 走 LLMUnavailable → 412 失败单源
    assert resp.status_code == 412, resp.text
    detail = resp.json()["detail"]
    text = detail if isinstance(detail, str) else (
        detail.get("message") if isinstance(detail, dict) else json.dumps(detail, ensure_ascii=False)
    )
    assert CLI_RUNNER_PLAYER_MESSAGE in str(text)
    assert "待补" not in str(text)
    assert "补写" not in str(text)
    # 点即入曾发生
    assert saw_capture.get("snap") == before
    # 真失败另形：展示态退出
    assert game.db.get_month_open_snapshot(turn) is None
    payload = game.state_payload()
    assert payload["turn"]["settlement_display"] is False
    for k in MONTH_OPEN_KEYS:
        assert payload["metrics"][k] == int(game.state.metrics[k])  # 活值，非冻快照
    # 夜保持开（0036 原意），可重按过月
    assert an.get_night(game.db, nid)["status"] == an.NIGHT_STATUS_OPEN
    assert game.db.count_pending_story_extractions(night_id=nid) >= 1
    assert game.db.get_story_extract_status(ctid) in ("", "pending")


def test_true_failure_issue_exits_display(web_game, monkeypatch, tmp_path):
    """AC2 颁布入口同形。"""
    game = web_game
    minister = _active_minister(game)
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda *a, **k: _BoomExtractor())
    before = _click_before(game.state)
    turn = int(game.state.turn)
    _open_night_with_unextracted_reply(game, minister)
    game.db.add_directive(
        game.state, None, "着户部核边饷", "t1235-fail", actor=minister,
        status="draft",
        dossier_payload={
            "dossier_action_type": "policy",
            "target_kind": "issue",
            "target_id": "border-pay-fail",
        },
    )
    saw = {}
    real_close = web_app._auto_close_open_night_gate_free

    def _close_observing(g, **kw):
        saw["snap"] = g.db.get_month_open_snapshot(int(g.state.turn))
        return real_close(g, **kw)

    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", _close_observing)

    async def go():
        async with _client() as client:
            return await client.post("/api/decree/issue", json={})

    resp = asyncio.run(go())
    from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE
    # 欠账类 409 已删；issue 走 LLMUnavailable → 400 失败单源
    assert resp.status_code == 400, resp.text
    detail = resp.json().get("detail")
    blob = detail if isinstance(detail, str) else json.dumps(detail or {}, ensure_ascii=False)
    assert CLI_RUNNER_PLAYER_MESSAGE in blob
    assert saw.get("snap") == before  # 点即入曾发生
    assert game.db.get_month_open_snapshot(turn) is None
    assert game.state_payload()["turn"]["settlement_display"] is False


# ── 4. AC3 不回归：settling 恢复条 / 批红下发 ────────────────────────────


def test_settling_keeps_display_for_recovery(game):
    """AC3：settling 相位下快照保留（恢复入口可达的状态口条件）。"""
    db, state, content = game
    before = _click_before(state)
    db.capture_month_open_snapshot(state)
    import ming_sim.decree as dm
    dm.pre_settle(state, db, content=content)
    assert state.turn_phase == TurnPhase.SETTLING.value
    # 真失败退出不得误清 settling 快照
    from ming_sim.month_open_snapshot import exit_settlement_display_on_failure
    assert exit_settlement_display_on_failure(db, state) is False
    assert db.get_month_open_snapshot(int(state.turn)) == before
    payload = _runtime_payload(db, state)
    assert payload["turn"]["settlement_display"] is True
    assert payload["turn"]["phase"] == "settling"


def test_awaiting_decision_still_emits_pending(game):
    """AC3：awaiting_decision 下 pending_decisions 照常下发 + 核账展示态在。"""
    db, state, _content = game
    before = _click_before(state)
    db.capture_month_open_snapshot(state)
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    decisions = [{"title": "测", "context": "x", "idx": 0, "options": [{"label": "a"}]}]

    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(
        db=db,
        state=state,
        content=SimpleNamespace(characters={}),
        previous_summary="",
        last_decree="",
        last_report="",
        pending_count=lambda: 0,
        pending_decisions=lambda: list(decisions),
        victory=lambda: {"status": "ongoing", "summary": ""},
    )
    runtime.directive_rows = lambda: []
    runtime.issue_payloads = lambda: []
    runtime.legacies_payload = lambda: []
    runtime.closed_this_turn_payloads = lambda: []
    runtime.map_nodes = lambda: []
    runtime.ending_payload = lambda: None
    runtime.public_character = lambda c: {"name": getattr(c, "name", "")}
    runtime.character_power_id = lambda c: "ming"

    payload = runtime.state_payload()
    assert payload["turn"]["settlement_display"] is True
    assert payload["turn"]["phase"] == "awaiting_decision"
    assert payload["pending_decisions"] == decisions
    for k in MONTH_OPEN_KEYS:
        assert payload["metrics"][k] == before[k]

    from ming_sim.month_open_snapshot import exit_settlement_display_on_failure
    assert exit_settlement_display_on_failure(db, state) is False
    assert db.get_month_open_snapshot(int(state.turn)) == before


def test_accept_creator_atomic_only_one_true(game, monkeypatch):
    """#1235 r6：双 accept 仅一 True——原子 INSERT 裁定创建者，禁后置见行假 True。

    monkeypatch get 恒 None 模拟双侧预检同空（交错窗）；连调两次须 (True, False)。
    旧后置见行路径会 (True, True) 或 IntegrityError；本测有牙。
    """
    from ming_sim.month_open_snapshot import accept_settlement_period

    db, state, _ = game
    turn = int(state.turn)
    real_get = db.get_month_open_snapshot
    monkeypatch.setattr(db, "get_month_open_snapshot", lambda _t: None)

    first = accept_settlement_period(db, state)
    second = accept_settlement_period(db, state)
    assert (first, second) == (True, False)

    # 行确实只建一次（绕过恒 None 补丁读真库）
    assert real_get(turn) is not None
    third = accept_settlement_period(db, state)
    assert third is False


# ── 5. accept 后 gate/HTTPException 拒收 → 不得留孤儿核账展示态 ──────────


def test_advance_http_reject_after_accept_exits_display(web_game, monkeypatch):
    """#1235 r1 D：退朝 accept 后 _serialized_web_write 抢锁 409 → 出展示态。

    HTTPException 非 ValueError 子类；须经 settled_ok 失败臂收口，禁孤儿快照。
    """
    from fastapi import HTTPException

    game = web_game
    before = _click_before(game.state)
    turn = int(game.state.turn)
    saw = {}

    @contextlib.contextmanager
    def _gate_busy(g):
        # accept 已落：此处快照必在且 = 点击前四键
        saw["snap"] = g.db.get_month_open_snapshot(int(g.state.turn))
        raise HTTPException(
            status_code=409,
            detail="月末结算或上一步写入进行中，请稍候再操作。",
        )
        yield  # pragma: no cover — raise 后不可达；保 CM 形

    monkeypatch.setattr(web_app, "_serialized_web_write", _gate_busy)
    # 跳过 await/close 噪声，直达 gate 缝
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda _g, **kw: None)

    async def go():
        async with _client() as client:
            return await client.post("/api/decree/advance_without_edict")

    resp = asyncio.run(go())
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    text = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
    assert "请稍候" in text or "进行中" in text
    # 点即入曾发生
    assert saw.get("snap") == before
    # 拒收后不得留孤儿核账展示态
    assert game.db.get_month_open_snapshot(turn) is None
    assert game.state_payload()["turn"]["settlement_display"] is False
    # 相位仍常态（非 settling/awaiting）——AC3 路径未误触
    assert game.state.turn_phase not in (
        TurnPhase.SETTLING.value, TurnPhase.AWAITING_DECISION.value,
    )


def test_concurrent_advance_noncreator_must_not_clear_owner_snapshot(web_game, monkeypatch):
    """#1235 r2 p2：并发代清洞——A 已 capture 持 _write_gate；B accept 幂等 no-op 后抢锁 409，
    其 finally 以 non-blocking exit 撞锁 skip，不得代清 A 的快照（须立即返回不堵）。

    主案：advance 非阻塞 _serialized_web_write 洞口（持锁支）。gate-free 在办支见 r4。
    """
    game = web_game
    before = _click_before(game.state)
    turn = int(game.state.turn)

    # 跳过 await/close 噪声，直达 gate 缝
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda _g, **kw: None)

    # 请求 A：点即入真新建 + 持 _write_gate（结算 worker 在办）
    assert web_app._accept_settlement_period(game) is True
    assert game.db.get_month_open_snapshot(turn) == before
    gate = web_app._game_write_gate(game)
    assert gate.acquire(blocking=False), "A 须能持 write_gate"
    try:
        async def go_b():
            async with _client() as client:
                return await client.post("/api/decree/advance_without_edict")

        resp_b = asyncio.run(go_b())
        assert resp_b.status_code == 409, resp_b.text
        detail = resp_b.json()["detail"]
        text = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
        assert "请稍候" in text or "进行中" in text
        # B 幂等 no-op 后 409：non-blocking exit 撞锁 skip，不得代清 A 的快照
        assert game.db.get_month_open_snapshot(turn) == before
        assert game.state_payload()["turn"]["settlement_display"] is True
        # accept 幂等：B 再调仍 False（非创建）
        assert web_app._accept_settlement_period(game) is False
    finally:
        gate.release()

    # A 仍在办时快照保持；释放后创建者失败路径仍可自行 exit（单请求口径不回归）
    assert game.db.get_month_open_snapshot(turn) == before


def test_exit_settlement_display_acquires_write_gate(web_game):
    """#1235 r2 p2 / r3：blocking=True（创建者）清快照须经 _write_gate 阻塞 acquire。"""
    import threading

    game = web_game
    turn = int(game.state.turn)
    assert web_app._accept_settlement_period(game) is True
    gate = web_app._game_write_gate(game)
    assert gate.acquire(blocking=False)
    held = {"cleared_under_gate": False}
    done = threading.Event()
    err: list = []

    orig_clear = game.db.clear_month_open_snapshot

    def _wrapped_clear(t):
        held["cleared_under_gate"] = gate.locked()
        return orig_clear(t)

    game.db.clear_month_open_snapshot = _wrapped_clear  # type: ignore[method-assign]

    def _peer_exit():
        try:
            # 创建者路径：blocking 等待 gate 后必清
            web_app._exit_settlement_display_on_failure(game, blocking=True)
        except Exception as exc:  # noqa: BLE001
            err.append(exc)
        finally:
            done.set()

    try:
        t = threading.Thread(target=_peer_exit, daemon=True)
        t.start()
        # 他持 write_gate 时 blocking exit 须堵在 acquire，不得无门完成清快照
        assert not done.wait(0.05), "exit 不得在 write_gate 仍被他持时无门完成"
        assert game.db.get_month_open_snapshot(turn) is not None
        gate.release()
        assert done.wait(2.0), "exit 在 gate 释放后须完成"
        t.join(2.0)
    finally:
        game.db.clear_month_open_snapshot = orig_clear  # type: ignore[method-assign]
        if gate.locked():
            gate.release()

    assert not err, err
    assert held["cleared_under_gate"] is True
    assert game.db.get_month_open_snapshot(turn) is None


@pytest.mark.parametrize("entry", [
    pytest.param("issue", id="issue"),
    pytest.param("stream", id="stream"),
])
def test_session_reaccept_orphan_exits_after_owner_release(web_game, monkeypatch, entry):
    """#1235 r3 / #1241 S5：session-reaccept-orphan-after-web-noncreator（issue/stream 同根）。

    A web-accept 真新建并持 gate；B web-accept 得 False 后堵在阻塞 gate；
    A 失败 exit 清快照并放锁 → B 进 resolve（session 再 accept 新建）后失败 →
    B finally 虽 created_display=False 仍须 non-blocking 抢到锁并清孤儿。
    """
    import threading
    import time

    from ming_sim.month_open_snapshot import accept_settlement_period

    game = web_game
    before = _click_before(game.state)
    turn = int(game.state.turn)

    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda _g, **kw: None)

    saw = {"web_created": None, "session_reaccept": None}
    b_done = threading.Event()
    b_result: dict = {}

    real_accept = web_app._accept_settlement_period

    def _track_web_accept(g):
        created = real_accept(g)
        # 只记 B 线程的 web accept（A 已在主线程手工 accept）
        if threading.current_thread() is not threading.main_thread():
            saw["web_created"] = created
        return created

    monkeypatch.setattr(web_app, "_accept_settlement_period", _track_web_accept)

    def _boom_resolve(*_a, **_k):
        # 模拟 session.resolve_turn 内二次 accept 后 ValueError（无 session exit 臂）
        created = accept_settlement_period(game.db, game.state)
        saw["session_reaccept"] = created
        raise ValueError(f"推演失败·{entry} session再创建后注入")

    monkeypatch.setattr(game.session, "resolve_turn", _boom_resolve)

    # A：点即入 + 持 gate（结算在办）
    assert web_app._accept_settlement_period(game) is True
    assert game.db.get_month_open_snapshot(turn) == before
    gate = web_app._game_write_gate(game)
    assert gate.acquire(blocking=False), "A 须能持 write_gate"

    def _run_b():
        try:
            async def go():
                async with _client() as client:
                    if entry == "issue":
                        resp = await client.post("/api/decree/issue", json={})
                        return resp.status_code, resp.text
                    async with client.stream(
                        "POST", "/api/decree/issue/stream", json={},
                    ) as resp:
                        body = ""
                        async for chunk in resp.aiter_text():
                            body += chunk
                        return resp.status_code, body

            status, body = asyncio.run(go())
            b_result["status"] = status
            b_result["body"] = body
        except Exception as exc:  # noqa: BLE001
            b_result["err"] = exc
        finally:
            b_done.set()

    t = threading.Thread(target=_run_b, daemon=True)
    t.start()
    # 等 B 完成 web accept（False）并堵在阻塞 gate
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and saw["web_created"] is None:
        time.sleep(0.01)
    assert saw["web_created"] is False, "B 须为 web 非创建者"
    assert not b_done.is_set(), f"B 不得在 A 持锁时完成 {entry}"
    assert game.db.get_month_open_snapshot(turn) == before

    # A 失败 exit 清快照后再放锁（判词序：清后放锁，逼出 B session 再创建）
    from ming_sim.month_open_snapshot import exit_settlement_display_on_failure
    assert exit_settlement_display_on_failure(game.db, game.state) is True
    assert game.db.get_month_open_snapshot(turn) is None
    gate.release()

    assert b_done.wait(5.0), "B 在 A 放锁后须完成"
    t.join(2.0)
    assert "err" not in b_result, b_result.get("err")
    if entry == "issue":
        assert b_result.get("status") == 400, b_result
    else:
        assert b_result.get("status") == 200, b_result
        assert "error" in (b_result.get("body") or "")
    # B 进 resolve 后 session 再创建了孤儿快照
    assert saw["session_reaccept"] is True
    # B finally 须清掉该孤儿（created_display=False 不得再跳过 exit）
    assert game.db.get_month_open_snapshot(turn) is None
    assert game.state_payload()["turn"]["settlement_display"] is False
    if entry == "issue":
        assert game.state.turn_phase not in (
            TurnPhase.SETTLING.value, TurnPhase.AWAITING_DECISION.value,
        )


def test_noncreator_exit_must_not_clear_owner_during_gatefree(web_game, monkeypatch):
    """#1235 r4：noncreator-exit-clears-owner-during-gatefree。

    A web-accept 真新建后停在 gate-free await（不持 write_gate）仍在办；
    B 非创建同窗失败 → non-blocking exit 不得因锁闲代清 A 快照。
    放行 A 后创建者失败臂自行清（r1 D 不松；C 面孤儿回归另案保留）。
    """
    import threading

    from ming_sim.audience_night import AudienceNightError

    game = web_game
    before = _click_before(game.state)
    turn = int(game.state.turn)

    a_in_await = threading.Event()
    a_release = threading.Event()
    a_done = threading.Event()
    a_result: dict = {}

    def _hold_close_for_a(_g, **_kw):
        # 仅 A 线程：停在 accept 后屏障体内（展示态应保留）
        a_in_await.set()
        assert a_release.wait(5.0), "测试须放行 A 的屏障 close"
        raise AudienceNightError(
            "收夜失败·A创建者收口", code="close_failed",
        )

    # A 的 close hold；B 在 A 屏障未完成前会卡在自己的 barrier 等待，不得代清
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", _hold_close_for_a)

    def _run_a():
        try:
            async def go():
                async with _client() as client:
                    return await client.post("/api/decree/advance_without_edict")

            resp = asyncio.run(go())
            a_result["status"] = resp.status_code
            a_result["body"] = resp.text
        except Exception as exc:  # noqa: BLE001
            a_result["err"] = exc
        finally:
            a_done.set()

    t_a = threading.Thread(target=_run_a, daemon=True)
    t_a.start()
    assert a_in_await.wait(2.0), "A 须进入屏障 close 窗"
    assert game.db.get_month_open_snapshot(turn) == before
    assert game.state_payload()["turn"]["settlement_display"] is True
    assert web_app._settlement_entry_inflight(game) >= 1

    # B：同窗并发过月——卡在 barrier 等待 A，不得代清 A 快照
    b_started = threading.Event()
    b_done = threading.Event()
    b_result: dict = {}

    def _run_b():
        b_started.set()
        try:
            async def go_b():
                async with _client() as client:
                    return await client.post("/api/decree/advance_without_edict")

            resp_b = asyncio.run(go_b())
            b_result["status"] = resp_b.status_code
            b_result["body"] = resp_b.text
        except Exception as exc:  # noqa: BLE001
            b_result["err"] = exc
        finally:
            b_done.set()

    t_b = threading.Thread(target=_run_b, daemon=True)
    t_b.start()
    assert b_started.wait(2.0)
    # A 仍在办时快照不得被清
    time.sleep(0.05)
    assert game.db.get_month_open_snapshot(turn) == before
    assert game.state_payload()["turn"]["settlement_display"] is True
    assert web_app._settlement_entry_inflight(game) >= 1, "A 仍须计在办"

    # 放行 A：创建者失败臂清展示态；B 随后以自有屏障继续/失败
    a_release.set()
    assert a_done.wait(5.0), "A 放行后须完成"
    t_a.join(2.0)
    assert b_done.wait(5.0), "B 须在 A 屏障结束后完成"
    t_b.join(2.0)
    assert "err" not in a_result, a_result.get("err")
    assert a_result.get("status") == 409, a_result
    assert "err" not in b_result, b_result.get("err")
    assert b_result.get("status") == 409, b_result
    assert game.db.get_month_open_snapshot(turn) is None
    assert game.state_payload()["turn"]["settlement_display"] is False
    assert web_app._settlement_entry_inflight(game) == 0
    assert game.state.turn_phase not in (
        TurnPhase.SETTLING.value, TurnPhase.AWAITING_DECISION.value,
    )


# ── 5. SP1 #1241：断线→重连 e2e tracer（#1220 US14）──────────────────────


def test_disconnect_mid_settlement_reconnect_coherent(web_game, monkeypatch):
    """#1241 SP1 / #1220 US14：断线后结算继续，重连状态口自洽。

    接缝：真实颁布 stream 入口 + 既有离线 LLM 替身；客户端弃流后 worker 仍跑完；
    全新连接 GET /api/game/state 见终态（不丢账、不重跑）。禁仅测试用生产钩子。
    """
    import threading
    import time

    game = web_game
    minister = _active_minister(game)
    _fake_settlement_llm(monkeypatch)
    before = _click_before(game.state)
    turn_before = int(game.state.turn)

    game.db.add_directive(
        game.state, None, "着户部核边饷", "t1241-sp1", actor=minister,
        status="draft",
        dossier_payload={
            "dossier_action_type": "policy",
            "target_kind": "issue",
            "target_id": "border-pay-1241-sp1",
        },
    )

    entered_resolve = threading.Event()
    release_resolve = threading.Event()
    stream_done = threading.Event()
    stream_meta: dict = {}

    real_resolve = game.session.resolve_turn

    def _held_resolve(*a, **k):
        # 先推一条 stage，让 SSE generate 不堵在首个 queue.get（便于客户端弃流）。
        on_event = k.get("on_event")
        if callable(on_event):
            on_event("stage", "推演中")
        entered_resolve.set()
        assert release_resolve.wait(15.0), "测试须放行 resolve"
        return real_resolve(*a, **k)

    monkeypatch.setattr(game.session, "resolve_turn", _held_resolve)

    def _run_stream_then_drop():
        """模拟关页/断网：见到结算已进入 resolve 后弃流，不读终态。"""
        try:
            async def go():
                async with _client() as client:
                    async with client.stream(
                        "POST", "/api/decree/issue/stream", json={},
                    ) as resp:
                        stream_meta["status"] = resp.status_code
                        # 读到首条 stage（resolve 已入）即弃流
                        async for _chunk in resp.aiter_text():
                            if entered_resolve.is_set():
                                break
                        # 离开 stream 上下文 = 客户端断开；worker 线程须独立续跑

            asyncio.run(go())
        except Exception as exc:  # noqa: BLE001
            stream_meta["err"] = exc
        finally:
            stream_done.set()

    t = threading.Thread(target=_run_stream_then_drop, daemon=True)
    t.start()
    assert entered_resolve.wait(10.0), "须进入 resolve（点即入+gate 后）"

    # 断线窗：核账展示态已亮、四键为点击前（状态口可观测）
    assert game.db.get_month_open_snapshot(turn_before) == before
    mid = game.state_payload()
    assert mid["turn"]["settlement_display"] is True
    for k in MONTH_OPEN_KEYS:
        assert mid["metrics"][k] == before[k]

    # 重连观察（结算仍在办、原 SSE 已弃读）：全新连接见同一张核账脸
    async def reconnect():
        async with _client() as client:
            return await client.get("/api/game/state")

    mid_resp = asyncio.run(reconnect())
    assert mid_resp.status_code == 200, mid_resp.text
    mid_state = mid_resp.json()
    assert mid_state["turn"]["settlement_display"] is True
    for k in MONTH_OPEN_KEYS:
        assert mid_state["metrics"][k] == before[k]

    # 放行 worker：客户端已弃读 SSE，结算须在后台继续跑完
    # （先放行再等弃流线程——否则 ASGI generate 堵在 queue.get，aclose 与 release 死锁）
    release_resolve.set()

    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if web_app._settlement_entry_inflight(game) == 0 and not web_app._game_write_gate(game).locked():
            break
        time.sleep(0.05)
    assert web_app._settlement_entry_inflight(game) == 0, "入口须销账（结算 worker 须跑完）"
    assert not web_app._game_write_gate(game).locked()

    assert stream_done.wait(10.0), "弃流客户端须返回"
    t.join(2.0)
    assert "err" not in stream_meta, stream_meta.get("err")

    # 再重连：终态自洽（不接原 SSE）
    resp = asyncio.run(reconnect())
    assert resp.status_code == 200, resp.text
    state = resp.json()
    # 自洽：月推进完成 → 展示态清；或 awaiting 停窗 → 展示态在且四键仍为点击前
    # 不丢账：快照回合绑定，不得无展示态却残留本回合快照
    turn_now = int(state["turn"]["turn"])
    display = bool(state["turn"].get("settlement_display"))
    snap = game.db.get_month_open_snapshot(turn_before)
    if turn_now == turn_before + 1:
        assert display is False
        assert snap is None
        # 活值回归（非冻快照）；不重跑：只推进一回合
        assert int(game.state.turn) == turn_before + 1
    elif display:
        assert turn_now == turn_before
        assert snap == before
        for k in MONTH_OPEN_KEYS:
            assert state["metrics"][k] == before[k]
    else:
        raise AssertionError(
            f"重连态不自洽: turn={turn_now} display={display} snap={snap} phase={state['turn'].get('phase')}"
        )
