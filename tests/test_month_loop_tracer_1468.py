"""#1468 过月主链 e2e tracer——真实 HTTP 入口两月循环 + #1353 fold-in 钉。

回应 owner「测试全绿流程走不通」：全仓接缝钉照不到跨接缝状态机脱节；
本文件从真实 HTTP 入口走玩家基本循环，仅在最外层 LLM 接缝 deterministic stub
（不 mock 内部函数 / 结算核 / 收夜编排）。

主 tracer：new_game → 召对开夜/回话/收夜 → 拟旨 → POST /api/decree/issue
→ 月+1 → 再一月。断言 turn+2 与 year/period 跨年安全月序 +2、无 409 死锁、
无裸 500、闸/账双向等量（成功过月 count==len(pending)==0）。

#1353 fold-in 钉：
- 植入欠账后一次过月动作成功（流内处理、无 409、无 CTA、账清、月+1）
- 真死 LLM stub → 失败单源（通传未达），非待补 CTA/409；夜保持可重按

速度红线：单条 ≤30s；罩类断言用可注入小值（本片不靠真实超时窗）。
"""

from __future__ import annotations

import time
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
        # 等召对尾随（读心/抽取）落完再关库，避免 teardown 与后台写竞态。
        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline:
            pending = int(getattr(game, "_pending_writes_count", 0) or 0)
            if pending <= 0:
                break
            time.sleep(0.01)
        try:
            game.session.close()
        except Exception:
            pass
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


def _wait_pending_writes(game, *, timeout_s: float = 2.0) -> None:
    """等召对尾随（读心/抽取）放闸——拟旨/颁诏抢 write_gate 前必须空。

    轮询间隔 0.01s 级，禁等真实 LLM/超时窗。
    """
    deadline = time.perf_counter() + float(timeout_s)
    while time.perf_counter() < deadline:
        pending = int(getattr(game, "_pending_writes_count", 0) or 0)
        if pending <= 0:
            # 再确认 gate 可非阻塞获取（无结算/尾随持锁）
            gate = getattr(game, "_write_gate", None)
            if gate is None:
                return
            if gate.acquire(blocking=False):
                gate.release()
                return
        time.sleep(0.01)
    raise AssertionError(
        f"pending writes did not drain in {timeout_s}s; "
        f"count={getattr(game, '_pending_writes_count', None)}"
    )


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


def _play_one_month(client: TestClient, *, minister: str, month_label: str) -> int:
    """召对 → 拟旨 → 颁诏结算。返回推进后的 turn。"""
    state = _get_state(client)
    turn_before = _turn_of(state)
    assert state["turn"]["phase"] not in (
        "settling", "awaiting_decision",
    ), f"{month_label}: unexpected phase before month play: {state['turn']!r}"

    chat = client.post(
        f"/api/ministers/{minister}/chat",
        json={"message": f"边饷如何？本月{month_label}召对。"},
    )
    _assert_not_bare_500(chat, step=f"{month_label} chat")
    assert chat.status_code == 200, f"{month_label} chat → {chat.status_code}: {chat.text}"
    answer = str((chat.json() or {}).get("answer") or "")
    assert answer, f"{month_label}: empty minister answer"

    game = web_app.web_game
    assert game is not None
    # 召对 epilogue 尾随仍可能持 write_gate；拟旨/颁诏前必须放空（短轮询，非真超时窗）。
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

    _wait_pending_writes(game)
    issue = client.post(
        "/api/decree/issue",
        json={"expected_turn": turn_before},
    )
    _assert_not_bare_500(issue, step=f"{month_label} issue")
    assert issue.status_code != 409, (
        f"{month_label}: 409 deadlock on issue; body={issue.text}"
    )
    assert issue.status_code == 200, (
        f"{month_label} issue → {issue.status_code}: {issue.text}"
    )
    body = issue.json()
    # 若 simulator canned 仍吐决策点，最短续跑：空批不得卡死主链。
    if body.get("awaiting_decision"):
        decisions = body.get("decisions") or []
        # canned 叙事无 <<DECISION>> → 不应 awaiting；若 awaiting 空列表也属异常。
        assert decisions, (
            f"{month_label}: awaiting_decision with empty decisions: {body!r}"
        )
        # 最短：按首选项自动批红经真实 resolve 入口
        choices = []
        for d in decisions:
            opts = d.get("options") or ["准"]
            choices.append({
                "title": d.get("title") or d.get("id"),
                "choice": opts[0] if isinstance(opts[0], str) else str(opts[0]),
            })
        # resolve stream 是 SSE；同步 resolve 路径若无，走 stream 消费 done
        resolve = client.post(
            "/api/decree/resolve_decisions/stream",
            json={"choices": choices},
        )
        _assert_not_bare_500(resolve, step=f"{month_label} resolve_decisions")
        assert resolve.status_code == 200, resolve.text
        assert "event: error" not in resolve.text, resolve.text

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


# ── 主 tracer：两整月 ────────────────────────────────────────────────────


def test_month_loop_two_months_via_http_entry(tracer_client):
    """HTTP 真入口起局走两个整月：turn+2 且 year/period 月序+2、无 409、闸/账双向清零。"""
    client = tracer_client
    t0 = time.perf_counter()

    new = client.post("/api/menu/new_game")
    _assert_not_bare_500(new, step="POST /api/menu/new_game")
    assert new.status_code == 200, new.text
    state0 = (new.json() or {}).get("state") or {}
    turn0 = _turn_of(state0)
    ord0 = _month_ord_of(state0)
    assert turn0 >= 1, state0.get("turn")
    assert ord0 > 0, state0.get("turn")
    minister = _pick_active_minister(state0)

    game = web_app.web_game
    assert game is not None
    _install_canned_minister(game)

    turn1 = _play_one_month(client, minister=minister, month_label="M1")
    assert turn1 == turn0 + 1

    # 第二月：registry 仍挂 canned（begin_turn 不重建 registry.get 绑定）
    _install_canned_minister(web_app.web_game)
    turn2 = _play_one_month(client, minister=minister, month_label="M2")
    assert turn2 == turn0 + 2

    # 年月投影跨年钉：冻结 calendar 只让 turn 自增须红（mutation 自验）。
    state_end = _get_state(client)
    assert _turn_of(state_end) == turn0 + 2
    assert _month_ord_of(state_end) == ord0 + 2, (
        f"calendar must advance +2 months (year-safe): "
        f"start={state0.get('turn')!r} end={state_end.get('turn')!r} "
        f"ord {ord0} → {_month_ord_of(state_end)}"
    )

    elapsed = time.perf_counter() - t0
    assert elapsed <= 30.0, f"speed red line: tracer took {elapsed:.2f}s > 30s"


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
    t0 = time.perf_counter()

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

    issue = client.post("/api/decree/issue", json={"expected_turn": turn0})
    _assert_not_bare_500(issue, step="debt-ok issue")
    assert issue.status_code != 409, (
        f"fold-in forbids debt-class 409; body={issue.text}"
    )
    assert CLI_RUNNER_PLAYER_MESSAGE not in issue.text
    assert issue.status_code == 200, (
        f"debt-ok issue → {issue.status_code}: {issue.text}"
    )
    body = issue.json()
    if body.get("awaiting_decision"):
        decisions = body.get("decisions") or []
        assert decisions, f"awaiting_decision empty: {body!r}"
        choices = []
        for d in decisions:
            opts = d.get("options") or ["准"]
            choices.append({
                "title": d.get("title") or d.get("id"),
                "choice": opts[0] if isinstance(opts[0], str) else str(opts[0]),
            })
        resolve = client.post(
            "/api/decree/resolve_decisions/stream",
            json={"choices": choices},
        )
        _assert_not_bare_500(resolve, step="debt-ok resolve")
        assert resolve.status_code == 200, resolve.text
        assert "event: error" not in resolve.text, resolve.text

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

    elapsed = time.perf_counter() - t0
    assert elapsed <= 30.0, f"speed red line: debt-ok took {elapsed:.2f}s > 30s"


def test_issue_extraction_llm_dead_single_source_not_cta(tracer_client, monkeypatch):
    """#1353 fold-in：抽取 LLM 死透 → 失败单源（通传未达），非待补 CTA/409；夜可重按。"""
    from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE

    client = tracer_client
    t0 = time.perf_counter()

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

    elapsed = time.perf_counter() - t0
    assert elapsed <= 30.0, f"speed red line: dead-llm took {elapsed:.2f}s > 30s"
