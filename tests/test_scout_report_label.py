from __future__ import annotations

import subprocess
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
    scan = subprocess.run(
        [
            "git",
            "grep",
            "-F",
            "-l",
            "-z",
            "-e",
            old_label,
            "--",
            ".",
            ":(exclude)docs/**",
            ":(exclude)archive/**",
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert scan.returncode in (0, 1), scan.stderr.decode("utf-8", errors="replace")
    old_label_files = [
        path.decode("utf-8")
        for path in scan.stdout.split(b"\0")
        if path
    ]

    assert old_label_files == []
    assert contents[ROOT / "content/prompts/season_simulator.md"].count(new_label) >= 3
    assert (
        f"「{new_label}」里的传闻不改盘面"
        in contents[ROOT / "content/prompts/score_extractor_military_external.md"]
    )
