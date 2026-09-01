"""#1468 过月主链 e2e tracer——真实 HTTP 入口两月循环 + #1353 fold-in 钉。

回应 owner「测试全绿流程走不通」：全仓接缝钉照不到跨接缝状态机脱节；
本文件从真实 HTTP 入口走玩家基本循环，仅在最外层 LLM 接缝 deterministic stub
（不 mock 内部函数 / 结算核 / 收夜编排）。

主 tracer：new_game → 召对开夜/回话/收夜 → 拟旨 → POST /api/decree/issue/stream
（消费 SSE 到终态）→ 月+1 → 再一月。起点置十一月以真跨 year rollover
（year+1 且 period 回 1）。断言 turn+2 与 year/period 跨年安全月序 +2、无 409 死锁、
无裸 500、闸/账双向等量（成功过月 count==len(pending)==0）。
至少一轮 chat 返回后不预排空尾随写，直接拟旨/颁诏，用 Event 卡住 stub 尾随写
完成时机以钉「颁诏受理 vs 尾随写」接缝（禁 sleep 竞猜）。

#1353 fold-in 钉：
- 植入欠账后一次过月动作成功（流内处理、无 409、无 CTA、账清、月+1）
- 真死 LLM stub → 失败单源（通传未达），非待补 CTA/409；夜保持可重按
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import ming_sim.agents as agents_mod
import ming_sim.cli_backend as cli_backend
import ming_sim.decree as decree_mod
import ming_sim.memories as memories_mod
import ming_sim.mindreading as mindreading_mod
import ming_sim.session as session_mod
import web_app
from ming_sim import audience_night as an
from ming_sim.session_write_queue import _is_barrier_ticket, get_session_write_queue
from tests.test_session_write_queue_1353 import wait_pending_writes as _wait_pending_writes


# ── outermost LLM seams only ─────────────────────────────────────────────


class _CannedExtractor:
    def run(self, _material):
        return SimpleNamespace(content='{"facts":[]}')


class _BoomExtractor:
    def run(self, _material):
        raise RuntimeError("抽取持续失败·#1468 负向钉")


class _CannedEndorsementExtractor:
    def run(self, _material):
        return SimpleNamespace(content='{"endorsements":[]}')


class _CannedMindreadingAgent:
    def run(self, _material):
        return SimpleNamespace(content="近臣低声：边饷事重。")


class _CannedMinisterAgent:
    """非流式 session.chat 读 agent.run().content（非 generator）。"""

    def run(self, *_a, **_k):
        return SimpleNamespace(content="臣已知悉，边饷当速清。", tools=[])


class _CannedRelationJudge:
    """召对/收夜关系判官外层——零事件 canned，禁真网。"""

    def run(self, _prompt):
        return SimpleNamespace(content='{"events":[]}')


def _stub_outer_llm_seams(monkeypatch) -> None:
    """只换最外层 LLM 工厂/调用；结算核、收夜、HTTP 路由全真跑。"""
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent",
        lambda *a, **k: _CannedExtractor(),
    )
    monkeypatch.setattr(
        agents_mod, "create_endorsement_extractor_agent",
        lambda *a, **k: _CannedEndorsementExtractor(),
    )
    monkeypatch.setattr(
        mindreading_mod, "create_mindreading_agent",
        lambda *a, **k: _CannedMindreadingAgent(),
    )
    # #642：召对/收夜关系判官同属外层 LLM 缝——漏 stub 会在有 window 时真网挂起，
    # 票据不归还 → xdist 下 _wait_pending_writes 墙钟假红。
    monkeypatch.setattr(
        agents_mod, "create_relation_judge_agent",
        lambda *a, **k: _CannedRelationJudge(),
    )
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
    # 月末推演 LLM 边界（sim/extract/拟诏/章记）；resolve_directives 结算核真跑。
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod,
        "llm_promulgation_verdicts",
        lambda dossiers, _state, **_kwargs: [
            {"dossier_id": row["id"], "decision": "promulgated"} for row in dossiers
        ],
    )
    monkeypatch.setattr(
        decree_mod,
        "simulate_season_with_payload",
        lambda *a, **k: (
            "本月邸报：边饷已清，流寇未息。",
            k.get("simulator_payload") or {},
        ),
    )
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "create_score_extractor_module_agent", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        decree_mod,
        "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({}, "out", "in"),
    )
    monkeypatch.setattr(
        session_mod, "write_decree_with_agno",
        lambda *a, **k: "奉天承运，诏曰：着户部清核辽饷。",
    )
    monkeypatch.setattr(
        memories_mod,
        "run_agent_text",
        lambda *a, **k: '{"body": "本月边饷已清，暗流暗涌。", "tags": ["边饷"]}',
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


def _install_canned_minister(game) -> None:
    game.session.registry.get = lambda _ch: _CannedMinisterAgent()


def _install_trail_hold(game, release: threading.Event):
    """卡住读心/抽取尾随写完成时机（Event 控制，禁 sleep 竞猜）。

    返回 (restore_fn,)——race 轮结束后还原真方法。
    """
    real_mind = game._trail_mindreading_after_reply
    real_extract = game._trail_extraction_after_reply

    def _held_mind(*args, **kwargs):
        assert release.wait(timeout=5.0), "mind trail hold timed out"
        return real_mind(*args, **kwargs)

    def _held_extract(*args, **kwargs):
        assert release.wait(timeout=5.0), "extract trail hold timed out"
        return real_extract(*args, **kwargs)

    game._trail_mindreading_after_reply = _held_mind
    game._trail_extraction_after_reply = _held_extract

    def _restore() -> None:
        game._trail_mindreading_after_reply = real_mind
        game._trail_extraction_after_reply = real_extract

    return _restore


def _arm_barrier_open_event(game):
    """包装 session queue 的 barrier claim/open 接缝：票入 _open 后 wait_prior 时置 Event。

    与 test_web_audience_night_498 同形——只观察既有 wait_prior 接缝，不改生产、不加钩子。
    返回 (barrier_open_event, restore_fn)。
    """
    q = get_session_write_queue(game)
    barrier_open = threading.Event()
    real_wait_prior = q.wait_prior

    def _observe_wait_prior(ticket):
        # barrier() 先把票写入 _open 再 wait_prior——此处即 claim/open 接缝。
        if _is_barrier_ticket(ticket):
            barrier_open.set()
        return real_wait_prior(ticket)

    q.wait_prior = _observe_wait_prior  # type: ignore[method-assign]

    def _restore() -> None:
        q.wait_prior = real_wait_prior  # type: ignore[method-assign]

    return barrier_open, _restore


def _release_trails_when_barrier_open(
    barrier_open: threading.Event, release: threading.Event,
) -> None:
    """侧线程：显式等待并断言 barrier 真打开后，再放行 stub 尾随写。

    禁 deadline/sleep 轮询；禁『未见 barrier 也放行』。
    """

    def _run() -> None:
        assert barrier_open.wait(timeout=5.0), (
            "barrier ticket never claimed/opened; refusing unconditional trail release"
        )
        release.set()

    threading.Thread(target=_run, daemon=True, name="trail-release-on-barrier").start()


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
    resp = client.get("/api/audience/extraction/pending")
    _assert_not_bare_500(resp, step="GET /api/audience/extraction/pending")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, dict)
    return body


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
) -> dict:
    """玩家真入口：POST /api/decree/issue/stream，消费 SSE 到终态。

    返回归一化 body：done → payload；decisions → payload + awaiting_decision=True。
    event:error 且 status_code=409 → 死锁断言红；其它 error 亦红。
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


def _play_one_month(
    client: TestClient,
    *,
    minister: str,
    month_label: str,
    race_trailing_writes: bool = False,
) -> int:
    """召对 → 拟旨 → 流式颁诏结算。返回推进后的 turn。

    race_trailing_writes=True：chat 返回后不预排空尾随写，直接拟旨/颁诏；
    用 Event 卡住 stub 尾随完成时机，屏障开后放行——钉真实竞态窗。
    """
    state = _get_state(client)
    turn_before = _turn_of(state)
    assert state["turn"]["phase"] not in (
        "settling", "awaiting_decision",
    ), f"{month_label}: unexpected phase before month play: {state['turn']!r}"

    game = web_app.web_game
    assert game is not None

    trail_release: threading.Event | None = None
    barrier_open: threading.Event | None = None
    restore_trails = None
    restore_barrier_signal = None
    if race_trailing_writes:
        trail_release = threading.Event()
        restore_trails = _install_trail_hold(game, trail_release)
        barrier_open, restore_barrier_signal = _arm_barrier_open_event(game)

    try:
        chat = client.post(
            f"/api/ministers/{minister}/chat",
            json={"message": f"边饷如何？本月{month_label}召对。"},
        )
        _assert_not_bare_500(chat, step=f"{month_label} chat")
        assert chat.status_code == 200, (
            f"{month_label} chat → {chat.status_code}: {chat.text}"
        )
        answer = str((chat.json() or {}).get("answer") or "")
        assert answer, f"{month_label}: empty minister answer"

        if race_trailing_writes:
            # 竞态窗：chat 已回但尾随票仍在——禁止预排空。
            pending_now = int(getattr(game, "_pending_writes_count", 0) or 0)
            assert pending_now > 0, (
                f"{month_label}: expected in-flight trailing writes after chat, "
                f"got count={pending_now}"
            )
            assert barrier_open is not None and trail_release is not None
            _release_trails_when_barrier_open(barrier_open, trail_release)
        else:
            # 非竞态轮：拟旨/颁诏前放空尾随（短轮询，非真超时窗）。
            _wait_pending_writes(game)

        directive = client.post(
            "/api/directives",
            json={"text": f"着户部清核辽饷（{month_label}）。", "notes": ""},
        )
        _assert_not_bare_500(directive, step=f"{month_label} 拟旨")
        assert directive.status_code == 200, (
            f"{month_label} 拟旨 → {directive.status_code}: {directive.text}"
        )
        dirs = (directive.json() or {}).get("directives") or []
        assert dirs, f"{month_label}: directive list empty after POST"

        if not race_trailing_writes:
            _wait_pending_writes(game)

        body = _post_issue_stream(
            client, expected_turn=turn_before, step=f"{month_label} issue/stream",
        )
        if race_trailing_writes:
            # 主链结束后再钉一次：屏障票必须真打开过（非超时放行）。
            assert barrier_open is not None and barrier_open.is_set(), (
                f"{month_label}: issue/stream finished without barrier ticket open"
            )
        # 若 simulator canned 仍吐决策点，最短续跑：空批不得卡死主链。
        if body.get("awaiting_decision"):
            decisions = body.get("decisions") or []
            assert decisions, (
                f"{month_label}: awaiting_decision with empty decisions: {body!r}"
            )
            _resolve_decisions_via_stream(
                client, decisions, step=f"{month_label} resolve_decisions",
            )
    finally:
        # 禁无条件 trail_release.set()：仅 _release_trails_when_barrier_open
        # 在观察到 barrier_open 后才可置位；finally 只还原实例方法。
        if restore_trails is not None:
            restore_trails()
        if restore_barrier_signal is not None:
            restore_barrier_signal()

    _wait_pending_writes(game)
    after = _get_state(client)
    turn_after = _turn_of(after)
    assert turn_after == turn_before + 1, (
        f"{month_label}: turn {turn_before} → {turn_after}, expected +1; "
        f"phase={after.get('turn')!r}"
    )
    # 闸/账双向等量：成功过月后 count == len(pending) == 0（漏账或残债均红）。
    pending = _pending_payload(client)
    pending_list = pending.get("pending") or []
    count = int(pending.get("count") or 0)
    assert count == len(pending_list) == 0, (
        f"{month_label}: post-month pending not empty/eq: "
        f"count={count} len={len(pending_list)} body={pending!r}"
    )
    # 夜应收：无跨月开夜
    open_after = an.get_open_night(game.db)
    assert open_after is None or str(open_after.get("status")) == an.NIGHT_STATUS_CLOSED, (
        f"{month_label}: night still blocking after month advance: {open_after!r}"
    )
    return turn_after


# ── 主 tracer：两整月（起点十一月 → 真跨年） ────────────────────────────


def test_month_loop_two_months_via_http_entry(tracer_client):
    """HTTP 真入口起局走两个整月：turn+2 且 year rollover（period 回 1）、无 409、闸/账双向清零。

    M1 保留 post-chat 尾随写竞态窗（Event 控 stub）；M2 正常排空。
    """
    client = tracer_client

    new = client.post("/api/menu/new_game")
    _assert_not_bare_500(new, step="POST /api/menu/new_game")
    assert new.status_code == 200, new.text
    state0 = (new.json() or {}).get("state") or {}
    turn0 = _turn_of(state0)
    assert turn0 >= 1, state0.get("turn")
    minister = _pick_active_minister(state0)

    game = web_app.web_game
    assert game is not None
    _install_canned_minister(game)

    # 真跨年：新档默认 period=10；推到 11 月起走两月 → year+1 / period=1。
    # （只推 M1/M2 从 10 起会停在 12 月，year rollover 根本不执行。）
    game.state.period = 11
    game.db.save_state(game.state)
    state0 = _get_state(client)
    ord0 = _month_ord_of(state0)
    year0 = int((state0.get("turn") or {}).get("year") or 0)
    period0 = int((state0.get("turn") or {}).get("period") or 0)
    assert period0 == 11, state0.get("turn")
    assert ord0 > 0, state0.get("turn")

    # M1：chat 后不预排空尾随写，直接拟旨/流式颁诏（竞态窗）。
    turn1 = _play_one_month(
        client, minister=minister, month_label="M1", race_trailing_writes=True,
    )
    assert turn1 == turn0 + 1

    # 第二月：registry 仍挂 canned（begin_turn 不重建 registry.get 绑定）
    _install_canned_minister(web_app.web_game)
    turn2 = _play_one_month(
        client, minister=minister, month_label="M2", race_trailing_writes=False,
    )
    assert turn2 == turn0 + 2

    # 年月投影跨年钉：必须真执行 12→1 的 year+1（禁只靠 ord 算术蒙混）。
    state_end = _get_state(client)
    end_turn = state_end.get("turn") or {}
    assert _turn_of(state_end) == turn0 + 2
    assert int(end_turn.get("year") or 0) == year0 + 1, (
        f"year must roll +1: start={state0.get('turn')!r} end={end_turn!r}"
    )
    assert int(end_turn.get("period") or 0) == 1, (
        f"period must wrap to 1 after Dec: start={state0.get('turn')!r} end={end_turn!r}"
    )
    assert _month_ord_of(state_end) == ord0 + 2, (
        f"calendar must advance +2 months (year-safe): "
        f"start={state0.get('turn')!r} end={end_turn!r} "
        f"ord {ord0} → {_month_ord_of(state_end)}"
    )


# ── #1353 fold-in：带欠账一次过月成功 + 死透失败单源 ─────────────────────


def _plant_extraction_debt(game, minister: str, *, sess_tag: str) -> int:
    """生产同核欠账：开夜 + 回话落库未抽。返回 chat_turn_id。"""
    night = an.open_night(game.db, game.state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    an.ensure_summon_enter(game.db, nid, minister)
    ctid = game.db.create_chat_turn(game.state, minister, sess_tag, 0, night_id=nid)
    game.db.persist_minister_reply(minister, int(game.state.turn), "臣愿肩起此事。", ctid)
    assert int(game.db.count_pending_story_extractions(night_id=nid) or 0) >= 1
    return int(ctid)


def test_issue_with_extraction_debt_succeeds_once(tracer_client):
    """#1353 fold-in：植入欠账后一次过月成功——流内清账、无 409、无 CTA、月+1。"""
    from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE

    client = tracer_client

    new = client.post("/api/menu/new_game")
    _assert_not_bare_500(new, step="new_game (debt-ok)")
    assert new.status_code == 200, new.text
    state0 = (new.json() or {}).get("state") or {}
    turn0 = _turn_of(state0)
    ord0 = _month_ord_of(state0)
    minister = _pick_active_minister(state0)
    game = web_app.web_game
    assert game is not None

    ctid = _plant_extraction_debt(game, minister, sess_tag="sess-1468-debt-ok")

    # 颁诏须至少一条草案（与主 tracer 同形）；欠账在收夜流内清，不靠手动补写。
    directive = client.post(
        "/api/directives",
        json={"text": "着户部清核辽饷（debt-ok）。", "notes": ""},
    )
    _assert_not_bare_500(directive, step="debt-ok 拟旨")
    assert directive.status_code == 200, directive.text

    body = _post_issue_stream(
        client, expected_turn=turn0, step="debt-ok issue/stream",
    )
    assert CLI_RUNNER_PLAYER_MESSAGE not in json.dumps(body, ensure_ascii=False)
    if body.get("awaiting_decision"):
        decisions = body.get("decisions") or []
        assert decisions, f"awaiting_decision empty: {body!r}"
        _resolve_decisions_via_stream(
            client, decisions, step="debt-ok resolve",
        )

    _wait_pending_writes(game)
    after = _get_state(client)
    assert _turn_of(after) == turn0 + 1, (
        f"debt-ok: turn {turn0} → {_turn_of(after)}; phase={after.get('turn')!r}"
    )
    assert _month_ord_of(after) == ord0 + 1
    pending = _pending_payload(client)
    pending_list = pending.get("pending") or []
    count = int(pending.get("count") or 0)
    assert count == len(pending_list) == 0, (
        f"debt-ok: post-month pending not empty: count={count} body={pending!r} ctid={ctid}"
    )
    open_after = an.get_open_night(game.db)
    assert open_after is None or str(open_after.get("status")) == an.NIGHT_STATUS_CLOSED, (
        f"debt-ok: night still blocking: {open_after!r}"
    )


def test_issue_extraction_llm_dead_single_source_not_cta(tracer_client, monkeypatch):
    """#1353 fold-in：抽取 LLM 死透 → 失败单源（通传未达），非待补 CTA/409；夜可重按。

    非流式兼容口轻钉：结构化 HTTP 400/412 + detail 单源（流式主链另由主 tracer 覆盖）。
    """
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

    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent",
        lambda *a, **k: _BoomExtractor(),
    )

    issue = client.post("/api/decree/issue", json={"expected_turn": turn0})
    _assert_not_bare_500(issue, step="dead-llm issue")
    # 欠账类不得再 409 打回；走既定 LLM 失败单源面。
    assert issue.status_code != 409, (
        f"debt-class 409 deleted; got {issue.status_code}: {issue.text}"
    )
    assert issue.status_code in (400, 412), (
        f"expected LLM single-source status, got {issue.status_code}: {issue.text}"
    )
    detail = issue.json().get("detail")
    if isinstance(detail, dict):
        detail_text = str(detail.get("message") or "")
        detail_blob = str(detail)
    else:
        detail_text = str(detail or "")
        detail_blob = detail_text
    assert CLI_RUNNER_PLAYER_MESSAGE in detail_text or CLI_RUNNER_PLAYER_MESSAGE in detail_blob, (
        f"failure single source missing: {detail!r}"
    )
    # 禁玩家可见待补/补写 CTA 语义
    assert "待补" not in detail_text
    assert "补写" not in detail_text
    assert "chat_turn" not in detail_text

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


def test_issue_1716_offsite_court_break_skips_admission(tracer_client):
    """#1716 独占缝：已开夜 + 场外大臣经真实 /chat/stream 发收夜口令。

    只证 admission 未消费、done.court_action=court_break、夜关闭。
    grant 字符串 amount → shape 单测；done 计数 → App race 测；整月清账 → 既有 month-loop。
    """
    client = tracer_client
    new = client.post("/api/menu/new_game")
    _assert_not_bare_500(new, step="#1716 new_game")
    assert new.status_code == 200, new.text

    game = web_app.web_game
    assert game is not None

    night = an.open_night(game.db, game.state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])

    remote = "洪承畴"
    assert remote in game.content.characters, remote
    game.db.conn.execute(
        "UPDATE characters SET location=?, transit_to='' WHERE name=?",
        ("shaanxi", remote),
    )
    game.db.conn.commit()

    consumed: list[str] = []
    real_consume = game.session.consume_audience_admission

    def _spy_consume(character, **kwargs):
        consumed.append(str(character.name))
        return real_consume(character, **kwargs)

    game.session.consume_audience_admission = _spy_consume  # type: ignore[method-assign]

    # stream 主链在 command verdict 前仍跑 agent.run generator；禁真网。
    class _StreamAgent:
        def run(self, *_a, **_k):
            yield SimpleNamespace(event="RunContent", content="臣领旨。")
            yield SimpleNamespace(content="", tools=[])

        def get_last_run_output(self):
            return None

    agent = _StreamAgent()
    game.session.registry.get = lambda _ch: agent

    stream = client.post(
        f"/api/ministers/{remote}/chat/stream",
        json={"message": "退朝"},
    )
    _assert_not_bare_500(stream, step="#1716 chat/stream 场外退朝")
    assert stream.status_code == 200, stream.text
    events = _parse_sse(stream.text)
    types = [str(ev.get("event") or "") for ev in events]
    assert "error" not in types, events
    assert "done" in types, events
    done_raw = next(ev for ev in events if ev.get("event") == "done").get("data") or "{}"
    done = json.loads(done_raw) if isinstance(done_raw, str) else done_raw
    assert isinstance(done, dict), done
    assert done.get("court_action") == "court_break", done
    assert not done.get("admission"), done
    assert consumed == [], f"退朝不得 consume admission，got {consumed}"

    _wait_pending_writes(game)
    assert an.get_open_night(game.db) is None
    night_row = game.db.conn.execute(
        "SELECT status FROM audience_nights WHERE id=?", (night_id,),
    ).fetchone()
    assert night_row is not None
    assert str(night_row["status"]) == an.NIGHT_STATUS_CLOSED, dict(night_row)
