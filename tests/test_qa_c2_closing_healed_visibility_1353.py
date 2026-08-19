"""QA 包乙刀④ #1353/#1381 半面：收夜待补自愈后 closing 夜的可见重试态。

fail-closed 机制不动（drain 仍挡收夜）。
当 /api/audience/extraction/pending 报 count=0 且夜停 closing：
玩家面须给「可重试/已自愈」指引，不得静默无态。
"""

from __future__ import annotations

from types import SimpleNamespace

import web_app
from ming_sim.audience_night import NIGHT_STATUS_CLOSING, NIGHT_STATUS_OPEN


def _shell(db):
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(db=db)
    return runtime


def test_pending_extractions_hint_when_closing_and_healed(monkeypatch):
    """closing + pending=0 → player_hint 指引可重试；count 仍 0（fail-closed 数源不动）。"""
    db = SimpleNamespace(
        conn=object(),
        list_unextracted_replies=lambda night_id=None: [],
    )
    runtime = _shell(db)

    monkeypatch.setattr(
        "ming_sim.audience_night.get_open_night",
        lambda _db: {"id": 7, "status": NIGHT_STATUS_CLOSING},
    )

    payload = runtime.pending_story_extractions()
    assert payload["night_id"] == 7
    assert payload["count"] == 0
    assert payload["pending"] == []
    assert payload["night_status"] == NIGHT_STATUS_CLOSING
    assert "自愈" in payload["player_hint"] or "可重试" in payload["player_hint"]
    assert "收夜" in payload["player_hint"] or "颁诏" in payload["player_hint"]


def test_pending_extractions_no_hint_when_open_and_zero(monkeypatch):
    """open + pending=0：无异常态，不塞指引。"""
    db = SimpleNamespace(
        conn=object(),
        list_unextracted_replies=lambda night_id=None: [],
    )
    runtime = _shell(db)

    monkeypatch.setattr(
        "ming_sim.audience_night.get_open_night",
        lambda _db: {"id": 3, "status": NIGHT_STATUS_OPEN},
    )

    payload = runtime.pending_story_extractions()
    assert payload["count"] == 0
    assert payload.get("player_hint") in (None, "")
    assert payload.get("night_status") in (None, NIGHT_STATUS_OPEN, "")


def test_pending_extractions_still_lists_when_closing_unhealed(monkeypatch):
    """closing + 仍有待补：照旧报 count，不假装已自愈。"""
    db = SimpleNamespace(
        conn=object(),
        list_unextracted_replies=lambda night_id=None: [
            {"chat_turn_id": 2, "minister_name": "周延儒", "night_id": 7},
        ],
    )
    runtime = _shell(db)

    monkeypatch.setattr(
        "ming_sim.audience_night.get_open_night",
        lambda _db: {"id": 7, "status": NIGHT_STATUS_CLOSING},
    )

    payload = runtime.pending_story_extractions()
    assert payload["count"] == 1
    assert payload["pending"][0]["chat_turn_id"] == 2
    # 未自愈不给「已自愈」假象
    hint = str(payload.get("player_hint") or "")
    assert "已自愈" not in hint
