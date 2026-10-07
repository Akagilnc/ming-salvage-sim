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

import json
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


def _install_canned_minister(game, monkeypatch) -> None:
    agent = _CannedMinisterAgent()
    stub_scene_agent(monkeypatch, agent)


def _turn_of(state: dict) -> int:
    turn = state.get("turn") or {}
    return int(turn.get("turn") or 0)


def _month_ord_of(state: dict) -> int:
    """跨年安全月序：HTTP turn.year*12 + turn.period（禁只盯 turn 计数）。"""
    turn = state.get("turn") or {}
    return int(turn.get("year") or 0) * 12 + int(turn.get("period") or 0)


def _get_state(client: TestClient) -> dict:
    resp = client.get("/api/game/state")
    _assert_not_bare_500(resp, step="GET /api/game/state")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _pending_payload(client: TestClient) -> dict:

    """#1842/#1853：待补投影唯一真源 = list_pending_translations → scroll.translation_retries。"""
    resp = client.get("/api/audience/scroll")
    _assert_not_bare_500(resp, step="GET /api/audience/scroll")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    retries = list(body.get("translation_retries") or [])
    return {"pending": retries, "count": len(retries)}



def _parse_sse(text: str) -> list[dict]:
    """解析 SSE 文本为 [{event, data}, ...]（与仓内其他 ASGI tracer 同形）。"""
    events: list[dict] = []
    for block in (text or "").strip().split("\n\n"):
        cur: dict = {}
        for line in block.splitlines():
            if line.startswith("event:"):
                cur["event"] = line[len("event:"):].strip()
            elif line.startswith("data:"):
                cur["data"] = line[len("data:"):].strip()
        if cur:
            events.append(cur)
    return events


def _choices_from_decisions(decisions: list) -> list[dict]:
    """按契约从 d['options'] 取真实 option → {label, hint?, note?, dossier_*}。"""
    choices: list[dict] = []
    for d in decisions:
        opts = d.get("options") or []
        assert opts, f"decision missing options: {d!r}"
        opt0 = opts[0]
        if isinstance(opt0, dict):
            choice: dict = {"label": str(opt0.get("label") or "准")}
            if opt0.get("hint") is not None:
                choice["hint"] = opt0.get("hint")
            if opt0.get("note") is not None:
                choice["note"] = opt0.get("note")
            if "dossier_id" in opt0:
                choice["dossier_id"] = opt0.get("dossier_id")
            if "dossier_decision" in opt0:
                choice["dossier_decision"] = opt0.get("dossier_decision")
            choices.append(choice)
        else:
            choices.append({"label": str(opt0)})
    return choices


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
    """#1353 fold-in / #1842：转译 LLM 死透 → 耗尽失败单源；夜可重按。

    非流式兼容口轻钉：结构化 HTTP 409 SettlementAbort + detail 单源。
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

    issue = client.post("/api/decree/issue", json={"expected_turn": turn0})
    _assert_not_bare_500(issue, step="dead-llm issue")
    # #1842：转译耗尽 → SettlementAbort → 409 + typed stage（非玩家补写 CTA）。
    assert issue.status_code == 409, (
        f"expected translation-exhaustion 409, got {issue.status_code}: {issue.text}"
    )
    detail = issue.json().get("detail")
    assert isinstance(detail, dict), detail
    assert detail.get("stage") == "audience_translation_exhausted", detail
    assert detail.get("error_pack_path"), detail

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


def _setup_open_night_participant(tracer_client, *, kind: str):
    """new_game + 开夜 + 参与者。kind=offsite|temporary。

    返回 (client, game, participant, night_id)。
    """
    client = tracer_client
    new = client.post("/api/menu/new_game")
    _assert_not_bare_500(new, step="#1716 new_game")
    assert new.status_code == 200, new.text

    game = web_app.web_game
    assert game is not None
    night = an.open_night(game.db, game.state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])

    if kind == "temporary":
        participant = "临时行人甲"
        # 公开门放行 temporary；stream admission 不得因 can_summon reason 阻断收夜。
        temp = game.session._temporary_character(participant)
        assert participant in game.session.temporary_characters
        assert temp.name == participant
    else:
        assert kind == "offsite", kind
        participant = "洪承畴"
        assert participant in game.content.characters, participant
        game.db.conn.execute(
            "UPDATE characters SET location=?, transit_to='' WHERE name=?",
            ("shaanxi", participant),
        )
        game.db.conn.commit()

    return client, game, participant, night_id


def _assert_court_break_closed(game, body: dict, night_id: int, *, remote: str) -> None:
    """外部可见契约：court_break、夜关闭、参与者无殿上 presence/entrance 账。"""
    assert body.get("court_action") == "court_break", body
    assert not body.get("admission"), body
    _wait_pending_writes(game)
    assert an.get_open_night(game.db) is None
    night_row = game.db.conn.execute(
        "SELECT status FROM audience_nights WHERE id=?", (night_id,),
    ).fetchone()
    assert night_row is not None
    assert str(night_row["status"]) == an.NIGHT_STATUS_CLOSED, dict(night_row)
    # #1716 durable 物理账：场外/临时收夜不得写入该人 entrance/presence。
    assert remote not in an.persons_present_tonight(game.db, night_id), remote
    assert remote not in an.persons_entered_tonight(game.db, night_id), remote
    for entry in an.list_ledger(game.db, night_id):
        names = entry.get("person_names") or []
        if remote not in names:
            continue
        tags = entry.get("tags") or []
        assert an.TAG_ENTER not in tags, entry
        assert str(entry.get("presence_effect") or "") not in {
            an.PRESENCE_ENTER, "enter",
        }, entry
