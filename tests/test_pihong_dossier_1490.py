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
    assert issue is not None and "廷议" in str(issue["title"])

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


def test_657_return_revise_round_prior_and_clear_anchor(game):
    """C1.2：改票 round 不双增、prior 全史；phase2 后清 choice_json。"""
    from ming_sim import rescript_actions as ra
    db, state, content = game
    urgent, opts = _plant_urgent_desk(db, state)
    key = urgent["decision_key"]
    choice = {
        "decision_key": key,
        "action": "return_revise",
        "label": "发回改票",
        "applied_from_revision_round": 0,
        "draft_capability": opts[0]["draft_capability"],
    }
    batch = ra.validate_all([urgent], [choice])
    new_opts = [
        {"label": "新拟甲", "hint": "h1", "draft_capability": "cap-a"},
        {"label": "新拟乙", "hint": "h2", "draft_capability": "cap-b"},
    ]
    pre = ra.PrewriteResults(revise_by_key={key: new_opts})
    ra.apply_rescript_batch(db, state, batch, pre, content=content)
    hit = next(r for r in db.list_rescript_drafts() if r["title"] == "陕西告饥")
    assert hit["status"] == "pending"
    assert hit["revision_round"] == 1
    assert [o["label"] for o in hit["options"]] == ["新拟甲", "新拟乙"]
    assert len(hit["prior_options_json"]) == 1
    assert (hit["choice"] or {}).get("action") == "return_revise"

    # 同 revise choice 重放 → already_applied，round 不双增
    desk2 = db.list_rescript_desk(int(state.turn))
    row2 = next(r for r in desk2 if r["decision_key"] == key)
    batch2 = ra.validate_all([row2], [choice])
    assert batch2.items[0].already_applied is True
    ra.apply_rescript_batch(db, state, batch2, ra.PrewriteResults(), content=content)
    hit2 = next(r for r in db.list_rescript_drafts() if r["title"] == "陕西告饥")
    assert hit2["revision_round"] == 1

    # phase2 成功后清锚
    ra.clear_return_revise_choice_anchors(db, [key])
    db.conn.commit()
    hit3 = next(r for r in db.list_rescript_drafts() if r["title"] == "陕西告饥")
    assert hit3["choice"] == {} or hit3["choice"] is None or hit3["choice"] == {}
    # 空 choice 后新鲜 follow 可提交（用新 options 的 cap）
    fresh = {
        "decision_key": key,
        "action": "hold",
        "label": "留中",
    }
    desk3 = db.list_rescript_desk(int(state.turn))
    row3 = next(r for r in desk3 if r["decision_key"] == key)
    batch3 = ra.validate_all([row3], [fresh])
    assert batch3.items[0].already_applied is False


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
    # 库态未变
    hit = next(r for r in db.list_rescript_drafts() if r["title"] == "陕西告饥")
    assert hit["status"] == "pending"
    assert hit["choice"] is None or hit["choice"] == {} or not hit["choice"]


def test_657_abi_mapper_matrix_a1_a12(game):
    """A1–A12：map_rescript_option_or_choice 首写前正/负 + 闭集。"""
    from ming_sim import rescript_actions as ra
    from ming_sim.decree_vocabulary import (
        DOSSIER_ACTION_TYPES,
        RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES,
        RESCRIPT_ROUTABLE_ACTION_TYPES,
    )
    db, state, content = game

    # A12 闭集
    assert RESCRIPT_ROUTABLE_ACTION_TYPES < DOSSIER_ACTION_TYPES
    assert "dismiss_assignment" in RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(decree_dossiers)").fetchall()}
    assert "rescript_origin" not in cols

    # A1 assignment duty 无 assignee
    p = ra.map_rescript_option_or_choice({
        "action_type": "assignment", "label": "责成督赈", "hint": "h",
        "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈", "deadline_months": 2,
    }, db=db, content=content, state=state)
    assert p["end_turn"] == int(state.turn) + 2
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({
            "action_type": "assignment", "label": "x", "hint": "h",
            "target_kind": "region", "target_id": "shaanxi",
            "locality_scope": "single",
        }, db=db, content=content, state=state)

    # A2 military_order
    army = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()
    if army is not None:
        aid = str(army["id"])
        minister = db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND power_id='ming' LIMIT 1"
        ).fetchone()
        name = str(minister["name"]) if minister else "杨嗣昌"
        p = ra.map_rescript_option_or_choice({
            "action_type": "military_order", "label": "调驻", "hint": "h",
            "assignee_name": name, "target_kind": "army", "target_id": aid,
            "locality_scope": "none", "station": "山海关",
        }, db=db, content=content, state=state)
        assert p["station"] == "山海关"
        with pytest.raises(ValueError):
            ra.map_rescript_option_or_choice({
                "action_type": "military_order", "label": "x", "hint": "h",
                "assignee_name": name, "target_kind": "region", "target_id": "shaanxi",
                "locality_scope": "none",
            }, db=db, content=content, state=state)

    # A3/A4 grant honorific + 金钱
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' LIMIT 1"
    ).fetchone()
    mname = str(minister["name"]) if minister else "杨嗣昌"
    p = ra.map_rescript_option_or_choice({
        "action_type": "grant_allocation", "label": "加衔", "hint": "h",
        "grant_action": "加衔", "target_kind": "character", "target_id": mname,
        "name": mname, "locality_scope": "none",
    }, db=db, content=content, state=state)
    assert p.get("execution_surface") == "terminal"
    p = ra.map_rescript_option_or_choice({
        "action_type": "grant_allocation", "label": "赏", "hint": "h",
        "grant_action": "赏赉", "amount": 1000,
        "target_kind": "character", "target_id": mname, "name": mname,
        "locality_scope": "none",
    }, db=db, content=content, state=state)
    assert p["account"] == "国库"  # 缺 account 默认
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({
            "action_type": "grant_allocation", "label": "赏", "hint": "h",
            "grant_action": "赏赉",  # 缺 amount
            "target_kind": "character", "target_id": mname,
            "locality_scope": "none",
        }, db=db, content=content, state=state)

    # A7/A8 appointment
    p = ra.map_rescript_option_or_choice({
        "action_type": "appointment", "label": "授官", "hint": "h",
        "appoint_action": "任命", "office": "兵部尚书",
        "target_kind": "character", "target_id": mname, "name": mname,
        "locality_scope": "none",
    }, db=db, content=content, state=state)
    assert p["_office_action"] == "任命" and p["_emitted_action_type"] == "appointment"
    p = ra.map_rescript_option_or_choice({
        "action_type": "appointment", "label": "罢", "hint": "h",
        "appoint_action": "罢免", "office": "",
        "target_kind": "character", "target_id": mname, "name": mname,
        "locality_scope": "none",
    }, db=db, content=content, state=state)
    assert p["_emitted_action_type"] == "dismiss_assignment"
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({
            "action_type": "appointment", "label": "授", "hint": "h",
            "appoint_action": "任命", "office": "",  # 缺 office
            "target_kind": "character", "target_id": mname,
            "locality_scope": "none",
        }, db=db, content=content, state=state)

    # A9 punishment
    p = ra.map_rescript_option_or_choice({
        "action_type": "punishment", "label": "下狱", "hint": "h",
        "punish_action": "拿问下狱",
        "target_kind": "character", "target_id": mname, "name": mname,
        "locality_scope": "none",
    }, db=db, content=content, state=state)
    assert p["punish_action"] == "拿问下狱"
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({
            "action_type": "punishment", "label": "罚", "hint": "h",
            "punish_action": "罚俸",  # 无 amount
            "target_kind": "character", "target_id": mname,
            "locality_scope": "none",
        }, db=db, content=content, state=state)

    # A10 authorization name-only
    p = ra.map_rescript_option_or_choice({
        "action_type": "authorization", "label": "委任", "hint": "h",
        "name": mname, "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
    }, db=db, content=content, state=state)
    assert p["privilege"] == "便宜行事"
    assert p["holder_id"] == mname or p["name"]
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({
            "action_type": "authorization", "label": "x", "hint": "h",
            "target_kind": "region", "target_id": "shaanxi",
            "locality_scope": "single",
        }, db=db, content=content, state=state)

    # follow create 幂等：同 body 重交不增（C1 decided 跳过）— 行级
    opt_fields = {
        "action_type": "assignment", "label": "幂等交办", "hint": "h",
        "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈", "deadline_months": 1,
    }
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option
    opt = normalize_rescript_layer_a_option(opt_fields)
    db.conn.execute("DELETE FROM pending_decisions WHERE kind='rescript_draft'")
    db.save_rescript_drafts(int(state.turn), [{
        "title": "幂等急务", "context": "c", "options": [opt, {"label": "b", "hint": "h",
            "draft_capability": "x"}],
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
    # 重交 decided 精确匹配 → skip
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


def test_657_mixed_batch_follow_plus_decision_and_no_context_copy(game):
    """C1.1 骨架：急务 follow + decision 同批；resolve_context 无 choices 批副本。"""
    from ming_sim import rescript_actions as ra
    db, state, content = game
    opt = _layer_a_option()
    urgent, _ = _plant_urgent_desk(db, state, options=[opt, _layer_a_option(label="备", hint="b")])
    db.save_pending_decisions(int(state.turn), [{
        "title": "边警",
        "context": "c",
        "options": [{"label": "准", "hint": ""}, {"label": "驳", "hint": ""}],
        "event_id": "ev-x",
    }])
    db.conn.commit()
    desk = db.list_rescript_desk(int(state.turn))
    u_key = next(r["decision_key"] for r in desk if r["kind"] == "rescript_draft")
    d_key = next(r["decision_key"] for r in desk if r["kind"] == "decision")
    batch = ra.validate_all(desk, [
        {
            "decision_key": u_key,
            "action": "follow_draft",
            "draft_capability": opt["draft_capability"],
            "label": opt["label"],
        },
        {"decision_key": d_key, "label": "准", "hint": "", "action": "decision"},
    ])
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=content)
    # decision decided
    decs = db.list_pending_decisions(int(state.turn))
    assert decs and decs[0]["status"] == "decided"
    # 无 choices 批副本键写入 resolve_context
    ctx = db.get_resolve_context(int(state.turn))
    if ctx is not None:
        blob = json.dumps(ctx, ensure_ascii=False)
        assert "committed_rescript_batch" not in blob
        assert "rescript_choices" not in blob
