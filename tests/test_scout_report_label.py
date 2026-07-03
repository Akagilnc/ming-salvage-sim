from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    ROOT / "content/prompts/season_simulator.md",
    ROOT / "content/prompts/score_extractor_military_external.md",
    ROOT / "ming_sim/tools.py",
)


# The old-label tripwire guards live surfaces (prompts/engine/frontend) only.
# docs/ and archive/ may legitimately quote the retired label verbatim
# (e.g. archived playtest transcripts predate the rename) — see #531.
EXCLUDED_PREFIXES = ("docs/", "archive/")


def test_scout_report_label_replaces_old_bulletin_section_name():
    old_label = "陛下" + "未知者"
    new_label = "探子回报"

    contents = {path: path.read_text(encoding="utf-8") for path in SOURCE_FILES}
    tracked_files = [
        path.decode("utf-8")
        for path in subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0")
        if path
    ]
    old_label_files = [
        path
        for path in tracked_files
        if not path.startswith(EXCLUDED_PREFIXES)
        and old_label in (ROOT / path).read_text(encoding="utf-8", errors="ignore")
    ]

    assert old_label_files == []
    assert contents[ROOT / "content/prompts/season_simulator.md"].count(new_label) >= 3
    assert (
        f"「{new_label}」里的传闻不改盘面"
        in contents[ROOT / "content/prompts/score_extractor_military_external.md"]
    )
