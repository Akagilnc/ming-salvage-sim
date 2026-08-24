"""#670 Web 殿上 chat/chat_stream 测试壳共享 admission 契约。

生产 WebGame 无条件调 session.consume_audience_admission（密疏 gate_already_held 除外）。
测试假壳不得各自复制放行方法体，也不得在 web_app 对缺方法 fail-open。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

from ming_sim.session import AudienceAdmission, AudienceAdmissionDecision


def allow_hall_admission(
    character: Any,
    *,
    origin_id: str,
    state: Optional[Any] = None,
) -> AudienceAdmissionDecision:
    """殿上测试放行：与 test_web_chat_serialization_393 已绿契约同形。"""
    del character, origin_id, state
    return AudienceAdmissionDecision(
        AudienceAdmission.IN_CAPITAL,
        reason="",
        allowed=True,
    )


class HallAdmissionSessionMixin:
    """给 class 体可改的假 Session 混入统一放行入口（实现只此一处）。"""

    consume_audience_admission = staticmethod(allow_hall_admission)


def install_hall_admission(session: Any) -> Any:
    """给无法改 class 体的轻壳一次赋值共享函数。"""
    session.consume_audience_admission = allow_hall_admission
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
