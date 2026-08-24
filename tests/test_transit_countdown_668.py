"""#668：0095 确定性在途倒数 tick + transit_arrivals 叙事投喂 + 恢复。

Seams under test:
- tick_transit_arrivals / pre_settle（结算链调用点）
- GameDB.set_character_transit（抵达唯一写缝）
- build_simulator_payload（transit_arrivals 键）
- resolve_directives 的 pre_settle+ready=0 占位与 settling fallthrough
- content/distance_matrix.json（河南特批 ≤1.0）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ming_sim.decree import pre_settle, reload_state_from_db, tick_transit_arrivals
from ming_sim.distance import DistanceMatrix
from ming_sim.models import Event, TurnPhase
from ming_sim.simulation import build_simulator_payload
from tests.conftest import active_ming_character

ROOT = Path(__file__).resolve().parents[1]
MATRIX = DistanceMatrix.from_file(ROOT / "content/distance_matrix.json")


def _oracle_n(r0: float, speed_factor: float) -> int:
    """F2：N = min { n ∈ ℕ⁺ : r0 - n*step ≤ 0 }；抵达 turn = T0 + N。"""
    step = 1.0 * float(speed_factor)
    remaining = float(r0)
    n = 0
    while remaining > 0:
        remaining -= step
        n += 1
    return n


def _ledger(db, name: str):
    return db.conn.execute(
        "SELECT location, transit_to, transit_distance_remaining, "
        "transit_speed_factor, transit_start_turn FROM characters WHERE name=?",
        (name,),
    ).fetchone()


def _put_in_transit(
    db, content, name: str, *, origin: str, dest: str,
    speed_factor: float = 1.0, start_turn: int,
):
    r0 = MATRIX.travel_time(origin, dest)
    db.set_character_transit(
        name,
        location=origin,
        transit_to=dest,
        distance_remaining=r0,
        speed_factor=speed_factor,
        start_turn=start_turn,
        content=content,
    )
    return r0


# ── 1) 河南常速黄金 ──────────────────────────────────────────────────────────


def test_henan_beizhili_matrix_special_case_le_one_and_symmetric():
    raw = json.loads((ROOT / "content/distance_matrix.json").read_text(encoding="utf-8"))["matrix"]
    assert raw["henan"]["beizhili"] <= 1.0
    assert raw["beizhili"]["henan"] == raw["henan"]["beizhili"]


def test_henan_normal_speed_arrives_next_month(game):
    db, state, content = game
    name = active_ming_character(db, content)
    t0 = state.turn
    r0 = _put_in_transit(
        db, content, name, origin="henan", dest="beizhili",
        speed_factor=1.0, start_turn=t0,
    )
    assert r0 <= 1.0
    assert _oracle_n(r0, 1.0) == 1

    # 启程当月不减
    assert tick_transit_arrivals(db, state, content) == []
    row = _ledger(db, name)
    assert row["transit_to"] == "beizhili"
    assert row["location"] == "henan"

    # 次月首 tick 抵达
    state.turn = t0 + 1
    arrivals = tick_transit_arrivals(db, state, content)
    assert arrivals == [{"name": name, "location": "beizhili"}]
    row = _ledger(db, name)
    assert tuple(row) == ("beizhili", "", None, None, 0)
    ch = content.characters[name]
    assert (
        ch.location, ch.transit_to,
        ch.transit_distance_remaining, ch.transit_speed_factor, ch.transit_start_turn,
    ) == ("beizhili", "", None, None, 0)


# ── 2) 非常速差异路线 + 3) 未到期不抵达 ─────────────────────────────────────


@pytest.mark.parametrize("speed_factor", [1.0, 1.5, 2.0])
def test_speed_factors_match_f2_oracle_on_differentiated_route(game, speed_factor):
    """同一 r0 下 1.0/1.5/2.0 抵达 turn 与 F2 oracle 一致；未到期月仍在途。"""
    db, state, content = game
    name = active_ming_character(db, content)
    origin, dest = "henan", "liaodong"
    t0 = state.turn
    r0 = _put_in_transit(
        db, content, name, origin=origin, dest=dest,
        speed_factor=speed_factor, start_turn=t0,
    )
    n = _oracle_n(r0, speed_factor)
    assert n >= 2, "路线须使 N>1 才能覆盖未到期断言"
    # 三档须能分出差异（本矩阵边 r0≈3.1 → N=4/3/2）
    assert len({_oracle_n(r0, f) for f in (1.0, 1.5, 2.0)}) == 3

    step = 1.0 * speed_factor
    for k in range(1, n):
        state.turn = t0 + k
        arrivals = tick_transit_arrivals(db, state, content)
        assert name not in [a["name"] for a in arrivals]
        row = _ledger(db, name)
        assert row["transit_to"] == dest
        assert row["location"] == origin
        expected_remaining = r0 - k * step
        assert row["transit_distance_remaining"] == pytest.approx(expected_remaining)
        assert row["transit_speed_factor"] == pytest.approx(speed_factor)
        assert row["transit_start_turn"] == t0

    state.turn = t0 + n
    arrivals = tick_transit_arrivals(db, state, content)
    assert arrivals == [{"name": name, "location": dest}]
    row = _ledger(db, name)
    assert tuple(row) == (dest, "", None, None, 0)


# ── 4) 链顺序：tick 先于 event terminal / seed 门 ─────────────────────────────


def test_pre_settle_tick_before_event_terminal_reads_new_location(game):
    db, state, content = game
    import ming_sim.issues as issues
    issues.bind_content(content)
    name = active_ming_character(db, content)
    t0 = state.turn
    r0 = _put_in_transit(
        db, content, name, origin="henan", dest="beizhili",
        speed_factor=1.0, start_turn=t0,
    )
    assert _oracle_n(r0, 1.0) == 1

    ev = Event(
        id="__test_transit_gate_668__", title="测试在途门控", kind="situation",
        summary="x", urgency=50, severity=50, credibility=50,
        interests=[], audiences=[],
        trigger_year=1, trigger_month=0,
        trigger_gate={
            f"character.{name}.location": "==beizhili",
            f"character.{name}.status": "==active",
        },
        person_core_subjects=[name],
    )
    content.events.append(ev)
    try:
        state.turn = t0 + 1
        state.turn_phase = TurnPhase.REVIEWING.value
        db.save_state(state)
        pre_settle(state, db, content=content)

        row = _ledger(db, name)
        assert row["location"] == "beizhili" and row["transit_to"] == ""
        assert not db.has_event_terminal_state("__test_transit_gate_668__", "avoided")
    finally:
        content.events.remove(ev)


def test_pre_settle_tick_before_seed_auto_trigger_reads_new_location(game):
    """F7.4：pre_settle 内 tick 先于 auto_trigger_seed_issues，seed 门读到新 location。"""
    db, state, content = game
    import ming_sim.issues as issues
    issues.bind_content(content)
    name = active_ming_character(db, content)
    t0 = state.turn
    r0 = _put_in_transit(
        db, content, name, origin="henan", dest="beizhili",
        speed_factor=1.0, start_turn=t0,
    )
    assert _oracle_n(r0, 1.0) == 1

    ev = Event(
        id="__test_transit_seed_gate_668__", title="测试在途 seed 门控",
        kind="situation", summary="x", urgency=50, severity=50, credibility=50,
        interests=[], audiences=[],
        auto_trigger=True,
        trigger_gate={
            f"character.{name}.location": "==beizhili",
            f"character.{name}.status": "==active",
        },
        person_core_subjects=[name],
    )
    content.seed_events.append(ev)
    try:
        state.turn = t0 + 1
        state.turn_phase = TurnPhase.REVIEWING.value
        db.save_state(state)
        pre_settle(state, db, content=content)

        row = _ledger(db, name)
        assert row["location"] == "beizhili" and row["transit_to"] == ""
        issue = db.find_any_issue_by_origin("event_pool", ev.id)
        assert issue is not None, "seed 门应在 tick 后读新 location 并硬立项"
        assert issue["status"] == "active"
    finally:
        content.seed_events.remove(ev)


# ── 5) 中断型 ───────────────────────────────────────────────────────────────


def test_ousted_in_transit_stops_countdown_and_never_arrives(game):
    db, state, content = game
    name = active_ming_character(db, content)
    t0 = state.turn
    r0 = _put_in_transit(
        db, content, name, origin="henan", dest="liaodong",
        speed_factor=1.0, start_turn=t0,
    )
    assert _oracle_n(r0, 1.0) >= 2

    db.set_character_status(state, name, "imprisoned", reason="廷杖下狱", content=content)
    row = _ledger(db, name)
    assert row["location"] == "henan"
    assert tuple(row)[1:] == ("", None, None, 0)

    for k in range(1, _oracle_n(r0, 1.0) + 2):
        state.turn = t0 + k
        arrivals = tick_transit_arrivals(db, state, content)
        assert name not in [a["name"] for a in arrivals]

    row = _ledger(db, name)
    assert row["location"] == "henan"
    assert tuple(row)[1:] == ("", None, None, 0)


# ── 6) restore：真关库重开 + 不中断对照 ────────────────────────────────────


def _transit_frame(db, name: str, arrivals):
    row = _ledger(db, name)
    return {
        "location": row["location"],
        "transit_to": row["transit_to"],
        "remaining": row["transit_distance_remaining"],
        "factor": row["transit_speed_factor"],
        "start_turn": row["transit_start_turn"],
        "arrivals": [dict(a) for a in arrivals],
    }


def _assert_transit_frame_equal(got, expected):
    assert got["location"] == expected["location"]
    assert got["transit_to"] == expected["transit_to"]
    assert got["start_turn"] == expected["start_turn"]
    assert got["arrivals"] == expected["arrivals"]
    if expected["remaining"] is None:
        assert got["remaining"] is None
    else:
        assert got["remaining"] == pytest.approx(expected["remaining"])
    if expected["factor"] is None:
        assert got["factor"] is None
    else:
        assert got["factor"] == pytest.approx(expected["factor"])


def test_mid_countdown_save_reopen_continues_identically(game, tmp_path):
    """F6：中途 backup→关库重开后续 tick，与不中断对照轨逐月 location/四量/抵达一致。"""
    from ming_sim.db import GameDB

    db, state, content = game
    name = active_ming_character(db, content)
    origin, dest = "henan", "liaodong"
    t0 = state.turn
    r0 = _put_in_transit(
        db, content, name, origin=origin, dest=dest,
        speed_factor=1.0, start_turn=t0,
    )
    n = _oracle_n(r0, 1.0)
    assert n >= 3
    db.save_state(state)

    initial_backup = tmp_path / "transit_mid_initial.db"
    db.backup_to(str(initial_backup))

    # 对照轨：同初态不中断逐月 tick
    control: dict[int, dict] = {}
    for k in range(1, n + 1):
        state.turn = t0 + k
        arrivals = tick_transit_arrivals(db, state, content)
        control[k] = _transit_frame(db, name, arrivals)
    assert control[n]["arrivals"] == [{"name": name, "location": dest}]
    assert control[n]["location"] == dest and control[n]["transit_to"] == ""

    # 恢复轨：自初态 backup 另开；中途真关库重开后再续
    mid_k = max(1, n // 2)
    assert mid_k < n

    db_r = GameDB(str(initial_backup), content)
    try:
        state_r = db_r.load_state()
        reload_state_from_db(db_r, state_r, content=content)
        for k in range(1, mid_k + 1):
            state_r.turn = t0 + k
            arrivals = tick_transit_arrivals(db_r, state_r, content)
            _assert_transit_frame_equal(_transit_frame(db_r, name, arrivals), control[k])

        state_r.turn = t0 + mid_k
        db_r.save_state(state_r)
        reopen_path = db_r.path
        db_r.close()

        db2 = GameDB(reopen_path, content)
        try:
            state2 = db2.load_state()
            content.characters[name].location = "junk"
            content.characters[name].transit_to = ""
            content.characters[name].transit_distance_remaining = None
            content.characters[name].transit_speed_factor = None
            content.characters[name].transit_start_turn = 0
            reload_state_from_db(db2, state2, content=content)
            _assert_transit_frame_equal(
                _transit_frame(db2, name, []),
                {**control[mid_k], "arrivals": []},
            )

            for k in range(mid_k + 1, n + 1):
                state2.turn = t0 + k
                arrivals = tick_transit_arrivals(db2, state2, content)
                _assert_transit_frame_equal(_transit_frame(db2, name, arrivals), control[k])
            assert tuple(_ledger(db2, name)) == (dest, "", None, None, 0)
        finally:
            db2.close()
    except BaseException:
        try:
            db_r.close()
        except Exception:
            pass
        raise


# ── 7) 拆除：符号零残留 + payload 无 transit_nudge ─────────────────────────


def test_removed_symbols_have_no_live_residues():
    # 拆成拼接，避免本验收文件被自扫误伤。
    banned = (
        "force_transit_" + "arrivals",
        "_build_transit_" + "nudge",
        "transit_" + "nudge",
    )
    hits = []
    self_name = Path(__file__).name
    scan_paths = []
    for base in ("ming_sim", "tests"):
        for path in (ROOT / base).rglob("*.py"):
            if path.name == self_name:
                continue
            scan_paths.append(path)
    # 现役 fixture 迁移账（非历史 ADR）：旧符号不得残留在 inventory 元数据
    inventory = ROOT / "tests" / "game_fixture_retained_inventory.tsv"
    if inventory.is_file():
        scan_paths.append(inventory)
    for path in scan_paths:
        text = path.read_text(encoding="utf-8")
        for token in banned:
            if token in text:
                hits.append(f"{path.relative_to(ROOT)}:{token}")
    assert hits == [], f"live residues: {hits}"


def test_simulator_payload_has_arrivals_not_nudge(game):
    db, state, content = game
    name = active_ming_character(db, content)
    arrivals = [{"name": name, "location": "beizhili"}]
    payload = build_simulator_payload(
        state, db, "", "", transit_arrivals=arrivals,
    )
    assert "transit_nudge" not in payload
    assert payload["transit_arrivals"] == arrivals
    dumped = json.dumps(payload["transit_arrivals"], ensure_ascii=False)
    assert "remaining" not in dumped
    assert "speed_factor" not in dumped
    note = str(payload.get("data_note") or "")
    assert "transit_nudge" not in note
    assert "transit_arrivals" in note or "抵达" in note


# ── 9) pre_settle 已提交 → simulator 前崩溃恢复 ─────────────────────────────


def _assert_ledger_match(db, name: str, expected):
    loc, to, remaining, factor, start_turn = expected
    row = _ledger(db, name)
    assert row["location"] == loc
    assert row["transit_to"] == to
    assert row["transit_start_turn"] == start_turn
    if remaining is None:
        assert row["transit_distance_remaining"] is None
    else:
        assert row["transit_distance_remaining"] == pytest.approx(remaining)
    if factor is None:
        assert row["transit_speed_factor"] is None
    else:
        assert row["transit_speed_factor"] == pytest.approx(factor)


def _crash_resolve_before_simulator_and_recover(
    *, game, monkeypatch, name: str, origin: str, dest: str,
    speed_factor: float, advance_months: int, expected_arrivals: list,
    after_pre_settle_ledger,
):
    """生产缝：pre_settle+ready0 后 simulator 前崩溃 → settling 重入只读 ctx。"""
    import ming_sim.decree as decree_mod
    from ming_sim.db import GameDB

    db, state, content = game
    t0 = state.turn
    r0 = _put_in_transit(
        db, content, name, origin=origin, dest=dest,
        speed_factor=speed_factor, start_turn=t0,
    )
    state.turn = t0 + advance_months
    state.turn_phase = TurnPhase.REVIEWING.value
    db.save_state(state)

    tick_calls = {"n": 0}
    real_tick = decree_mod.tick_transit_arrivals

    def _count_tick(*a, **k):
        tick_calls["n"] += 1
        return real_tick(*a, **k)

    monkeypatch.setattr(decree_mod, "tick_transit_arrivals", _count_tick)

    def _crash_before_sim(*_a, **_k):
        raise RuntimeError("crash-before-simulator")

    monkeypatch.setattr(decree_mod, "build_simulator_payload", _crash_before_sim)
    with pytest.raises(RuntimeError, match="crash-before-simulator"):
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "测试诏", content=content,
        )

    assert tick_calls["n"] == 1
    assert state.turn_phase == TurnPhase.SETTLING.value
    _assert_ledger_match(db, name, after_pre_settle_ledger)
    ctx = db.get_resolve_context(state.turn)
    assert ctx is not None
    assert ctx["extracted"] is None
    assert ctx["simulator_payload"]["transit_arrivals"] == expected_arrivals

    db2 = GameDB(db.path, content)
    try:
        state2 = db2.load_state()
        assert state2.turn_phase == TurnPhase.SETTLING.value
        reload_state_from_db(db2, state2, content=content)
        _assert_ledger_match(db2, name, after_pre_settle_ledger)

        captured: dict = {}
        real_build = build_simulator_payload

        def _capture_build(*a, **k):
            payload = real_build(*a, **k)
            captured["payload"] = payload
            return payload

        monkeypatch.setattr(decree_mod, "build_simulator_payload", _capture_build)
        monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
        monkeypatch.setattr(
            decree_mod, "simulate_season_with_payload",
            lambda *a, **k: ("本月邸报。", k.get("simulator_payload") or captured.get("payload") or {}),
        )
        monkeypatch.setattr(decree_mod, "build_extractor_shared_context", lambda *a, **k: "")
        monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
        monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: None)
        monkeypatch.setattr(
            decree_mod, "extract_scores_by_modules_with_agno",
            lambda *a, **k: ({}, "out", "in"),
        )

        ticks_before_recovery = tick_calls["n"]
        decree_mod.resolve_directives(
            state2, db2, None, None, [object()], "测试诏", content=content,
        )

        assert tick_calls["n"] == ticks_before_recovery
        _assert_ledger_match(db2, name, after_pre_settle_ledger)
        assert "payload" in captured
        assert captured["payload"]["transit_arrivals"] == expected_arrivals
        assert "transit_nudge" not in captured["payload"]
        names = [row["name"] for row in captured["payload"]["transit_arrivals"]]
        assert names == sorted(set(names))
        # 无幻影人名：payload 抵达表不得出现盘外名字
        known = {
            str(r["name"])
            for r in db2.conn.execute("SELECT name FROM characters").fetchall()
        }
        assert set(names) <= known
        return r0, t0, captured["payload"]
    finally:
        db2.close()


def test_pre_settle_placeholder_persists_transit_arrivals_for_recovery(game, monkeypatch):
    """F4/F6：生产 resolve_directives 缝写入 transit_arrivals；settling 重入只读该键。"""
    db, _state, content = game
    name = active_ming_character(db, content)
    expected = [{"name": name, "location": "beizhili"}]
    r0, _t0, _payload = _crash_resolve_before_simulator_and_recover(
        game=game,
        monkeypatch=monkeypatch,
        name=name,
        origin="henan",
        dest="beizhili",
        speed_factor=1.0,
        advance_months=1,
        expected_arrivals=expected,
        after_pre_settle_ledger=("beizhili", "", None, None, 0),
    )
    assert _oracle_n(r0, 1.0) == 1


def test_pre_settle_no_arrival_month_recovery_keeps_empty_transit_arrivals(game, monkeypatch):
    """F7.9：无抵达月（在途未到）崩溃恢复 → transit_arrivals=[]，无幻影人名，不二次 tick。"""
    db, state, content = game
    name = active_ming_character(db, content)
    t0 = state.turn
    r0 = MATRIX.travel_time("henan", "liaodong")
    assert _oracle_n(r0, 1.0) > 1
    # 次月首减后仍在途：remaining = r0 - 1.0，location 仍为启程地
    after = ("henan", "liaodong", r0 - 1.0, 1.0, t0)
    got_r0, _t0, payload = _crash_resolve_before_simulator_and_recover(
        game=game,
        monkeypatch=monkeypatch,
        name=name,
        origin="henan",
        dest="liaodong",
        speed_factor=1.0,
        advance_months=1,
        expected_arrivals=[],
        after_pre_settle_ledger=after,
    )
    assert got_r0 == pytest.approx(r0)
    assert payload["transit_arrivals"] == []
    assert name not in json.dumps(payload.get("transit_arrivals"), ensure_ascii=False)


def test_arrivals_sorted_by_name_stable(game):
    db, state, content = game
    rows = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "ORDER BY name LIMIT 2"
    ).fetchall()
    names = [str(r["name"]) for r in rows]
    assert len(names) == 2
    t0 = state.turn
    for name in names:
        _put_in_transit(
            db, content, name, origin="henan", dest="beizhili",
            speed_factor=1.0, start_turn=t0,
        )
    state.turn = t0 + 1
    arrivals = tick_transit_arrivals(db, state, content)
    got_names = [a["name"] for a in arrivals]
    assert got_names == sorted(got_names)
    assert set(got_names) == set(names)
