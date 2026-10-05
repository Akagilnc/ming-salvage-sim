#!/usr/bin/env python3
"""#1847 w11 independent probes — temp dir only; not a durable proof test."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from ming_sim.content import GameContent
from ming_sim.db import GameDB, POPULATION_UNIT_PERSONS
from ming_sim.llm_model import extract_agent_text
from ming_sim.session import prune_auto_saves
from ming_sim.settlement_payload import parse_decision_blocks
import ming_sim.cli_backend as cb


def main() -> int:
    probe = Path(tempfile.mkdtemp(prefix="1847-w11-probes-"))
    results: dict = {"probe_dir": str(probe)}
    content = GameContent.load()

    db = GameDB(str(probe / "pop.db"), content)
    db.seed_static_data()
    beizhili = int(
        db.conn.execute("SELECT population FROM regions WHERE id='beizhili'").fetchone()[0]
    )
    unit_new = db.population_unit
    db.conn.execute("DELETE FROM save_meta WHERE key='population_unit'")
    db.conn.commit()
    unit_unmarked = db.population_unit
    results["N11_pop"] = {
        "new_unit": unit_new,
        "unmarked_unit": unit_unmarked,
        "beizhili_pop": beizhili,
        "no_wan_fallback": unit_unmarked != "万人",
    }
    db.close()

    raw = (
        '<<DECISION>>{"title":"发帑","context":"c","options":['
        '{"label":"准","action_type":"grant_allocaton","amount":30},'
        '{"label":"缓"}]}<<END>>'
    )
    dec = parse_decision_blocks(raw)
    results["N11_season"] = {
        "titles": [d["title"] for d in dec],
        "option_keys": sorted(dec[0]["options"][0].keys()) if dec else [],
    }

    saves = probe / "saves"
    saves.mkdir()
    for name, blob in [
        ("auto_1630_01_t0001_begin.db", b"legacy"),
        ("manual_keep.db", b"manual"),
        ("auto_othercamp_1627_10_t0001_begin.db", b"other"),
        ("auto_curr_1627_10_t0001_begin.db", b"t1"),
        ("auto_curr_1627_10_t0002_begin.db", b"t2"),
        ("auto_curr_1627_10_t0003_begin.db", b"t3"),
        ("auto_curr_1627_10_t0004_begin.db", b"t4"),
    ]:
        (saves / name).write_bytes(blob)
    prune_auto_saves(str(saves), "curr", keep_turns=3)
    remaining = sorted(p.name for p in saves.iterdir())
    results["N16"] = {
        "remaining": remaining,
        "legacy_kept": "auto_1630_01_t0001_begin.db" in remaining,
        "manual_kept": "manual_keep.db" in remaining,
        "other_kept": "auto_othercamp_1627_10_t0001_begin.db" in remaining,
        "curr_t1_pruned": "auto_curr_1627_10_t0001_begin.db" not in remaining,
    }

    class RunOutput:
        def __init__(self, content, status="COMPLETED"):
            self.content = content
            self.status = status

    ok = extract_agent_text(RunOutput("authentication succeeded with api key ok"))
    results["N10_extract"] = {
        "text": ok,
        "pass": ok == "authentication succeeded with api key ok",
    }

    # CLI 边界：现役 FakeCliRunner 外部路径替身（tests/cli_process_doubles），非手写原逻辑。
    from tests.cli_process_doubles import install_fake_cli_runner

    class _Patch:
        def __init__(self):
            self._orig = []

        def setattr(self, target, name, value=None, raising=True):
            old = getattr(target, name)
            self._orig.append((target, name, old))
            setattr(target, name, value)

        def undo(self):
            for obj, name, old in reversed(self._orig):
                setattr(obj, name, old)

    mp = _Patch()
    try:
        install_fake_cli_runner(
            mp,
            [{"stdout": ("authentication succeeded with api key",), "returncode": 0}],
        )
        text, attempts = cb._run_agy("PROMPT")
        results["N10_cli"] = {
            "text": text,
            "attempts": attempts,
            "pass": text.strip() == "authentication succeeded with api key" and attempts == 1,
            "external_stub": "tests.cli_process_doubles.install_fake_cli_runner",
        }
    except Exception as e:
        results["N10_cli"] = {"error": f"{type(e).__name__}:{e}", "pass": False}
    finally:
        mp.undo()

    dbx = GameDB(str(probe / "n13x.db"), content)
    dbx.seed_static_data()
    stx = dbx.load_state()
    dbx.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content, knowledge_status) "
        "VALUES (?,?,?,?,?)",
        ("温体仁", stx.turn, "user", "密谕", "held"),
    )
    dbx.conn.commit()
    dbx.conn.close()
    try:
        dbx.release_held_audience_knowledge(commit=False)
        results["N13_closed"] = {"raised": False, "pass": False}
    except Exception as e:
        results["N13_closed"] = {
            "raised": True,
            "type": type(e).__name__,
            "pass": True,
        }

    db4 = GameDB(str(probe / "n13c.db"), content)
    db4.seed_static_data()
    st4 = db4.load_state()
    mid4 = db4.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content, knowledge_status) "
        "VALUES (?,?,?,?,?)",
        ("温体仁", st4.turn, "user", "密谕C", "held"),
    ).lastrowid
    db4.conn.execute(
        "INSERT INTO pending_actions (turn, kind, action, status, payload_json) "
        "VALUES (?,?,?,?,?)",
        (
            st4.turn,
            "secret_order",
            "创建",
            "pending",
            json.dumps({"origin_chat_message_id": mid4}, ensure_ascii=False),
        ),
    )
    db4.conn.commit()
    rel = db4.release_held_audience_knowledge(commit=True)
    st = db4.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid4,)
    ).fetchone()[0]
    results["N13_live_current"] = {
        "released_count": rel,
        "status": st,
        "pass": st in ("held", "withheld") and rel == 0,
    }

    # In-memory mutation of failure shape (empty protection), not a verbatim old-body reload.
    orig_prot = GameDB._secret_origin_message_protection
    GameDB._secret_origin_message_protection = lambda self: {}
    db4.conn.execute(
        "UPDATE chat_messages SET knowledge_status='held' WHERE id=?", (mid4,)
    )
    db4.conn.commit()
    rel_bad = db4.release_held_audience_knowledge(commit=True)
    st_bad = db4.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid4,)
    ).fetchone()[0]
    results["N13_mutated_empty_protection_RED"] = {
        "released_count": rel_bad,
        "status": st_bad,
        "pass_as_red": st_bad == "released" or rel_bad > 0,
        "disclaimer": (
            "in-memory empty-protection mutation; not a verbatim reload of deleted old function body"
        ),
    }
    GameDB._secret_origin_message_protection = orig_prot
    db4.conn.execute(
        "UPDATE chat_messages SET knowledge_status='held' WHERE id=?", (mid4,)
    )
    db4.conn.commit()
    rel_g = db4.release_held_audience_knowledge(commit=True)
    st_g = db4.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid4,)
    ).fetchone()[0]
    results["N13_restored_green"] = {
        "released_count": rel_g,
        "status": st_g,
        "pass": st_g in ("held", "withheld"),
    }

    import shutil

    shutil.rmtree(probe, ignore_errors=True)
    results["OWN_TEMP_CLEANED"] = True
    print(json.dumps(results, ensure_ascii=False, indent=2))
    ok = all(
        [
            results["N11_pop"]["no_wan_fallback"],
            results["N11_season"]["titles"] == ["发帑"],
            results["N16"]["legacy_kept"],
            results["N16"]["manual_kept"],
            results["N16"]["other_kept"],
            results["N10_extract"]["pass"],
            results["N10_cli"]["pass"],
            results["N13_closed"]["pass"],
            results["N13_live_current"]["pass"],
            results["N13_mutated_empty_protection_RED"]["pass_as_red"],
            results["N13_restored_green"]["pass"],
            results["OWN_TEMP_CLEANED"],
        ]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
