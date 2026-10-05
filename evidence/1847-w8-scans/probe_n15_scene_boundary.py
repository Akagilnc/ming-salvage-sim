#!/usr/bin/env python3
"""#1847 w8 N15 — scene_chat call-boundary probe (STUB translate only).

DISCLAIMER: temporary stub of create_scene_agent + _apply_scene_turn_translation
proves CALL BOUNDARY only; does NOT prove real translation implementation.

Replay (from repo root, seven false bins):
  MING_SIM_*_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD \\
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \\
    evidence/1847-w8-scans/probe_n15_scene_boundary.py
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ming_sim.audience_night import (
    CMD_NONE,
    get_open_night,
    open_night,
    recognize_audience_command,
)
from ming_sim.content import GameContent
from ming_sim.db import GameDB
from ming_sim.session import GameSession
from ming_sim.session_write_queue import SessionWriteQueue


def main() -> None:
    print(
        "NOTE: temporary stub of create_scene_agent + _apply_scene_turn_translation "
        "proves CALL BOUNDARY only; does not prove real translation implementation."
    )
    content = GameContent.load()
    td = Path(tempfile.mkdtemp(prefix="1847-n15-", dir="/tmp"))
    try:
        db = GameDB(str(td / "g.db"), content)
        db.seed_static_data()
        state = db.load_state()
        open_night(db, state)
        night = get_open_night(db)
        assert night is not None

        scene_calls = {"n": 0, "prompt": None}
        translate_calls = {"n": 0, "msg": None}

        class FakeAgent:
            def run(self, prompt, **kw):
                scene_calls["n"] += 1
                scene_calls["prompt"] = prompt if isinstance(prompt, str) else str(prompt)
                return SimpleNamespace(content="王绍徽叩答：臣在侧听候。")

        def fake_create(*a, **k):
            return FakeAgent()

        def fake_translate(self, *a, **k):
            translate_calls["n"] += 1
            if a:
                translate_calls["msg"] = a[0] if isinstance(a[0], str) else str(a[0])[:120]
            return None

        def build_sess():
            sess = GameSession.__new__(GameSession)
            sess.db = db
            sess.state = state
            sess.content = content
            sess.registry = None
            sess.llm_config = SimpleNamespace(channel="api")
            sess.temporary_characters = {}
            sess.agno_db = None
            sess._write_queue = SessionWriteQueue()
            sess._write_gate = sess._write_queue.write_gate
            return sess

        def pack(result):
            if isinstance(result, dict):
                return (
                    result.get("court_action") or "",
                    result.get("answer") or result.get("reply") or "",
                )
            return (
                getattr(result, "court_action", "") or "",
                getattr(result, "answer", None)
                or getattr(result, "reply", "")
                or getattr(result, "content", "")
                or "",
            )

        assert recognize_audience_command("留下听着") == CMD_NONE
        assert recognize_audience_command("今日就到这里吧") == CMD_NONE

        sess = build_sess()
        with patch("ming_sim.session.create_scene_agent", fake_create), patch.object(
            GameSession, "_apply_scene_turn_translation", fake_translate
        ):
            ctid = int(
                db.create_chat_turn(
                    state, "殿上", "test-sess", 0, night_id=int(night["id"])
                )
            )
            scene_calls["n"] = translate_calls["n"] = 0
            result = sess.scene_chat("留下听着", chat_turn_id=ctid)
            ca, ans = pack(result)
            current_stay = {
                "scene_calls": scene_calls["n"],
                "translate_calls": translate_calls["n"],
                "court_action": ca,
                "answer": ans,
                "scene_prompt": [scene_calls["prompt"]] if scene_calls["prompt"] else [],
                "translate_message": translate_calls["msg"],
            }
            print("CURRENT_stay", current_stay)
            assert current_stay["scene_calls"] >= 1, current_stay
            assert current_stay["translate_calls"] >= 1, current_stay

            night = get_open_night(db)
            ctid2 = int(
                db.create_chat_turn(
                    state, "殿上", "test-sess", 0, night_id=int(night["id"])
                )
            )
            scene_calls["n"] = translate_calls["n"] = 0
            result2 = sess.scene_chat("今日就到这里吧", chat_turn_id=ctid2)
            ca2, _ = pack(result2)
            print(
                "CURRENT_close_phrase",
                {
                    "scene_calls": scene_calls["n"],
                    "translate_calls": translate_calls["n"],
                    "court_action": ca2,
                },
            )
            assert scene_calls["n"] >= 1 and translate_calls["n"] >= 1

        scene_calls["n"] = translate_calls["n"] = 0
        orig_scene = GameSession.scene_chat

        def wrapped(self, message, **kw):
            if str(message).strip() == "留下听着":
                return {"court_action": "stay_attend", "answer": ""}
            return orig_scene(self, message, **kw)

        with patch.object(GameSession, "scene_chat", wrapped):
            sess2 = build_sess()
            night = get_open_night(db)
            ctid3 = int(
                db.create_chat_turn(
                    state, "殿上", "test-sess", 0, night_id=int(night["id"])
                )
            )
            result3 = sess2.scene_chat("留下听着", chat_turn_id=ctid3)
            ca3, ans3 = pack(result3)
            mutated_stay = {
                "scene_calls": scene_calls["n"],
                "translate_calls": translate_calls["n"],
                "court_action": ca3,
                "answer": ans3,
            }
            print("MUTATED_stay", mutated_stay)
            assert mutated_stay["scene_calls"] == 0 and mutated_stay["translate_calls"] == 0
            assert mutated_stay["court_action"] == "stay_attend"

        print("N15_SCENE_CHAT_MUTATION PASS")
    finally:
        shutil.rmtree(td, ignore_errors=True)
        print("tmpdir_cleaned", not td.exists())
        print(
            "DISCLAIMER: stub translate proves CALL BOUNDARY only, "
            "not real translate implementation."
        )


if __name__ == "__main__":
    main()
