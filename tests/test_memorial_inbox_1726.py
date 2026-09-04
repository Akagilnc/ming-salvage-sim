"""#1726：奏疏收件箱 — 读取端接通 + 未读模型。

验收入口：state_payload → 面板同源计数；已读随存档持久化。
"""

from __future__ import annotations

import threading

from ming_sim.db import GameDB
from ming_sim.models import TurnPhase


def _executing_with_owner(db, state, *, owner: str, token: str = "m1726"):
    did = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"着{owner}从国库拨银{token}",
        target_kind="issue",
        target_id=f"land-{token}",
        executor_kind="character",
        executor_id=owner,
        participants=[{"character_id": owner, "tier": "主办"}],
    )
    db.apply_dossier_promulgation(state, did, "promulgated")
    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing' WHERE id=?", (did,),
    )
    db.conn.commit()
    return did


def _active_name(db) -> str:
    return db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"]


def test_new_game_memorial_inbox_empty(game):
    """新局首月无奏报 → 0 件；不得拿局势条数充数。"""
    db, state, _content = game
    assert db.list_player_memorials() == []
    assert db.unread_memorial_count() == 0
    # 开局常有局势，但奏疏计数必须与之脱钩
    assert len(db.list_active_issues()) >= 1


def test_progress_and_denunciation_project_as_memorials(game):
    """两类真奏疏入收件箱；进度奏报署承办人，检举署 accuser_name；正文原样。"""
    db, state, _content = game
    owner = _active_name(db)
    did = _executing_with_owner(db, state, owner=owner, token="prog")
    body_progress = "臣已拨银十万两，库藏尚可周转。"
    pid = db.record_dossier_progress(
        did, state.turn, "在办", body_progress,
        origin="dossier-report:monthly_errand", commit=True,
    )

    accuser = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name LIMIT 1",
        (owner,),
    ).fetchone()["name"]
    body_den = f"{accuser}奏：{owner}清丈有私，请皇上按问。"
    hits = db.accept_faction_denunciations(
        state,
        [{
            "accuser_name": accuser,
            "subject_name": owner,
            "target_dossier_id": did,
            "memorial_text": body_den,
        }],
        commit=True,
    )
    assert len(hits) == 1
    den_id = int(hits[0]["id"])

    rows = db.list_player_memorials()
    assert len(rows) == 2
    by_key = {r["key"]: r for r in rows}

    prog = by_key[f"progress:{pid}"]
    assert prog["kind"] == "progress"
    assert prog["author_name"] == owner
    assert prog["memorial_text"] == body_progress
    assert prog["unread"] is True
    # 玩家面不得夹带结构化字段
    for banned in ("progress_band", "origin", "payload", "target_dossier_id", "dossier_id"):
        assert banned not in prog

    den = by_key[f"denunciation:{den_id}"]
    assert den["kind"] == "denunciation"
    assert den["author_name"] == accuser
    assert den["memorial_text"] == body_den
    assert den["unread"] is True

    assert db.unread_memorial_count() == 2


def test_mark_read_binds_to_row_not_dossier_and_persists(game):
    """点开即已读；同案卷新奏报重回未读；已读随库持久化。"""
    db, state, content = game
    owner = _active_name(db)
    did = _executing_with_owner(db, state, owner=owner, token="read")

    pid1 = db.record_dossier_progress(
        did, state.turn, "在途", "首批已出京",
        origin="dossier-report:monthly_errand", commit=True,
    )
    key1 = f"progress:{pid1}"
    assert db.unread_memorial_count() == 1

    db.mark_memorials_read([key1])
    assert db.unread_memorial_count() == 0
    rows = db.list_player_memorials()
    assert rows[0]["key"] == key1
    assert rows[0]["unread"] is False

    # 同案卷再来新奏报 → 新 key 未读，旧 key 仍已读
    pid2 = db.record_dossier_progress(
        did, state.turn + 1, "在办", "次月续报已至",
        origin="dossier-report:monthly_errand", commit=True,
    )
    key2 = f"progress:{pid2}"
    assert db.unread_memorial_count() == 1
    by_key = {r["key"]: r for r in db.list_player_memorials()}
    assert by_key[key1]["unread"] is False
    assert by_key[key2]["unread"] is True

    # 持久化：重开同一库路径后已读仍在
    path = db.path
    db.close()
    restored = GameDB(path, content)
    try:
        assert restored.unread_memorial_count() == 1
        by_key = {r["key"]: r for r in restored.list_player_memorials()}
        assert by_key[key1]["unread"] is False
        assert by_key[key2]["unread"] is True
        restored.mark_memorials_read([key2])
        assert restored.unread_memorial_count() == 0
    finally:
        restored.close()


def test_state_payload_memorials_and_mark_read_api(game, monkeypatch):
    """真实入口：GET /api/game/state 投影 + POST /api/memorials/read 后计数归零。"""
    from types import SimpleNamespace

    import web_app
    from fastapi.testclient import TestClient

    db, state, content = game
    owner = _active_name(db)
    did = _executing_with_owner(db, state, owner=owner, token="api")
    body = "臣工本月办理进度奏报。"
    pid = db.record_dossier_progress(
        did, state.turn, "在办", body,
        origin="dossier-report:monthly_errand", commit=True,
    )
    key = f"progress:{pid}"

    # 与 c3/s2 同形轻壳：经真 state_payload 投影链；object.__new__ 拼装可暂留。
    runtime = object.__new__(web_app.WebGame)
    runtime.favorites = set()
    runtime.session = SimpleNamespace(
        db=db,
        state=state,
        content=content,
        pending_count=lambda: 0,
        pending_decisions=lambda: [],
        victory=lambda: {"status": "ongoing", "summary": ""},
        previous_summary="",
        last_decree="",
        last_report="",
    )
    runtime.directive_rows = lambda: []
    runtime.issue_payloads = lambda: []
    runtime.legacies_payload = lambda: []
    runtime.closed_this_turn_payloads = lambda: []
    runtime.map_nodes = lambda: []
    runtime.ending_payload = lambda: None
    runtime.public_character = lambda c: {"name": getattr(c, "name", "")}
    runtime.character_power_id = lambda c: "ming"
    runtime._write_gate = threading.Lock()
    runtime._runtime_write_gate = lambda: runtime._write_gate

    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    client = TestClient(web_app.app)

    # 验收第 7 条：真 HTTP GET /api/game/state；断接线（去 memorials 键）须转红。
    state_resp = client.get("/api/game/state")
    assert state_resp.status_code == 200
    state_payload = state_resp.json()
    assert any(m.get("key") == key for m in state_payload["memorials"])
    memorial = next(m for m in state_payload["memorials"] if m["key"] == key)
    assert memorial["memorial_text"] == body
    assert memorial["author_name"] == owner
    assert memorial["unread"] is True
    assert state_payload["unread_memorial_count"] == 1

    # #1726 F1：核账相位经真 HTTP 入口 409，未读不得被吞。
    for phase in (TurnPhase.SETTLING.value, TurnPhase.AWAITING_DECISION.value):
        state.turn_phase = phase
        blocked = client.post("/api/memorials/read", json={"keys": [key]})
        assert blocked.status_code == 409
        assert db.unread_memorial_count() == 1

    state.turn_phase = TurnPhase.SUMMONING.value
    resp = client.post("/api/memorials/read", json={"keys": [key]})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["unread_memorial_count"] == 0
    assert all(not m["unread"] for m in payload["memorials"])
    assert db.unread_memorial_count() == 0


def test_progress_without_owner_uses_diegetic_fallback(game):
    """无可解析承办人时不得裸露 id。"""
    db, state, _content = game
    did = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="清丈无主名",
        target_kind="issue",
        target_id="land-orphan-1726",
    )
    db.apply_dossier_promulgation(state, did, "promulgated")
    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing', executor_id='', executor_kind='', "
        "participant_roster='[]' WHERE id=?",
        (did,),
    )
    db.conn.commit()
    pid = db.record_dossier_progress(
        did, state.turn, "在办", "无主名奏报正文",
        origin="dossier-report:monthly_errand", commit=True,
    )
    row = next(r for r in db.list_player_memorials() if r["key"] == f"progress:{pid}")
    assert row["author_name"]
    assert row["author_name"] != str(did)
    assert not row["author_name"].isdigit()
