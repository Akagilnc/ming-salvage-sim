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



def _dossier_payload(row):
    if not isinstance(row, dict):
        return {}
    payload = row.get("payload")
    if isinstance(payload, dict) and payload:
        return payload
    try:
        loaded = json.loads(str(row.get("payload_json") or "{}"))
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


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

    # deliberate will 首尾空白 → stalled 案卷 decree_text/title 原文；惯性 issue 同源
    urgent, _ = _plant_urgent_desk(db, state)
    key = urgent["decision_key"]
    batch = ra.validate_all([urgent], [{
        "decision_key": key, "action": "deliberate", "label": "下部议",
    }])
    will_title = " 廷议题 "
    will_body = "\n臣请集议。\t"
    pre = ra.PrewriteResults(deliberate_by_key={
        key: {"title": will_title, "body": will_body, "supporter_ids": []},
    })
    ra.apply_rescript_batch(db, state, batch, pre, content=content)
    drow = db.find_deliberation_dossier_by_decision_key(key)
    assert drow is not None
    payload = _dossier_payload(drow)
    assert payload.get("deliberation_state") == "stalled"
    assert payload.get("title") == will_title  # payload 原文
    # decree_text 经成案内核 strip；惯性 issue 保留 will 原文
    issue = db.conn.execute(
        "SELECT title, stage_text, origin_ref FROM issues WHERE origin_ref=?",
        (f"dossier:{int(drow['id'])}",),
    ).fetchone()
    assert issue is not None
    assert str(issue["title"]) == will_title
    assert str(issue["stage_text"]) == will_body

    # stop_condition：C.6 仅 str 原样；dict/非 str 拒；mapper/payload 逐字相等
    stop = "军饷清完乃止"
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
    assert isinstance(choice["stop_condition"], str)
    mapped = ra.map_rescript_option_or_choice(choice, mode="midzhi", db=db, content=content, state=state)
    assert mapped["stop_condition"] == stop
    with pytest.raises(ValueError):
        ra.canonical_choice({
            "decision_key": "rescript_draft:1:0",
            "action": "midzhi",
            "stop_condition": {"army.x.arrears": "<=0"},
        })

    # Layer-A PRESENT 三键：缺键 / 非 str → ValueError；三键在且 "" 通过
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option
    base_a = {
        "label": "拟", "hint": "h", "action_type": "assignment",
        "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single",
        "assignee_name": "", "region_id": "shaanxi", "transaction_category": "督赈",
    }
    assert normalize_rescript_layer_a_option(base_a)["assignee_name"] == ""
    for miss in ("assignee_name", "region_id", "transaction_category"):
        bad = dict(base_a)
        del bad[miss]
        with pytest.raises(ValueError):
            normalize_rescript_layer_a_option(bad)
    for bad_key, bad_val in (
        ("assignee_name", None),
        ("region_id", 12),
        ("transaction_category", ["督赈"]),
    ):
        bad = dict(base_a)
        bad[bad_key] = bad_val
        with pytest.raises(ValueError):
            normalize_rescript_layer_a_option(bad)


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
    # §C.8：payload 须带既有 decision identity
    mid_payload = json.loads(str(mids[-1].get("payload_json") or "{}"))
    assert mid_payload.get("decision_key") == key
    assert mid_payload.get("mode") == "midzhi"

    # --- deliberate（无人站台 → stalled 案卷 + dossier: origin issue）---
    db.conn.execute("DELETE FROM pending_decisions WHERE kind='rescript_draft'")
    urgent, _ = _plant_urgent_desk(db, state)
    key = urgent["decision_key"]
    batch = ra.validate_all([urgent], [{
        "decision_key": key, "action": "deliberate", "label": "下部议",
    }])
    pre = ra.PrewriteResults(deliberate_by_key={
        key: {
            "title": "廷议陕西赈济", "body": "臣请集议赈策。", "stance": "主赈",
            "supporter_ids": [],
        },
    })
    ra.apply_rescript_batch(db, state, batch, pre, content=content)
    drow = db.find_deliberation_dossier_by_decision_key(key)
    assert drow is not None
    assert _dossier_payload(drow).get("deliberation_state") == "stalled"
    issue = db.conn.execute(
        "SELECT title, origin_ref FROM issues WHERE origin_ref=?",
        (f"dossier:{int(drow['id'])}",),
    ).fetchone()
    assert issue is not None and str(issue["origin_ref"] or "") == f"dossier:{int(drow['id'])}"

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
                        # 完整合法 Layer-A raw（六必填+三 PRESENT）；禁伪造 draft_capability
                        out[it.decision_key] = [
                            {"label": "新拟甲", "hint": "h1",
                             "action_type": "assignment", "target_kind": "region",
                             "target_id": "shaanxi", "locality_scope": "single",
                             "region_id": "shaanxi", "assignee_name": "",
                             "transaction_category": "督赈", "deadline_months": 2},
                            {"label": "新拟乙", "hint": "h2",
                             "action_type": "assignment", "target_kind": "region",
                             "target_id": "shaanxi", "locality_scope": "single",
                             "region_id": "", "assignee_name": "",
                             "transaction_category": ""},
                        ]
                return ra.PrewriteResults(revise_by_key=out)
            ra.run_prewrite_llms = _fake_prewrite
        elif prewrite_mode == "deliberate":
            def _fake_prewrite(batch, **kwargs):
                out = {}
                for it in batch.items:
                    out[it.decision_key] = {
                        "title": "廷议", "body": "臣请集议。", "stance": "主赈",
                        "supporter_ids": [],
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
        new_labels = [str(o.get("label") or "") for o in (hit["options"] or [])]
        assert "新拟甲" in new_labels
        new_caps = [str(o.get("draft_capability") or "") for o in (hit["options"] or [])]
        assert all(c and c not in {"cap-new-a", "cap-new-b"} for c in new_caps)
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
        # 跟新拟甲：capability 由服务端派生，禁伪造 cap-new-a
        new_opt = next(
            o for o in (hit["options"] or [])
            if str(o.get("label") or "") == "新拟甲"
        )
        follow_cap = str(new_opt.get("draft_capability") or "")
        assert follow_cap
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

    def interrupted(_it):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        ra.run_prewrite_llms(batch, deliberate_runner=interrupted)


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
        opt = None
        if choice_fields.get("action") == "follow_draft":
            raw_opt = {
                "label": choice_fields.get("label") or "拟",
                "hint": "h",
                # C.3 PRESENT 三键必须在（可 ""）
                "assignee_name": "",
                "region_id": "",
                "transaction_category": "",
                **{k: v for k, v in choice_fields.items()
                   if k not in {"decision_key", "action", "draft_capability"}},
            }
            opt = normalize_rescript_layer_a_option(raw_opt)
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
            # #657 §C.8：midzhi 顺颁不附猜派 affected_parties
            verdict = {"dossier_id": int(created["id"]), "decision": "promulgated"}
            db.apply_dossier_verdicts(state, [verdict], content=content)
            created = next(
                d for d in db.list_decree_dossiers() if int(d["id"]) == int(created["id"])
            )
        return created

    # A1 assignment duty route B：无显式 assignee + 合法 category + deadline→绝对 end_turn
    # 省域 single 职司链需本省在任；seed 户部 location 以便 duty 命中主办
    db.conn.execute(
        "UPDATE characters SET location='shaanxi' "
        "WHERE status='active' AND power_id='ming' AND office_type='户部'"
    )
    db.conn.commit()
    p = ra.map_rescript_option_or_choice({
        "action_type": "assignment", "label": "责成督赈", "hint": "h",
        "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈", "deadline_months": 2,
        "assignee_name": "",
    }, db=db, content=content, state=state)
    assert p["end_turn"] == int(state.turn) + 2
    # mapper 可选正：until_stop + 非空 str stop → payload 逐字相等
    stop_a1 = "军饷清完乃止"
    p_stop = ra.map_rescript_option_or_choice({
        "action_type": "assignment", "label": "责成督赈", "hint": "h",
        "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈", "deadline_months": 2,
        "assignee_name": "",
        "commitment_kind": "until_stop", "stop_condition": stop_a1,
    }, db=db, content=content, state=state)
    assert p_stop.get("stop_condition") == stop_a1
    created = _apply_mapped_choice({
        "action": "follow_draft", "action_type": "assignment",
        "label": "责成督赈", "hint": "h",
        "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈", "deadline_months": 2,
        "assignee_name": "",
    }, title="A1急务")
    origin = f"dossier:{int(created['id'])}"
    init = db.conn.execute(
        "SELECT kind, origin_ref, end_turn, status FROM issues WHERE origin_ref=?",
        (origin,),
    ).fetchone()
    assert init is not None, "A1 判后须落 initiative"
    assert str(init["kind"]) == "initiative"
    assert str(init["origin_ref"]) == origin
    assert int(init["end_turn"]) == int(state.turn) + 2
    roster = created.get("participant_roster") or []
    assert any(
        isinstance(e, dict) and str(e.get("tier") or "") == "主办"
        for e in roster
    ), f"A1 roster 须有主办：{roster!r}"
    # 负例：category 与主办均缺；until_stop 无/空 stop
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({
            "action_type": "assignment", "label": "x", "hint": "h",
            "target_kind": "region", "target_id": "shaanxi",
            "locality_scope": "single", "assignee_name": "",
        }, db=db, content=content, state=state)
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({
            "action_type": "assignment", "label": "x", "hint": "h",
            "target_kind": "region", "target_id": "shaanxi",
            "locality_scope": "single", "region_id": "shaanxi",
            "transaction_category": "督赈", "assignee_name": "",
            "commitment_kind": "until_stop", "stop_condition": "",
        }, db=db, content=content, state=state)

    # A2 military_order：station 正例 + 无 station 限期 due_turn 正例
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
        # 无 station + deadline_months → 颁布后 dossier due_turn == turn+N
        created_due = _apply_mapped_choice({
            "action": "follow_draft", "action_type": "military_order",
            "label": "限期", "hint": "h", "assignee_name": mname,
            "target_kind": "army", "target_id": aid, "locality_scope": "none",
            "deadline_months": 3,
        }, title="A2限期")
        assert int(created_due.get("due_turn") or 0) == int(state.turn) + 3
        # 负例：非 army；假军；无 station 且无有效未来 due
        with pytest.raises(ValueError):
            ra.map_rescript_option_or_choice({
                "action_type": "military_order", "label": "x", "hint": "h",
                "assignee_name": mname, "target_kind": "region", "target_id": "shaanxi",
                "locality_scope": "none",
            }, db=db, content=content, state=state)
        with pytest.raises(ValueError):
            ra.map_rescript_option_or_choice({
                "action_type": "military_order", "label": "x", "hint": "h",
                "assignee_name": mname, "target_kind": "army",
                "target_id": "no-such-army-657", "locality_scope": "none",
                "deadline_months": 2,
            }, db=db, content=content, state=state)
        with pytest.raises(ValueError):
            ra.map_rescript_option_or_choice({
                "action_type": "military_order", "label": "x", "hint": "h",
                "assignee_name": mname, "target_kind": "army", "target_id": aid,
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
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({
            "action_type": "grant_allocation", "label": "加衔", "hint": "h",
            "grant_action": "加衔", "target_kind": "character", "target_id": "",
            "name": "", "locality_scope": "none",
        }, db=db, content=content, state=state)

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
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({
            "action_type": "grant_allocation", "label": "赏", "hint": "h",
            "grant_action": "赏赉", "amount": 10, "account": "私库",
            "target_kind": "character", "target_id": mname, "name": mname,
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
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({
            "action_type": "grant_allocation", "label": "项目", "hint": "h",
            "grant_action": "项目经费", "amount": 500,
            "target_kind": "issue", "target_id": "", "locality_scope": "none",
        }, db=db, content=content, state=state)

    # A6 协饷销欠：只咬 province_pay_arrears + central_pay_arrears 双累加器
    if army is not None:
        aid = str(army["id"])
        # seed：双累加器；arrears 镜像和，主断言不参与
        db.conn.execute(
            "UPDATE armies SET province_pay_arrears=500, central_pay_arrears=0, "
            "arrears=500 WHERE id=?",
            (aid,),
        )
        db.conn.commit()
        before_arr = db.conn.execute(
            "SELECT province_pay_arrears, central_pay_arrears FROM armies WHERE id=?",
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
            "SELECT province_pay_arrears, central_pay_arrears FROM armies WHERE id=?",
            (aid,),
        ).fetchone()
        before_total = (
            float(before_arr["province_pay_arrears"] or 0)
            + float(before_arr["central_pay_arrears"] or 0)
        )
        after_total = (
            float(after_arr["province_pay_arrears"] or 0)
            + float(after_arr["central_pay_arrears"] or 0)
        )
        assert after_total < before_total, (
            f"A6 双累加器欠饷应下降：{before_total}→{after_total}"
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
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({
            "action_type": "punishment", "label": "罚", "hint": "h",
            "punish_action": "不是刑罚",
            "target_kind": "character", "target_id": mname, "name": mname,
            "locality_scope": "none",
        }, db=db, content=content, state=state)
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({
            "action_type": "punishment", "label": "罚", "hint": "h",
            "punish_action": "罚俸", "amount": 0,
            "target_kind": "character", "target_id": mname, "name": mname,
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
    # A8 负例：非 active 不得罢免；无 appoint_action 不得默任命
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({
            "action_type": "appointment", "label": "罢", "hint": "h",
            "appoint_action": "罢免", "office": "",
            "target_kind": "character", "target_id": mname, "name": mname,
            "locality_scope": "none",
        }, db=db, content=content, state=state)
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({
            "action_type": "appointment", "label": "授", "hint": "h",
            "office": "兵部尚书",
            "target_kind": "character", "target_id": mname, "name": mname,
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
        "assignee_name": "", "transaction_category": "督赈", "deadline_months": 1,
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
                    key: {
                        "title": "廷议", "body": "臣请集议。", "stance": "主赈",
                        "supporter_ids": [],
                    },
                })

            monkeypatch.setattr(ra, "run_prewrite_llms", _fake_prewrite)
        if name == "return_revise":
            import ming_sim.rescript_actions as ra

            def _fake_prewrite_rev(batch, **kwargs):
                return ra.PrewriteResults(revise_by_key={
                    key: [
                        _layer_a_option(label="新甲", hint="h1"),
                        _layer_a_option(label="新乙", hint="h2"),
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
            drow = db.find_deliberation_dossier_by_decision_key(key)
            assert drow is not None
            assert _dossier_payload(drow).get("deliberation_state") == "stalled"
            issue = db.conn.execute(
                "SELECT title, origin_ref FROM issues WHERE origin_ref=?",
                (f"dossier:{int(drow['id'])}",),
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


def test_657_follow_draft_ignores_client_field_overlay(game):
    """Spec1/A12：同 capability 不得靠客户端字段 overlay 改机械载荷。"""
    from ming_sim import rescript_actions as ra

    db, state, content = game
    opt = _layer_a_option(
        label="权威票拟",
        target_id="shaanxi",
        region_id="shaanxi",
        transaction_category="督赈",
        title="权威标题",
    )
    urgent, _ = _plant_urgent_desk(db, state, options=[opt, _layer_a_option(label="备")])
    key = urgent["decision_key"]
    before = len(db.list_decree_dossiers())
    batch = ra.validate_all([urgent], [{
        "decision_key": key,
        "action": "follow_draft",
        "draft_capability": opt["draft_capability"],
        "label": opt["label"],
        # 客户端企图改机械字段
        "target_id": "henan",
        "region_id": "henan",
        "title": "伪造标题",
        "transaction_category": "练兵",
        "assignee_name": "不存在的人",
    }])
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=content)
    after = db.list_decree_dossiers()
    assert len(after) == before + 1
    created = after[-1]
    payload = json.loads(str(created.get("payload_json") or "{}"))
    assert str(created.get("target_id") or payload.get("target_id") or "") == "shaanxi"
    assert "henan" not in {
        str(created.get("target_id") or ""),
        str(payload.get("target_id") or ""),
        str(created.get("region_id") or ""),
        str(payload.get("region_id") or ""),
    }
    assert str(payload.get("title") or "") == "权威标题"
    assert "伪造标题" not in str(payload.get("title") or "")
    assert str(payload.get("transaction_category") or "") == "督赈"
    assert "不存在的人" not in str(payload.get("assignee_name") or "")
    assert "不存在的人" not in str(created.get("executor_id") or "")


def test_657_midzhi_persists_decision_key_and_llm_label(game):
    """Spec2 + P7：midzhi payload 带 decision_key；decree_text 用 LLM label 非固定钮文。"""
    from ming_sim import rescript_actions as ra

    db, state, content = game
    llm_label = "着户部立发秦地赈银"
    urgent, _ = _plant_urgent_desk(db, state)
    key = urgent["decision_key"]
    choice = {
        "decision_key": key,
        "action": "midzhi",
        "label": llm_label,
        "action_type": "assignment",
        "target_kind": "region",
        "target_id": "shaanxi",
        "locality_scope": "single",
        "region_id": "shaanxi",
        "transaction_category": "督赈",
        "deadline_months": 2,
    }
    batch = ra.validate_all([urgent], [choice])
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=content)
    mids = [d for d in db.list_decree_dossiers() if d.get("mode") == "midzhi"]
    assert mids
    hit = mids[-1]
    payload = json.loads(str(hit.get("payload_json") or "{}"))
    assert payload.get("decision_key") == key
    assert str(hit.get("decree_text") or "") == llm_label
    assert "另旨·中旨" not in str(hit.get("decree_text") or "")
    # mapper 缺 decision_key 响亮失败
    with pytest.raises(ValueError, match="decision_key"):
        ra.map_rescript_option_or_choice(
            {k: v for k, v in choice.items() if k != "decision_key"},
            mode="midzhi", db=db, content=content, state=state,
        )


def test_657_midzhi_verdict_no_party_satisfaction(game):
    """Spec3/§C.8：midzhi 判决不写派系 satisfaction，且不落库猜派。"""
    from tests.dossier_test_helpers import _sat

    db, state, content = game
    from ming_sim import rescript_actions as ra
    urgent, _ = _plant_urgent_desk(db, state)
    key = urgent["decision_key"]
    batch = ra.validate_all([urgent], [{
        "decision_key": key,
        "action": "midzhi",
        "label": "中旨赈陕",
        "action_type": "assignment",
        "target_kind": "region",
        "target_id": "shaanxi",
        "locality_scope": "single",
        "region_id": "shaanxi",
        "transaction_category": "督赈",
        "deadline_months": 1,
    }])
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=content)
    mid = next(d for d in db.list_decree_dossiers() if d.get("mode") == "midzhi")
    before_f = _sat(db, "factions", "东林")
    before_c = _sat(db, "classes", "士绅")
    # 夹带猜派亦不得落库/扇出
    db.apply_dossier_verdicts(state, [{
        "dossier_id": int(mid["id"]),
        "decision": "promulgated",
        "affected_parties": [
            {"kind": "faction", "key": "东林", "direction": "negative", "intensity": "strong"},
            {"kind": "class", "key": "士绅", "direction": "negative", "intensity": "strong"},
        ],
    }], content=content)
    assert _sat(db, "factions", "东林") == before_f
    assert _sat(db, "classes", "士绅") == before_c
    stored = db.conn.execute(
        "SELECT affected_parties_json FROM decree_dossier_decisions "
        "WHERE dossier_id=? ORDER BY id DESC LIMIT 1",
        (int(mid["id"]),),
    ).fetchone()
    parties = json.loads(str(stored["affected_parties_json"] or "[]"))
    assert parties == []


def test_657_summon_missing_tag_enter_blocks_phase2_then_retry(
    web_game, monkeypatch,
):
    """Spec4/§D.0：真 HTTP 入口；origin 非空 body 缺 TAG_ENTER → 不进 phase2；
    修正后同 body 重试成功。复用 S5 夹具，不另造平行机制。"""
    from ming_sim.audience_night import TAG_ENTER, rescript_summon_origin_ref
    from ming_sim.models import TurnPhase
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option
    import ming_sim.beat_orchestration as bo

    db, state = web_game.db, web_game.state
    opt = normalize_rescript_layer_a_option({
        "label": "备", "hint": "h", "action_type": "assignment",
        "assignee_name": "", "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈",
    })
    gen_body = "杨嗣昌门闩入殿。"

    def _gen(inputs):
        name = str(getattr(inputs, "person_name", "") or "") or "臣"
        return f"{name}门闩入殿。" if name != "臣" else gen_body

    monkeypatch.setattr(bo, "create_llm_beat_generator", lambda _cfg: _gen)
    monkeypatch.setattr(web_game.session, "_beat_generator", _gen, raising=False)

    _657_install_real_phase2_llm_boundary(monkeypatch)
    phase2_calls = {"n": 0}
    _real_p2 = session_mod.resolve_decisions_phase2

    def _count_phase2(*a, **k):
        phase2_calls["n"] += 1
        return _real_p2(*a, **k)

    monkeypatch.setattr(session_mod, "resolve_decisions_phase2", _count_phase2)

    # finish 写 body 后剥 TAG_ENTER：非空 body ≠ consumed，门闩挡 phase2
    corrupt = {"v": True}
    real_persist = bo.persist_chat_turn_scene

    def _persist_strip_enter(db_arg, generated):
        real_persist(db_arg, generated)
        if corrupt["v"]:
            for eid, _body in generated:
                db_arg.conn.execute(
                    "UPDATE story_ledger_entries SET tags=? WHERE id=?",
                    (json.dumps(["叙事"], ensure_ascii=False), int(eid)),
                )

    monkeypatch.setattr(bo, "persist_chat_turn_scene", _persist_strip_enter)

    desk = _657_plant_awaiting_web(web_game, drafts=[{
        "title": "门闩召见", "context": "c",
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
    assert phase2_calls["n"] == 0, "缺 TAG_ENTER 不得进 phase2"
    assert web_game.state.turn_phase != TurnPhase.ISSUED.value
    hit = next(r for r in db.list_rescript_drafts() if r["title"] == "门闩召见")
    assert hit["status"] == "decided"
    assert (hit["choice"] or {}).get("action") == "summon"
    assert int(web_game.state.turn) == turn_before
    # 门闩失败须把空问话 scaffold 落 failed（与 generator 失败同形），否则 barrier 永等
    assert db.conn.execute(
        "SELECT COUNT(*) AS c FROM chat_turns WHERE status='generating' "
        "AND user_message_id IS NULL",
    ).fetchone()["c"] == 0

    # 修正：恢复 TAG_ENTER（合法消费账）后同 body 重试
    corrupt["v"] = False
    kind, turn_s, idx_s = key.split(":")
    origin = rescript_summon_origin_ref(int(turn_s), int(idx_s), 0)
    db.conn.execute(
        "UPDATE story_ledger_entries SET tags=? WHERE origin_ref=?",
        (json.dumps([TAG_ENTER, "宣入"], ensure_ascii=False), origin),
    )
    db.conn.commit()
    web_game.state.turn_phase = TurnPhase.AWAITING_DECISION.value
    web_game.session.state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(web_game.state)
    r2 = asyncio.run(_post_resolve(body))
    assert r2.status_code == 200 and "event: done" in r2.text, r2.text
    assert phase2_calls["n"] == 1
    assert int(web_game.state.turn) == turn_before + 1
    rows = db.conn.execute(
        "SELECT body, tags FROM story_ledger_entries WHERE origin_ref=?",
        (origin,),
    ).fetchall()
    assert len(rows) == 1
    tags = json.loads(rows[0]["tags"] or "[]")
    assert TAG_ENTER in tags
    assert str(rows[0]["body"] or "").strip() == gen_body


# ---------------------------------------------------------------------------
# #657 大理寺六类：扩展既有 tracer，不另造夹具族
# ---------------------------------------------------------------------------

def test_657_backlog_only_enters_awaiting_via_merged_desk(game, monkeypatch):
    """① resolve_directives：仅急务 backlog → AWAITING；result.decisions=合并 desk。"""
    import ming_sim.decree as dm
    from ming_sim.models import TurnPhase

    db, state, content = game
    # 跨月 backlog：写在 turn-1
    prev = max(1, int(state.turn) - 1)
    db.conn.execute(
        "INSERT INTO pending_decisions "
        "(turn, idx, event_id, title, context, options_json, choice_json, status, kind, "
        " actor_name, actor_office, actor_faction) "
        "VALUES (?, 0, 'urgent:prev:0', '旧急务', 'c', ?, '', 'pending', 'rescript_draft', "
        " '杨嗣昌', 'o', 'f')",
        (prev, json.dumps([_layer_a_option()], ensure_ascii=False)),
    )
    db.conn.commit()
    assert db.list_rescript_desk(int(state.turn)), "precondition: backlog desk nonempty"

    monkeypatch.setattr(dm, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        dm, "simulate_season_with_payload",
        lambda *a, **k: ("本月无重大抉择。", k.get("simulator_payload") or {}),
    )
    # 禁 settle 直落（若误推进会调此）
    monkeypatch.setattr(
        dm, "_settle_after_narrative",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("backlog-only 不得直落 settle")),
    )

    result = dm.resolve_directives(
        state, db, None, None, [], "诏书", content=content, registry=None,
    )
    assert result.awaiting is True
    assert any(
        str(d.get("kind")) == "rescript_draft" and d.get("title") == "旧急务"
        for d in result.decisions
    )
    assert state.turn_phase == TurnPhase.AWAITING_DECISION.value
    assert db.get_resolve_context(int(state.turn)) is not None


def test_657_preferred_hitl_choice_urgent_follow_draft_ordinary_intact():
    """② 共享首选项投影：急务=follow_draft+capability；普通 decision 不变。"""
    from ming_sim.rescript_actions import project_preferred_hitl_choice

    opt = _layer_a_option()
    urgent = {
        "kind": "rescript_draft",
        "decision_key": "rescript_draft:1:0",
        "title": "急",
        "idx": 0,
        "options": [opt, {"label": "备", "hint": "h", "draft_capability": "x"}],
    }
    pref = project_preferred_hitl_choice(urgent)
    assert pref["action"] == "follow_draft"
    assert pref["draft_capability"] == opt["draft_capability"]
    assert pref["decision_key"] == "rescript_draft:1:0"
    assert pref["label"] == opt["label"]

    ordinary = {
        "kind": "decision",
        "decision_key": "decision:1:0",
        "idx": 0,
        "options": [
            {"label": "甲", "hint": "h1", "dossier_id": 3, "dossier_decision": "hold"},
            {"label": "乙", "hint": "h2"},
        ],
    }
    pref2 = project_preferred_hitl_choice(ordinary)
    assert pref2.get("action") in (None, "")
    assert pref2["label"] == "甲"
    assert pref2["dossier_id"] == 3
    assert pref2["dossier_decision"] == "hold"
    assert "follow_draft" not in str(pref2.get("action") or "")


def test_657_phase2_preserve_backlog_and_generate_current_drafts(game, monkeypatch):
    """③ 真入口 resolve_decisions_phase2：保留既有急务并追加本回合新票拟；清锚同终态。

    不 stub extract 编排：真实 extract fan-out 调 side_leg；只替 LLM 文本与票拟生成结果。
    """
    import ming_sim.decree as dm
    import ming_sim.simulation as simulation
    from ming_sim.models import TurnPhase

    db, state, content = game
    turn = int(state.turn)
    old_opt = _layer_a_option()
    db.save_rescript_drafts(turn, [{
        "title": "旧急务", "context": "c", "options": [old_opt],
        "actor_name": "杨嗣昌", "actor_office": "o", "actor_faction": "f",
    }])
    db.conn.execute(
        "UPDATE pending_decisions SET revision_round=1, choice_json=? "
        "WHERE turn=? AND kind='rescript_draft' AND title='旧急务'",
        (json.dumps({
            "action": "return_revise", "label": "发回改票",
            "applied_from_revision_round": 0,
        }, ensure_ascii=False), turn),
    )
    db.save_resolve_context(
        turn, "诏", "邸报正文",
        {"candidate_events": [], "transit_semantics": [], "decree_text": "诏"},
        secret_orders=[], relevant_memories=[],
    )
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)

    canned = (
        '{"economy_moves": [], "new_armies": [], "new_issues": [], '
        '"secret_order_updates": []}'
    )
    monkeypatch.setattr(simulation, "run_agent_text", lambda *a, **k: canned)
    monkeypatch.setattr(dm, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "create_score_extractor_module_agent", lambda *a, **k: object())
    monkeypatch.setattr(dm, "build_extractor_shared_context", lambda *a, **k: "ctx")
    monkeypatch.setattr(dm, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "record_chapter_memory", lambda *a, **k: None)
    monkeypatch.setattr(dm, "_make_relation_brew_runner", lambda *a, **k: None)
    monkeypatch.setattr(dm, "create_ending_summary_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "create_rescript_draft_agent", lambda *a, **k: object())
    monkeypatch.setattr(dm, "build_rescript_draft_payload", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(
        dm, "select_triage_actor",
        lambda _db: {"name": "杨嗣昌", "office": "首辅", "faction": "东林"},
    )
    new_opt = _layer_a_option(label="新拟本月", hint="新")
    monkeypatch.setattr(
        dm, "generate_rescript_draft",
        lambda *a, **k: [{
            "title": "本月新急务", "context": "n", "options": [new_opt],
        }],
    )

    turn_before = int(state.turn)
    report = dm.resolve_decisions_phase2(
        state, db, None, None, content=content, registry=None,
    )
    assert isinstance(report, str)
    assert int(state.turn) == turn_before + 1
    titles = {d["title"] for d in db.list_rescript_drafts()}
    assert "旧急务" in titles, titles
    assert "本月新急务" in titles, titles
    old = next(d for d in db.list_rescript_drafts() if d["title"] == "旧急务")
    assert int(old["revision_round"] or 0) == 1
    assert not (old.get("choice") or {})


def test_657_consumed_scaffold_finalized_on_retry(game):
    """④ consumed origin 短路时 scaffold 仍须落 consumed 终态（禁 generating 永挂）。"""
    from ming_sim.audience_night import (
        TAG_ENTER,
        prepare_rescript_summon_scaffold,
        rescript_summon_origin_ref,
    )

    db, state, _content = game
    origin = rescript_summon_origin_ref(int(state.turn), 0, 0)
    first = prepare_rescript_summon_scaffold(
        db, state, person_name="杨嗣昌", origin_ref=origin,
    )
    ctid = int(first["chat_turn_id"])
    eid = int(first["entry_id"])
    # 模拟：body 已落 + TAG_ENTER，但 scaffold 仍 generating（崩溃窗口）
    db.conn.execute(
        "UPDATE story_ledger_entries SET body=?, tags=? WHERE id=?",
        ("杨嗣昌入殿。", json.dumps([TAG_ENTER, "宣入"], ensure_ascii=False), eid),
    )
    db.conn.execute(
        "UPDATE chat_turns SET status='generating' WHERE id=?",
        (ctid,),
    )
    db.conn.commit()

    again = prepare_rescript_summon_scaffold(
        db, state, person_name="杨嗣昌", origin_ref=origin,
    )
    assert again.get("consumed") is True
    st = db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()
    assert str(st["status"]) == "consumed"


def test_657_clear_revise_anchor_corrupt_json_fails_loud(game):
    """④ 清锚扫描：choice_json 损坏 / 非 object → 响亮失败，禁静默跳过。"""
    from ming_sim import rescript_actions as ra

    db, state, _content = game
    urgent, _ = _plant_urgent_desk(db, state)
    db.conn.execute(
        "UPDATE pending_decisions SET choice_json=?, revision_round=1 "
        "WHERE turn=? AND idx=? AND kind='rescript_draft'",
        ("{not-json", int(urgent["source_turn"] or urgent["turn"]), int(urgent["idx"])),
    )
    db.conn.commit()
    with pytest.raises(ValueError, match="choice_json 损坏"):
        ra.clear_return_revise_choice_anchors(db, None)

    db.conn.execute(
        "UPDATE pending_decisions SET choice_json=? "
        "WHERE turn=? AND idx=? AND kind='rescript_draft'",
        ("[1,2]", int(urgent["source_turn"] or urgent["turn"]), int(urgent["idx"])),
    )
    db.conn.commit()
    with pytest.raises(ValueError, match="非 object"):
        ra.clear_return_revise_choice_anchors(db, None)


def test_657_default_hold_preserves_red_pen_note(game):
    """⑤ 默认 hold 保留朱笔 note。"""
    from ming_sim import rescript_actions as ra

    db, state, _content = game
    urgent, _ = _plant_urgent_desk(db, state)
    key = urgent["decision_key"]
    batch = ra.validate_all(
        [urgent],
        [{"decision_key": key, "note": "着再议。"}],
        default_hold_missing=True,
    )
    assert key in batch.default_hold_keys
    assert batch.items[0].choice.get("action") == "hold"
    assert batch.items[0].choice.get("note") == "着再议。"


def test_657_appointment_name_target_id_conflict_batch_reject(game):
    """⑥ appointment/dismiss name≠target_id 在 mapper 单一边界整批拒绝。"""
    from ming_sim import rescript_actions as ra

    db, state, content = game
    # 找两名 active 明臣
    rows = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "ORDER BY name LIMIT 2",
    ).fetchall()
    assert len(rows) >= 2
    n1, n2 = str(rows[0]["name"]), str(rows[1]["name"])
    with pytest.raises(ValueError, match="冲突|name|target_id"):
        ra.map_rescript_option_or_choice(
            {
                "action_type": "appointment",
                "appoint_action": "任命",
                "office": "兵部尚书",
                "name": n1,
                "target_kind": "character",
                "target_id": n2,
                "label": "授官",
            },
            db=db, content=content, state=state,
        )
    with pytest.raises(ValueError, match="冲突|name|target_id"):
        ra.map_rescript_option_or_choice(
            {
                "action_type": "appointment",
                "appoint_action": "罢免",
                "office": "",
                "name": n1,
                "target_kind": "character",
                "target_id": n2,
                "label": "罢",
            },
            db=db, content=content, state=state,
        )


def test_657_punishment_name_target_id_conflict_zero_writes(web_game, monkeypatch):
    """punishment name≠target_id → 整批拒；真 HTTP 零 dossier/character 写。"""
    from ming_sim import rescript_actions as ra
    from ming_sim.models import TurnPhase
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    db, state = web_game.db, web_game.state
    rows = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "ORDER BY name LIMIT 2",
    ).fetchall()
    assert len(rows) >= 2
    n1, n2 = str(rows[0]["name"]), str(rows[1]["name"])

    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice(
            {
                "action_type": "punishment",
                "punish_action": "廷杖",
                "name": n1,
                "target_kind": "character",
                "target_id": n2,
                "label": "责",
                "locality_scope": "none",
            },
            db=db, content=web_game.content, state=state,
        )
    ok = ra.map_rescript_option_or_choice(
        {
            "action_type": "punishment",
            "punish_action": "廷杖",
            "name": n1,
            "target_kind": "character",
            "target_id": n1,
            "label": "责",
            "locality_scope": "none",
        },
        db=db, content=web_game.content, state=state,
    )
    assert ok["name"] == n1 and ok["target_id"] == n1
    ok_one = ra.map_rescript_option_or_choice(
        {
            "action_type": "punishment",
            "punish_action": "廷杖",
            "target_kind": "character",
            "target_id": n1,
            "label": "责",
            "locality_scope": "none",
        },
        db=db, content=web_game.content, state=state,
    )
    assert ok_one["name"] == n1 and ok_one["target_id"] == n1

    opt_base = normalize_rescript_layer_a_option({
        "label": "责", "hint": "h", "action_type": "punishment",
        "assignee_name": "", "target_kind": "character", "target_id": n1,
        "name": n1, "punish_action": "廷杖",
        "locality_scope": "none", "region_id": "", "transaction_category": "",
    })
    _657_plant_awaiting_web(web_game, drafts=[{
        "title": "惩处冲突", "context": "c",
        "options": [opt_base, {"label": "x", "hint": "h", "draft_capability": "z"}],
        "actor_name": n1, "actor_office": "o", "actor_faction": "f",
    }])
    desk = db.list_rescript_desk(int(state.turn))
    key = desk[0]["decision_key"]
    before_status = db.get_character_status(n1)[0]
    before_dossiers = db.conn.execute(
        "SELECT COUNT(*) AS c FROM decree_dossiers",
    ).fetchone()["c"]

    body = [{
        "decision_key": key,
        "action": "midzhi",
        "label": "责",
        "action_type": "punishment",
        "punish_action": "廷杖",
        "name": n1,
        "target_kind": "character",
        "target_id": n2,
        "locality_scope": "none",
    }]
    r = asyncio.run(_post_resolve(body))
    assert r.status_code == 200
    # 外部契约：零 durable 写 + 未推进；不解析 SSE 自由文本
    assert db.get_character_status(n1)[0] == before_status
    after_dossiers = db.conn.execute(
        "SELECT COUNT(*) AS c FROM decree_dossiers",
    ).fetchone()["c"]
    assert after_dossiers == before_dossiers
    assert web_game.state.turn_phase != TurnPhase.ISSUED.value
    hit = next(row for row in db.list_rescript_drafts() if row["title"] == "惩处冲突")
    assert hit["status"] == "pending"
    assert hit.get("choice") in (None, {},)


def test_657_revise_deliberate_strict_contracts_zero_write_on_bad_shape(game, monkeypatch):
    """revise 拒 monthly items[]；deliberate 拒缺 stance；合法 options 进入 prewrite。"""
    from ming_sim.rescript_actions import PrewriteResults
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option
    from ming_sim.session import GameSession
    from ming_sim.models import TurnPhase
    import ming_sim.agents as agents_mod

    db, state, content = game
    opt = normalize_rescript_layer_a_option({
        "label": "备", "hint": "h", "action_type": "assignment",
        "assignee_name": "", "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈",
    })
    db.conn.execute("DELETE FROM pending_decisions WHERE kind='rescript_draft'")
    db.save_rescript_drafts(int(state.turn), [{
        "title": "改票契约", "context": "c",
        "options": [opt, {"label": "x", "hint": "h", "draft_capability": "z"}],
        "actor_name": "杨嗣昌", "actor_office": "o", "actor_faction": "f",
    }])
    db.save_resolve_context(
        int(state.turn), "诏", "邸报",
        {"candidate_events": [], "transit_semantics": []},
        secret_orders=[], relevant_memories=[],
    )
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    desk = db.list_rescript_desk(int(state.turn))
    key = desk[0]["decision_key"]

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.llm_config = object()
    sess.agno_db = None
    sess.registry = None
    sess.last_decree = "诏"
    sess.temporary_characters = {}

    def _bad_revise_text(*_a, **_k):
        return json.dumps({
            "items": [{"title": "t", "context": "c", "options": [opt]}],
        }, ensure_ascii=False)

    monkeypatch.setattr(agents_mod, "create_rescript_revise_agent", lambda *_a, **_k: object())
    monkeypatch.setattr(agents_mod, "run_agent_text", _bad_revise_text)
    with pytest.raises(RuntimeError):
        sess.prepare_rescript_prewrite([{
            "decision_key": key, "action": "return_revise", "note": "再拟",
        }])
    hit = next(r for r in db.list_rescript_drafts() if r["title"] == "改票契约")
    assert hit["status"] == "pending"

    legal_opt = normalize_rescript_layer_a_option({
        "label": "改后", "hint": "h2", "action_type": "assignment",
        "assignee_name": "", "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈",
    })

    def _ok_revise_text(*_a, **_k):
        return json.dumps({"options": [legal_opt]}, ensure_ascii=False)

    monkeypatch.setattr(agents_mod, "run_agent_text", _ok_revise_text)
    pre = sess.prepare_rescript_prewrite([{
        "decision_key": key, "action": "return_revise", "note": "再拟",
    }])
    assert isinstance(pre.get("prewrite"), PrewriteResults)
    ro = pre["prewrite"].revise_by_key
    assert key in ro and isinstance(ro[key], list) and len(ro[key]) >= 1
    assert all(isinstance(o, dict) and o.get("action_type") for o in ro[key])

    def _bad_delib(*_a, **_k):
        return json.dumps({"title": "t", "body": "b"}, ensure_ascii=False)

    monkeypatch.setattr(agents_mod, "create_rescript_deliberate_agent", lambda *_a, **_k: object())
    monkeypatch.setattr(agents_mod, "run_agent_text", _bad_delib)
    with pytest.raises(RuntimeError):
        sess.prepare_rescript_prewrite([{
            "decision_key": key, "action": "deliberate", "label": "下部议",
        }])
    hit2 = next(r for r in db.list_rescript_drafts() if r["title"] == "改票契约")
    assert hit2["status"] == "pending"


def test_657_summon_single_flight_concurrent_http(web_game, monkeypatch):
    """summon 同 body 并发：单 chat_turn / 单 ledger body / 单月推进；失败后可重入。"""
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

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
    started = threading.Event()
    release = threading.Event()
    gen_calls = {"n": 0}

    def _gen(inputs):
        gen_calls["n"] += 1
        started.set()
        assert release.wait(5), "generator not released"
        name = str(getattr(inputs, "person_name", "") or "") or "臣"
        return f"{name}single-flight。"

    import ming_sim.beat_orchestration as bo
    monkeypatch.setattr(bo, "create_llm_beat_generator", lambda _cfg: _gen)
    monkeypatch.setattr(web_game.session, "_beat_generator", _gen, raising=False)
    _657_install_real_phase2_llm_boundary(monkeypatch)

    desk = _657_plant_awaiting_web(web_game, drafts=[{
        "title": "单飞召见", "context": "c",
        "options": [opt, {"label": "x", "hint": "h", "draft_capability": "x"}],
        "actor_name": "杨嗣昌", "actor_office": "o", "actor_faction": "f",
    }])
    key = desk[0]["decision_key"]
    body = [{
        "decision_key": key, "action": "summon",
        "label": "召见", "summon_target": "杨嗣昌",
    }]
    turn_before = int(state.turn)

    def _post():
        return asyncio.run(_post_resolve(body))

    # 并发两路同 body：一路慢 generator 窗口内第二路须 coalesce
    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_post)
        assert started.wait(3), "first generator never started"
        f2 = pool.submit(_post)
        time.sleep(0.15)  # 第二路进入 wait/coalesce 窗口
        release.set()
        results = [f.result(timeout=60) for f in (f1, f2)]

    assert all(r.status_code == 200 for r in results), [r.status_code for r in results]
    kind, turn_s, idx_s = key.split(":")
    origin = rescript_summon_origin_ref(int(turn_s), int(idx_s), 0)
    rows = db.conn.execute(
        "SELECT body, tags, origin_chat_turn_id FROM story_ledger_entries WHERE origin_ref=?",
        (origin,),
    ).fetchall()
    assert len(rows) == 1
    tags = json.loads(rows[0]["tags"] or "[]")
    assert TAG_ENTER in tags
    # 外部契约：单 origin 非空 body + 单 chat_turn + 单月推进；不锁正文/SSE 字面
    assert str(rows[0]["body"] or "").strip()
    ctid = int(rows[0]["origin_chat_turn_id"] or 0)
    assert ctid > 0
    assert gen_calls["n"] <= 4, gen_calls
    assert db.conn.execute(
        "SELECT COUNT(*) AS c FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["c"] == 1
    assert int(web_game.state.turn) == turn_before + 1
    assert db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["status"] == "consumed"


def test_657_resume_phase2_signal_empty_desk_http(web_game, monkeypatch):
    """crash 后 desk 空 pending：state_payload.resume_phase2；空 POST stream 完成 phase2。"""
    from ming_sim.models import TurnPhase
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    db, state = web_game.db, web_game.state
    opt = normalize_rescript_layer_a_option({
        "label": "备", "hint": "h", "action_type": "assignment",
        "assignee_name": "", "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi",
        "transaction_category": "督赈",
    })
    desk = _657_plant_awaiting_web(web_game, drafts=[{
        "title": "续跑信号", "context": "c",
        "options": [opt, {"label": "x", "hint": "h", "draft_capability": "z"}],
        "actor_name": "杨嗣昌", "actor_office": "o", "actor_faction": "f",
    }])
    key = desk[0]["decision_key"]

    # 模拟 phase1 已落 decided 后 crash：choice 已写、status=decided、仍 awaiting
    choice = {
        "decision_key": key, "action": "follow_draft", "label": "备",
    }
    kind, turn_s, idx_s = key.split(":")
    db.conn.execute(
        "UPDATE pending_decisions SET status='decided', choice_json=? "
        "WHERE kind=? AND turn=? AND idx=?",
        (json.dumps(choice, ensure_ascii=False), kind, int(turn_s), int(idx_s)),
    )
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    web_game.state.turn_phase = TurnPhase.AWAITING_DECISION.value
    web_game.session.state.turn_phase = TurnPhase.AWAITING_DECISION.value
    # 确保 settlement_display 可真：开 snapshot 若需要
    db.conn.commit()

    payload = web_game.state_payload()
    assert payload.get("resume_phase2") is True
    assert payload.get("pending_decisions") == []

    _657_install_real_phase2_llm_boundary(monkeypatch)
    turn_before = int(state.turn)
    r = asyncio.run(_post_resolve([]))  # 空 POST 既有 stream
    assert r.status_code == 200
    # durable：空 POST 续跑完成 → 月推进；不解析 SSE 自由文本
    assert int(web_game.state.turn) == turn_before + 1


def _summonable_name(db, content):
    from ming_sim import rescript_actions as ra
    ids = ra.list_deliberation_candidate_ids(db, content)
    assert ids, "fixture 须有可召大臣"
    return ids[0]


def test_658_deliberate_backed_and_stalled_dossier_first(game):
    """#658：有站台 → backed+当面站台背书；无人 → stalled+dossier: issue；非法身份零写。"""
    from ming_sim import rescript_actions as ra
    from ming_sim.db import GameDB

    db, state, content = game
    minister = _summonable_name(db, content)

    # --- backed ---
    urgent, _ = _plant_urgent_desk(db, state)
    key = urgent["decision_key"]
    before_dossiers = len(db.list_decree_dossiers())
    before_issues = db.conn.execute("SELECT COUNT(*) AS c FROM issues").fetchone()["c"]
    batch = ra.validate_all([urgent], [{
        "decision_key": key, "action": "deliberate", "label": "下部议",
    }])
    pre = ra.PrewriteResults(deliberate_by_key={
        key: {
            "title": "南迁之议", "body": "臣请集议南迁。", "stance": "可议",
            "supporter_ids": [minister],
        },
    })
    ra.apply_rescript_batch(db, state, batch, pre, content=content)
    assert len(db.list_decree_dossiers()) == before_dossiers + 1
    drow = db.find_deliberation_dossier_by_decision_key(key)
    assert drow is not None and drow["status"] == "proposed"
    payload = _dossier_payload(drow)
    assert payload.get("deliberation_state") == "backed"
    assert payload.get("decision_key") == key
    # 站台名单只在背书表
    assert "supporter_ids" not in payload
    ends = db.list_dossier_endorsements(int(drow["id"]))
    assert len(ends) == 1
    assert ends[0]["form"] == "当面站台"
    assert ends[0]["endorser_id"] == minister
    assert ends[0]["decision_key"] == key
    assert int(ends[0]["source_chat_turn_id"] or 0) == 0
    # backed 不产惯性 issue
    assert db.conn.execute(
        "SELECT COUNT(*) AS c FROM issues WHERE origin_ref=?",
        (f"dossier:{int(drow['id'])}",),
    ).fetchone()["c"] == 0
    assert db.conn.execute("SELECT COUNT(*) AS c FROM issues").fetchone()["c"] == before_issues

    # restore
    reopened = GameDB(db.path, content=content)
    try:
        restored = reopened.find_deliberation_dossier_by_decision_key(key)
        assert restored is not None
        assert _dossier_payload(restored).get("deliberation_state") == "backed"
        r_ends = reopened.list_dossier_endorsements(int(restored["id"]))
        assert r_ends[0]["decision_key"] == key
        assert r_ends[0]["source_chat_turn_id"] == 0
    finally:
        reopened.close()

    # --- stalled（换 turn 避免 decision_key 与上案碰撞）---
    state.turn = int(state.turn) + 1
    db.save_state(state)
    db.conn.execute("DELETE FROM pending_decisions WHERE kind='rescript_draft'")
    urgent2, _ = _plant_urgent_desk(db, state)
    key2 = urgent2["decision_key"]
    assert key2 != key
    batch2 = ra.validate_all([urgent2], [{
        "decision_key": key2, "action": "deliberate", "label": "下部议",
    }])
    pre2 = ra.PrewriteResults(deliberate_by_key={
        key2: {
            "title": "议而不决", "body": "无人肯担。", "stance": "冷场",
            "supporter_ids": [],
        },
    })
    ra.apply_rescript_batch(db, state, batch2, pre2, content=content)
    stalled = db.find_deliberation_dossier_by_decision_key(key2)
    assert stalled is not None
    assert _dossier_payload(stalled).get("deliberation_state") == "stalled"
    assert db.list_dossier_endorsements(int(stalled["id"])) == []
    issue = db.conn.execute(
        "SELECT status, origin_ref FROM issues WHERE origin_ref=?",
        (f"dossier:{int(stalled['id'])}",),
    ).fetchone()
    assert issue is not None and str(issue["status"]) == "active"

    # --- illegal supporter zero write ---
    state.turn = int(state.turn) + 1
    db.save_state(state)
    db.conn.execute("DELETE FROM pending_decisions WHERE kind='rescript_draft'")
    urgent3, _ = _plant_urgent_desk(db, state)
    key3 = urgent3["decision_key"]
    dossiers_before = len(db.list_decree_dossiers())
    batch3 = ra.validate_all([urgent3], [{
        "decision_key": key3, "action": "deliberate", "label": "下部议",
    }])
    pre3 = ra.PrewriteResults(deliberate_by_key={
        key3: {
            "title": "t", "body": "b", "stance": "s",
            "supporter_ids": ["不存在的大臣XYZ"],
        },
    })
    with pytest.raises(ValueError, match="非法站台身份"):
        ra.apply_rescript_batch(db, state, batch3, pre3, content=content)
    assert len(db.list_decree_dossiers()) == dossiers_before
    assert db.find_deliberation_dossier_by_decision_key(key3) is None
    hit = next(r for r in db.list_rescript_drafts() if r["title"] == "陕西告饥")
    assert hit["status"] == "pending"


def test_658_imperial_push_reuses_stalled_and_backing_credit(game):
    """#658：御笔强推复用 stalled；处置命中站台者写辜负；幻影 backing 零写。"""
    from ming_sim import rescript_actions as ra
    from ming_sim.credit_events import KIND_BETRAY

    db, state, content = game
    minister = _summonable_name(db, content)

    # plant stalled deliberation via deliberate
    urgent, _ = _plant_urgent_desk(db, state)
    key = urgent["decision_key"]
    batch = ra.validate_all([urgent], [{
        "decision_key": key, "action": "deliberate", "label": "下部议",
    }])
    pre = ra.PrewriteResults(deliberate_by_key={
        key: {
            "title": "南迁", "body": "无人站台。", "stance": "冷",
            "supporter_ids": [],
        },
    })
    ra.apply_rescript_batch(db, state, batch, pre, content=content)
    stalled = db.find_deliberation_dossier_by_decision_key(key)
    did = int(stalled["id"])
    before = len(db.list_decree_dossiers())

    # imperial push via ensure_directive_dossier seam
    dir_id = db.conn.execute(
        "INSERT INTO turn_directives(turn, year, period, actor, text, source, status, dossier_payload_json) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            int(state.turn), int(state.year), int(state.period), minister,
            "着即强推南迁", "test-658", "draft",
            json.dumps({"target_dossier_id": did}, ensure_ascii=False),
        ),
    ).lastrowid
    db.conn.commit()
    ids = db._ensure_directive_dossier(
        state, int(dir_id), "着即强推南迁",
        payload={"target_dossier_id": did},
        commit=True,
    )
    assert ids == [did]
    assert len(db.list_decree_dossiers()) == before  # 不新建第二案卷
    pushed = db.get_decree_dossier(did)
    assert _dossier_payload(pushed).get("deliberation_state") == "backed"
    ends = db.list_dossier_endorsements(did)
    assert any(
        e["form"] == "御笔手敕" and e["imperial"] is True
        and e["decision_key"] == f"directive:{int(dir_id)}"
        and int(e["source_chat_turn_id"] or 0) == 0
        for e in ends
    )

    # illegal target (not stalled) → fail
    with pytest.raises(ValueError, match="stalled|proposed"):
        ra.apply_imperial_deliberation_push(
            db, state, target_dossier_id=did,
            directive_identity="directive:999",
        )

    # plant backed with minister stand, then punish via propose_directive 真生产链
    state.turn = int(state.turn) + 1
    db.save_state(state)
    db.conn.execute("DELETE FROM pending_decisions WHERE kind='rescript_draft'")
    urgent2, _ = _plant_urgent_desk(db, state)
    key2 = urgent2["decision_key"]
    assert key2 != key
    batch2 = ra.validate_all([urgent2], [{
        "decision_key": key2, "action": "deliberate", "label": "下部议",
    }])
    ra.apply_rescript_batch(
        db, state, batch2,
        ra.PrewriteResults(deliberate_by_key={
            key2: {
                "title": "清丈", "body": "臣请清丈。", "stance": "主清",
                "supporter_ids": [minister],
            },
        }),
        content=content,
    )
    backed = db.find_deliberation_dossier_by_decision_key(key2)
    bid = int(backed["id"])

    # 生产 tracer：GameSession.chat→propose_directive → commit → verdict → 信用
    from types import SimpleNamespace
    from ming_sim.session import GameSession

    actor = next(
        n for n in ra.list_deliberation_candidate_ids(db, content) if n != minister
    )
    other = next(
        n for n in ra.list_deliberation_candidate_ids(db, content)
        if n not in {minister, actor}
    )
    tool_args: dict = {
        "decree_text": f"背信弃义，着罚{minister}俸示惩。",
        "punish_action": "罚俸",
        "target_id": minister,
        "amount": 100,
        "backing_dossier_id": bid,
    }

    class _Agent:
        def run(self, _message):
            return SimpleNamespace(
                content="臣已拟旨。",
                tools=[
                    SimpleNamespace(
                        tool_name="propose_directive",
                        result="",
                        arguments=dict(tool_args),
                    )
                ],
            )

    class _Registry:
        def get(self, _character):
            return _Agent()

        def build_draft_line(self):
            return "无"

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = _Registry()
    sess.llm_config = SimpleNamespace(channel="api")
    sess.temporary_characters = set()
    sess._audience_prompt_for_message = lambda message: message
    sess._start_cli_action_intent = lambda *_a, **_k: None
    sess._finish_cli_action_intent = lambda *_a, **_k: None

    def _edge_count() -> int:
        return int(db.conn.execute(
            "SELECT COUNT(*) AS c FROM relation_edge_events WHERE event_kind=?",
            (KIND_BETRAY,),
        ).fetchone()["c"])

    def _pending_count() -> int:
        return int(db.conn.execute(
            "SELECT COUNT(*) AS c FROM pending_actions WHERE status='pending'"
        ).fetchone()["c"])

    result = GameSession.chat(sess, actor, f"拟旨罚{minister}俸。")
    assert result.pending_action_id
    staged = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?",
        (int(result.pending_action_id),),
    ).fetchone()["payload_json"])
    assert int(staged.get("backing_dossier_id") or 0) == bid

    db.commit_pending_actions(
        state, content=content, action_ids=[int(result.pending_action_id)],
    )
    punish = next(
        d for d in db.list_decree_dossiers()
        if d["pending_action_id"] == int(result.pending_action_id)
    )
    assert int(_dossier_payload(punish).get("backing_dossier_id") or 0) == bid

    edges_before = _edge_count()
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": int(punish["id"]), "decision": "promulgated"}],
        content=content,
    )
    edges_after = db.conn.execute(
        "SELECT origin, context, target FROM relation_edge_events "
        "WHERE event_kind=? ORDER BY id DESC LIMIT 1",
        (KIND_BETRAY,),
    ).fetchone()
    assert _edge_count() == edges_before + 1
    assert str(edges_after["origin"] or "").startswith(f"dossier:{bid}")
    assert str(edges_after["target"]) == minister

    # 幻影 / 坏 shape / 显式 0 → 真入口响亮拒绝，零 pending / 零信用
    pending_mid = _pending_count()
    edges_mid = _edge_count()
    for bad in (999999, True, 1.9, "1", 0, -3):
        tool_args.update({
            "decree_text": f"着罚{minister}俸。",
            "target_id": minister,
            "amount": 50,
            "backing_dossier_id": bad,
        })
        with pytest.raises(ValueError):
            GameSession.chat(sess, actor, f"拟旨罚{minister}。")
    assert _pending_count() == pending_mid
    assert _edge_count() == edges_mid

    # 非站台者 → chat 真入口顺颁零信用
    tool_args.update({
        "decree_text": f"着罚{other}俸。",
        "target_id": other,
        "amount": 10,
        "backing_dossier_id": bid,
    })
    other_result = GameSession.chat(sess, actor, f"拟旨罚{other}。")
    assert other_result.pending_action_id
    db.commit_pending_actions(
        state, content=content, action_ids=[int(other_result.pending_action_id)],
    )
    other_d = next(
        d for d in db.list_decree_dossiers()
        if d["pending_action_id"] == int(other_result.pending_action_id)
    )
    edges_b = _edge_count()
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": int(other_d["id"]), "decision": "promulgated"}],
        content=content,
    )
    assert _edge_count() == edges_b

    # 处置案卷被 rejected → 零信用（同 chat→commit→verdict 最短 tracer）
    tool_args.update({
        "decree_text": f"再罚{minister}俸。",
        "target_id": minister,
        "amount": 20,
        "backing_dossier_id": bid,
    })
    rejected_result = GameSession.chat(sess, actor, f"拟旨再罚{minister}。")
    assert rejected_result.pending_action_id
    db.commit_pending_actions(
        state, content=content,
        action_ids=[int(rejected_result.pending_action_id)],
    )
    rejected_d = next(
        d for d in db.list_decree_dossiers()
        if d["pending_action_id"] == int(rejected_result.pending_action_id)
    )
    edges_r = _edge_count()
    db.apply_dossier_verdicts(
        state,
        [rejected_verdict(int(rejected_d["id"]))],
        content=content,
    )
    assert _edge_count() == edges_r


def test_658_endorsement_provenance_xor(game):
    """#658：背书 provenance 恰为 chat_turn 或 decision_key 之一。"""
    db, state, content = game
    minister = _summonable_name(db, content)
    did = db.create_decree_dossier(
        state, action_type="policy", decree_text="试",
        target_kind="policy", target_id="t",
    )
    chat = db.create_chat_turn(state, minister, "658-xor", 0)
    # chat path
    eid = db.add_dossier_endorsement(
        did, form="会签", endorser_id=minister, source_chat_turn_id=chat,
    )
    row = db.list_dossier_endorsements(did)[0]
    assert row["source_chat_turn_id"] == chat and row["decision_key"] == ""
    # decision_key path
    eid2 = db.add_dossier_endorsement(
        did, form="当面站台", endorser_id=minister,
        decision_key="rescript_draft:1:0",
    )
    rows = {e["id"]: e for e in db.list_dossier_endorsements(did)}
    assert rows[eid2]["decision_key"] == "rescript_draft:1:0"
    assert rows[eid2]["source_chat_turn_id"] == 0
    # both → reject
    with pytest.raises(ValueError, match="provenance"):
        db.add_dossier_endorsement(
            did, form="会签", endorser_id=minister,
            source_chat_turn_id=chat, decision_key="x",
        )
    # neither → reject
    with pytest.raises(ValueError, match="provenance"):
        db.add_dossier_endorsement(
            did, form="会签", endorser_id=minister,
        )


def _658_plant_stalled_deliberation(db, state, content, *, title="议而不决"):
    """最短：经 deliberate 真写核种一条 stalled 案卷 + active issue。"""
    from ming_sim import rescript_actions as ra

    urgent, _ = _plant_urgent_desk(db, state)
    key = urgent["decision_key"]
    batch = ra.validate_all([urgent], [{
        "decision_key": key, "action": "deliberate", "label": "下部议",
    }])
    ra.apply_rescript_batch(
        db, state, batch,
        ra.PrewriteResults(deliberate_by_key={
            key: {
                "title": title, "body": f"{title}正文", "stance": "冷",
                "supporter_ids": [],
            },
        }),
        content=content,
    )
    stalled = db.find_deliberation_dossier_by_decision_key(key)
    assert stalled is not None
    return stalled, key


def test_658_candidates_require_active_status(game):
    """#658 F1：罢黜等非 active 不得入廷议站台候选。"""
    from ming_sim import rescript_actions as ra

    db, state, content = game
    name = _summonable_name(db, content)
    assert name in ra.list_deliberation_candidate_ids(db, content)
    db.set_character_status(state, name, "dismissed", "658-candidate")
    assert name not in ra.list_deliberation_candidate_ids(db, content)
    # 非法身份整批零写（dismissed 不再属候选）
    urgent, _ = _plant_urgent_desk(db, state)
    key = urgent["decision_key"]
    before = len(db.list_decree_dossiers())
    batch = ra.validate_all([urgent], [{
        "decision_key": key, "action": "deliberate", "label": "下部议",
    }])
    with pytest.raises(ValueError, match="非法站台身份"):
        ra.apply_rescript_batch(
            db, state, batch,
            ra.PrewriteResults(deliberate_by_key={
                key: {
                    "title": "t", "body": "b", "stance": "s",
                    "supporter_ids": [name],
                },
            }),
            content=content,
        )
    assert len(db.list_decree_dossiers()) == before


def test_658_imperial_push_same_directive_idempotent(game):
    """#658 F2：同 directive 重试 ensure 幂等返回，不因已 backed 假拒。"""
    db, state, content = game
    stalled, _ = _658_plant_stalled_deliberation(db, state, content, title="南迁")
    did = int(stalled["id"])
    dir_id = int(db.add_directive(
        state, None, "着即强推", "test-658-idem",
        dossier_payload={"target_dossier_id": did},
    ))
    payload = {"target_dossier_id": did}
    assert db._ensure_directive_dossier(
        state, int(dir_id), "着即强推", payload=payload, commit=True,
    ) == [did]
    # 重试：已 stalled→backed 仍按同一 directive 绑定幂等返回
    assert db._ensure_directive_dossier(
        state, int(dir_id), "着即强推", payload=payload, commit=True,
    ) == [did]
    ends = [
        e for e in db.list_dossier_endorsements(did)
        if e["form"] == "御笔手敕"
    ]
    assert len(ends) == 1
    assert ends[0]["decision_key"] == f"directive:{int(dir_id)}"


def test_658_stalled_excluded_from_promulgation_validation(game, monkeypatch):
    """#658 F3：判官/校验只覆盖可颁布集合；stalled 同在 proposed 不触发全覆盖炸。"""
    import ming_sim.decree as decree_mod

    db, state, content = game
    stalled, _ = _658_plant_stalled_deliberation(db, state, content, title="冷场")
    stalled_id = int(stalled["id"])
    normal_id = int(db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id=f"river-{state.turn}",
    ))
    seen: list[list[int]] = []

    def provider(dossiers, _state):
        ids = [int(row["id"]) for row in dossiers]
        seen.append(ids)
        assert stalled_id not in ids
        return [{"dossier_id": i, "decision": "promulgated"} for i in ids]

    monkeypatch.setattr(
        db, "list_decree_dossiers_for_simulation",
        lambda _turn: (_ for _ in ()).throw(RuntimeError("stop after durable verdict")),
    )
    with pytest.raises(RuntimeError, match="durable verdict"):
        decree_mod.resolve_directives(
            state, db, None, None, [], "清核河工",
            content=content, promulgation_verdict_provider=provider,
        )
    assert seen == [[normal_id]]
    stored = db.get_pending_promulgation_verdicts(state.turn)
    assert {int(v["dossier_id"]) for v in stored} == {normal_id}
    # stalled 仍 proposed，未入 durable 判决
    assert db.get_decree_dossier(stalled_id)["status"] == "proposed"
    assert _dossier_payload(db.get_decree_dossier(stalled_id)).get(
        "deliberation_state",
    ) == "stalled"


def test_658_free_decree_capture_target_dossier_real_entry(game, monkeypatch):
    """#658 F4：自由下旨 capture 声明/投影 target_dossier_id，经 session.add 真入口强推。"""
    import ming_sim.cli_backend as cli_backend
    from ming_sim.session import GameSession

    db, state, content = game
    stalled, _ = _658_plant_stalled_deliberation(db, state, content, title="南迁之议")
    did = int(stalled["id"])
    before = len(db.list_decree_dossiers())
    prompts: list[str] = []

    def backend(prompt, *_a, **_k):
        prompts.append(str(prompt))
        return (json.dumps({
            "拟旨意图": "拟旨",
            "目标案卷ID": did,
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    payload = cli_backend.capture_manual_directive_payload(
        f"着即强推南迁之议（案卷{did}）", None, db=db, content=content,
    )
    # 契约只锁 structured 字段；不锁 prompt 措辞/排版
    assert payload.get("target_dossier_id") == did
    assert prompts, "须真实走过抽取 backend"

    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content
    session._refuse_if_settling = lambda: None  # type: ignore[attr-defined]
    dv = session.add_directive(
        f"着即强推南迁之议（案卷{did}）", dossier_payload=payload,
    )
    ids = db._ensure_directive_dossier(
        state, int(dv.id), f"着即强推南迁之议（案卷{did}）",
        payload=payload, commit=True,
    )
    assert ids == [did]
    assert len(db.list_decree_dossiers()) == before
    pushed = db.get_decree_dossier(did)
    assert _dossier_payload(pushed).get("deliberation_state") == "backed"
    assert any(
        e["form"] == "御笔手敕" and e["decision_key"] == f"directive:{int(dv.id)}"
        for e in db.list_dossier_endorsements(did)
    )


def test_658_typed_target_rejects_bool_float_string(game, monkeypatch):
    """#658 F4：typed target 只接真正正整数；坏 shape 响亮失败且自由下旨零写。"""
    from ming_sim.db import imperial_push_target_dossier_id
    from ming_sim.session import GameSession
    import ming_sim.cli_backend as cli_backend

    db, state, content = game
    stalled, _ = _658_plant_stalled_deliberation(db, state, content, title="南迁")
    did = int(stalled["id"])
    before_dossiers = len(db.list_decree_dossiers())
    before_ends = len(db.list_dossier_endorsements(did))
    before_dirs = db.conn.execute("SELECT COUNT(*) AS c FROM turn_directives").fetchone()["c"]

    from ming_sim.db import parse_backing_dossier_id

    # 最低层结构化负例：target/backing 共吃正整数契约；显式 0/负亦拒
    for bad in (True, False, 1.9, 1.0, "1", "12", 0, -1):
        with pytest.raises(ValueError):
            imperial_push_target_dossier_id(bad)
        with pytest.raises(ValueError):
            imperial_push_target_dossier_id({"target_dossier_id": bad})
        with pytest.raises(ValueError):
            imperial_push_target_dossier_id({"目标案卷ID": bad})
        with pytest.raises(ValueError):
            parse_backing_dossier_id(bad)
    assert imperial_push_target_dossier_id(did) == did
    assert imperial_push_target_dossier_id({"target_dossier_id": did}) == did
    assert imperial_push_target_dossier_id({}) is None
    assert imperial_push_target_dossier_id({"target_dossier_id": None}) is None
    assert parse_backing_dossier_id(None) is None
    assert parse_backing_dossier_id("") is None
    assert parse_backing_dossier_id(did) == did

    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content
    session._refuse_if_settling = lambda: None  # type: ignore[attr-defined]

    # 自由下旨真入口：坏 shape 不得落 directive / 御笔
    for bad in (True, 1.9, "1"):
        with pytest.raises(ValueError):
            session.add_directive(
                f"着即强推（坏shape）",
                dossier_payload={"target_dossier_id": bad},
            )

    def backend_bad(prompt, *_a, **_k):
        return (json.dumps({
            "拟旨意图": "拟旨",
            "目标案卷ID": True,
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend_bad)
    with pytest.raises(ValueError):
        cli_backend.capture_manual_directive_payload(
            f"着即强推南迁（案卷{did}）", None, db=db, content=content,
        )

    assert len(db.list_decree_dossiers()) == before_dossiers
    assert len(db.list_dossier_endorsements(did)) == before_ends
    assert db.conn.execute(
        "SELECT COUNT(*) AS c FROM turn_directives"
    ).fetchone()["c"] == before_dirs
    assert _dossier_payload(db.get_decree_dossier(did)).get(
        "deliberation_state",
    ) == "stalled"


def test_658_deliberate_faction_stance_sliced_via_prewrite_entry(game, monkeypatch):
    """#658：廷议真入口只把候选 canonical faction 态势送入 LLM 边界（结构化切片）。"""
    from ming_sim import rescript_actions as ra
    from ming_sim.models import TurnPhase
    from ming_sim.session import GameSession
    import ming_sim.agents as agents_mod

    db, state, content = game
    candidates = ra.list_deliberation_candidate_ids(db, content)
    assert candidates
    cand_factions = {
        str(getattr(content.characters.get(n), "faction", "") or "").strip()
        for n in candidates
    }
    cand_factions.discard("")
    assert cand_factions
    hit = next(iter(cand_factions))
    miss = "__658_non_candidate_faction__"
    db.conn.execute(
        "INSERT OR REPLACE INTO factions(name, satisfaction, leverage, agenda) "
        "VALUES (?,?,?,?)",
        (miss, 50, 0, ""),
    )
    db.apply_faction_brew_result(
        faction=hit, stance_segment="候选相关", last_event_id=1,
        turn=int(state.turn), year=int(state.year), period=int(state.period),
    )
    db.apply_faction_brew_result(
        faction=miss, stance_segment="无关派", last_event_id=2,
        turn=int(state.turn), year=int(state.year), period=int(state.period),
    )
    full = {str(r["faction"]) for r in db.get_faction_stance_summaries()}
    assert hit in full and miss in full

    urgent, _ = _plant_urgent_desk(db, state)
    key = urgent["decision_key"]
    db.save_resolve_context(
        int(state.turn), "诏", "邸报",
        {"candidate_events": [], "transit_semantics": []},
        secret_orders=[], relevant_memories=[],
    )
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.llm_config = object()
    sess.agno_db = None
    sess.registry = None
    sess.last_decree = "诏"
    sess.temporary_characters = {}

    llm_inputs: list[str] = []

    def _delib_text(_agent, prompt, **_k):
        llm_inputs.append(str(prompt or ""))
        return json.dumps({
            "title": "廷议",
            "body": "请下部议。",
            "stance": "主",
            "supporter_ids": [],
        }, ensure_ascii=False)

    monkeypatch.setattr(
        agents_mod, "create_rescript_deliberate_agent", lambda *_a, **_k: object(),
    )
    monkeypatch.setattr(agents_mod, "run_agent_text", _delib_text)

    pre = sess.prepare_rescript_prewrite([{
        "decision_key": key, "action": "deliberate", "label": "下部议",
    }])
    assert pre.get("prewrite") is not None
    assert key in pre["prewrite"].deliberate_by_key
    assert llm_inputs, "须真实走过 deliberate LLM 边界"

    # 从 LLM 输入中抽取含 faction 键的 JSON 数组；不锁 prompt 措辞/表头
    decoder = json.JSONDecoder()
    faction_sets: list[set[str]] = []
    blob = llm_inputs[0]
    idx = 0
    while idx < len(blob):
        if blob[idx] != "[":
            idx += 1
            continue
        try:
            value, end = decoder.raw_decode(blob, idx)
        except json.JSONDecodeError:
            idx += 1
            continue
        idx = end
        if not (
            isinstance(value, list)
            and value
            and all(isinstance(row, dict) for row in value)
            and any("faction" in row for row in value)
        ):
            continue
        faction_sets.append({str(row.get("faction") or "") for row in value})
    assert faction_sets, "廷议 LLM 输入须含派系态势结构化切片"
    sliced = set.union(*faction_sets)
    assert hit in sliced
    assert miss not in sliced
    assert sliced <= cand_factions

