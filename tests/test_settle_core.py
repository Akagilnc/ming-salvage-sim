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
from ming_sim.models import Event
from ming_sim import issues
from tests.conftest import active_ming_character, covering_monthly_extract, with_monthly_reports
from tests.dossier_test_helpers import create_test_secret_order


def test_settle_with_delta_applies_region_and_advances_turn(game):
    """喂一份 region_delta，城内动乱按增量落库，且回合推进 turn+1。"""
    db, state, content = game
    before_turn = state.turn
    old_unrest = db.conn.execute(
        "SELECT unrest FROM regions WHERE id='shanxi'"
    ).fetchone()[0]

    extracted = {"region_delta": {"shanxi": {"origin_ref": "盘面自发", "unrest": 5}}}
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
                    {"origin_ref": "盘面自发", "name": name, "动作": "处置", "status": "dismissed", "reason": "自然失败问责"}
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


def test_settle_persists_public_and_restricted_sources_before_archive_projection(game):
    """生产结算先落逐 source 事项；#883 密令只进专用简报，不进共享源。"""
    db, state, content = game
    ministers = [
        character for character in content.characters.values()
        if character.office_type not in ("后宫", "宗藩")
        and db.get_character_status(character.name)[0] == "active"
    ]
    knower, excluded = ministers[:2]
    order = create_test_secret_order(db, 
        state,
        knower.name,
        "生产链密查",
        "生产链受限事项",
        [],
        excluded_names=[excluded.name],
    )
    before_turn = state.turn
    source_id = "restricted:settlement-private"
    db.register_character_knowledge_source(
        state, [{"character_id": knower.name, "tier": "主办"}], "private_matter",
        "生产链密查", "生产链受限事项", source_id=source_id,
        excluded_names=[excluded.name],
    )
    db.record_public_knowledge_event(
        state, "生产链公开事项", "生产链公开事项", source_id="test:settlement-public",
    )
    assert db.conn.execute(
        "SELECT 1 FROM character_knowledge_events WHERE source_id=?",
        (source_id,),
    ).fetchone() is None
    settle_with_delta(
        state,
        db,
        with_monthly_reports(db, {}),
        before_turn=before_turn,
        content=content,
        narrative="生产链公开事项",
    )

    rows = db.conn.execute(
        "SELECT source_id, excluded_names FROM character_knowledge_events "
        "WHERE character_name='' AND turn=? ORDER BY source_id",
        (before_turn,),
    ).fetchall()
    by_source = {row["source_id"]: row for row in rows}
    assert f"settlement:narrative:{before_turn}" not in by_source
    assert source_id in by_source
    assert excluded.name in by_source[source_id]["excluded_names"]
    # #883: secret order itself never materializes into the shared ledger.
    assert db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id=?",
        (f"secret_order:{order}",),
    ).fetchone()[0] == 0
    brief = db.conn.execute(
        "SELECT body FROM secret_order_briefs WHERE order_id=?", (order,)
    ).fetchone()
    assert brief is not None and "生产链受限事项" in (brief["body"] or "")

    excluded_text = " ".join(
        item.get("body", "")
        for item in db.get_character_knowledge(state, excluded.name)["public_events"]
    )
    assert "生产链公开事项" in excluded_text
    assert "生产链受限事项" not in excluded_text


def test_private_audience_does_not_erase_independent_public_settlement(game):
    db, state, content = game
    people = [
        c for c in content.characters.values()
        if c.office_type not in ("后宫", "宗藩")
        and db.get_character_status(c.name)[0] == "active"
    ]
    participant, nonparticipant = people[:2]
    db.register_character_knowledge_source(
        state, [{"character_id": participant.name}], "audience",
        "私下召对", "私下所议", source_id="audience:private-current-turn",
    )

    settle_with_delta(
        state, db, with_monthly_reports(db, {}), before_turn=state.turn, content=content,
        narrative="本月公开邸报",
    )

    rendered = " ".join(
        item.get("body", "")
        for item in db.get_character_knowledge(state, nonparticipant.name)["public_events"]
    )
    assert "本月公开邸报" in rendered
    assert "私下所议" not in rendered


def test_settlement_pure_public_narrative_excludes_secret_brief_from_public_view(game):
    """真实结算：密令只在 brief；独立公开源投影给未参与者；不靠文本擦洗拆混合串。

    #976 结构：公共 LLM 永不预读密令，故结算 narrative 只承载公开句；
    密令正文不会出现在 narrative 注入路径上。
    """
    db, state, content = game
    ministers = [
        character for character in content.characters.values()
        if character.office_type not in ("后宫", "宗藩")
        and db.get_character_status(character.name)[0] == "active"
    ]
    knower, excluded = ministers[:2]
    secret_marker = "混合结算密令标记"
    order = create_test_secret_order(db, 
        state, knower.name, "混合密查", secret_marker, [],
        excluded_names=[excluded.name],
    )
    before_turn = state.turn
    # Producer path: pure public narrative + independent public source (no secret inject).
    narrative = "公开结算标记；公开结算尾声"
    db.record_public_knowledge_event(
        state, "公开结算", "公开结算标记；公开结算尾声",
        source_id="test:mixed-settlement-public",
    )

    settle_with_delta(
        state, db, with_monthly_reports(db, {}), before_turn=before_turn, content=content,
        narrative=narrative,
    )

    excluded_text = " ".join(
        item.get("body", "")
        for item in db.get_character_knowledge(state, excluded.name)["public_events"]
    )
    assert "公开结算标记" in excluded_text
    assert "公开结算尾声" in excluded_text
    assert secret_marker not in excluded_text
    assert order > 0
    # Brief still holds the secret for the assignee only.
    brief = db.conn.execute(
        "SELECT body FROM secret_order_briefs WHERE order_id=?", (order,)
    ).fetchone()
    assert brief is not None and secret_marker in (brief["body"] or "")


def test_settlement_pure_public_narrative_lands_while_secret_brief_active(game):
    """#883/#976：公共产出不预读密令；纯公开结算叙事在 brief 存活期仍可入档（F3）。"""
    db, state, content = game
    ministers = [
        character for character in content.characters.values()
        if character.office_type not in ("后宫", "宗藩")
        and db.get_character_status(character.name)[0] == "active"
    ]
    knower, excluded = ministers[:2]
    secret_body = "核验边镇欠饷密令"
    order = create_test_secret_order(db, 
        state, knower.name, "改写密查", secret_body, [],
        excluded_names=[excluded.name],
    )

    # Structural producer path: narrative is pure public (no secret preload).
    settle_with_delta(
        state, db, with_monthly_reports(db, {}), before_turn=state.turn, content=content,
        narrative="邸报旁述：另报山东漕运如常。",
    )

    excluded_text = " ".join(
        item.get("body", "")
        for item in db.get_character_knowledge(state, excluded.name)["public_events"]
    )
    assert secret_body not in excluded_text
    # 正向：纯公开句在 brief 存活期仍可入档（F3，不整闸吞公开层）。
    assert "山东漕运如常" in excluded_text
    assert order > 0
    brief = db.conn.execute(
        "SELECT body FROM secret_order_briefs WHERE order_id=?", (order,)
    ).fetchone()
    assert brief is not None and secret_body in (brief["body"] or "")


def test_settlement_archive_writes_rollback_on_later_failure(game, monkeypatch):
    """真实结算在归档后续故障时不能留下 source/event/chapter/report 半写。"""
    db, state, _content = game
    turn = state.turn

    def fail_after_archive(*_args, **_kwargs):
        raise RuntimeError("archive failure")

    monkeypatch.setattr(db, "save_turn_extraction", fail_after_archive)
    with pytest.raises(decree.SettlementAbort):
        settle_with_delta(
            state, db, {}, before_turn=turn, narrative="归档公开事项"
        )

    assert db.conn.execute(
        "SELECT 1 FROM character_knowledge_events WHERE source_id=?",
        (f"settlement:narrative:{turn}",),
    ).fetchone() is None
    assert db.conn.execute(
        "SELECT 1 FROM turn_reports WHERE turn=?", (turn,)
    ).fetchone() is None
    assert db.conn.execute(
        "SELECT 1 FROM event_memories WHERE turn=? AND event_type='chapter_summary'",
        (turn,),
    ).fetchone() is None


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


def test_pre_settle_persists_event_terminal_states_in_write_path(game):
    """PR review：事件过期终态由 pre_settle 写路径落库，候选查询本身不写 DB。"""
    db, state, content = game
    issues.bind_content(content)
    ev = Event(
        id="__test_pre_settle_expiring_event__",
        title="测试·pre_settle 过期事件",
        kind="situation",
        summary="x",
        urgency=50,
        severity=50,
        credibility=50,
        interests=[],
        audiences=[],
        trigger_year=1629,
        trigger_month=1,
        trigger_end_year=1629,
        trigger_end_month=2,
        trigger_gate={"民心": "<=5"},
    )
    content.events.append(ev)
    try:
        state.year = 1629
        state.period = 3
        state.metrics["民心"] = 60

        assert all(c.id != ev.id for c in issues.gather_candidate_events(state, db))
        assert db.conn.execute(
            "SELECT 1 FROM event_triggers WHERE event_id=?",
            (ev.id,),
        ).fetchone() is None

        pre_settle(state, db)

        row = db.conn.execute(
            "SELECT terminal_state FROM event_triggers WHERE event_id=?",
            (ev.id,),
        ).fetchone()
        assert row["terminal_state"] == "expired"
    finally:
        content.events.remove(ev)


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
        settle_with_delta(state, db, with_monthly_reports(db, {}), before_turn=state.turn, content=content)
