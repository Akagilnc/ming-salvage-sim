"""#1468 / #1353：转译 LLM 死透 → 耗尽失败单源（真实 HTTP 入口）。

主两月 tracer 与场外 COURT_BREAK 夹具已随退役入口清除；本文件只保留仍有
真实入口契约价值的死透负向案。#1902 F3：删专用死夹具。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import ming_sim.decree as decree_mod
import ming_sim.session as session_mod
import web_app
from ming_sim import audience_night as an
from tests.conftest import stub_audience_translate
from tests.sse_helpers import parse_sse_events
from tests.test_session_write_queue_1353 import wait_pending_writes as _wait_pending_writes


def _stub_outer_llm_seams(monkeypatch) -> None:
    """只换最外层 LLM 工厂/调用；结算核、收夜、HTTP 路由全真跑。"""
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    monkeypatch.setattr(web_app, "run_highlight_judge", lambda **_k: [])
    monkeypatch.setattr(
        decree_mod,
        "llm_promulgation_verdicts",
        lambda dossiers, _state, **_kwargs: [
            {"dossier_id": row["id"], "decision": "promulgated"} for row in dossiers
        ],
    )
    monkeypatch.setattr(
        session_mod, "write_decree_with_agno",
        lambda *a, **k: "奉天承运，诏曰：着户部清核辽饷。",
    )
    monkeypatch.setattr(
        "ming_sim.month_chain.run_world_segment_text",
        lambda *a, **k: "本月邸报：边饷已清，流寇未息。",
    )
    monkeypatch.setattr(
        "ming_sim.month_chain.run_gazette_text",
        lambda *a, **k: ("边饷已清", "本月邸报：边饷已清，流寇未息。"),
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
            "forecast_text": "边饷已核",
            "visible_refs": {},
        },
    )


@pytest.fixture
def tracer_client(tmp_path, monkeypatch, _offline_scene_beat_generator):
    """真实 FastAPI TestClient；用户数据落 tmp；仅外层 LLM stub。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.delenv("MING_SIM_DB", raising=False)
    _stub_outer_llm_seams(monkeypatch)
    monkeypatch.setattr(web_app, "web_game", None)

    client = TestClient(web_app.app)
    yield client

    game = web_app.web_game
    if game is not None:
        try:
            _wait_pending_writes(game)
            game.session.close()
        finally:
            web_app.web_game = None


def _assert_not_bare_500(resp, *, step: str) -> None:
    """裸 500 = 无 detail 的服务器崩；结构化 4xx/可读 500 detail 另论。"""
    if resp.status_code < 500:
        return
    detail = None
    try:
        body = resp.json()
        detail = body.get("detail") if isinstance(body, dict) else body
    except Exception:
        detail = resp.text
    assert detail not in (None, "", {}), (
        f"{step}: bare 500 without detail; body={resp.text!r}"
    )
    assert resp.status_code < 500, (
        f"{step}: unexpected {resp.status_code}; detail={detail!r}"
    )


def _pick_active_minister(state: dict) -> str:
    for m in state.get("ministers") or []:
        if not isinstance(m, dict):
            continue
        if m.get("status") != "active":
            continue
        if m.get("power_id", "ming") != "ming":
            continue
        if m.get("office_type") in ("后宫", "宗藩"):
            continue
        name = str(m.get("name") or "").strip()
        if name:
            return name
    raise AssertionError(f"no active ming minister in state ministers={state.get('ministers')!r}")


def _turn_of(state: dict) -> int:
    turn = state.get("turn") or {}
    return int(turn.get("turn") or 0)


def _get_state(client: TestClient) -> dict:
    resp = client.get("/api/game/state")
    _assert_not_bare_500(resp, step="GET /api/game/state")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _pending_payload(client: TestClient) -> dict:
    """#1842：待补投影唯一真源 = list_pending_translations → chat.translation_retries。"""
    resp = client.get("/api/audience/chat")
    _assert_not_bare_500(resp, step="GET /api/audience/chat")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    retries = list(body.get("translation_retries") or [])
    return {"pending": retries, "count": len(retries)}


def _post_issue_stream(
    client: TestClient, *, expected_turn: int, step: str,
    allow_error: bool = False,
) -> dict:
    """玩家真入口：POST /api/decree/issue/stream，消费 SSE 到终态。

    跨文件共享（#1769/#1624/#1685/#1777）；非死夹具。
    """
    resp = client.post(
        "/api/decree/issue/stream",
        json={"expected_turn": expected_turn},
    )
    _assert_not_bare_500(resp, step=step)
    assert resp.status_code == 200, f"{step} → {resp.status_code}: {resp.text}"
    events = parse_sse_events(resp.text)
    assert events, f"{step}: empty SSE body={resp.text!r}"
    terminal = events[-1]
    ev = terminal.get("event")
    raw = terminal.get("data") or "{}"
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        data = {"message": raw}
    if ev == "error":
        status = data.get("status_code") if isinstance(data, dict) else None
        assert status != 409, (
            f"{step}: 409 deadlock on issue/stream; body={resp.text}"
        )
        if allow_error:
            payload = dict(data) if isinstance(data, dict) else {"message": data}
            return {**payload, "_event": "error"}
        raise AssertionError(f"{step}: stream error event: {data!r}; sse={resp.text!r}")
    if ev == "decisions":
        assert isinstance(data, dict), f"{step}: decisions payload not dict: {data!r}"
        return {**data, "awaiting_decision": True}
    if ev == "done":
        assert isinstance(data, dict), f"{step}: done payload not dict: {data!r}"
        return data
    raise AssertionError(
        f"{step}: unexpected terminal SSE event {ev!r}; body={resp.text!r}"
    )


def _resolve_decisions_via_stream(
    client: TestClient, decisions: list, *, step: str,
) -> None:
    """亲裁续跑：按 {label,hint?} 契约提交，消费 resolve SSE 到 done。"""
    choices = _choices_from_decisions(decisions)
    resolve = client.post(
        "/api/decree/resolve_decisions/stream",
        json={"choices": choices},
    )
    _assert_not_bare_500(resolve, step=step)
    assert resolve.status_code == 200, f"{step} → {resolve.status_code}: {resolve.text}"
    assert "event: error" not in resolve.text, f"{step} error SSE: {resolve.text}"
    assert "event: done" in resolve.text, f"{step} missing done: {resolve.text}"



def _plant_extraction_debt(game, minister: str, *, sess_tag: str) -> int:
    """生产同核欠账：开夜 + 回话落库未抽。返回 chat_turn_id。"""
    night = an.open_night(game.db, game.state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    an.ensure_summon_enter(game.db, nid, minister)
    ctid = game.db.create_chat_turn(game.state, minister, sess_tag, 0, night_id=nid)
    game.db.persist_minister_reply(minister, int(game.state.turn), "臣愿肩起此事。", ctid)
    assert int(len(game.db.list_unextracted_replies(night_id=nid)) or 0) >= 1
    return int(ctid)


def test_issue_extraction_llm_dead_single_source_not_cta(tracer_client, monkeypatch):
    """#1353 fold-in / #1842：转译 LLM 死透 → 耗尽失败单源；夜可重按。"""
    from ming_sim.exceptions import LLMUnavailable
    from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE

    client = tracer_client

    new = client.post("/api/menu/new_game")
    _assert_not_bare_500(new, step="new_game (dead-llm)")
    assert new.status_code == 200, new.text
    state0 = (new.json() or {}).get("state") or {}
    turn0 = _turn_of(state0)
    minister = _pick_active_minister(state0)
    game = web_app.web_game
    assert game is not None

    ctid = _plant_extraction_debt(game, minister, sess_tag="sess-1468-dead")

    def _boom_translate(prompt, llm_config):
        del prompt, llm_config
        raise LLMUnavailable(CLI_RUNNER_PLAYER_MESSAGE, code="llm_error")

    stub_audience_translate(monkeypatch, _boom_translate)

    from tests.issue_stream_helpers import IssueStreamError, post_issue_stream

    try:
        post_issue_stream(client, expected_turn=turn0, step="dead-llm issue")
    except IssueStreamError as exc:
        assert exc.status_code is None, f"中止不该冒充 409：{exc.payload}"
        detail = exc.payload
    else:
        raise AssertionError("dead-llm issue/stream 应以 SettlementAbort 终态收场")
    assert isinstance(detail, dict), detail
    assert detail.get("stage") == "audience_translation_exhausted", detail
    assert detail.get("error_pack_path"), detail

    pending = _pending_payload(client)
    pending_list = pending.get("pending") or []
    count = int(pending.get("count") or 0)
    assert count == len(pending_list) >= 1, (
        f"diagnostic pending should remain: count={count} body={pending!r}"
    )
    api_ids = {int(p.get("chat_turn_id") or 0) for p in pending_list}
    assert ctid in api_ids, f"pending API missing debt turn {ctid}: {pending!r}"

    still = an.get_open_night(game.db)
    assert still is not None
    assert str(still.get("status")) == an.NIGHT_STATUS_OPEN
    after = _get_state(client)
    assert _turn_of(after) == turn0, "dead-llm must not advance month"
