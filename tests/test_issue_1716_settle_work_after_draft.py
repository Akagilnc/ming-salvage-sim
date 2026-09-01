"""#1716：拟旨后须形成可 settle 工作——grant 金额运输 + 场外散夜 + 手工新增投影。

票面根因两缝：
1. classifier 常给 amount 整数字符串；#1620 shape 拒字符串 → grant 物化中断、pending=0。
2. 场外记召短路吞掉已开夜「退朝」，散夜失败、夜停 open、拟诏真空。
另：chat done / POST /api/directives 须回传 pending_directive_count，拟诏台不单靠 refresh。
"""

from __future__ import annotations

import json
from types import MethodType, SimpleNamespace

import pytest

from ming_sim.action_clusters import normalize_one_candidate
from ming_sim.action_materialize import (
    MaterializeCtx,
    require_grant_allocation_shape,
    run_materialize_pipeline,
)
from ming_sim.session import ChatTurnResult, GameSession
from tests.test_audience_travel_gating_670 import (
    _set_place,
    _web_hall_runtime,
)
from tests.test_month_loop_tracer_1468 import tracer_client  # noqa: F401 — fixture


def test_grant_shape_accepts_integer_string_rejects_bool_float():
    """#1716 / #1620：整数字符串可入 shape；bool/float 仍 fail-loud。"""
    shaped = require_grant_allocation_shape(
        grant_action="赈灾", amount="8", account="国库",
    )
    assert shaped["amount"] == 8
    assert shaped["account"] == "国库"
    with pytest.raises(ValueError, match="正整数"):
        require_grant_allocation_shape(
            grant_action="赈灾", amount=True, account="国库",
        )
    with pytest.raises(ValueError, match="正整数"):
        require_grant_allocation_shape(
            grant_action="赈灾", amount=1.5, account="国库",
        )


def test_normalize_coerces_amount_integer_string_keeps_optional_none():
    """#658/#1716：as_int+default None 缺省仍 None；有值的整数字符串收成 int。"""
    empty = normalize_one_candidate(
        {"kind": "grant_allocation", "grant_action": "赈灾"}, soft=True,
    )
    assert empty.get("amount") is None
    filled = normalize_one_candidate(
        {
            "kind": "grant_allocation",
            "grant_action": "赈灾",
            "amount": "8",
            "account": "国库",
            "target_id": "shaanxi",
            "target_kind": "region",
        },
        soft=True,
    )
    assert filled["amount"] == 8
    assert isinstance(filled["amount"], int)


def test_grant_pipeline_stages_pending_from_string_amount(game):
    """真 materialize 缝：字符串 amount 不得中断；须落 kind=directive pending。"""
    db, state, content = game
    actor = content.characters["郭允厚"]
    intent = normalize_one_candidate(
        {
            "kind": "grant_allocation",
            "grant_action": "赈灾",
            "amount": "8",
            "account": "国库",
            "target_id": "shaanxi",
            "target_kind": "region",
        },
        soft=True,
    )
    assert intent["amount"] == 8

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.llm_config = SimpleNamespace(channel="cli")
    sess.registry = None

    out = {"pending_action_id": 0, "secret_order_id": 0}
    ctx = MaterializeCtx(
        session=sess,
        character=actor,
        player_message="拟旨如下：着户部从国库拨银八万两赈济陕西饥民。",
        reply="臣领旨。请从国库拨银八万两赈济陕西。",
        message_text="拟旨如下：着户部从国库拨银八万两赈济陕西饥民。",
        explicit_prefixed=True,
        has_directive=False,
        pend_for_minister=[],
        out=out,
        intent=intent,
        intent_kind="grant_allocation",
        llm_config=None,
        intent_candidates=[intent],
    )
    run_materialize_pipeline(ctx)
    assert int(out.get("pending_action_id") or 0) > 0
    pending = [
        p for p in db.list_pending_actions(state.turn)
        if p["kind"] == "directive" and p["status"] == "pending"
    ]
    assert len(pending) == 1
    payload = json.loads(pending[0]["payload_json"])
    assert payload["dossier_action_type"] == "grant_allocation"
    assert payload["amount"] == 8


def test_offsite_open_night_court_break_closes_night(game, monkeypatch):
    """#1716：场外大臣已开夜后「退朝」须收夜，不得再被 SUMMON_* 短路。"""
    import ming_sim.audience_night as an

    db, state, content = game
    remote = _set_place(game, "洪承畴", location="shaanxi")

    def _session_chat(minister_name, message, *, chat_turn_id=0, explicit_secret_order=False):
        raise AssertionError("场外记召不得调回话")

    runtime = _web_hall_runtime(db, state, content, session_chat=_session_chat)
    runtime.session._beat_generator = lambda _inputs: "场外传召途中。"

    # 先记召：开夜 + 场外 scene
    first = runtime.chat(remote.name, "宣洪承畴")
    assert first.get("admission") == "SUMMON_FRESH"
    open_n = an.get_open_night(db)
    assert open_n is not None
    night_id = int(open_n["id"])

    # 证明旁路：退朝不再走 consume_audience_admission（否则会再记 SUMMON_*）
    consumed = []
    real_consume = runtime.session.consume_audience_admission

    def _spy_consume(character, **kwargs):
        consumed.append(str(character.name))
        return real_consume(character, **kwargs)

    runtime.session.consume_audience_admission = _spy_consume

    # 收夜口令：须走 chat 主链；shell 默认 stub close_after，改挂真缝。
    def _break_chat(minister_name, message, *, chat_turn_id=0, explicit_secret_order=False):
        assert message.strip() == "退朝"
        result = ChatTurnResult(answer="臣等恭送陛下。")
        result.court_action = "court_break"
        return result

    runtime.session.chat = MethodType(
        lambda self, *a, **k: _break_chat(*a, **k), runtime.session,
    )
    runtime.session.close_night_after_chat_if_needed = MethodType(
        GameSession.close_night_after_chat_if_needed, runtime.session,
    )
    runtime.session._write_gate = getattr(runtime, "_write_gate", None) or __import__(
        "threading"
    ).Lock()

    payload = runtime.chat(remote.name, "退朝")
    assert consumed == [], f"退朝不得再 consume admission，got {consumed}"
    assert payload.get("court_action") == "court_break"
    assert not payload.get("admission"), payload.get("admission")
    open_after = an.get_open_night(db)
    assert open_after is None, f"散夜后夜仍 open: {open_after}"
    row = db.conn.execute(
        "SELECT status FROM audience_nights WHERE id=?", (night_id,),
    ).fetchone()
    assert row is not None
    assert str(row["status"]) == "closed"


def test_web_create_directive_returns_settle_projection(tracer_client, monkeypatch):
    """POST /api/directives 成功后响应含 directives + pending 投影，state 可 settle。"""
    import ming_sim.cli_backend as cli_backend
    import web_app

    new = tracer_client.post("/api/menu/new_game")
    assert new.status_code == 200
    game = web_app.web_game
    assert game is not None

    def backend(*_a, **_k):
        return json.dumps(
            {
                "拟旨意图": "拟旨",
                "动作类型": "special_decree",
                "目标类型": "policy",
                "目标ID": "relief-shaanxi",
                "颁布方式": "普通",
            },
            ensure_ascii=False,
        ), 1

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    text = "着户部从国库拨银一万两赈济陕西饥民。"
    response = tracer_client.post("/api/directives", json={"text": text, "notes": ""})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["directive"]["id"] > 0
    assert isinstance(body["directives"], list)
    assert len(body["directives"]) >= 1
    assert "pending_directive_count" in body
    assert "pending_count" in body

    state = tracer_client.get("/api/game/state").json()
    has_settle = (
        len(state.get("directives") or []) > 0
        or int(state.get("pending_directive_count") or 0) > 0
    )
    assert has_settle, state
