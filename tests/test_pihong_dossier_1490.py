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
import json

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
        {
            "candidate_events": [{"id": "ev_border", "title": "边警"}],
            "transit_semantics": [],
        },
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


# ---------------------------------------------------------------------------
# #657 片2：C1 ＋ 五动作领域写（rescript_actions 模块级）
# ---------------------------------------------------------------------------

def _layer_a_option(**overrides):
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option
    base = {
        "label": "发帑赈济",
        "hint": "所安者饥民",
        "action_type": "assignment",
        "assignee_name": "",
        "target_kind": "region",
        "target_id": "shaanxi",
        "locality_scope": "single",
        "region_id": "shaanxi",
        "transaction_category": "督赈",
        "title": "陕西赈济",
        "deadline_months": 3,
    }
    base.update(overrides)
    return normalize_rescript_layer_a_option(base)


def _plant_urgent_desk(db, state, *, options=None, actor_name="杨嗣昌"):
    opts = options or [_layer_a_option(), _layer_a_option(label="缓征", hint="先赈后征")]
    db.save_rescript_drafts(int(state.turn), [{
        "title": "陕西告饥",
        "context": "秦地赤旱",
        "options": opts,
        "actor_name": actor_name,
        "actor_office": "兵部尚书",
        "actor_faction": "东林",
    }])
    db.conn.commit()
    desk = db.list_rescript_desk(int(state.turn))
    urgent = next(r for r in desk if r["kind"] == "rescript_draft")
    return urgent, opts


def test_657_c1_validate_rejects_stale_capability_and_desk_outsider(game):
    """C1.5 stale capability；desk 外键整批拒。"""
    from ming_sim import rescript_actions as ra
    db, state, _content = game
    urgent, opts = _plant_urgent_desk(db, state)
    key = urgent["decision_key"]
    with pytest.raises(ValueError, match="draft_capability|stale"):
        ra.validate_all([urgent], [{
            "decision_key": key,
            "action": "follow_draft",
            "draft_capability": "not-a-real-cap",
            "label": opts[0]["label"],
        }])
    with pytest.raises(ValueError, match="不在当前 desk"):
        ra.validate_all([urgent], [{
            "decision_key": "rescript_draft:999:0",
            "action": "hold",
            "label": "留中",
        }])


def test_657_c1_decided_mismatch_rejects_and_cas0(game):
    """C1.3/C1.4：decided 不匹配 / 空 choice → 整批拒。"""
    from ming_sim import rescript_actions as ra
    db, state, _content = game
    urgent, opts = _plant_urgent_desk(db, state)
    key = urgent["decision_key"]
    # 先 hold 落 decided
    batch = ra.validate_all([urgent], [{
        "decision_key": key, "action": "hold", "label": "留中",
    }])
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=_content)
    row = db.list_rescript_drafts()
    hit = next(r for r in row if r["title"] == "陕西告饥")
    assert hit["status"] == "decided"
    # 构造 decided desk 行
    decided_row = {
        **urgent,
        "status": "decided",
        "choice": hit["choice"],
    }
    with pytest.raises(ValueError, match="不匹配"):
        ra.validate_all([decided_row], [{
            "decision_key": key, "action": "hold", "label": "另留",
        }])
    empty_decided = {**urgent, "status": "decided", "choice": None}
    with pytest.raises(ValueError, match="不匹配|缺请求"):
        ra.validate_all([empty_decided], [{
            "decision_key": key, "action": "hold", "label": "留中",
        }])


def test_657_p6_mapper_deliberate_preserve_free_text(game):
    """#657 Class3 P6：label/note/title/body 原文落库；title>80 响亮拒绝。"""
    from ming_sim import rescript_actions as ra
    db, state, content = game
    m = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' LIMIT 1"
    ).fetchone()
    mname = str(m["name"]) if m else "杨嗣昌"

    label = " 责成督赈 "
    note = "\n着即办理。\t"
    p = ra.map_rescript_option_or_choice({
        "action_type": "assignment", "label": label, "note": note, "hint": " h ",
        "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈", "assignee_name": mname,
        "title": " 陕赈 ",
    }, db=db, content=content, state=state)
    assert p["label"] == label
    assert p["hint"] == " h "
    assert p["title"] == " 陕赈 "
    assert p.get("_decree_text") == note

    title80 = "字" * 80
    p80 = ra.map_rescript_option_or_choice({
        "action_type": "assignment", "label": "x", "hint": "h",
        "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈", "assignee_name": mname,
        "title": title80,
    }, db=db, content=content, state=state)
    assert p80["title"] == title80
    with pytest.raises(ValueError, match="80"):
        ra.map_rescript_option_or_choice({
            "action_type": "assignment", "label": "x", "hint": "h",
            "target_kind": "region", "target_id": "shaanxi",
            "locality_scope": "single", "region_id": "shaanxi",
            "transaction_category": "督赈", "assignee_name": mname,
            "title": "字" * 81,
        }, db=db, content=content, state=state)

    # deliberate will 首尾空白 → issues 全等
    urgent, _ = _plant_urgent_desk(db, state)
    key = urgent["decision_key"]
    batch = ra.validate_all([urgent], [{
        "decision_key": key, "action": "deliberate", "label": "下部议",
    }])
    will_title = " 廷议题 "
    will_body = "\n臣请集议。\t"
    pre = ra.PrewriteResults(deliberate_by_key={
        key: {"title": will_title, "body": will_body},
    })
    ra.apply_rescript_batch(db, state, batch, pre, content=content)
    issue = db.conn.execute(
        "SELECT title, stage_text FROM issues WHERE origin_ref=?",
        (f"rescript_deliberate:{key}",),
    ).fetchone()
    assert issue is not None
    assert str(issue["title"]) == will_title
    assert str(issue["stage_text"]) == will_body

    # stop_condition：经 canonical_choice（validate 入口）保真 dict，mapper 落 payload 结构化相等
    army0 = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()
    stop = {f"army.{army0['id']}.arrears": "<=0"} if army0 else {"metrics.民心": ">=0"}
    choice = ra.canonical_choice({
        "decision_key": "rescript_draft:1:0",
        "action": "midzhi",
        "action_type": "assignment",
        "label": "x", "hint": "h",
        "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈", "assignee_name": mname,
        "commitment_kind": "until_stop",
        "stop_condition": stop,
        "deadline_months": 1,
    })
    assert choice["stop_condition"] == stop
    assert isinstance(choice["stop_condition"], dict)
    # JSON 串入口同样还原为 dict
    choice_s = ra.canonical_choice({
        "decision_key": "rescript_draft:1:0",
        "action": "midzhi",
        "stop_condition": json.dumps(stop, ensure_ascii=False),
    })
    assert choice_s["stop_condition"] == stop
    mapped = ra.map_rescript_option_or_choice(choice, mode="midzhi", db=db, content=content, state=state)
    assert mapped["stop_condition"] == stop


def test_657_default_hold_missing_and_empty_action(game):
    """#657 Class2 V1–V5：缺行/keyed 无 action/keyed 空 action → hold；
    decided 精确重放过、不匹配拒；revise 锚 + 空 action 不重新 default。"""
    from ming_sim import rescript_actions as ra
    db, state, content = game

    # V1 省略该行
    urgent, _ = _plant_urgent_desk(db, state, actor_name="杨嗣昌")
    key = urgent["decision_key"]
    batch = ra.validate_all([urgent], [], default_hold_missing=True)
    assert key in batch.default_hold_keys
    assert batch.items[0].choice.get("action") == "hold"

    # V2 keyed 无 action
    batch2 = ra.validate_all([urgent], [{"decision_key": key}], default_hold_missing=True)
    assert key in batch2.default_hold_keys
    assert batch2.items[0].choice.get("action") == "hold"

    # V3 keyed 空 action
    batch3 = ra.validate_all(
        [urgent], [{"decision_key": key, "action": ""}], default_hold_missing=True,
    )
    assert key in batch3.default_hold_keys
    assert batch3.items[0].choice.get("action") == "hold"

    # apply V2 → decided + 辜负
    ra.apply_rescript_batch(db, state, batch2, ra.PrewriteResults(), content=content)
    hit = next(r for r in db.list_rescript_drafts() if r["title"] == "陕西告饥")
    assert hit["status"] == "decided"
    assert (hit["choice"] or {}).get("action") == "hold"
    edges = db.conn.execute(
        "SELECT event_kind FROM relation_edge_events WHERE target=? AND event_kind=?",
        ("杨嗣昌", "辜负"),
    ).fetchall()
    assert edges, "default hold 须写辜负信用事件"

    # V4 decided 精确重放仍过；空/不匹配仍整批拒（不 default）
    stored = dict(hit["choice"] or {})
    stored.setdefault("decision_key", key)
    decided_desk = {
        **urgent, "status": "decided", "choice": stored,
    }
    batch4 = ra.validate_all([decided_desk], [stored], default_hold_missing=True)
    assert batch4.items[0].already_applied
    assert key not in batch4.default_hold_keys
    with pytest.raises(ValueError):
        ra.validate_all(
            [decided_desk], [{"decision_key": key}], default_hold_missing=True,
        )
    with pytest.raises(ValueError):
        ra.validate_all(
            [decided_desk],
            [{"decision_key": key, "action": "hold", "label": "另留"}],
            default_hold_missing=True,
        )

    # V5 pending 已应用 return_revise 锚 + 空 action → 拒，禁止重新 default
    db.conn.execute("DELETE FROM pending_decisions WHERE kind='rescript_draft'")
    urgent2, opts2 = _plant_urgent_desk(db, state, actor_name="杨嗣昌")
    key2 = urgent2["decision_key"]
    revise_choice = ra.canonical_choice({
        "decision_key": key2, "action": "return_revise", "label": "发回改票",
        "applied_from_revision_round": 0,
    })
    # 模拟已应用 revise 锚：pending + choice=return_revise + round 已 +1 + prior 非空
    db.conn.execute(
        "UPDATE pending_decisions SET choice_json=?, revision_round=1, "
        "prior_options_json=? WHERE turn=? AND idx=? AND kind='rescript_draft'",
        (
            json.dumps(revise_choice, ensure_ascii=False),
            json.dumps([opts2], ensure_ascii=False),
            int(urgent2["source_turn"] if urgent2.get("source_turn") is not None else urgent2["turn"]),
            int(urgent2["idx"]),
        ),
    )
    db.conn.commit()
    desk2 = db.list_rescript_desk(int(state.turn))
    row2 = next(r for r in desk2 if r["decision_key"] == key2)
    assert row2["status"] == "pending"
    with pytest.raises(ValueError):
        ra.validate_all(
            [row2], [{"decision_key": key2, "action": ""}], default_hold_missing=True,
        )
    # equal 重放 → already_applied，不进 default_hold_keys
    batch5 = ra.validate_all([row2], [revise_choice], default_hold_missing=True)
    assert batch5.items[0].already_applied
    assert key2 not in batch5.default_hold_keys


def test_657_http_default_hold_keyed_empty_action_and_betray(web_game, monkeypatch):
    """#657 Class2 V6 必跑：真 HTTP keyed 仅 decision_key → 持久 hold + 辜负。"""
    db, state = web_game.db, web_game.state
    _657_install_real_phase2_llm_boundary(monkeypatch)
    opt = _layer_a_option()
    db.conn.execute("DELETE FROM pending_decisions WHERE kind='rescript_draft'")
    db.save_rescript_drafts(int(state.turn), [{
        "title": "HTTP默认留中",
        "context": "c",
        "options": [opt, _layer_a_option(label="备", hint="h")],
        "actor_name": "杨嗣昌",
        "actor_office": "兵部尚书",
        "actor_faction": "东林",
    }])
    db.save_resolve_context(
        int(state.turn), "诏", "邸报",
        {"candidate_events": [], "transit_semantics": []},
        secret_orders=[], relevant_memories=[],
    )
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    db.conn.commit()
    desk = db.list_rescript_desk(int(state.turn))
    key = next(r["decision_key"] for r in desk if r["title"] == "HTTP默认留中")

    r = asyncio.run(_post_resolve([{"decision_key": key}]))
    assert r.status_code == 200, r.text
    hit = next(row for row in db.list_rescript_drafts() if row["title"] == "HTTP默认留中")
    assert hit["status"] == "decided"
    assert (hit["choice"] or {}).get("action") == "hold"
    edges = db.conn.execute(
        "SELECT event_kind FROM relation_edge_events WHERE target=? AND event_kind=?",
        ("杨嗣昌", "辜负"),
    ).fetchall()
    assert edges, "HTTP default hold 须写辜负"


def test_657_five_actions_domain_writes(game):
    """五动作至少各一领域断言；summon 只 CAS decided。"""
    from ming_sim import rescript_actions as ra
    from ming_sim.decree_vocabulary import derive_draft_capability
    db, state, content = game

    # --- hold ---
    urgent, _opts = _plant_urgent_desk(db, state, actor_name="杨嗣昌")
    key = urgent["decision_key"]
    batch = ra.validate_all([urgent], [{
        "decision_key": key, "action": "hold", "label": "留中",
    }])
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=content)
    hit = next(r for r in db.list_rescript_drafts() if r["title"] == "陕西告饥")
    assert hit["status"] == "decided"
    assert (hit["choice"] or {}).get("action") == "hold"
    # 信用辜负边
    edges = db.conn.execute(
        "SELECT event_kind FROM relation_edge_events WHERE target=? AND event_kind=?",
        ("杨嗣昌", "辜负"),
    ).fetchall()
    assert edges, "hold 须写辜负信用事件"

    # --- follow_draft (assignment duty route) ---
    db.conn.execute("DELETE FROM pending_decisions WHERE kind='rescript_draft'")
    opt = _layer_a_option(assignee_name="")  # duty route B
    urgent, _ = _plant_urgent_desk(db, state, options=[opt, _layer_a_option(label="备", hint="b")])
    key = urgent["decision_key"]
    before = len(db.list_decree_dossiers())
    batch = ra.validate_all([urgent], [{
        "decision_key": key,
        "action": "follow_draft",
        "draft_capability": opt["draft_capability"],
        "label": opt["label"],
    }])
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=content)
    after = db.list_decree_dossiers()
    assert len(after) > before
    created = after[-1]
    assert created["action_type"] == "assignment"
    assert created["status"] in {"proposed", "promulgated", "executing"} or created["status"]

    # --- midzhi ---
    db.conn.execute("DELETE FROM pending_decisions WHERE kind='rescript_draft'")
    urgent, _ = _plant_urgent_desk(db, state)
    key = urgent["decision_key"]
    before = len(db.list_decree_dossiers())
    midzhi_choice = {
        "decision_key": key,
        "action": "midzhi",
        "label": "中旨赈济",
        "action_type": "assignment",
        "target_kind": "region",
        "target_id": "shaanxi",
        "locality_scope": "single",
        "region_id": "shaanxi",
        "transaction_category": "督赈",
        "title": "中旨赈陕",
        "deadline_months": 2,
    }
    batch = ra.validate_all([urgent], [midzhi_choice])
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=content)
    mids = [d for d in db.list_decree_dossiers() if d.get("mode") == "midzhi"]
    assert mids, "midzhi 须落 mode=midzhi 案卷"
    assert mids[-1]["status"] == "proposed"

    # --- deliberate ---
    db.conn.execute("DELETE FROM pending_decisions WHERE kind='rescript_draft'")
    urgent, _ = _plant_urgent_desk(db, state)
    key = urgent["decision_key"]
    batch = ra.validate_all([urgent], [{
        "decision_key": key, "action": "deliberate", "label": "下部议",
    }])
    pre = ra.PrewriteResults(deliberate_by_key={
        key: {"title": "廷议陕西赈济", "body": "臣请集议赈策。", "stance": "主赈"},
    })
    ra.apply_rescript_batch(db, state, batch, pre, content=content)
    issue = db.conn.execute(
        "SELECT title, origin_ref FROM issues WHERE origin_ref=?",
        (f"rescript_deliberate:{key}",),
    ).fetchone()
    assert issue is not None and str(issue["origin_ref"] or "") == f"rescript_deliberate:{key}"

    # --- summon：只 decided，不写 ledger 正文 ---
    db.conn.execute("DELETE FROM pending_decisions WHERE kind='rescript_draft'")
    urgent, _ = _plant_urgent_desk(db, state)
    key = urgent["decision_key"]
    batch = ra.validate_all([urgent], [{
        "decision_key": key, "action": "summon",
        "label": "召见", "summon_target": "杨嗣昌",
    }])
    ledger_before = db.conn.execute("SELECT COUNT(*) AS c FROM story_ledger_entries").fetchone()["c"]
    result = ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=content)
    assert key in result.summon_keys
    hit = next(r for r in db.list_rescript_drafts() if r["title"] == "陕西告饥")
    assert hit["status"] == "decided"
    assert (hit["choice"] or {}).get("action") == "summon"
    ledger_after = db.conn.execute("SELECT COUNT(*) AS c FROM story_ledger_entries").fetchone()["c"]
    assert ledger_after == ledger_before

    # consumed_epoch 列不存在
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(pending_decisions)").fetchall()}
    assert "consumed_epoch" not in cols
    _ = derive_draft_capability  # import seam kept warm




# ---------------------------------------------------------------------------
# #657 helpers：跨进程 HTTP 崩溃重入（C1.1 / C1.2 共用；禁第二 worker 族）
# ---------------------------------------------------------------------------

def _657_db_path_of(game_or_path) -> str:
    if isinstance(game_or_path, str):
        return game_or_path
    path = getattr(game_or_path, "db_path", None)
    if path:
        return str(path)
    db = getattr(game_or_path, "db", None)
    return str(getattr(db, "path", None) or getattr(db, "db_path", None) or "")


def _657_install_real_phase2_llm_boundary(monkeypatch_or_module):
    """只中和 phase2 LLM 边界；保留 resolve_decisions_phase2 真结算/推月。"""
    import ming_sim.decree as dm

    def _set(name, value):
        if hasattr(monkeypatch_or_module, "setattr"):
            monkeypatch_or_module.setattr(dm, name, value)
        else:
            setattr(dm, name, value)

    _set("create_season_simulator_agent", lambda *a, **k: None)
    _set("create_json_sanitizer_agent", lambda *a, **k: None)
    _set("create_score_extractor_module_agent", lambda *a, **k: None)
    _set("build_extractor_shared_context", lambda *a, **k: "ctx")
    _set("extract_scores_by_modules_with_agno", lambda *a, **k: ({}, "o", "i"))
    _set("create_ending_summary_agent", lambda *a, **k: None)
    _set("create_chapter_memory_agent", lambda *a, **k: None)
    _set("create_rescript_draft_agent", lambda *a, **k: None)
    # 章节/关系酿制：禁 sk-test 打真网；record 空操作
    _set("record_chapter_memory", lambda *a, **k: None)
    _set("_make_relation_brew_runner", lambda *a, **k: None)
    # subprocess worker 内无 monkeypatch 对象时同步写 dm


def _657_subprocess_resolve(
    db_path: str,
    choices: list,
    *,
    crash: str = "",
    prewrite_mode: str = "",
    timeout: float = 180.0,
) -> dict:
    """同文件可复用：子进程真 HTTP POST resolve_decisions/stream。

    crash:
      - "" 正常跑完（真 phase2 + LLM 边界 stub）
      - "phase2" 领域 ① 已 commit 后、进入 phase2 时 os._exit 真杀进程
    prewrite_mode:
      - "" 无 prewrite LLM
      - "revise" stub 改票新 options
      - "deliberate" stub 廷议意愿
    stdout 只回传 @@SUMMARY@@ JSON；真杀进程无 summary 时父进程认 returncode。
    """
    import os
    import subprocess
    import sys
    import textwrap

    worker = textwrap.dedent(
        r"""
        import asyncio, json, os, sys
        db_path = sys.argv[1]
        choices = json.loads(sys.argv[2])
        crash = sys.argv[3]
        prewrite_mode = sys.argv[4]
        os.environ["MING_SIM_DB"] = db_path
        os.environ["OPENAI_API_KEY"] = "sk-test"
        os.environ.pop("MING_SIM_LLM_BACKEND", None)

        import httpx
        import ming_sim.beat_orchestration as bo
        import ming_sim.decree as dm
        import ming_sim.rescript_actions as ra
        import ming_sim.session as session_mod
        import web_app
        from ming_sim.models import TurnPhase

        def _det_gen(_inputs):
            name = str(getattr(_inputs, "person_name", "") or "") or "臣"
            return f"{name}入殿请安。"

        bo.create_llm_beat_generator = lambda _cfg: _det_gen
        web_app.load_runtime_llm = lambda: {}
        web_app.run_highlight_judge = lambda **_k: []

        # 真 phase2：只 stub LLM 边界
        dm.create_season_simulator_agent = lambda *a, **k: None
        dm.create_json_sanitizer_agent = lambda *a, **k: None
        dm.create_score_extractor_module_agent = lambda *a, **k: None
        dm.build_extractor_shared_context = lambda *a, **k: "ctx"
        dm.extract_scores_by_modules_with_agno = lambda *a, **k: ({}, "o", "i")
        dm.create_ending_summary_agent = lambda *a, **k: None
        dm.create_chapter_memory_agent = lambda *a, **k: None
        dm.create_rescript_draft_agent = lambda *a, **k: None
        dm.record_chapter_memory = lambda *a, **k: None
        dm._make_relation_brew_runner = lambda *a, **k: None

        if crash == "phase2":
            def _kill_at_phase2(*a, **k):
                # §E.2：领域 commit 后、写 extracted 前真杀进程（禁 SSE 捕获后正常 close）
                os._exit(97)

            session_mod.resolve_decisions_phase2 = _kill_at_phase2
            dm.resolve_decisions_phase2 = _kill_at_phase2

        if prewrite_mode == "revise":
            def _fake_prewrite(batch, **kwargs):
                out = {}
                for it in batch.items:
                    if getattr(it, "needs_revise_llm", False) or str(
                        (it.choice or {}).get("action") or ""
                    ) == "return_revise":
                        out[it.decision_key] = [
                            {"label": "新拟甲", "hint": "h1", "draft_capability": "cap-new-a",
                             "action_type": "assignment", "target_kind": "region",
                             "target_id": "shaanxi", "locality_scope": "single",
                             "region_id": "shaanxi", "transaction_category": "督赈",
                             "deadline_months": 2},
                            {"label": "新拟乙", "hint": "h2", "draft_capability": "cap-new-b"},
                        ]
                return ra.PrewriteResults(revise_by_key=out)
            ra.run_prewrite_llms = _fake_prewrite
        elif prewrite_mode == "deliberate":
            def _fake_prewrite(batch, **kwargs):
                out = {}
                for it in batch.items:
                    out[it.decision_key] = {
                        "title": "廷议", "body": "臣请集议。", "stance": "主赈",
                    }
                return ra.PrewriteResults(deliberate_by_key=out)
            ra.run_prewrite_llms = _fake_prewrite

        game = web_app.WebGame(fresh=False)
        web_app.web_game = game
        # 保持待裁
        game.state.turn_phase = TurnPhase.AWAITING_DECISION.value
        game.session.state.turn_phase = TurnPhase.AWAITING_DECISION.value
        game.db.save_state(game.state)

        summary = {"db_path": db_path, "body": choices}
        try:
            async def _post():
                transport = httpx.ASGITransport(app=web_app.app)
                async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                    return await client.post(
                        "/api/decree/resolve_decisions/stream",
                        json={"choices": choices},
                    )
            r = asyncio.run(_post())
            summary.update({
                "status_code": r.status_code,
                "text_head": (r.text or "")[:2500],
                "done": "event: done" in (r.text or ""),
                "error": "event: error" in (r.text or ""),
                "turn": int(game.state.turn),
            })
        except Exception as exc:
            summary.update({"exc": type(exc).__name__, "msg": str(exc)[:500]})
        finally:
            try:
                game.session.close()
            except Exception:
                pass
        print("@@SUMMARY@@" + json.dumps(summary, ensure_ascii=False), flush=True)
        """
    )
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    body_json = json.dumps(choices, ensure_ascii=False, separators=(",", ":"))
    proc = subprocess.run(
        [sys.executable, "-c", worker, db_path, body_json, crash, prewrite_mode],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=root,
        env={**os.environ, "MING_SIM_DB": db_path, "OPENAI_API_KEY": "sk-test"},
    )
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    marker = "@@SUMMARY@@"
    body_canon = body_json
    if marker not in out:
        # 真杀进程：无 finally/summary；returncode 97 即 §E.2 可观测终止
        if crash == "phase2" and proc.returncode == 97:
            return {
                "db_path": db_path,
                "_returncode": 97,
                "_killed": True,
                "_body_canonical": body_canon,
                "error": True,
                "done": False,
            }
        raise AssertionError(
            f"subprocess missing summary exit={proc.returncode}\n"
            f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    payload = out.split(marker, 1)[1].strip().splitlines()[0]
    data = json.loads(payload)
    data["_returncode"] = proc.returncode
    data["_body_canonical"] = body_canon
    data["_killed"] = False
    return data



def _657_plant_awaiting_web(web_game, *, drafts=None, decisions=None, title="陕西告饥"):
    """web_game 上种植急务/decision + resolve_context，相位 AWAITING_DECISION。"""
    from ming_sim.models import TurnPhase

    db, state = web_game.db, web_game.state
    db.conn.execute("DELETE FROM pending_decisions")
    db.conn.commit()
    if drafts:
        db.save_rescript_drafts(int(state.turn), drafts)
    if decisions:
        db.save_pending_decisions(int(state.turn), decisions)
    db.save_resolve_context(
        int(state.turn), "诏", "邸报",
        {"candidate_events": [], "transit_semantics": []},
        secret_orders=[], relevant_memories=[],
    )
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    web_game.state.turn_phase = TurnPhase.AWAITING_DECISION.value
    web_game.session.state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.conn.commit()
    return db.list_rescript_desk(int(state.turn))


def test_657_record_event_choice_failure_rolls_back_batch(game, monkeypatch):
    """Class 5：record_event_decision_choice 抛错 → 整批回滚，零 decided/零事件账。"""
    from ming_sim import rescript_actions as ra

    db, state, content = game
    opt = _layer_a_option()
    urgent, _ = _plant_urgent_desk(db, state, options=[opt, _layer_a_option(label="备", hint="b")])
    db.conn.execute(
        "INSERT OR IGNORE INTO events "
        "(id, title, kind, summary, urgency, severity, credibility, interests, audiences) "
        "VALUES ('ev-class5', '边警', 'test', 'class5', 1, 1, 50, '[]', '[]')"
    )
    db.save_pending_decisions(int(state.turn), [{
        "title": "边警",
        "context": "c",
        "options": [{"label": "打回", "hint": "驳回"}, {"label": "准", "hint": ""}],
        "event_id": "ev-class5",
    }])
    db.conn.commit()
    desk = db.list_rescript_desk(int(state.turn))
    u_key = next(r["decision_key"] for r in desk if r["kind"] == "rescript_draft")
    d_key = next(r["decision_key"] for r in desk if r["kind"] == "decision")

    def boom(*_a, **_k):
        raise RuntimeError("event ledger inject")

    monkeypatch.setattr(db, "record_event_decision_choice", boom)
    before_triggers = db.conn.execute(
        "SELECT COUNT(*) AS c FROM event_triggers"
    ).fetchone()["c"]
    batch = ra.validate_all(desk, [
        {
            "decision_key": u_key,
            "action": "follow_draft",
            "draft_capability": opt["draft_capability"],
            "label": opt["label"],
        },
        {"decision_key": d_key, "label": "打回", "hint": "驳回", "action": "decision"},
    ])
    with pytest.raises(RuntimeError, match="event ledger inject"):
        ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=content)
    # 整批回滚
    drafts = [r for r in db.list_rescript_drafts() if r["title"] == "陕西告饥"]
    assert drafts and drafts[0]["status"] == "pending"
    decs = db.list_pending_decisions(int(state.turn))
    assert decs and decs[0]["status"] == "pending"
    after_triggers = db.conn.execute(
        "SELECT COUNT(*) AS c FROM event_triggers"
    ).fetchone()["c"]
    assert after_triggers == before_triggers


def test_657_return_revise_round_prior_and_clear_anchor(web_game, monkeypatch):
    """C1.2：真 HTTP return_revise → ①后 phase2 前崩溃 → 同 DB 同 body 重 POST
    round 不双增 → 清锚后新 capability HTTP follow_draft。复用 C1.1 subprocess helper。"""
    from ming_sim.models import TurnPhase
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    db_path = _657_db_path_of(web_game)
    opt = normalize_rescript_layer_a_option({
        "label": "发帑赈济", "hint": "所安者饥民",
        "action_type": "assignment", "assignee_name": "",
        "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈", "deadline_months": 2,
    })
    desk = _657_plant_awaiting_web(web_game, drafts=[{
        "title": "改票急务", "context": "c",
        "options": [opt, {"label": "备", "hint": "h", "draft_capability": "x"}],
        "actor_name": "杨嗣昌", "actor_office": "兵部尚书", "actor_faction": "东林",
    }])
    key = desk[0]["decision_key"]
    body = [{
        "decision_key": key,
        "action": "return_revise",
        "label": "发回改票",
        "applied_from_revision_round": 0,
        "draft_capability": opt["draft_capability"],
    }]
    body_canon = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    # 释放父进程连接，交给子进程
    web_game.session.close()

    r1 = _657_subprocess_resolve(db_path, body, crash="phase2", prewrite_mode="revise")
    assert r1.get("_killed") is True or r1.get("_returncode") == 97
    assert r1["_body_canonical"] == body_canon

    # 库态：round+1、仍 pending、锚在、extracted 空
    from ming_sim.content import GameContent
    from ming_sim.db import GameDB
    content = GameContent.load()
    probe = GameDB(db_path, content)
    try:
        hit = next(r for r in probe.list_rescript_drafts() if r["title"] == "改票急务")
        assert hit["status"] == "pending"
        assert int(hit["revision_round"] or 0) == 1
        assert (hit["choice"] or {}).get("action") == "return_revise"
        assert len(hit["prior_options_json"] or []) == 1
        ctx = probe.get_resolve_context(int(probe.load_state().turn))
        assert ctx is None or ctx.get("extracted") is None
        new_caps = [str(o.get("draft_capability") or "") for o in (hit["options"] or [])]
        assert "cap-new-a" in new_caps
    finally:
        probe.close()

    # 同 body 重 POST → already_applied，round 不双增，phase2 完成清锚
    r2 = _657_subprocess_resolve(db_path, body, crash="", prewrite_mode="revise")
    assert r2.get("done") is True, r2
    assert r2["_body_canonical"] == body_canon

    probe = GameDB(db_path, content)
    try:
        hit = next(r for r in probe.list_rescript_drafts() if r["title"] == "改票急务")
        assert int(hit["revision_round"] or 0) == 1
        choice_after = hit["choice"] or {}
        assert choice_after == {} or choice_after is None or not choice_after
        # 清锚后 follow 新 capability
        state = probe.load_state()
        state.turn_phase = TurnPhase.AWAITING_DECISION.value
        probe.save_state(state)
        probe.save_resolve_context(
            int(state.turn), "诏", "邸报", {"candidate_events": [], "transit_semantics": []},
            secret_orders=[], relevant_memories=[],
        )
        probe.conn.commit()
        follow_cap = "cap-new-a"
        follow_body = [{
            "decision_key": key,
            "action": "follow_draft",
            "label": "新拟甲",
            "draft_capability": follow_cap,
        }]
    finally:
        probe.close()

    r3 = _657_subprocess_resolve(db_path, follow_body, crash="")
    assert r3.get("done") is True, r3
    probe = GameDB(db_path, content)
    try:
        hit = next(r for r in probe.list_rescript_drafts() if r["title"] == "改票急务")
        assert hit["status"] == "decided"
        assert (hit["choice"] or {}).get("action") == "follow_draft"
        assert len(probe.list_decree_dossiers()) >= 1
    finally:
        probe.close()


def test_657_prewrite_failure_zero_db_writes(game):
    """prewrite 任一腿失败 → 整批中止，apply 前零写。"""
    from ming_sim import rescript_actions as ra
    db, state, content = game
    urgent, _ = _plant_urgent_desk(db, state)
    key = urgent["decision_key"]
    batch = ra.validate_all([urgent], [{
        "decision_key": key, "action": "deliberate", "label": "下部议",
    }])

    def boom(_it):
        raise RuntimeError("llm down")

    with pytest.raises(RuntimeError, match="prewrite LLM 失败|llm down"):
        ra.run_prewrite_llms(batch, deliberate_runner=boom)
    hit = next(r for r in db.list_rescript_drafts() if r["title"] == "陕西告饥")
    assert hit["status"] == "pending"
    assert hit["choice"] is None or hit["choice"] == {} or not hit["choice"]


def test_657_abi_mapper_matrix_a1_a12(game):
    """A1–A12：map 正/负 + 判后 follow/midzhi→apply 链（补 A5/A6/A11）。"""
    from ming_sim import rescript_actions as ra
    from ming_sim.decree_vocabulary import (
        DOSSIER_ACTION_TYPES,
        RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES,
        RESCRIPT_ROUTABLE_ACTION_TYPES,
    )
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    db, state, content = game

    # A12 闭集
    assert RESCRIPT_ROUTABLE_ACTION_TYPES < DOSSIER_ACTION_TYPES
    assert "dismiss_assignment" in RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(decree_dossiers)").fetchall()}
    assert "rescript_origin" not in cols

    ministers = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "ORDER BY name LIMIT 2"
    ).fetchall()
    mname = str(ministers[0]["name"]) if ministers else "杨嗣昌"
    other = str(ministers[1]["name"]) if len(ministers) > 1 else mname

    def _apply_mapped_choice(choice_fields, *, title, promulgate=True):
        """mapper→validate→apply_rescript_batch；默认再顺颁，读世界事实。"""
        db.conn.execute("DELETE FROM pending_decisions WHERE kind='rescript_draft'")
        opt = normalize_rescript_layer_a_option({
            "label": choice_fields.get("label") or "拟",
            "hint": "h",
            **{k: v for k, v in choice_fields.items()
               if k not in {"decision_key", "action", "draft_capability"}},
        }) if choice_fields.get("action") == "follow_draft" else None
        if opt is not None:
            drafts_opts = [opt, _layer_a_option(label="b", hint="h")]
            cap = opt["draft_capability"]
            label = opt["label"]
        else:
            drafts_opts = [
                _layer_a_option(label="骨架", hint="h"),
                _layer_a_option(label="b", hint="h"),
            ]
            cap = ""
            label = choice_fields.get("label") or "中旨"
        db.save_rescript_drafts(int(state.turn), [{
            "title": title, "context": "c", "options": drafts_opts,
            "actor_name": mname, "actor_office": "o", "actor_faction": "f",
        }])
        db.conn.commit()
        desk = db.list_rescript_desk(int(state.turn))
        row = next(r for r in desk if r["title"] == title)
        key = row["decision_key"]
        if choice_fields.get("action") == "follow_draft":
            choice = {
                "decision_key": key, "action": "follow_draft",
                "draft_capability": cap, "label": label,
            }
        else:
            choice = {"decision_key": key, **choice_fields}
            choice.setdefault("action", "midzhi")
        before = len(db.list_decree_dossiers())
        batch = ra.validate_all([row], [choice])
        ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=content)
        after_rows = db.list_decree_dossiers()
        assert len(after_rows) > before, title
        created = after_rows[-1]
        if promulgate:
            verdict = {"dossier_id": int(created["id"]), "decision": "promulgated"}
            if str(created.get("mode") or "") == "midzhi":
                verdict["affected_parties"] = [{
                    "kind": "faction", "key": "皇党",
                    "direction": "positive", "intensity": "weak",
                }]
            db.apply_dossier_verdicts(state, [verdict], content=content)
            created = next(
                d for d in db.list_decree_dossiers() if int(d["id"]) == int(created["id"])
            )
        return created

    # A1 assignment：判后 issues initiative + origin_ref + end_turn；roster 有主办
    army0 = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()
    stop_a1 = {f"army.{army0['id']}.arrears": "<=0"} if army0 else {"metrics.民心": ">=0"}
    p = ra.map_rescript_option_or_choice({
        "action_type": "assignment", "label": "责成督赈", "hint": "h",
        "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈", "deadline_months": 2,
        "assignee_name": mname,
        "commitment_kind": "until_stop", "stop_condition": stop_a1,
    }, db=db, content=content, state=state)
    assert p["end_turn"] == int(state.turn) + 2
    created = _apply_mapped_choice({
        "action": "follow_draft", "action_type": "assignment",
        "label": "责成督赈", "hint": "h",
        "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈", "deadline_months": 2,
        "assignee_name": mname,
        "commitment_kind": "until_stop", "stop_condition": stop_a1,
    }, title="A1急务")
    origin = f"dossier:{int(created['id'])}"
    init = db.conn.execute(
        "SELECT kind, origin_ref, end_turn, status, stop_condition FROM issues WHERE origin_ref=?",
        (origin,),
    ).fetchone()
    assert init is not None, "A1 判后须落 initiative"
    assert str(init["kind"]) == "initiative"
    assert str(init["origin_ref"]) == origin
    assert int(init["end_turn"]) == int(state.turn) + 2
    # stop_condition 结构化保真（经 option normalize→follow→payload→initiative）
    sc_issue = init["stop_condition"] if "stop_condition" in init.keys() else None
    if isinstance(sc_issue, str) and sc_issue.strip().startswith("{"):
        sc_issue = json.loads(sc_issue)
    assert sc_issue == stop_a1, f"A1 issue stop_condition 须结构化相等：{sc_issue!r}"
    pl_a1 = created.get("payload_json") or created.get("payload") or {}
    if isinstance(pl_a1, str):
        pl_a1 = json.loads(pl_a1 or "{}")
    assert pl_a1.get("stop_condition") == stop_a1
    roster = created.get("participant_roster") or []
    assert any(
        isinstance(e, dict) and str(e.get("tier") or "") == "主办"
        for e in roster
    ), f"A1 roster 须有主办：{roster!r}"
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({
            "action_type": "assignment", "label": "x", "hint": "h",
            "target_kind": "region", "target_id": "shaanxi",
            "locality_scope": "single",
        }, db=db, content=content, state=state)

    # A2 military_order：station 正例改 armies.station
    army = db.conn.execute("SELECT id, station FROM armies LIMIT 1").fetchone()
    if army is not None:
        aid = str(army["id"])
        old_station = str(army["station"] or "")
        new_station = "山海关" if old_station != "山海关" else "大同"
        p = ra.map_rescript_option_or_choice({
            "action_type": "military_order", "label": "调驻", "hint": "h",
            "assignee_name": mname, "target_kind": "army", "target_id": aid,
            "locality_scope": "none", "station": new_station,
        }, db=db, content=content, state=state)
        assert p["station"] == new_station
        created = _apply_mapped_choice({
            "action": "follow_draft", "action_type": "military_order",
            "label": "调驻", "hint": "h", "assignee_name": mname,
            "target_kind": "army", "target_id": aid, "locality_scope": "none",
            "station": new_station,
        }, title="A2急务")
        after_army = db.conn.execute(
            "SELECT station FROM armies WHERE id=?", (aid,),
        ).fetchone()
        assert after_army is not None
        assert str(after_army["station"] or "") == new_station
        with pytest.raises(ValueError):
            ra.map_rescript_option_or_choice({
                "action_type": "military_order", "label": "x", "hint": "h",
                "assignee_name": mname, "target_kind": "region", "target_id": "shaanxi",
                "locality_scope": "none",
            }, db=db, content=content, state=state)

    # A3 grant honorific：person_logs 加衔；office 不被覆盖
    office_before = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (mname,),
    ).fetchone()
    office_before_s = str(office_before["office"] or "") if office_before else ""
    p = ra.map_rescript_option_or_choice({
        "action_type": "grant_allocation", "label": "加衔", "hint": "h",
        "grant_action": "加衔", "target_kind": "character", "target_id": mname,
        "name": mname, "locality_scope": "none",
    }, db=db, content=content, state=state)
    assert p.get("execution_surface") == "terminal"
    created = _apply_mapped_choice({
        "action": "follow_draft", "action_type": "grant_allocation",
        "label": "加衔", "hint": "h", "grant_action": "加衔",
        "target_kind": "character", "target_id": mname, "name": mname,
        "locality_scope": "none",
    }, title="A3急务")
    logs = db.conn.execute(
        "SELECT action FROM person_logs WHERE person_name=? AND action IN ('加衔','荫叙')",
        (mname,),
    ).fetchall()
    assert logs, "A3 判后须落 person_logs 加衔/荫叙"
    office_after = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (mname,),
    ).fetchone()
    assert str(office_after["office"] or "") == office_before_s

    # A4 金钱：国库减少 amount（seed 足额后再咬）
    state.metrics["国库"] = int(state.metrics.get("国库") or 0) + 5000
    db.save_state(state)
    treasury_before = int(state.metrics.get("国库") or 0)
    amount_a4 = 1000
    p = ra.map_rescript_option_or_choice({
        "action_type": "grant_allocation", "label": "赏", "hint": "h",
        "grant_action": "赏赉", "amount": amount_a4,
        "target_kind": "character", "target_id": mname, "name": mname,
        "locality_scope": "none",
    }, db=db, content=content, state=state)
    assert p["account"] == "国库"
    created = _apply_mapped_choice({
        "action": "follow_draft", "action_type": "grant_allocation",
        "label": "赏", "hint": "h", "grant_action": "赏赉", "amount": amount_a4,
        "target_kind": "character", "target_id": mname, "name": mname,
        "locality_scope": "none",
    }, title="A4急务")
    treasury_after = int(state.metrics.get("国库") or 0)
    assert treasury_after == treasury_before - amount_a4, (
        f"A4 国库应减 {amount_a4}：{treasury_before}→{treasury_after}"
    )
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({
            "action_type": "grant_allocation", "label": "赏", "hint": "h",
            "grant_action": "赏赉",
            "target_kind": "character", "target_id": mname,
            "locality_scope": "none",
        }, db=db, content=content, state=state)

    # A5 项目经费/赈灾：仅 kind 落对（持久 target_kind/target_id）
    p = ra.map_rescript_option_or_choice({
        "action_type": "grant_allocation", "label": "项目", "hint": "h",
        "grant_action": "项目经费", "amount": 500,
        "target_kind": "issue", "target_id": "river-works",
        "locality_scope": "none",
    }, db=db, content=content, state=state)
    assert p.get("grant_action") == "项目经费"
    created = _apply_mapped_choice({
        "action": "follow_draft", "action_type": "grant_allocation",
        "label": "项目", "hint": "h", "grant_action": "项目经费", "amount": 500,
        "target_kind": "issue", "target_id": "river-works", "locality_scope": "none",
    }, title="A5项目")
    assert str(created.get("target_kind") or "") == "issue"
    assert str(created.get("target_id") or "") == "river-works"
    p = ra.map_rescript_option_or_choice({
        "action_type": "grant_allocation", "label": "赈", "hint": "h",
        "grant_action": "赈灾", "amount": 800,
        "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
    }, db=db, content=content, state=state)
    assert p.get("grant_action") == "赈灾"
    created = _apply_mapped_choice({
        "action": "follow_draft", "action_type": "grant_allocation",
        "label": "赈", "hint": "h", "grant_action": "赈灾", "amount": 800,
        "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
    }, title="A5赈灾")
    assert str(created.get("target_kind") or "") == "region"
    assert str(created.get("target_id") or "") == "shaanxi"
    # 赈灾无可用 region 靶（target_id 空/等于动作字面）→ issue 叉
    created_fb = _apply_mapped_choice({
        "action": "follow_draft", "action_type": "grant_allocation",
        "label": "赈fallback", "hint": "h", "grant_action": "赈灾", "amount": 100,
        "target_kind": "issue", "target_id": "赈灾", "locality_scope": "none",
    }, title="A5赈灾fallback")
    assert str(created_fb.get("target_kind") or "") == "issue"

    # A6 协饷销欠：真军 arrears 可见变化
    if army is not None:
        aid = str(army["id"])
        # seed 欠饷
        db.conn.execute(
            "UPDATE armies SET province_pay_arrears=500, central_pay_arrears=0, "
            "arrears=500 WHERE id=?",
            (aid,),
        )
        db.conn.commit()
        before_arr = db.conn.execute(
            "SELECT province_pay_arrears, central_pay_arrears, arrears FROM armies WHERE id=?",
            (aid,),
        ).fetchone()
        p = ra.map_rescript_option_or_choice({
            "action_type": "grant_allocation", "label": "协饷", "hint": "h",
            "grant_action": "协饷", "amount": 1200,
            "target_kind": "army", "target_id": aid, "locality_scope": "none",
        }, db=db, content=content, state=state)
        assert p.get("grant_action") == "协饷"
        created = _apply_mapped_choice({
            "action": "follow_draft", "action_type": "grant_allocation",
            "label": "协饷", "hint": "h", "grant_action": "协饷", "amount": 1200,
            "target_kind": "army", "target_id": aid, "locality_scope": "none",
        }, title="A6协饷")
        after_arr = db.conn.execute(
            "SELECT province_pay_arrears, central_pay_arrears, arrears FROM armies WHERE id=?",
            (aid,),
        ).fetchone()
        before_total = (
            float(before_arr["province_pay_arrears"] or 0)
            + float(before_arr["central_pay_arrears"] or 0)
            + float(before_arr["arrears"] or 0)
        )
        after_total = (
            float(after_arr["province_pay_arrears"] or 0)
            + float(after_arr["central_pay_arrears"] or 0)
            + float(after_arr["arrears"] or 0)
        )
        # 销欠或补饷可见：欠饷总额下降（真军写核）
        assert after_total < before_total, (
            f"A6 欠饷应下降：{before_total}→{after_total}"
        )
        assert str(created.get("target_kind") or "") == "army"
        assert str(created.get("target_id") or "") == aid
        with pytest.raises(ValueError):
            ra.map_rescript_option_or_choice({
                "action_type": "grant_allocation", "label": "协饷", "hint": "h",
                "grant_action": "协饷", "amount": 100,
                "target_kind": "army", "target_id": "no-such-army-657",
                "locality_scope": "none",
            }, db=db, content=content, state=state)

    # A9 punishment：下狱 imprisoned；罚俸国库变化
    p = ra.map_rescript_option_or_choice({
        "action_type": "punishment", "label": "下狱", "hint": "h",
        "punish_action": "拿问下狱",
        "target_kind": "character", "target_id": mname, "name": mname,
        "locality_scope": "none",
    }, db=db, content=content, state=state)
    assert p["punish_action"] == "拿问下狱"
    assert db.get_character_status(mname)[0] == "active", "A9 下狱前须 active"
    _apply_mapped_choice({
        "action": "follow_draft", "action_type": "punishment",
        "label": "下狱", "hint": "h", "punish_action": "拿问下狱",
        "target_kind": "character", "target_id": mname, "name": mname,
        "locality_scope": "none", "assignee_name": other,
    }, title="A9下狱")
    assert db.get_character_status(mname)[0] == "imprisoned", "A9 判后须 imprisoned"
    # 恢复 active 以便后续 A7/A8/罚俸
    db.set_character_status(state, mname, "active", "A9 cleanup")
    if mname in getattr(content, "characters", {}):
        content.characters[mname].status = "active"
    db.conn.commit()

    # 罚俸：seed 足额后咬 person_logs 罚俸 + 国库精确减额（禁 status 恒真兜底）
    state.metrics["国库"] = int(state.metrics.get("国库") or 0) + 500
    db.save_state(state)
    treasury_b = int(state.metrics.get("国库") or 0)
    fine_amt = 50
    p = ra.map_rescript_option_or_choice({
        "action_type": "punishment", "label": "罚俸", "hint": "h",
        "punish_action": "罚俸", "amount": fine_amt,
        "target_kind": "character", "target_id": mname, "name": mname,
        "locality_scope": "none",
    }, db=db, content=content, state=state)
    assert p["amount"] == fine_amt
    _apply_mapped_choice({
        "action": "follow_draft", "action_type": "punishment",
        "label": "罚俸", "hint": "h", "punish_action": "罚俸", "amount": fine_amt,
        "target_kind": "character", "target_id": mname, "name": mname,
        "locality_scope": "none", "assignee_name": other,
    }, title="A9罚俸")
    plogs = db.conn.execute(
        "SELECT action FROM person_logs WHERE person_name=? AND action=?",
        (mname, "罚俸"),
    ).fetchall()
    assert plogs, "A9 罚俸须落 person_logs action=罚俸"
    treasury_a = int(state.metrics.get("国库") or 0)
    assert treasury_a == treasury_b - fine_amt, (
        f"A9 罚俸国库应减 {fine_amt}：{treasury_b}→{treasury_a}"
    )
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({
            "action_type": "punishment", "label": "罚", "hint": "h",
            "punish_action": "罚俸",
            "target_kind": "character", "target_id": mname,
            "locality_scope": "none",
        }, db=db, content=content, state=state)

    # A7/A8 appointment：授官 office_change 或 office；罢免非 active 主职
    p = ra.map_rescript_option_or_choice({
        "action_type": "appointment", "label": "授官", "hint": "h",
        "appoint_action": "任命", "office": "兵部尚书",
        "target_kind": "character", "target_id": mname, "name": mname,
        "locality_scope": "none",
    }, db=db, content=content, state=state)
    assert p["_office_action"] == "任命" and p["_emitted_action_type"] == "appointment"
    # seed 可知前态：非目标官职，避免「本已是兵部尚书」零写绿灯
    office_before_a7 = "光禄寺署丞"
    db.conn.execute(
        "UPDATE characters SET office=?, status='active', power_id='ming' WHERE name=?",
        (office_before_a7, mname),
    )
    db.conn.commit()
    created = _apply_mapped_choice({
        "action": "follow_draft", "action_type": "appointment",
        "label": "授官", "hint": "h", "appoint_action": "任命", "office": "兵部尚书",
        "target_kind": "character", "target_id": mname, "name": mname,
        "locality_scope": "none",
    }, title="A7授官")
    ocr = db.conn.execute(
        "SELECT COUNT(*) AS c FROM office_change_records WHERE dossier_id=?",
        (int(created["id"]),),
    ).fetchone()
    assert int(ocr["c"] or 0) >= 1, "A7 须落 office_change_records 绑定本案"
    office_now = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (mname,),
    ).fetchone()
    assert str(office_now["office"] or "") == "兵部尚书"
    assert str(office_now["office"] or "") != office_before_a7

    p = ra.map_rescript_option_or_choice({
        "action_type": "appointment", "label": "罢", "hint": "h",
        "appoint_action": "罢免", "office": "",
        "target_kind": "character", "target_id": mname, "name": mname,
        "locality_scope": "none",
    }, db=db, content=content, state=state)
    assert p["_emitted_action_type"] == "dismiss_assignment"
    office_before_a8 = str(db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (mname,),
    ).fetchone()["office"] or "")
    assert office_before_a8 == "兵部尚书", "A8 前须有 A7 授官"
    assert db.get_character_status(mname)[0] == "active"
    _apply_mapped_choice({
        "action": "follow_draft", "action_type": "appointment",
        "label": "罢", "hint": "h", "appoint_action": "罢免", "office": "",
        "target_kind": "character", "target_id": mname, "name": mname,
        "locality_scope": "none",
    }, title="A8罢免")
    # dismiss_assignment 判后：status=dismissed 且 office 清空（真写核，非 ocr 表）
    assert db.get_character_status(mname)[0] == "dismissed", "A8 判后须 dismissed"
    office8 = str(db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (mname,),
    ).fetchone()["office"] or "")
    assert not office8.strip(), f"A8 罢免后 office 须空：{office8!r}"
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({
            "action_type": "appointment", "label": "授", "hint": "h",
            "appoint_action": "任命", "office": "",
            "target_kind": "character", "target_id": mname,
            "locality_scope": "none",
        }, db=db, content=content, state=state)

    # 恢复 mname 以便 A10/A11（若被罢）
    if db.get_character_status(mname)[0] != "active":
        db.set_character_status(state, mname, "active", "A8 cleanup")
    db.conn.execute(
        "UPDATE characters SET office=COALESCE(NULLIF(office,''), '兵部尚书'), "
        "power_id='ming', status='active' WHERE name=?",
        (mname,),
    )
    db.conn.commit()

    # A10 authorization
    p = ra.map_rescript_option_or_choice({
        "action_type": "authorization", "label": "委任", "hint": "h",
        "name": mname, "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
    }, db=db, content=content, state=state)
    assert p["privilege"] == "便宜行事"
    auth_before = len(db.list_active_authorities(int(state.turn), holder_id=mname))
    created = _apply_mapped_choice({
        "action": "follow_draft", "action_type": "authorization",
        "label": "委任", "hint": "h", "name": mname,
        "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
    }, title="A10授权")
    auth_after = db.list_active_authorities(int(state.turn), holder_id=mname)
    assert len(auth_after) >= auth_before + 1
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({
            "action_type": "authorization", "label": "x", "hint": "h",
            "target_kind": "region", "target_id": "shaanxi",
            "locality_scope": "single",
        }, db=db, content=content, state=state)

    # A11 pacification 易主
    rebel = db.conn.execute(
        "SELECT c.name AS name FROM characters c "
        "JOIN powers p ON p.id = c.power_id "
        "WHERE c.status='active' AND p.kind='内乱' AND p.stance IN ('敌对','潜伏') "
        "AND p.leader = c.name LIMIT 1"
    ).fetchone()
    if rebel is None:
        db.conn.execute(
            "INSERT OR REPLACE INTO powers "
            "(id, name, kind, leader, stance, troops, cohesion, morale, supply, aggression, "
            "notes, activity, home_region, tags) "
            "VALUES ('test_rebel_657','测试流寇','内乱','测试流寇头','敌对',25,20,55,30,22,"
            "'','','shaanxi','[]')"
        )
        db.conn.execute(
            "INSERT OR REPLACE INTO characters "
            "(name, status, power_id, office, office_type, location) "
            "VALUES ('测试流寇头','active','test_rebel_657','','','shaanxi')"
        )
        db.conn.commit()
        rname = "测试流寇头"
    else:
        rname = str(rebel["name"])
    p = ra.map_rescript_option_or_choice({
        "action_type": "pacification", "label": "招抚", "hint": "h",
        "target_kind": "character", "target_id": rname, "name": rname,
        "locality_scope": "none",
    }, db=db, content=content, state=state)
    assert p["target_id"] == rname
    created = _apply_mapped_choice({
        "action": "follow_draft", "action_type": "pacification",
        "label": "招抚", "hint": "h",
        "target_kind": "character", "target_id": rname, "name": rname,
        "locality_scope": "none",
    }, title="A11招抚")
    prow = db.conn.execute(
        "SELECT power_id FROM characters WHERE name=?", (rname,)
    ).fetchone()
    assert prow is not None and str(prow["power_id"] or "") == "ming"

    # follow create 幂等：decided 精确匹配 skip（A12 判后）
    opt_fields = {
        "action_type": "assignment", "label": "幂等交办", "hint": "h",
        "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈", "deadline_months": 1,
    }
    opt = normalize_rescript_layer_a_option(opt_fields)
    db.conn.execute("DELETE FROM pending_decisions WHERE kind='rescript_draft'")
    db.save_rescript_drafts(int(state.turn), [{
        "title": "幂等急务", "context": "c",
        "options": [opt, _layer_a_option(label="b", hint="h")],
        "actor_name": mname, "actor_office": "o", "actor_faction": "f",
    }])
    db.conn.commit()
    desk = db.list_rescript_desk(int(state.turn))
    key = next(r["decision_key"] for r in desk if r["title"] == "幂等急务")
    choice = {
        "decision_key": key, "action": "follow_draft",
        "draft_capability": opt["draft_capability"], "label": opt["label"],
    }
    before = len(db.list_decree_dossiers())
    batch = ra.validate_all([next(r for r in desk if r["decision_key"] == key)], [choice])
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=content)
    mid = len(db.list_decree_dossiers())
    assert mid > before
    row = next(r for r in db.list_rescript_drafts() if r["title"] == "幂等急务")
    stored = dict(row["choice"] or {})
    stored.setdefault("decision_key", key)
    decided_desk = {
        "decision_key": key, "kind": "rescript_draft",
        "source_turn": int(row["turn"]), "turn": int(row["turn"]),
        "idx": int(row["idx"]), "status": "decided",
        "choice": stored, "options": row["options"],
        "revision_round": row["revision_round"],
        "prior_options_json": row["prior_options_json"],
        "title": row["title"], "actor_name": row.get("actor_name"),
    }
    batch2 = ra.validate_all([decided_desk], [stored])
    assert batch2.items[0].already_applied
    ra.apply_rescript_batch(db, state, batch2, ra.PrewriteResults(), content=content)
    assert len(db.list_decree_dossiers()) == mid



def test_657_s10_http_five_actions_and_1490_no_regress(web_game, monkeypatch):
    """P3+S10(+S1)：六动作参数表真 HTTP + 真 phase2 外部结构化终局。

    不含 S5/S6（独立符号）。#1490 批红 force/hold 物化由同文件既有 #1490 专测覆盖，
    不在本符号 stub phase2 冒充。five_actions_domain_writes 保留领域写，不得标 P3。
    """
    from ming_sim.audience_night import TAG_ENTER
    from ming_sim.models import TurnPhase
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    db, state = web_game.db, web_game.state
    opt = normalize_rescript_layer_a_option({
        "label": "发帑赈济", "hint": "所安者饥民",
        "action_type": "assignment", "assignee_name": "",
        "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈", "deadline_months": 2,
    })

    # 真 phase2（只 stub LLM 边界）；六动作各推月后按当前 turn 再种
    _657_install_real_phase2_llm_boundary(monkeypatch)

    # summon generator 边界 stub（经 session 公共缝）
    summon_gen_bodies = {}

    def _det_gen(inputs):
        name = str(getattr(inputs, "person_name", "") or "") or "臣"
        text = f"{name}奉诏入殿。"
        summon_gen_bodies[name] = text
        return text

    monkeypatch.setattr(
        web_game.session, "_beat_generator", _det_gen, raising=False,
    )
    import ming_sim.beat_orchestration as bo
    monkeypatch.setattr(bo, "create_llm_beat_generator", lambda _cfg: _det_gen)

    cases = [
        ("hold", {"action": "hold", "label": "留中"}),
        ("follow_draft", {
            "action": "follow_draft", "label": opt["label"],
            "draft_capability": opt["draft_capability"],
        }),
        ("midzhi", {
            "action": "midzhi", "label": "中旨",
            "action_type": "assignment",
            "target_kind": "region", "target_id": "shaanxi",
            "locality_scope": "single", "region_id": "shaanxi",
            "transaction_category": "督赈", "deadline_months": 1,
        }),
        ("deliberate", {"action": "deliberate", "label": "下部议"}),
        ("return_revise", {"action": "return_revise", "label": "发回改票"}),
        # summon 置末：开夜后 auto_close 会等在飞；后续 case 不再触发 barrier 死等
        ("summon", {
            "action": "summon", "label": "召见", "summon_target": "杨嗣昌",
        }),
    ]

    for name, choice_body in cases:
        # phase2/refresh 可能换 state 对象——每轮从 session 重取真源
        state = web_game.session.state
        db = web_game.db
        db.conn.execute("DELETE FROM pending_decisions")
        db.conn.commit()
        db.save_rescript_drafts(int(state.turn), [{
            "title": f"急务-{name}", "context": "c",
            "options": [opt, {"label": "备", "hint": "h", "draft_capability": "x"}],
            "actor_name": "杨嗣昌", "actor_office": "兵部尚书", "actor_faction": "东林",
        }])
        db.conn.commit()
        db.save_resolve_context(
            int(state.turn), "诏", "邸报", {"candidate_events": [], "transit_semantics": []},
            secret_orders=[], relevant_memories=[],
        )
        state.turn_phase = TurnPhase.AWAITING_DECISION.value
        db.save_state(state)
        desk = db.list_rescript_desk(int(state.turn))
        key = desk[0]["decision_key"]
        choice = {**choice_body, "decision_key": key}

        if name == "deliberate":
            import ming_sim.rescript_actions as ra

            def _fake_prewrite(batch, **kwargs):
                return ra.PrewriteResults(deliberate_by_key={
                    key: {"title": "廷议", "body": "臣请集议。", "stance": "主赈"},
                })

            monkeypatch.setattr(ra, "run_prewrite_llms", _fake_prewrite)
        if name == "return_revise":
            import ming_sim.rescript_actions as ra

            def _fake_prewrite_rev(batch, **kwargs):
                return ra.PrewriteResults(revise_by_key={
                    key: [
                        {"label": "新甲", "hint": "h1", "draft_capability": "n1"},
                        {"label": "新乙", "hint": "h2", "draft_capability": "n2"},
                    ],
                })

            monkeypatch.setattr(ra, "run_prewrite_llms", _fake_prewrite_rev)

        r = asyncio.run(_post_resolve([choice]))
        assert r.status_code == 200, f"{name}: {r.text}"
        assert "event: error" not in r.text, f"{name}: {r.text}"
        assert "event: done" in r.text, f"{name}: {r.text}"

        hit = next(x for x in db.list_rescript_drafts() if x["title"] == f"急务-{name}")
        if name == "hold":
            assert hit["status"] == "decided"
            assert (hit["choice"] or {}).get("action") == "hold"
            edges = db.conn.execute(
                "SELECT event_kind FROM relation_edge_events "
                "WHERE target=? AND event_kind=?",
                ("杨嗣昌", "辜负"),
            ).fetchall()
            assert edges, "hold 须写辜负信用边"
        elif name == "follow_draft":
            assert hit["status"] == "decided"
            assert len(db.list_decree_dossiers()) >= 1
        elif name == "midzhi":
            mids = [d for d in db.list_decree_dossiers() if d.get("mode") == "midzhi"]
            assert mids and mids[-1]["status"] == "proposed"
        elif name == "deliberate":
            issue = db.conn.execute(
                "SELECT title, origin_ref FROM issues WHERE origin_ref=?",
                (f"rescript_deliberate:{key}",),
            ).fetchone()
            assert issue is not None
        elif name == "summon":
            assert hit["status"] == "decided"
            assert (hit["choice"] or {}).get("action") == "summon"
            # S1：无需再 attach 即有全局 origin_ref+TAG_ENTER，body==generator 非空
            from ming_sim.audience_night import rescript_summon_origin_ref
            kind, turn_s, idx_s = key.split(":")
            origin = rescript_summon_origin_ref(int(turn_s), int(idx_s), 0)
            row = db.conn.execute(
                "SELECT body, tags FROM story_ledger_entries WHERE origin_ref=?",
                (origin,),
            ).fetchone()
            assert row is not None
            tags = json.loads(row["tags"] or "[]")
            assert TAG_ENTER in tags
            assert str(row["body"] or "").strip()
            body_s = str(row["body"] or "").strip()
            assert body_s
            assert body_s == summon_gen_bodies.get("杨嗣昌") or body_s in summon_gen_bodies.values()
        elif name == "return_revise":
            assert hit["status"] == "pending"
            assert int(hit["revision_round"] or 0) == 1
            labels = [str(o.get("label") or "") for o in (hit["options"] or [])]
            assert "新甲" in labels

def test_657_mixed_batch_follow_plus_decision_and_no_context_copy(web_game, monkeypatch):
    """C1.1：急务 follow + decision 打回；真 HTTP；③后 extracted 空杀进程；
    同 DB 同 body 重 POST 无双写；resolve_context 无批副本键。"""
    from ming_sim.models import TurnPhase
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    db_path = _657_db_path_of(web_game)
    opt = normalize_rescript_layer_a_option({
        "label": "发帑赈济", "hint": "所安者饥民",
        "action_type": "assignment", "assignee_name": "",
        "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈", "deadline_months": 2,
    })
    desk = _657_plant_awaiting_web(
        web_game,
        drafts=[{
            "title": "混批急务", "context": "c",
            "options": [opt, {"label": "备", "hint": "h", "draft_capability": "x"}],
            "actor_name": "杨嗣昌", "actor_office": "兵部尚书", "actor_faction": "东林",
        }],
        decisions=[{
            "title": "打回件", "context": "科臣封驳",
            "options": [{"label": "打回", "hint": "驳"}, {"label": "准", "hint": ""}],
            "event_id": "",  # 无事件父行；决策仍落 decided（C1.1 不测事件账）
        }],
    )
    u_key = next(r["decision_key"] for r in desk if r["kind"] == "rescript_draft")
    d_key = next(r["decision_key"] for r in desk if r["kind"] == "decision")
    body = [
        {
            "decision_key": u_key,
            "action": "follow_draft",
            "draft_capability": opt["draft_capability"],
            "label": opt["label"],
        },
        {"decision_key": d_key, "label": "打回", "hint": "驳", "action": "decision"},
    ]
    body_canon = json.dumps(body, ensure_ascii=False, separators=(",", ":"))

    # 父进程释放 DB
    dossiers_before = len(web_game.db.list_decree_dossiers())
    web_game.session.close()

    r1 = _657_subprocess_resolve(db_path, body, crash="phase2")
    assert r1.get("_killed") is True or r1.get("_returncode") == 97
    assert r1["_body_canonical"] == body_canon

    from ming_sim.content import GameContent
    from ming_sim.db import GameDB
    content = GameContent.load()
    probe = GameDB(db_path, content)
    try:
        hit = next(r for r in probe.list_rescript_drafts() if r["title"] == "混批急务")
        assert hit["status"] == "decided"
        decs = probe.list_pending_decisions(int(probe.load_state().turn))
        assert decs and decs[0]["status"] == "decided"
        assert (decs[0]["choice"] or {}).get("label") == "打回"
        ctx = probe.get_resolve_context(int(probe.load_state().turn))
        assert ctx is None or ctx.get("extracted") is None
        mid_dossiers = len(probe.list_decree_dossiers())
        assert mid_dossiers > dossiers_before
        choice_fp = json.dumps(decs[0]["choice"], ensure_ascii=False, sort_keys=True)
    finally:
        probe.close()

    # 同 body 重 POST
    r2 = _657_subprocess_resolve(db_path, body, crash="")
    assert r2.get("done") is True, r2
    assert r2["_body_canonical"] == body_canon

    probe = GameDB(db_path, content)
    try:
        assert len(probe.list_decree_dossiers()) == mid_dossiers  # 无双写案卷
        decs = probe.list_pending_decisions(int(probe.load_state().turn))
        # 真 phase2 清 decision 行
        assert not decs or all(d.get("status") == "decided" for d in decs)
        ctx = probe.get_resolve_context(int(probe.load_state().turn))
        if ctx is not None:
            blob = json.dumps(ctx, ensure_ascii=False)
            assert "committed_rescript_batch" not in blob
            assert "rescript_choices" not in blob
        # decision choice 指纹不双写（行已清或 choice 不变）
        _ = choice_fp
    finally:
        probe.close()


def test_657_s5_http_generator_failure_blocks_phase2_and_same_body_retry(
    web_game, monkeypatch,
):
    """S5：真 HTTP summon；generator 失败挡 phase2；修后同 body 重试恰一条消费账。"""
    from ming_sim.audience_night import TAG_ENTER, rescript_summon_origin_ref
    from ming_sim.models import TurnPhase
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    db, state = web_game.db, web_game.state
    opt = normalize_rescript_layer_a_option({
        "label": "备", "hint": "h", "action_type": "assignment",
        "assignee_name": "", "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈",
    })
    fail = {"v": True}

    def _gen(inputs):
        if fail["v"]:
            raise RuntimeError("generator inject fail")
        name = str(getattr(inputs, "person_name", "") or "") or "臣"
        return f"{name}再入殿。"

    import ming_sim.beat_orchestration as bo
    monkeypatch.setattr(bo, "create_llm_beat_generator", lambda _cfg: _gen)
    monkeypatch.setattr(web_game.session, "_beat_generator", _gen, raising=False)

    _657_install_real_phase2_llm_boundary(monkeypatch)
    phase2_calls = {"n": 0}
    _real_p2 = session_mod.resolve_decisions_phase2

    def _count_phase2(*a, **k):
        phase2_calls["n"] += 1
        return _real_p2(*a, **k)

    monkeypatch.setattr(session_mod, "resolve_decisions_phase2", _count_phase2)

    desk = _657_plant_awaiting_web(web_game, drafts=[{
        "title": "S5召见", "context": "c",
        "options": [opt, {"label": "x", "hint": "h", "draft_capability": "x"}],
        "actor_name": "杨嗣昌", "actor_office": "o", "actor_faction": "f",
    }])
    key = desk[0]["decision_key"]
    body = [{
        "decision_key": key, "action": "summon",
        "label": "召见", "summon_target": "杨嗣昌",
    }]
    turn_before = int(state.turn)
    r1 = asyncio.run(_post_resolve(body))
    assert r1.status_code == 200
    assert "event: error" in r1.text or "event: done" not in r1.text
    assert phase2_calls["n"] == 0, "generator 失败不得进 phase2"
    assert web_game.state.turn_phase != TurnPhase.ISSUED.value
    hit = next(r for r in db.list_rescript_drafts() if r["title"] == "S5召见")
    assert hit["status"] == "decided"
    assert (hit["choice"] or {}).get("action") == "summon"
    assert int(web_game.state.turn) == turn_before

    # 修 generator 后同 body 重试
    fail["v"] = False
    web_game.state.turn_phase = TurnPhase.AWAITING_DECISION.value
    web_game.session.state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(web_game.state)
    r2 = asyncio.run(_post_resolve(body))
    assert r2.status_code == 200 and "event: done" in r2.text, r2.text
    assert phase2_calls["n"] == 1
    # §E.4 S5：消费成功且月可推
    assert int(web_game.state.turn) == turn_before + 1
    kind, turn_s, idx_s = key.split(":")
    origin = rescript_summon_origin_ref(int(turn_s), int(idx_s), 0)
    rows = db.conn.execute(
        "SELECT body, tags FROM story_ledger_entries WHERE origin_ref=?",
        (origin,),
    ).fetchall()
    assert len(rows) == 1
    tags = json.loads(rows[0]["tags"] or "[]")
    assert TAG_ENTER in tags
    assert str(rows[0]["body"] or "").strip() == "杨嗣昌再入殿。"


def test_657_s6_http_present_target_gets_unique_origin_body(web_game, monkeypatch):
    """S6：目标已在场，真 HTTP summon → 该 origin 恰一条 TAG_ENTER，body==generator。"""
    from ming_sim.audience_night import (
        TAG_ENTER, open_night, rescript_summon_origin_ref, summon_enter,
    )
    from ming_sim.models import TurnPhase
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    db, state = web_game.db, web_game.state
    gen_body = "杨嗣昌已在场仍独立入账。"

    def _gen(_inputs):
        return gen_body

    import ming_sim.beat_orchestration as bo
    monkeypatch.setattr(bo, "create_llm_beat_generator", lambda _cfg: _gen)
    monkeypatch.setattr(web_game.session, "_beat_generator", _gen, raising=False)

    _657_install_real_phase2_llm_boundary(monkeypatch)

    # 先使目标已在场
    night = open_night(db, state, empty_scaffold=True)
    summon_enter(db, int(night["id"]), "杨嗣昌", empty_scaffold=False)
    db.conn.commit()

    opt = normalize_rescript_layer_a_option({
        "label": "备", "hint": "h", "action_type": "assignment",
        "assignee_name": "", "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈",
    })
    desk = _657_plant_awaiting_web(web_game, drafts=[{
        "title": "S6召见", "context": "c",
        "options": [opt, {"label": "x", "hint": "h", "draft_capability": "x"}],
        "actor_name": "杨嗣昌", "actor_office": "o", "actor_faction": "f",
    }])
    key = desk[0]["decision_key"]
    body = [{
        "decision_key": key, "action": "summon",
        "label": "召见", "summon_target": "杨嗣昌",
    }]
    r = asyncio.run(_post_resolve(body))
    assert r.status_code == 200 and "event: done" in r.text, r.text
    kind, turn_s, idx_s = key.split(":")
    origin = rescript_summon_origin_ref(int(turn_s), int(idx_s), 0)
    rows = db.conn.execute(
        "SELECT body, tags FROM story_ledger_entries WHERE origin_ref=?",
        (origin,),
    ).fetchall()
    assert len(rows) == 1
    tags = json.loads(rows[0]["tags"] or "[]")
    assert TAG_ENTER in tags
    assert str(rows[0]["body"] or "") == gen_body



def test_657_web_http_hitl_lock_boundary_same_gate(web_game, monkeypatch):
    """Class4/S2 web 生产调用：真 HTTP → submit_hitl；①/③ 持同一 gate，② 释放。"""
    import threading
    import time

    from ming_sim.models import TurnPhase
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    db, state = web_game.db, web_game.state
    _657_install_real_phase2_llm_boundary(monkeypatch)

    gate = web_game._write_gate
    events = []
    lock = threading.Lock()
    in_join = {"v": False}

    real_commit = web_game.session.commit_rescript_phase1
    real_join = web_game.session.join_rescript_summons
    real_finish = web_game.session.finish_rescript_phase2

    def _commit(pre):
        with lock:
            events.append(("commit", gate.locked()))
        assert gate.locked(), "① commit 须持 write_gate"
        return real_commit(pre)

    def _join(p1):
        in_join["v"] = True
        try:
            free = gate.acquire(False)
            if free:
                gate.release()
            with lock:
                events.append(("join_free", bool(free)))
            assert free, "② join 期间 write_gate 必须释放"
            return real_join(p1)
        finally:
            in_join["v"] = False

    def _finish(p1, j, **kw):
        with lock:
            events.append(("finish", gate.locked()))
        assert gate.locked(), "③ finish 须再持同一 write_gate"
        return real_finish(p1, j, **kw)

    web_game.session.commit_rescript_phase1 = _commit  # type: ignore[method-assign]
    web_game.session.join_rescript_summons = _join  # type: ignore[method-assign]
    web_game.session.finish_rescript_phase2 = _finish  # type: ignore[method-assign]

    def _gen(inputs):
        # 给 join 探针一点窗口
        time.sleep(0.02)
        name = str(getattr(inputs, "person_name", "") or "") or "臣"
        return f"{name}锁窗入殿。"

    import ming_sim.beat_orchestration as bo
    monkeypatch.setattr(bo, "create_llm_beat_generator", lambda _cfg: _gen)
    monkeypatch.setattr(web_game.session, "_beat_generator", _gen, raising=False)

    opt = normalize_rescript_layer_a_option({
        "label": "备", "hint": "h", "action_type": "assignment",
        "assignee_name": "", "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈",
    })
    desk = _657_plant_awaiting_web(web_game, drafts=[{
        "title": "锁窗召见", "context": "c",
        "options": [opt, {"label": "x", "hint": "h", "draft_capability": "x"}],
        "actor_name": "杨嗣昌", "actor_office": "o", "actor_faction": "f",
    }])
    key = desk[0]["decision_key"]
    r = asyncio.run(_post_resolve([{
        "decision_key": key, "action": "summon",
        "label": "召见", "summon_target": "杨嗣昌",
    }]))
    assert r.status_code == 200 and "event: done" in r.text, r.text
    kinds = [k for k, _ in events]
    assert "commit" in kinds and "join_free" in kinds and "finish" in kinds
    assert any(k == "join_free" and v for k, v in events)


def test_657_illegal_summon_target_http_zero_writes(web_game, monkeypatch):
    """非法 summon target → 公共 HTTP 零 choice 落库、零 decided、零 scaffold。"""
    from ming_sim.models import TurnPhase
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    db, state = web_game.db, web_game.state

    def _phase2(_state, _db, *_a, **_k):
        raise AssertionError("illegal summon must not reach phase2")

    monkeypatch.setattr(session_mod, "resolve_decisions_phase2", _phase2)
    opt = normalize_rescript_layer_a_option({
        "label": "备", "hint": "h", "action_type": "assignment",
        "assignee_name": "", "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈",
    })
    ledger_before = db.conn.execute(
        "SELECT COUNT(*) AS c FROM story_ledger_entries"
    ).fetchone()["c"]
    desk = _657_plant_awaiting_web(web_game, drafts=[{
        "title": "非法召见", "context": "c",
        "options": [opt, {"label": "x", "hint": "h", "draft_capability": "x"}],
        "actor_name": "杨嗣昌", "actor_office": "o", "actor_faction": "f",
    }])
    key = desk[0]["decision_key"]
    r = asyncio.run(_post_resolve([{
        "decision_key": key, "action": "summon",
        "label": "召见", "summon_target": "不存在的边将xyz",
    }]))
    assert r.status_code == 200
    assert "event: error" in r.text
    assert "event: done" not in r.text
    hit = next(x for x in db.list_rescript_drafts() if x["title"] == "非法召见")
    assert hit["status"] == "pending"
    assert not hit["choice"]
    ledger_after = db.conn.execute(
        "SELECT COUNT(*) AS c FROM story_ledger_entries"
    ).fetchone()["c"]
    assert ledger_after == ledger_before
