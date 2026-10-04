"""#1849 / ADR 0152 决定 1：独立手拟新增 Web 入口退役后的草稿播种夹具。

`POST /api/directives` 已随拟诏台「御笔自拟」控件退出。日常直接下旨走召对拟旨
（`scene_chat` → 转译 → 落桌），但多数后端测试的被测对象是**落桌之后**的行为
（成案准入、案卷契约、月推进、恢复后可写），与「谁发起这旨」无关。

本模块给这些测试一条**现行仍在产的**播种路：CLI 审阅路同款
`capture_manual_directive_payload` + `session.add_directive`（`ming_sim/cli/terminal.py`
的 add 分支即此二步）。它不是替身 API，而是与召对落桌共用同一 `turn_directives`
写入与同一拟旨抽取核，故下游断言的账本事实与真实局同形。

需要证「Web 写端点仍可写」的测试请改用幸存的 `PATCH /api/directives/{id}`
（草稿改仍可达），不要把新增口写回来。
"""

from __future__ import annotations

from typing import Any


def seed_manual_draft(session: Any, text: str) -> int:
    """经现行 capture 核 + session.add_directive 落一条草稿，返回 directive id。"""
    from ming_sim.cli_backend import capture_manual_directive_payload

    payload = capture_manual_directive_payload(
        text,
        session.llm_config,
        **({"db": session.db, "content": session.content}
           if getattr(session, "content", None) is not None else {}),
    )
    return int(session.add_directive(text, dossier_payload=payload).id)
