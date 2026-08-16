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
from tests.dossier_test_helpers import promulgate_proposed_appointments


def _result():
    return SimpleNamespace(answer="", proposed_directive=None, secret_order_id=None, pending_action_id=0)


def test_non_streaming_path_surfaces_pending_action_id(game, monkeypatch):
    """非流式 session 路径(_cli_backend_fallback_actions)也要 surface pending_action_id,
    与流式不漂移(ship-pre CMR);暂存不当场落 secret_order_id。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    who = "非流式承办官"
    oid = db.create_secret_order(state, who, "原标题", "原内容", [], deadline_months=0)
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


def _commit_staged_secret_order(db, state, result_or_mapping):
    """#413: prefix/button secret-order paths stage first; commit here only when a test inspects the durable row."""
    if isinstance(result_or_mapping, dict):
        assert result_or_mapping.get("secret_order_id") in (None, 0)
        pending_id = result_or_mapping.get("pending_action_id")
    else:
        assert getattr(result_or_mapping, "secret_order_id", None) in (None, 0)
        pending_id = getattr(result_or_mapping, "pending_action_id", 0)
    assert pending_id
    db.commit_pending_actions(state)
    orders = db.list_secret_orders()
    assert len(orders) == 1
    return orders[0]


def test_draft_prefix_with_active_secret_order_runs_zero_llm(game, monkeypatch):
    """#344「按钮前缀路零 LLM」(US3)：玩家用『拟旨如下：』前缀、且该大臣有 active 密令时，
    旧的会话密令抽取器(extract_minister_actions, LLM)不得被触发——前缀已由 resolve_minister_actions
    零 LLM 落拟旨。整合 cmr r2/r3 codex 完整性腿抓出：原实现 secret 块未按 explicit_prefixed 把门，
    于是前缀消息在有 active 密令时仍多跑一次 LLM extractor。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    who = "前缀零LLM承办官"
    db.create_secret_order(state, who, "原密令", "查某亏空", [], deadline_months=0)

    def _forbidden(*a, **k):
        raise AssertionError("前缀拟旨不应触发任何后置 LLM 抽取器")

    monkeypatch.setattr(cb, "extract_minister_actions", _forbidden)
    monkeypatch.setattr(cb, "extract_draft_intent", _forbidden)
    monkeypatch.setattr(cb, "extract_appointment_action", _forbidden)
    monkeypatch.setattr(cb, "extract_confirmation_intent", _forbidden)

    result = _result()
    result.answer = "臣遵旨，当即清核辽饷。"
    _session(db, state, llm_config=SimpleNamespace(channel="cli"))._cli_backend_fallback_actions(
        result, SimpleNamespace(name=who, office_type="兵部"),
        "拟旨如下：着户部清核辽饷。")

    # 前缀拟旨零 LLM 暂存：不直写 turn_directives，仍无 secret 误触发
    assert result.proposed_directive is None
    assert result.pending_action_id
    pending = db.list_pending_actions(state.turn)
    assert len(pending) == 1 and pending[0]["kind"] == "directive"
    assert json.loads(pending[0]["payload_json"])["text"] == "臣遵旨，当即清核辽饷。"
    assert result.secret_order_id is None


def test_staged_action_reply_gets_confirmation_cue(game, monkeypatch):
    """#412/#413 completeness: staged chat actions must visibly ask the emperor to approve/reject."""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    who = "确认提示承办官"

    def _forbidden(*a, **k):
        raise AssertionError("显式拟旨前缀不应触发后置 LLM 抽取器")

    monkeypatch.setattr(cb, "extract_minister_actions", _forbidden)
    monkeypatch.setattr(cb, "extract_draft_intent", _forbidden)
    monkeypatch.setattr(cb, "extract_appointment_action", _forbidden)
    monkeypatch.setattr(cb, "extract_confirmation_intent", _forbidden)

    result = _result()
    result.answer = "奉天承运皇帝诏曰，着户部清核辽饷。"
    _session(db, state, llm_config=SimpleNamespace(channel="cli"))._cli_backend_fallback_actions(
        result, SimpleNamespace(name=who, office_type="兵部"),
        "拟旨如下：着户部清核辽饷。")

    assert result.pending_action_id
    assert "请陛下定夺准驳" in result.answer


def test_tool_call_pending_directive_reply_gets_confirmation_cue(read_game):
    """#412: agno/tool-call staged directives also need the visible approval cue."""
    db, state, _ = read_game
    result = _result()
    result.pending_action_id = 42
    result.answer = "臣领旨。"

    _session(db, state, llm_config=SimpleNamespace(channel="api"))._cli_backend_fallback_actions(
        result, SimpleNamespace(name="工具拟旨承办官", office_type="户部"),
        "请拟旨发银赈陕西。")

    assert result.pending_action_id == 42
    assert "请陛下定夺准驳" in result.answer


def test_tool_call_pending_secret_order_reply_gets_confirmation_cue(read_game):
    """#413: agno/tool-call staged secret orders also need the visible approval cue."""
    db, state, _ = read_game
    result = _result()
    result.pending_action_id = 43
    result.answer = "臣领密旨。"

    _session(db, state, llm_config=SimpleNamespace(channel="api"))._cli_backend_fallback_actions(
        result, SimpleNamespace(name="工具密令承办官", office_type="司礼监"),
        "密查辽饷侵冒。")

    assert result.pending_action_id == 43
    assert "请陛下定夺准驳" in result.answer


def test_generic_please_your_majesty_does_not_suppress_confirmation_cue():
    answer = GameSession._ensure_confirmation_cue("臣已拟妥，请陛下放心。")

    assert "请陛下定夺准驳" in answer


def test_tool_call_staged_new_secret_order_merges_minister_reply(game, monkeypatch):
    """#413/#405：tool-call 已暂存的新密令仍要把玩家任务和大臣补充并入正文真源。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "工具密令承办官"
    pid = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={
            "title": "暗查辽饷",
            "content": "暗查辽饷侵冒。",
            "assignee": minister,
            "tags": ["辽饷"],
            "deadline_months": 3,
        },
    )

    result = _result()
    result.pending_action_id = pid
    result.answer = "臣当先封存兵部辽饷册，再密访关宁诸将。"

    _session(db, state, llm_config=SimpleNamespace(channel="api"))._cli_backend_fallback_actions(
        result,
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：暗查辽饷侵冒，三月内回奏，不可声张。",
    )

    pending = db.list_pending_actions(state.turn)
    assert len(pending) == 1 and pending[0]["id"] == pid
    payload = json.loads(pending[0]["payload_json"])
    assert "暗查辽饷侵冒" in payload["content"]
    assert "三月内回奏" in payload["content"]
    assert "不可声张" in payload["content"]
    assert "封存兵部辽饷册" in payload["content"]


def test_tool_call_staged_secret_order_merge_updates_reply_assignee(game, monkeypatch):
    """tool-call 新密令也要从大臣补充里回填承办人。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "工具密令承办官"
    pid = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={
            "title": "暗查辽饷",
            "content": "暗查辽饷侵冒。",
            "assignee": minister,
            "tags": [],
        },
    )

    result = _result()
    result.pending_action_id = pid
    result.answer = "臣请委李若琏负责密访关宁诸将。"

    _session(db, state, llm_config=SimpleNamespace(channel="api"))._cli_backend_fallback_actions(
        result,
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：暗查辽饷侵冒。",
    )

    payload = json.loads(db.list_pending_actions(state.turn)[0]["payload_json"])
    assert payload["assignee"] == "李若琏"


def test_staged_secret_order_assignee_merge_uses_llm_field_contract(game, monkeypatch):
    """_choose_assignee 的首参是已暂存的 LLM assignee 字段，不是 llm_config。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "工具密令承办官"
    pid = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={
            "title": "暗查辽饷",
            "content": "暗查辽饷侵冒。",
            "assignee": "王在晋",
            "tags": [],
        },
    )
    seen = {}

    def fake_choose_assignee(assignee_llm, player_command, minister_reply, content, default_assignee):
        seen.update({
            "assignee_llm": assignee_llm,
            "player_command": player_command,
            "minister_reply": minister_reply,
            "content": content,
            "default_assignee": default_assignee,
        })
        return "李若琏"

    monkeypatch.setattr(cb, "_choose_assignee", fake_choose_assignee)
    result = _result()
    result.pending_action_id = pid
    result.answer = "臣请委李若琏负责密访关宁诸将。"

    _session(db, state, llm_config=SimpleNamespace(channel="api"))._cli_backend_fallback_actions(
        result,
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：暗查辽饷侵冒。",
    )

    assert seen["assignee_llm"] == "王在晋"
    assert seen["player_command"] == "暗查辽饷侵冒。"
    assert seen["minister_reply"] == "臣请委李若琏负责密访关宁诸将。"
    assert "暗查辽饷侵冒" in seen["content"]
    assert seen["default_assignee"] == minister
    payload = json.loads(db.list_pending_actions(state.turn)[0]["payload_json"])
    assert payload["assignee"] == "李若琏"


def test_tool_call_staged_new_secret_order_merges_missing_metadata(game, monkeypatch):
    """tool 已暂存但漏掉可选字段时，从按钮/前缀文本回填标签与期限。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "工具密令元数据承办官"
    pid = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={
            "title": "暗查辽饷",
            "content": "暗查辽饷侵冒。",
            "assignee": minister,
            "tags": [],
        },
    )

    result = _result()
    result.pending_action_id = pid
    result.answer = "臣领旨。"

    _session(db, state, llm_config=SimpleNamespace(channel="api"))._cli_backend_fallback_actions(
        result,
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：暗查辽饷侵冒。\n标签：辽饷, 关宁\n期限：3月",
    )

    payload = json.loads(db.list_pending_actions(state.turn)[0]["payload_json"])
    assert payload["tags"] == ["辽饷", "关宁"]
    assert payload["deadline_months"] == 3


def test_tool_call_staged_new_secret_order_keeps_explicit_zero_deadline(game, monkeypatch):
    """tool 已明确 deadline_months=0 时，不被按钮/前缀文本里的期限回填覆盖。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "工具密令零期限承办官"
    pid = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={
            "title": "暗查辽饷",
            "content": "暗查辽饷侵冒。",
            "assignee": minister,
            "tags": [],
            "deadline_months": 0,
        },
    )

    result = _result()
    result.pending_action_id = pid
    result.answer = "臣领旨。"

    _session(db, state, llm_config=SimpleNamespace(channel="api"))._cli_backend_fallback_actions(
        result,
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：暗查辽饷侵冒。\n期限：3月",
    )

    payload = json.loads(db.list_pending_actions(state.turn)[0]["payload_json"])
    assert payload["deadline_months"] == 0


def test_secret_order_tool_progress_stages_pending_action_not_direct_write(game):
    """function-call 密令进展工具也要过 pending 确认闸门，不得直接改真实表。"""
    db, state, content = game
    minister = "毕自严"
    oid = db.create_secret_order(state, minister, "查辽饷", "查辽饷侵冒。", [], deadline_months=0)
    db.conn.execute("UPDATE secret_orders SET turn_issued=? WHERE id=?", (state.turn - 1, oid))
    db.conn.commit()

    tool_payload = json.dumps({
        "action": "记进展",
        "order_id": oid,
        "payload": {"note": "已封存兵部辽饷册。"},
    }, ensure_ascii=False)

    class Agent:
        def run(self, _message):
            return SimpleNamespace(
                content="臣已记下进展，请陛下定夺。",
                tools=[SimpleNamespace(tool_name="secret_order", result=f"__secret_action__{tool_payload}")],
            )

    class Registry:
        def get(self, _character):
            return Agent()

        def build_draft_line(self):
            return "无"

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = Registry()
    sess.llm_config = SimpleNamespace(channel="api")
    sess.temporary_characters = set()
    sess._audience_prompt_for_message = lambda message: message
    sess._start_cli_action_intent = lambda *_args, **_kwargs: None
    sess._finish_cli_action_intent = lambda *_args, **_kwargs: None

    result = GameSession.chat(sess, minister, "奏报密令进展。")

    assert result.pending_action_id
    assert "已封存兵部辽饷册" not in (
        db.conn.execute("SELECT result FROM secret_orders WHERE id=?", (oid,)).fetchone()["result"] or ""
    )
    pending = db.list_pending_actions(state.turn)
    assert len(pending) == 1
    assert pending[0]["action"] == "记进展"


def test_chat_prompt_builder_internal_typeerror_is_not_retried_without_turn_scope(game):
    """真实 builder 的 TypeError 不能被误判为旧签名兼容而改走无 turn 的调用。"""
    _db, _state, content = game
    minister = "毕自严"
    calls = []
    sess = GameSession.__new__(GameSession)
    sess.content = content
    sess.registry = SimpleNamespace(get=lambda _character: object())
    sess.temporary_characters = set()

    def prompt_builder(message, character, *, chat_turn_id=0):
        calls.append((message, character.name, chat_turn_id))
        raise TypeError("production prompt failure")

    sess._audience_prompt_for_message = prompt_builder

    with pytest.raises(TypeError, match="^production prompt failure$"):
        GameSession.chat(sess, minister, "请奏", chat_turn_id=7)
    assert calls == [("请奏", minister, 7)]


def test_propose_directive_tool_arguments_stages_draft(game):
    """session 路 tool 参数兼容 arguments/tool_args，避免丢 Agno/Phidata decree_text。"""
    db, state, content = game
    minister = "毕自严"

    class Agent:
        def run(self, _message):
            return SimpleNamespace(
                content="臣已拟旨，请陛下定夺。",
                tools=[SimpleNamespace(
                    tool_name="propose_directive",
                    result="",
                    arguments={"decree_text": "着户部清核辽饷。"},
                )],
            )

    class Registry:
        def get(self, _character):
            return Agent()

        def build_draft_line(self):
            return "无"

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = Registry()
    sess.llm_config = SimpleNamespace(channel="api")
    sess.temporary_characters = set()
    sess._audience_prompt_for_message = lambda message: message
    sess._start_cli_action_intent = lambda *_args, **_kwargs: None
    sess._finish_cli_action_intent = lambda *_args, **_kwargs: None

    result = GameSession.chat(sess, minister, "中旨直发，拟一道清查辽饷的旨。")

    assert result.pending_action_id
    pending = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "directive"]
    assert len(pending) == 1
    pending_payload = json.loads(pending[0]["payload_json"])
    assert pending_payload["text"] == "着户部清核辽饷。"
    assert pending_payload["mode"] == "midzhi"

    db.commit_pending_actions(state, kind_filter="directive")
    db.ensure_dossiers_for_draft_directives(state)
    dossiers = db.list_decree_dossiers()
    assert len(dossiers) == 1
    assert dossiers[0]["mode"] == "midzhi"


def test_api_channel_rejects_existing_pending_action(game):
    """API/function-call 通道已暂存动作后，下一句拒绝也必须删除 pending，不能早退默认同意。"""
    db, state, _ = game
    minister = "魏忠贤"
    db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={
            "title": "暗查辽饷",
            "content": "暗查辽饷侵冒。",
            "assignee": minister,
            "tags": [],
            "deadline_months": 0,
        },
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

    def _semantic_confirmation(prompt, llm_config=None, tag=""):
        calls.append((prompt, tag))
        return (json.dumps({"确认": "应允"}, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_json_extractor_for_config", _semantic_confirmation)

    result = cb.extract_confirmation_intent(
        player_message="不必多言，准了。",
        minister_reply="臣候旨。",
        pending_summaries=["新建密令：暗查辽饷"],
        llm_config=SimpleNamespace(channel="api"),
    )

    assert result == "应允"
    assert calls and calls[0][1] == "confirmation"


def test_confirmation_negated_hold_over_uses_semantic_extractor(monkeypatch):
    """#525：「不必留中，准了」含「留中」字面，不得字面快路径误判留中。"""
    calls = []

    def _semantic_confirmation(prompt, llm_config=None, tag=""):
        calls.append((prompt, tag))
        return (json.dumps({"确认": "应允"}, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_json_extractor_for_config", _semantic_confirmation)

    result = cb.extract_confirmation_intent(
        player_message="不必留中，准了。",
        minister_reply="臣候旨。",
        pending_summaries=["草拟圣旨：清核辽饷"],
        llm_config=SimpleNamespace(channel="api"),
    )

    assert result == "应允"
    assert calls and calls[0][1] == "confirmation"


def test_confirmation_explicit_hold_over_uses_semantic_extractor(monkeypatch):
    """#525：显式「留中不发」走既有 typed 抽取，不得依赖字面快路径。"""
    calls = []

    def _semantic_confirmation(prompt, llm_config=None, tag=""):
        calls.append((prompt, tag))
        return (json.dumps({"确认": "留中"}, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_json_extractor_for_config", _semantic_confirmation)

    result = cb.extract_confirmation_intent(
        player_message="留中不发。",
        minister_reply="臣候旨。",
        pending_summaries=["草拟圣旨：清核辽饷"],
        llm_config=SimpleNamespace(channel="api"),
    )

    assert result == "留中"
    assert calls and calls[0][1] == "confirmation"


def test_confirmation_question_with_approval_words_uses_semantic_extractor(monkeypatch):
    """“若准奏会如何？”只是追问后果，不能因含“准奏”走快路提交 pending。"""
    calls = []

    def _semantic_confirmation(prompt, llm_config=None, tag=""):
        calls.append((prompt, tag))
        return (json.dumps({"确认": "无"}, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_json_extractor_for_config", _semantic_confirmation)

    result = cb.extract_confirmation_intent(
        player_message="若准奏会如何？",
        minister_reply="臣候旨。",
        pending_summaries=["草拟圣旨：清核辽饷"],
        llm_config=SimpleNamespace(channel="api"),
    )

    assert result == "无"
    assert calls and calls[0][1] == "confirmation"


def test_confirmation_negated_approval_phrase_is_rejection():
    """“不可照办”不能因包含“照办”走快路误判应允。"""
    result = cb.extract_confirmation_intent(
        player_message="不可照办。",
        minister_reply="臣候旨。",
        pending_summaries=["新建密令：暗查辽饷"],
        llm_config=SimpleNamespace(channel="api"),
    )

    assert result == "拒绝"


def test_confirmation_soft_negated_approval_phrase_is_rejection():
    """“先别照办”也是否定确认，不能因包含“照办”走快路误判应允。"""
    result = cb.extract_confirmation_intent(
        player_message="先别照办。",
        minister_reply="臣候旨。",
        pending_summaries=["新建密令：暗查辽饷"],
        llm_config=SimpleNamespace(channel="api"),
    )

    assert result == "拒绝"


def test_confirmation_negated_approval_rejects_when_extractor_fails(monkeypatch):
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

    assert result == "拒绝"


def test_confirmation_bubi_zhaoban_rejects_when_extractor_fails(monkeypatch):
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

    assert result == "拒绝"


def test_mixed_directive_and_secret_confirmation_commits_both(game):
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
            "title": "暗查辽饷",
            "content": "暗查辽饷侵冒。",
            "assignee": minister,
            "tags": [],
            "deadline_months": 0,
        },
    )

    out = GameSession.apply_cli_conversation_actions(
        _session(db, state, content=content),
        ch,
        player_message="圣旨和密令都准。",
        answer="臣领旨。",
        has_directive=False,
        secret_order_id=None,
        preclassified_intent={"kind": "confirmation", "confirmation": "应允"},
    )

    assert out["pending_action_failures"] == []
    assert db.list_pending_actions(state.turn) == []
    assert [order["title"] for order in db.list_secret_orders()] == ["暗查辽饷"]
    directives = db.list_directives(state, statuses=("pending",))
    assert len(directives) == 1
    assert directives[0]["text"] == "着户部清核辽饷。"


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
            payload={"name": "史可法", "office": "兵部主事", "appointer": minister,
                     "mode": "ordinary"},
        )

    GameSession.apply_cli_conversation_actions(
        _session(db, state, content=content),
        SimpleNamespace(name=minister, office_type="兵部"),
        player_message="中旨直发，准了。", answer="臣领旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "confirmation", "confirmation": "应允"},
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
        preclassified_intent={"kind": "confirmation", "confirmation": "应允"},
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
        preclassified_intent={"kind": "confirmation", "confirmation": "应允"},
        confirm_target_ids={pending_id},
    )
    audience_night.close_night(db, state, night_id=night["id"], content=content)

    dossiers = db.list_decree_dossiers(status="proposed")
    assert len(dossiers) == 1
    assert dossiers[0]["mode"] == "midzhi"


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
        payload={"name": "史可法", "office": "兵部主事"},
    )
    db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={
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
        payload={"name": "史可法", "office": "兵部主事"},
    )
    db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={
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


def test_tool_staged_action_is_not_confirmed_in_same_chat_turn(game):
    """本轮 tool 刚 stage 的 pending action 不能被同一句“准了”立即提交。"""
    db, state, content = game
    minister = "毕自严"
    tool_payload = json.dumps({
        "title": "暗查辽饷",
        "content": "暗查辽饷侵冒。",
        "assignee": minister,
        "tags": [],
        "deadline_months": 0,
    }, ensure_ascii=False)

    class Agent:
        def run(self, _message):
            return SimpleNamespace(
                content="臣领旨，请陛下定夺。",
                tools=[SimpleNamespace(tool_name="secret_order", result=f"__secret_order__{tool_payload}")],
            )

    class Registry:
        def get(self, _character):
            return Agent()

        def build_draft_line(self):
            return "无"

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = Registry()
    sess.llm_config = SimpleNamespace(channel="api")
    sess.temporary_characters = set()
    sess._audience_prompt_for_message = lambda message: message
    sess._start_cli_action_intent = lambda *_args, **_kwargs: None
    sess._finish_cli_action_intent = lambda *_args, **_kwargs: None

    result = GameSession.chat(sess, minister, "准了，密查辽饷。")

    assert result.pending_action_id
    assert db.list_secret_orders() == []
    assert len(db.list_pending_actions(state.turn)) == 1


def test_non_streaming_appointment_tool_stages_pending_action(game):
    """session.chat 的 propose_appointment 工具路也只暂存任免候选，不绕过确认闸门直写人物表。"""
    db, state, content = game
    minister = "毕自严"
    appointee = "工具候选乙"
    payload = json.dumps({
        "name": appointee,
        "office": "户部尚书",
        "action": "任命",
        "faction": "阉党",
        "reason": "吏部举荐",
    }, ensure_ascii=False)

    class Agent:
        def run(self, _message):
            return SimpleNamespace(
                content="臣遵旨，请陛下定夺。",
                tools=[SimpleNamespace(tool_name="propose_appointment", result=f"__pending_appointment__{payload}")],
            )

    class Registry:
        def get(self, _character):
            return Agent()

        def build_draft_line(self):
            return "无"

        def register(self, _character):
            return None

        def refresh(self, _character):
            return None

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = Registry()
    sess.llm_config = SimpleNamespace(channel="api")
    sess.temporary_characters = set()
    sess._audience_prompt_for_message = lambda message: message
    sess._start_cli_action_intent = lambda *_args, **_kwargs: None
    sess._finish_cli_action_intent = lambda *_args, **_kwargs: None

    def forbidden_direct_apply(*_args, **_kwargs):
        raise AssertionError("appointment tool results must not apply before confirmation")

    sess._apply_appointment = forbidden_direct_apply

    result = GameSession.chat(sess, minister, "中旨直发，拟以工具候选乙为户部尚书。")

    assert result.pending_action_id
    pending = db.list_pending_actions(state.turn)
    assert len(pending) == 1
    assert pending[0]["kind"] == "office"
    assert pending[0]["action"] == "任命"
    pending_payload = json.loads(pending[0]["payload_json"])
    assert pending_payload["name"] == appointee
    assert pending_payload["faction"] == "阉党"
    assert pending_payload["reason"] == "吏部举荐"
    assert pending_payload["mode"] == "midzhi"
    assert db.conn.execute(
        "SELECT name FROM characters WHERE name=?", (appointee,)
    ).fetchone() is None

    db.commit_pending_actions(state, content=content, registry=sess.registry)
    appointment_dossiers = [
        row for row in db.list_decree_dossiers(status="proposed")
        if row["action_type"] == "appointment"
    ]
    assert len(appointment_dossiers) == 1
    assert appointment_dossiers[0]["mode"] == "midzhi"
    promulgate_proposed_appointments(
        db, state, content, registry=sess.registry,
    )

    assert content.characters[appointee].faction == "阉党"


def test_confirmation_turn_ignores_same_turn_secret_order_tool_output(game, monkeypatch):
    """确认旧 pending 的同一句，不能再消费 tool sentinel 重建一道新密令。"""
    db, state, content = game
    minister = "毕自严"
    old_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={
            "title": "旧候选",
            "content": "旧候选内容",
            "assignee": minister,
            "tags": [],
            "deadline_months": 0,
        },
    )
    tool_payload = json.dumps({
        "title": "同句新令",
        "content": "同句新令内容",
        "assignee": minister,
        "tags": [],
        "deadline_months": 0,
    }, ensure_ascii=False)
    calls = []
    monkeypatch.setattr(
        cb,
        "_run_api_for_config",
        lambda *a, **k: (calls.append((a, k)) or (json.dumps({"确认": "应允"}, ensure_ascii=False), 1)),
    )

    class Agent:
        def run(self, _message):
            return SimpleNamespace(
                content="臣遵旨。",
                tools=[SimpleNamespace(tool_name="secret_order", result=f"__secret_order__{tool_payload}")],
            )

    class Registry:
        def get(self, _character):
            return Agent()

        def build_draft_line(self):
            return "无"

        def refresh(self, _name):
            return None

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = Registry()
    sess.llm_config = SimpleNamespace(channel="api")
    sess.temporary_characters = set()
    sess._audience_prompt_for_message = lambda message: message
    sess._start_cli_action_intent = lambda *_args, **_kwargs: None
    sess._finish_cli_action_intent = lambda *_args, **_kwargs: None

    result = GameSession.chat(sess, minister, "准了")

    assert result.pending_action_id == 0
    orders = db.list_secret_orders()
    assert len(orders) == 1
    assert orders[0]["title"] == "旧候选"
    assert db.list_pending_actions(state.turn) == []
    assert not db.conn.execute(
        "SELECT 1 FROM pending_actions WHERE id=? AND status='pending'", (old_id,)
    ).fetchone()


def test_secret_prefix_ignores_mismatched_directive_tool_output(game, monkeypatch):
    """显式密令前缀是权威 intent；错家族 propose_directive tool 不得压掉密令 fallback。"""
    db, state, content = game
    minister = "毕自严"
    monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: (json.dumps({
        "密令": {
            "标题": "暗查辽饷",
            "内容": "暗查辽饷侵冒。",
            "承办人": minister,
            "标签": ["辽饷"],
            "期限月数": 0,
        },
    }, ensure_ascii=False), 1))

    class Agent:
        def run(self, _message):
            return SimpleNamespace(
                content="臣领旨。",
                tools=[SimpleNamespace(tool_name="propose_directive", result="__pending_directive__着户部清核辽饷。")],
            )

    class Registry:
        def get(self, _character):
            return Agent()

        def build_draft_line(self):
            return "无"

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = Registry()
    sess.llm_config = SimpleNamespace(channel="api")
    sess.temporary_characters = set()
    sess._audience_prompt_for_message = lambda message: message
    sess._start_cli_action_intent = lambda *_args, **_kwargs: None
    sess._finish_cli_action_intent = lambda *_args, **_kwargs: None

    result = GameSession.chat(sess, minister, "密令如下：暗查辽饷侵冒。")

    assert result.pending_action_id
    pending = db.list_pending_actions(state.turn)
    assert len(pending) == 1
    assert pending[0]["kind"] == "secret_order"


def test_confirmation_commit_only_visible_pending_ids(game):
    """同句新 stage 的动作即便同大臣同 kind，也不能被本句确认顺手提交。"""
    db, state, _content = game
    minister = "毕自严"
    oid = db.create_secret_order(state, minister, "原标题", "原内容", [], deadline_months=0)
    old_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="更新", minister_name=minister, target_id=oid,
        payload={"new_title": "旧候选", "new_content": "旧候选内容", "deadline_months": 0},
    )
    new_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={"title": "同句新令", "content": "同句新令内容", "assignee": minister,
                 "tags": [], "deadline_months": 0},
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


def test_confirmation_reject_only_visible_pending_ids(game):
    """拒绝确认也只能丢本轮开始前可见的 pending，不能删同句新 stage。"""
    db, state, _content = game
    minister = "毕自严"
    oid = db.create_secret_order(state, minister, "原标题", "原内容", [], deadline_months=0)
    old_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="更新", minister_name=minister, target_id=oid,
        payload={"new_title": "旧候选", "new_content": "旧候选内容", "deadline_months": 0},
    )
    new_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={"title": "同句新令", "content": "同句新令内容", "assignee": minister,
                 "tags": [], "deadline_months": 0},
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


def test_legacy_registered_secret_order_marker_parser_restages(game):
    """旧 __secret_order_registered__<id>__ marker 经 chat parser 也要反转回 pending。"""
    db, state, content = game
    minister = "毕自严"
    oid = db.create_secret_order(state, minister, "暗查辽饷", "暗查辽饷侵冒。", [], deadline_months=0)

    class Agent:
        def run(self, _message):
            return SimpleNamespace(
                content="臣领旨，请陛下定夺。",
                tools=[SimpleNamespace(
                    tool_name="secret_order",
                    result=f"__secret_order_registered__{oid}__密令已登记入档",
                )],
            )

    class Registry:
        def get(self, _character):
            return Agent()

        def build_draft_line(self):
            return "无"

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = Registry()
    sess.llm_config = SimpleNamespace(channel="api")
    sess.temporary_characters = set()
    sess._audience_prompt_for_message = lambda message: message
    sess._start_cli_action_intent = lambda *_args, **_kwargs: None
    sess._finish_cli_action_intent = lambda *_args, **_kwargs: None

    result = GameSession.chat(sess, minister, "密令如下：暗查辽饷")

    assert result.pending_action_id
    assert db.list_secret_orders() == []
    assert db.list_pending_actions(state.turn)[0]["kind"] == "secret_order"


def test_secret_order_extract_fallback_preserves_structured_metadata(monkeypatch):
    """API/按钮兼容文本带出的标签/期限，在 extractor 空结果时也不能丢。"""
    monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: ("{}", 1))

    out = cb._extract_secret_order(
        "密令如下：暗查辽饷侵冒。\n标签：辽饷, 关宁\n期限：3月",
        "臣领旨。",
        "魏忠贤",
        llm_config=SimpleNamespace(channel="cli"),
    )

    assert out["tags"] == ["辽饷", "关宁"]
    assert out["deadline_months"] == 3

    negative = cb._extract_secret_order(
        "密令如下：暗查辽饷侵冒。\n期限：-5月",
        "臣领旨。",
        "魏忠贤",
        llm_config=SimpleNamespace(channel="cli"),
    )
    assert negative["deadline_months"] == 0


def test_secret_order_extract_keeps_explicit_zero_deadline(monkeypatch):
    """LLM 明确给 0 月时，不被御旨里的 fallback 期限覆盖。"""
    monkeypatch.setattr(
        cb,
        "_run_backend_for_config",
        lambda *a, **k: (json.dumps({
            "标题": "暗查辽饷",
            "内容": "暗查辽饷侵冒。",
            "承办人": "魏忠贤",
            "期限月数": 0,
            "标签": [],
        }, ensure_ascii=False), 1),
    )

    out = cb._extract_secret_order(
        "密令如下：暗查辽饷侵冒。\n期限：3月",
        "臣领旨。",
        "魏忠贤",
        llm_config=SimpleNamespace(channel="cli"),
    )

    assert out["deadline_months"] == 0


def test_draft_prefix_with_pending_confirmation_runs_zero_llm(game, monkeypatch):
    """#344「按钮前缀路零 LLM」(US3)——确认闸门面：该大臣有非 directive 待确认暂存动作时，
    玩家发 '拟旨如下：' 前缀不得触发 extract_confirmation_intent(LLM)，也不得被误判应允/拒绝
    把这道前缀拟旨吞掉。整合 cmr r4 codex 完整性腿抓出此 sibling 缺口（r3 只把住了密令块、
    漏了更靠前的确认闸门）→ 顶部单一 explicit_prefixed 统一把门所有后置 LLM 抽取器。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    who = "前缀零LLM确认承办官"
    # 预置一个非 directive 待确认暂存动作（confirm_targets 非空 → 旧路会跑确认抽取）
    db.stage_pending_action(
        state.turn, kind="office", action="任命",
        minister_name=who, target_id=None,
        payload={"name": "倪元璐", "office": "户部尚书", "appointer": who})

    def _forbidden(*a, **k):
        raise AssertionError("前缀拟旨不应触发任何后置 LLM 抽取器（含确认闸门）")

    monkeypatch.setattr(cb, "extract_confirmation_intent", _forbidden)
    monkeypatch.setattr(cb, "extract_minister_actions", _forbidden)
    monkeypatch.setattr(cb, "extract_draft_intent", _forbidden)
    monkeypatch.setattr(cb, "extract_appointment_action", _forbidden)

    result = _result()
    result.answer = "臣遵旨，当即清核辽饷。"
    _session(db, state, llm_config=SimpleNamespace(channel="cli"))._cli_backend_fallback_actions(
        result, SimpleNamespace(name=who, office_type="兵部"),
        "拟旨如下：着户部清核辽饷。")

    # 前缀拟旨零 LLM 暂存：未被确认闸门吞掉，也不直接绕进 turn_directives。
    assert result.proposed_directive is None
    assert result.pending_action_id
    pending = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "directive"]
    assert len(pending) == 1
    assert json.loads(pending[0]["payload_json"])["text"] == "臣遵旨，当即清核辽饷。"


def test_secret_prefix_confirmation_uses_recent_context_for_order_body(game, monkeypatch):
    """#354: 玩家先自然语言描述 covert 任务，下一轮只点「密令」确认“可，就按你意思办”。
    显式密令按钮是权威路由；密令字段提取必须看到前文任务正文，而不是只看确认短句。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "魏忠贤"
    described_task = "洪承畴已任陕西巡抚。命洪承畴督办陕西赈灾，东厂暗助护赈银、查截留。"
    db.append_chat_message(minister, state.turn, "user", described_task)
    db.append_chat_message(minister, state.turn, "minister", "臣领密旨，当令东厂暗中护送赈银。")
    captured = {}

    def fake_extract(prompt, llm_config=None, tag=""):
        captured["prompt"] = prompt
        return (json.dumps({
            "标题": "暗护陕西赈银",
            "内容": "命洪承畴督办陕西赈灾，东厂暗助护赈银并查截留。",
            "承办人": minister,
            "期限月数": 0,
            "标签": ["陕西", "赈灾", "东厂"],
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_extract)
    result = _result()
    result.answer = "臣领命。"

    _session(db, state, llm_config=SimpleNamespace(channel="cli"))._cli_backend_fallback_actions(
        result,
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：可，就按你意思办",
    )

    assert "督办陕西赈灾" in captured["prompt"]
    assert "东厂暗助护赈银" in captured["prompt"]
    row = _commit_staged_secret_order(db, state, result)
    assert row["minister_name"] == minister
    assert "督办陕西赈灾" in row["content"]


def test_api_tool_created_secret_order_skips_prefix_fallback_extraction(read_game, monkeypatch):
    """Codex ship review: API tool-call 已建密令时，前缀 fallback 不得再发起一次会被丢弃的抽取。"""
    db, state, _ = read_game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "魏忠贤"

    def forbidden_resolve(*args, **kwargs):
        raise AssertionError("tool-created secret order should not run fallback extraction")

    monkeypatch.setattr(cb, "resolve_minister_actions", forbidden_resolve)
    result = _session(db, state, llm_config=SimpleNamespace(channel="api")).apply_cli_conversation_actions(
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：暗查辽饷",
        "臣领旨。",
        has_directive=False,
        secret_order_id=123,
    )

    assert result["secret_order_id"] == 123


def test_api_tool_staged_secret_order_skips_prefix_fallback_extraction(game, monkeypatch):
    """#413：API tool-call 已暂存新密令时，前缀 fallback 不得再抽取出第二条候选。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "魏忠贤"
    pid = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister, target_id=None,
        payload={"title": "暗查辽饷", "content": "暗查辽饷。", "assignee": minister},
    )

    def forbidden_resolve(*args, **kwargs):
        raise AssertionError("tool-staged secret order should not run fallback extraction")

    monkeypatch.setattr(cb, "resolve_minister_actions", forbidden_resolve)
    result = _session(db, state, llm_config=SimpleNamespace(channel="api")).apply_cli_conversation_actions(
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：暗查辽饷",
        "臣领旨。",
        has_directive=True,
        secret_order_id=None,
    )

    assert result["secret_order_id"] is None
    assert not result.get("pending_action_id")
    pending = db.list_pending_actions(state.turn)
    assert len(pending) == 1 and pending[0]["id"] == pid


def test_legacy_registered_secret_order_marker_is_restaged(game):
    """#413 review fix：旧 __secret_order_registered__ 直写结果也要转回 pending，不能绕过确认闸门。"""
    db, state, _ = game
    minister = "魏忠贤"
    oid = db.create_secret_order(
        state, minister, "暗查辽饷", "暗查辽饷侵冒。", ["辽饷"], deadline_months=3,
        excluded_names=["毕自严"], excluded_offices=["户部"],
    )
    s = _session(db, state)

    pid = GameSession._stage_legacy_registered_secret_order(s, oid, minister)

    assert pid
    assert db.list_secret_orders() == []
    pending = db.list_pending_actions(state.turn)
    assert len(pending) == 1
    assert pending[0]["id"] == pid
    payload = json.loads(pending[0]["payload_json"])
    assert payload["title"] == "暗查辽饷"
    assert payload["content"] == "暗查辽饷侵冒。"
    assert payload["assignee"] == minister
    assert payload["tags"] == ["辽饷"]
    assert payload["deadline_months"] == 3
    assert "毕自严" in payload["excluded_names"]
    assert payload["excluded_offices"] == ["户部"]
    assert not db.conn.execute(
        "SELECT 1 FROM character_knowledge_sources WHERE source_id=?", (f"secret_order:{oid}",)
    ).fetchone()


def test_legacy_registered_secret_order_restaging_rolls_back_pending_if_delete_fails(game, monkeypatch):
    """旧直写密令转 pending 时若删除源行失败，不得留下 duplicate pending 候选。"""
    db, state, _ = game
    minister = "魏忠贤"
    oid = db.create_secret_order(state, minister, "暗查辽饷", "暗查辽饷侵冒。", ["辽饷"], deadline_months=3)
    s = _session(db, state)
    original_execute = db.conn.execute

    def fail_delete(sql, *args, **kwargs):
        if str(sql).lstrip().startswith("DELETE FROM secret_orders"):
            raise RuntimeError("delete failed")
        return original_execute(sql, *args, **kwargs)

    monkeypatch.setattr(db.conn, "execute", fail_delete)

    with pytest.raises(RuntimeError):
        GameSession._stage_legacy_registered_secret_order(s, oid, minister)

    monkeypatch.setattr(db.conn, "execute", original_execute)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM pending_actions WHERE kind='secret_order'"
    ).fetchone()[0] == 0
    assert db.conn.execute(
        "SELECT COUNT(*) FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()[0] == 1


def test_noop_appointment_intent_is_not_staged(read_game, monkeypatch):
    """#354: 背景里提到“某人已任某职”被抽成任命时，若其当前已在该职，确定性丢弃。"""
    db, state, content = read_game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    target = next(
        ch for ch in content.characters.values()
        if getattr(ch, "power_id", "ming") == "ming"
        and getattr(ch, "office", "")
        and getattr(ch, "office_type", "") != "后宫"
        and db.get_character_status(ch.name)[0] == "active"
    )
    summoner = next(
        ch for ch in content.characters.values()
        if ch.name != target.name
        and getattr(ch, "power_id", "ming") == "ming"
        and getattr(ch, "office_type", "") != "后宫"
        and db.get_character_status(ch.name)[0] == "active"
    )

    res = _session(db, state, llm_config=SimpleNamespace(channel="cli")).apply_cli_conversation_actions(
        SimpleNamespace(name=summoner.name, office_type=summoner.office_type),
        f"{target.name}已任{target.office}，可先查赈银截留。",
        "臣领旨。",
        has_directive=False,
        secret_order_id=None,
        preclassified_intent={
            "kind": "appointment",
            "appoint_action": "任命",
            "name": target.name,
            "office": target.office,
        },
    )

    assert not res.get("pending_action_id")
    assert db.list_pending_actions(state.turn) == []


def test_secret_prefix_keyao_confirmation_uses_recent_context(game, monkeypatch):
    """#354 (cmr): 「可，照办」是 issue 点名的确认短句（US3 / Testing Decisions F17），
    必须照样从前文召对取任务正文，而不是只把「可，照办」当密令交代。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "魏忠贤"
    described_task = "洪承畴已任陕西巡抚。命洪承畴督办陕西赈灾，东厂暗助护赈银、查截留。"
    db.append_chat_message(minister, state.turn, "user", described_task)
    db.append_chat_message(minister, state.turn, "minister", "臣领密旨，当令东厂暗中护送赈银。")
    captured = {}

    def fake_extract(prompt, llm_config=None, tag=""):
        captured["prompt"] = prompt
        return (json.dumps({
            "标题": "暗护陕西赈银",
            "内容": "命洪承畴督办陕西赈灾，东厂暗助护赈银并查截留。",
            "承办人": minister,
            "期限月数": 0,
            "标签": ["陕西"],
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_extract)
    result = _result()
    result.answer = "臣领命。"

    _session(db, state, llm_config=SimpleNamespace(channel="cli"))._cli_backend_fallback_actions(
        result,
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：可，照办",
    )

    assert "督办陕西赈灾" in captured["prompt"]
    row = _commit_staged_secret_order(db, state, result)
    assert "督办陕西赈灾" in row["content"]


def test_secret_prefix_confirmation_with_supplement_keeps_recent_context(game, monkeypatch):
    """#354 correctness: 确认句带期限/补充时仍是对前文任务的确认，不能只把按钮当轮短句交给密令抽取。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "魏忠贤"
    db.append_chat_message(minister, state.turn, "user", "命洪承畴督办陕西赈灾，东厂暗助护赈银、查截留。")
    db.append_chat_message(minister, state.turn, "minister", "臣领密旨，当令东厂暗中护送赈银。")
    captured = {}

    def fake_extract(prompt, llm_config=None, tag=""):
        captured["prompt"] = prompt
        return (json.dumps({
            "标题": "暗护陕西赈银",
            "内容": "三月内回奏。",  # 若上下文没有被并入，兜底也保不住前文任务
            "承办人": minister,
            "期限月数": 3,
            "标签": ["陕西"],
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_extract)
    result = _result()
    result.answer = "臣领命。"

    _session(db, state, llm_config=SimpleNamespace(channel="cli"))._cli_backend_fallback_actions(
        result,
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：可，照办，三月内回奏",
    )

    assert "督办陕西赈灾" in captured["prompt"]
    row = _commit_staged_secret_order(db, state, result)
    assert "督办陕西赈灾" in row["content"]
    assert "三月内回奏" in row["content"]


def test_api_channel_secret_prefix_confirmation_uses_recent_context(game, monkeypatch):
    """#354 correctness r2: API/tool-call 通道未产出 secret_order 时，显式密令按钮仍是权威路由。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "魏忠贤"
    db.append_chat_message(minister, state.turn, "user", "命洪承畴督办陕西赈灾，东厂暗助护赈银、查截留。")
    db.append_chat_message(minister, state.turn, "minister", "臣领密旨，当令东厂暗中护送赈银。")

    def fake_extract(prompt, llm_config=None, tag=""):
        return (json.dumps({
            "标题": "暗护陕西赈银",
            "内容": "命洪承畴督办陕西赈灾，东厂暗助护赈银并查截留。",
            "承办人": minister,
            "期限月数": 0,
            "标签": ["陕西"],
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_api_for_config", fake_extract)
    res = _session(db, state, llm_config=SimpleNamespace(channel="api")).apply_cli_conversation_actions(
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：可，照办",
        "臣领命。",
        has_directive=False,
        secret_order_id=None,
    )

    row = _commit_staged_secret_order(db, state, res)
    assert row["minister_name"] == minister
    assert "督办陕西赈灾" in row["content"]


def test_api_channel_secret_prefix_extracts_deadline_without_cli_helper(game, monkeypatch):
    """#354/#358 cmr r10: API 显式密令路要用 API 抽取字段，不能调用 CLI-only helper 后吞错丢期限。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "魏忠贤"
    db.append_chat_message(minister, state.turn, "user", "命洪承畴督办陕西赈灾。")
    db.append_chat_message(minister, state.turn, "minister", "臣领密旨。")

    def forbidden_cli(*_args, **_kwargs):
        raise AssertionError("API 密令字段提取不应调用 CLI-only helper")

    def fake_api_extract(prompt, llm_config=None, tag=""):
        assert tag == "secret_extract"
        assert getattr(llm_config, "channel", "") == "api"
        return (json.dumps({
            "标题": "督赈陕西",
            "内容": "命洪承畴督办陕西赈灾，三月内回奏。",
            "承办人": minister,
            "期限月数": 3,
            "标签": ["陕西"],
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", forbidden_cli)
    monkeypatch.setattr(cb, "_run_api_for_config", fake_api_extract)
    res = _session(db, state, llm_config=SimpleNamespace(channel="api")).apply_cli_conversation_actions(
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：可，照办，三月内回奏",
        "臣领命。",
        has_directive=False,
        secret_order_id=None,
    )

    row = _commit_staged_secret_order(db, state, res)
    assert "三月内回奏" in row["content"]
    assert row["due_turn"] == state.turn + 3


def test_api_channel_mixed_confirmation_keeps_supplement_when_extract_fails(game, monkeypatch):
    """#354 correctness r3: API/提取失败兜底时，混合确认句里的期限/约束不能随确认噪声整行丢掉。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "魏忠贤"
    db.append_chat_message(minister, state.turn, "user", "命洪承畴督办陕西赈灾，东厂暗助护赈银、查截留。")
    db.append_chat_message(minister, state.turn, "minister", "臣领密旨，当令东厂暗中护送赈银。")

    def fail_extract(*_args, **_kwargs):
        raise RuntimeError("backend unavailable")

    monkeypatch.setattr(cb, "_run_api_for_config", fail_extract)
    res = _session(db, state, llm_config=SimpleNamespace(channel="api")).apply_cli_conversation_actions(
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：可，照办，三月内回奏",
        "臣领命。",
        has_directive=False,
        secret_order_id=None,
    )

    row = _commit_staged_secret_order(db, state, res)
    assert "督办陕西赈灾" in row["content"]
    assert "三月内回奏" in row["content"]


def test_secret_context_path_preserves_multiple_related_emperor_task_lines(game, monkeypatch):
    """#354 correctness: 玩家前几轮连续补充同一密令任务时，兜底/守门不能只保留最后一条皇帝行。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "魏忠贤"
    db.append_chat_message(minister, state.turn, "user", "命洪承畴督办陕西赈灾。")
    db.append_chat_message(minister, state.turn, "minister", "臣领命。")
    db.append_chat_message(minister, state.turn, "user", "再令东厂护赈银、查截留。")
    db.append_chat_message(minister, state.turn, "minister", "臣当密遣番役护银。")

    def fake_extract_drops_first_task(prompt, llm_config=None, tag=""):
        return (json.dumps({
            "标题": "护赈银",
            "内容": "再令东厂护赈银、查截留。",
            "承办人": minister,
            "期限月数": 0,
            "标签": ["东厂"],
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_extract_drops_first_task)
    result = _result()
    result.answer = "臣领命。"

    _session(db, state, llm_config=SimpleNamespace(channel="cli"))._cli_backend_fallback_actions(
        result,
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：可，照办",
    )

    row = _commit_staged_secret_order(db, state, result)
    body = row["content"]
    assert "督办陕西赈灾" in body
    assert "护赈银" in body
    assert "京营操练" not in body


def test_secret_context_path_preserves_related_bingming_continuation(game, monkeypatch):
    """#354 cmr r14: 并命/又命/另遣 等延续式任务行也要与上一行合并，不能只认再令。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "魏忠贤"
    db.append_chat_message(minister, state.turn, "user", "命洪承畴督办陕西赈灾。")
    db.append_chat_message(minister, state.turn, "minister", "臣领命。")
    db.append_chat_message(minister, state.turn, "user", "并命东厂护赈银、查截留。")
    db.append_chat_message(minister, state.turn, "minister", "臣当密遣番役护银。")

    def fake_extract_drops_first_task(prompt, llm_config=None, tag=""):
        return (json.dumps({
            "标题": "护赈银",
            "内容": "并命东厂护赈银、查截留。",
            "承办人": minister,
            "期限月数": 0,
            "标签": ["东厂"],
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_extract_drops_first_task)
    result = _result()
    result.answer = "臣领命。"

    _session(db, state, llm_config=SimpleNamespace(channel="cli"))._cli_backend_fallback_actions(
        result,
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：可，照办",
    )

    row = _commit_staged_secret_order(db, state, result)
    body = row["content"]
    assert "督办陕西赈灾" in body
    assert "护赈银" in body


def test_secret_order_body_excludes_audience_role_labels(game, monkeypatch):
    """#354 (cmr): 密令正文必须是任务文本，不得混入对话快照的角色标签
    「皇帝：」「大臣：」或「【本轮确认】」短句（御旨守门/兜底误用对话 blob 会污染正文）。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "魏忠贤"
    described_task = "命洪承畴督办陕西赈灾，东厂暗助护赈银、查截留。"
    db.append_chat_message(minister, state.turn, "user", described_task)
    db.append_chat_message(minister, state.turn, "minister", "臣领密旨，当令东厂暗中护送赈银。")

    def fake_extract(prompt, llm_config=None, tag=""):
        return (json.dumps({
            "标题": "暗护陕西赈银",
            "内容": "命洪承畴督办陕西赈灾，东厂暗助护赈银并查截留。",
            "承办人": minister,
            "期限月数": 0,
            "标签": ["陕西"],
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_extract)
    result = _result()
    result.answer = "臣领命。"

    _session(db, state, llm_config=SimpleNamespace(channel="cli"))._cli_backend_fallback_actions(
        result,
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：可，就按你意思办",
    )

    row = _commit_staged_secret_order(db, state, result)
    body = row["content"]
    assert "督办陕西赈灾" in body
    assert "皇帝：" not in body
    assert "大臣：" not in body
    assert "本轮确认" not in body
    assert "就按你意思办" not in body


def test_secret_context_path_preserves_prior_minister_supplement(game, monkeypatch):
    """#354 (cmr r3): 「大臣领命回话」的实质补充也是密令正文一部分——若前文大臣加了实质承办
    步骤（封存兵部辽饷册），按钮轮只「臣领命」、LLM 又漏掉该补充，补充守门须照样兜底保住它，
    不因它来自前文（非当前回话）就漏检。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "魏忠贤"
    db.append_chat_message(minister, state.turn, "user", "命李若琏暗查阉党余孽。")
    db.append_chat_message(
        minister, state.turn, "minister", "臣领密旨，另需封存兵部辽饷册以防串改。")

    def fake_extract_drops_supplement(prompt, llm_config=None, tag=""):
        return (json.dumps({
            "标题": "暗查阉党",
            "内容": "命李若琏暗查阉党余孽。",  # 漏掉了大臣补的「封存兵部辽饷册」
            "承办人": minister,
            "期限月数": 0,
            "标签": ["阉党"],
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_extract_drops_supplement)
    result = _result()
    result.answer = "臣领命。"

    _session(db, state, llm_config=SimpleNamespace(channel="cli"))._cli_backend_fallback_actions(
        result,
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：可，照办",
    )

    row = _commit_staged_secret_order(db, state, result)
    body = row["content"]
    assert "封存兵部辽饷册" in body  # 前文大臣实质补充保住
    assert "皇帝：" not in body
    assert "大臣：" not in body


def test_secret_context_path_ignores_unrelated_prior_conversation(game, monkeypatch):
    """#354 (cmr r4): 密令正文只取最近的任务跨度——同回合更早的【无关】问答（如先问京营操练）
    不得混进密令正文。否则御旨守门按无关问句逐句核验必然失败、兜底把无关问句并进正文。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "魏忠贤"
    db.append_chat_message(minister, state.turn, "user", "近日京营操练如何？")
    db.append_chat_message(minister, state.turn, "minister", "回陛下，操练如常。")
    db.append_chat_message(minister, state.turn, "user", "命李若琏暗查阉党余孽。")
    db.append_chat_message(minister, state.turn, "minister", "臣领命。")

    def fake_extract(prompt, llm_config=None, tag=""):
        return (json.dumps({
            "标题": "暗查阉党",
            "内容": "命李若琏暗查阉党余孽。",
            "承办人": minister,
            "期限月数": 0,
            "标签": ["阉党"],
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_extract)
    result = _result()
    result.answer = "臣领命。"

    _session(db, state, llm_config=SimpleNamespace(channel="cli"))._cli_backend_fallback_actions(
        result,
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：可，照办",
    )

    row = _commit_staged_secret_order(db, state, result)
    body = row["content"]
    assert "暗查阉党" in body
    assert "京营操练" not in body  # 同回合无关问答不入密令正文


def test_secret_context_path_ignores_unrelated_prior_task_like_command(game, monkeypatch):
    """#354 cmr r10: 更早的无关命令式话语也是边界，不能因 task-like 就并入后续密令。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "魏忠贤"
    db.append_chat_message(minister, state.turn, "user", "命京营明日加操。")
    db.append_chat_message(minister, state.turn, "minister", "臣遵旨。")
    db.append_chat_message(minister, state.turn, "user", "命李若琏暗查阉党余孽。")
    db.append_chat_message(minister, state.turn, "minister", "臣领命。")

    def fake_extract(prompt, llm_config=None, tag=""):
        return (json.dumps({
            "标题": "暗查阉党",
            "内容": "命李若琏暗查阉党余孽。",
            "承办人": minister,
            "期限月数": 0,
            "标签": ["阉党"],
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_extract)
    result = _result()
    result.answer = "臣领命。"

    _session(db, state, llm_config=SimpleNamespace(channel="cli"))._cli_backend_fallback_actions(
        result,
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：可，照办",
    )

    row = _commit_staged_secret_order(db, state, result)
    body = row["content"]
    assert "暗查阉党" in body
    assert "京营明日加操" not in body


def test_secret_context_path_ignores_prior_task_with_same_assignee(game, monkeypatch):
    """#354 cmr r11: 同一承办人不等于同一密令；不同任务共享人名也不能被 keygram 合并。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "魏忠贤"
    db.append_chat_message(minister, state.turn, "user", "命李若琏暗查阉党余孽。")
    db.append_chat_message(minister, state.turn, "minister", "臣遵旨。")
    db.append_chat_message(minister, state.turn, "user", "命李若琏密查关宁军饷。")
    db.append_chat_message(minister, state.turn, "minister", "臣领命。")

    def fake_extract(prompt, llm_config=None, tag=""):
        return (json.dumps({
            "标题": "密查军饷",
            "内容": "命李若琏密查关宁军饷。",
            "承办人": minister,
            "期限月数": 0,
            "标签": ["关宁", "军饷"],
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_extract)
    result = _result()
    result.answer = "臣领命。"

    _session(db, state, llm_config=SimpleNamespace(channel="cli"))._cli_backend_fallback_actions(
        result,
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：可，照办",
    )

    row = _commit_staged_secret_order(db, state, result)
    body = row["content"]
    assert "密查关宁军饷" in body
    assert "暗查阉党余孽" not in body


def test_secret_context_path_ignores_unrelated_prior_task_before_lingqian(game, monkeypatch):
    """#354 cmr r15: 另遣/并命 是延续标记但不是无条件相关，前一条无关任务仍须排除。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "魏忠贤"
    db.append_chat_message(minister, state.turn, "user", "命京营明日加操。")
    db.append_chat_message(minister, state.turn, "minister", "臣遵旨。")
    db.append_chat_message(minister, state.turn, "user", "另遣李若琏密查关宁军饷。")
    db.append_chat_message(minister, state.turn, "minister", "臣领命。")

    def fake_extract(prompt, llm_config=None, tag=""):
        return (json.dumps({
            "标题": "密查军饷",
            "内容": "另遣李若琏密查关宁军饷。",
            "承办人": minister,
            "期限月数": 0,
            "标签": ["关宁", "军饷"],
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_extract)
    result = _result()
    result.answer = "臣领命。"

    _session(db, state, llm_config=SimpleNamespace(channel="cli"))._cli_backend_fallback_actions(
        result,
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：可，照办",
    )

    row = _commit_staged_secret_order(db, state, result)
    body = row["content"]
    assert "密查关宁军饷" in body
    assert "京营明日加操" not in body


def test_secret_context_path_preserves_confidentiality_constraint_line(game, monkeypatch):
    """#354 cmr r15: 任务后的保密/不可泄露约束是上一任务补充，不得把任务行切掉。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "魏忠贤"
    db.append_chat_message(minister, state.turn, "user", "命李若琏暗查阉党余孽。")
    db.append_chat_message(minister, state.turn, "minister", "臣领命。")
    db.append_chat_message(minister, state.turn, "user", "此事机密，不可泄露。")
    db.append_chat_message(minister, state.turn, "minister", "臣谨记。")

    def fake_extract_drops_task(prompt, llm_config=None, tag=""):
        return (json.dumps({
            "标题": "保密约束",
            "内容": "此事机密，不可泄露。",
            "承办人": minister,
            "期限月数": 0,
            "标签": ["机密"],
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_extract_drops_task)
    result = _result()
    result.answer = "臣领命。"

    _session(db, state, llm_config=SimpleNamespace(channel="cli"))._cli_backend_fallback_actions(
        result,
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：可，照办",
    )

    row = _commit_staged_secret_order(db, state, result)
    body = row["content"]
    assert "暗查阉党余孽" in body
    assert "不可泄露" in body


def test_secret_context_path_keeps_offtopic_llm_guard(game, monkeypatch):
    """#354 (cmr r2): 上下文合成路径不得无条件信 LLM——若 LLM 内容跑题（写成别的任务），
    御旨守门须照样兜底回前文真任务，不静默采信跑题正文。守门输入用剥标签后的任务文本。"""
    db, state, _ = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = "魏忠贤"
    described_task = "命洪承畴督办陕西赈灾，东厂暗助护赈银、查截留。"
    db.append_chat_message(minister, state.turn, "user", described_task)
    db.append_chat_message(minister, state.turn, "minister", "臣领密旨。")

    def fake_extract_offtopic(prompt, llm_config=None, tag=""):
        return (json.dumps({
            "标题": "清查盐政",
            "内容": "命毕自严清查两淮盐政，追比积欠。",  # 完全跑题
            "承办人": minister,
            "期限月数": 0,
            "标签": ["盐政"],
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_extract_offtopic)
    result = _result()
    result.answer = "臣领命。"

    _session(db, state, llm_config=SimpleNamespace(channel="cli"))._cli_backend_fallback_actions(
        result,
        SimpleNamespace(name=minister, office_type="司礼监"),
        "密令如下：可，照办",
    )

    row = _commit_staged_secret_order(db, state, result)
    body = row["content"]
    assert "督办陕西赈灾" in body  # 真任务兜底保住
    assert "皇帝：" not in body
    assert "本轮确认" not in body


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

    # 第一夜：一段密谋，随后收夜
    n1 = an.open_night(db, state)["id"]
    _link_night_chat_turn(
        db, state, n1, minister, "命东厂暗查阉党第一夜密谋。", "臣领密旨，第一夜遵办。")
    db.conn.execute(
        "UPDATE audience_nights SET status='closed' WHERE id=?", (int(n1),))
    db.conn.commit()

    # 第二夜：另起一段任务，按钮确认取喂料
    n2 = an.open_night(db, state)["id"]
    _link_night_chat_turn(
        db, state, n2, minister, "命李若琏第二夜暗查关宁军饷。", "臣领命，第二夜遵办。")

    ctx = session_mod._recent_audience_context_for_secret_order(
        db, minister, int(state.turn), "密令如下：可，照办")

    assert "第二夜暗查关宁军饷" in ctx  # 本夜正文取到
    assert "第一夜密谋" not in ctx      # 上一夜正文不串入


def test_noop_appointment_alias_target_is_not_staged(read_game, monkeypatch):
    """#354 (cmr): no-op 任免丢弃须按 canonical 口径——背景句用别名提到「某人已任某职」、
    其规范名当前已在该职时，照样确定性丢弃，不因别名查不到精确行而漏判成假任免。"""
    db, state, content = read_game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    target = next(
        ch for ch in content.characters.values()
        if getattr(ch, "power_id", "ming") == "ming"
        and getattr(ch, "office", "")
        and getattr(ch, "office_type", "") != "后宫"
        and any(a != ch.name for a in (getattr(ch, "aliases", None) or []))
        and db.get_character_status(ch.name)[0] == "active"
    )
    alias = next(a for a in target.aliases if a != target.name)
    summoner = next(
        ch for ch in content.characters.values()
        if ch.name != target.name
        and getattr(ch, "power_id", "ming") == "ming"
        and getattr(ch, "office_type", "") != "后宫"
        and db.get_character_status(ch.name)[0] == "active"
    )

    res = _session(
        db, state, llm_config=SimpleNamespace(channel="cli"), content=content,
    ).apply_cli_conversation_actions(
        SimpleNamespace(name=summoner.name, office_type=summoner.office_type),
        f"{alias}已任{target.office}，可先查赈银截留。",
        "臣领旨。",
        has_directive=False,
        secret_order_id=None,
        preclassified_intent={
            "kind": "appointment",
            "appoint_action": "任命",
            "name": alias,
            "office": target.office,
        },
    )

    assert not res.get("pending_action_id")
    assert db.list_pending_actions(state.turn) == []


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


def test_chat_starts_cli_action_classification_before_reply_finishes(read_game, monkeypatch):
    """CLI 召对动作判断只看皇帝消息，应与大臣回话并发；无动作消息回话后不再跑抽取器。"""
    db, state, content = read_game
    minister = next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫",)
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
    )
    classifier_started = threading.Event()
    allow_reply = threading.Event()
    calls = []

    def fake_classify(*args, **kwargs):
        calls.append("classify")
        classifier_started.set()
        return {"kind": "none"}

    def forbidden_post_reply(*args, **kwargs):
        raise AssertionError("普通问询回话后不应再跑动作抽取")

    class FakeAgent:
        def run(self, message):
            assert classifier_started.wait(1), "动作判断应在大臣回话完成前启动"
            allow_reply.set()
            return SimpleNamespace(content="臣谨奏：辽饷尚可支应。", tools=[])

    registry = SimpleNamespace(
        get=lambda character: FakeAgent(),
        build_draft_line=lambda: "无",
    )
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = registry
    # 并发分类器仅对并发安全 runner（codex）启用——cmr Gate2 守门（agy/claude 并发未验证）。
    sess.llm_config = SimpleNamespace(channel="cli", cli_runner="codex")
    sess.temporary_characters = {}
    sess._retrieve_memories_for_message = lambda message: message

    monkeypatch.setattr(session_mod, "_dump_llm_messages", lambda *a, **k: None)
    monkeypatch.setattr(cb, "classify_cli_action_intent", fake_classify)
    monkeypatch.setattr(cb, "extract_minister_actions", forbidden_post_reply)
    monkeypatch.setattr(cb, "extract_appointment_action", forbidden_post_reply)
    monkeypatch.setattr(cb, "extract_draft_intent", forbidden_post_reply)
    monkeypatch.setattr(cb, "extract_confirmation_intent", forbidden_post_reply)

    result = sess.chat(minister.name, "辽东军饷如何？")

    assert allow_reply.is_set()
    assert result.answer == "臣谨奏：辽饷尚可支应。"
    assert calls == ["classify"]


def test_non_parallel_safe_runner_skips_concurrent_classifier(read_game, monkeypatch):
    """非并发安全 runner（agy）不得把动作分类器与回话并发跑（会撞 keychain auth-race，
    cmr Gate2 F-E）：_start_cli_action_intent 返 None → 回话后回落串行抽取，动作不丢。"""
    db, state, content = read_game
    minister = next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫",)
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
    )
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.llm_config = SimpleNamespace(channel="cli", cli_runner="agy")
    sess.temporary_characters = {}

    def fake_classify(*args, **kwargs):
        raise AssertionError("agy runner 不应并发跑分类器")

    monkeypatch.setattr(cb, "classify_cli_action_intent", fake_classify)
    # agy 非并发安全 → 返 None，不触发分类器。
    assert sess._start_cli_action_intent(minister, "辽东军饷如何？") is None
    # 对照：codex 并发安全 → 返回 future（真跑分类器）。
    sess.llm_config = SimpleNamespace(channel="cli", cli_runner="codex")
    monkeypatch.setattr(cb, "classify_cli_action_intent", lambda *a, **k: {"kind": "none"})
    fut = sess._start_cli_action_intent(minister, "辽东军饷如何？")
    assert fut is not None
    fut.result(timeout=2)


@pytest.mark.parametrize(
    ("message", "classified", "expected_kind", "audience_context"),
    [
        ("请另拟一道赈陕西的旨。", [{"kind": "draft"}], "directive", "plain"),
        (
            "另遣人暗查晋商输饷去向。",
            [{"kind": "secret", "secret_action": "新建"}],
            "secret_order",
            "plain",
        ),
        ("请另拟一道赈陕西的旨。", [{"kind": "draft"}], "directive", "active_secret"),
        ("请另拟一道赈陕西的旨。", [{"kind": "draft"}], "directive", "consort"),
    ],
)
def test_non_parallel_safe_chat_serially_classifies_new_actions(
    game, monkeypatch, message, classified, expected_kind, audience_context,
):
    """agy/claude 不并发时按 runtime 串行分类；既有业务状态不吞 fresh draft。"""
    db, state, content = game
    if audience_context == "consort":
        minister = next(
            ch for ch in content.characters.values()
            if getattr(ch, "office_type", "") == "后宫"
            and db.resolve_power_id(ch) == "ming"
            and db.get_character_status(ch.name)[0] == "active"
        )
    else:
        minister = next(
            ch for ch in content.characters.values()
            if getattr(ch, "office_type", "") != "后宫"
            and db.resolve_power_id(ch) == "ming"
            and db.get_character_status(ch.name)[0] == "active"
        )
    if audience_context == "active_secret":
        db.create_secret_order(state, minister.name, "暗查旧案", "继续暗查旧案。", [])
    calls = []

    class FakeAgent:
        def run(self, _message):
            calls.append("reply")
            return SimpleNamespace(content="臣已拟妥，伏候圣裁。", tools=[])

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = SimpleNamespace(
        get=lambda _character: FakeAgent(),
        build_draft_line=lambda: "无",
    )
    sess.llm_config = SimpleNamespace(channel="cli", cli_runner="agy")
    sess.temporary_characters = {}
    sess._retrieve_memories_for_message = lambda text: text
    monkeypatch.setattr(session_mod, "_dump_llm_messages", lambda *a, **k: None)

    def fake_classify(*_args, **_kwargs):
        calls.append("classify")
        return classified

    # 串行分类契约：只替 classifier；后置物化 extract 用返回值 stub，禁 blanket patch runner/真 subprocess。
    monkeypatch.setattr(cb, "classify_cli_action_intent", fake_classify)
    monkeypatch.setattr(
        cb,
        "_extract_secret_order",
        lambda *a, **k: {
            "title": "暗查输饷",
            "content": "暗查晋商输饷去向",
            "assignee": minister.name,
            "tags": [],
            "deadline_months": 0,
            "excluded_names": [],
            "excluded_offices": [],
        },
    )
    monkeypatch.setattr(
        cb,
        "extract_draft_intent",
        lambda *a, **k: {
            "draft_action": "拟旨",
            "draft_text": "臣已拟妥，伏候圣裁。",
            "target_candidate": "",
        },
    )

    sess.chat(minister.name, message)

    assert calls == ["reply", "classify"]
    assert any(
        row["kind"] == expected_kind
        for row in db.list_pending_actions(state.turn, minister_name=minister.name)
    )


def test_api_chat_never_calls_cli_classifier(game, monkeypatch):
    """API 真实 session.chat 入口不因无 active 业务状态而额外调用 CLI classifier。"""
    db, state, content = game
    minister = next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") != "后宫"
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
    )

    class FakeAgent:
        def run(self, _message):
            return SimpleNamespace(content="臣谨奏：陕西赈务尚待核实。", tools=[])

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = SimpleNamespace(
        get=lambda _character: FakeAgent(),
        build_draft_line=lambda: "无",
    )
    sess.llm_config = SimpleNamespace(channel="api")
    sess.temporary_characters = {}
    sess._retrieve_memories_for_message = lambda text: text
    monkeypatch.setattr(session_mod, "_dump_llm_messages", lambda *a, **k: None)
    monkeypatch.setattr(
        cb,
        "classify_cli_action_intent",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("API channel must not invoke CLI classifier")
        ),
    )

    result = sess.chat(minister.name, "陕西赈务如何？")

    assert result.answer == "臣谨奏：陕西赈务尚待核实。"


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
        registry=None,
        last_decree="",
        last_report="",
        _begun=False,
        auto_save=lambda label: None,
        turn_snapshot=lambda: SimpleNamespace(ok=True),
    )
    monkeypatch.setattr(session_mod, "_sync_offices_from_db_impl",
                        lambda content, db, llm_config=None: seen.append(llm_config))
    monkeypatch.setattr(session_mod, "MinisterRegistry",
                        lambda llm_config, agno_db, context: SimpleNamespace())

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
        registry=SimpleNamespace(),
    )
    monkeypatch.setattr(session_mod, "_sync_offices_from_db_impl",
                        lambda content, db, llm_config=None: seen.append(llm_config))
    monkeypatch.setattr(session_mod, "MinisterRegistry",
                        lambda llm_config, agno_db, context: SimpleNamespace())

    GameSession.refresh_runtime_after_chat_rollback(fake)

    assert seen == [cfg]


def test_no_backend_is_noop(read_game, monkeypatch):
    """未启 CLI 后端（走原 api 路径）时，胶水不动任何东西。"""
    db, state, _ = read_game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    result = _result()
    result.answer = "臣领旨。敕谕户部发银三万两。钦此。"
    _session(db, state)._cli_backend_fallback_actions(
        result, SimpleNamespace(name="毕自严", office_type="户部"), "拟旨如下：发三万两赈陕西")
    assert result.proposed_directive is None
    assert result.secret_order_id is None


def test_draft_prefix_stages_directive(game, monkeypatch):
    """玩家『拟旨如下：』→ 大臣回话原文进 pending_actions，等待对话确认或颁诏默认同意。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    _no_conv_action(monkeypatch)
    result = _result()
    result.answer = "臣领旨。敕谕户部与陕西巡抚发太仓银三万两亲督赈发。钦此。"
    _session(db, state)._cli_backend_fallback_actions(
        result, SimpleNamespace(name="毕自严", office_type="户部"), "拟旨如下：发三万两赈陕西")
    assert result.proposed_directive is None
    assert result.pending_action_id
    pending = db.list_pending_actions(state.turn)
    assert len(pending) == 1 and pending[0]["kind"] == "directive"
    assert json.loads(pending[0]["payload_json"])["text"] == "臣领旨。敕谕户部与陕西巡抚发太仓银三万两亲督赈发。钦此。"
    assert "请陛下定夺准驳" in result.answer
    assert db.conn.execute(
        "SELECT COUNT(*) FROM turn_directives WHERE turn=?", (state.turn,)
    ).fetchone()[0] == 0


def test_runtime_cli_channel_without_env_stages_directive(game, monkeypatch):
    """runtime 选择 CLI 通道时，即使无 MING_SIM_LLM_BACKEND，也要启用会话写动作胶水。"""
    db, state, _ = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    _no_conv_action(monkeypatch)
    result = _result()
    result.answer = "臣领旨。敕谕户部与陕西巡抚发太仓银三万两亲督赈发。钦此。"
    _session(db, state, llm_config=SimpleNamespace(channel="cli"))._cli_backend_fallback_actions(
        result, SimpleNamespace(name="毕自严", office_type="户部"), "拟旨如下：发三万两赈陕西")

    assert result.proposed_directive is None
    assert result.pending_action_id
    pending = db.list_pending_actions(state.turn)
    assert len(pending) == 1 and pending[0]["kind"] == "directive"
    assert json.loads(pending[0]["payload_json"])["text"] == "臣领旨。敕谕户部与陕西巡抚发太仓银三万两亲督赈发。钦此。"
    assert "请陛下定夺准驳" in result.answer
    assert db.conn.execute(
        "SELECT COUNT(*) FROM turn_directives WHERE turn=?", (state.turn,)
    ).fetchone()[0] == 0


def test_runtime_cli_secret_prefix_merges_via_configured_runner(game, monkeypatch):
    """#397：runtime CLI 通道的前缀密令经配置 runner(codex) 合并皇帝旨意 + 大臣回话，
    不再直取回话当正文（旧零 LLM 路径会丢御旨）。"""
    db, state, _ = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    calls = []
    canned = json.dumps({
        "标题": "密查辽东军饷",
        "内容": "查辽东军饷有无侵冒，三月内回奏；着李若琏暗查。",
        "承办人": "李若琏",
        "期限月数": 3,
        "标签": ["辽饷"],
    }, ensure_ascii=False)

    def fake_codex(prompt, model=None, timeout=None, **kwargs):
        calls.append(("codex", model, timeout))
        return canned, 1

    monkeypatch.setattr(cb, "_run_codex", fake_codex)
    monkeypatch.setattr(cb, "_run_agy", lambda p, timeout=None: (_ for _ in ()).throw(
        AssertionError("runtime codex 通道不应回落 agy")))
    result = _result()
    result.answer = "臣领密旨，可授李若琏暗查。"
    _session(
        db,
        state,
        llm_config=SimpleNamespace(
            channel="cli", cli_runner="codex", cli_model="gpt-5.5", cli_timeout_seconds=240,
        ),
    )._cli_backend_fallback_actions(
        result, SimpleNamespace(name="王在晋", office_type="兵部"),
        "密令如下：查辽东军饷有无侵冒，三月内回奏")

    # 经配置 runner 合并润色（不再零 LLM）
    assert calls == [("codex", "gpt-5.5", 240)]
    row = _commit_staged_secret_order(db, state, result)
    assert "查辽东军饷" in row["content"]          # 御旨不丢
    assert "李若琏" in row["content"]              # 大臣补充保留
    assert row["minister_name"] == "李若琏"        # 大臣建议的承办人被采纳


def test_secret_prefix_creates_order(game, monkeypatch):
    """#397/#413：玩家『密令如下：』→ 合并皇帝旨意 + 大臣回话，先暂存，确认/commit 后建 active 密令。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    canned = json.dumps({
        "标题": "查辽东军饷有无侵冒",
        "内容": "查辽东军饷有无侵冒，三月内回奏；可授李若琏暗查。",
        "承办人": "王在晋",
        "期限月数": 0,
        "标签": [],
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_agy", lambda p, timeout=None: (canned, 1))
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    result = _result()
    result.answer = "臣领密旨，可授李若琏暗查。"
    _session(db, state, registry=None)._cli_backend_fallback_actions(
        result, SimpleNamespace(name="王在晋", office_type="兵部"),
        "密令如下：查辽东军饷有无侵冒，三月内回奏")
    row = _commit_staged_secret_order(db, state, result)
    assert "查辽东军饷" in row["content"]          # 御旨不丢（#397）
    assert "李若琏" in row["content"]              # 大臣补充保留
    # #401 R1：正文/回话皆指李若琏，承办人字段填王在晋属漂移→采信校验后的线索李若琏
    assert row["minister_name"] == "李若琏"
    assert row["status"] == "active"


def test_secret_prefix_upserts_not_duplicates_and_refreshes(game, monkeypatch):
    """#413：前缀密令只暂存候选；正式 commit 时才建密令并 refresh 承办大臣 agent。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    refreshed = []
    registry = SimpleNamespace(refresh=lambda name: refreshed.append(name))
    s = _session(db, state, registry=registry)
    who = "测试承办官F3"

    def fake_agy(prompt):
        if "臣领旨二" in prompt:
            content = "改查甲；臣领旨二。"
        else:
            content = "查甲；臣领旨一。"
        return (json.dumps({"标题": "查甲", "内容": content, "承办人": who,
                            "期限月数": 0, "标签": []}, ensure_ascii=False), 1)
    monkeypatch.setattr(cb, "_run_agy", fake_agy)

    r1 = _result(); r1.answer = "臣领旨一。"
    s._cli_backend_fallback_actions(r1, SimpleNamespace(name=who, office_type="兵部"), "密令如下：查甲")
    assert r1.secret_order_id is None
    assert r1.pending_action_id

    r2 = _result(); r2.answer = "臣领旨二。"
    s._cli_backend_fallback_actions(r2, SimpleNamespace(name=who, office_type="兵部"), "密令如下：改查甲")
    assert r2.secret_order_id is None
    assert r2.pending_action_id
    assert db.list_secret_orders() == []
    db.commit_pending_actions(state, registry=registry)
    cnt = db.conn.execute(
        "SELECT COUNT(*) FROM secret_orders WHERE minister_name=? AND status='active'", (who,)
    ).fetchone()[0]
    assert cnt == 2
    contents = {
        r["content"] for r in db.conn.execute(
            "SELECT content FROM secret_orders WHERE minister_name=? AND status='active'", (who,)
        ).fetchall()
    }
    assert contents == {"查甲；臣领旨一。", "改查甲；臣领旨二。"}
    assert refreshed.count(who) == 2


def test_existing_directive_not_overwritten(read_game, monkeypatch):
    """agno 工具已产 directive 时，胶水不重复入档（result.proposed_directive 非空）。"""
    db, state, _ = read_game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    _no_conv_action(monkeypatch)
    sentinel = SimpleNamespace(id=999, text="原工具产出", status="draft")
    result = _result()
    result.answer = "臣另拟一道。钦此。"
    result.proposed_directive = sentinel
    _session(db, state)._cli_backend_fallback_actions(
        result, SimpleNamespace(name="毕自严", office_type="户部"), "拟旨如下：发三万两")
    assert result.proposed_directive is sentinel    # 不被覆盖


# ── codexC-1：会话动作（非前缀）必须经 session 路径落地，不再只在 web 有 ──

def test_conversation_update_lands_via_session_path(game, monkeypatch):
    """无前缀、口头说『更新密令』→ session 路径(apply_cli_conversation_actions)把更新进 pending 暂存,
    颁诏 commit 才落真实表(ADR 0006 动作闸门);召对当场不直写、不丢动作。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    who = "会话动作承办官"
    oid = db.create_secret_order(state, who, "原标题", "原内容", ["甲"], deadline_months=0)
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
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    who = "长回话承办官"
    oid = db.create_secret_order(state, who, "查核边饷", "逐项查核", [])
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
    oid = db.create_secret_order(state, who, "原标题", "原内容", [], deadline_months=0)

    def reply_aware_extract(player_message, reply, active, is_consort, llm_config=None):
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
    oid = db.create_secret_order(state, who, "原标题", "原内容", [], deadline_months=0)
    calls = []
    canned = json.dumps({
        "密令动作": "更新",
        "目标密令编号": oid,
        "新标题": "改后标题",
        "新内容": "改后内容",
        "期限月数": 0,
    }, ensure_ascii=False)

    def fake_codex(prompt, model=None, timeout=None, **kwargs):
        calls.append(("codex", model, timeout))
        return canned, 1

    def fake_agy(prompt, timeout=None):
        calls.append(("agy", timeout))
        raise RuntimeError("agy should not be used")

    monkeypatch.setattr(cb, "_run_codex", fake_codex)
    monkeypatch.setattr(cb, "_run_agy", fake_agy)
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
    assert calls == [("codex", "gpt-5.5", 240)]
    # 动作闸门：暂存,颁诏 commit 才落库(不在召对当场直写)
    assert res["secret_order_id"] is None
    assert res.get("pending_action_id")
    assert db.conn.execute(
        "SELECT content FROM secret_orders WHERE id=?", (oid,)).fetchone()["content"] == "原内容"
    db.commit_pending_actions(state)
    assert db.conn.execute(
        "SELECT content FROM secret_orders WHERE id=?", (oid,)).fetchone()["content"] == "改后内容"


def test_conversation_rush_skips_pending_review(game, monkeypatch):
    """催办目标恰为 pending_review 时不抛错、不误置成功（target_active 守门）。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    who = "待核承办官"
    oid = db.create_secret_order(state, who, "待核令", "内容", [], deadline_months=6)
    db.submit_secret_order_for_review(oid, "已呈核", state.year, state.period)  # → pending_review
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
    assert res["secret_order_id"] is None        # pending_review 不被催办，不抛错
    row = db.conn.execute("SELECT status FROM secret_orders WHERE id=?", (oid,)).fetchone()
    assert row["status"] == "pending_review"     # 状态未被动
