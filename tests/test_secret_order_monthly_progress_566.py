import threading
import pytest
from tests.dossier_test_helpers import create_test_secret_order
from ming_sim.settlement import SettlementContext, settle_delta
"""#566: production settlement owns the durable monthly progress rail."""




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
    return order_id, int(db.dossiers.get_for_secret_order(order_id)["id"])


def _production_session(db, state, content):
    from ming_sim.session import GameSession

    session = GameSession.__new__(GameSession)
    session.db, session.state, session.content = db, state, content
    session.registry = session.llm_config = session.agno_db = None
    session.deaths_this_turn, session.debuts_this_turn = [], []
    session.last_decree = ""
    session._decree_draft_fingerprint = ()
    session.auto_save = lambda *args, **kwargs: None
    return session


def _record_monthly_report(db, state, progress):
    db.record_monthly_dossier_progress(state.turn, [progress])




def test_disclosure_promotes_monthly_report_to_public_event_only_after_disclosure(game):

    db, state, content = game
    order_id, dossier_id = _order(db, state, title="稽核辽饷", tags=["稽核"])
    marker = "密奏查得辽饷兑付名册有重名566"
    _record_monthly_report(db, state, {
        "dossier_id": dossier_id, "progress_band": "核账",
        "memorial_text": marker,
    })
    assert not any(
        str(item.get("source_id") or "").startswith(f"secret_order_disclosure:{order_id}:")
        for item in db._character_knowledge_events("")
    )

    sim_note = "该案已经明发廷议"
    settle_delta(state, db, {'secret_order_updates': [{'order_id': order_id, 'sim_note': sim_note, 'disclosed': True}]}, SettlementContext(content=content))
    public = db._character_knowledge_events("")
    disclosure = next(
        item for item in public
        if str(item.get("source_id") or "").startswith(
            f"secret_order_disclosure:{order_id}:"
        )
    )
    assert marker in disclosure["body"]
    assert sim_note in disclosure["body"]


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
    assert db.dossiers.list_dossier_progress(title_only)
    assert db.dossiers.list_dossier_progress(unrelated)
    assert db.dossiers.list_dossier_progress(short)






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
    assert db.dossiers.get(dossier_id)["due_turn"] != state.turn + 3
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
    from types import SimpleNamespace
    import ming_sim.decree as decree
    import web_app
    from fastapi.testclient import TestClient

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
    fiscal_fault = RuntimeError("post-fiscal failure 566")

    def fail_after_real_flows(flow_db, flow_state):
        ledger_before = _rows(flow_db, "economy_ledger")
        metrics_before = dict(flow_state.metrics)
        original_flows(flow_db, flow_state)
        observed["fiscal_written"] = _rows(flow_db, "economy_ledger") != ledger_before
        observed["metrics_written"] = dict(flow_state.metrics) != metrics_before
        assert observed == {"fiscal_written": True, "metrics_written": True}
        raise fiscal_fault

    monkeypatch.setattr(decree, "apply_fixed_period_flows", fail_after_real_flows)
    from tests.month_chain_helpers import make_light_session
    session = make_light_session(db, state, content)

    if entry == "web":
        web_game = SimpleNamespace(
            _write_gate=threading.Lock(),
            db=db, state=state, content=content, session=session,
            directive_rows=lambda: [], refresh_turn=lambda: None,
            state_payload=lambda: {"turn": state.turn},
        )

        monkeypatch.setattr(web_app, "get_game", lambda: web_game)
        def invoke():
            from tests.sse_helpers import parse_sse_event_pairs
            response = TestClient(web_app.app).post("/api/decree/advance_without_edict/stream")
            assert response.status_code == 200
            return parse_sse_event_pairs(response.text)[-1]
    else:
        invoke = session.advance_without_decree

    # W4 统一停住契约：保留原错为 cause，Web 报告同一失败包。
    if entry == "web":
        kind, detail = invoke()
        assert kind == "error"
        assert isinstance(detail, dict)
        assert detail["stage"] == "pre_settle"
        assert detail["error_type"] == type(fiscal_fault).__name__
        assert detail["error_pack_path"]
        assert detail.get("message") == str(fiscal_fault)
    else:
        from ming_sim.exceptions import SettlementAbort
        with pytest.raises(SettlementAbort) as ei:
            invoke()
        assert ei.value.__cause__ is fiscal_fault
        assert ei.value.stage == "pre_settle"

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
        with pytest.raises(ValueError):
            db.record_monthly_dossier_progress(state.turn, [{
                "dossier_id": invalid_id,
                "progress_band": "伪进展",
                "memorial_text": "不得命中真实案卷",
            }])
    assert db.dossiers.list_dossier_progress(dossier_id) == []

def test_close_secret_order_keeps_model_reports_without_synthesizing_terminal(game):
    """结案只落 result/执行格；不把结案正文写成人物终奏。"""
    db, state, content = game
    eligible_id, eligible = _order(db, state)
    ordinary_id, ordinary = _order(db, state, title="保护堤岸", tags=["河工"])
    state.turn += 1
    db.reign.save_game_state(state)
    reports = [
        {"dossier_id": eligible, "progress_band": "在途", "memorial_text": "已出京"},
        {"dossier_id": ordinary, "progress_band": "在办", "memorial_text": "河工并列密奏"},
    ]
    db.record_monthly_dossier_progress(state.turn, reports)
    before_eligible = db.dossiers.list_dossier_progress(eligible)
    before_ordinary = db.dossiers.list_dossier_progress(ordinary)

    db.close_secret_order(eligible_id, "failed", "护行中止", state.turn)
    db.close_secret_order(ordinary_id, "failed", "河工中止", state.turn)

    after_eligible = db.dossiers.list_dossier_progress(eligible)
    after_ordinary = db.dossiers.list_dossier_progress(ordinary)
    assert after_eligible == before_eligible
    assert after_ordinary == before_ordinary
    assert all(not row.get("is_terminal") for row in after_eligible)
    assert db.dossiers.get(eligible)["status"] == "closed"
    assert db.dossiers.get(ordinary)["status"] == "closed"


def test_character_terminal_status_closes_orders_without_synthetic_memorial(game):
    """人物终态关密令/案卷；终态落账，不污染既有模型月报。"""
    db, state, content = game
    assignee = _actor(db)
    chained_id, chained_dossier = _order(db, state, title="护行辽饷")
    unchained_id, unchained_dossier = _order(
        db, state, title="清查库藏", tags=["财政"],
    )
    state.turn += 1
    db.reign.save_game_state(state)
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
    before_chained = db.dossiers.list_dossier_progress(chained_dossier)
    before_unchained = db.dossiers.list_dossier_progress(unchained_dossier)

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
    assert db.dossiers.get(chained_dossier)["status"] == "closed"
    assert db.dossiers.get(unchained_dossier)["status"] == "closed"
    chained_progress = db.dossiers.list_dossier_progress(chained_dossier)
    unchained_progress = db.dossiers.list_dossier_progress(unchained_dossier)
    assert chained_progress == before_chained
    assert unchained_progress == before_unchained
    assert all(not row.get("is_terminal") for row in chained_progress)
    assert unchained_progress
