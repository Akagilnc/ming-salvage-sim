from __future__ import annotations

import json
import threading
import time
import types
from types import SimpleNamespace

import ming_sim.cli_backend as cb
from ming_sim.exceptions import LLMUnavailable
from ming_sim.session import GameSession
from ming_sim.skills import bind_content as bind_skills_content
from web_app import WebGame


class RunContent:
    event = "RunContent"

    def __init__(self, content: str) -> None:
        self.content = content


class RunOutput:
    def __init__(self, tools=None) -> None:
        self.tools = tools or []
        self.content = None


class ToolExec:
    def __init__(self, tool_name: str, result: str) -> None:
        self.tool_name = tool_name
        self.result = result


class _FakeAgent:
    def __init__(self, tools=None, chunks=None) -> None:
        self.completed = threading.Event()
        self.tools = tools or []
        self.chunks = chunks or ["臣", "遵旨。"]
        self.calls = []

    def run(self, *_args, **_kwargs):
        self.calls.append((_args, _kwargs))
        for chunk in self.chunks:
            yield RunContent(chunk)
        self.completed.set()
        yield RunOutput(self.tools)


class _EmptyAgent(_FakeAgent):
    def run(self, *_args, **_kwargs):
        self.completed.set()
        yield RunOutput()


class _FakeRegistry:
    def __init__(self, agent: _FakeAgent) -> None:
        self.agent = agent
        self.session_ids = {}

    def get(self, _character):
        return self.agent

    def refresh(self, _name):
        return None


class _FakeSession:
    def __init__(self, db, state, content, agent: _FakeAgent) -> None:
        self.db = db
        self.state = state
        self.content = content
        self.registry = _FakeRegistry(agent)
        self.temporary_characters = set()
        self.llm_config = SimpleNamespace(channel="api")

    def _character(self, minister_name: str):
        return self.content.characters[minister_name]

    def _start_cli_action_intent(self, _character, _message):
        return None

    def _finish_cli_action_intent(self, _future):
        return None

    def _confirmation_intent_for_preexisting_pending(self, *args, **kwargs):
        return GameSession._confirmation_intent_for_preexisting_pending(self, *args, **kwargs)

    def _stage_appointment_candidate(self, *args, **kwargs):
        return GameSession._stage_appointment_candidate(self, *args, **kwargs)

    def _merge_staged_new_secret_order_content(self, *args, **kwargs):
        return GameSession._merge_staged_new_secret_order_content(self, *args, **kwargs)

    def _audience_prompt_for_message(self, message):
        return f"【增强上下文】{message}"

    def apply_cli_conversation_actions(self, *_args, **_kwargs):
        return {"directive": None, "secret_order_id": None, "pending_action_id": 0}

    def pending_count(self) -> int:
        return 0

    def note_chat_rollback(self, **_kwargs):
        return None

    def refresh_runtime_after_chat_rollback(self):
        return None


def _web_game(db, state, content, agent: _FakeAgent) -> WebGame:
    bind_skills_content(content)
    game = WebGame.__new__(WebGame)
    game.session = _FakeSession(db, state, content, agent)
    game.chat_history = {name: [] for name in content.characters}
    game.suggestions_for = lambda _character: []
    # The production lifecycle waits on this condition before closing its
    # shared DB.  Keep observer-departure tests on the same boundary so a
    # daemon worker cannot outlive the fixture and touch a closed connection.
    game._drain_cond = threading.Condition()
    game._pending_writes_count = 0
    game._draining = False
    return game


def _wait_for(predicate, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _wait_for_pending_writes_to_drain(web_game: WebGame) -> None:
    with web_game._drain_cond:
        web_game._drain_cond.wait_for(
            lambda: web_game._pending_writes_count == 0
        )


def _assert_next_accepted(stream) -> None:
    accepted = next(stream)
    assert isinstance(accepted, dict)
    assert accepted["type"] == "accepted"
    assert isinstance(accepted["campaign_id"], str)
    assert isinstance(accepted["night_id"], int)
    assert accepted["night_id"] > 0
    assert isinstance(accepted["chat_turn_id"], int)
    assert accepted["chat_turn_id"] > 0


def test_chat_stream_observer_departure_after_acceptance_still_completes_turn(game):
    db, state, content = game
    minister_name = "毕自严"
    agent = _FakeAgent()
    web_game = _web_game(db, state, content, agent)

    stream = web_game.chat_stream(minister_name, "户部钱粮如何？")
    _assert_next_accepted(stream)
    assert next(stream) == {"type": "delta", "content": "臣"}

    stream.close()

    assert agent.completed.wait(1.0), "后台召对应在观察者离开后继续跑完 LLM 流"
    assert _wait_for(lambda: len(web_game.chat_history[minister_name]) >= 2)
    assert web_game.chat_history[minister_name] == [
        {"role": "user", "content": "户部钱粮如何？"},
        {"role": "minister", "content": "臣遵旨。"},
    ]
    assert db.can_undo_last_chat_turn(minister_name, state.turn)
    # fixture 关闭共享 DB 前必须等后台 worker 的 finally 完整结束。
    _wait_for_pending_writes_to_drain(web_game)


def test_chat_reload_exposes_retryable_failed_secret_order(game):
    db, state, content = game
    minister_name = "毕自严"
    web_game = _web_game(db, state, content, _FakeAgent())
    secret_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister_name, target_id=None,
        payload={"title": "暗查辽饷", "content": "密查辽饷去向", "assignee": minister_name},
    )
    db.stage_pending_action(
        state.turn, kind="office", action="任命", minister_name=minister_name, target_id=None,
        payload={"name": "测试新臣", "office": "太常寺卿"},
    )
    db.conn.execute("UPDATE pending_actions SET status='failed'")
    db.conn.commit()

    failures = web_game.pending_action_failures_for(minister_name)

    assert len(failures) == 1
    assert failures[0]["id"] == secret_id
    assert failures[0]["kind"] == "secret_order"
    assert "密令" in failures[0]["message"]


def test_undo_chat_response_preserves_retryable_failed_secret_order(game):
    db, state, content = game
    minister_name = "毕自严"
    web_game = _web_game(db, state, content, _FakeAgent())
    failed_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister_name, target_id=None,
        payload={"title": "暗查辽饷", "content": "密查辽饷去向", "assignee": minister_name},
    )
    db.conn.execute("UPDATE pending_actions SET status='failed' WHERE id=?", (failed_id,))
    db.conn.commit()
    chat_turn_id = db.create_chat_turn(state, minister_name, "undo-failure-refresh", 0)
    db.update_chat_turn_messages(
        chat_turn_id,
        db.append_chat_message(minister_name, state.turn, "user", "无关问话"),
        db.append_chat_message(minister_name, state.turn, "minister", "臣谨奏。"),
    )
    assert db.can_undo_last_chat_turn(minister_name, state.turn)

    out = web_game.undo_last_chat(minister_name)

    failures = out["pending_action_failures"]
    assert [f["id"] for f in failures] == [failed_id]
    assert "密令" in failures[0]["message"]


def test_background_audience_reply_keeps_staged_edict_after_observer_departure(game):
    db, state, content = game
    minister_name = "毕自严"
    draft_text = "着户部清核辽饷。"
    agent = _FakeAgent([ToolExec("propose_directive", f"__pending_directive__{draft_text}")])
    web_game = _web_game(db, state, content, agent)

    stream = web_game.chat_stream(minister_name, "拟一道清核辽饷的旨。")
    _assert_next_accepted(stream)
    assert next(stream)["type"] == "delta"
    stream.close()

    assert agent.completed.wait(1.0)
    assert _wait_for(lambda: any(
        row["kind"] == "directive"
        and json.loads(row["payload_json"])["text"] == draft_text
        for row in db.list_pending_actions(state.turn)
    ))
    assert not any(
        row["text"] == draft_text
        for row in db.list_directives(state, statuses=("pending", "draft"))
    )
    assert _wait_for(lambda: db.can_undo_last_chat_turn(minister_name, state.turn))
    _wait_for_pending_writes_to_drain(web_game)


def test_stream_tool_staged_secret_order_merges_minister_reply(game):
    """#413/#405：web streaming tool-call 新密令也要保留玩家任务 + 大臣补充正文。"""
    db, state, content = game
    minister_name = "毕自严"
    tool_payload = json.dumps({
        "title": "密查辽饷",
        "content": "密查辽饷去向。",
        "assignee": minister_name,
        "tags": ["辽饷"],
        "deadline_months": 3,
    }, ensure_ascii=False)
    agent = _FakeAgent(
        [ToolExec("issue_secret_order", f"__secret_order__{tool_payload}")],
        chunks=["臣当", "先封存兵部辽饷册，再密访关宁诸将。"],
    )
    web_game = _web_game(db, state, content, agent)

    payload = web_game._chat_stream_payload(
        minister_name,
        "密令如下：密查辽饷去向，三月内回奏，不可声张。",
        chat_turn_id=0,
        before_snapshot={},
        accepted_turn=state.turn,
        emit_delta=lambda _chunk: None,
    )

    pending = db.list_pending_actions(state.turn)
    assert len(pending) == 1
    assert payload["pending_action_id"] == pending[0]["id"]
    staged = json.loads(pending[0]["payload_json"])
    assert "密查辽饷去向" in staged["content"]
    assert "三月内回奏" in staged["content"]
    assert "不可声张" in staged["content"]
    assert "封存兵部辽饷册" in staged["content"]


def test_stream_confirmation_ignores_same_turn_secret_order_tool_output(game, monkeypatch):
    """streaming 路径确认旧 pending 时，也不能把同轮 tool sentinel 留成新 pending。"""
    db, state, content = game
    minister_name = "毕自严"
    db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=minister_name, target_id=None,
        payload={
            "title": "旧候选",
            "content": "旧候选内容",
            "assignee": minister_name,
            "tags": [],
            "deadline_months": 0,
        },
    )
    tool_payload = json.dumps({
        "title": "同句新令",
        "content": "同句新令内容",
        "assignee": minister_name,
        "tags": [],
        "deadline_months": 0,
    }, ensure_ascii=False)
    monkeypatch.setattr(
        cb,
        "_run_api_for_config",
        lambda *a, **k: (json.dumps({"确认": "应允"}, ensure_ascii=False), 1),
    )
    agent = _FakeAgent(
        [ToolExec("secret_order", f"__secret_order__{tool_payload}")],
        chunks=["臣", "遵旨。"],
    )
    web_game = _web_game(db, state, content, agent)
    web_game.session.apply_cli_conversation_actions = types.MethodType(
        GameSession.apply_cli_conversation_actions, web_game.session)

    payload = web_game._chat_stream_payload(
        minister_name,
        "准了",
        chat_turn_id=0,
        before_snapshot={},
        accepted_turn=state.turn,
        emit_delta=lambda _chunk: None,
    )

    assert payload["pending_action_id"] == 0
    orders = db.list_secret_orders()
    assert len(orders) == 1
    assert orders[0]["title"] == "旧候选"
    assert db.list_pending_actions(state.turn) == []


def test_stream_secret_order_tool_blocked_in_recovery_window(game):
    """FRONT_HALF_DONE 恢复窗内，streaming tool sentinel 不得新 stage 密令。"""
    from ming_sim.models import TurnPhase

    db, state, content = game
    state.turn_phase = TurnPhase.SETTLING.value
    minister_name = "毕自严"
    tool_payload = json.dumps({
        "title": "恢复窗新令",
        "content": "恢复窗不应暂存。",
        "assignee": minister_name,
        "tags": [],
        "deadline_months": 0,
    }, ensure_ascii=False)
    web_game = _web_game(
        db,
        state,
        content,
        _FakeAgent([ToolExec("secret_order", f"__secret_order__{tool_payload}")]),
    )

    payload = web_game._chat_stream_payload(
        minister_name,
        "密令如下：恢复窗新令",
        chat_turn_id=0,
        before_snapshot={},
        accepted_turn=state.turn,
        emit_delta=lambda _chunk: None,
    )

    assert payload["pending_action_id"] == 0
    assert db.list_pending_actions(state.turn) == []


def test_stream_secret_order_plain_tool_result_does_not_stage_empty_candidate(game):
    """secret_order 工具的普通查询文本不是 sentinel，stream 路不得误建空 pending 新密令。"""
    db, state, content = game
    minister_name = "毕自严"
    agent = _FakeAgent([ToolExec("secret_order", "密令 #1 状态：active。")])
    web_game = _web_game(db, state, content, agent)

    payload = web_game._chat_stream_payload(
        minister_name,
        "查一下密令进展。",
        chat_turn_id=0,
        before_snapshot={},
        accepted_turn=state.turn,
        emit_delta=lambda _chunk: None,
    )

    assert payload["pending_action_id"] == 0
    assert db.list_pending_actions(state.turn) == []


def test_chat_stream_uses_session_augmented_audience_prompt(game):
    """web streaming 应与非流式召对一样把记忆/草案增强 prompt 送给大臣 agent。"""
    db, state, content = game
    minister_name = "毕自严"
    agent = _FakeAgent()
    web_game = _web_game(db, state, content, agent)

    web_game._chat_stream_payload(
        minister_name,
        "辽饷近况如何？",
        chat_turn_id=0,
        before_snapshot={},
        accepted_turn=state.turn,
        emit_delta=lambda _chunk: None,
    )

    assert agent.calls[0][0][0] == "【增强上下文】辽饷近况如何？"


def test_audience_prompt_does_not_expose_unissued_draft_to_uninvolved_minister(game):
    """未明发草案不应绕过见闻投影，注入未参与大臣的召对提示。"""
    db, state, content = game
    minister = next(iter(content.characters.values()))
    session = SimpleNamespace(
        db=db,
        state=state,
        registry=SimpleNamespace(build_draft_line=lambda: "#1 着户部清核辽饷。"),
    )

    prompt = GameSession._audience_prompt_for_message(
        session, "辽饷近况如何？", minister
    )

    assert "着户部清核辽饷" not in prompt


def test_audience_prompt_projects_return_report_with_derived_source(game, monkeypatch):
    """回奏进入该角色知识投影，查访问题不能被生产编排伪装成见闻。"""
    db, state, content = game
    minister = content.characters["王承恩"]
    calls = []
    original = db.build_return_report

    def build_report(query, **kwargs):
        calls.append(kwargs.get("source_kind"))
        return original(query, **kwargs)

    monkeypatch.setattr(db, "build_return_report", build_report)
    session = SimpleNamespace(db=db, state=state)

    prompt = GameSession._audience_prompt_for_message(session, "请查访各镇欠饷如何？", minister)

    assert calls == ["inquiry"]
    assert "近臣查访" in prompt
    assert "军队警讯" in prompt


def test_audience_prompt_does_not_create_near_minister_report_for_ordinary_minister(game):
    db, state, content = game
    minister = next(
        character for character in content.characters.values()
        if character.office_type not in {"司礼监", "内廷"}
        and "太监" not in character.office
    )
    session = SimpleNamespace(db=db, state=state)

    GameSession._audience_prompt_for_message(session, "请查访各镇欠饷如何？", minister)

    assert not any(
        item.get("source_id", "").startswith("near_minister:")
        for item in db.get_character_knowledge(state, minister.name)["events"]
    )


class _CliActionSession(_FakeSession):
    """CLI 路召对：动作经 apply_cli_conversation_actions 落地（密令/pending_action）。"""

    def __init__(self, db, state, content, agent, *, secret_order_id=0, pending_action_id=0):
        super().__init__(db, state, content, agent)
        self._secret_order_id = secret_order_id
        self._pending_action_id = pending_action_id
        self.apply_calls = []

    def apply_cli_conversation_actions(self, *_args, **_kwargs):
        self.apply_calls.append((_args, _kwargs))
        return {
            "directive": None,
            "secret_order_id": self._secret_order_id,
            "pending_action_id": self._pending_action_id,
        }


def _cli_web_game(db, state, content, agent, **kwargs) -> WebGame:
    bind_skills_content(content)
    game = WebGame.__new__(WebGame)
    game.session = _CliActionSession(db, state, content, agent, **kwargs)
    game.chat_history = {name: [] for name in content.characters}
    game.suggestions_for = lambda _character: []
    game._drain_cond = threading.Condition()
    game._pending_writes_count = 0
    game._draining = False
    return game


def test_background_audience_secret_order_persists_after_observer_departure(game):
    """密令结果：退出观看窗后，后台仍跑完 CLI 动作落地（apply_cli_conversation_actions）
    并完成回话入档（#383 US5）。"""
    db, state, content = game
    minister_name = "毕自严"
    agent = _FakeAgent()
    web_game = _cli_web_game(db, state, content, agent, secret_order_id=4242)

    stream = web_game.chat_stream(minister_name, "密查盐政亏空。")
    _assert_next_accepted(stream)
    assert next(stream)["type"] == "delta"
    stream.close()

    assert agent.completed.wait(1.0)
    # 后台跑完：CLI 动作落地真源被调用 + 大臣回话入档（apply 在 _chat_payload 前）
    assert _wait_for(lambda: len(web_game.session.apply_calls) >= 1)
    assert _wait_for(lambda: len(web_game.chat_history[minister_name]) >= 2)
    assert db.can_undo_last_chat_turn(minister_name, state.turn)
    _wait_for_pending_writes_to_drain(web_game)


def test_background_audience_pending_action_persists_after_observer_departure(game):
    """pending_action（如调教/任免暂存）：退出后后台仍跑完落地（#383 US6）。"""
    db, state, content = game
    minister_name = "毕自严"
    agent = _FakeAgent()
    web_game = _cli_web_game(db, state, content, agent, pending_action_id=77)

    stream = web_game.chat_stream(minister_name, "着王承恩调教自省。")
    _assert_next_accepted(stream)
    assert next(stream)["type"] == "delta"
    stream.close()

    assert agent.completed.wait(1.0)
    assert _wait_for(lambda: len(web_game.session.apply_calls) >= 1)
    assert _wait_for(lambda: len(web_game.chat_history[minister_name]) >= 2)
    assert db.can_undo_last_chat_turn(minister_name, state.turn)
    _wait_for_pending_writes_to_drain(web_game)


def test_background_audience_appointment_stages_after_observer_departure(game):
    """任免工具路也必须先进 pending_actions，退出后后台跑完只暂存不直写真实表。"""
    db, state, content = game
    minister_name = "毕自严"
    appointee = "工具候选甲"
    agent = _FakeAgent([
        ToolExec(
            "propose_appointment",
            "__pending_appointment__" + json.dumps(
                {"name": appointee, "office": "户部尚书", "action": "任命"},
                ensure_ascii=False,
            ),
        )
    ])
    web_game = _web_game(db, state, content, agent)

    stream = web_game.chat_stream(minister_name, "拟以工具候选甲为户部尚书。")
    _assert_next_accepted(stream)
    assert next(stream)["type"] == "delta"
    stream.close()

    assert agent.completed.wait(1.0)
    # 后台跑完：只暂存任免候选，等待皇帝确认/颁诏，不绕过确认闸门。
    assert _wait_for(lambda: len(db.list_pending_actions(state.turn)) == 1)
    pending = db.list_pending_actions(state.turn)[0]
    assert pending["kind"] == "office"
    assert pending["action"] == "任命"
    payload = json.loads(pending["payload_json"])
    assert payload["name"] == appointee
    assert payload["office"] == "户部尚书"
    assert db.conn.execute(
        "SELECT name FROM characters WHERE name=?", (appointee,)
    ).fetchone() is None
    assert _wait_for(lambda: len(web_game.chat_history[minister_name]) >= 2)
    assert db.can_undo_last_chat_turn(minister_name, state.turn)
    _wait_for_pending_writes_to_drain(web_game)


def test_background_audience_recommendation_stages_candidate_snapshot(game, monkeypatch):
    """真实 CLI Agent 流式荐人进入 web pending，envelope 不泄漏给玩家。"""
    from agno.agent import Agent

    from ming_sim.models import CourtContext
    from ming_sim.tools import build_minister_tools

    db, state, content = game
    minister_name = "毕自严"
    candidate = db.list_recommendation_candidates(state, minister_name)[0]
    model = cb.CliChat(id="test-stream-recommendation", backend="codex")
    calls = iter((
        [
            "臣荐",
            candidate["name"],
            "。[[recomm",
            "end_person:"
            + json.dumps({
                "name": candidate["name"],
                "target_office": "巡盐御史",
                "reason": "可堪任事",
            }, ensure_ascii=False)
            + "]]",
        ],
        ["臣荐此人巡盐，请陛下裁夺。"],
    ))
    monkeypatch.setattr(cb, "_iter_codex_stream_chunks", lambda *_args, **_kwargs: iter(next(calls)))
    agent = Agent(
        name=minister_name,
        model=model,
        tools=build_minister_tools(
            content.characters[minister_name], CourtContext(state=state, db=db),
        ),
        markdown=False,
    )
    web_game = _web_game(db, state, content, agent)

    events = list(web_game.chat_stream(minister_name, "可荐何人巡盐？"))

    player_text = "".join(event.get("content", "") for event in events if event["type"] == "delta")
    assert "[[recommend_person:" not in player_text
    assert len(db.list_pending_actions(state.turn)) == 1
    staged = json.loads(db.list_pending_actions(state.turn)[0]["payload_json"])
    assert staged["recommendation"]["recommender"] == minister_name
    assert staged["recommendation"]["candidate"]["name"] == candidate["name"]
    assert staged["office"] == "巡盐御史"


def test_llm_failure_does_not_leave_half_chat_in_history(game):
    db, state, content = game
    minister_name = "毕自严"
    agent = _EmptyAgent()
    web_game = _web_game(db, state, content, agent)

    events = list(web_game.chat_stream(minister_name, "户部钱粮如何？"))

    assert events[-1]["type"] == "error"
    assert web_game.chat_history[minister_name] == []
    assert db.conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 0
    row = db.conn.execute("SELECT status FROM chat_turns").fetchone()
    assert row["status"] == "failed"


class _RaisingActionSession(_FakeSession):
    """落地阶段（apply_cli_conversation_actions）在动作已写入后抛错。"""

    def apply_cli_conversation_actions(self, *_args, **_kwargs):
        raise RuntimeError("落地阶段失败")


def test_background_audience_failure_after_action_rolls_back_cleanly(game):
    """#383 US8 + Testing Decisions「失败清理」：拟旨已写入后落地失败 → 失败路径须回滚
    已写动作（不留不可撤回的半成品政务结果）、删半截聊天、标 turn failed。与「退出≠取消」
    的后台完成路明确分开（真后端错误才走失败）。"""
    db, state, content = game
    minister_name = "毕自严"
    draft_text = "着户部清核辽饷。"
    agent = _FakeAgent([ToolExec("propose_directive", f"__pending_directive__{draft_text}")])
    bind_skills_content(content)
    web_game = WebGame.__new__(WebGame)
    web_game.session = _RaisingActionSession(db, state, content, agent)
    web_game.chat_history = {name: [] for name in content.characters}
    web_game.suggestions_for = lambda _character: []

    events = list(web_game.chat_stream(minister_name, "拟一道清核辽饷的旨。"))

    assert events[-1]["type"] == "error"
    # 已暂存的拟旨被回滚——不留不可撤回的半成品政务结果
    assert not any(
        row["kind"] == "directive"
        and json.loads(row["payload_json"])["text"] == draft_text
        for row in db.list_pending_actions(state.turn)
    )
    assert not any(
        row["text"] == draft_text
        for row in db.list_directives(state, statuses=("pending", "draft"))
    )
    # 半截聊天被清，turn 标 failed
    assert web_game.chat_history[minister_name] == []
    assert db.conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 0
    assert db.conn.execute("SELECT status FROM chat_turns").fetchone()["status"] == "failed"


def test_chat_stream_rejects_second_concurrent_turn_same_minister(game):
    """#383 Out of Scope「不允许同大臣并发未答 turn」+ integrated cmr Gate2 P1（Claude+codex×2
    一致）：同一大臣已有 in-flight（status='active' 且 minister_message_id 空）turn 时，再开流式
    召对必须被服务端拒掉、不创建第二个并发 turn——否则两个后台 worker 竞写同一 SQLite 连接
    （ADR0008 单写者不变式）且历史错序。可达路径：离开实时流（前端 busy 清）→ 重开 → 再问。"""
    db, state, content = game
    minister_name = "毕自严"
    agent = _FakeAgent()
    web_game = _web_game(db, state, content, agent)

    # 预置一个 in-flight turn（已受理、minister_message_id 仍空 = 后台仍在回奏）
    db.create_chat_turn(state, minister_name, "sess-inflight", 0)
    turns_before = db.conn.execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0]

    events = list(web_game.chat_stream(minister_name, "再问一句。"))

    assert events[-1]["type"] == "error"
    assert "仍在进行" in str(events[-1].get("message", ""))
    # 未创建第二个并发 turn
    assert db.conn.execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0] == turns_before
    # 一个完成的（可撤回）turn 不算 in-flight：写入 minister_message_id 后应放行新问
    db.update_chat_turn_messages(
        db.get_last_active_chat_turn(minister_name, state.turn)["id"], minister_message_id=999)
    assert web_game._audience_turn_in_flight(minister_name) is False


def test_chat_stream_closed_before_turn_creation_is_noop(read_game):
    """#383 Testing Decisions「turn 创建前 vs 创建后边界」的创建前半：观察者在生成器首次
    迭代前就离开（close 未 next）→ no-op，不留 chat_turns / chat_messages。turn 创建（首次
    迭代）后才进入「退出≠取消」语义，由 observer-departure 测试覆盖创建后半。"""
    db, state, content = read_game
    minister_name = "毕自严"
    agent = _FakeAgent()
    web_game = _web_game(db, state, content, agent)

    turns_before = db.conn.execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0]
    msgs_before = db.conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]

    stream = web_game.chat_stream(minister_name, "户部钱粮如何？")
    stream.close()  # 首次迭代前离开 → 生成器体从未执行 → turn 未创建

    assert db.conn.execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0] == turns_before
    assert db.conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == msgs_before
    assert web_game.chat_history[minister_name] == []
