"""#544 高亮判官管道：同通道后处理 · 清单落库 · 两通道时序 · 静默降级。

票面 AC（冻结 r2）：
- 超时/坏输出 → 无高亮、零报错、回话照常（注入假输出、零真 LLM）
- 清单落库 + restore 后仍在（build_chat_projection / audience_night 卷轴）
- 非流式同到（折等待窗、超时封顶）；流式不挡流、流完补挂
- 慢而成功的判官：流式=回话先显示；非流式=折窗封顶
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

from ming_sim import audience_night as an
from ming_sim.db import GameDB
from ming_sim.highlight_judge import (
    DEFAULT_HIGHLIGHT_JUDGE_TIMEOUT_S,
    parse_highlight_judge_output,
    run_highlight_judge,
)


# ── 解析 / 单次调用降级 ──────────────────────────────────────────────────


def test_parse_highlight_judge_bad_output_is_empty():
    assert parse_highlight_judge_output("") == []
    assert parse_highlight_judge_output("not json") == []
    assert parse_highlight_judge_output('{"highlights": "辽饷"}') == []
    assert parse_highlight_judge_output('{"phrases": ["甲"]}') == []
    assert parse_highlight_judge_output('{"highlights": [1, null, ""]}') == []


def test_parse_highlight_judge_valid_phrases():
    assert parse_highlight_judge_output(
        '```json\n{"highlights": ["**辽饷**", "户部亏空", "  "]}\n```'
    ) == ["**辽饷**", "户部亏空"]


def test_run_highlight_judge_timeout_and_exception_degrade_silently():
    release = threading.Event()

    class _Slow:
        def run(self, *_a, **_k):
            release.wait(timeout=2.0)
            return SimpleNamespace(content='{"highlights": ["迟到"]}')

    class _Boom:
        def run(self, *_a, **_k):
            raise RuntimeError("model down")

    assert run_highlight_judge(
        minister_reply="臣陈辽饷。",
        llm_config=object(),
        agent=_Slow(),
        timeout_s=0.05,
    ) == []
    release.set()

    assert run_highlight_judge(
        minister_reply="臣陈辽饷。",
        llm_config=object(),
        agent=_Boom(),
        timeout_s=1.0,
    ) == []


def test_run_highlight_judge_success_returns_phrases():
    class _Ok:
        def run(self, *_a, **_k):
            return SimpleNamespace(content='{"highlights": ["辽饷", "军心"]}')

    assert run_highlight_judge(
        minister_reply="臣陈**辽饷**与军心。",
        llm_config=object(),
        agent=_Ok(),
        timeout_s=1.0,
    ) == ["辽饷", "军心"]


# ── 落库 + 两读端 + restore ──────────────────────────────────────────────


def _minister_turn(db, state, minister: str, reply: str, night_id: int = 0):
    uid = db.append_chat_message(minister, int(state.turn), "user", "问。")
    mid = db.append_chat_message(minister, int(state.turn), "minister", reply)
    cid = db.create_chat_turn(state, minister, "hl-test", 0, night_id=night_id)
    db.update_chat_turn_messages(cid, user_message_id=uid, minister_message_id=mid)
    return cid, mid


def test_build_chat_projection_includes_minister_highlights(game):
    db, state, _ = game
    minister = "温体仁"
    _cid, mid = _minister_turn(db, state, minister, "臣陈辽饷与户部亏空。")
    db.set_message_highlights(mid, ["辽饷", "户部亏空"])
    # 帝/递话消息不得因列默认而带高亮清单（只标大臣）
    uid_row = db.conn.execute(
        "SELECT id FROM chat_messages WHERE role='user' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert uid_row is not None

    proj = db.build_chat_projection(minister)
    roles = [(m["role"], m.get("highlights")) for m in proj]
    assert ("user", []) in roles or any(r == "user" and h == [] for r, h in roles)
    minister_msgs = [m for m in proj if m["role"] == "minister"]
    assert minister_msgs
    assert minister_msgs[0]["highlights"] == ["辽饷", "户部亏空"]


def test_read_night_scroll_includes_minister_highlights(game):
    db, state, _ = game
    minister = "杨嗣昌"
    night_id = int(an.open_night(db, state, time_of_day="戌时", location="乾清宫")["id"])
    _cid, mid = _minister_turn(
        db, state, minister, "臣请据实核账。", night_id=night_id,
    )
    db.set_message_highlights(mid, ["据实核账"])

    scroll = an.read_night_scroll(db, night_id)
    minister_msgs = [m for m in scroll if m["role"] == "minister"]
    assert minister_msgs
    assert minister_msgs[0]["highlights"] == ["据实核账"]
    # 帝/scene 不带非空高亮
    for m in scroll:
        if m["role"] != "minister":
            assert m.get("highlights") == []


def test_highlights_survive_db_restore(game, content, tmp_path):
    """接口层：落库后重开同档，两读端仍带回清单。"""
    import shutil

    src_db, state, _ = game
    minister = "温体仁"
    night_id = int(an.open_night(src_db, state, time_of_day="午时", location="文华殿")["id"])
    _cid, mid = _minister_turn(
        src_db, state, minister, "臣陈军务与辽饷。", night_id=night_id,
    )
    src_db.set_message_highlights(mid, ["军务", "辽饷"])
    # 不关 fixture 库：checkpoint + 文件拷贝后重开，模拟 restore
    src_db.conn.execute("PRAGMA wal_checkpoint(FULL)")
    copy_path = Path(tmp_path) / "restore-hl.db"
    shutil.copy2(src_db.path, copy_path)

    db2 = GameDB(str(copy_path), content)
    try:
        proj = db2.build_chat_projection(minister, night_id)
        minister_msgs = [m for m in proj if m["role"] == "minister"]
        assert minister_msgs and minister_msgs[0]["highlights"] == ["军务", "辽饷"]
        scroll = an.read_night_scroll(db2, night_id)
        scroll_min = [m for m in scroll if m["role"] == "minister"]
        assert scroll_min and scroll_min[0]["highlights"] == ["军务", "辽饷"]
    finally:
        db2.close()


# ── 通道时序（注入假判官，零真 LLM）────────────────────────────────────


def _patch_mindreading_skip(monkeypatch):
    import web_app as web_app_mod

    monkeypatch.setattr(web_app_mod, "run_mindreading_for_turn", lambda **_k: None)
    # 抽取尾随与本票无关；禁真跑以免 fixture teardown 与后台写竞态
    monkeypatch.setattr(
        web_app_mod, "trail_extraction_after_reply", lambda **_k: None, raising=False,
    )


def _drain(web_game) -> None:
    from tests.test_audience_background import _wait_for_pending_writes_to_drain

    _wait_for_pending_writes_to_drain(web_game)


def test_chat_stream_done_before_highlights_and_degrade(game, monkeypatch):
    """流式：done 先于 highlights；坏输出/超时 → 无高亮事件、回话照常、零上抛。"""
    import web_app as web_app_mod
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    minister = "温体仁"
    web_game = _web_game(db, state, content, _FakeAgent(chunks=["臣", "陈辽饷。"]))
    _patch_mindreading_skip(monkeypatch)

    # run_highlight_judge 契约：失败/超时/坏输出只回 []、不抛（一层边界在其内部）。
    monkeypatch.setattr(web_app_mod, "run_highlight_judge", lambda **_k: [])

    events = list(web_game.chat_stream(minister, "军务如何？"))
    types = [e.get("type") for e in events]
    assert "delta" in types
    assert "done" in types
    assert "end" in types
    assert "error" not in types
    assert "highlights" not in types
    done = next(e for e in events if e["type"] == "done")
    assert done["payload"]["answer"] == "臣陈辽饷。"
    # 回话已落库且高亮为空
    mid = int(db.get_last_active_chat_turn(minister, state.turn)["minister_message_id"])
    assert db.get_message_highlights(mid) == []
    _drain(web_game)


def test_chat_stream_slow_success_attaches_after_done(game, monkeypatch):
    """AC6 流式：回话先 done；慢而成功的判官在 done 后补挂 highlights 事件并落库。"""
    import web_app as web_app_mod
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    minister = "温体仁"
    web_game = _web_game(db, state, content, _FakeAgent(chunks=["臣", "先陈军务。"]))
    _patch_mindreading_skip(monkeypatch)

    release = threading.Event()
    seen_reply: List[str] = []

    def slow_ok(**kwargs):
        seen_reply.append(str(kwargs.get("minister_reply") or ""))
        release.wait(timeout=2.0)
        return ["军务"]

    monkeypatch.setattr(web_app_mod, "run_highlight_judge", slow_ok)

    stream = web_game.chat_stream(minister, "如何？")
    events: List[Dict[str, Any]] = []
    done_seen = False
    hl_before_done = False
    for item in stream:
        events.append(item)
        if item.get("type") == "highlights" and not done_seen:
            hl_before_done = True
        if item.get("type") == "done":
            done_seen = True
            release.set()

    types = [e.get("type") for e in events]
    assert types.index("done") < types.index("highlights")
    assert types.index("highlights") < types.index("end")
    assert not hl_before_done
    hl = next(e for e in events if e["type"] == "highlights")
    assert hl["highlights"] == ["军务"]
    assert seen_reply == ["臣先陈军务。"]
    mid = int(hl.get("message_id") or 0)
    assert mid > 0
    assert db.get_message_highlights(mid) == ["军务"]
    # 投影读端
    proj = db.build_chat_projection(minister)
    assert any(m.get("highlights") == ["军务"] for m in proj if m["role"] == "minister")
    _drain(web_game)


def test_chat_nonstream_folds_judge_within_timeout(game, monkeypatch):
    """AC6 非流式：折进等待窗，成功则 history 同到带高亮。"""
    import web_app as web_app_mod
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    minister = "温体仁"
    web_game = _web_game(db, state, content, _FakeAgent(chunks=["臣陈辽饷。"]))
    _patch_mindreading_skip(monkeypatch)

    # session.chat 非流式路径
    def fake_chat(name, message, *, chat_turn_id=0):
        from ming_sim.session import ChatTurnResult
        return ChatTurnResult(answer="臣陈辽饷。")

    web_game.session.chat = fake_chat  # type: ignore[method-assign]
    monkeypatch.setattr(
        web_app_mod, "run_highlight_judge",
        lambda **_k: ["辽饷"],
    )

    payload = web_game.chat(minister, "问辽饷？")
    assert payload["answer"] == "臣陈辽饷。"
    minister_msgs = [m for m in payload["history"] if m["role"] == "minister"]
    assert minister_msgs
    assert minister_msgs[-1]["highlights"] == ["辽饷"]
    _drain(web_game)


def test_chat_nonstream_timeout_returns_reply_without_highlights(game, monkeypatch):
    """非流式超时封顶：回话先行返回、无高亮、不报错。"""
    import web_app as web_app_mod
    import ming_sim.highlight_judge as hj
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    minister = "温体仁"
    web_game = _web_game(db, state, content, _FakeAgent(chunks=["臣遵旨。"]))
    _patch_mindreading_skip(monkeypatch)

    def fake_chat(name, message, *, chat_turn_id=0):
        from ming_sim.session import ChatTurnResult
        return ChatTurnResult(answer="臣遵旨。")

    web_game.session.chat = fake_chat  # type: ignore[method-assign]

    release = threading.Event()

    class _Slow:
        def run(self, *_a, **_k):
            release.wait(timeout=2.0)
            return SimpleNamespace(content='{"highlights": ["不该出现"]}')

    real_run = hj.run_highlight_judge

    def capped(**kwargs):
        kwargs = dict(kwargs)
        kwargs["agent"] = _Slow()
        kwargs["timeout_s"] = 0.05
        return real_run(**kwargs)

    monkeypatch.setattr(web_app_mod, "run_highlight_judge", capped)

    t0 = time.monotonic()
    payload = web_game.chat(minister, "问？")
    elapsed = time.monotonic() - t0
    release.set()

    assert payload["answer"] == "臣遵旨。"
    minister_msgs = [m for m in payload["history"] if m["role"] == "minister"]
    assert minister_msgs
    assert minister_msgs[-1].get("highlights") in ([], None) or minister_msgs[-1]["highlights"] == []
    # 不得被慢判官拖过上限太多
    assert elapsed < 1.0
    assert DEFAULT_HIGHLIGHT_JUDGE_TIMEOUT_S > 0
    _drain(web_game)
