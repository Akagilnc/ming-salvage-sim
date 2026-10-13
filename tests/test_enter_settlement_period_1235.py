from __future__ import annotations
import asyncio
import web_app
from ming_sim import audience_night as an
from ming_sim.models import TurnPhase
from tests.conftest import MONTH_OPEN_KEYS
from tests.conftest import stub_audience_translate
from tests.test_court_break_player_lock_1727 import _active_minister
from tests.test_court_break_player_lock_1727 import _client
from tests.sse_helpers import parse_sse_event_pairs
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





_IN_FLIGHT_DETAIL = "收夜中止：本夜仍有未完成回话（在飞/挂起），chat_turn_ids=[9]。夜保持开启，可原地重试。"
_GATE_BUSY_DETAIL = "月末结算或上一步写入进行中，请稍候再操作。"


# ── 轻量 canned 边界（与 #498 web tracer 同形，仅中和 LLM）────────────────










def _open_night_with_unextracted_reply(game, minister, reply="臣愿肩起此事。"):
    """票面夹具：开夜 + 回话已落、story 抽取未落（extract_status 待补）。"""
    db, state = game.db, game.state
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    an.ensure_summon_enter(db, nid, minister)
    ctid = db.create_chat_turn(state, minister, "sess-1235", 0, night_id=nid)
    db.persist_minister_reply(minister, int(state.turn), reply, ctid)

    assert len(db.reign.list_unextracted_replies(night_id=nid)) >= 1

    return nid, ctid




# ── 1. 未了续跑：未落账回话退朝不 409，自动接续至月完 ────────────────────


# ── 2. 点即入：capture 先于 await/close（失败前已入核账，失败后出展示态）──




# ── 3. 真失败另形：pending 抽取仍失败 → 人话 + 展示态退出 ──────────────






# ── 4. AC3 不回归：settling 恢复条 / 批红下发 ────────────────────────────






def test_accept_creator_atomic_only_one_true(game, monkeypatch):
    """#1235 r6：双 accept 仅一 True——原子 INSERT 裁定创建者，禁后置见行假 True。

    monkeypatch get 恒 None 模拟双侧预检同空（交错窗）；连调两次须 (True, False)。
    旧后置见行路径会 (True, True) 或 IntegrityError；本测有牙。
    """
    from ming_sim.month_open_snapshot import accept_settlement_period

    db, state, _ = game
    turn = int(state.turn)
    real_get = db.month_open_snapshots.get
    monkeypatch.setattr(db.month_open_snapshots, "get", lambda _t: None)

    first = accept_settlement_period(db, state)
    second = accept_settlement_period(db, state)
    assert (first, second) == (True, False)

    # 行确实只建一次（绕过恒 None 补丁读真库）
    before = {k: int(state.metrics[k]) for k in ("国库", "内库", "民心", "皇威")}
    assert real_get(turn) == before
    state.metrics["国库"] += 7
    third = accept_settlement_period(db, state)
    assert third is False
    assert real_get(turn) == before
    assert real_get(turn + 1) is None


# ── 5. accept 后 gate/HTTPException 拒收 → 不得留孤儿核账展示态 ──────────












# ── 5. SP1 #1241：断线→重连 e2e tracer（#1220 US14）──────────────────────


def test_true_failure_pending_translation_exits_display(web_game, monkeypatch, tmp_path):
    """AC2 / #1353 fold-in：drain 真失败 → 失败单源 + settlement_display 退出（≠ 未了在办）。"""
    from ming_sim.exceptions import LLMUnavailable

    game = web_game
    minister = _active_minister(game)
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    # #1842：收夜 catch-up 认转译水位；真失败注入转译缝（旧抽取 drain 已退役）。
    def _boom_translate(prompt, llm_config):
        del prompt, llm_config
        raise LLMUnavailable("fixture unavailable", code="llm_error")

    stub_audience_translate(monkeypatch, _boom_translate)
    _click_before(game.state)
    turn = int(game.state.turn)
    nid, ctid = _open_night_with_unextracted_reply(game, minister)

    # 观测：await 通过后 close 前应已 capture
    saw_capture = {}

    real_close = web_app._auto_close_open_night_gate_free

    def _close_observing(g, **kw):
        saw_capture["snap"] = g.db.month_open_snapshots.get(int(g.state.turn))
        return real_close(g, **kw)

    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", _close_observing)

    async def go():
        async with _client() as client:
            return await client.post("/api/decree/advance_without_edict/stream")

    resp = asyncio.run(go())
    # #1842：转译单轮失败标 pending；过月耗尽 → SSE error（typed stage）。
    assert resp.status_code == 200, resp.text
    kind, detail = parse_sse_event_pairs(resp.text)[-1]
    assert kind == "error"
    assert detail.get("stage") == "audience_translation_exhausted", detail
    pack = detail.get("error_pack_path")
    assert pack, detail
    # join-before-close：耗尽在 auto_close 前 → close 钩未跑
    assert saw_capture == {}, saw_capture
    # 真失败另形：展示态退出（点即入曾发生后 exit）
    assert game.db.month_open_snapshots.get(turn) is None
    payload = game.state_payload()
    assert payload["turn"]["settlement_display"] is False
    for k in MONTH_OPEN_KEYS:
        assert payload["metrics"][k] == int(game.state.metrics[k])  # 活值，非冻快照
    # 夜保持开（0036 原意），可重按过月
    assert an.get_night(game.db, nid)["status"] == an.NIGHT_STATUS_OPEN

    assert len(game.db.reign.list_unextracted_replies(night_id=nid)) >= 1

    assert game.db.reign.get_story_extract_status(ctid) in ("", "pending")


def test_advance_http_reject_after_accept_exits_display(web_game, monkeypatch):
    """#1235 r1 D：退朝 accept 后非阻塞会话闸拒收 → 出展示态。

    HTTPException 非 ValueError 子类；须经 settled_ok 失败臂收口，禁孤儿快照。
    """
    game = web_game
    from tests.month_chain_helpers import canned_full_settlement
    canned_full_settlement(monkeypatch)
    before = _click_before(game.state)
    turn = int(game.state.turn)
    saw = {}

    gate = game._runtime_write_gate()
    acquire = type(gate).acquire

    def _busy_once(lock, blocking=True, timeout=-1):
        if lock is gate and not saw and game.db.month_open_snapshots.get(turn) is not None:
            # 仅在锁资源边界制造一次占用；受理、拒收、失败清快照仍走真实入口。
            saw["snap"] = game.db.month_open_snapshots.get(turn)
            assert blocking is False
            assert acquire(lock, blocking=False)
            try:
                return acquire(lock, blocking=blocking, timeout=timeout)
            finally:
                lock.release()
        return acquire(lock, blocking=blocking, timeout=timeout)

    monkeypatch.setattr(type(gate), "acquire", _busy_once)

    async def go():
        async with _client() as client:
            return await client.post("/api/decree/advance_without_edict/stream")

    resp = asyncio.run(go())
    assert resp.status_code == 200, resp.text
    kind, detail = parse_sse_event_pairs(resp.text)[-1]
    assert kind == "error"
    assert detail["status_code"] == 409
    # 点即入曾发生
    assert saw.get("snap") == before
    # 拒收后不得留孤儿核账展示态
    assert game.db.month_open_snapshots.get(turn) is None
    assert game.state_payload()["turn"]["settlement_display"] is False
    # 相位仍常态（非 settling/awaiting）——AC3 路径未误触
    assert game.state.turn_phase not in (
        TurnPhase.SETTLING.value, TurnPhase.AWAITING_DECISION.value,
    )

def _click_before(state) -> dict[str, int]:
    return {k: int(state.metrics[k]) for k in MONTH_OPEN_KEYS}
