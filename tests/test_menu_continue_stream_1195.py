"""#1195: POST /api/menu/continue 分阶段 SSE 反馈（stage → done/error）。"""
from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

import web_app
from tests.wait_utils import wait_until


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        ev_name = ""
        data_raw = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                ev_name = line[7:].strip()
            elif line.startswith("data: "):
                data_raw += line[6:]
        if not ev_name or not data_raw:
            continue
        events.append((ev_name, json.loads(data_raw)))
    return events


def test_menu_continue_streams_stage_labels_then_done_state(monkeypatch):
    """继续路径：先推阶段文案，再 done 带 state；禁百分比/进度条形态。"""
    stages_from_ctor: list[str] = []

    class FakeWebGame:
        def __init__(self, fresh: bool = False, on_stage=None) -> None:
            assert fresh is False
            # 模拟 WebGame 在既有初始化序上的阶段回调（不改 GameSession 序）。
            # 首条「准备载入上次进度...」由 worker 在构造前入队（#1195/#1228），此处不重复。
            labels = [
                "载入上次进度...",
                "重整朝堂名册...",
                "恢复召对记录...",
            ]
            for label in labels:
                stages_from_ctor.append(label)
                if on_stage:
                    on_stage(label)
            self._state = {"turn": {"turn": 2, "year": 1627, "period": 11}}

        def state_payload(self) -> dict:
            return self._state

    # #1749：隔离前序 exit completion。
    monkeypatch.setattr(web_app, "_menu_exit_detach_completion", None)
    monkeypatch.setattr(web_app, "_has_main_db", lambda: True)
    monkeypatch.setattr(web_app, "WebGame", FakeWebGame)
    monkeypatch.setattr(web_app, "web_game", None)

    response = TestClient(web_app.app).post("/api/menu/continue")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(response.text)
    assert events, "应至少有 SSE 事件"
    kinds = [name for name, _ in events]
    assert kinds[-1] == "done"
    assert "error" not in kinds

    stage_texts = [payload.get("content", "") for name, payload in events if name == "stage"]
    assert stage_texts, "应推送至少一条 stage"
    assert stage_texts[0]  # ≤5s 首条：服务端在重活前即发，可断言非空首条
    assert stage_texts[0] == "准备载入上次进度..."
    # 文案沿用「载入上次进度…」式标签（省略号/叙事），禁百分比/进度条/剩余秒数
    # #1228：不再把「检查」列为合法阶段——构造路径已无后端检查。
    for text in stage_texts:
        assert "检查" not in text
        assert "载入" in text or "重整" in text or "恢复" in text
        assert "%" not in text
        assert "进度条" not in text
        assert not any(ch.isdigit() and "秒" in text for ch in text) or "秒" not in text

    done_payload = events[-1][1]
    assert done_payload["state"]["turn"]["turn"] == 2
    assert web_app.web_game is not None
    assert stages_from_ctor  # ctor 确实走过阶段回调


def test_menu_continue_streams_error_when_llm_unavailable(monkeypatch):
    """LLM 不可用时以 SSE error 收束，不抛成非流响应。"""

    class BoomWebGame:
        def __init__(self, fresh: bool = False, on_stage=None) -> None:
            # 首条 stage 已由 worker 在构造前入队；ctor 内可直接失败。
            raise web_app.LLMUnavailable("未配 API key，请先到设置页填写。")

    monkeypatch.setattr(web_app, "_menu_exit_detach_completion", None)
    monkeypatch.setattr(web_app, "_has_main_db", lambda: True)
    monkeypatch.setattr(web_app, "WebGame", BoomWebGame)
    monkeypatch.setattr(web_app, "web_game", None)

    response = TestClient(web_app.app).post("/api/menu/continue")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(response.text)
    assert events[-1][0] == "error"
    assert "message" in events[-1][1]
    assert web_app.web_game is None


def test_menu_continue_404_when_no_main_db(monkeypatch):
    """无主档时仍同步 404（流开始前即可判定）。"""
    monkeypatch.setattr(web_app, "_has_main_db", lambda: False)
    response = TestClient(web_app.app).post("/api/menu/continue")
    assert response.status_code == 404


def test_stale_continue_worker_does_not_publish_after_exit(monkeypatch):
    """#1195/#1749：取消窗口在构造前——exit-completion 等待窗内被 exit bump → 对号失败，不构造不发布。

    持锁构造期间其它菜单串行；契约取消点是构造前世代对号（非 ctor 中途 SlowWebGame）。
    """
    import asyncio
    import threading

    entered_ctor = threading.Event()
    results: dict = {}

    class TrackingWebGame:
        def __init__(self, fresh: bool = False, on_stage=None) -> None:
            assert fresh is False
            entered_ctor.set()
            self._state = {"from": "stale-continue"}
            self._write_gate = threading.Lock()
            self.session = SimpleNamespace(close=lambda: None)

        def state_payload(self) -> dict:
            return self._state

    stuck = web_app._MenuExitDetachCompletion()
    monkeypatch.setattr(web_app, "_menu_exit_detach_completion", stuck)
    monkeypatch.setattr(web_app, "_has_main_db", lambda: True)
    monkeypatch.setattr(web_app, "WebGame", TrackingWebGame)
    monkeypatch.setattr(web_app, "web_game", None)

    cont_started = threading.Event()
    real_wait = stuck.done.wait

    def wait_mark(timeout=None):
        cont_started.set()
        return real_wait(timeout)

    stuck.done.wait = wait_mark  # type: ignore[method-assign]

    def run_continue() -> None:
        response = TestClient(web_app.app).post("/api/menu/continue")
        results["status"] = response.status_code
        results["events"] = _parse_sse(response.text)

    thread = threading.Thread(target=run_continue, daemon=True)
    thread.start()
    # peek 模型：continue 卡在 stuck.done，completion 仍在全局位
    wait_until(cont_started.is_set)
    assert web_app._menu_exit_detach_completion is stuck

    exit_result = asyncio.run(web_app.api_menu_exit())
    assert exit_result == {"ok": True}
    assert web_app.web_game is None

    stuck.close_ok = True
    stuck.done.set()
    thread.join()
    assert not thread.is_alive(), "continue stream thread hung"
    assert results.get("status") == 200
    events = results["events"]
    assert events and events[-1][0] == "error"
    assert web_app.web_game is None
    assert not entered_ctor.is_set(), "superseded continue must not construct WebGame"


def test_stale_continue_worker_does_not_publish_after_new_game(monkeypatch, tmp_path):
    """#1195/#1749：构造前等待窗内 new_game 已发布 → 世代对号失败不覆盖。"""
    import asyncio
    import threading

    entered_ctor = threading.Event()
    results: dict = {}

    class TrackingWebGame:
        def __init__(self, fresh: bool = False, on_stage=None) -> None:
            assert fresh is False
            entered_ctor.set()
            self._state = {"from": "stale-continue"}
            self._write_gate = threading.Lock()
            self.session = SimpleNamespace(close=lambda: None)

        def state_payload(self) -> dict:
            return self._state

    class FreshWebGame:
        def __init__(self, fresh: bool = True, on_stage=None) -> None:
            assert fresh is True
            self._state = {"from": "new-game"}

        def state_payload(self) -> dict:
            return self._state

    stuck = web_app._MenuExitDetachCompletion()
    monkeypatch.setattr(web_app, "_menu_exit_detach_completion", stuck)
    monkeypatch.setattr(web_app, "_has_main_db", lambda: True)
    monkeypatch.setattr(web_app, "WebGame", TrackingWebGame)
    monkeypatch.setattr(web_app, "web_game", None)
    monkeypatch.delenv("MING_SIM_DB", raising=False)
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    monkeypatch.setattr(web_app.steam_events, "with_events", lambda payload, events: payload)

    cont_started = threading.Event()
    real_wait = stuck.done.wait

    def wait_mark(timeout=None):
        cont_started.set()
        return real_wait(timeout)

    stuck.done.wait = wait_mark  # type: ignore[method-assign]

    def run_continue() -> None:
        response = TestClient(web_app.app).post("/api/menu/continue")
        results["status"] = response.status_code
        results["events"] = _parse_sse(response.text)

    thread = threading.Thread(target=run_continue, daemon=True)
    thread.start()
    wait_until(cont_started.is_set)
    assert web_app._menu_exit_detach_completion is stuck

    monkeypatch.setattr(web_app, "WebGame", FreshWebGame)
    new_result = asyncio.run(web_app.api_menu_new_game())
    assert new_result["state"]["from"] == "new-game"
    settled = web_app.web_game
    assert settled is not None and settled.state_payload()["from"] == "new-game"

    stuck.close_ok = True
    stuck.done.set()
    thread.join()
    assert not thread.is_alive()
    assert results.get("status") == 200
    assert results["events"][-1][0] == "error"
    assert web_app.web_game is settled
    assert not entered_ctor.is_set(), "superseded continue must not construct"
