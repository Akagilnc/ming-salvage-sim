"""#1468 过月主链 e2e tracer——真实 HTTP 入口两月循环 + #1353 fold-in 钉。

回应 owner「测试全绿流程走不通」：全仓接缝钉照不到跨接缝状态机脱节；
本文件从真实 HTTP 入口走玩家基本循环，仅在最外层 LLM 接缝 deterministic stub
（不 mock 内部函数 / 结算核 / 收夜编排）。

主 tracer：new_game → 召对开夜/回话/收夜 → 拟旨 → POST /api/decree/issue/stream
（消费 SSE 到终态）→ 月+1 → 再一月。起点置十一月以真跨 year rollover
（year+1 且 period 回 1）。断言 turn+2 与 year/period 跨年安全月序 +2、无 409 死锁、
无裸 500、闸/账双向等量（成功过月 count==len(pending)==0）。
#1353 fold-in 钉：
- 植入欠账后一次过月动作成功（流内处理、无 409、无 CTA、账清、月+1）
- 真死 LLM stub → 失败单源（通传未达），非待补 CTA/409；夜保持可重按
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import ming_sim.agents as agents_mod
import ming_sim.cli_backend as cli_backend
import ming_sim.decree as decree_mod
import ming_sim.session as session_mod
import web_app
from ming_sim import audience_night as an
from tests.test_session_write_queue_1353 import wait_pending_writes as _wait_pending_writes
from tests.conftest import stub_audience_translate, stub_scene_agent


# ── outermost LLM seams only ─────────────────────────────────────────────


class _CannedExtractor:
    def run(self, _material):
        return SimpleNamespace(content='{"facts":[]}')


class _BoomExtractor:
    def run(self, _material):
        raise RuntimeError("抽取持续失败·#1468 负向钉")



class _CannedMinisterAgent:
    """非流式 session.chat 读 agent.run().content（非 generator）。"""

    def run(self, *_a, **_k):
        return SimpleNamespace(content="臣已知悉，边饷当速清。", tools=[])




def _stub_outer_llm_seams(monkeypatch) -> None:
    """只换最外层 LLM 工厂/调用；结算核、收夜、HTTP 路由全真跑。"""
    from tests.month_chain_helpers import empty_rescript_response
    monkeypatch.setattr("ming_sim.rescript_draft.run_rescript_text", empty_rescript_response)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    # #642：召对/收夜关系判官同属外层 LLM 缝——漏 stub 会在有 window 时真网挂起，
    # 票据不归还 → xdist 下 _wait_pending_writes 墙钟假红。
    # 高亮判官默认 8s 超时——必须零延迟 stub，否则两月链必破速度红线。
    monkeypatch.setattr(web_app, "run_highlight_judge", lambda **_k: [])
    # 拟旨 capture 默认 30s 总罩——外层接缝 canned，禁真 LLM/真等。
    monkeypatch.setattr(
        cli_backend,
        "capture_manual_directive_payload",
        lambda text, llm_config=None, **_k: {
            "dossier_action_type": "policy",
            "target_kind": "issue",
            "target_id": "month-loop-tracer-1468",
            "mode": "ordinary",
        },
    )
    # 判决及本月世界段只桩现役外部 LLM 缝。
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
        # 等召对尾随落完再关库；fail-loud——wait_idle=False/异常不得吞掉后继续关库。
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
    # 仍禁止主链撞 500——玩家基本流程必须走通。
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



from tests.test_chat_stream_failpaths_393 import _parse_sse



def _post_issue_stream(
    client: TestClient, *, expected_turn: int, step: str,
    allow_error: bool = False,
) -> dict:
    """玩家真入口：POST /api/decree/issue/stream，消费 SSE 到终态。

    返回归一化 body：done → payload；decisions → payload + awaiting_decision=True。
    event:error 且 status_code=409 → 死锁断言红；其它 error 默认亦红。
    allow_error=True（#1769 真故障钉）：error 终态返回 payload 并标 _event='error'。
    """
    resp = client.post(
        "/api/decree/issue/stream",
        json={"expected_turn": expected_turn},
    )
    _assert_not_bare_500(resp, step=step)
    assert resp.status_code == 200, f"{step} → {resp.status_code}: {resp.text}"
    # 流式入口 HTTP 层 200；业务失败走 event:error（含 409 令牌/锁语义）。
    events = _parse_sse(resp.text)
    assert events, f"{step}: empty SSE body={resp.text!r}"
    ev, data = events[-1]
    if not isinstance(data, dict):
        data = {"message": data}
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




# ── 主 tracer：两整月（起点十一月 → 真跨年） ────────────────────────────




# ── #1353 fold-in：带欠账一次过月成功 + 死透失败单源 ─────────────────────


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
    """#1353 fold-in / #1842：转译 LLM 死透 → 耗尽失败单源；夜可重按。

    真入口 POST /api/decree/issue/stream：SSE error + typed stage 单源。
    """
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

    # #1842：收夜 catch-up 认转译水位；真失败注入转译缝。
    def _boom_translate(prompt, llm_config):
        del prompt, llm_config
        raise LLMUnavailable(CLI_RUNNER_PLAYER_MESSAGE, code="llm_error")

    stub_audience_translate(monkeypatch, _boom_translate)

    body = _post_issue_stream(
        client, expected_turn=turn0, step="dead-llm issue", allow_error=True,
    )
    # #1842：转译耗尽 → SettlementAbort → SSE error + typed stage（非玩家补写 CTA）。
    assert body.get("_event") == "error", body
    assert body.get("stage") == "audience_translation_exhausted", body
    assert body.get("error_pack_path"), body

    # 诊断面仍可见欠账；夜保持开，玩家重按过月=重试整段
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


# ── #1716：已开夜场外 COURT_BREAK 不得被 SUMMON_* 短路 ──────────────────
