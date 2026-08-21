"""#1490 / #1492 批红轨契约。

#1490：
1. 接收端：缺字段 → SSE error 且仍 pending；带齐字段重交 → decided。
   经 httpx.ASGITransport 真 POST /api/decree/resolve_decisions/stream。
2. 生成端：dossier options 含 dossier_id / dossier_decision。
3. bind 保带能力字段的 dossier: event_id。

#1492 follow-up：
A. bind 对无能力字段的 dossier: 前缀解绑；due-commitment 同形不批红卡死。
D. 命中 allowed 后从服务端 option 重建 label/hint/能力字段，客户端只留 note。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

import ming_sim.decree as decree_mod
import ming_sim.session as session_mod
import web_app
from ming_sim.models import TurnPhase
from tests.dossier_test_helpers import rejected_verdict


@pytest.fixture
def web_game(tmp_path, monkeypatch, _offline_scene_beat_generator):
    """真实 WebGame + ASGI 入口；仅中和构造/LLM 边界（与 #498/#1235 同形）。"""
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    # 回话后高亮判官属 LLM 边界——离线中和，禁 sk-test 打真网。
    monkeypatch.setattr(web_app, "run_highlight_judge", lambda **_k: [])
    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", game)
    yield game
    try:
        game.session.close()
    except Exception:
        pass


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_app.app), base_url="http://t",
    )


async def _post_resolve(choices: list[dict]) -> httpx.Response:
    async with _client() as client:
        return await client.post(
            "/api/decree/resolve_decisions/stream",
            json={"choices": choices},
        )


def _plant_dossier_awaiting(db, state):
    """种 QA 同形：dossier 批红待裁 + resolve_context（含 candidate_events，触发 bind）。"""
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="密查陕西驿卒",
        target_kind="issue",
        target_id="river-works",
    )
    options = [
        {
            "label": "强颁",
            "hint": "以中旨强行颁出",
            "dossier_id": dossier_id,
            "dossier_decision": "force_promulgated",
        },
        {
            "label": "收回",
            "hint": "收回此道准旨",
            "dossier_id": dossier_id,
            "dossier_decision": "withdrawn",
        },
        {
            "label": "留中",
            "hint": "留待下月重判",
            "dossier_id": dossier_id,
            "dossier_decision": "hold",
        },
    ]
    db.save_pending_decisions(state.turn, [{
        "event_id": f"dossier:{dossier_id}",
        "title": "批红待裁",
        "context": "密查陕西驿卒",
        "rejection_reason": "科臣封驳",
        "opposition": "东林",
        "options": options,
    }])
    db.save_resolve_context(
        state.turn,
        "诏曰密查",
        "待续邸报",
        {"candidate_events": [{"id": "ev_border", "title": "边警"}]},
        secret_orders=[],
        relevant_memories=[],
    )
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    return dossier_id


def test_missing_dossier_fields_stay_pending_then_full_retry_decides(
    web_game, monkeypatch,
):
    """失败形（#1490 QA）：缺 dossier_id → error 且 pending；带齐字段 → decided。
    经 ASGI 真 HTTP POST /api/decree/resolve_decisions/stream；真实 WebGame，
    仅 stub phase2 LLM 边界。"""
    db, state = web_game.db, web_game.state
    dossier_id = _plant_dossier_awaiting(db, state)

    phase2_calls: list[list] = []

    def _phase2(_state, _db, *_a, **_k):
        rows = list(_db.list_pending_decisions(int(_state.turn)))
        phase2_calls.append(rows)
        _db.clear_pending_decisions(int(_state.turn))
        return "邸报：批红已落。"

    monkeypatch.setattr(session_mod, "resolve_decisions_phase2", _phase2)

    # ① 缺字段（与 QA m02-first-issue-pihong-choices 同形）
    incomplete = {"label": "强颁", "hint": "", "note": "准。先济关宁边饷。"}
    r1 = asyncio.run(_post_resolve([incomplete]))
    assert r1.status_code == 200, r1.text
    assert "event: error" in r1.text, r1.text
    assert "event: done" not in r1.text
    assert any(
        token in r1.text for token in ("批红", "dossier", "非法", "选项")
    ), r1.text

    row = db.list_pending_decisions(state.turn)[0]
    assert row["status"] == "pending", (
        f"非法载荷绝不可落 decided，got status={row['status']!r} choice={row['choice']!r}"
    )
    assert row["choice"] is None
    assert phase2_calls == [], "校验失败不得进入 phase2"

    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)

    # ② 带齐字段重交 → 成功
    full = {
        "label": "强颁",
        "hint": "以中旨强行颁出",
        "note": "准。先济关宁边饷。",
        "dossier_id": dossier_id,
        "dossier_decision": "force_promulgated",
    }
    r2 = asyncio.run(_post_resolve([full]))
    assert r2.status_code == 200, r2.text
    assert "event: done" in r2.text, r2.text
    assert "event: error" not in r2.text
    assert len(phase2_calls) == 1
    decided_row = phase2_calls[0][0]
    assert decided_row["status"] == "decided"
    choice = decided_row["choice"] or {}
    assert choice.get("dossier_id") == dossier_id
    assert choice.get("dossier_decision") == "force_promulgated"


def test_rescript_decision_options_carry_dossier_capability_fields(game, monkeypatch):
    """生成端正常路径：dossier 类 decision 的 options 含 dossier_id / dossier_decision。"""
    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="特旨清核河工",
        target_kind="issue",
        target_id="river-works",
        payload={"mode": "ordinary"},
    )

    def provider(_dossiers, _state):
        return [rejected_verdict(dossier_id)]

    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: object())
    monkeypatch.setattr(
        decree_mod,
        "simulate_season_with_payload",
        lambda _simulator, _state, _db, _decree_text, _previous, **kwargs: (
            "本月邸报。", kwargs["simulator_payload"],
        ),
    )

    result = decree_mod.resolve_directives(
        state, db, None, None, [object()], "清核河工",
        content=content, promulgation_verdict_provider=provider,
    )

    assert result.awaiting is True
    dossier_rows = [
        d for d in result.decisions
        if str(d.get("event_id") or "") == f"dossier:{dossier_id}"
    ]
    assert len(dossier_rows) == 1, result.decisions
    options = dossier_rows[0]["options"]
    assert options, "批红 options 不得为空"
    for opt in options:
        assert opt.get("dossier_id") == dossier_id, opt
        assert opt.get("dossier_decision") in {
            "force_promulgated", "withdrawn", "hold",
        }, opt
        assert isinstance(opt.get("hint"), str), opt

    stored = db.list_pending_decisions(state.turn)
    stored_dossier = [
        d for d in stored
        if str(d.get("event_id") or "") == f"dossier:{dossier_id}"
    ]
    assert stored_dossier
    for opt in stored_dossier[0]["options"]:
        assert opt.get("dossier_id") == dossier_id
        assert opt.get("dossier_decision") in {
            "force_promulgated", "withdrawn", "hold",
        }


def test_bind_preserves_dossier_event_id():
    """#1490 接收端病灶：bind 不得把 dossier: 前缀 event_id 当 off-snapshot 解绑。"""
    from ming_sim.settlement_payload import bind_decisions_to_candidate_events

    decisions = [{
        "event_id": "dossier:8",
        "title": "批红待裁",
        "options": [{
            "label": "强颁",
            "dossier_id": 8,
            "dossier_decision": "force_promulgated",
        }],
    }]
    payload = {"candidate_events": [{"id": "ev1", "title": "边警"}]}
    out = bind_decisions_to_candidate_events(decisions, payload)
    assert out[0]["event_id"] == "dossier:8"


def test_bind_unbinds_dossier_prefix_without_capability_fields():
    """#1492 A：due-commitment 形 origin_ref=dossier:N + 纯 {label,hint} options
    不得保留 dossier: 前缀——否则 submit 空对空放行后 phase2 批红卡死。"""
    from ming_sim.settlement_payload import bind_decisions_to_candidate_events

    decisions = [{
        "event_id": "dossier:12",
        "title": "承诺到期核验",
        "options": [
            {"label": "准其销号", "hint": "事已办结"},
            {"label": "着再催办", "hint": "期限宽延"},
        ],
    }]
    payload = {"candidate_events": [{"id": "ev1", "title": "边警"}]}
    out = bind_decisions_to_candidate_events(decisions, payload)
    assert "event_id" not in out[0] or not str(out[0].get("event_id") or "").startswith(
        "dossier:"
    ), out[0]


def _plant_due_commitment_shaped_awaiting(db, state, *, dossier_id: int = 12):
    """种 due-commitment 同形：event_id=dossier:N，options 仅 {label,hint}。"""
    options = [
        {"label": "准其销号", "hint": "事已办结"},
        {"label": "着再催办", "hint": "期限宽延"},
    ]
    db.save_pending_decisions(state.turn, [{
        "event_id": f"dossier:{dossier_id}",
        "title": "承诺到期核验",
        "context": "清丈之诺届期",
        "options": options,
    }])
    db.save_resolve_context(
        state.turn,
        "诏曰核验",
        "待续邸报",
        {"candidate_events": [{"id": "ev_border", "title": "边警"}]},
        secret_orders=[],
        relevant_memories=[],
    )
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)


def test_due_commitment_shaped_submit_does_not_poison_or_deadlock(
    web_game, monkeypatch,
):
    """#1492 A 真 HTTP：due-commitment 形提交后不落 poisoned decided、不批红卡死。
    无能力字段 → 不作批红轨；phase2 _chosen_rescript_actions 不得抛。"""
    from ming_sim.decree import _chosen_rescript_actions

    db, state = web_game.db, web_game.state
    _plant_due_commitment_shaped_awaiting(db, state, dossier_id=12)

    phase2_calls: list[list] = []

    def _phase2(_state, _db, *_a, **_k):
        rows = list(_db.list_pending_decisions(int(_state.turn)))
        # 真消费缝：即便 DB 仍留 dossier: 前缀，无能力 options 也不得抛批红非法
        actions = _chosen_rescript_actions(rows)
        assert actions == [], actions
        phase2_calls.append(rows)
        _db.clear_pending_decisions(int(_state.turn))
        return "邸报：承诺已核。"

    monkeypatch.setattr(session_mod, "resolve_decisions_phase2", _phase2)

    choice = {"label": "准其销号", "hint": "事已办结", "note": "准销。"}
    r = asyncio.run(_post_resolve([choice]))
    assert r.status_code == 200, r.text
    assert "event: error" not in r.text, r.text
    assert "event: done" in r.text, r.text
    assert "批红决策载荷非法" not in r.text
    assert len(phase2_calls) == 1
    decided_row = phase2_calls[0][0]
    assert decided_row["status"] == "decided"
    stored_choice = decided_row["choice"] or {}
    assert stored_choice.get("label") == "准其销号"
    assert stored_choice.get("note") == "准销。"
    assert not stored_choice.get("dossier_decision")


def test_lying_label_rebuilt_from_server_option(web_game, monkeypatch):
    """#1492 D 真 HTTP：合法能力对 + 撒谎 label/hint → 落库取服务端 option，客户端只留 note。"""
    db, state = web_game.db, web_game.state
    dossier_id = _plant_dossier_awaiting(db, state)

    phase2_calls: list[list] = []

    def _phase2(_state, _db, *_a, **_k):
        rows = list(_db.list_pending_decisions(int(_state.turn)))
        phase2_calls.append(rows)
        _db.clear_pending_decisions(int(_state.turn))
        return "邸报：批红已落。"

    monkeypatch.setattr(session_mod, "resolve_decisions_phase2", _phase2)

    lying = {
        "label": "收回",  # 撒谎：能力对是强颁
        "hint": "收回此道准旨",
        "note": "准。先济关宁边饷。",
        "dossier_id": dossier_id,
        "dossier_decision": "force_promulgated",
    }
    r = asyncio.run(_post_resolve([lying]))
    assert r.status_code == 200, r.text
    assert "event: done" in r.text, r.text
    assert "event: error" not in r.text
    assert len(phase2_calls) == 1
    choice = phase2_calls[0][0]["choice"] or {}
    assert choice.get("dossier_id") == dossier_id
    assert choice.get("dossier_decision") == "force_promulgated"
    assert choice.get("label") == "强颁", choice
    assert choice.get("hint") == "以中旨强行颁出", choice
    assert choice.get("note") == "准。先济关宁边饷。"


def test_parse_rescript_capability_pair_rejects_non_positive_and_unknown():
    """#1494 共享校验器：正整数 id + 支持动作枚举；其余一律 None。"""
    from ming_sim.settlement_payload import parse_rescript_capability_pair

    assert parse_rescript_capability_pair({
        "dossier_id": 3, "dossier_decision": "hold",
    }) == (3, "hold")
    assert parse_rescript_capability_pair({
        "dossier_id": "7", "dossier_decision": "withdrawn",
    }) == (7, "withdrawn")
    # 非正 / 未知动作 / 缺字段 / 非 dict
    assert parse_rescript_capability_pair({
        "dossier_id": 0, "dossier_decision": "hold",
    }) is None
    assert parse_rescript_capability_pair({
        "dossier_id": -1, "dossier_decision": "hold",
    }) is None
    assert parse_rescript_capability_pair({
        "dossier_id": 3, "dossier_decision": "promulgated",
    }) is None
    assert parse_rescript_capability_pair({
        "dossier_id": 3, "dossier_decision": None,
    }) is None
    assert parse_rescript_capability_pair({"dossier_decision": "hold"}) is None
    assert parse_rescript_capability_pair(None) is None
    assert parse_rescript_capability_pair("force_promulgated") is None


def test_mixed_legal_illegal_options_illegal_choice_stays_pending(
    web_game, monkeypatch,
):
    """#1494：混合合法/非法 options 时，选非法能力对保持 pending、不进 phase2。

    allowed 只收共享校验器放行的对；非法残对（负 id / 未知 decision）不得空对空放行。
    """
    db, state = web_game.db, web_game.state
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="密查陕西驿卒",
        target_kind="issue",
        target_id="river-works",
    )
    options = [
        {
            "label": "强颁",
            "hint": "以中旨强行颁出",
            "dossier_id": dossier_id,
            "dossier_decision": "force_promulgated",
        },
        {
            "label": "伪收回",
            "hint": "残对负 id",
            "dossier_id": -9,
            "dossier_decision": "withdrawn",
        },
        {
            "label": "伪留中",
            "hint": "未知动作",
            "dossier_id": dossier_id,
            "dossier_decision": "promulgated",
        },
        {
            "label": "裸字段",
            "hint": "仅非 None",
            "dossier_id": dossier_id,
            "dossier_decision": None,
        },
    ]
    db.save_pending_decisions(state.turn, [{
        "event_id": f"dossier:{dossier_id}",
        "title": "批红待裁",
        "context": "密查陕西驿卒",
        "options": options,
    }])
    db.save_resolve_context(
        state.turn,
        "诏曰密查",
        "待续邸报",
        {"candidate_events": [{"id": "ev_border", "title": "边警"}]},
        secret_orders=[],
        relevant_memories=[],
    )
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)

    phase2_calls: list[list] = []

    def _phase2(_state, _db, *_a, **_k):
        rows = list(_db.list_pending_decisions(int(_state.turn)))
        phase2_calls.append(rows)
        _db.clear_pending_decisions(int(_state.turn))
        return "邸报：不应到此。"

    monkeypatch.setattr(session_mod, "resolve_decisions_phase2", _phase2)

    # ① 选非法残对（负 id）→ error + pending
    illegal = {
        "label": "伪收回",
        "hint": "残对负 id",
        "dossier_id": -9,
        "dossier_decision": "withdrawn",
    }
    r1 = asyncio.run(_post_resolve([illegal]))
    assert r1.status_code == 200, r1.text
    assert "event: error" in r1.text, r1.text
    assert "event: done" not in r1.text
    row = db.list_pending_decisions(state.turn)[0]
    assert row["status"] == "pending", row
    assert row["choice"] is None
    assert phase2_calls == [], "非法选择不得进入 phase2"

    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)

    # ② 选未知动作枚举 → 同样 fail-closed
    unknown = {
        "label": "伪留中",
        "hint": "未知动作",
        "dossier_id": dossier_id,
        "dossier_decision": "promulgated",
    }
    r2 = asyncio.run(_post_resolve([unknown]))
    assert r2.status_code == 200, r2.text
    assert "event: error" in r2.text, r2.text
    assert phase2_calls == []
    assert db.list_pending_decisions(state.turn)[0]["status"] == "pending"

    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)

    # ③ 同批合法 option 仍可过
    legal = {
        "label": "强颁",
        "hint": "以中旨强行颁出",
        "note": "准。",
        "dossier_id": dossier_id,
        "dossier_decision": "force_promulgated",
    }
    r3 = asyncio.run(_post_resolve([legal]))
    assert r3.status_code == 200, r3.text
    assert "event: done" in r3.text, r3.text
    assert "event: error" not in r3.text
    assert len(phase2_calls) == 1
    choice = phase2_calls[0][0]["choice"] or {}
    assert choice.get("dossier_id") == dossier_id
    assert choice.get("dossier_decision") == "force_promulgated"
    assert choice.get("label") == "强颁"


def test_ordinary_event_with_hallucinated_capability_submits(
    web_game, monkeypatch,
):
    """#1494-F1：普通 event_id + options 幻觉能力对不得入批红轨。

    submit 须与 bind/phase2 同用「dossier: 前缀 AND 能力对」合取；仅能力对
    会把普通决策块当批红校验 → 客户端无能力字段的 choice 永卡 AWAITING。
    """
    db, state = web_game.db, web_game.state
    # 普通候选事件决策：真实 event_id（无 dossier: 前缀），但 LLM 幻觉出能力字段
    event_id = "mao_wenlong"
    db.save_pending_decisions(state.turn, [{
        "event_id": event_id,
        "title": "边警",
        "context": "辽东来报",
        "options": [
            {"label": "准其销号", "hint": "事已办结"},
            {
                "label": "强颁",
                "hint": "幻觉批红",
                "dossier_id": 3,
                "dossier_decision": "hold",
            },
        ],
    }])
    db.save_resolve_context(
        state.turn,
        "诏曰边警",
        "待续邸报",
        {"candidate_events": [{"id": event_id, "title": "边警"}]},
        secret_orders=[],
        relevant_memories=[],
    )
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)

    phase2_calls: list[list] = []

    def _phase2(_state, _db, *_a, **_k):
        rows = list(_db.list_pending_decisions(int(_state.turn)))
        phase2_calls.append(rows)
        _db.clear_pending_decisions(int(_state.turn))
        return "邸报：边警已核。"

    monkeypatch.setattr(session_mod, "resolve_decisions_phase2", _phase2)

    # 客户端按普通决策提交（无能力字段）——不得 SSE error / 批红卡死
    choice = {"label": "准其销号", "hint": "事已办结", "note": "准销。"}
    r = asyncio.run(_post_resolve([choice]))
    assert r.status_code == 200, r.text
    assert "event: error" not in r.text, r.text
    assert "event: done" in r.text, r.text
    assert "批红选择必须是本案提供的强颁、收回或留中选项" not in r.text
    assert len(phase2_calls) == 1
    decided = phase2_calls[0][0]
    assert decided["status"] == "decided"
    stored = decided["choice"] or {}
    assert stored.get("label") == "准其销号"
    assert stored.get("note") == "准销。"
    assert not stored.get("dossier_decision")
