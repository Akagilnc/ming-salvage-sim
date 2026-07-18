from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    ROOT / "content/prompts/season_simulator.md",
    ROOT / "content/prompts/score_extractor_military_external.md",
    ROOT / "ming_sim/tools.py",
)


def test_scout_report_label_replaces_old_bulletin_section_name():
    old_label = "陛下" + "未知者"
    new_label = "探子回报"

    contents = {path: path.read_text(encoding="utf-8") for path in SOURCE_FILES}
    old_label_files = [
        path.relative_to(ROOT).as_posix()
        for path, content in contents.items()
        if old_label in content
    ]

    assert old_label_files == []
    assert contents[ROOT / "content/prompts/season_simulator.md"].count(new_label) >= 3
    assert (
        f"「{new_label}」里的传闻不改盘面"
        in contents[ROOT / "content/prompts/score_extractor_military_external.md"]
    )
