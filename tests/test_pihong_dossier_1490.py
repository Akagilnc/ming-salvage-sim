"""Retained dossier binding, typed imperial push and endorsement contracts."""
from __future__ import annotations


import copy

import json


import pytest
from tests.conftest import wait_for_background_jobs


import ming_sim.decree as decree_mod

import ming_sim.session as session_mod
from tests.test_web_audience_night_498 import _fake_settlement_llm


@pytest.fixture(autouse=True)
def rescript_llm_boundary(monkeypatch):
    from tests.month_chain_helpers import empty_rescript_response
    monkeypatch.setattr("ming_sim.rescript_draft.run_rescript_text", empty_rescript_response)


_ROSTER_LEAD = '毕自严'

_ROSTER = [{'character_id': _ROSTER_LEAD, 'tier': '主办', 'role': '总核', 'delegator_id': None}]


def _summonable_name(db):
    return db.conn.execute("SELECT name FROM characters WHERE status='active' AND power_id='ming' ORDER BY name LIMIT 1").fetchone()[0]

def _658_plant_stalled_deliberation(db, state, *, title='议而不决'):
    """已落库的无人站台原案，与退役的 deliberate 写核无关。"""
    key = f"rescript_draft:{state.turn}:0"
    did = db.create_decree_dossier(
        state, action_type="special_decree", decree_text=title, target_kind="issue", target_id=key,
        payload={"decision_key": key, "deliberation_state": "stalled"},
    )
    db.insert_issue(state, kind="situation", title=title, origin_kind="decree", origin_ref=f"dossier:{did}")
    return db.get_decree_dossier(did), key

def test_658_stalled_excluded_from_promulgation_validation(game, monkeypatch):
    """冷场案卷不进过月补跑判官；同月普通案卷仍补跑。"""
    import ming_sim.decree as decree_mod
    import ming_sim.month_chain as month_chain
    db, state, content = game
    stalled, _ = _658_plant_stalled_deliberation(db, state, title='冷场')
    stalled_id = int(stalled['id'])
    normal_id = int(db.create_decree_dossier(state, action_type='policy', decree_text='清核河工', target_kind='issue', target_id=f'river-{state.turn}'))
    _fake_settlement_llm(monkeypatch, narrative="预推")
    from ming_sim.decree_forecast import produce_forecast_product as real_product
    seen: list[int] = []

    def product(_session, snapshot):
        candidate = snapshot.get('candidate') or {}
        dossier_id = int(snapshot.get('dossier_id') or candidate.get('id') or 0)
        seen.append(dossier_id)
        return real_product(_session, snapshot)
    monkeypatch.setattr(month_chain, 'run_world_segment_text', lambda *a, **k: '')
    monkeypatch.setattr('ming_sim.decree_forecast.produce_forecast_product', product)
    decree_mod.resolve_directives(state, db, None, object(), '清核河工', content=content)
    assert stalled_id not in seen
    assert normal_id in seen
    assert db.get_decree_dossier(stalled_id)['status'] == 'proposed'
    assert db.get_decree_dossier(stalled_id)['payload'].get('deliberation_state') == 'stalled'

def test_658_endorsement_provenance_xor(game):
    """#658：背书 provenance 恰为 chat_turn 或 decision_key 之一。"""
    db, state, content = game
    minister = _summonable_name(db)
    did = db.create_decree_dossier(state, action_type='policy', decree_text='试', target_kind='policy', target_id='t')
    chat = db.create_chat_turn(state, minister, '658-xor', 0)
    db.add_dossier_endorsement(did, form='会签', endorser_id=minister, source_chat_turn_id=chat)
    row = db.list_dossier_endorsements(did)[0]
    assert row['source_chat_turn_id'] == chat and row['decision_key'] == ''
    eid2 = db.add_dossier_endorsement(did, form='当面站台', endorser_id=minister, decision_key='rescript_draft:1:0')
    rows = {e['id']: e for e in db.list_dossier_endorsements(did)}
    assert rows[eid2]['decision_key'] == 'rescript_draft:1:0'
    assert rows[eid2]['source_chat_turn_id'] == 0
    with pytest.raises(ValueError):
        db.add_dossier_endorsement(did, form='会签', endorser_id=minister, source_chat_turn_id=chat, decision_key='x')
    with pytest.raises(ValueError):
        db.add_dossier_endorsement(did, form='会签', endorser_id=minister)

@pytest.mark.parametrize("historical", [False, True])
def test_658_imperial_push_uses_rescript_original_and_key(game, monkeypatch, historical):
    from tests.month_chain_helpers import make_light_session
    db, state, content = game
    stalled, _ = _658_plant_stalled_deliberation(db, state)
    did = int(stalled["id"])
    if historical:
        db.conn.execute("UPDATE decree_dossiers SET created_turn=? WHERE id=?", (state.turn - 1, did))
        db.conn.commit()
    _fake_settlement_llm(monkeypatch)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    assert session.resolve_turn(allow_empty_decree=True).awaiting
    row = next(r for r in session.pending_decisions() if r["event_id"] == f"deliberation:{did}")
    choice = {"decision_key": row["decision_key"], "action": "imperial_push", "note": "  朕独担  "}
    session.submit_hitl_choices([choice], write_gate=session._write_gate)
    pushed = db.get_decree_dossier(did)
    assert pushed["promulgation_decision"] == "promulgated"
    assert pushed["status"] != "proposed"
    assert pushed["payload"]["deliberation_state"] == "backed"
    assert pushed["payload"]["imperial_push_note"] == choice["note"]
    assert len(db.list_decree_dossiers()) == 1
    endorsements = db.list_dossier_endorsements(did)
    assert len(endorsements) == 1
    assert endorsements[0]["decision_key"] == choice["decision_key"]
    assert int(endorsements[0]["source_chat_turn_id"] or 0) == 0
    assert not db.list_issued_directives()
    assert not db.conn.execute("SELECT id FROM issues WHERE origin_ref=? AND status='active'", (f"dossier:{did}",)).fetchone()
    session.resolve_turn(allow_empty_decree=True)
    assert len(db.list_dossier_endorsements(did)) == 1

@pytest.mark.parametrize("failure", ["consume", "scope", "account"])
def test_midzhi_rescript_model_uses_original_key_and_existing_gate(game, monkeypatch, failure):
    from tests.month_chain_helpers import make_light_session
    db, state, content = game
    captured = []

    def rescript(session, *, officers, backlog, answer=None):
        if answer is None:
            return json.dumps({"actor_name": officers[-1]["name"], "revisions": [],
                               "items": [{"title": "急务", "context": "原奏与拟旨", "options": []}]})
        captured.append(answer)
        payload = {"dossier_action_type": "policy", "target_kind": "issue",
                   "target_id": "urgent", "due_turn": int(state.turn) + 2,
                   "locality_scope": "none", "participant_roster": copy.deepcopy(_ROSTER)}
        if len(captured) == 1 and failure == "scope":
            payload.update(dossier_action_type="authorization", scope="region:",
                           holder_id=officers[-1]["name"])
        elif len(captured) == 1 and failure == "account":
            payload.update(dossier_action_type="grant_allocation", grant_action="赏赉",
                           amount=1, account="unknown")
        return json.dumps({"disposition": "settled", "text": "", "decree": {
            "text": "御笔旨文", "payload": payload,
        }})

    gate = []
    _fake_settlement_llm(monkeypatch)
    monkeypatch.setattr("ming_sim.rescript_draft.run_rescript_text", rescript)
    from ming_sim.decree_forecast import produce_forecast_product as real_product
    def forecast(_session, snapshot):
        gate.append(snapshot["candidate"]["id"])
        return real_product(_session, snapshot)
    monkeypatch.setattr("ming_sim.decree_forecast.produce_forecast_product", forecast)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    assert session.resolve_turn(allow_empty_decree=True).awaiting
    original = session.pending_decisions()[0]
    choice = {"decision_key": original["decision_key"], "action": "midzhi", "note": "  朕亲拟\n旨意  "}
    real_endorse = db.add_dossier_endorsement
    def interrupted_endorse(*args, **kwargs):
        real_endorse(*args, **kwargs)
        raise RuntimeError("injected consumption failure")
    if failure == "consume":
        monkeypatch.setattr(db, "add_dossier_endorsement", interrupted_endorse)
    from ming_sim.exceptions import SettlementAbort
    from ming_sim.month_chain import _load_chain
    with pytest.raises(SettlementAbort):
        session.submit_hitl_choices([choice], write_gate=session._write_gate)
    saved = _load_chain(db, int(state.turn))
    assert bool(saved["rescript_answer_products"]) == (failure == "consume")
    assert not saved["rescript_consumed"]
    assert not db.list_decree_dossiers()
    monkeypatch.setattr(db, "add_dossier_endorsement", real_endorse)
    session = make_light_session(db, db.load_state(content), content)
    session.llm_config = object()
    session.resolve_turn(allow_empty_decree=True)
    assert len(captured) == (1 if failure == "consume" else 2)
    saved = _load_chain(db, int(state.turn))
    assert saved["rescript_consumed"] == [original["decision_key"]]
    assert not saved["rescript_answer_products"]
    dossiers = db.list_decree_dossiers()
    assert len(dossiers) == 1
    dossier = dossiers[0]
    assert gate == [int(dossier["id"])]
    assert dossier["payload"]["decision_key"] == original["decision_key"]
    assert dossier["payload"]["mode"] == "midzhi"
    assert dossier["due_turn"] == int(state.turn) + 2
    assert captured[0]["choice"] == choice
    assert db.list_dossier_endorsements(int(dossier["id"]))[0]["decision_key"] == original["decision_key"]
    session.resolve_turn(allow_empty_decree=True)
    assert len(db.list_decree_dossiers()) == 1
    assert gate == [int(dossier["id"])]


@pytest.mark.parametrize("desk_kind", ["mixed", "decision", "empty"])
def test_1589_keyless_batch_rejected_without_writes(game, monkeypatch, desk_kind):
    """Stable identity admission survives six-action retirement, including empty desks."""
    from ming_sim.models import TurnPhase
    from tests.month_chain_helpers import canned_full_settlement, make_light_session

    db, state, content = game
    canned_full_settlement(monkeypatch)
    if desk_kind != "empty":
        monkeypatch.setattr("ming_sim.month_chain.run_world_segment_text", lambda *a, **k:
            '<<DECISION>>{"title":"请旨","context":"c","options":[{"label":"准"},{"label":"缓"}]}<<END>>')
    if desk_kind == "mixed":
        monkeypatch.setattr("ming_sim.rescript_draft.run_rescript_text", lambda session, *, officers, backlog, answer=None:
            json.dumps({"actor_name": officers[-1]["name"], "revisions": [],
                        "items": [{"title": "急务", "context": "c", "options": [{"label": "准"}]}]})
            if answer is None else json.dumps({"disposition": "settled", "text": ""}))
    monkeypatch.setattr("ming_sim.agents.create_world_segment_agent", lambda *a, **k: object())
    monkeypatch.setattr("ming_sim.agents.run_agent_text", lambda *a, **k: "")
    session = make_light_session(db, state, content)
    session.llm_config = object()
    session.resolve_turn(allow_empty_decree=True)
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    turn = int(state.turn)
    rows = session.pending_decisions()
    assert {r["kind"] for r in rows} == {
        "mixed": {"rescript_draft", "decision"}, "decision": {"decision"}, "empty": set(),
    }[desk_kind]
    dossier_ids = {r["id"] for r in db.list_decree_dossiers()}
    events = [tuple(r) for r in db.conn.execute("SELECT event_id, terminal_state, source FROM event_triggers ORDER BY event_id")]
    choices = [{"label": "准"}]
    if desk_kind == "mixed":
        choices.insert(0, {"decision_key": rows[0]["decision_key"], "label": "准"})
    invalid_batches = [choices, [{"decision_key": "decision:999:0", "label": "准"}]]
    if rows:
        keyed = {"decision_key": rows[0]["decision_key"], "label": "准"}
        invalid_batches.append([keyed, keyed])
    for batch in invalid_batches:
        with pytest.raises(ValueError):
            session.submit_hitl_choices(batch, write_gate=session._write_gate)
    after = session.pending_decisions()
    assert {r["decision_key"] for r in after} == {r["decision_key"] for r in rows}
    assert all(r["status"] == "pending" and not r["choice"] for r in after)
    assert {r["id"] for r in db.list_decree_dossiers()} == dossier_ids
    assert [tuple(r) for r in db.conn.execute("SELECT event_id, terminal_state, source FROM event_triggers ORDER BY event_id")] == events
    assert db.load_state(content).turn_phase == TurnPhase.AWAITING_DECISION.value
    assert int(state.turn) == turn
    session.submit_hitl_choices(
        [{"decision_key": r["decision_key"], "label": "准"} for r in rows],
        write_gate=session._write_gate,
    )
    assert not session.pending_decisions()
    assert int(state.turn) == turn
    assert state.turn_phase == TurnPhase.SETTLING.value
    if rows:
        state.turn_phase = TurnPhase.AWAITING_DECISION.value
        db.save_state(state)
        with pytest.raises(ValueError):
            session.submit_hitl_choices(
                [{"decision_key": rows[0]["decision_key"], "label": "准", "note": "改写旧批"}],
                write_gate=session._write_gate,
            )
        persisted = db.get_rescript_desk_rows_by_keys([r["decision_key"] for r in rows])
        assert all(r["status"] == "decided" and not r["choice"].get("note") for r in persisted)
        assert int(state.turn) == turn

def test_658_routing_rejected_draft_retries_across_real_turn_boundaries(
    game, monkeypatch, tmp_path,
):
    from tests.month_chain_helpers import canned_full_settlement, make_light_session

    db, state, content = game
    mirror = tmp_path / 'routing-rejections.jsonl'
    monkeypatch.setattr('ming_sim.error_pack.rejections_jsonl_path', lambda: str(mirror))
    canned_full_settlement(monkeypatch)
    import ming_sim.cli_backend as cb
    monkeypatch.setattr(cb, '_run_backend_for_config', lambda *_a, **_k: (json.dumps({'拟旨意图': '拟旨', '动作类型': 'grant_allocation', '目标类型': 'issue', '目标ID': 'route-缺账', '颁布方式': '普通', '施行范围': '无', '参与人': [], 'entries': []}, ensure_ascii=False), {}))
    session = make_light_session(db, state, content)
    original_turn = int(state.turn)
    original_year = int(state.year)
    original_period = int(state.period)
    bad = int(db.add_directive(state, None, '缺账拨帑', 'player-decree-test', dossier_payload={'dossier_action_type': 'grant_allocation', 'target_kind': 'issue', 'target_id': 'route-缺账', 'amount': 100}))
    good = int(db.add_directive(state, None, '清丈', 'player-decree-test', dossier_payload={'dossier_action_type': 'assignment', 'target_kind': 'issue', 'target_id': 'route-清丈', 'transaction_category': '清丈', 'participant_roster': copy.deepcopy(_ROSTER)}))
    first = session.resolve_turn()
    wait_for_background_jobs(db)
    assert first.awaiting is False
    assert int(state.turn) == original_turn
    db.conn.execute('INSERT INTO turn_reports (turn, year, period, report) VALUES (?, ?, ?, ?)', (original_turn, original_year, original_period, '邸报已成'))
    db.conn.commit()
    from ming_sim.month_chain import run_player_month_chain
    advanced = run_player_month_chain(state, db, session.agno_db, session.llm_config)
    wait_for_background_jobs(db)
    assert advanced.advanced is True
    assert int(state.turn) == original_turn + 1
    statuses = dict(db.conn.execute('SELECT id,status FROM turn_directives WHERE id IN (?,?)', (bad, good)).fetchall())
    assert statuses == {bad: 'draft', good: 'issued'}
    assert db.conn.execute('SELECT COUNT(*) FROM decree_dossiers WHERE directive_id=?', (good,)).fetchone()[0] == 1
    assert db.conn.execute('SELECT COUNT(*) FROM decree_dossiers WHERE directive_id=?', (bad,)).fetchone()[0] == 0
    reports = db.conn.execute('SELECT section,item_json,category,source FROM rejection_reports').fetchall()
    assert len(reports) == 1
    assert reports[0]['section'] == 'directive_locality'
    assert reports[0]['category'] == 'locality_fanout_failed'
    assert reports[0]['source'] == 'player_decree'
    assert json.loads(reports[0]['item_json'])['directive_id'] == bad
    assert mirror.exists()
    mirror_lines = mirror.read_text(encoding='utf-8').splitlines()
    assert len(mirror_lines) == 1
    mirror_row = json.loads(mirror_lines[0])
    assert mirror_row['section'] == 'directive_locality'
    assert mirror_row['category'] == 'locality_fanout_failed'
    assert mirror_row['source'] == 'player_decree'
    assert json.loads(mirror_row['item_json'])['directive_id'] == bad
    assert [d.id for d in session.list_directives()] == [bad]
    # #1902：会话层 update_directive 随拟诏台手写改稿入口退役而删，落库改走引擎面。
    session.db.update_directive_text(bad, '补账重拟', dossier_payload={'dossier_action_type': 'grant_allocation', 'target_kind': 'issue', 'target_id': 'route-缺账-retry', 'amount': 100, 'account': '国库'})
    second = session.resolve_turn()
    wait_for_background_jobs(db)
    assert second.awaiting is False
    assert int(state.turn) == original_turn + 1
    db.save_turn_report(state, '邸报已成')
    advanced = run_player_month_chain(state, db, session.agno_db, session.llm_config)
    wait_for_background_jobs(db)
    assert advanced.advanced is True
    assert int(state.turn) == original_turn + 2
    statuses = dict(db.conn.execute('SELECT id,status FROM turn_directives WHERE id IN (?,?)', (bad, good)).fetchall())
    assert statuses == {bad: 'issued', good: 'issued'}
    assert db.conn.execute('SELECT COUNT(*) FROM decree_dossiers WHERE directive_id=?', (bad,)).fetchone()[0] == 1
    assert db.conn.execute('SELECT COUNT(*) FROM decree_dossiers WHERE directive_id=?', (good,)).fetchone()[0] == 1
    provenance = db.conn.execute('SELECT turn,year,period,source FROM turn_directives WHERE id=?', (bad,)).fetchone()
    assert (provenance['turn'], provenance['year'], provenance['period']) == (original_turn, original_year, original_period)
    assert provenance['source'] == 'player-decree-test'

def test_658_ordinary_edit_does_not_inherit_push_target(game, monkeypatch):
    """#658：普通 triad 改草不得继承旧强推 target。"""
    db, state, content = game
    stalled, _ = _658_plant_stalled_deliberation(db, state, title='旧强推')
    did = int(stalled['id'])
    dir_id = db.add_directive(state, None, '着即强推', 'test-658-edit', dossier_payload={'target_dossier_id': did})
    db.update_directive_text(dir_id, '着清核河工', dossier_payload={'dossier_action_type': 'policy', 'target_kind': 'issue', 'target_id': 'river-works', 'mode': 'ordinary'})
    row = db.conn.execute('SELECT dossier_payload_json FROM turn_directives WHERE id=?', (dir_id,)).fetchone()
    payload = json.loads(str(row['dossier_payload_json'] or '{}'))
    assert 'target_dossier_id' not in payload
    assert payload.get('dossier_action_type') == 'policy'
    assert payload.get('target_id') == 'river-works'
    # 第二次种 stalled 前清掉上一次夹具急务行（固定 idx/event_id），由用例自管。
    db.conn.execute(
        "DELETE FROM pending_decisions WHERE turn=? AND event_id=?",
        (int(state.turn), 'plant:陕西告饥'),
    )
    db.conn.commit()
    stalled2, _ = _658_plant_stalled_deliberation(db, state, title='改草强推')
    did2 = int(stalled2['id'])
    name = _summonable_name(db)
    cid = int(db.stage_directive_candidate(state.turn, name, payload={'text': '着清核河工原文', 'actor': name, 'dossier_action_type': 'policy', 'target_kind': 'issue', 'target_id': 'river-works', 'mode': 'ordinary'}))
    db.update_directive_candidate(cid, {'target_dossier_id': did2, 'mode': 'midzhi'})
    staged = json.loads(db.conn.execute('SELECT payload_json FROM pending_actions WHERE id=?', (cid,)).fetchone()['payload_json'])
    assert int(staged.get('target_dossier_id') or 0) == did2
    assert staged.get('mode') == 'midzhi'
    assert staged.get('text') == '着清核河工原文'
    assert staged.get('actor') == name
    assert 'dossier_action_type' not in staged
    assert 'target_kind' not in staged
    assert 'target_id' not in staged
