from __future__ import annotations

import json
import threading
from tests.wait_utils import wait_until
import types
from types import SimpleNamespace

import pytest

import ming_sim.cli_backend as cb
from ming_sim.exceptions import LLMUnavailable
from ming_sim.materials import prepare_character_materials
from ming_sim.session import GameSession
from tests.dossier_test_helpers import TYPED_COVERT_TASK
from tests.web_audience_test_doubles import HallAdmissionSessionMixin
from web_app import WebGame
from tests.conftest import (
    stub_audience_translate,
    stub_scene_agent,
)


class RunContent:
    event = "RunContent"

    def __init__(self, content: str) -> None:
        self.content = content


class RunOutput:
    def __init__(self, tools=None) -> None:
        self.tools = tools or []
        self.content = None


class ToolExec:
    def __init__(self, tool_name: str, result: str, arguments=None) -> None:
        self.tool_name = tool_name
        self.result = result
        self.arguments = arguments or {}


class _FakeAgent:
    def __init__(self, tools=None, chunks=None) -> None:
        self.completed = threading.Event()
        self.tools = tools or []
        self.chunks = chunks or ["臣", "遵旨。"]
        self.calls = []

    def run(self, *_args, **_kwargs):
        # 接受 stream/stream_events/yield_run_output（生产 transport 同形），不因旗崩。
        self.calls.append((_args, _kwargs))
        for chunk in self.chunks:
            yield RunContent(chunk)
        self.completed.set()
        yield RunOutput(self.tools)


class _EmptyAgent(_FakeAgent):
    def run(self, *_args, **_kwargs):
        self.completed.set()
        yield RunOutput()


class _FakeSession(HallAdmissionSessionMixin):
    def __init__(self, db, state, content, agent: _FakeAgent) -> None:
        self.db = db
        self.state = state
        self.content = content
        self._fake_scene_agent = agent

        self.llm_config = SimpleNamespace(
            channel="api", base_url="", model="test", api_key="",
            timeout_seconds=30.0, default_headers=None,
        )
        # 高亮离线：禁 FakeSession llm_config 半字段触发真 create_chat_model
        self._write_gate = None
        # 绑生产 scene_chat 及依赖方法（不平行实现 tool 暂存）
        # #1842：WebGame persist 尾必调 schedule_pending_scene_translation——假壳缺绑
        # 会在回话已入档后 AttributeError，失败回滚 history，观察者离开回归永久停车。
        import types as _types
        for _name in (
            "_apply_scene_turn_translation",
            "_run_scene_agent_transport",
            "_recognize_audience_command_verdict",
            "summon_character",
            "schedule_pending_scene_translation",
        ):
            if hasattr(GameSession, _name):
                setattr(self, _name, _types.MethodType(getattr(GameSession, _name), self))
        # scene_chat：基类绑生产；子类（_CliActionSession 等）可覆盖实例方法
        if type(self) is _FakeSession:
            self.scene_chat = _types.MethodType(GameSession.scene_chat, self)
        # admission 放行仍用 HallAdmissionSessionMixin.consume_audience_admission

    def _resolve_scene_agent(self, prepared, *, night_id: int):
        """测试双：读取可替换的场景 agent，以覆盖耗尽后的重发。"""
        del prepared, night_id
        return self._fake_scene_agent

    def _character(self, minister_name: str):
        return self.content.characters[minister_name]

    def pending_count(self) -> int:
        return 0

    def list_directives(self, include_pending: bool = True):
        # WebGame.directive_rows 唯一权威：委托真 GameSession 过滤（含 dossier 剔除）。
        return GameSession.list_directives(self, include_pending=include_pending)

    def close(self):
        # SQLite 由共享 ``game`` fixture 关闭；这里只给生产 drain seam 一个资源终点。
        return None

    def note_chat_rollback(self, **_kwargs):
        return None

    def refresh_runtime_after_chat_rollback(self):
        return None

    def can_summon(self, character):
        # #1402：web _require_active_minister 改调 session.can_summon——假壳挂真方法，禁自造文案表
        return GameSession.can_summon(self, character)


def _web_game(db, state, content, agent: _FakeAgent, monkeypatch=None) -> WebGame:
    game = WebGame.__new__(WebGame)
    game.session = _FakeSession(db, state, content, agent)
    game.chat_history = {name: [] for name in content.characters}
    game.suggestions_for = lambda _character: []
    from ming_sim.session_write_queue import SessionWriteQueue
    game._write_queue = SessionWriteQueue()
    game._write_gate = game._write_queue.write_gate
    # 与生产 WebGame 同形：session._write_gate = queue gate。转译 worker 与
    # chat atomic 须同闸串行，禁分家导致共享 conn 嵌套 BEGIN。
    game.session._write_gate = game._write_gate
    game.session._write_queue = game._write_queue
    from tests.conftest import own_session_until_game_teardown
    own_session_until_game_teardown(db, game.session)
    game._runtime_write_queue = lambda: game._write_queue  # type: ignore
    game._mark_pending_write = lambda key=None: game._write_queue.claim(key=key or ("pending",))  # type: ignore
    game._complete_pending_write = lambda ticket=None: game._write_queue.complete(ticket)  # type: ignore
    # 高亮/尾随离线——禁 FakeSession 半配置触发真 LLM
    game._trail_highlight_judge_after_reply = lambda *a, **k: []  # type: ignore
    game._spawn_pending_write_thread = lambda *a, **k: None  # type: ignore
    if monkeypatch is not None:
        stub_scene_agent(monkeypatch, agent)
        stub_audience_translate(monkeypatch)
    return game


def _wait_for_pending_writes_to_drain(web_game: WebGame) -> None:
    """等本局唯一写队列进入 idle。"""
    q = getattr(web_game, "_write_queue", None)
    if q is not None and hasattr(q, "wait_idle"):
        q.wait_idle()  # unlimited; CI job final line owns hang
    else:
        wait_until(lambda: int(getattr(web_game, "_pending_writes_count", 0) or 0) == 0)


def _assert_next_accepted(stream) -> None:
    accepted = next(stream)
    assert isinstance(accepted, dict)
    assert accepted["type"] == "accepted"
    assert isinstance(accepted["campaign_id"], str)
    assert isinstance(accepted["night_id"], int)
    assert accepted["night_id"] > 0
    assert isinstance(accepted["chat_turn_id"], int)
    assert accepted["chat_turn_id"] > 0




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
        payload={"text": "测试任免原文", "name": "测试新臣", "office": "太常寺卿"},
    )
    db.conn.execute("UPDATE pending_actions SET status='failed'")
    db.conn.commit()

    failures = web_game.pending_action_failures_for(minister_name)

    assert len(failures) == 1
    assert failures[0]["id"] == secret_id
    assert failures[0]["kind"] == "secret_order"
    assert "密令" in failures[0]["message"]




def test_newer_interrupted_turn_blocks_withdrawal_of_completed_turn(game):
    db, state, content = game
    minister_name = "毕自严"
    web_game = _web_game(db, state, content, _FakeAgent())
    completed = db.create_chat_turn(state, minister_name, "completed", 0)
    db.update_chat_turn_messages(
        completed,
        db.append_chat_message(minister_name, state.turn, "user", "前问"),
        db.append_chat_message(minister_name, state.turn, "minister", "前答"),
    )
    interrupted = db.create_chat_turn(state, minister_name, "interrupted", 0)
    db.conn.execute("UPDATE chat_turns SET status='interrupted' WHERE id=?", (interrupted,))
    db.conn.commit()

    assert not web_game.can_undo_last_chat(minister_name)
    with pytest.raises(Exception) as error:
        web_game.undo_last_chat(minister_name)
    assert getattr(error.value, "status_code", None) == 409
    assert db.get_last_active_chat_turn(minister_name, state.turn)["id"] == completed


def test_withdrawal_under_web_write_gate_returns_undone_turn(game):
    db, state, content = game
    minister_name = "毕自严"
    web_game = _web_game(db, state, content, _FakeAgent())
    turn = db.create_chat_turn(state, minister_name, "sess", 0)
    user_id = db.append_chat_message(minister_name, state.turn, "user", "前问")
    db.update_chat_turn_messages(turn, user_message_id=user_id)
    db.persist_minister_reply(minister_name, state.turn, "前答", turn)

    # Web 路由持同一非重入写闸再调撤回；不得在取消转译时二次取闸。
    with web_game._write_gate:
        result = web_game.undo_last_chat(minister_name, gate_held=True)

    assert result["undone_chat_turn_id"] == turn
    assert db.get_last_active_chat_turn(minister_name, state.turn) is None


def test_current_unissued_draft_is_not_character_carryover(game):
    """本回合未明发草案不应绕过见闻投影，注入未参与大臣的召对提示。

    #1769 只放行**跨月**未入档旨稿（上月已随颁诏发出、仅未落档）；本回合刚拟、
    还在御案上的草案仍是密事，不得越过排除边界。
    """
    db, state, _content = game
    db.add_directive(
        state, None, "着户部清核辽饷。", "player-decree-test",
        dossier_payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "liaoxiang-audit", "locality_scope": "none",
        },
    )
    from ming_sim.materials import _carryover_drafts
    assert _carryover_drafts(db, state) == []








def test_chat_stream_closed_before_turn_creation_is_noop(read_game, monkeypatch):

    """#383 Testing Decisions「turn 创建前 vs 创建后边界」的创建前半：观察者在生成器首次
    迭代前就离开（close 未 next）→ no-op，不留 chat_turns / chat_messages。turn 创建（首次
    迭代）后才进入「退出≠取消」语义，由 observer-departure 测试覆盖创建后半。"""
    db, state, content = read_game
    minister_name = "毕自严"
    agent = _FakeAgent()
    web_game = _web_game(db, state, content, agent, monkeypatch)

    turns_before = db.conn.execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0]
    msgs_before = db.conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]

    stream = web_game.chat_stream(minister_name, "户部钱粮如何？")
    stream.close()  # 首次迭代前离开 → 生成器体从未执行 → turn 未创建

    assert db.conn.execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0] == turns_before
    assert db.conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == msgs_before
    assert web_game.chat_history[minister_name] == []
