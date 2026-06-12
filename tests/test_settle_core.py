"""s1 (#10) — 确定性结算核 settle_with_delta / pre_settle 的行为测试。

settle_with_delta 是从 decree._settle_after_narrative 抽出的「后括号」：
收一份已规范化的 extracted delta → 落库 → inertia → 结局判定 → next_period，
不依赖 llm_config（章节记忆 / 结局总评是注入回调，默认跳过）。
真实流程与探针 driver 共用此核（ADR 0004）。
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

import ming_sim.decree as decree
from ming_sim.decree import pre_settle, settle_with_delta
from ming_sim.memories import effect_brief
from tests.conftest import active_ming_character


def test_settle_with_delta_applies_region_and_advances_turn(game):
    """喂一份 region_delta，城内动乱按增量落库，且回合推进 turn+1。"""
    db, state, content = game
    before_turn = state.turn
    old_unrest = db.conn.execute(
        "SELECT unrest FROM regions WHERE id='shanxi'"
    ).fetchone()[0]

    extracted = {"region_delta": {"shanxi": {"unrest": 5}}}
    settle_with_delta(state, db, extracted, before_turn=before_turn, content=content)

    new_unrest = db.conn.execute(
        "SELECT unrest FROM regions WHERE id='shanxi'"
    ).fetchone()[0]
    assert state.turn == before_turn + 1
    assert new_unrest == old_unrest + 5


def test_settle_with_delta_invokes_injected_callbacks(game):
    """注入的 chapter_recorder / on_stage 确实被调用（真实流程用它们跑 LLM 步；此处用 spy 验接缝）。"""
    db, state, content = game
    calls: list = []

    settle_with_delta(
        state,
        db,
        {},
        before_turn=state.turn,
        content=content,
        chapter_recorder=lambda *a: calls.append("chapter"),
        on_stage=lambda label: calls.append(("stage", label)),
    )

    assert "chapter" in calls
    assert any(isinstance(c, tuple) and c[0] == "stage" for c in calls)


def test_settle_with_delta_includes_inertia_person_changes_in_chapter_brief(game):
    db, state, content = game
    name = active_ming_character(db, content)
    before_turn = state.turn
    old_status = content.characters[name].status
    old_office = content.characters[name].office
    seen: dict = {}

    try:
        db.insert_issue(
            state,
            kind="situation",
            title="自然失败章节人事摘要测试",
            bar_value=1,
            inertia=-1,
            effect_on_fail={
                "人物变更": [
                    {"name": name, "动作": "处置", "status": "dismissed", "reason": "自然失败问责"}
                ]
            },
        )

        settle_with_delta(
            state,
            db,
            {},
            before_turn=state.turn,
            content=content,
            chapter_recorder=lambda _db, _state, _decree, _narrative, applied: seen.update(applied),
        )

        assert seen["issue_summary"]["applied_person_changes"] == [
            {"name": name, "动作": "处置", "status": "dismissed", "reason": "自然失败问责"}
        ]
        persisted = db.get_turn_extraction(before_turn)["extractor_output"]
        assert persisted["issue_summary"]["applied_person_changes"] == [
            {"name": name, "动作": "处置", "status": "dismissed", "reason": "自然失败问责"}
        ]
        assert persisted["applied_person_changes"] == [
            {"name": name, "动作": "处置", "status": "dismissed", "reason": "自然失败问责"}
        ]
        assert f"处分：{name}" in effect_brief(seen)
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office


def test_pre_settle_runs_fixed_fiscal_tick(game):
    """pre_settle 跑固定月度财政 tick（落 economy_ledger 行）+ 返回 auto_triggered 清单。"""
    db, state, content = game
    turn = state.turn
    before = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)
    ).fetchone()[0]

    auto = pre_settle(state, db)

    after = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)
    ).fetchone()[0]
    assert after > before
    assert isinstance(auto, list)


class _EnterBoom(BaseException):
    """非-Exception 的 BaseException：原样透传路（不写错误包），sentinel 干净可断言。"""


def test_settle_with_delta_enter_failure_preserves_original(game, monkeypatch):
    """atomic_and_reload 的 __enter__ 在 yield 前就抛时，原异常须原样透传——
    而不是被外层 except 里 `_atomic.reload_failed` 的 UnboundLocalError 吃掉
    （cmr S4 三模型收敛：gemini high×2 / sourcery bug_risk / codex P2）。"""
    db, state, content = game

    @contextmanager
    def _atomic_boom(_db):
        raise _EnterBoom("enter-time failure before yield")
        yield  # pragma: no cover - unreachable, keeps it a generator CM

    monkeypatch.setattr(decree, "atomic", _atomic_boom)

    with pytest.raises(_EnterBoom):
        settle_with_delta(state, db, {}, before_turn=state.turn, content=content)
