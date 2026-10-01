"""Retained dossier binding, typed imperial push and endorsement contracts."""
from __future__ import annotations


import copy

import json


import pytest


import ming_sim.decree as decree_mod

import ming_sim.session as session_mod


@pytest.fixture(autouse=True)
def rescript_llm_boundary(monkeypatch):
    from tests.month_chain_helpers import empty_rescript_response
    monkeypatch.setattr("ming_sim.rescript_draft.run_rescript_text", empty_rescript_response)


def test_bind_preserves_dossier_event_id():
    """#1490 接收端病灶：bind 不得把 dossier: 前缀 event_id 当 off-snapshot 解绑。"""
    from ming_sim.settlement_payload import bind_decisions_to_candidate_events
    decisions = [{'event_id': 'dossier:8', 'title': '批红待裁', 'options': [{'label': '强颁', 'dossier_id': 8, 'dossier_decision': 'force_promulgated'}]}]
    payload = {'candidate_events': [{'id': 'ev1', 'title': '边警'}]}
    out = bind_decisions_to_candidate_events(decisions, payload)
    assert out[0]['event_id'] == 'dossier:8'

def test_bind_unbinds_dossier_prefix_without_capability_fields():
    """#1492 A：due-commitment 形 origin_ref=dossier:N + 纯 {label,hint} options
    不得保留 dossier: 前缀——否则 submit 空对空放行后 phase2 批红卡死。"""
    from ming_sim.settlement_payload import bind_decisions_to_candidate_events
    decisions = [{'event_id': 'dossier:12', 'title': '承诺到期核验', 'options': [{'label': '准其销号', 'hint': '事已办结'}, {'label': '着再催办', 'hint': '期限宽延'}]}]
    payload = {'candidate_events': [{'id': 'ev1', 'title': '边警'}]}
    out = bind_decisions_to_candidate_events(decisions, payload)
    assert 'event_id' not in out[0] or not str(out[0].get('event_id') or '').startswith('dossier:'), out[0]

def test_parse_rescript_capability_pair_rejects_non_positive_and_unknown():
    """#1494 共享校验器：正整数 id + 支持动作枚举；其余一律 None。"""
    from ming_sim.settlement_payload import parse_rescript_capability_pair
    assert parse_rescript_capability_pair({'dossier_id': 3, 'dossier_decision': 'hold'}) == (3, 'hold')
    assert parse_rescript_capability_pair({'dossier_id': '7', 'dossier_decision': 'withdrawn'}) == (7, 'withdrawn')
    assert parse_rescript_capability_pair({'dossier_id': 0, 'dossier_decision': 'hold'}) is None
    assert parse_rescript_capability_pair({'dossier_id': -1, 'dossier_decision': 'hold'}) is None
    assert parse_rescript_capability_pair({'dossier_id': 3, 'dossier_decision': 'promulgated'}) is None
    assert parse_rescript_capability_pair({'dossier_id': 3, 'dossier_decision': None}) is None
    assert parse_rescript_capability_pair({'dossier_decision': 'hold'}) is None
    assert parse_rescript_capability_pair(None) is None
    assert parse_rescript_capability_pair('force_promulgated') is None

_ROSTER_LEAD = '毕自严'

_ROSTER = [{'character_id': _ROSTER_LEAD, 'tier': '主办', 'role': '总核', 'delegator_id': None}]

def _dossier_payload(row):
    if not isinstance(row, dict):
        return {}
    payload = row.get('payload')
    if isinstance(payload, dict) and payload:
        return payload
    try:
        loaded = json.loads(str(row.get('payload_json') or '{}'))
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}

def _summonable_name(db, content):
    return db.conn.execute("SELECT name FROM characters WHERE status='active' AND power_id='ming' ORDER BY name LIMIT 1").fetchone()[0]

def _658_plant_stalled_deliberation(db, state, content, *, title='议而不决'):
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
    stalled, _ = _658_plant_stalled_deliberation(db, state, content, title='冷场')
    stalled_id = int(stalled['id'])
    normal_id = int(db.create_decree_dossier(state, action_type='policy', decree_text='清核河工', target_kind='issue', target_id=f'river-{state.turn}'))
    seen: list[int] = []

    def product(_session, snapshot):
        candidate = snapshot.get('candidate') or {}
        dossier_id = int(snapshot.get('dossier_id') or candidate.get('id') or 0)
        seen.append(dossier_id)
        return {'verdict': {'decision': 'promulgated', 'dossier_id': dossier_id}, 'declaration': {}, 'questions': None, 'forecast_text': ''}
    monkeypatch.setattr(month_chain, 'run_world_segment_text', lambda *a, **k: '')
    monkeypatch.setattr('ming_sim.decree_forecast.produce_forecast_product', product)
    decree_mod.resolve_directives(state, db, None, object(), [], '清核河工', content=content)
    assert stalled_id not in seen
    assert normal_id in seen
    assert db.get_decree_dossier(stalled_id)['status'] == 'proposed'
    assert _dossier_payload(db.get_decree_dossier(stalled_id)).get('deliberation_state') == 'stalled'

def _658_session(db, state, content, *, agent=None):
    """最小真 GameSession 壳：只填 chat/add_directive 所需属性。"""
    from types import SimpleNamespace
    from ming_sim.session import GameSession
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.llm_config = SimpleNamespace(channel='api')
    sess.temporary_characters = set()
    sess._refuse_if_settling = lambda: None
    sess._audience_prompt_for_message = lambda message, *_a, **_kw: message
    if agent is not None:

        class _Registry:

            def get(self, _character, **_kw):
                return agent
        sess.registry = _Registry()
    return sess

def test_658_endorsement_provenance_xor(game):
    """#658：背书 provenance 恰为 chat_turn 或 decision_key 之一。"""
    db, state, content = game
    minister = _summonable_name(db, content)
    did = db.create_decree_dossier(state, action_type='policy', decree_text='试', target_kind='policy', target_id='t')
    chat = db.create_chat_turn(state, minister, '658-xor', 0)
    eid = db.add_dossier_endorsement(did, form='会签', endorser_id=minister, source_chat_turn_id=chat)
    row = db.list_dossier_endorsements(did)[0]
    assert row['source_chat_turn_id'] == chat and row['decision_key'] == ''
    eid2 = db.add_dossier_endorsement(did, form='当面站台', endorser_id=minister, decision_key='rescript_draft:1:0')
    rows = {e['id']: e for e in db.list_dossier_endorsements(did)}
    assert rows[eid2]['decision_key'] == 'rescript_draft:1:0'
    assert rows[eid2]['source_chat_turn_id'] == 0
    with pytest.raises(ValueError, match='provenance'):
        db.add_dossier_endorsement(did, form='会签', endorser_id=minister, source_chat_turn_id=chat, decision_key='x')
    with pytest.raises(ValueError, match='provenance'):
        db.add_dossier_endorsement(did, form='会签', endorser_id=minister)

@pytest.mark.parametrize("historical", [False, True])
def test_658_imperial_push_uses_rescript_original_and_key(game, monkeypatch, historical):
    from tests.month_chain_helpers import make_light_session, canned_full_settlement
    db, state, content = game
    stalled, _ = _658_plant_stalled_deliberation(db, state, content)
    did = int(stalled["id"])
    if historical:
        db.conn.execute("UPDATE decree_dossiers SET created_turn=? WHERE id=?", (state.turn - 1, did))
        db.conn.commit()
    canned_full_settlement(monkeypatch)
    monkeypatch.setattr("ming_sim.decree_forecast.produce_forecast_product", lambda *a, **k: {
        "verdict": {"decision": "promulgated"}, "declaration": {"effects": {}},
        "questions": None, "forecast_text": "", "visible_refs": {},
    })
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

def test_midzhi_rescript_model_uses_original_key_and_existing_gate(game, monkeypatch):
    from tests.month_chain_helpers import make_light_session, canned_full_settlement
    db, state, content = game
    canned_full_settlement(monkeypatch)
    captured = []

    def rescript(session, *, officers, backlog, answer=None):
        if answer is None:
            return json.dumps({"actor_name": officers[-1]["name"], "revisions": [],
                               "items": [{"title": "急务", "context": "原奏与拟旨", "options": []}]})
        captured.append(answer)
        return json.dumps({"disposition": "settled", "text": "", "decree": {
            "text": "御笔旨文", "payload": {"dossier_action_type": "policy", "target_kind": "issue",
                "target_id": "urgent", "due_turn": int(state.turn) + 2,
                "locality_scope": "none", "participant_roster": copy.deepcopy(_ROSTER)},
        }})

    monkeypatch.setattr("ming_sim.rescript_draft.run_rescript_text", rescript)
    gate = []
    def forecast(_session, snapshot):
        gate.append(snapshot["candidate"]["id"])
        return {"verdict": {"decision": "promulgated"}, "declaration": {"effects": {}},
                "questions": None, "forecast_text": "", "visible_refs": {}}
    monkeypatch.setattr("ming_sim.decree_forecast.produce_forecast_product", forecast)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    assert session.resolve_turn(allow_empty_decree=True).awaiting
    original = session.pending_decisions()[0]
    choice = {"decision_key": original["decision_key"], "action": "midzhi", "note": "  朕亲拟\n旨意  "}
    session.submit_hitl_choices([choice], write_gate=session._write_gate)
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


def test_658_typed_target_and_backing_reject_bad_shapes(game, monkeypatch):
    """#658：typed 解析边界表驱动 + 一条外部入口零写（不跨裸值/双别名/session 全排列）。"""
    from ming_sim.db import imperial_push_target_dossier_id, parse_backing_dossier_id
    import ming_sim.cli_backend as cli_backend
    db, state, content = game
    stalled, _ = _658_plant_stalled_deliberation(db, state, content, title='南迁')
    did = int(stalled['id'])
    bind_did = db.create_decree_dossier(state, action_type='policy', decree_text='南迁绑定', target_kind='issue', target_id='river-works', payload={'deliberation_state': 'stalled', 'mode': 'ordinary'})
    db.insert_issue(state, kind='situation', title='南迁绑定', origin_kind='decree', origin_ref=f'dossier:{bind_did}')
    bind_affair = db.affairs.open(name='南迁事务', origin='下部议', year=state.year, period=state.period, turn=state.turn)
    push_declaration = {'attach': 'existing', 'affair_id': int(bind_affair.id)}
    before_dossiers = len(db.list_decree_dossiers())
    before_ends = len(db.list_dossier_endorsements(did))
    before_dirs = db.conn.execute('SELECT COUNT(*) AS c FROM turn_directives').fetchone()['c']
    bad_shapes = (True, False, 1.9, 1.0, '1', '12', 0, -1)
    for bad in bad_shapes:
        with pytest.raises(ValueError):
            imperial_push_target_dossier_id(bad)
        with pytest.raises(ValueError):
            parse_backing_dossier_id(bad)
    sample_bad = True
    with pytest.raises(ValueError):
        imperial_push_target_dossier_id({'target_dossier_id': sample_bad})
    with pytest.raises(ValueError):
        imperial_push_target_dossier_id({'目标案卷ID': sample_bad})
    assert imperial_push_target_dossier_id(did) == did
    assert imperial_push_target_dossier_id({'target_dossier_id': did}) == did
    assert imperial_push_target_dossier_id({'目标案卷ID': did}) == did
    assert imperial_push_target_dossier_id({}) is None
    assert imperial_push_target_dossier_id({'target_dossier_id': None}) is None
    assert parse_backing_dossier_id(None) is None
    assert parse_backing_dossier_id('') is None
    assert parse_backing_dossier_id(did) == did
    endorsers = [_summonable_name(db, content)]
    endorsers.append(next((n for n in content.characters if n != endorsers[0])))
    for index, endorser in enumerate(endorsers):
        db.add_dossier_endorsement(did, form='会签', endorser_id=endorser, decision_key=f'test:658:typed:{index}')
    projected = db.list_endorsed_dossier_candidates(state.turn)
    assert [c['endorser_id'] for c in projected if c['dossier_id'] == did] == list(reversed(endorsers))

    def backend_multi(prompt, *_a, **_k):
        return (json.dumps({'成品旨稿': [{'正文': '御笔强推', '目标案卷ID': bind_did, '颁布方式': '中旨直发'}, {'正文': '清核河工', '动作类型': 'policy', '目标类型': 'issue', '目标ID': 'river-works', '颁布方式': '普通', '施行范围': '无'}], '事务声明': push_declaration}, ensure_ascii=False), 1)
    monkeypatch.setattr(cli_backend, '_run_backend_for_config', backend_multi)
    multi = cli_backend.extract_draft_intent('分拟两旨', '臣已拟成', draft_count=2, db=db)
    assert multi['drafts'][0]['target_dossier_id'] == bind_did
    assert multi['drafts'][1]['target_id'] == 'river-works'
    push_payload = cli_backend.project_draft_extract_to_directive_payload(multi['drafts'][0], decree_text='御笔强推', db=db, content=content)
    assert push_payload.get('affair_declaration')
    push_dir = int(db.add_directive(state, None, '御笔强推', 'test-658-push-bind', dossier_payload=push_payload))
    db.ensure_dossiers_for_draft_directives(state)
    assert int(db.get_decree_dossier(bind_did)['affair_id'] or 0) == 0
    assert db.get_dossier_for_directive(push_dir) is None
    assert db.conn.execute('SELECT status FROM turn_directives WHERE id=?', (push_dir,)).fetchone()['status'] == 'draft'
    bad_directive = int(db.add_directive(state, None, '处分不存在之人', 'test-658-ensure', dossier_payload={'dossier_action_type': 'punishment', 'target_kind': 'character', 'target_id': '不存在的大臣XYZ', 'mode': 'ordinary'}))
    db.ensure_dossiers_for_draft_directives(state)
    status = db.conn.execute('SELECT status FROM turn_directives WHERE id=?', (bad_directive,)).fetchone()['status']
    assert status == 'draft'
    assert all((int(row['id']) != bad_directive for row in db.list_dossiered_draft_directives(state)))
    db.mark_directives_issued(state)
    status = db.conn.execute('SELECT status FROM turn_directives WHERE id=?', (bad_directive,)).fetchone()['status']
    assert status == 'draft'

    def backend_bad(prompt, *_a, **_k):
        return (json.dumps({'拟旨意图': '拟旨', '目标案卷ID': True}, ensure_ascii=False), 1)
    monkeypatch.setattr(cli_backend, '_run_backend_for_config', backend_bad)
    with pytest.raises(ValueError):
        cli_backend.capture_manual_directive_payload(f'着即强推南迁（案卷{did}）', None, db=db, content=content)
    assert len(db.list_decree_dossiers()) == before_dossiers
    assert len(db.list_dossier_endorsements(did)) == before_ends + 2
    assert db.conn.execute('SELECT COUNT(*) AS c FROM turn_directives').fetchone()['c'] == before_dirs + 2
    assert _dossier_payload(db.get_decree_dossier(did)).get('deliberation_state') == 'stalled'

@pytest.mark.usefixtures("_offline_scene_beat_generator")
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
    monkeypatch.setattr(session_mod, 'write_decree_with_agno', lambda *_a, **_k: '诏曰清丈。')
    session = make_light_session(db, state, content)
    original_turn = int(state.turn)
    original_year = int(state.year)
    original_period = int(state.period)
    bad = int(db.add_directive(state, None, '缺账拨帑', 'player-decree-test', dossier_payload={'dossier_action_type': 'grant_allocation', 'target_kind': 'issue', 'target_id': 'route-缺账', 'amount': 100}))
    good = int(db.add_directive(state, None, '清丈', 'player-decree-test', dossier_payload={'dossier_action_type': 'assignment', 'target_kind': 'issue', 'target_id': 'route-清丈', 'transaction_category': '清丈', 'participant_roster': copy.deepcopy(_ROSTER)}))
    first = session.resolve_turn()
    assert first.awaiting is False
    assert int(state.turn) == original_turn
    db.conn.execute('INSERT INTO turn_reports (turn, year, period, report) VALUES (?, ?, ?, ?)', (original_turn, original_year, original_period, '邸报已成'))
    db.conn.commit()
    from ming_sim.month_chain import run_player_month_chain
    advanced = run_player_month_chain(state, db, session.agno_db, session.llm_config)
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
    session.update_directive(bad, '补账重拟', dossier_payload={'dossier_action_type': 'grant_allocation', 'target_kind': 'issue', 'target_id': 'route-缺账-retry', 'amount': 100, 'account': '国库'})
    second = session.resolve_turn()
    assert second.awaiting is False
    assert int(state.turn) == original_turn + 1
    db.save_turn_report(state, '邸报已成')
    advanced = run_player_month_chain(state, db, session.agno_db, session.llm_config)
    assert advanced.advanced is True
    assert int(state.turn) == original_turn + 2
    statuses = dict(db.conn.execute('SELECT id,status FROM turn_directives WHERE id IN (?,?)', (bad, good)).fetchall())
    assert statuses == {bad: 'issued', good: 'issued'}
    assert db.conn.execute('SELECT COUNT(*) FROM decree_dossiers WHERE directive_id=?', (bad,)).fetchone()[0] == 1
    assert db.conn.execute('SELECT COUNT(*) FROM decree_dossiers WHERE directive_id=?', (good,)).fetchone()[0] == 1
    provenance = db.conn.execute('SELECT turn,year,period,source FROM turn_directives WHERE id=?', (bad,)).fetchone()
    assert (provenance['turn'], provenance['year'], provenance['period']) == (original_turn, original_year, original_period)
    assert provenance['source'] == 'player-decree-test'

def test_658_ordinary_edit_does_not_inherit_push_target(game):
    """#658：普通 triad 改草不得继承旧强推 target。"""
    db, state, content = game
    stalled, _ = _658_plant_stalled_deliberation(db, state, content, title='旧强推')
    did = int(stalled['id'])
    dir_id = int(db.add_directive(state, None, '着即强推', 'test-658-edit', dossier_payload={'target_dossier_id': did}))
    db.update_directive_text(dir_id, '着清核河工', dossier_payload={'dossier_action_type': 'policy', 'target_kind': 'issue', 'target_id': 'river-works', 'mode': 'ordinary'})
    row = db.conn.execute('SELECT dossier_payload_json FROM turn_directives WHERE id=?', (dir_id,)).fetchone()
    payload = json.loads(str(row['dossier_payload_json'] or '{}'))
    assert 'target_dossier_id' not in payload
    assert payload.get('dossier_action_type') == 'policy'
    assert payload.get('target_id') == 'river-works'
    stalled2, _ = _658_plant_stalled_deliberation(db, state, content, title='改草强推')
    did2 = int(stalled2['id'])
    name = _summonable_name(db, content)
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

def test_658_mixed_ordinary_triad_and_target_rejected(game, monkeypatch):
    """#658：普通 triad + target 矛盾载荷——一条真实入口零写（禁 classifier/session/backend 三份）。"""
    import ming_sim.cli_backend as cli_backend
    db, state, content = game
    stalled, _ = _658_plant_stalled_deliberation(db, state, content, title='混载')
    did = int(stalled['id'])
    before_dossiers = len(db.list_decree_dossiers())
    before_dirs = db.conn.execute('SELECT COUNT(*) AS c FROM turn_directives').fetchone()['c']

    def backend_mixed(prompt, *_a, **_k):
        return (json.dumps({'拟旨意图': '拟旨', '动作类型': 'policy', '目标类型': 'issue', '目标ID': 'river', '目标案卷ID': did}, ensure_ascii=False), 1)
    monkeypatch.setattr(cli_backend, '_run_backend_for_config', backend_mixed)
    with pytest.raises(ValueError, match='不得同时'):
        cli_backend.capture_manual_directive_payload('混载旨文', None, db=db, content=content)
    assert len(db.list_decree_dossiers()) == before_dossiers
    assert db.conn.execute('SELECT COUNT(*) AS c FROM turn_directives').fetchone()['c'] == before_dirs
