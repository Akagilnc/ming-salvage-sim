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

from types import SimpleNamespace

import httpx
import pytest

import web_app
from ming_sim import audience_night as an

_IN_FLIGHT_DETAIL = "收夜中止：本夜仍有未完成回话（在飞/挂起），chat_turn_ids=[9]。夜保持开启，可原地重试。"
_GATE_BUSY_DETAIL = "月末结算或上一步写入进行中，请稍候再操作。"


# ── 轻量 canned 边界（与 #498 web tracer 同形，仅中和 LLM）────────────────


@pytest.fixture
def web_game(tmp_path, monkeypatch, _offline_scene_beat_generator):
    """真实 WebGame；LLM 边界 canned。与 #498 fixture 同形。"""
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    # #544 / #1353 r6：高亮判官同属回话后 LLM 边界——离线中和。
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
        if game.db.characters.get_character_status(name)[0] == "active":
            return name
    raise AssertionError("no active ming minister")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_app.app), base_url="http://t",
    )




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
    assert real_get(turn) is not None
    third = accept_settlement_period(db, state)
    assert third is False


# ── 5. accept 后 gate/HTTPException 拒收 → 不得留孤儿核账展示态 ──────────












# ── 5. SP1 #1241：断线→重连 e2e tracer（#1220 US14）──────────────────────
