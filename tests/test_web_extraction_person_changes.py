"""Static contract tests for ADR 0009 extraction display wiring."""

from pathlib import Path


EXTRACTION_TSX = (
    Path(__file__).resolve().parents[1] / "web" / "src" / "components" / "extraction.tsx"
)


def test_extraction_view_renders_unified_person_change_section():
    """邸报明细要展示 ADR 0009 unified key,不能只展示 legacy four-key."""
    text = EXTRACTION_TSX.read_text(encoding="utf-8")

    assert '<ExtractionSection title="人物变更">' in text
    assert 'pickField(out, "人物变更", "applied_person_changes")' in text
    assert 'pickField(issueSummary, "人物变更", "applied_person_changes")' in text
    assert "mergeLists(" in text
    assert "PersonChangesBlock" in text
    assert 'pickItem(it, "所在", "location")' in text
    assert 'labelRegion(transitTo || location)' in text


def test_person_changes_block_reads_localized_title_for_office_actions():
    """localized extractor output 会把 office 显成位号,任命/调任不能显示问号。"""
    text = EXTRACTION_TSX.read_text(encoding="utf-8")

    assert 'pickItem(it, "位号", "office")' in text
    assert (
        'pickItem(it, "新官职", "new_office") || pickItem(it, "位号", "office") '
        '|| pickItem(it, "官职", "office")'
    ) in text


def test_person_changes_block_labels_derived_active_by_event_not_blanket_release():
    """派生 active 处置（被顶替腾缺 / 起复·昭雪·夺情释放）须按 derived_from/缘由 标具体事由,
    不能一律「起复」——否则把「被顶替」误显成「起复」(5b r3 codex-c R1)。"""
    text = EXTRACTION_TSX.read_text(encoding="utf-8")

    # 旧的「active 一律起复」硬映射已删（被顶替也会落 active 处置，会被误标）。
    assert 'active: "起复"' not in text
    # 处置/active 改走 derived_from/缘由 派生标签。
    assert 'pickItem(it, "derived_from", "derived_from")' in text
    assert 'pickItem(it, "缘由", "reason_code")' in text
    # main 必须由 tag 派生链赋值，而非另行硬编标签——否则计算了 tag 却仍写死「起复」也会过
    # （codex r4 R1：钉住赋值表达式，不只钉 tag 出现）。
    assert "tag || cnValue(status) || action" in text


def test_extraction_view_reads_applied_trace_shape():
    """turn_extractions.extractor_output 已是 applied trace,弹窗不能只读 raw extractor keys."""
    text = EXTRACTION_TSX.read_text(encoding="utf-8")

    assert 'const issueSummary = pickField(out, "局势摘要", "issue_summary") || {}' in text
    assert 'pickField(issueSummary, "局势推进", "advances")' in text
    assert 'pickField(issueSummary, "新立局势", "new_issues")' in text
    assert 'pickField(issueSummary, "结案局势", "closes")' in text
    assert 'pickField(issueSummary, "撤销局势", "cancels")' in text
    assert 'pickField(out, "地区变化", "region_changes")' in text
    assert 'pickField(out, "军队变化", "army_changes")' in text
    assert 'pickField(out, "新建军队", "created_armies")' in text
    assert 'pickField(out, "势力变化", "power_changes")' in text


def test_issue_advances_block_derives_regression_tone_from_from_to_values():
    """applied issue advances 只有 from/to 时,下降不能默认显示成 good。"""
    text = EXTRACTION_TSX.read_text(encoding="utf-8")

    assert "const toneDelta =" in text
    assert "Number(toValue) - Number(fromValue)" in text
    assert 'className={toneDelta >= 0 ? "good" : "bad"}' in text
