"""#1490 / #1492 批红轨契约。

#1490：
1. 接收端：缺字段 → SSE error 且仍 pending；带齐字段重交 → decided。
   经 httpx.ASGITransport 真 POST /api/decree/resolve_decisions/stream。
2. 生成端：dossier options 含 dossier_id / dossier_decision。
3. bind 保带能力字段的 dossier: event_id。

#1492 follow-up：
A. bind 对无能力字段的 dossier: 前缀解绑；due-commitment 同形不批红卡死。
D. 命中 allowed 后从服务端 option 重建 label/hint/能力字段，客户端只留 note。
"""
from __future__ import annotations

from ming_sim.decree import ResolveResult
from tests.conftest import clear_pending_rows
import asyncio
import json
import httpx
import pytest
import ming_sim.agents as agents_mod
import ming_sim.decree as decree_mod
import web_app
from ming_sim.models import TurnPhase


@pytest.fixture
def web_game(tmp_path, monkeypatch, _offline_scene_beat_generator):
    """真实 WebGame + ASGI 入口；仅中和构造/LLM 边界（与 #498/#1235 同形）。"""
    monkeypatch.setenv('MING_SIM_DB', str(tmp_path / 'ming.db'))
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-test')
    monkeypatch.delenv('MING_SIM_LLM_BACKEND', raising=False)
    monkeypatch.setattr(web_app, 'load_runtime_llm', lambda: {})

    def _promulgation_verdicts(dossiers, _state, **kwargs):
        context = kwargs['prepared_context']
        by_id = {int(row['id']): row for row in context['dossiers']}
        faction = str(context['factions'][0]['name'])
        verdicts = []
        for dossier in dossiers:
            dossier_id = int(dossier['id'])
            row = by_id[dossier_id]
            if row['mode'] == 'midzhi':
                verdicts.append({'dossier_id': dossier_id, 'decision': 'rejected', 'blocked_layer': 'six_offices', 'reason': '测试中留待批红。', 'primary_opponents': [{'kind': 'faction', 'key': faction}], 'gatekeeper_id': None, 'criteria_snapshot': row['criteria_snapshot_source']})
            else:
                verdicts.append({'dossier_id': dossier_id, 'decision': 'promulgated'})
        return verdicts
    monkeypatch.setattr(decree_mod, 'llm_promulgation_verdicts', _promulgation_verdicts)
    real_run_agent_text = agents_mod.run_agent_text

    def _run_month_chain_text(agent, prompt, tag, **kwargs):
        if tag in {'world-segment', 'decree-forecast'}:
            return ''
        if tag == 'gazette':
            return '{"title":"邸报","report":"本月实况。"}'
        return real_run_agent_text(agent, prompt, tag, **kwargs)
    monkeypatch.setattr(agents_mod, 'run_agent_text', _run_month_chain_text)
    monkeypatch.setattr(web_app, 'run_highlight_judge', lambda **_k: [])
    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, 'web_game', game)
    yield game
    try:
        game.session.close()
    except Exception:
        pass


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=web_app.app), base_url='http://t')


async def _post_resolve(choices: list[dict]) -> httpx.Response:
    async with _client() as client:
        return await client.post('/api/decree/resolve_decisions/stream', json={'choices': choices})


async def _get_state() -> dict:
    async with _client() as client:
        r = await client.get('/api/game/state')
        assert r.status_code == 200, r.text
        return r.json()


def _plant_dossier_awaiting(db, state):
    """种 QA 同形：dossier 批红待裁 + resolve_context（含 candidate_events，触发 bind）。"""
    dossier_id = db.create_decree_dossier(state, action_type='policy', decree_text='密查陕西驿卒', target_kind='issue', target_id='river-works')
    options = [{'label': '强颁', 'hint': '以中旨强行颁出', 'dossier_id': dossier_id, 'dossier_decision': 'force_promulgated'}, {'label': '收回', 'hint': '收回此道准旨', 'dossier_id': dossier_id, 'dossier_decision': 'withdrawn'}, {'label': '留中', 'hint': '留待下月重判', 'dossier_id': dossier_id, 'dossier_decision': 'hold'}]
    db.save_pending_decisions(state.turn, [{'event_id': f'dossier:{dossier_id}', 'title': '批红待裁', 'context': '密查陕西驿卒', 'rejection_reason': '科臣封驳', 'opposition': '东林', 'options': options}])
    db.save_resolve_context(state.turn, '诏曰密查', {'candidate_events': [{'id': 'ev_border', 'title': '边警'}], 'transit_semantics': []})
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    return dossier_id


def _plant_proposed_push_target(db, state, *, title="待强推案"):
    """现役 proposed 案卷，供御笔强推 target_dossier_id 结构性负向案复用。"""
    body = f"{title}正文"
    dossier_id = int(db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=body,
        target_kind="issue",
        target_id=f"push-target-{title}-{int(state.turn)}",
        payload={
            "dossier_action_type": "policy",
            "mode": "ordinary",
            "title": title,
            "target_kind": "issue",
            "target_id": f"push-target-{title}-{int(state.turn)}",
        },
        status="proposed",
    ))
    row = db.get_decree_dossier(dossier_id)
    assert row is not None
    return row


def test_missing_dossier_fields_stay_pending_then_full_retry_decides(web_game, monkeypatch):
    """失败形（#1490 QA）：缺 dossier_id → error 且 pending；带齐字段 → decided。
    经 ASGI 真 HTTP POST /api/decree/resolve_decisions/stream；真实 WebGame，
    仅 stub phase2 LLM 边界。"""
    db, state = (web_game.db, web_game.state)
    dossier_id = _plant_dossier_awaiting(db, state)
    phase2_calls: list[list] = []

    def _phase2(_state, _db, *_a, **_k):
        rows = list(_db.list_pending_decisions(int(_state.turn)))
        phase2_calls.append(rows)
        clear_pending_rows(_db, int(_state.turn))
        return ResolveResult(report='邸报：批红已落。', awaiting=False, advanced=False)
    monkeypatch.setattr("ming_sim.month_chain.run_player_month_chain", _phase2)
    d_key = db.list_rescript_desk(int(state.turn))[0]['decision_key']
    incomplete = {'decision_key': d_key, 'label': '强颁', 'hint': '', 'note': '准。先济关宁边饷。'}
    r1 = asyncio.run(_post_resolve([incomplete]))
    assert r1.status_code == 200, r1.text
    assert 'event: error' in r1.text, r1.text
    assert 'event: done' not in r1.text
    row = db.list_pending_decisions(state.turn)[0]
    assert row['status'] == 'pending', f"非法载荷绝不可落 decided，got status={row['status']!r} choice={row['choice']!r}"
    assert row['choice'] is None
    assert phase2_calls == [], '校验失败不得进入 phase2'
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    full = {'decision_key': d_key, 'label': '强颁', 'hint': '以中旨强行颁出', 'note': '准。先济关宁边饷。', 'dossier_id': dossier_id, 'dossier_decision': 'force_promulgated'}
    r2 = asyncio.run(_post_resolve([full]))
    assert r2.status_code == 200, r2.text
    assert 'event: done' in r2.text, r2.text
    assert 'event: error' not in r2.text
    assert len(phase2_calls) == 1
    decided_row = phase2_calls[0][0]
    assert decided_row['status'] == 'decided'
    choice = decided_row['choice'] or {}
    assert choice.get('dossier_id') == dossier_id
    assert choice.get('dossier_decision') == 'force_promulgated'


def _plant_due_commitment_shaped_awaiting(db, state, *, dossier_id: int=12):
    """种 due-commitment 同形：event_id=dossier:N，options 仅 {label,hint}。"""
    options = [{'label': '准其销号', 'hint': '事已办结'}, {'label': '着再催办', 'hint': '期限宽延'}]
    db.save_pending_decisions(state.turn, [{'event_id': f'dossier:{dossier_id}', 'title': '承诺到期核验', 'context': '清丈之诺届期', 'options': options}])
    db.save_resolve_context(state.turn, '诏曰核验', {'candidate_events': [{'id': 'ev_border', 'title': '边警'}]})
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)


def test_due_commitment_shaped_submit_does_not_poison_or_deadlock(web_game, monkeypatch):
    """#1492 A 真 HTTP：due-commitment 形提交后不落 poisoned decided、不批红卡死。
    无能力字段 → 不作批红轨，且不落 poisoned decided。"""
    db, state = (web_game.db, web_game.state)
    _plant_due_commitment_shaped_awaiting(db, state, dossier_id=12)
    phase2_calls: list[list] = []

    def _phase2(_state, _db, *_a, **_k):
        rows = list(_db.list_pending_decisions(int(_state.turn)))
        phase2_calls.append(rows)
        clear_pending_rows(_db, int(_state.turn))
        return ResolveResult(report='邸报：承诺已核。', awaiting=False, advanced=False)
    monkeypatch.setattr("ming_sim.month_chain.run_player_month_chain", _phase2)
    choice = {'decision_key': db.list_rescript_desk(int(state.turn))[0]['decision_key'], 'label': '准其销号', 'hint': '事已办结', 'note': '准销。'}
    r = asyncio.run(_post_resolve([choice]))
    assert r.status_code == 200, r.text
    assert 'event: error' not in r.text, r.text
    assert 'event: done' in r.text, r.text
    assert len(phase2_calls) == 1
    decided_row = phase2_calls[0][0]
    assert decided_row['status'] == 'decided'
    stored_choice = decided_row['choice'] or {}
    assert stored_choice.get('label') == '准其销号'
    assert stored_choice.get('note') == '准销。'
    assert not stored_choice.get('dossier_decision')


def test_lying_label_rebuilt_from_server_option(web_game, monkeypatch):
    """#1492 D 真 HTTP：合法能力对 + 撒谎 label/hint → 落库取服务端 option，客户端只留 note。"""
    db, state = (web_game.db, web_game.state)
    dossier_id = _plant_dossier_awaiting(db, state)
    phase2_calls: list[list] = []

    def _phase2(_state, _db, *_a, **_k):
        rows = list(_db.list_pending_decisions(int(_state.turn)))
        phase2_calls.append(rows)
        clear_pending_rows(_db, int(_state.turn))
        return ResolveResult(report='邸报：批红已落。', awaiting=False, advanced=False)
    monkeypatch.setattr("ming_sim.month_chain.run_player_month_chain", _phase2)
    lying = {'decision_key': db.list_rescript_desk(int(state.turn))[0]['decision_key'], 'label': '收回', 'hint': '收回此道准旨', 'note': '准。先济关宁边饷。', 'dossier_id': dossier_id, 'dossier_decision': 'force_promulgated'}
    r = asyncio.run(_post_resolve([lying]))
    assert r.status_code == 200, r.text
    assert 'event: done' in r.text, r.text
    assert 'event: error' not in r.text
    assert len(phase2_calls) == 1
    choice = phase2_calls[0][0]['choice'] or {}
    assert choice.get('dossier_id') == dossier_id
    assert choice.get('dossier_decision') == 'force_promulgated'
    assert choice.get('label') == '强颁', choice
    assert choice.get('hint') == '以中旨强行颁出', choice
    assert choice.get('note') == '准。先济关宁边饷。'


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


def test_mixed_legal_illegal_options_illegal_choice_stays_pending(web_game, monkeypatch):
    """#1494：混合合法/非法 options 时，选非法能力对保持 pending、不进 phase2。

    allowed 只收共享校验器放行的对；非法残对（负 id / 未知 decision）不得空对空放行。
    """
    db, state = (web_game.db, web_game.state)
    dossier_id = db.create_decree_dossier(state, action_type='policy', decree_text='密查陕西驿卒', target_kind='issue', target_id='river-works')
    options = [{'label': '强颁', 'hint': '以中旨强行颁出', 'dossier_id': dossier_id, 'dossier_decision': 'force_promulgated'}, {'label': '伪收回', 'hint': '残对负 id', 'dossier_id': -9, 'dossier_decision': 'withdrawn'}, {'label': '伪留中', 'hint': '未知动作', 'dossier_id': dossier_id, 'dossier_decision': 'promulgated'}, {'label': '裸字段', 'hint': '仅非 None', 'dossier_id': dossier_id, 'dossier_decision': None}]
    db.save_pending_decisions(state.turn, [{'event_id': f'dossier:{dossier_id}', 'title': '批红待裁', 'context': '密查陕西驿卒', 'options': options}])
    db.save_resolve_context(state.turn, '诏曰密查', {'candidate_events': [{'id': 'ev_border', 'title': '边警'}]})
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    phase2_calls: list[list] = []

    def _phase2(_state, _db, *_a, **_k):
        rows = list(_db.list_pending_decisions(int(_state.turn)))
        phase2_calls.append(rows)
        clear_pending_rows(_db, int(_state.turn))
        return ResolveResult(report='邸报：不应到此。', awaiting=False, advanced=False)
    monkeypatch.setattr("ming_sim.month_chain.run_player_month_chain", _phase2)
    illegal = {'decision_key': db.list_rescript_desk(int(state.turn))[0]['decision_key'], 'label': '伪收回', 'hint': '残对负 id', 'dossier_id': -9, 'dossier_decision': 'withdrawn'}
    r1 = asyncio.run(_post_resolve([illegal]))
    assert r1.status_code == 200, r1.text
    assert 'event: error' in r1.text, r1.text
    assert 'event: done' not in r1.text
    row = db.list_pending_decisions(state.turn)[0]
    assert row['status'] == 'pending', row
    assert row['choice'] is None
    assert phase2_calls == [], '非法选择不得进入 phase2'
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    unknown = {'decision_key': db.list_rescript_desk(int(state.turn))[0]['decision_key'], 'label': '伪留中', 'hint': '未知动作', 'dossier_id': dossier_id, 'dossier_decision': 'promulgated'}
    r2 = asyncio.run(_post_resolve([unknown]))
    assert r2.status_code == 200, r2.text
    assert 'event: error' in r2.text, r2.text
    assert phase2_calls == []
    assert db.list_pending_decisions(state.turn)[0]['status'] == 'pending'
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    legal = {'decision_key': db.list_rescript_desk(int(state.turn))[0]['decision_key'], 'label': '强颁', 'hint': '以中旨强行颁出', 'note': '准。', 'dossier_id': dossier_id, 'dossier_decision': 'force_promulgated'}
    r3 = asyncio.run(_post_resolve([legal]))
    assert r3.status_code == 200, r3.text
    assert 'event: done' in r3.text, r3.text
    assert 'event: error' not in r3.text
    assert len(phase2_calls) == 1
    choice = phase2_calls[0][0]['choice'] or {}
    assert choice.get('dossier_id') == dossier_id
    assert choice.get('dossier_decision') == 'force_promulgated'
    assert choice.get('label') == '强颁'


def test_ordinary_event_with_hallucinated_capability_submits(web_game, monkeypatch):
    """#1494-F1：普通 event_id + options 幻觉能力对不得入批红轨。

    submit 须与 bind/phase2 同用「dossier: 前缀 AND 能力对」合取；仅能力对
    会把普通决策块当批红校验 → 客户端无能力字段的 choice 永卡 AWAITING。
    """
    db, state = (web_game.db, web_game.state)
    event_id = 'mao_wenlong'
    db.save_pending_decisions(state.turn, [{'event_id': event_id, 'title': '边警', 'context': '辽东来报', 'options': [{'label': '准其销号', 'hint': '事已办结'}, {'label': '强颁', 'hint': '幻觉批红', 'dossier_id': 3, 'dossier_decision': 'hold'}]}])
    db.save_resolve_context(state.turn, '诏曰边警', {'candidate_events': [{'id': event_id, 'title': '边警'}]})
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    phase2_calls: list[list] = []

    def _phase2(_state, _db, *_a, **_k):
        rows = list(_db.list_pending_decisions(int(_state.turn)))
        phase2_calls.append(rows)
        clear_pending_rows(_db, int(_state.turn))
        return ResolveResult(report='邸报：边警已核。', awaiting=False, advanced=False)
    monkeypatch.setattr("ming_sim.month_chain.run_player_month_chain", _phase2)
    choice = {'decision_key': db.list_rescript_desk(int(state.turn))[0]['decision_key'], 'label': '准其销号', 'hint': '事已办结', 'note': '准销。'}
    r = asyncio.run(_post_resolve([choice]))
    assert r.status_code == 200, r.text
    assert 'event: error' not in r.text, r.text
    assert 'event: done' in r.text, r.text
    assert len(phase2_calls) == 1
    decided = phase2_calls[0][0]
    assert decided['status'] == 'decided'
    stored = decided['choice'] or {}
    assert stored.get('label') == '准其销号'
    assert stored.get('note') == '准销。'
    assert not stored.get('dossier_decision')


def _summonable_name(db, content):
    """现役可召大臣名：读 active 大臣，不依赖已撤 list_deliberation_candidate_ids。"""
    del db
    for name, ch in (getattr(content, "characters", {}) or {}).items():
        if getattr(ch, "alive", True) and not getattr(ch, "is_emperor", False):
            return str(name)
    raise AssertionError("fixture 须有可召大臣")


def _657_db_path_of(game_or_path) -> str:
    if isinstance(game_or_path, str):
        return game_or_path
    path = getattr(game_or_path, 'db_path', None)
    if path:
        return str(path)
    db = getattr(game_or_path, 'db', None)
    return str(getattr(db, 'path', None) or getattr(db, 'db_path', None) or '')


def test_1682_phase2_surfaces_ambiguous_stored_choice(game):
    """批红真入口拒绝同名选项，且拒绝前不得落亲裁。"""
    from contextlib import nullcontext
    from ming_sim.models import TurnPhase
    from tests.month_chain_helpers import make_light_session

    db, state, content = game
    db.save_pending_decisions(int(state.turn), [{'title': '歧义亲裁', 'context': 'c', 'options': [{'label': '同名', 'hint': '一'}, {'label': '同名', 'hint': '二'}]}])
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    session = make_light_session(db, state, content)
    choice = [{'decision_key': db.list_rescript_desk(int(state.turn))[0]['decision_key'], 'label': '同名', 'action': 'decision'}]
    with pytest.raises(ValueError):
        session.submit_hitl_choices(choice, write_gate=nullcontext())
    assert db.list_pending_decisions(int(state.turn))[0]['status'] == 'pending'


def test_658_ordinary_edit_does_not_inherit_push_target(game):
    """#658：普通 triad 改草不得继承旧强推 target。"""
    db, state, content = game
    did = int(_plant_proposed_push_target(db, state, title='旧强推')['id'])
    dir_id = int(db.add_directive(state, None, '着即强推', 'test-658-edit', dossier_payload={'target_dossier_id': did}))
    db.update_directive_text(dir_id, '着清核河工', dossier_payload={'dossier_action_type': 'policy', 'target_kind': 'issue', 'target_id': 'river-works', 'mode': 'ordinary'})
    row = db.conn.execute('SELECT dossier_payload_json FROM turn_directives WHERE id=?', (dir_id,)).fetchone()
    payload = json.loads(str(row['dossier_payload_json'] or '{}'))
    assert 'target_dossier_id' not in payload
    assert payload.get('dossier_action_type') == 'policy'
    assert payload.get('target_id') == 'river-works'
    did2 = int(_plant_proposed_push_target(db, state, title='改草强推')['id'])
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
    did = int(_plant_proposed_push_target(db, state, title='混载')['id'])
    before_dossiers = len(db.list_decree_dossiers())
    before_dirs = db.conn.execute('SELECT COUNT(*) AS c FROM turn_directives').fetchone()['c']

    def backend_mixed(prompt, *_a, **_k):
        return (json.dumps({'拟旨意图': '拟旨', '动作类型': 'policy', '目标类型': 'issue', '目标ID': 'river', '目标案卷ID': did}, ensure_ascii=False), 1)
    monkeypatch.setattr(cli_backend, '_run_backend_for_config', backend_mixed)
    with pytest.raises(ValueError):
        cli_backend.capture_manual_directive_payload('混载旨文', None, db=db, content=content)
    assert len(db.list_decree_dossiers()) == before_dossiers
    assert db.conn.execute('SELECT COUNT(*) AS c FROM turn_directives').fetchone()['c'] == before_dirs


def _657_plant_awaiting_web(web_game, *, decisions=None):
    """web_game 上种植 decision + resolve_context，相位 AWAITING_DECISION。"""
    from ming_sim.models import TurnPhase
    db, state = (web_game.db, web_game.state)
    db.conn.execute('DELETE FROM pending_decisions')
    db.conn.commit()
    if decisions:
        db.save_pending_decisions(int(state.turn), decisions)
    db.save_resolve_context(int(state.turn), '诏', {'candidate_events': [], 'transit_semantics': []})
    db.save_turn_report(state, '邸报')
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    web_game.state.turn_phase = TurnPhase.AWAITING_DECISION.value
    web_game.session.state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.conn.commit()
    return db.list_rescript_desk(int(state.turn))


def _657_subprocess_resolve(
    db_path: str,
    choices: list,
    *,
    crash: str = "",
    timeout: float = 180.0,
) -> dict:
    """子进程真 HTTP POST resolve_decisions/stream。"""
    import os
    import subprocess
    import sys
    import textwrap

    worker = textwrap.dedent(
        r"""
        import asyncio, json, os, sys
        db_path = sys.argv[1]
        choices = json.loads(sys.argv[2])
        crash = sys.argv[3]
        os.environ["MING_SIM_DB"] = db_path
        os.environ["OPENAI_API_KEY"] = "sk-test"
        os.environ.pop("MING_SIM_LLM_BACKEND", None)

        import httpx
        import ming_sim.decree as dm
        import ming_sim.session as session_mod
        import web_app
        from ming_sim.models import TurnPhase

        web_app.load_runtime_llm = lambda: {}
        web_app.run_highlight_judge = lambda **_k: []

        import ming_sim.mechanical_tail as mechanical_tail
        mechanical_tail._run_relation_brew = lambda *a, **k: None
        import ming_sim.decree_forecast as decree_forecast
        import ming_sim.month_chain as month_chain
        month_chain.run_world_segment_text = lambda *a, **k: ""
        decree_forecast.produce_forecast_product = lambda *a, **k: {
            "verdict": {"decision": "promulgated"},
            "declaration": {"effects": {}},
            "questions": None,
            "forecast_text": "",
            "visible_refs": {},
        }
        import ming_sim.agents as agents_mod
        _real_run_agent_text = agents_mod.run_agent_text

        def _run_agent_text(agent, prompt, tag, **kwargs):
            if tag == "gazette":
                return '{"title":"邸报","report":"本月实况。"}'
            return _real_run_agent_text(agent, prompt, tag, **kwargs)

        agents_mod.run_agent_text = _run_agent_text

        if crash == "phase2":
            def _kill_at_phase2(*a, **k):
                os._exit(97)

            session_mod.resolve_decisions_phase2 = _kill_at_phase2
            dm.resolve_decisions_phase2 = _kill_at_phase2

        game = web_app.WebGame(fresh=False)
        web_app.web_game = game
        game.state.turn_phase = TurnPhase.AWAITING_DECISION.value
        game.session.state.turn_phase = TurnPhase.AWAITING_DECISION.value
        game.db.save_state(game.state)

        summary = {"db_path": db_path, "body": choices}
        try:
            async def _post():
                transport = httpx.ASGITransport(app=web_app.app)
                async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                    return await client.post(
                        "/api/decree/resolve_decisions/stream",
                        json={"choices": choices},
                    )
            r = asyncio.run(_post())
            summary.update({
                "status_code": r.status_code,
                "text_head": (r.text or "")[:2500],
                "done": "event: done" in (r.text or ""),
                "error": "event: error" in (r.text or ""),
                "turn": int(game.state.turn),
            })
        except Exception as exc:
            summary.update({"exc": type(exc).__name__, "msg": str(exc)[:500]})
        finally:
            try:
                game.session.close()
            except Exception:
                pass
        print("@@SUMMARY@@" + json.dumps(summary, ensure_ascii=False), flush=True)
        """
    )
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    body_json = json.dumps(choices, ensure_ascii=False, separators=(",", ":"))
    proc = subprocess.run(
        [sys.executable, "-c", worker, db_path, body_json, crash],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=root,
        env={**os.environ, "MING_SIM_DB": db_path, "OPENAI_API_KEY": "sk-test"},
    )
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    marker = "@@SUMMARY@@"
    body_canon = body_json
    if marker not in out:
        if crash == "phase2" and proc.returncode == 97:
            return {
                "db_path": db_path,
                "_returncode": 97,
                "_killed": True,
                "_body_canonical": body_canon,
                "error": True,
                "done": False,
            }
        raise AssertionError(
            f"subprocess missing summary exit={proc.returncode}\n"
            f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    payload = out.split(marker, 1)[1].strip().splitlines()[0]
    data = json.loads(payload)
    data["_returncode"] = proc.returncode
    data["_body_canonical"] = body_canon
    data["_killed"] = False
    return data


def test_1589_pure_decision_keyless_rejected_then_keyed_same_choice_passes(web_game):
    """#1589：纯 decision 无键合法 choice 整批拒；显式 key 的同一选择正常通过。"""
    from ming_sim.content import GameContent
    from ming_sim.db import GameDB
    db_path = _657_db_path_of(web_game)
    _657_plant_awaiting_web(web_game, decisions=[{
        'title': '科参驳还', 'context': '科臣封驳',
        'options': [{'label': '打回', 'hint': '驳'}, {'label': '准', 'hint': ''}],
        'event_id': '',
    }])
    desk = web_game.db.list_rescript_desk(int(web_game.state.turn))
    d_key = str(desk[0]['decision_key'])
    turn_before = int(web_game.state.turn)
    dossiers_before = len(web_game.db.list_decree_dossiers())
    web_game.session.close()
    baseline_game = web_app.WebGame(fresh=False)
    events_before = baseline_game.db.conn.execute(
        'SELECT COUNT(*) AS c FROM event_triggers'
    ).fetchone()['c']
    baseline_game.session.close()

    r1 = _657_subprocess_resolve(db_path, [{'label': '打回', 'hint': '驳'}])
    assert r1.get('error') is True, r1
    probe = GameDB(db_path, GameContent.load())
    rows = probe.list_pending_decisions(turn_before)
    assert rows and str(rows[0].get('status') or '') == 'pending'
    assert not rows[0].get('choice')
    assert len(probe.list_decree_dossiers()) == dossiers_before
    events_after = probe.conn.execute(
        'SELECT COUNT(*) AS c FROM event_triggers'
    ).fetchone()['c']
    assert events_after == events_before
    probe.close()

    r2 = _657_subprocess_resolve(
        db_path, [{'decision_key': d_key, 'label': '打回', 'hint': '驳', 'action': 'decision'}],
    )
    assert r2.get('done') is True, r2
    assert r2.get('error') is False, r2


def test_1589_empty_desk_rejects_nonempty_keyless_choices(web_game, monkeypatch):
    """#1589：desk 空时非空无键载荷整批拒。"""
    from ming_sim.decree import ResolveResult
    db, state = (web_game.db, web_game.state)
    _657_plant_awaiting_web(web_game)
    turn = int(state.turn)
    assert db.list_rescript_desk(turn) == []
    phase2_calls: list[int] = []

    def _phase2(_state, _db, *_a, **_k):
        phase2_calls.append(1)
        return ResolveResult(report='邸报', awaiting=False, advanced=False)

    monkeypatch.setattr("ming_sim.month_chain.run_player_month_chain", _phase2)
    r1 = asyncio.run(_post_resolve([{'label': '留', 'note': '无键'}]))
    assert r1.status_code == 200, r1.text
    assert 'event: error' in (r1.text or '')
    assert phase2_calls == []
