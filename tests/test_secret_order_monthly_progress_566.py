"""#566: production settlement owns the durable monthly progress rail."""

import json
import threading

import pytest
from tests.dossier_test_helpers import create_test_secret_order


def _actor(db):
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"])


def _order(db, state, title="护行辽饷", tags=None, deadline=4):
    order_id = create_test_secret_order(db,
        state, _actor(db), title, "逐月办理", tags or ["护行"],
        deadline_months=deadline,
        covert_task={
            "kind": "护行差务",
            "axes": ["实务事功"],
            "direction": 1,
            "delivery": {
                "unit": "万两", "target_units": float(deadline or 1), "effect_sign": -1,
                "purpose": "辽饷", "category": "军饷", "account": "国库",
            },
        },
    )
    return order_id, int(db.get_dossier_for_secret_order(order_id)["id"])


def _production_session(db, state, content):
    from ming_sim.session import GameSession

    session = GameSession.__new__(GameSession)
    session.db, session.state, session.content = db, state, content
    session.registry = session.llm_config = session.agno_db = None
    session.deaths_this_turn, session.debuts_this_turn = [], []
    session.last_decree = session.last_report = ""
    session._decree_draft_fingerprint = ()
    session._scene_registry = None
    session._beat_generator = None
    session.auto_save = lambda *args, **kwargs: None
    return session


def _canned_monthly_settlement(monkeypatch, extractor_calls):
    """Keep the production settlement pipeline; replace only external LLM seams."""
    from tests.settlement_seam_helpers import canned_full_settlement

    def _track_world(*_a, **_k):
        extractor_calls.append("world")
        return "本月公开邸报"

    canned_full_settlement(monkeypatch, narrative="本月公开邸报")
    monkeypatch.setattr("ming_sim.month_chain.run_world_segment_text", _track_world)


def _record_monthly_report(db, state, progress):
    db.record_monthly_dossier_progress(state.turn, [progress])


def test_only_emperor_private_payload_shows_monthly_report(game):

    db, state, content = game
    order_id, dossier_id = _order(db, state)
    marker = "首批饷车已验山海关关防566"
    _record_monthly_report(db, state, {
        "dossier_id": dossier_id, "progress_band": "在途核验",
        "memorial_text": marker,
    })

    # Emperor-facing secret-order product payload reads the canonical rail.
    emperor_order = next(item for item in db.list_secret_orders() if item["id"] == order_id)
    assert emperor_order["dossier_progress"][-1]["memorial_text"] == marker

    # The report does not leak into the assignee's on-demand material directory.
    from ming_sim.materials import list_materials, prepare_character_materials, read_material
    assignee = content.characters[emperor_order["minister_name"]]
    prepared = prepare_character_materials(db, state, assignee)
    private_blob = "\n".join(
        read_material(prepared.root, path)
        for path in list_materials(prepared.root)
    )
    assert marker not in private_blob


def test_disclosure_promotes_monthly_report_to_public_event_only_after_disclosure(game):
    from ming_sim.issues import apply_score_extraction

    db, state, content = game
    order_id, dossier_id = _order(db, state, title="稽核辽饷", tags=["稽核"])
    marker = "密奏查得辽饷兑付名册有重名566"
    _record_monthly_report(db, state, {
        "dossier_id": dossier_id, "progress_band": "核账",
        "memorial_text": marker,
    })
    assert marker not in str(db._character_knowledge_events(""))

    apply_score_extraction(db, state, {"secret_order_updates": [{
        "order_id": order_id, "sim_note": "该案已经明发廷议", "disclosed": True,
    }]}, content=content)
    public = db._character_knowledge_events("")
    disclosure = next(
        item for item in public
        if str(item.get("source_id") or "").startswith(
            f"secret_order_disclosure:{order_id}:"
        )
    )
    assert marker in disclosure["body"]


def test_titles_do_not_classify_and_all_active_secret_orders_are_candidates(game):
    db, state, content = game
    _, title_only = _order(db, state, title="保护堤岸", tags=["河工"])
    _, unrelated = _order(db, state, title="清查库藏", tags=["财政"])
    _, short = _order(db, state, tags=["护行"], deadline=1)

    ids = {title_only, unrelated, short}
    assert {item["dossier_id"] for item in db.list_monthly_dossier_progress_nudges()} == ids
    reports = [
        {
            "dossier_id": did,
            "progress_band": "在办",
            "memorial_text": f"密奏{did}",
        }
        for did in ids
    ]
    db.record_monthly_dossier_progress(state.turn, reports)
    assert db.list_dossier_progress(title_only)
    assert db.list_dossier_progress(unrelated)
    assert db.list_dossier_progress(short)


def test_only_an_existing_monthly_chain_gets_terminal_progress(game):
    db, state, content = game
    eligible_id, eligible = _order(db, state)
    ordinary_id, ordinary = _order(db, state, title="保护堤岸", tags=["河工"])
    state.turn += 1
    db.save_state(state)
    reports = [
        {"dossier_id": eligible, "progress_band": "在途", "memorial_text": "已出京"},
        {"dossier_id": ordinary, "progress_band": "在办", "memorial_text": "河工并列密奏"},
    ]
    db.record_monthly_dossier_progress(state.turn, reports)

    db.close_secret_order(eligible_id, "failed", "护行中止", state.turn)
    db.close_secret_order(ordinary_id, "failed", "河工中止", state.turn)

    assert db.list_dossier_progress(eligible)[-1]["is_terminal"] is True
    assert db.list_dossier_progress(ordinary)


def test_character_terminal_status_closes_secret_orders_through_canonical_progress_rail(game):
    db, state, content = game
    assignee = _actor(db)
    chained_id, chained_dossier = _order(db, state, title="护行辽饷")
    unchained_id, unchained_dossier = _order(
        db, state, title="清查库藏", tags=["财政"],
    )
    state.turn += 1
    db.save_state(state)
    reports = [
        {
            "dossier_id": chained_dossier,
            "progress_band": "在途",
            "memorial_text": "首批已出京",
        },
        {
            "dossier_id": unchained_dossier,
            "progress_band": "在办",
            "memorial_text": "库藏并列密奏",
        },
    ]
    db.record_monthly_dossier_progress(state.turn, reports)

    db.set_character_status(state, assignee, "dead", "途中病故")

    orders = {
        int(row["id"]): row
        for row in db.conn.execute(
            "SELECT id,status,result FROM secret_orders WHERE id IN (?, ?)",
            (chained_id, unchained_id),
        ).fetchall()
    }
    assert orders[chained_id]["status"] == "failed"
    assert orders[unchained_id]["status"] == "failed"
    assert "人物终态：dead；途中病故" in orders[chained_id]["result"]
    assert db.get_decree_dossier(chained_dossier)["status"] == "closed"
    assert db.get_decree_dossier(unchained_dossier)["status"] == "closed"
    terminal = db.list_dossier_progress(chained_dossier)[-1]
    assert terminal["is_terminal"] is True
    assert "人物终态：dead；途中病故" in terminal["memorial_text"]
    assert db.list_dossier_progress(unchained_dossier)


def test_current_secret_order_deadline_controls_monthly_eligibility(game):
    db, state, content = game
    order_id, dossier_id = _order(db, state, deadline=1)
    assert [item["dossier_id"] for item in db.list_monthly_dossier_progress_nudges()] == [dossier_id]

    rushed = db.rush_secret_order(order_id, state, 3)
    row = db.conn.execute(
        "SELECT deadline_span FROM secret_orders WHERE id=?", (order_id,),
    ).fetchone()
    assert rushed["due_turn"] == state.turn + 1
    assert row["deadline_span"] == 1
    assert [item["dossier_id"] for item in db.list_monthly_dossier_progress_nudges()] == [dossier_id]
    db.update_secret_order_by_id(state, order_id, "护行辽饷", "继续逐月办理", ["护行"], 3)
    assert db.get_decree_dossier(dossier_id)["due_turn"] != state.turn + 3
    assert [item["dossier_id"] for item in db.list_monthly_dossier_progress_nudges()] == [dossier_id]


def _stage_routed_secret_order(db, state, action, deadline):
    target_id = None
    if action == "更新":
        target_id, _ = _order(db, state, deadline=1 if deadline > 1 else 3)
    pending_id = db.stage_pending_action(
        state.turn, "secret_order", action, _actor(db), {
            "title": "护行辽饷", "content": "逐月稽核", "tags": ["护行"],
            "new_title": "护行辽饷", "new_content": "继续逐月稽核",
            "deadline_months": deadline,
            "covert_task": {
                "kind": "护行差务",
                "axes": ["实务事功"],
                "direction": 1,
                "delivery": {
                    "unit": "万两", "target_units": float(max(deadline, 1)), "effect_sign": -1,
                    "purpose": "辽饷", "category": "军饷", "account": "国库",
                },
            },
        }, target_id=target_id,
    )
    return pending_id, target_id


def _rows(db, table, where="", params=()):
    import math

    sql = f'SELECT * FROM "{table}"'
    if where:
        sql += " WHERE " + where
    sql += " ORDER BY rowid"
    return [{
        key: ("<NaN>" if isinstance(value, float) and math.isnan(value) else value)
        for key, value in dict(row).items()
    } for row in db.conn.execute(sql, params).fetchall()]


def _rollback_snapshot(db, state, pending_ids):
    fiscal_tables = [row["name"] for row in db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND "
        "(name LIKE '%fiscal%' OR name LIKE '%economy%' OR name LIKE '%ledger%') "
        "ORDER BY name"
    ).fetchall()]
    fiscal = {name: _rows(db, name) for name in fiscal_tables}
    # load_state refreshes this cache's bookkeeping timestamp even after rollback;
    # account identity/balance are the external fiscal state under test.
    for row in fiscal.get("economy_accounts", []):
        row.pop("updated_at", None)
    return {
        "pending": [_rows(db, "pending_actions", "id=?", (pid,))[0] for pid in pending_ids],
        "directives": _rows(db, "turn_directives"),
        "dossiers": _rows(db, "decree_dossiers", "status='proposed'"),
        "orders": _rows(db, "secret_orders"),
        "knowledge": _rows(db, "character_knowledge_sources"),
        "fiscal": fiscal,
        "metrics": dict(state.metrics),
        "clock": (state.turn, state.year, state.period, state.turn_phase),
    }


@pytest.mark.parametrize("entry", ["cli", "web"])
@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_real_no_edict_entries_roll_back_every_external_state_after_fiscal_write(
    game, monkeypatch, entry,
):
    """A post-fiscal fault cannot expose preview-time directive materialization."""
    from contextlib import contextmanager
    from types import SimpleNamespace
    import ming_sim.decree as decree
    import ming_sim.session as session_mod
    import web_app

    db, state, content = game
    turn = state.turn
    secret_id, _ = _stage_routed_secret_order(db, state, "新建", deadline=3)
    directive_id = db.stage_pending_action(
        turn, "directive", "拟旨", _actor(db), {
            "text": "着户部清核辽饷。", "actor": _actor(db),
            "dossier_action_type": "policy",
            "target_kind": "issue", "target_id": "liao-pay-audit-566",
        },
    )
    pending_ids = [secret_id, directive_id]
    before = _rollback_snapshot(db, state, pending_ids)
    observed = {"fiscal_written": False, "metrics_written": False}
    original_flows = decree.apply_fixed_period_flows

    def fail_after_real_flows(flow_db, flow_state):
        ledger_before = _rows(flow_db, "economy_ledger")
        metrics_before = dict(flow_state.metrics)
        result = original_flows(flow_db, flow_state)
        observed["fiscal_written"] = _rows(flow_db, "economy_ledger") != ledger_before
        observed["metrics_written"] = dict(flow_state.metrics) != metrics_before
        assert observed == {"fiscal_written": True, "metrics_written": True}
        raise RuntimeError("post-fiscal failure 566")

    monkeypatch.setattr(decree, "apply_fixed_period_flows", fail_after_real_flows)
    monkeypatch.setattr(
        session_mod, "write_decree_with_agno",
        lambda _config, _agno, _state, directives, db=None: "\n".join(
            str(item["text"]) for item in directives
        ),
    )
    session = _production_session(db, state, content)

    if entry == "web":
        web_game = SimpleNamespace(
            _write_gate=threading.Lock(),
            db=db, state=state, content=content, session=session,
            directive_rows=lambda: [], refresh_turn=lambda: None,
            state_payload=lambda: {"turn": state.turn},
        )

        @contextmanager
        def unlocked(_game):
            yield

        monkeypatch.setattr(web_app, "get_game", lambda: web_game)
        monkeypatch.setattr(web_app, "_serialized_web_write", unlocked)
        invoke = web_app.api_advance_without_edict
    else:
        invoke = session.advance_without_decree

    # cli：session 层 RuntimeError 原样穿透。
    # web：#1433 可读错误包契约——Exception → 500 + {"message": str(e)}（回滚语义不变）。
    if entry == "web":
        with pytest.raises(web_app.HTTPException) as exc_info:
            invoke()
        assert exc_info.value.status_code == 500
        detail = exc_info.value.detail
        if isinstance(detail, dict):
            assert "post-fiscal failure 566" in str(detail.get("message") or detail)
        else:
            assert "post-fiscal failure 566" in str(detail)
    else:
        with pytest.raises(RuntimeError, match="post-fiscal failure 566"):
            invoke()

    assert observed == {"fiscal_written": True, "metrics_written": True}
    after = _rollback_snapshot(db, state, pending_ids)
    for key in ("pending", "directives", "dossiers", "orders", "knowledge", "metrics", "clock"):
        assert after[key] == before[key], key
    for table, rows in before["fiscal"].items():
        assert after["fiscal"][table] == rows, table
    reloaded = db.load_state()
    assert (reloaded.turn, reloaded.year, reloaded.period, reloaded.turn_phase) == before["clock"]
    assert reloaded.metrics == before["metrics"]


def test_missing_bad_unknown_and_duplicate_reports_are_rejected(game):
    db, state, _content = game
    _, dossier_id = _order(db, state)
    import pytest
    with pytest.raises(ValueError):
        db.record_monthly_dossier_progress(state.turn, None)
    with pytest.raises(ValueError):
        db.record_monthly_dossier_progress(state.turn, {"dossier_id": dossier_id})
    with pytest.raises(ValueError):
        db.record_monthly_dossier_progress(state.turn, [
        {"dossier_id": 999999, "progress_band": "伪", "memorial_text": "伪进展"},
        {"dossier_id": dossier_id, "progress_band": "", "memorial_text": "缺档"},
        {"dossier_id": dossier_id, "progress_band": "启程", "memorial_text": "首批出京"},
            {"dossier_id": dossier_id, "progress_band": "重复", "memorial_text": "不得覆盖"},
        ])
    for invalid_id in (True, 1.0, 0, -1):
        with pytest.raises(ValueError, match="案卷编号无效"):
            db.record_monthly_dossier_progress(state.turn, [{
                "dossier_id": invalid_id,
                "progress_band": "伪进展",
                "memorial_text": "不得命中真实案卷",
            }])
    assert db.list_dossier_progress(dossier_id) == []
