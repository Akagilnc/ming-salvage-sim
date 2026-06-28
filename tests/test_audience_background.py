from __future__ import annotations

import json
import threading
import time

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

    def run(self, *_args, **_kwargs):
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


class _FakeSession:
    def __init__(self, db, state, content, agent: _FakeAgent) -> None:
        self.db = db
        self.state = state
        self.content = content
        self.registry = _FakeRegistry(agent)
        self.temporary_characters = set()

    def _character(self, minister_name: str):
        return self.content.characters[minister_name]

    def _start_cli_action_intent(self, _character, _message):
        return None

    def _finish_cli_action_intent(self, _future):
        return None

    def apply_cli_conversation_actions(self, *_args, **_kwargs):
        return {"directive": None, "secret_order_id": None, "pending_action_id": 0}

    def pending_count(self) -> int:
        return 0


def _web_game(db, state, content, agent: _FakeAgent) -> WebGame:
    bind_skills_content(content)
    game = WebGame.__new__(WebGame)
    game.session = _FakeSession(db, state, content, agent)
    game.chat_history = {name: [] for name in content.characters}
    game.suggestions_for = lambda _character: []
    return game


def _wait_for(predicate, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_chat_stream_observer_departure_after_acceptance_still_completes_turn(game):
    db, state, content = game
    minister_name = "毕自严"
    agent = _FakeAgent()
    web_game = _web_game(db, state, content, agent)

    stream = web_game.chat_stream(minister_name, "户部钱粮如何？")
    assert next(stream) == {"type": "delta", "content": "臣"}

    stream.close()

    assert agent.completed.wait(1.0), "后台召对应在观察者离开后继续跑完 LLM 流"
    assert _wait_for(lambda: len(web_game.chat_history[minister_name]) >= 2)
    assert web_game.chat_history[minister_name] == [
        {"role": "user", "content": "户部钱粮如何？"},
        {"role": "minister", "content": "臣遵旨。"},
    ]
    assert db.can_undo_last_chat_turn(minister_name, state.turn)


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


def test_background_audience_reply_keeps_staged_edict_after_observer_departure(game):
    db, state, content = game
    minister_name = "毕自严"
    draft_text = "着户部清核辽饷。"
    agent = _FakeAgent([ToolExec("propose_directive", f"__pending_directive__{draft_text}")])
    web_game = _web_game(db, state, content, agent)

    stream = web_game.chat_stream(minister_name, "拟一道清核辽饷的旨。")
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
    return game


def test_background_audience_secret_order_persists_after_observer_departure(game):
    """密令结果：退出观看窗后，后台仍跑完 CLI 动作落地（apply_cli_conversation_actions）
    并完成回话入档（#383 US5）。"""
    db, state, content = game
    minister_name = "毕自严"
    agent = _FakeAgent()
    web_game = _cli_web_game(db, state, content, agent, secret_order_id=4242)

    stream = web_game.chat_stream(minister_name, "密查盐政亏空。")
    assert next(stream)["type"] == "delta"
    stream.close()

    assert agent.completed.wait(1.0)
    # 后台跑完：CLI 动作落地真源被调用 + 大臣回话入档（apply 在 _chat_payload 前）
    assert _wait_for(lambda: len(web_game.session.apply_calls) >= 1)
    assert _wait_for(lambda: len(web_game.chat_history[minister_name]) >= 2)
    assert db.can_undo_last_chat_turn(minister_name, state.turn)


def test_background_audience_pending_action_persists_after_observer_departure(game):
    """pending_action（如调教/任免暂存）：退出后后台仍跑完落地（#383 US6）。"""
    db, state, content = game
    minister_name = "毕自严"
    agent = _FakeAgent()
    web_game = _cli_web_game(db, state, content, agent, pending_action_id=77)

    stream = web_game.chat_stream(minister_name, "着王承恩调教自省。")
    assert next(stream)["type"] == "delta"
    stream.close()

    assert agent.completed.wait(1.0)
    assert _wait_for(lambda: len(web_game.session.apply_calls) >= 1)
    assert _wait_for(lambda: len(web_game.chat_history[minister_name]) >= 2)
    assert db.can_undo_last_chat_turn(minister_name, state.turn)


def test_background_audience_appointment_persists_after_observer_departure(game):
    """任免/人员候选（agno propose_appointment 工具路）：退出后后台仍跑完任免落地，
    且回话入档（#383 US6）。"""
    db, state, content = game
    minister_name = "毕自严"
    appointee = "倪元璐"
    agent = _FakeAgent([
        ToolExec(
            "propose_appointment",
            "__pending_appointment__" + json.dumps(
                {"name": appointee, "office": "户部尚书", "action": "任命"},
                ensure_ascii=False,
            ),
        )
    ])
    applied = {}

    web_game = _web_game(db, state, content, agent)

    def _fake_apply_appointment(payload_json, _character):
        applied["payload"] = payload_json
        return (appointee, "")

    web_game.session._apply_appointment = _fake_apply_appointment

    stream = web_game.chat_stream(minister_name, "拟以倪元璐为户部尚书。")
    assert next(stream)["type"] == "delta"
    stream.close()

    assert agent.completed.wait(1.0)
    # 后台跑完：任免落地被调用（人员候选受保护）+ 回话入档
    assert _wait_for(lambda: "payload" in applied)
    assert appointee in applied["payload"]
    assert _wait_for(lambda: len(web_game.chat_history[minister_name]) >= 2)
    assert db.can_undo_last_chat_turn(minister_name, state.turn)


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


def test_chat_stream_closed_before_turn_creation_is_noop(game):
    """#383 Testing Decisions「turn 创建前 vs 创建后边界」的创建前半：观察者在生成器首次
    迭代前就离开（close 未 next）→ no-op，不留 chat_turns / chat_messages。turn 创建（首次
    迭代）后才进入「退出≠取消」语义，由 observer-departure 测试覆盖创建后半。"""
    db, state, content = game
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
