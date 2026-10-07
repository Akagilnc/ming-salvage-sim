"""#544 高亮判官管道：同通道后处理 · 清单落库 · 两通道时序 · 静默降级。

票面 AC（冻结 r2）：
- 超时/坏输出 → 无高亮、零报错、回话照常（注入假输出、零真 LLM）
- 清单落库 + restore 后仍在（build_chat_projection / audience_night 卷轴）
- 非流式同到（折等待窗、超时封顶）；流式不挡流、流完补挂
- 慢而成功的判官：流式=回话先显示；非流式=折窗封顶
"""

from __future__ import annotations

import threading

import pytest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

from ming_sim import audience_night as an
from ming_sim.db import GameDB
from ming_sim.highlight_judge import (
    DEFAULT_HIGHLIGHT_JUDGE_TIMEOUT_S,
    run_highlight_judge,
)


# ── 解析 / 单次调用降级 ──────────────────────────────────────────────────


def test_run_highlight_judge_timeout_and_exception_degrade_silently():
    release = threading.Event()

    class _Slow:
        def run(self, *_a, **_k):
            release.wait()
            return SimpleNamespace(content='{"highlights": ["迟到"]}')

    class _Boom:
        def run(self, *_a, **_k):
            raise RuntimeError("model down")

    try:
        assert run_highlight_judge(
            minister_reply="臣陈辽饷。",
            llm_config=object(),
            agent=_Slow(),
            timeout_s=0.05,
        ) == []
    finally:
        # 断言失败不得扣住 _Slow.run；释放归本测 finally。
        release.set()

    assert run_highlight_judge(
        minister_reply="臣陈辽饷。",
        llm_config=object(),
        agent=_Boom(),
        timeout_s=1.0,
    ) == []


@pytest.mark.parametrize(("output", "expected"), [
    ("", []),
    ("not json", []),
    ('{"highlights": "辽饷"}', []),
    ('{"phrases": ["甲"]}', []),
    ('{"highlights": [1, null, ""]}', []),
    ('{"highlights": ["辽饷", "军心"]}', ["辽饷", "军心"]),
])
def test_run_highlight_judge_success_returns_phrases(output, expected):
    class _Ok:
        def run(self, *_a, **_k):
            return SimpleNamespace(content=output)

    assert run_highlight_judge(
        minister_reply="臣陈**辽饷**与军心。",
        llm_config=object(),
        agent=_Ok(),
        timeout_s=1.0,
    ) == expected


# ── 落库 + 两读端 + restore ──────────────────────────────────────────────


def _minister_turn(db, state, minister: str, reply: str, night_id: int = 0):
    uid = db.append_chat_message(minister, int(state.turn), "user", "问。")
    mid = db.append_chat_message(minister, int(state.turn), "minister", reply)
    cid = db.create_chat_turn(state, minister, "hl-test", 0, night_id=night_id)
    db.update_chat_turn_messages(cid, user_message_id=uid, minister_message_id=mid)
    return cid, mid


def _settle_minister_reply(db, state, chat_turn_id: int, night_id: int, minister: str, reply: str):
    from ming_sim.audience_translation import apply_audience_round_translation

    apply_audience_round_translation(
        db, state,
        {"scene_facts": [{
            "body": reply, "role": "minister", "audibility": "殿上公开",
            "person_names": [minister], "tags": ["scroll_role:minister"],
        }]},
        night_id=night_id, chat_turn_id=chat_turn_id, minister_name=minister,
    )


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
    cid, mid = _minister_turn(
        db, state, minister, "臣请据实核账。", night_id=night_id,
    )
    db.set_message_highlights(mid, ["据实核账"])

    scroll = an.read_night_scroll(db, night_id)
    assert any(m["role"] == "scene" and m.get("chat_turn_id") == cid
               and m["highlights"] == [] for m in scroll)
    _settle_minister_reply(db, state, cid, night_id, minister, "臣请据实核账。")
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
    cid, mid = _minister_turn(
        src_db, state, minister, "臣陈军务与辽饷。", night_id=night_id,
    )
    src_db.set_message_highlights(mid, ["军务", "辽饷"])
    assert any(m["role"] == "scene" and m["highlights"] == []
               for m in an.read_night_scroll(src_db, night_id) if m.get("chat_turn_id") == cid)
    _settle_minister_reply(src_db, state, cid, night_id, minister, "臣陈军务与辽饷。")
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


def _restore_highlight_seams(web_game) -> None:
    """_web_game 默认桩掉高亮 trail/spawn（离线禁真 LLM）；本文件通道测须绑回生产缝。"""
    import types
    from web_app import WebGame

    web_game._trail_highlight_judge_after_reply = types.MethodType(
        WebGame._trail_highlight_judge_after_reply, web_game,
    )
    web_game._spawn_pending_write_thread = types.MethodType(
        WebGame._spawn_pending_write_thread, web_game,
    )


def _drain(web_game) -> None:
    from tests.test_audience_background import _wait_for_pending_writes_to_drain

    _wait_for_pending_writes_to_drain(web_game)
