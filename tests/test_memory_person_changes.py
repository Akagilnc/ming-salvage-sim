"""ADR 0009 person changes must surface in narrative memory summaries.

#1185: no exact Chinese presentation pins. Assert ledger name tokens,
segment membership (adjustment vs punishment), baseline-empty equivalence,
and dedupe counts.
"""

from ming_sim.memories import effect_brief


def _segments(brief: str) -> list[str]:
    return [part for part in str(brief or "").split("；") if part]


def _segment_for(brief: str, name: str) -> str:
    for part in _segments(brief):
        if name in part:
            return part
    raise AssertionError(f"{name!r} absent from brief={brief!r}")


def test_effect_brief_summarizes_unified_person_changes():
    """章节时间线读取新 unified key,不只读 legacy four-key."""
    brief = effect_brief({
        "applied_person_changes": [
            {"name": "孙传庭", "动作": "调任", "new_office": "陕西总督"},
            {"name": "皇太极", "动作": "易主", "new_power": "ming"},
            {"name": "魏忠贤", "动作": "罢黜", "status": "dismissed"},
        ],
    })

    assert "孙传庭" in brief and "皇太极" in brief and "魏忠贤" in brief
    # adjustment names share one segment; punishment is a distinct segment
    adj = _segment_for(brief, "孙传庭")
    assert "皇太极" in adj
    pun = _segment_for(brief, "魏忠贤")
    assert adj != pun
    assert "孙传庭" not in pun and "皇太极" not in pun


def test_effect_brief_does_not_treat_raw_person_changes_as_applied():
    """raw extractor intent may contain rejected items; timeline only summarizes applied facts."""
    raw_only = {
        "person_changes": [
            {"name": "不存在的人", "动作": "任命", "office": "首辅"},
        ],
    }
    brief = effect_brief(raw_only)

    assert "不存在的人" not in brief
    assert brief == effect_brief({})


def test_effect_brief_merges_direct_and_issue_person_changes():
    """同月既有直接人事又有 issue 人事时,章节摘要不能被顶层 key 吃掉 issue key."""
    brief = effect_brief({
        "applied_person_changes": [
            {"name": "孙传庭", "动作": "调任", "new_office": "陕西总督"},
        ],
        "issue_summary": {
            "applied_person_changes": [
                {"name": "魏忠贤", "动作": "处置", "status": "dismissed"},
            ]
        },
    })

    assert "孙传庭" in brief and "魏忠贤" in brief
    assert _segment_for(brief, "孙传庭") != _segment_for(brief, "魏忠贤")


def test_effect_brief_dedupes_persisted_issue_person_changes():
    """玩家可见存档会把 issue 人事并到顶层,时间线摘要不能因此重复同一人。"""
    change = {"name": "魏忠贤", "动作": "处置", "status": "dismissed", "reason": "结案问责"}
    brief = effect_brief({
        "applied_person_changes": [change],
        "issue_summary": {"applied_person_changes": [change]},
    })

    assert brief.count("魏忠贤") == 1


def test_effect_brief_does_not_call_derived_release_punishment():
    """放归/起复等派生处置是释放前置,不是章节里的处分事件."""
    brief = effect_brief({
        "applied_person_changes": [
            {"name": "韩爌", "动作": "处置", "status": "offstage", "reason": "放归"},
            {"name": "韩爌", "动作": "任命", "new_office": "首辅"},
        ],
    })
    pure_appoint = effect_brief({
        "applied_person_changes": [
            {"name": "韩爌", "动作": "任命", "new_office": "首辅"},
        ],
    })
    pure_punish = effect_brief({
        "applied_person_changes": [
            {"name": "韩爌", "动作": "罢黜", "status": "dismissed"},
        ],
    })

    assert brief.count("韩爌") == 1
    assert _segment_for(brief, "韩爌") == _segment_for(pure_appoint, "韩爌")
    assert _segment_for(brief, "韩爌") != _segment_for(pure_punish, "韩爌")
