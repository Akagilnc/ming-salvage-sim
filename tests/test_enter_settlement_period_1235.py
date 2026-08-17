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

    def _boom_await(_g):
        snap = _g.db.get_month_open_snapshot(int(_g.state.turn))
        captured_at["before_await"] = snap
        raise AudienceNightError(
            "收夜中止：本夜仍有未完成回话（在飞/挂起），chat_turn_ids=[9]。夜保持开启，可原地重试。",
            code="in_flight_chat",
        )

    monkeypatch.setattr(web_app, "_await_audience_inflight_clear", _boom_await)

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
    """AC2：drain 真失败 → 409 人话 + settlement_display 退出（≠ 未了在办）。"""
    game = web_game
    minister = _active_minister(game)
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    # 持续失败的抽取员 → drain fail-closed
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
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    text = detail if isinstance(detail, str) else (
        detail.get("message") if isinstance(detail, dict) else json.dumps(detail, ensure_ascii=False)
    )
    assert "待补" in text or "未抽取" in text or "抽取" in text
    # 点即入曾发生
    assert saw_capture.get("snap") == before
    # 真失败另形：展示态退出
    assert game.db.get_month_open_snapshot(turn) is None
    payload = game.state_payload()
    assert payload["turn"]["settlement_display"] is False
    for k in MONTH_OPEN_KEYS:
        assert payload["metrics"][k] == int(game.state.metrics[k])  # 活值，非冻快照
    # 夜保持开（0036 原意），可重试
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
    assert resp.status_code == 409, resp.text
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
    monkeypatch.setattr(web_app, "_await_audience_inflight_clear", lambda _g: None)
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
