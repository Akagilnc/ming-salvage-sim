"""#670 Web 殿上 chat/chat_stream 测试壳共享 admission 契约。

生产 WebGame 殿上入口调 session.consume_audience_admission。
测试假壳不得各自复制放行方法体，也不得在 web_app 对缺方法 fail-open。
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from typing import Any, Optional

from ming_sim.applier import _SuspendableConnection
from ming_sim.session import AudienceAdmission, AudienceAdmissionDecision


def open_audience_night_conn() -> _SuspendableConnection:
    """方法替身库上的一条已开夜，建轮与 ``atomic`` 走生产唯一路径。"""
    conn = sqlite3.connect(
        ":memory:", factory=_SuspendableConnection, check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE audience_nights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            turn INTEGER NOT NULL,
            year INTEGER NOT NULL,
            period INTEGER NOT NULL,
            time_of_day TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',
            close_commit_cursor INTEGER NOT NULL DEFAULT 0,
            next_event_seq INTEGER NOT NULL DEFAULT 0,
            protagonist_name TEXT NOT NULL DEFAULT '',
            opened_at TEXT NOT NULL DEFAULT '',
            closed_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE chat_turns (
            id INTEGER PRIMARY KEY,
            status TEXT,
            minister_message_id INTEGER,
            extract_status TEXT,
            user_message_id INTEGER
        )
        """
    )
    conn.execute(
        "INSERT INTO audience_nights (turn, year, period, status) VALUES (1, 1628, 1, 'open')"
    )
    conn.commit()
    return conn


def allow_hall_admission(
    character: Any,
    *,
    origin_id: str,
    state: Optional[Any] = None,
    origin_chat_turn_id: int = 0,
) -> AudienceAdmissionDecision:
    """殿上测试放行：与 test_web_chat_serialization_393 已绿契约同形。"""
    del character, origin_id, state, origin_chat_turn_id
    return AudienceAdmissionDecision(
        AudienceAdmission.IN_CAPITAL,
        reason="",
        allowed=True,
    )


def allow_hall_admit_audience(character: Any) -> AudienceAdmissionDecision:
    """收夜入口调 admit_audience；与 consume 同形放行，禁各壳自造。"""
    del character
    return AudienceAdmissionDecision(
        AudienceAdmission.IN_CAPITAL,
        reason="",
        allowed=True,
    )


class HallAdmissionSessionMixin:
    """给 class 体可改的假 Session 混入统一放行入口（实现只此一处）。"""

    consume_audience_admission = staticmethod(allow_hall_admission)
    # #1716：收夜入口走 admit_audience（不 consume）；壳须同混入。
    admit_audience = staticmethod(allow_hall_admit_audience)


def install_hall_admission(session: Any) -> Any:
    """给无法改 class 体的轻壳一次赋值共享函数。"""
    session.consume_audience_admission = allow_hall_admission
    session.admit_audience = allow_hall_admit_audience
    return session


def minister_double(name: str, **overrides: Any) -> SimpleNamespace:
    """朝堂大臣替身：默认补齐 can_summon / is_vassal_prince 所需字段。"""
    base = dict(
        name=name,
        office_type="文官",
        office="",
        status="active",
        faction="",
        power_id="ming",
        location="beizhili",
        transit_to="",
    )
    base.update(overrides)
    return SimpleNamespace(**base)
