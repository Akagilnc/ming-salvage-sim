"""CLI 后端会话落地的共享真源（session.apply_cli_conversation_actions）。

补 toolcall 缺口——agy/codex 不做 function-calling，原 propose_directive /
secret_order / 会话动作工具不触发。靠 apply_cli_conversation_actions 一处把
拟旨/密令前缀入档 + LLM 判会话动作（更新/催办/提交核议/记进展/调教）落地；
session.chat 非流式路径与 web streaming 路径共用它，杜绝漂移（CMR F3 / codexC-1）。

方法只用 self.db/state/registry，故用 fake self（绑定方法）测，不构造完整 GameSession。
"""

from __future__ import annotations

import json
import threading
import types
from types import SimpleNamespace

import pytest

_POLICY_FIELDS = {
    "dossier_action_type": "policy",
    "target_kind": "issue",
    "target_id": "test-policy",
}

import ming_sim.audience_night as audience_night
import ming_sim.cli_backend as cb
import ming_sim.session as session_mod
from ming_sim.session import GameSession
from tests.dossier_test_helpers import TYPED_COVERT_EXTRACT, TYPED_COVERT_TASK, create_test_secret_order as _create_secret_order, promulgate_proposed_appointments


def _result():
    return SimpleNamespace(answer="", proposed_directive=None, secret_order_id=None, pending_action_id=0)


def test_non_streaming_path_surfaces_pending_action_id(game, monkeypatch):
    """非流式 session 路径(_cli_backend_fallback_actions)也要 surface pending_action_id,
    与流式不漂移(ship-pre CMR);暂存不当场落 secret_order_id。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    who = "非流式承办官"
    oid = _create_secret_order(db, state, who, "原标题", "原内容", [], deadline_months=0)
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "更新", "order_id": oid, "new_title": "改", "new_content": "改",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": ""})
    result = _result()
    result.answer = "臣领旨，已记改。"
    # 非 classifier 契约：显式 candidate，禁止 serial classify → 真 subprocess。
    _session(db, state)._cli_backend_fallback_actions(
        result, SimpleNamespace(name=who, office_type="兵部"), "改一下要旨",
        preclassified_intent={
            "kind": "secret", "secret_action": "更新", "order_id": oid,
            "new_title": "改", "new_content": "改", "deadline_months": 0,
            "cultivate_skill": "", "cultivate_trait": "",
        })
    assert result.pending_action_id        # 非流式也回传 staged 信号
    assert result.secret_order_id is None  # 暂存不当场落库


def _session(db, state, registry=None, llm_config=None, content=None):
    """fake self：带 db/state/registry(+content) + 绑定共享方法与适配器。"""
    s = SimpleNamespace(
        db=db,
        state=state,
        registry=registry,
        content=content,
        llm_config=llm_config or SimpleNamespace(channel=""),
    )
    s.apply_cli_conversation_actions = types.MethodType(
        GameSession.apply_cli_conversation_actions, s)
    s._cli_backend_fallback_actions = types.MethodType(
        GameSession._cli_backend_fallback_actions, s)
    s._merge_staged_new_secret_order_content = types.MethodType(
        GameSession._merge_staged_new_secret_order_content, s)
    return s


def _no_conv_action(monkeypatch):
    """默认让会话动作判定返回「无」，避免无关测试触发真 backend。"""
    monkeypatch.setattr(cb, "extract_minister_actions",
                        lambda *a, **k: {"secret_action": "无", "order_id": 0,
                                         "new_title": "", "new_content": "", "deadline_months": 0,
                                         "cultivate_skill": "", "cultivate_trait": ""})
    monkeypatch.setattr(cb, "_trace", lambda rec: None)


def test_opening_seed_secret_orders_empty_or_structured(game):
    """#1274 K1 seed 开局合约：生产开局同核无预置密令（或 content 来自结构化源）。"""
    db, _state, _ = game
    orders = db.list_secret_orders()
    # 当前生产开局：零条预置密令
    assert orders == []


def test_scene_secret_order_progress_stages_pending_not_direct_write(game):
    """转译记录往期密令进展先走候选闸门，不直写真实密令。"""
    from ming_sim.audience_translate import normalize_audience_declaration
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    minister = "毕自严"
    oid = _create_secret_order(db, state, minister, "查辽饷", "查辽饷侵冒。", [], deadline_months=0)
    db.conn.execute("UPDATE secret_orders SET turn_issued=? WHERE id=?", (state.turn - 1, oid))
    db.conn.commit()

    declaration = normalize_audience_declaration({"commissions": [{
        "text": "奏报密令进展。",
        "secret_order_progress": {"order_id": oid, "note": "已封存兵部辽饷册。"},
    }]})
    result = dispatch_declaration(db, state, declaration, minister_name=minister)
    assert result.commissions.rejected == []
    assert "已封存兵部辽饷册" not in (
        db.conn.execute("SELECT result FROM secret_orders WHERE id=?", (oid,)).fetchone()["result"] or ""
    )
    pending = db.list_pending_actions(state.turn)
    assert len(pending) == 1
    assert pending[0]["kind"] == "secret_order" and pending[0]["action"] == "记进展"
    assert pending[0]["target_id"] == oid


def test_scene_directive_midzhi_stages_draft(game):
    """场景交办明示中旨时暂存与成案皆保留模式。"""
    from ming_sim.audience_translate import normalize_audience_declaration
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    declaration = normalize_audience_declaration({"commissions": [{
        "text": "着户部清核辽饷。", "mode": "midzhi",
    }]})
    result = dispatch_declaration(db, state, declaration, minister_name="毕自严")
    assert result.commissions.rejected == []
    pending = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "directive"]
    assert len(pending) == 1
    pending_payload = json.loads(pending[0]["payload_json"])
    assert pending_payload["mode"] == "midzhi"

    db.commit_pending_actions(state, kind_filter="directive")
    db.ensure_dossiers_for_draft_directives(state)
    dossiers = db.list_decree_dossiers()
    assert len(dossiers) == 1
    assert dossiers[0]["mode"] == "midzhi"


def test_api_channel_rejects_existing_pending_action(game, monkeypatch):
    """API/function-call 通道已暂存动作后，下一句拒绝也必须删除 pending，不能早退默认同意。"""
    db, state, _ = game
    minister = "魏忠贤"
    db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={
            "covert_task": TYPED_COVERT_TASK,
            "title": "暗查辽饷",
            "content": "暗查辽饷侵冒。",
            "assignee": minister,
            "tags": [],
            "deadline_months": 0,
        },
    )
    monkeypatch.setattr(
        cb,
        "_run_json_extractor_for_config",
        lambda *a, **k: (json.dumps({"确认": "拒绝"}, ensure_ascii=False), 1),
    )

    GameSession.apply_cli_conversation_actions(
        _session(db, state, llm_config=SimpleNamespace(channel="api")),
        SimpleNamespace(name=minister, office_type="司礼监"),
        player_message="不准，撤了。",
        answer="臣遵旨。",
        has_directive=False,
        secret_order_id=None,
    )

    assert db.list_pending_actions(state.turn) == []


def test_api_channel_uses_api_extractor_for_nonliteral_confirmation(game, monkeypatch):
    """API 通道的非关键词准驳语义应走 API extractor，不应退回 CLI-only backend 后变成无。"""
    db, state, _ = game
    minister = "魏忠贤"
    db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={
            "covert_task": TYPED_COVERT_TASK,
            "title": "暗查辽饷",
            "content": "暗查辽饷侵冒。",
            "assignee": minister,
            "tags": [],
            "deadline_months": 0,
        },
    )
    monkeypatch.setattr(cb, "_run_api_for_config", lambda *a, **k: (json.dumps({"确认": "拒绝"}, ensure_ascii=False), 1))
    monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: (_ for _ in ()).throw(AssertionError("API confirmation should not use CLI backend")))

    GameSession.apply_cli_conversation_actions(
        _session(db, state, llm_config=SimpleNamespace(channel="api")),
        SimpleNamespace(name=minister, office_type="司礼监"),
        player_message="此事且停一停。",
        answer="臣候旨。",
        has_directive=False,
        secret_order_id=None,
    )

    assert db.list_pending_actions(state.turn) == []


def test_confirmation_mixed_rejection_and_approval_cues_uses_semantic_extractor(monkeypatch):
    """“不必多言，准了”这类混合句不能被拒绝子串抢先误删 pending。"""
    calls = []

    def _semantic_confirmation(prompt, llm_config=None, tag="", *, policy=None):
        calls.append((prompt, tag))
        return (json.dumps({"确认": "应允"}, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_json_extractor_for_config", _semantic_confirmation)

    result = cb.extract_confirmation_intent(
        player_message="不必多言，准了。",
        minister_reply="臣候旨。",
        pending_summaries=["新建密令：暗查辽饷"],
        llm_config=SimpleNamespace(channel="api"),
    )

    assert result["confirmation"] == "应允"
    assert result["target_ids"] == []
    assert calls and calls[0][1] == "confirmation"


def test_confirmation_question_with_approval_words_uses_semantic_extractor(monkeypatch):
    """“若准奏会如何？”只是追问后果，不能因含“准奏”走快路提交 pending。"""
    calls = []

    def _semantic_confirmation(prompt, llm_config=None, tag="", *, policy=None):
        calls.append((prompt, tag))
        return (json.dumps({"确认": "无"}, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_json_extractor_for_config", _semantic_confirmation)

    result = cb.extract_confirmation_intent(
        player_message="若准奏会如何？",
        minister_reply="臣候旨。",
        pending_summaries=["草拟圣旨：清核辽饷"],
        llm_config=SimpleNamespace(channel="api"),
    )

    assert result["confirmation"] == "无"
    assert result["target_ids"] == []
    assert calls and calls[0][1] == "confirmation"


def test_confirmation_negated_approval_phrase_is_rejection(monkeypatch):
    """“不可照办”由结构化 LLM 枚举判拒绝，不靠含“照办”的词表快路。"""
    calls = []

    def _semantic_confirmation(prompt, llm_config=None, tag="", *, policy=None):
        calls.append((prompt, tag))
        return (json.dumps({"确认": "拒绝"}, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_json_extractor_for_config", _semantic_confirmation)

    result = cb.extract_confirmation_intent(
        player_message="不可照办。",
        minister_reply="臣候旨。",
        pending_summaries=["新建密令：暗查辽饷"],
        llm_config=SimpleNamespace(channel="api"),
    )

    assert result["confirmation"] == "拒绝"
    assert result["target_ids"] == []
    assert calls and calls[0][1] == "confirmation"


def test_confirmation_soft_negated_approval_phrase_is_rejection(monkeypatch):
    """“先别照办”由结构化 LLM 枚举判拒绝，不靠词表快路。"""
    calls = []

    def _semantic_confirmation(prompt, llm_config=None, tag="", *, policy=None):
        calls.append((prompt, tag))
        return (json.dumps({"确认": "拒绝"}, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_json_extractor_for_config", _semantic_confirmation)

    result = cb.extract_confirmation_intent(
        player_message="先别照办。",
        minister_reply="臣候旨。",
        pending_summaries=["新建密令：暗查辽饷"],
        llm_config=SimpleNamespace(channel="api"),
    )

    assert result["confirmation"] == "拒绝"
    assert result["target_ids"] == []
    assert calls and calls[0][1] == "confirmation"


def test_confirmation_negated_approval_no_wordlist_when_extractor_fails(monkeypatch):
    """抽取失败 → 「无」；禁词表快路在 extractor down 时顶替拒绝。"""
    monkeypatch.setattr(
        cb,
        "_run_json_extractor_for_config",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("extractor down")),
    )

    result = cb.extract_confirmation_intent(
        player_message="不可准奏。",
        minister_reply="臣候旨。",
        pending_summaries=["草拟圣旨：清核辽饷"],
        llm_config=SimpleNamespace(channel="api"),
    )

    assert result["confirmation"] == "无"
    assert result["target_ids"] == []


def test_confirmation_bubi_zhaoban_no_wordlist_when_extractor_fails(monkeypatch):
    """抽取失败 → 「无」；“不必照办”亦不得词表快路顶替。"""
    monkeypatch.setattr(
        cb,
        "_run_json_extractor_for_config",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("extractor down")),
    )

    result = cb.extract_confirmation_intent(
        player_message="不必照办。",
        minister_reply="臣候旨。",
        pending_summaries=["新建密令：暗查辽饷"],
        llm_config=SimpleNamespace(channel="api"),
    )

    assert result["confirmation"] == "无"
    assert result["target_ids"] == []


def test_scene_promises_confirm_directive_and_secret_order_independently(game):
    """同轮两项应允：密令即落档，拟旨经收夜提交，不彼此吞并。"""
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    minister = next(iter(content.characters.values())).name
    directive_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={**_POLICY_FIELDS, "text": "着户部清核辽饷。", "actor": minister},
    )
    secret_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister,
        payload={"covert_task": TYPED_COVERT_TASK, "title": "暗查辽饷",
                 "content": "暗查辽饷侵冒。", "assignee": minister,
                 "tags": [], "deadline_months": 0},
    )
    result = dispatch_declaration(db, state, {"promises": [
        {"action_id": action_id, "decision": "应允"}
        for action_id in (directive_id, secret_id)
    ]}, minister_name=minister)
    assert result.promises.rejected == []
    assert {r["action_id"] for r in result.promises.applied} == {directive_id, secret_id}
    assert [order["title"] for order in db.list_secret_orders()] == ["暗查辽饷"]
    assert db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (directive_id,),
    ).fetchone()["night_approved"] == 1
    db.commit_pending_actions(state, action_ids=[directive_id])
    assert db.list_pending_actions(state.turn) == []
    directives = db.list_directives(state, statuses=("draft",))
    assert len(directives) == 1 and directives[0]["text"] == "着户部清核辽饷。"


@pytest.mark.parametrize("kind", ["directive", "office"])
def test_midzhi_confirmation_updates_selected_dossier_mode(game, kind):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    if kind == "directive":
        pending_id = db.stage_pending_action(
            state.turn, kind="directive", action="拟旨", minister_name=minister,
            payload={**_POLICY_FIELDS, "text": "着户部清核辽饷。", "actor": minister,
                     "mode": "ordinary"},
        )
    else:
        pending_id = db.stage_pending_action(
            state.turn, kind="office", action="任命", minister_name=minister,
            payload={"text": "测试任免原文", "name": "史可法", "office": "兵部主事", "appointer": minister,
                     "mode": "ordinary"},
        )

    GameSession.apply_cli_conversation_actions(
        _session(db, state, content=content),
        SimpleNamespace(name=minister, office_type="兵部"),
        player_message="中旨直发，准了。", answer="臣领旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "confirmation", "confirmation": "应允", "mode": "midzhi"},
        confirm_target_ids={pending_id},
    )

    if kind == "directive":
        row = db.conn.execute(
            "SELECT dossier_payload_json FROM turn_directives WHERE turn=?",
            (state.turn,),
        ).fetchone()
        assert json.loads(row["dossier_payload_json"])["mode"] == "midzhi"
    else:
        dossiers = [
            row for row in db.list_decree_dossiers(status="proposed")
            if row["action_type"] == "appointment"
        ]
        assert len(dossiers) == 1
        assert dossiers[0]["mode"] == "midzhi"


@pytest.mark.parametrize(
    ("lifecycle", "kind", "raw_payload"),
    [
        ("immediate", "directive", "{malformed"),
        ("night", "office", "[]"),
        ("recovery", "directive", "null"),
    ],
)
def test_confirmation_preserves_invalid_payload_for_terminal_failure_owner(
        game, lifecycle, kind, raw_payload):
    """确认只写有效对象的元数据；坏载荷由各生命周期的提交端判 failed。"""
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    night = audience_night.open_night(db, state) if lifecycle == "night" else None
    if lifecycle == "recovery":
        state.turn_phase = "settling"
    pending_id = db.stage_pending_action(
        state.turn, kind=kind, action="拟旨" if kind == "directive" else "任命",
        minister_name=minister, payload={"placeholder": True},
    )
    db.conn.execute(
        "UPDATE pending_actions SET payload_json=? WHERE id=?",
        (raw_payload, pending_id),
    )
    db.conn.commit()

    GameSession.apply_cli_conversation_actions(
        _session(db, state, content=content),
        SimpleNamespace(name=minister, office_type="兵部"),
        player_message="中旨直发，准了。", answer="臣领旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "confirmation", "confirmation": "应允", "mode": "midzhi"},
        confirm_target_ids={pending_id},
    )

    row = db.conn.execute(
        "SELECT status, payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()
    assert row["payload_json"] == raw_payload
    if lifecycle == "night":
        assert row["status"] == "pending"
        audience_night.close_night(db, state, night_id=night["id"], content=content)
    elif lifecycle == "recovery":
        assert row["status"] == "pending"
        db.commit_pending_actions(state, content=content)

    terminal = db.conn.execute(
        "SELECT status, payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()
    assert terminal["status"] == "failed"
    assert terminal["payload_json"] == raw_payload


def test_night_approved_midzhi_confirmation_keeps_mode_through_close(game):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    night = audience_night.open_night(db, state)
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={**_POLICY_FIELDS, "text": "着户部清核辽饷。", "actor": minister,
                 "mode": "ordinary"},
    )

    GameSession.apply_cli_conversation_actions(
        _session(db, state, content=content),
        SimpleNamespace(name=minister, office_type="兵部"),
        player_message="中旨直发，准了。", answer="臣领旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "confirmation", "confirmation": "应允", "mode": "midzhi"},
        confirm_target_ids={pending_id},
    )
    audience_night.close_night(db, state, night_id=night["id"], content=content)

    dossiers = db.list_decree_dossiers(status="proposed")
    assert len(dossiers) == 1
    assert dossiers[0]["mode"] == "midzhi"


def test_pending_directive_identity_version_increments_on_edit(game):
    """A decree forecast identity is the durable pending row plus its draft version."""
    from ming_sim.declaration_dispatch import (
        pending_action_decree_ref, stage_declaration,
    )
    from ming_sim.entities.staged_declaration.store import DecreeAlreadySettled

    db, state, content = game
    minister = next(iter(content.characters.values())).name
    pending_id = db.stage_explicit_directive(
        state.turn, minister, "着户部清核辽饷。",
    )

    row = db.conn.execute(
        "SELECT id,version FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()
    assert (int(row["id"]), int(row["version"])) == (pending_id, 1)
    old_ref = pending_action_decree_ref(pending_id, int(row["version"]))
    stage_declaration(db, decree_ref=old_ref, declaration={"commissions": []}, turn=state.turn)

    db.update_directive_candidate(pending_id, {
        **_POLICY_FIELDS,
        "text": "着户部重核辽饷。",
        "actor": minister,
    })
    row = db.conn.execute(
        "SELECT id,version FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()
    assert (int(row["id"]), int(row["version"])) == (pending_id, 2)
    assert db.conn.execute(
        "SELECT status FROM staged_declarations WHERE decree_ref=?",
        (old_ref,),
    ).fetchone()["status"] == "discarded"
    with pytest.raises(DecreeAlreadySettled):
        stage_declaration(
            db, decree_ref=old_ref, declaration={"commissions": []}, turn=state.turn,
        )


def test_undo_directive_edit_restores_text_with_new_forecast_version(game):
    from ming_sim.declaration_dispatch import (
        pending_action_decree_ref, stage_declaration,
    )

    db, state, content = game
    minister = next(iter(content.characters.values())).name
    pending_id = db.stage_explicit_directive(state.turn, minister, "着户部清核辽饷。")
    chat_turn_id = db.create_chat_turn(state, minister, "undo-directive-edit", 0)
    before = db.capture_chat_rollback_snapshot()
    db.update_directive_candidate(pending_id, {
        **_POLICY_FIELDS,
        "text": "着户部重核辽饷。",
        "actor": minister,
    })
    after = db.capture_chat_rollback_snapshot()
    db.record_chat_turn_rollback_diffs(chat_turn_id, before, after)

    db.undo_chat_turn(chat_turn_id)

    row = db.conn.execute(
        "SELECT id,version,payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()
    assert (int(row["id"]), int(row["version"])) == (pending_id, 3)
    assert json.loads(row["payload_json"])["text"] == "着户部清核辽饷。"
    restored_ref = pending_action_decree_ref(pending_id, 3)
    stage_declaration(db, decree_ref=restored_ref, declaration={"commissions": []}, turn=state.turn)


def test_withdraw_directive_invalidates_its_forecast(game):
    from ming_sim.declaration_dispatch import (
        pending_action_decree_ref, stage_declaration,
    )
    from ming_sim.entities.staged_declaration.store import DecreeAlreadySettled

    db, state, content = game
    minister = next(iter(content.characters.values())).name
    pending_id = db.stage_explicit_directive(state.turn, minister, "着户部清核辽饷。")
    forecast_ref = pending_action_decree_ref(pending_id, 1)
    stage_declaration(
        db, decree_ref=forecast_ref, declaration={"commissions": []}, turn=state.turn,
    )

    assert db.withdraw_pending_action(pending_id, state.turn)
    assert db.conn.execute(
        "SELECT 1 FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone() is None
    assert db.conn.execute(
        "SELECT status FROM staged_declarations WHERE decree_ref=?",
        (forecast_ref,),
    ).fetchone()["status"] == "discarded"
    with pytest.raises(DecreeAlreadySettled):
        stage_declaration(
            db, decree_ref=forecast_ref,
            declaration={"commissions": []}, turn=state.turn,
        )


def _forecast_decision_block():
    return "<<DECISION>>" + json.dumps({
        "title": "廷议",
        "context": "待择",
        "options": [{"label": "施行"}, {"label": "暂缓"}],
    }, ensure_ascii=False) + "<<END>>"


def _forecast_config():
    from ming_sim.models import LLMConfig

    return LLMConfig(
        api_key="test", base_url="https://example.invalid/v1", model="test-model",
    )


def test_approved_directives_forecast_independently_and_keep_midzhi_stage_only(
    game, monkeypatch,
):
    """真实应允入口分别启动逐旨预推；429 不牵连中旨，产物只入 C0 暂存。"""
    from ming_sim.declaration_dispatch import pending_action_decree_ref
    from ming_sim.exceptions import LLMUnavailable
    from ming_sim.session_write_queue import get_session_write_queue
    import ming_sim.decree as decree_mod
    import ming_sim.decree_forecast as forecast_mod
    import ming_sim.month_translate as month_translate

    db, state, content = game
    minister = next(iter(content.characters.values())).name
    night = audience_night.open_night(db, state)
    ordinary_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={**_POLICY_FIELDS, "text": "甲旨", "actor": minister,
                 "mode": "ordinary"},
    )
    midzhi_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={**_POLICY_FIELDS, "text": "乙旨", "actor": minister,
                 "mode": "ordinary"},
    )
    observed_modes = []
    simulator_calls = []
    translation_calls = []

    def judge(_agent, prompt, **_kwargs):
        context = json.loads(prompt)
        dossier = context["dossiers"][0]
        observed_modes.append(dossier["mode"])
        if dossier["mode"] == "ordinary":
            raise LLMUnavailable("exhausted", code="http_429", status_code=429)
        return json.dumps({
            "verdicts": [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        })

    def simulate(_agent, _prompt, **_kwargs):
        simulator_calls.append(1)
        return "旨意后果" + _forecast_decision_block() + "问后叙述"

    def translate(prompt, _llm_config, **_kwargs):
        translation_calls.append(1)
        return {"commissions": []}

    monkeypatch.setattr(decree_mod, "run_agent_text", judge)
    monkeypatch.setattr(forecast_mod.agents, "run_agent_text", simulate)
    monkeypatch.setattr(month_translate, "run_declaration_translate_prompt", translate)
    s = _session(db, state, content=content, llm_config=_forecast_config())
    s.agno_db = None
    for pending_id, mode in ((ordinary_id, "ordinary"), (midzhi_id, "midzhi")):
        GameSession.apply_cli_conversation_actions(
            s, SimpleNamespace(name=minister, office_type="兵部"),
            player_message="应允。", answer="臣领旨。", has_directive=False,
            secret_order_id=None,
            preclassified_intent={
                "kind": "confirmation", "confirmation": "应允", "mode": mode,
            },
            confirm_target_ids={pending_id},
        )

    assert get_session_write_queue(s).wait_idle(timeout_s=5)
    ref = pending_action_decree_ref(midzhi_id, 1)
    staged = db.conn.execute(
        "SELECT status FROM staged_declarations WHERE decree_ref=?", (ref,),
    ).fetchone()
    assert staged is not None and staged["status"] == "staged"
    assert db.conn.execute(
        "SELECT 1 FROM staged_declarations WHERE decree_ref=?",
        (pending_action_decree_ref(ordinary_id, 1),),
    ).fetchone() is None
    assert sorted(observed_modes) == ["midzhi", "ordinary"]
    assert simulator_calls == [1]
    assert translation_calls == [1]
    assert db.conn.execute(
        "SELECT 1 FROM decree_dossiers WHERE pending_action_id IN (?,?)",
        (ordinary_id, midzhi_id),
    ).fetchone() is None
    assert db.conn.execute(
        "SELECT 1 FROM story_ledger_entries WHERE origin_ref=?", (ref,),
    ).fetchone() is None


def test_question_first_during_decree_forecast_is_not_translated_or_staged(
    game, monkeypatch,
):
    """问处起首则无问前声明，但请旨与顺颁判决仍留在该旨暂存上。"""
    from ming_sim.exceptions import LLMUnavailable
    from ming_sim.session_write_queue import get_session_write_queue
    import ming_sim.decree as decree_mod
    import ming_sim.decree_forecast as forecast_mod
    import ming_sim.month_translate as month_translate

    db, state, content = game
    minister = next(iter(content.characters.values())).name
    night = audience_night.open_night(db, state)
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={**_POLICY_FIELDS, "text": "中旨", "actor": minister,
                 "mode": "midzhi"},
    )
    translated = []

    def judge(_agent, prompt, **_kwargs):
        dossier = json.loads(prompt)["dossiers"][0]
        return json.dumps({
            "verdicts": [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        })

    monkeypatch.setattr(decree_mod, "run_agent_text", judge)
    monkeypatch.setattr(
        forecast_mod.agents, "run_agent_text",
        lambda *_a, **_k: _forecast_decision_block() + "question-followup",
    )
    monkeypatch.setattr(
        month_translate, "run_declaration_translate_prompt",
        lambda *_a, **_k: translated.append(1) or {"commissions": []},
    )
    s = _session(db, state, content=content, llm_config=_forecast_config())
    s.agno_db = None
    GameSession.apply_cli_conversation_actions(
        s, SimpleNamespace(name=minister, office_type="兵部"),
        player_message="中旨应允。", answer="臣领旨。", has_directive=False,
        secret_order_id=None,
        preclassified_intent={
            "kind": "confirmation", "confirmation": "应允", "mode": "midzhi",
        },
        confirm_target_ids={pending_id},
    )

    assert get_session_write_queue(s).wait_idle(timeout_s=5)
    assert translated == []
    from ming_sim.declaration_dispatch import pending_action_decree_ref
    stored = db.staged_declarations.staged_for(pending_action_decree_ref(pending_id, 1))
    assert len(stored) == 1
    assert stored[0].declaration == {}
    assert stored[0].verdict["decision"] == "promulgated"
    assert stored[0].questions and stored[0].questions[0]["title"] == "廷议"
    assert db.list_pending_decisions(state.turn) == []


def test_opening_a_night_forecasts_held_decrees_by_dossier_identity(game, monkeypatch):
    """A newly opened audience night schedules a held proposal through its dossier id."""
    from ming_sim.session_write_queue import get_session_write_queue
    import ming_sim.decree as decree_mod
    import ming_sim.decree_forecast as forecast_mod
    import ming_sim.month_translate as month_translate

    db, state, content = game
    state.turn += 1
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="核议辽饷旧旨",
        target_kind="issue",
        target_id="test-policy",
        payload={**_POLICY_FIELDS},
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET status='proposed', promulgation_decision='rejected', "
        "held_turn=?, rescript_pending=0 WHERE id=?",
        (state.turn - 1, dossier_id),
    )
    db.conn.commit()

    def judge(_agent, prompt, **_kwargs):
        candidate = json.loads(prompt)["dossiers"][0]
        return json.dumps({
            "verdicts": [{"dossier_id": candidate["id"], "decision": "promulgated"}],
        })

    monkeypatch.setattr(decree_mod, "run_agent_text", judge)
    monkeypatch.setattr(
        forecast_mod.agents, "run_agent_text", lambda *_a, **_k: "预推叙述",
    )
    monkeypatch.setattr(
        month_translate, "run_declaration_translate_prompt",
        lambda *_a, **_k: {"commissions": []},
    )
    s = _session(db, state, content=content, llm_config=_forecast_config())
    s.agno_db = None
    s.consume_audience_admission = types.MethodType(
        GameSession.consume_audience_admission, s,
    )
    s.admit_audience = lambda _character: session_mod.AudienceAdmissionDecision(
        session_mod.AudienceAdmission.SUMMON_FRESH,
    )
    s.consume_audience_admission(
        SimpleNamespace(name="传召承办官"), origin_id="night-opening-test",
    )

    assert get_session_write_queue(s).wait_idle(timeout_s=5)
    staged = db.conn.execute(
        "SELECT status FROM staged_declarations WHERE decree_ref=?",
        (f"dossier:{dossier_id}",),
    ).fetchone()
    assert staged is not None and staged["status"] == "staged"
    held = db.get_decree_dossier(dossier_id)
    assert held["promulgation_decision"] == "rejected"
    assert db.conn.execute(
        "SELECT 1 FROM story_ledger_entries WHERE origin_ref=?",
        (f"dossier:{dossier_id}",),
    ).fetchone() is None


def test_mixed_directive_secret_confirmation_does_not_commit_unmentioned_office(game):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    ch = SimpleNamespace(name=minister, office_type="兵部")
    db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister, target_id=None,
        payload={**_POLICY_FIELDS, "text": "着户部清核辽饷。", "actor": minister},
    )
    db.stage_pending_action(
        state.turn, kind="office", action="任命", minister_name=minister, target_id=None,
        payload={"text": "测试任免原文", "name": "史可法", "office": "兵部主事"},
    )
    db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={
            "covert_task": TYPED_COVERT_TASK,
            "title": "暗查辽饷",
            "content": "暗查辽饷侵冒。",
            "assignee": minister,
            "tags": [],
            "deadline_months": 0,
        },
    )

    GameSession.apply_cli_conversation_actions(
        _session(db, state, content=content),
        ch,
        player_message="圣旨和密令都准。",
        answer="臣领旨。",
        has_directive=False,
        secret_order_id=None,
        preclassified_intent={"kind": "confirmation", "confirmation": "应允"},
    )

    pending = db.list_pending_actions(state.turn)
    assert [(p["kind"], p["action"]) for p in pending] == [("office", "任命")]
    assert [order["title"] for order in db.list_secret_orders()] == ["暗查辽饷"]
    directives = db.list_directives(state, statuses=("pending",))
    assert len(directives) == 1
    assert directives[0]["text"] == "着户部清核辽饷。"


def test_confirmation_all_regex_does_not_treat_preparing_as_all_targets():
    """“都准备好了”里的“准”不是确认“都准”，不能把 directive 一并卷入。"""
    pending = [
        {"id": 1, "kind": "directive", "action": "拟旨"},
        {"id": 2, "kind": "secret_order", "action": "新建"},
        {"id": 3, "kind": "office", "action": "任命"},
    ]

    targets = session_mod._confirmation_targets_for_message(pending, "都准备好了。")

    assert [item["id"] for item in targets] == [2, 3]


def test_duchayuan_does_not_confirm_directive_as_all_targets(game):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    ch = SimpleNamespace(name=minister, office_type="兵部")
    db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister, target_id=None,
        payload={**_POLICY_FIELDS, "text": "着户部清核辽饷。", "actor": minister},
    )
    db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={
            "covert_task": TYPED_COVERT_TASK,
            "title": "暗查辽饷",
            "content": "暗查辽饷侵冒。",
            "assignee": minister,
            "tags": [],
            "deadline_months": 0,
        },
    )

    GameSession.apply_cli_conversation_actions(
        _session(db, state, content=content),
        ch,
        player_message="那道密令交都察院办，准了。",
        answer="臣领旨。",
        has_directive=False,
        secret_order_id=None,
        preclassified_intent={"kind": "confirmation", "confirmation": "应允"},
    )

    pending = db.list_pending_actions(state.turn)
    assert [(p["kind"], p["action"]) for p in pending] == [("directive", "拟旨")]
    assert [order["title"] for order in db.list_secret_orders()] == ["暗查辽饷"]
    assert db.list_directives(state, statuses=("pending", "draft")) == []


def test_secret_confirmation_does_not_drop_office_pending(game):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    ch = SimpleNamespace(name=minister, office_type="兵部")
    db.stage_pending_action(
        state.turn, kind="office", action="任命", minister_name=minister, target_id=None,
        payload={"text": "测试任免原文", "name": "史可法", "office": "兵部主事"},
    )
    db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={
            "covert_task": TYPED_COVERT_TASK,
            "title": "暗查辽饷",
            "content": "暗查辽饷侵冒。",
            "assignee": minister,
            "tags": [],
            "deadline_months": 0,
        },
    )

    GameSession.apply_cli_conversation_actions(
        _session(db, state, content=content),
        ch,
        player_message="那道密令作罢。",
        answer="臣候旨。",
        has_directive=False,
        secret_order_id=None,
        preclassified_intent={"kind": "confirmation", "confirmation": "拒绝"},
    )

    pending = db.list_pending_actions(state.turn)
    assert [(p["kind"], p["action"]) for p in pending] == [("office", "任命")]
    assert db.list_secret_orders() == []


def test_mixed_directive_and_secret_rejection_drops_both(game):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    ch = SimpleNamespace(name=minister, office_type="兵部")
    db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister, target_id=None,
        payload={**_POLICY_FIELDS, "text": "着户部清核辽饷。", "actor": minister},
    )
    db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={
            "covert_task": TYPED_COVERT_TASK,
            "title": "暗查辽饷",
            "content": "暗查辽饷侵冒。",
            "assignee": minister,
            "tags": [],
            "deadline_months": 0,
        },
    )

    GameSession.apply_cli_conversation_actions(
        _session(db, state, content=content),
        ch,
        player_message="圣旨和密令都作罢。",
        answer="臣候旨。",
        has_directive=False,
        secret_order_id=None,
        preclassified_intent={"kind": "confirmation", "confirmation": "拒绝"},
    )

    assert db.list_pending_actions(state.turn) == []
    assert db.list_secret_orders() == []
    assert db.list_directives(state, statuses=("pending", "draft")) == []


def test_mixed_directive_and_secret_bare_doubuzhun_drops_both(game):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    ch = SimpleNamespace(name=minister, office_type="兵部")
    db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister, target_id=None,
        payload={**_POLICY_FIELDS, "text": "着户部清核辽饷。", "actor": minister},
    )
    db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={
            "covert_task": TYPED_COVERT_TASK,
            "title": "暗查辽饷",
            "content": "暗查辽饷侵冒。",
            "assignee": minister,
            "tags": [],
            "deadline_months": 0,
        },
    )

    GameSession.apply_cli_conversation_actions(
        _session(db, state, content=content),
        ch,
        player_message="都不准。",
        answer="臣候旨。",
        has_directive=False,
        secret_order_id=None,
        preclassified_intent={"kind": "confirmation", "confirmation": "拒绝"},
    )

    assert db.list_pending_actions(state.turn) == []
    assert db.list_secret_orders() == []
    assert db.list_directives(state, statuses=("pending", "draft")) == []


def test_scene_new_secret_order_is_not_confirmed_in_same_turn(game):
    """同轮新建密令不能被同轮应允声明直接落地。"""
    from ming_sim.audience_translate import normalize_audience_declaration
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    minister = "毕自严"
    next_id = db.conn.execute(
        "SELECT COALESCE(MAX(id), 0)+1 FROM pending_actions"
    ).fetchone()[0]
    declaration = normalize_audience_declaration({
        "commissions": [{"text": "密查辽饷。", "secret_order": {
            "title": "暗查辽饷", "content": "暗查辽饷侵冒。",
            "assignee": minister, "tags": [], "deadline_months": 0,
            "covert_task": TYPED_COVERT_TASK,
        }}],
        "promises": [{"action_id": next_id, "decision": "应允"}],
    })
    result = dispatch_declaration(db, state, declaration, minister_name=minister)
    assert result.commissions.rejected == []
    assert result.commissions.applied[0]["id"] == next_id
    assert len(result.promises.rejected) == 1
    assert db.list_secret_orders() == []
    pending = db.list_pending_actions(state.turn)
    assert len(pending) == 1 and pending[0]["kind"] == "secret_order"


def test_scene_two_independent_secret_commissions_commit_separately(game):
    """两条新交办分别暂存和落档，不因同一承办人合并成一案。"""
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, _content = game
    minister = "毕自严"
    declaration = {"commissions": [
        {"text": content, "secret_order": {
            "title": title, "content": content, "assignee": minister,
            "tags": [], "deadline_months": deadline, "covert_task": TYPED_COVERT_TASK,
        }}
        for title, content, deadline in (("暗查甲", "查甲", 0), ("暗查乙", "查乙", 3))
    ]}
    result = dispatch_declaration(db, state, declaration, minister_name=minister)
    assert len(result.commissions.applied) == 2
    assert result.commissions.rejected == []
    assert len(db.list_pending_actions(state.turn)) == 2
    assert db.list_secret_orders() == []
    db.commit_pending_actions(state)
    orders = db.list_secret_orders()
    assert {(r["title"], r["content"], r["due_turn"]) for r in orders} == {
        ("暗查甲", "查甲", 0), ("暗查乙", "查乙", state.turn + 3),
    }


@pytest.mark.parametrize("mode", [None, "ordinary", "midzhi"])
def test_scene_appointment_mode_contract(game, mode):
    """任免声明的显式密旨/普通模式不得被工具退役吞掉。"""
    from ming_sim.audience_translate import normalize_audience_declaration
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    minister = "毕自严"
    appointment = {"name": minister, "office": "户部尚书", "appoint_action": "任命"}
    if mode is not None:
        appointment["mode"] = mode
    declaration = normalize_audience_declaration({"commissions": [{
        "text": "着毕自严为户部尚书。", "appointment": appointment,
    }]})
    result = dispatch_declaration(db, state, declaration, minister_name=minister)
    assert result.commissions.rejected == []
    rows = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "office"]
    assert len(rows) == 1
    assert json.loads(rows[0]["payload_json"]).get("mode", "ordinary") == (mode or "ordinary")


def test_scene_appointment_region_id_stages_same_seat(game):
    """地方任所只来自声明 region_id，不从官名推断。"""
    from ming_sim.audience_translate import normalize_audience_declaration
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    minister = "毕自严"
    declaration = normalize_audience_declaration({"commissions": [{
        "text": "着毕自严为陕西巡抚。",
        "appointment": {"name": minister, "office": "陕西巡抚",
                        "appoint_action": "任命", "region_id": "shaanxi"},
    }]})
    result = dispatch_declaration(db, state, declaration, minister_name=minister)
    assert result.commissions.rejected == []
    rows = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "office"]
    assert len(rows) == 1
    payload = json.loads(rows[0]["payload_json"])
    assert payload["region_id"] == "shaanxi"
    assert payload["name"] == minister
    assert payload["office"] == "陕西巡抚"


@pytest.mark.parametrize(
    ("appointee", "seed_modes", "continue_mode", "expected_id_relation", "expected_modes"),
    [
        # 沉默续拟：同一 id，保留 midzhi
        ("续拟沉默", ("midzhi",), None, "same", ("midzhi",)),
        # 显式 ordinary：同一 id，原地降级
        ("续拟降级", ("midzhi",), "ordinary", "same", ("ordinary",)),
        # 多命中：不 INSERT，原行不动（人名须 ≤20，session 截断）
        ("续拟双命中", ("ordinary", "midzhi"), "ordinary", "zero", ("ordinary", "midzhi")),
    ],
)
def test_propose_appointment_continue_draft_same_direction(
    game, appointee, seed_modes, continue_mode, expected_id_relation, expected_modes,
):
    """#1731 场景任免续拟：同向命中合并/多命中禁插。"""
    from ming_sim.audience_translate import normalize_audience_declaration
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    minister = "毕自严"
    appointee = minister
    office = "户部尚书"
    seed_ids = []
    for mode in seed_modes:
        seed_ids.append(db.stage_pending_action(
            state.turn, kind="office", action="任命",
            minister_name=minister, target_id=None,
            payload={"text": "测试任免原文",
                "name": appointee, "office": office,
                "appointer": minister, "mode": mode,
            },
        ))
    appointment = {"name": appointee, "office": office, "appoint_action": "任命"}
    if continue_mode is not None:
        appointment["mode"] = continue_mode
    declaration = normalize_audience_declaration({"commissions": [{
        "text": "着毕自严继续掌户部。", "appointment": appointment,
    }]})
    result = dispatch_declaration(db, state, declaration, minister_name=minister)
    continued_id = result.commissions.applied[0]["id"] if result.commissions.applied else 0
    rows = [
        {"id": int(p["id"]), "mode": json.loads(p["payload_json"]).get("mode")}
        for p in db.list_pending_actions(state.turn)
        if p["kind"] == "office"
        and json.loads(p["payload_json"]).get("name") == appointee
        and json.loads(p["payload_json"]).get("office") == office
    ]
    if expected_id_relation == "same":
        assert continued_id == seed_ids[0]
        assert rows == [{"id": seed_ids[0], "mode": expected_modes[0]}]
    else:
        assert continued_id == 0
        assert len(result.commissions.rejected) == 1
        assert [r["id"] for r in rows] == seed_ids
        assert [r["mode"] for r in rows] == list(expected_modes)


def test_scene_confirmation_ignores_retired_tool_outputs(game, monkeypatch, _offline_scene_beat_generator):
    """场景生成链不消费旧密令或拟旨工具；确认只处理夜内既有候选。"""
    from ming_sim.audience_night import open_night
    from tests.conftest import stub_scene_agent, stub_audience_translate, offline_empty_audience_translate
    from tests.test_scene_llm_1836 import _sess

    db, state, content = game
    minister = "毕自严"
    open_night(db, state)
    old_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister,
        target_id=None, payload={
            "covert_task": TYPED_COVERT_TASK, "title": "旧候选",
            "content": "旧候选内容", "assignee": minister,
            "tags": [], "deadline_months": 0,
        },
    )

    class SceneAgent:
        tools = []

        def run(self, message):
            return SimpleNamespace(content="臣遵旨。", tools=[
                SimpleNamespace(tool_name="secret_order", result="__secret_order__新令"),
                SimpleNamespace(tool_name="propose_directive", result="__pending_directive__新旨"),
            ])

    stub_scene_agent(monkeypatch, SceneAgent())
    stub_audience_translate(monkeypatch, lambda prompt, cfg: {
        **offline_empty_audience_translate(prompt, cfg),
        "promises": [{"action_id": old_id, "decision": "应允"}],
    })
    sess = _sess(db, state, content)
    sess.scene_chat("准")

    orders = db.list_secret_orders()
    assert len(orders) == 1 and orders[0]["title"] == "旧候选"
    assert db.list_pending_actions(state.turn) == []


def test_confirmation_commit_only_visible_pending_ids(game, monkeypatch):
    """同句新 stage 的动作即便同大臣同 kind，也不能被本句确认顺手提交。"""
    db, state, _content = game
    minister = "毕自严"
    oid = _create_secret_order(db, state, minister, "原标题", "原内容", [], deadline_months=0)
    old_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="更新", minister_name=minister, target_id=oid,
        payload={"new_title": "旧候选", "new_content": "旧候选内容", "deadline_months": 0},
    )
    new_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={
            "covert_task": TYPED_COVERT_TASK,"title": "同句新令", "content": "同句新令内容", "assignee": minister,
                 "tags": [], "deadline_months": 0},
    )
    monkeypatch.setattr(
        cb,
        "_run_json_extractor_for_config",
        lambda *a, **k: (json.dumps({"确认": "应允"}, ensure_ascii=False), 1),
    )

    GameSession.apply_cli_conversation_actions(
        _session(db, state, llm_config=SimpleNamespace(channel="api")),
        SimpleNamespace(name=minister, office_type="户部"),
        player_message="准了",
        answer="臣领旨。",
        has_directive=False,
        secret_order_id=None,
        confirm_target_ids={old_id},
    )

    row = db.conn.execute(
        "SELECT title, content FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()
    assert (row["title"], row["content"]) == ("旧候选", "旧候选内容")
    assert not db.conn.execute(
        "SELECT 1 FROM secret_orders WHERE title='同句新令'"
    ).fetchone()
    pending_ids = [p["id"] for p in db.list_pending_actions(state.turn)]
    assert pending_ids == [new_id]


def test_confirmation_reject_only_visible_pending_ids(game, monkeypatch):
    """拒绝确认也只能丢本轮开始前可见的 pending，不能删同句新 stage。"""
    db, state, _content = game
    minister = "毕自严"
    oid = _create_secret_order(db, state, minister, "原标题", "原内容", [], deadline_months=0)
    old_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="更新", minister_name=minister, target_id=oid,
        payload={"new_title": "旧候选", "new_content": "旧候选内容", "deadline_months": 0},
    )
    new_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={
            "covert_task": TYPED_COVERT_TASK,"title": "同句新令", "content": "同句新令内容", "assignee": minister,
                 "tags": [], "deadline_months": 0},
    )
    monkeypatch.setattr(
        cb,
        "_run_json_extractor_for_config",
        lambda *a, **k: (json.dumps({"确认": "拒绝"}, ensure_ascii=False), 1),
    )

    GameSession.apply_cli_conversation_actions(
        _session(db, state, llm_config=SimpleNamespace(channel="api")),
        SimpleNamespace(name=minister, office_type="户部"),
        player_message="作罢",
        answer="臣候旨。",
        has_directive=False,
        secret_order_id=None,
        confirm_target_ids={old_id},
    )

    assert db.conn.execute(
        "SELECT title, content FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()["title"] == "原标题"
    assert not db.conn.execute(
        "SELECT 1 FROM pending_actions WHERE id=? AND status='pending'", (old_id,)
    ).fetchone()
    pending_ids = [p["id"] for p in db.list_pending_actions(state.turn)]
    assert pending_ids == [new_id]


def test_secret_order_extract_fallback_preserves_structured_metadata(monkeypatch):
    """API/按钮兼容文本带出的标签/期限，在 extractor 空结果时也不能丢。"""
    monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: ("{}", 1))
    tags = ["辽饷", "关宁"]
    deadline = 3

    out = cb._extract_secret_order(
        f"密令如下：暗查辽饷侵冒。\n标签：{', '.join(tags)}\n期限：{deadline}月",
        "臣领旨。",
        "魏忠贤",
        llm_config=SimpleNamespace(channel="cli"),
    )

    assert out["tags"] == tags
    assert out["deadline_months"] == deadline

    negative = cb._extract_secret_order(
        "密令如下：暗查辽饷侵冒。\n期限：-5月",
        "臣领旨。",
        "魏忠贤",
        llm_config=SimpleNamespace(channel="cli"),
    )
    assert negative["deadline_months"] == 0


def test_secret_order_extract_keeps_explicit_zero_deadline(monkeypatch):
    """LLM 明确给 0 月时，不被御旨里的 fallback 期限覆盖。"""
    explicit_zero = 0
    monkeypatch.setattr(
        cb,
        "_run_backend_for_config",
        lambda *a, **k: (json.dumps({
            "标题": "暗查辽饷",
            "内容": "暗查辽饷侵冒。",
            "承办人": "魏忠贤",
            "期限月数": explicit_zero,
            "差务": "清丈",
            "价值轴": ["实务事功"],
            "方向": 1,
            "交付单位": "万亩",
            "交付目标": 1, "效果符号": 1, "地区": "henan", "地区字段": "registered_land", "地区目标值": "421",
            "标签": [],
        }, ensure_ascii=False), 1),
    )

    out = cb._extract_secret_order(
        "密令如下：暗查辽饷侵冒。\n期限：3月",
        "臣领旨。",
        "魏忠贤",
        llm_config=SimpleNamespace(channel="cli"),
    )

    assert out["deadline_months"] == explicit_zero


@pytest.mark.parametrize("use_alias", [False, True])
def test_declared_noop_appointment_is_not_staged(game, use_alias):
    """结构化任免使用同一 canonical 目标与已在职判断，不重复立案。"""
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    target = next(
        ch for ch in content.characters.values()
        if getattr(ch, "power_id", "ming") == "ming"
        and getattr(ch, "office", "")
        and getattr(ch, "office_type", "") != "后宫"
        and (not use_alias or any(a != ch.name for a in (ch.aliases or [])))
        and db.get_character_status(ch.name)[0] == "active"
    )
    name = next(a for a in target.aliases if a != target.name) if use_alias else target.name
    result = dispatch_declaration(db, state, {"commissions": [{
        "text": "核对现任官职", "appointment": {
            "appoint_action": "任命", "name": name, "office": target.office,
        },
    }]}, minister_name="毕自严")
    assert result.commissions.applied == []
    assert result.commissions.rejected == []
    assert db.list_pending_actions(state.turn) == []


def _link_night_chat_turn(db, state, night_id, minister, user_text, minister_text):
    """在指定夜为大臣落一条完成态对话轮（user+minister 消息已 link），供按夜取回测。"""
    tid = db.create_chat_turn(
        state, minister, agno_session_id="", agno_runs_before=0, night_id=int(night_id))
    uid = db.append_chat_message(minister, state.turn, "user", user_text)
    mid = db.append_chat_message(minister, state.turn, "minister", minister_text)
    db.update_chat_turn_messages(tid, user_message_id=uid, minister_message_id=mid)
    return tid


def test_secret_context_feed_isolates_by_open_night(game):
    """#504 AC2「按夜取回」：同回合多夜时，密令喂料只取当前开着的夜——上一夜（已收）
    的密谋正文不得串进本夜的按钮确认喂料（接缝④·multi-night isolation #498）。"""
    import ming_sim.audience_night as an
    db, state, _ = game
    minister = "魏忠贤"
    night1_mark, night2_mark = "MARK_NIGHT1_密谋", "MARK_NIGHT2_军饷"

    # 第一夜：一段密谋，随后收夜
    n1 = an.open_night(db, state)["id"]
    _link_night_chat_turn(
        db, state, n1, minister,
        f"命东厂暗查阉党第一夜密谋 {night1_mark}。", "臣领密旨，第一夜遵办。")
    db.conn.execute(
        "UPDATE audience_nights SET status='closed' WHERE id=?", (int(n1),))
    db.conn.commit()

    # 第二夜：另起一段任务，按钮确认取喂料
    n2 = an.open_night(db, state)["id"]
    _link_night_chat_turn(
        db, state, n2, minister,
        f"命李若琏第二夜暗查关宁军饷 {night2_mark}。", "臣领命，第二夜遵办。")

    ctx = session_mod._recent_audience_context_for_secret_order(
        db, minister, int(state.turn), "密令如下：可，照办")

    assert night2_mark in ctx  # 本夜正文取到
    assert night1_mark not in ctx  # 上一夜正文不串入


def test_committed_draft_followup_merges_even_when_classifier_says_none(game, monkeypatch):
    """#344 US6 +integrated cmr Gate2 codex correctness：已有 committed draft 时，并发分类器只读
    皇帝本条消息、看不到 committed draft，可能把「再补一条…随行」误判 none——此时仍须回退
    extract_draft_intent 合并，不得静默丢掉草案补充。无草案的普通消息仍零额外 LLM。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' ORDER BY name LIMIT 1"
    ).fetchone()[0]
    db.add_directive(
        state, None, "着户部清核辽饷。", "大臣拟旨",
        actor=minister, notes="原草案", status="draft",
        dossier_payload={
            "dossier_action_type": "special_decree", "target_kind": "policy",
            "target_id": "liao-pay-audit",
        })
    merged_text = "着户部清核辽饷，并加派监察御史随行。"
    called = []

    def fake_draft(player_message, reply, **kwargs):
        called.append(kwargs.get("existing_draft_text"))
        return {
            "draft_action": "拟旨", "draft_text": merged_text,
        }

    monkeypatch.setattr(cb, "extract_draft_intent", fake_draft)
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": ""})
    monkeypatch.setattr(cb, "extract_appointment_action", lambda *a, **k: {
        "appoint_action": "无", "name": "", "office": ""})

    _session(db, state, llm_config=SimpleNamespace(channel="cli")).apply_cli_conversation_actions(
        SimpleNamespace(name=minister, office_type="兵部"),
        "再补一条，加派监察御史随行。", "臣遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "none"},
    )

    # 分类器判 none 也回退到 draft 合并（旧草案文本被喂给合并器，不丢补充）
    assert called and called[0] == "着户部清核辽饷。"
    row = db.conn.execute(
        "SELECT text FROM turn_directives WHERE actor=? AND status='draft'", (minister,)
    ).fetchone()
    assert row["text"] == merged_text


def test_committed_draft_followup_merges_even_when_classifier_says_draft(game, monkeypatch):
    """同上的孪生面（integrated cmr Gate2 r3 codex correctness）：分类器判 'draft' + 已有草案时，
    也必须 merge、不得用 raw reply 覆盖已有草案——none 半与 draft 半是同一覆盖丢失的两面，统一
    收敛到 extract_draft_intent 合并。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' ORDER BY name LIMIT 1 OFFSET 1"
    ).fetchone()[0]
    db.add_directive(
        state, None, "着户部清核辽饷。", "大臣拟旨",
        actor=minister, notes="原草案", status="draft",
        dossier_payload={
            "dossier_action_type": "special_decree", "target_kind": "policy",
            "target_id": "liao-pay-audit",
        })
    merged_text = "着户部清核辽饷，并加派监察御史随行。"
    fed_existing = []

    def fake_draft(player_message, reply, **kwargs):
        fed_existing.append(kwargs.get("existing_draft_text"))
        return {
            "draft_action": "拟旨", "draft_text": merged_text,
        }

    monkeypatch.setattr(cb, "extract_draft_intent", fake_draft)
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": ""})
    monkeypatch.setattr(cb, "extract_appointment_action", lambda *a, **k: {
        "appoint_action": "无", "name": "", "office": ""})

    _session(db, state, llm_config=SimpleNamespace(channel="cli")).apply_cli_conversation_actions(
        SimpleNamespace(name=minister, office_type="兵部"),
        "再拟一道旨，加派监察御史随行。", "臣谨拟：着户部清核辽饷，并加派监察御史随行。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "draft", "draft_text": ""},
    )

    # intent=='draft' + 已有草案 → 仍走合并（喂旧草案），不被 raw reply 覆盖
    assert fed_existing and fed_existing[0] == "着户部清核辽饷。"
    row = db.conn.execute(
        "SELECT text FROM turn_directives WHERE actor=? AND status='draft'", (minister,)
    ).fetchone()
    assert row["text"] == merged_text


def test_begin_turn_syncs_offices_with_runtime_llm_config(monkeypatch):
    seen = []
    cfg = SimpleNamespace(channel="api")
    state = SimpleNamespace(turn_phase="summoning")
    fake_db = SimpleNamespace(
        load_state=lambda: state,
        apply_historical_deaths=lambda state: [],
        apply_historical_debuts=lambda state: [],
        apply_historical_power_renames=lambda state: [],
        previous_turn_summary=lambda state: "",
        save_state=lambda state: None,
    )
    fake = SimpleNamespace(
        state=state,
        db=fake_db,
        content=SimpleNamespace(characters={}),
        llm_config=cfg,
        agno_db=SimpleNamespace(),
        previous_summary="",
        last_decree="",
        last_report="",
        _begun=False,
        auto_save=lambda label: None,
        turn_snapshot=lambda: SimpleNamespace(ok=True),
    )
    monkeypatch.setattr(session_mod, "_sync_offices_from_db_impl",
                        lambda content, db, llm_config=None: seen.append(llm_config))

    GameSession.begin_turn(fake)

    assert seen == [cfg]


def test_chat_rollback_refresh_syncs_offices_with_runtime_llm_config(monkeypatch):
    seen = []
    cfg = SimpleNamespace(channel="api")
    state = SimpleNamespace(turn_phase="summoning")
    fake_db = SimpleNamespace(load_state=lambda: state)
    fake = SimpleNamespace(
        state=state,
        db=fake_db,
        content=SimpleNamespace(characters={}),
        llm_config=cfg,
        agno_db=SimpleNamespace(),
        previous_summary="",
    )
    monkeypatch.setattr(session_mod, "_sync_offices_from_db_impl",
                        lambda content, db, llm_config=None: seen.append(llm_config))

    GameSession.refresh_runtime_after_chat_rollback(fake)

    assert seen == [cfg]


# ── codexC-1：会话动作（非前缀）必须经 session 路径落地，不再只在 web 有 ──

def test_conversation_update_lands_via_session_path(game, monkeypatch):
    """无前缀、口头说『更新密令』→ session 路径(apply_cli_conversation_actions)把更新进 pending 暂存,
    颁诏 commit 才落真实表(ADR 0006 动作闸门);召对当场不直写、不丢动作。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    who = "会话动作承办官"
    oid = _create_secret_order(db, state, who, "原标题", "原内容", ["甲"], deadline_months=0)
    # LLM 判意图：更新该密令（不走真 backend，直接喂结构化动作）
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "更新", "order_id": oid, "new_title": "改后标题",
        "new_content": "改后内容", "deadline_months": 0,
        "cultivate_skill": "", "cultivate_trait": ""})
    s = _session(db, state, registry=SimpleNamespace(refresh=lambda n: None))
    # 非 classifier 契约：preclassified_intent 跳过 serial classify，禁真 subprocess。
    res = s.apply_cli_conversation_actions(
        SimpleNamespace(name=who, office_type="兵部"),
        "你那道密令改一下，内容换成……", "臣领旨，已记改。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={
            "kind": "secret", "secret_action": "更新", "order_id": oid,
            "new_title": "改后标题", "new_content": "改后内容", "deadline_months": 0,
            "cultivate_skill": "", "cultivate_trait": "",
        },
    )
    # 召对当场：进暂存、不报"已交付"、真实表不动
    assert res["secret_order_id"] is None
    assert res.get("pending_action_id")
    assert db.conn.execute(
        "SELECT content FROM secret_orders WHERE id=?", (oid,)).fetchone()["content"] == "原内容"
    # 颁诏 commit 才落库
    db.commit_pending_actions(state)
    assert db.conn.execute(
        "SELECT content FROM secret_orders WHERE id=?", (oid,)).fetchone()["content"] == "改后内容"


@pytest.mark.parametrize("action, payload_key", [("提交核议", "claim"), ("记进展", "note")])
def test_secret_conversation_actions_persist_complete_minister_reply(
    game, monkeypatch, action, payload_key,
):
    db, state, _content = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    who = "长回话承办官"
    oid = _create_secret_order(db, state, who, "查核边饷", "逐项查核", [])
    if action == "记进展":
        db.conn.execute("UPDATE secret_orders SET turn_issued=? WHERE id=?", (state.turn - 1, oid))
        db.conn.commit()
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": action, "order_id": oid, "new_title": "",
        "new_content": "", "deadline_months": 0,
        "cultivate_skill": "", "cultivate_trait": "",
    })
    reply = "臣已逐册查核。" + "甲乙丙丁戊己庚辛壬癸" * 30 + "末尾凭据完整。"
    session = _session(db, state, registry=SimpleNamespace(refresh=lambda _name: None))

    # 非 classifier 契约：显式 candidate，避免 agy serial classify 真 subprocess。
    result = session.apply_cli_conversation_actions(
        SimpleNamespace(name=who, office_type="兵部"), action, reply,
        has_directive=False, secret_order_id=None,
        preclassified_intent={
            "kind": "secret", "secret_action": action, "order_id": oid,
            "new_title": "", "new_content": "", "deadline_months": 0,
            "cultivate_skill": "", "cultivate_trait": "",
        },
    )

    row = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (result["pending_action_id"],)
    ).fetchone()
    assert json.loads(row["payload_json"])[payload_key] == reply


def test_preclassified_secret_update_uses_reply_aware_extractor(game, monkeypatch):
    """#354/#397 cmr r13: 并发分类器只读皇帝话，secret 更新字段须等大臣回话后重抽，不能丢补充。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    who = "并发更新承办官"
    oid = _create_secret_order(db, state, who, "原标题", "原内容", [], deadline_months=0)

    def reply_aware_extract(player_message, reply, active, llm_config=None):
        assert "臣补充" in reply
        return {
            "secret_action": "更新",
            "order_id": oid,
            "new_title": "改后标题",
            "new_content": "皇帝增量；臣补充执行细则",
            "deadline_months": 0,
            "cultivate_skill": "",
            "cultivate_trait": "",
        }

    monkeypatch.setattr(cb, "extract_minister_actions", reply_aware_extract)
    s = _session(db, state, registry=SimpleNamespace(refresh=lambda n: None),
                 llm_config=SimpleNamespace(channel="cli", cli_runner="codex"))
    res = s.apply_cli_conversation_actions(
        SimpleNamespace(name=who, office_type="兵部"),
        "更新那道密令，补一条皇帝增量。",
        "臣补充执行细则。",
        has_directive=False,
        secret_order_id=None,
        preclassified_intent={
            "kind": "secret",
            "secret_action": "更新",
            "order_id": oid,
            "new_title": "预判标题",
            "new_content": "皇帝增量",
            "deadline_months": 0,
            "cultivate_skill": "",
            "cultivate_trait": "",
        },
    )

    assert res.get("pending_action_id")
    row = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (res["pending_action_id"],),
    ).fetchone()
    payload = json.loads(row["payload_json"])
    assert payload["new_content"] == "皇帝增量；臣补充执行细则"


def test_runtime_cli_conversation_update_uses_configured_runner_without_env(game, monkeypatch):
    """无前缀会话动作的 LLM 判定也必须按 runtime CLI 配置分派。"""
    db, state, _ = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    who = "配置通道承办官"
    oid = _create_secret_order(db, state, who, "原标题", "原内容", [], deadline_months=0)
    calls = []
    canned = json.dumps({
        "密令动作": "更新",
        "目标密令编号": oid,
        "新标题": "改后标题",
        "新内容": "改后内容",
        "期限月数": 0,
    }, ensure_ascii=False)

    def fake_codex(prompt, model=None, **kwargs):
        calls.append(("codex", model))
        return canned, 1

    monkeypatch.setattr(cb, "_run_codex", fake_codex)
    s = _session(
        db,
        state,
        llm_config=SimpleNamespace(
            channel="cli", cli_runner="codex", cli_model="gpt-5.5", cli_timeout_seconds=240,
        ),
    )

    res = s.apply_cli_conversation_actions(
        SimpleNamespace(name=who, office_type="兵部"),
        "你那道密令改一下，内容换成……",
        "臣领旨，已记改。",
        has_directive=False,
        secret_order_id=None,
    )

    # 会话动作判定按配置 runner 分派，且密令动作命中后不再串行跑任免抽取。
    assert calls == [("codex", "gpt-5.5")]
    # 动作闸门：暂存,颁诏 commit 才落库(不在召对当场直写)
    assert res["secret_order_id"] is None
    assert res.get("pending_action_id")
    assert db.conn.execute(
        "SELECT content FROM secret_orders WHERE id=?", (oid,)).fetchone()["content"] == "原内容"
    db.commit_pending_actions(state)
    assert db.conn.execute(
        "SELECT content FROM secret_orders WHERE id=?", (oid,)).fetchone()["content"] == "改后内容"


def test_conversation_rush_skips_non_active(game, monkeypatch):
    """催办目标恰为非 active 时不抛错、不误置成功（target_active 守门）。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    who = "待核承办官"
    oid = _create_secret_order(db, state, who, "已结令", "内容", [], deadline_months=6)
    db.conn.execute("UPDATE secret_orders SET status='failed' WHERE id=?", (oid,))
    db.conn.commit()
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "催办", "order_id": oid, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": ""})
    s = _session(db, state, registry=None)
    # 非 classifier 契约：显式 candidate，禁止 serial classify → 真 subprocess。
    res = s.apply_cli_conversation_actions(
        SimpleNamespace(name=who, office_type="兵部"),
        "那事催一下", "臣加紧。", has_directive=False, secret_order_id=None,
        preclassified_intent={
            "kind": "secret", "secret_action": "催办", "order_id": oid,
            "new_title": "", "new_content": "", "deadline_months": 0,
            "cultivate_skill": "", "cultivate_trait": "",
        },
    )
    assert res["secret_order_id"] is None        # 非 active 不被催办，不抛错
    row = db.conn.execute("SELECT status FROM secret_orders WHERE id=?", (oid,)).fetchone()
    assert row["status"] == "failed"     # 状态未被动
