"""ADR 0009 public delta schema documentation contract."""

from pathlib import Path


DELTA_SCHEMA = Path(__file__).resolve().parents[1] / "docs" / "DELTA_SCHEMA.md"


def _text() -> str:
    return DELTA_SCHEMA.read_text(encoding="utf-8")


def test_delta_schema_documents_single_person_change_key():
    """DELTA_SCHEMA exposes ADR 0009's single person key, not the legacy four-key API."""
    text = _text()
    top_level = text.split("## 各字段约束详表", 1)[0]

    assert '"人物变更":' in top_level
    for legacy_key in (
        '"office_changes":',
        '"appointments":',
        '"character_status_changes":',
        '"character_power_changes":',
    ):
        assert legacy_key not in top_level


def test_delta_schema_documents_person_actions_and_payloads():
    """The public schema names the seven ADR 0009 actions and their payload fields."""
    text = _text()

    assert "### `人物变更`" in text
    for action in ("任命", "罢黜", "调任", "处置", "易主", "册封", "行止"):
        assert f"`{action}`" in text
    for field in ("`name`", "`动作`", "`reason_code`", "`transit_to`", "`方式`"):
        assert field in text

    for legacy_heading in (
        "### `office_changes`",
        "### `character_status_changes`",
        "### `character_power_changes`",
        "### `appointments`",
    ):
        assert legacy_heading not in text


def test_delta_schema_documents_legacy_translation_order_example():
    """Legacy four-key replay semantics are documented as a worked example."""
    text = _text()

    assert "旧四 key 翻译示例" in text
    expected_order = (
        "appointments（后宫项） → character_status_changes → "
        "character_power_changes → office_changes → appointments（朝臣 spillover）"
    )
    assert expected_order in text
    for phrase in (
        "character_status_changes",
        "legacy_gate",
        "character_power_changes",
        "方式=不明",
        "appointments（朝臣 spillover）",
    ):
        assert phrase in text


def test_delta_schema_documents_power_change_backlash_contract():
    """New 易主 entries require backlash; only legacy translation may synthesize it."""
    text = _text()
    power_change_row = next(
        line for line in text.splitlines() if line.startswith("| `易主` |")
    )
    columns = [column.strip() for column in power_change_row.strip("|").split("|")]
    required_fields, optional_fields, notes = columns[1], columns[2], columns[3]

    for field in ("`new_power`", "`方式`", "`反噬`"):
        assert field in required_fields
    assert "`反噬`" not in optional_fields
    assert "legacy 翻译才可用 `不明`" in notes

    assert "零值反噬" in text
    assert '"方式": "不明"' in text
    assert "legacy_partial" in text
