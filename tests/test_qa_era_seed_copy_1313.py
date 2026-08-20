"""#1313：开局 1627.10 仍是天启七年，seed 不得当期误称「崇祯元年」。

finding：powers[ming].status 写「崇祯元年新立…」，与 opening_gazette
「改元之诏俟明年正月初一颁行」冲突。
victory_status.summary「社稷尚在崇祯一念之间」中『崇祯』=帝号称人，可留。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ming_sim.content import load_powers
from ming_sim.context import victory_status

ROOT = Path(__file__).resolve().parents[1]

# 当期纪年误称：崇祯元年 / 崇祯N年（汉字或阿拉伯）。帝号单称「崇祯」不算。
_CHONGZHEN_ERA_YEAR = re.compile(r"崇祯(?:元年|[元一二三四五六七八九十0-9]+年)")


def _opening_gazette_text() -> str:
    return (ROOT / "content" / "opening_gazette.md").read_text(encoding="utf-8")


def _powers_raw() -> list[dict]:
    data = json.loads((ROOT / "content" / "powers.json").read_text(encoding="utf-8"))
    return list(data["powers"])


def test_opening_gazette_defers_era_change_to_next_year_zhengyue():
    """来源钉：改元俟明年正月——开局不得自称崇祯元年。"""
    gazette = _opening_gazette_text()
    assert "改元之诏俟明年正月初一颁行" in gazette
    assert "新君嗣位" in gazette


def test_ming_power_status_not_chongzhen_era_year():
    """#1313 主病灶：powers[ming].status 无「崇祯元年」当期误称；奏报口吻钉正稿。"""
    powers = load_powers()
    status = powers["ming"].status
    assert "崇祯元年" not in status, status
    assert _CHONGZHEN_ERA_YEAR.search(status) is None, status
    # 正稿来源钉（与 opening_gazette 新君嗣位口径一致，不预支改元）
    assert status == "新君嗣位，诛阉党，内有民变外有建虏", status
    assert "新君嗣位" in status


def test_all_power_status_fields_no_chongzhen_era_year():
    """全 powers status 字段扫同型当期误称（leader 帝号称人不管）。"""
    offenders: list[str] = []
    for entry in _powers_raw():
        status = str(entry.get("status") or "")
        if _CHONGZHEN_ERA_YEAR.search(status):
            offenders.append(f"{entry.get('id')}: {status!r}")
    assert not offenders, "powers status 当期误称崇祯N年:\n" + "\n".join(offenders)


def test_victory_ongoing_summary_allows_emperor_title_not_era_year(game):
    """victory ongoing：可留帝号「崇祯」，不得写「崇祯元年」当期；summary 来源钉。"""
    db, state, _content = game
    state.year = 1627
    state.period = 10
    vs = victory_status(db, state)
    assert vs["status"] == "ongoing"
    summary = str(vs["summary"])
    assert "崇祯元年" not in summary, summary
    assert _CHONGZHEN_ERA_YEAR.search(summary) is None, summary
    # 帝号称人合法保留 + 正稿来源钉
    assert summary == "局势未决，社稷尚在崇祯一念之间。", summary
    assert "崇祯" in summary
