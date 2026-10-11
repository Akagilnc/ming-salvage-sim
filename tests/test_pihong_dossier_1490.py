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
import copy
import asyncio
import json
import httpx
import pytest
import ming_sim.agents as agents_mod
import ming_sim.decree as decree_mod
import ming_sim.session as session_mod
import web_app
from tests.rescript_test_helpers import sql_rescript_draft
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

def _657_install_real_phase2_llm_boundary(monkeypatch_or_module):
    """只中和 phase2 LLM 边界；保留 resolve_decisions_phase2 真结算/推月。"""
    import ming_sim.mechanical_tail as mechanical_tail

    # 机械尾关系酿制改为空操作，避免 sk-test 配置触发真实模型调用。
    _noop_brew = lambda *a, **k: None
    if hasattr(monkeypatch_or_module, "setattr"):
        monkeypatch_or_module.setattr(
            mechanical_tail, "_run_relation_brew", _noop_brew,
        )
    else:
        mechanical_tail._run_relation_brew = _noop_brew

def _657_subprocess_resolve(
    db_path: str,
    choices: list,
    *,
    crash: str = "",
    prewrite_mode: str = "",
    timeout: float = 180.0,
) -> dict:
    """同文件可复用：子进程真 HTTP POST resolve_decisions/stream。

    crash:
      - "" 正常跑完（真 phase2 + LLM 边界 stub）
      - "phase2" 领域 ① 已 commit 后、进入 phase2 时 os._exit 真杀进程
    prewrite_mode:
      - "" 无 prewrite LLM
      - "revise" stub 改票新 options
      - "deliberate" stub 廷议意愿
    stdout 只回传 @@SUMMARY@@ JSON；真杀进程无 summary 时父进程认 returncode。
    """
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
        prewrite_mode = sys.argv[4]
        os.environ["MING_SIM_DB"] = db_path
        os.environ["OPENAI_API_KEY"] = "sk-test"
        os.environ.pop("MING_SIM_LLM_BACKEND", None)

        import httpx
        import ming_sim.decree as dm
        import ming_sim.rescript_actions as ra
        import ming_sim.session as session_mod
        import web_app
        from ming_sim.models import TurnPhase

        web_app.load_runtime_llm = lambda: {}
        web_app.run_highlight_judge = lambda **_k: []

        # 真 phase2：只 stub LLM 边界
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
        # Agent-text boundary only. parse_agent_json, archive, and advance stay real.
        import ming_sim.agents as agents_mod
        _real_run_agent_text = agents_mod.run_agent_text

        def _run_agent_text(agent, prompt, tag, **kwargs):
            if tag == "gazette":
                return '{"title":"邸报","report":"本月实况。"}'
            return _real_run_agent_text(agent, prompt, tag, **kwargs)

        agents_mod.run_agent_text = _run_agent_text

        if crash == "phase2":
            def _kill_at_phase2(*a, **k):
                # §E.2：领域 commit 后、写 extracted 前真杀进程（禁 SSE 捕获后正常 close）
                os._exit(97)

            session_mod.resolve_decisions_phase2 = _kill_at_phase2
            dm.resolve_decisions_phase2 = _kill_at_phase2

        if prewrite_mode == "revise":
            def _fake_prewrite(batch, **kwargs):
                out = {}
                for it in batch.items:
                    if getattr(it, "needs_revise_llm", False) or str(
                        (it.choice or {}).get("action") or ""
                    ) == "return_revise":
                        # 完整合法 Layer-A raw（六必填+三 PRESENT）；禁伪造 draft_capability
                        # #1624：assignment 组合契约须 transaction_category 或点将主办
                        out[it.decision_key] = [
                            {"label": "新拟甲", "hint": "h1",
                             "action_type": "assignment", "target_kind": "region",
                             "target_id": "shaanxi", "locality_scope": "single",
                             "region_id": "shaanxi", "assignee_name": "",
                             "transaction_category": "督赈", "deadline_months": 2,
                             "participant_roster": [
                                 {"character_id": "毕自严", "tier": "主办",
                                  "role": "", "delegator_id": None},
                             ]},
                            {"label": "新拟乙", "hint": "h2",
                             "action_type": "assignment", "target_kind": "region",
                             "target_id": "shaanxi", "locality_scope": "single",
                             "region_id": "shaanxi", "assignee_name": "杨嗣昌",
                             "transaction_category": "",
                             "participant_roster": [
                                 {"character_id": "杨嗣昌", "tier": "主办",
                                  "role": "", "delegator_id": None},
                             ]},
                        ]
                return ra.PrewriteResults(revise_by_key=out)
            ra.run_prewrite_llms = _fake_prewrite
        elif prewrite_mode == "deliberate":
            def _fake_prewrite(batch, **kwargs):
                out = {}
                for it in batch.items:
                    out[it.decision_key] = {
                        "title": "廷议", "body": "臣请集议。", "stance": "主赈",
                        "supporter_ids": [],
                    }
                return ra.PrewriteResults(deliberate_by_key=out)
            ra.run_prewrite_llms = _fake_prewrite

        game = web_app.WebGame(fresh=False)
        web_app.web_game = game
        # 保持待裁
        game.state.turn_phase = TurnPhase.AWAITING_DECISION.value
        game.session.state.turn_phase = TurnPhase.AWAITING_DECISION.value
        game.db.reign.save_game_state(game.state)

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
        [sys.executable, "-c", worker, db_path, body_json, crash, prewrite_mode],
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
        # 真杀进程：无 finally/summary；returncode 97 即 §E.2 可观测终止
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
    db.issues.save_pending_decisions(state.turn, [{'event_id': f'dossier:{dossier_id}', 'title': '批红待裁', 'context': '密查陕西驿卒', 'rejection_reason': '科臣封驳', 'opposition': '东林', 'options': options}])
    db.resolve_contexts.save(state.turn, '诏曰密查', {'candidate_events': [{'id': 'ev_border', 'title': '边警'}], 'transit_semantics': []})
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.reign.save_game_state(state)
    return dossier_id


def _plant_due_commitment_shaped_awaiting(db, state, *, dossier_id: int=12):
    """种 due-commitment 同形：event_id=dossier:N，options 仅 {label,hint}。"""
    options = [{'label': '准其销号', 'hint': '事已办结'}, {'label': '着再催办', 'hint': '期限宽延'}]
    db.issues.save_pending_decisions(state.turn, [{'event_id': f'dossier:{dossier_id}', 'title': '承诺到期核验', 'context': '清丈之诺届期', 'options': options}])
    db.resolve_contexts.save(state.turn, '诏曰核验', {'candidate_events': [{'id': 'ev_border', 'title': '边警'}]})
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.reign.save_game_state(state)



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

def _roster(*names, tier='主办'):
    return [{'character_id': n, 'tier': tier, 'role': '', 'delegator_id': None} for n in names]

def _layer_a_option(**overrides):
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option
    base = {'label': '发帑赈济', 'hint': '所安者饥民', 'action_type': 'assignment', 'assignee_name': '', 'target_kind': 'region', 'target_id': 'shaanxi', 'locality_scope': 'single', 'region_id': 'shaanxi', 'transaction_category': '督赈', 'title': '陕西赈济', 'deadline_months': 3, 'participant_roster': [dict(item) for item in _ROSTER]}
    base.update(overrides)
    return normalize_rescript_layer_a_option(base)


def _plant_urgent_desk(db, state, *, options=None, actor_name='杨嗣昌'):
    opts = options or [_layer_a_option(), _layer_a_option(label='缓征', hint='先赈后征')]
    sql_rescript_draft(db, int(state.turn), idx=0, event_id='plant:陕西告饥', title='陕西告饥', context='秦地赤旱', options=opts, actor_name=actor_name, actor_office='兵部尚书', actor_faction='东林')
    db.conn.commit()
    desk = db.issues.list_rescript_desk(int(state.turn))
    urgent = next((r for r in desk if r['kind'] == 'rescript_draft'))
    return (urgent, opts)

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







def _657_db_path_of(game_or_path) -> str:
    if isinstance(game_or_path, str):
        return game_or_path
    path = getattr(game_or_path, 'db_path', None)
    if path:
        return str(path)
    db = getattr(game_or_path, 'db', None)
    return str(getattr(db, 'path', None) or getattr(db, 'db_path', None) or '')

    # subprocess worker 内无 monkeypatch 对象时同步写 dm


def _657_plant_awaiting_web(web_game, *, drafts=None, decisions=None, title='陕西告饥'):
    """web_game 上种植急务/decision + resolve_context，相位 AWAITING_DECISION。"""
    from ming_sim.models import TurnPhase
    db, state = (web_game.db, web_game.state)
    db.conn.execute('DELETE FROM pending_decisions')
    db.conn.commit()
    if drafts:

        for idx, draft in enumerate(drafts):
            sql_rescript_draft(db, int(state.turn), idx=idx, event_id=f'plant:{draft["title"]}', **draft)
    if decisions:
        db.issues.save_pending_decisions(int(state.turn), decisions)
    db.resolve_contexts.save(int(state.turn), '诏', {'candidate_events': [], 'transit_semantics': []})
    db.save_turn_report(state, '邸报')
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.reign.save_game_state(state)
    web_game.state.turn_phase = TurnPhase.AWAITING_DECISION.value
    web_game.session.state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.conn.commit()
    return db.issues.list_rescript_desk(int(state.turn))

def test_1627_stamp_ignores_pre_edict_clarification_directive(web_game):
    """亲裁落印不被颁诏前留下的待澄清拟旨阻断。"""
    from ming_sim.content import GameContent
    from ming_sim.db import GameDB
    db_path = _657_db_path_of(web_game)
    desk = _657_plant_awaiting_web(web_game, decisions=[{'title': '科参驳还', 'context': '科臣封驳', 'options': [{'label': '打回', 'hint': '驳'}, {'label': '准', 'hint': ''}], 'event_id': ''}])
    turn = int(web_game.state.turn)
    pending_id = web_game.db.stage_pending_action(turn, kind='directive', action='拟旨', minister_name='张居正', target_id=None, payload={'text': '着兵部再议边防。', '_needs_clarification': True, 'dossier_action_type': 'policy', 'target_kind': 'issue', 'target_id': 'border-defense'})
    web_game.db.conn.commit()
    decision_key = str(desk[0]['decision_key'])
    web_game.session.close()
    result = _657_subprocess_resolve(db_path, [{'decision_key': decision_key, 'label': '准', 'hint': '', 'action': 'decision'}])
    assert result.get('done') is True, result
    assert result.get('error') is False, result
    probe = GameDB(db_path, GameContent.load())
    try:
        row = probe.conn.execute('SELECT status, turn, night_id, night_approved FROM pending_actions WHERE id=?', (pending_id,)).fetchone()
        assert row is not None and row['status'] == 'pending'
        next_turn = int(probe.load_state().turn)
        assert next_turn == turn + 1
        assert row['turn'] == next_turn
        assert row['night_id'] == 0
        assert row['night_approved'] == 0
        assert pending_id in {int(action['id']) for action in probe.dossiers.list_pending_actions(next_turn)}
    finally:
        probe.close()





def test_1682_late_grants_follow_policy_without_consuming_verdict_batch(game, monkeypatch):
    """Late HITL grants auto-promulgate only canonical review-exempt dossiers."""
    from ming_sim import rescript_actions as ra
    db, state, content = game
    options = [{'label': '发内帑', 'hint': 'h', 'action_type': 'grant_allocation', 'grant_action': '协饷', 'account': '内库', 'amount': 7, 'purpose': '补饷', 'cadence': '一次性', 'execution_surface': 'immediate', 'target_kind': 'army', 'target_id': 'guanning'}, {'label': '国库赏赉', 'hint': 'h', 'action_type': 'grant_allocation', 'grant_action': '协饷', 'account': '国库', 'amount': 11, 'purpose': '补饷', 'cadence': '一次性', 'target_kind': 'army', 'target_id': 'guanning'}]
    db.issues.save_pending_decisions(state.turn, [{'event_id': '', 'title': '内帑', 'context': 'c', 'options': [options[0]]}, {'event_id': '', 'title': '国库', 'context': 'c', 'options': [options[1]]}])
    desk = db.issues.list_rescript_desk(int(state.turn))
    choices = [{'decision_key': row['decision_key'], 'label': row['options'][0]['label']} for row in desk]
    batch = ra.validate_all(desk, choices)
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=content)
    grants = [row for row in db.dossiers.list_dossiers() if row['action_type'] == 'grant_allocation' and _dossier_payload(row).get('decision_key') in {choice['decision_key'] for choice in choices}]
    assert len(grants) == 2
    by_account = {_dossier_payload(row)['account']: row for row in grants}
    inner = by_account['内库']
    assert inner['status'] == 'closed'
    assert inner['promulgation_decision'] == 'promulgated'
    assert len(db.reign.list_economy_moves_for_dossier(int(inner['id']))) == 1
    reviewed = by_account['国库']
    assert reviewed['status'] == 'proposed'
    assert reviewed['promulgation_decision'] == ''
    assert db.reign.list_economy_moves_for_dossier(int(reviewed['id'])) == []
    db.issues.save_pending_decisions(state.turn, [{'event_id': '', 'title': '先拨内帑', 'context': 'c', 'options': [options[0]]}, {'event_id': '', 'title': '后拨内帑失读', 'context': 'c', 'options': [options[0]]}])
    failed_rows = [row for row in db.issues.list_rescript_desk(int(state.turn)) if row['title'] in {'先拨内帑', '后拨内帑失读'}]
    failed_choices = [{'decision_key': row['decision_key'], 'label': row['options'][0]['label']} for row in failed_rows]
    failed_batch = ra.validate_all(failed_rows, failed_choices)
    dossiers_before = db.dossiers.list_dossiers()
    decisions_before = db.issues.list_pending_decisions(int(state.turn))
    accounts_before = db.conn.execute('SELECT account, metric_key, balance, note FROM economy_accounts ORDER BY account').fetchall()
    ledger_before = db.conn.execute('SELECT * FROM economy_ledger ORDER BY id').fetchall()
    metrics_before = copy.deepcopy(state.metrics)
    original_get = db.dossiers.get
    existing_ids = {int(row['id']) for row in dossiers_before}
    created_ids = []
    missed_ids = []

    def _miss_second_new_dossier(dossier_id):
        dossier_id = int(dossier_id)
        if dossier_id not in existing_ids and dossier_id not in created_ids:
            created_ids.append(dossier_id)
        if len(created_ids) >= 2 and dossier_id == created_ids[1]:
            missed_ids.append(dossier_id)
            return None
        return original_get(dossier_id)
    monkeypatch.setattr(db.dossiers, 'get', _miss_second_new_dossier)
    with pytest.raises(ValueError):
        ra.apply_rescript_batch(db, state, failed_batch, ra.PrewriteResults(), content=content)
    assert len(created_ids) == 2
    assert missed_ids == [created_ids[1]]
    assert db.dossiers.list_dossiers() == dossiers_before
    assert db.issues.list_pending_decisions(int(state.turn)) == decisions_before
    assert db.conn.execute('SELECT account, metric_key, balance, note FROM economy_accounts ORDER BY account').fetchall() == accounts_before
    assert db.conn.execute('SELECT * FROM economy_ledger ORDER BY id').fetchall() == ledger_before
    assert state.metrics == metrics_before
    assert db.load_state().metrics == metrics_before




def test_1589_pure_decision_keyless_rejected_then_keyed_same_choice_passes(web_game):
    """#1589：纯 decision 无急务时，无键合法 choice 修前经 submit_decisions 位置匹配受理；
    修后整批拒——decision 仍 pending、choice 未写、事件/案卷零写；显式 key 的同一选择正常通过。"""
    from ming_sim.content import GameContent
    from ming_sim.db import GameDB
    db_path = _657_db_path_of(web_game)
    _657_plant_awaiting_web(web_game, decisions=[{'title': '科参驳还', 'context': '科臣封驳', 'options': [{'label': '打回', 'hint': '驳'}, {'label': '准', 'hint': ''}], 'event_id': ''}])
    desk = web_game.db.issues.list_rescript_desk(int(web_game.state.turn))
    d_key = str(desk[0]['decision_key'])
    turn_before = int(web_game.state.turn)
    dossiers_before = len(web_game.db.dossiers.list_dossiers())
    web_game.session.close()
    baseline_game = web_app.WebGame(fresh=False)
    events_before = baseline_game.db.conn.execute('SELECT COUNT(*) AS c FROM event_triggers').fetchone()['c']
    baseline_game.session.close()
    keyless = [{'label': '打回', 'hint': '驳'}]
    r1 = _657_subprocess_resolve(db_path, keyless)
    assert r1.get('error') is True, r1
    assert r1.get('done') is not True, r1
    probe = GameDB(db_path, GameContent.load())
    try:
        assert int(probe.load_state().turn) == turn_before
        decs = probe.issues.list_pending_decisions(turn_before)
        assert decs and all((str(d.get('status')) == 'pending' for d in decs)), decs
        assert all((not d.get('choice') for d in decs)), decs
        assert len(probe.dossiers.list_dossiers()) == dossiers_before
        events_after = probe.conn.execute('SELECT COUNT(*) AS c FROM event_triggers').fetchone()['c']
        assert events_after == events_before, (events_before, events_after)
    finally:
        probe.close()
    keyed = [{'decision_key': d_key, 'label': '打回', 'hint': '驳', 'action': 'decision'}]
    r2 = _657_subprocess_resolve(db_path, keyed)
    assert r2.get('done') is True, r2
    probe = GameDB(db_path, GameContent.load())
    try:
        decs = probe.issues.list_pending_decisions(turn_before)
        assert not decs or all((d.get('status') == 'decided' for d in decs)), decs
    finally:
        probe.close()

def test_1589_empty_desk_rejects_nonempty_keyless_choices(web_game, monkeypatch):
    """#1589 fix5：desk 空（无 pending 急务/decision）时非空无键载荷同样整批拒——
    唯一合法续跑是真正空 choices（#1322）；不保留空 desk 例外。"""
    db, state = (web_game.db, web_game.state)
    _657_plant_awaiting_web(web_game)
    turn = int(state.turn)
    assert db.issues.list_rescript_desk(turn) == []
    phase2_calls: list[int] = []

    def _phase2(_state, _db, *_a, **_k):
        phase2_calls.append(1)
        return '邸报'
    monkeypatch.setattr(session_mod, 'resolve_decisions_phase2', _phase2)
    r1 = asyncio.run(_post_resolve([{'label': '留', 'note': '无键'}]))
    assert r1.status_code == 200, r1.text
    assert 'event: error' in r1.text, r1.text
    assert 'event: done' not in r1.text, r1.text
    assert phase2_calls == [], '空 desk + 非空无键载荷须整批拒，不得进 phase2'
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.reign.save_game_state(state)
    r2 = asyncio.run(_post_resolve([]))
    assert r2.status_code == 200, r2.text
    assert 'event: done' in r2.text, r2.text
    assert phase2_calls == [1], '真正空 choices 续跑仍合法，走 submit_decisions'






def test_1620_layer_a_money_grant_requires_positive_amount():
    """#1620：层 A shape 独掌 grant——正 amount/honorific/私库 + 非法 action/非积分 amount。"""
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option
    base = {'label': '赏银', 'hint': '赏功', 'action_type': 'grant_allocation', 'assignee_name': '', 'target_kind': 'character', 'target_id': '张瑞图', 'locality_scope': 'none', 'region_id': '', 'transaction_category': '', 'grant_action': '赏赉', 'name': '张瑞图'}
    with pytest.raises(ValueError):
        normalize_rescript_layer_a_option(base)
    with pytest.raises(ValueError):
        normalize_rescript_layer_a_option({**base, 'amount': 0})
    with pytest.raises(ValueError):
        normalize_rescript_layer_a_option({**base, 'amount': 10, 'account': '私库'})
    with pytest.raises(ValueError):
        normalize_rescript_layer_a_option({**base, 'amount': 10, 'grant_action': '无'})
    with pytest.raises(ValueError):
        normalize_rescript_layer_a_option({**base, 'amount': 10, 'grant_action': '未知赏'})
    with pytest.raises(ValueError):
        normalize_rescript_layer_a_option({**base, 'amount': True})
    with pytest.raises(ValueError):
        normalize_rescript_layer_a_option({**base, 'amount': 1.5})
    ok = normalize_rescript_layer_a_option({**base, 'amount': 10})
    assert int(ok['amount']) == 10
    assert str(ok.get('account') or '') == ''
    taicang = normalize_rescript_layer_a_option({**base, 'amount': 10, 'account': '太仓'})
    guoku = normalize_rescript_layer_a_option({**base, 'amount': 10, 'account': '国库'})
    assert str(taicang.get('account') or '') == '国库'
    assert str(guoku.get('account') or '') == '国库'
    assert taicang['draft_capability'] == guoku['draft_capability']
    assert taicang['draft_capability'] != ok['draft_capability']
    honor = normalize_rescript_layer_a_option({**base, 'grant_action': '加衔', 'label': '加衔'})
    assert honor.get('grant_action') == '加衔'
    assert 'amount' not in honor





# ---------------------------------------------------------------------------
# #657 大理寺六类：扩展既有 tracer，不另造夹具族
# ---------------------------------------------------------------------------

def test_1682_phase2_surfaces_ambiguous_stored_choice(game):
    """批红真入口拒绝同名选项，且拒绝前不得落亲裁。"""
    from contextlib import nullcontext
    from ming_sim.models import TurnPhase
    from tests.month_chain_helpers import make_light_session

    db, state, content = game
    db.issues.save_pending_decisions(int(state.turn), [{'title': '歧义亲裁', 'context': 'c', 'options': [{'label': '同名', 'hint': '一'}, {'label': ' 同名 ', 'hint': '二'}]}])
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.reign.save_game_state(state)
    session = make_light_session(db, state, content)
    choice = [{'decision_key': db.issues.list_rescript_desk(int(state.turn))[0]['decision_key'], 'label': '同名', 'action': 'decision'}]
    with pytest.raises(ValueError):
        session.submit_hitl_choices(choice, write_gate=nullcontext())
    assert db.issues.list_pending_decisions(int(state.turn))[0]['status'] == 'pending'



def test_657_appointment_name_target_id_conflict_batch_reject(game):
    """⑥ appointment/dismiss name≠target_id 在 mapper 单一边界整批拒绝。

    区分度在**各自的 action_type/appoint_action**（任命 / 罢免两条边界各自跑一遍）；
    报错措辞不是契约（#1889）。
    """
    from ming_sim import rescript_actions as ra
    db, state, content = game
    rows = db.conn.execute("SELECT name FROM characters WHERE status='active' AND power_id='ming' ORDER BY name LIMIT 2").fetchall()
    assert len(rows) >= 2
    n1, n2 = (str(rows[0]['name']), str(rows[1]['name']))
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({'action_type': 'appointment', 'appoint_action': '任命', 'office': '兵部尚书', 'name': n1, 'target_kind': 'character', 'target_id': n2, 'label': '授官'}, db=db, content=content, state=state)
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({'action_type': 'appointment', 'appoint_action': '罢免', 'office': '', 'name': n1, 'target_kind': 'character', 'target_id': n2, 'label': '罢'}, db=db, content=content, state=state)








def _summonable_name(db, content):
    from ming_sim import rescript_actions as ra
    ids = ra.list_deliberation_candidate_ids(db, content)
    assert ids, 'fixture 须有可召大臣'
    return ids[0]

def _658_plant_stalled_deliberation(db, state, content, *, title='议而不决'):
    """最短：经 deliberate 真写核种一条 stalled 案卷 + active issue。"""
    from ming_sim import rescript_actions as ra
    urgent, _ = _plant_urgent_desk(db, state)
    key = urgent['decision_key']
    batch = ra.validate_all([urgent], [{'decision_key': key, 'action': 'deliberate', 'label': '下部议'}])
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(deliberate_by_key={key: {'title': title, 'body': f'{title}正文', 'stance': '冷', 'supporter_ids': []}}), content=content)
    stalled = db.dossiers.find_by_decision_key(key)
    assert stalled is not None
    return (stalled, key)




def test_658_endorsement_provenance_xor(game):
    """#658：背书 provenance 恰为 chat_turn 或 decision_key 之一。"""
    db, state, content = game
    minister = _summonable_name(db, content)
    did = db.create_decree_dossier(state, action_type='policy', decree_text='试', target_kind='policy', target_id='t')
    chat = db.create_chat_turn(state, minister, '658-xor', 0)
    db.dossiers.add_endorsement(did, form='会签', endorser_id=minister, source_chat_turn_id=chat)
    row = db.dossiers.endorsements(did)[0]
    assert row['source_chat_turn_id'] == chat and row['decision_key'] == ''
    eid2 = db.dossiers.add_endorsement(did, form='当面站台', endorser_id=minister, decision_key='rescript_draft:1:0')
    rows = {e['id']: e for e in db.dossiers.endorsements(did)}
    assert rows[eid2]['decision_key'] == 'rescript_draft:1:0'
    assert rows[eid2]['source_chat_turn_id'] == 0
    with pytest.raises(ValueError):
        db.dossiers.add_endorsement(did, form='会签', endorser_id=minister, source_chat_turn_id=chat, decision_key='x')
    with pytest.raises(ValueError):
        db.dossiers.add_endorsement(did, form='会签', endorser_id=minister)





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
    bad = int(db.issues.add_directive(
            state.turn, state.year, state.period, None,
            '缺账拨帑', 'player-decree-test', dossier_payload={'dossier_action_type': 'grant_allocation', 'target_kind': 'issue', 'target_id': 'route-缺账', 'amount': 100}))
    good = int(db.issues.add_directive(
            state.turn, state.year, state.period, None,
            '清丈', 'player-decree-test', dossier_payload={'dossier_action_type': 'assignment', 'target_kind': 'issue', 'target_id': 'route-清丈', 'transaction_category': '清丈', 'participant_roster': _roster(_ROSTER_LEAD)}))
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





# ---------------------------------------------------------------------------
# #1778：参与名单由拟票大臣写进票拟；成案钉进案卷；代码不配人
# ---------------------------------------------------------------------------


def test_657_record_event_choice_failure_rolls_back_batch(game, monkeypatch):
    from ming_sim import rescript_actions as ra
    db, state, content = game
    opt = _layer_a_option()
    urgent, _ = _plant_urgent_desk(db, state, options=[opt, _layer_a_option(label='备', hint='b')])
    db.conn.execute("INSERT OR IGNORE INTO events (id, title, kind, summary, urgency, severity, credibility, interests, audiences) VALUES ('ev-class5', '边警', 'test', 'class5', 1, 1, 50, '[]', '[]')")
    db.issues.save_pending_decisions(int(state.turn), [{'title': '边警', 'context': 'c', 'options': [{'label': '打回', 'hint': '驳回'}, {'label': '准', 'hint': ''}], 'event_id': 'ev-class5'}])
    db.conn.commit()
    desk = db.issues.list_rescript_desk(int(state.turn))
    u_key = next((r['decision_key'] for r in desk if r['kind'] == 'rescript_draft'))
    d_key = next((r['decision_key'] for r in desk if r['kind'] == 'decision'))

    def boom(*_a, **_k):
        raise RuntimeError('event ledger inject')
    monkeypatch.setattr(db, 'record_event_decision_choice', boom)
    before_triggers = db.conn.execute('SELECT COUNT(*) AS c FROM event_triggers').fetchone()['c']
    batch = ra.validate_all(desk, [{'decision_key': u_key, 'action': 'follow_draft', 'draft_capability': opt['draft_capability'], 'label': opt['label']}, {'decision_key': d_key, 'label': '打回', 'hint': '驳回', 'action': 'decision'}])
    with pytest.raises(RuntimeError):
        ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=content)
    drafts = [r for r in db.issues.list_rescript_drafts() if r['title'] == '陕西告饥']
    assert drafts and drafts[0]['status'] == 'pending'
    decs = db.issues.list_pending_decisions(int(state.turn))
    assert decs and decs[0]['status'] == 'pending'
    after_triggers = db.conn.execute('SELECT COUNT(*) AS c FROM event_triggers').fetchone()['c']
    assert after_triggers == before_triggers


def test_657_illegal_summon_target_http_zero_writes(web_game, monkeypatch):
    from ming_sim.models import TurnPhase
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option
    db, state = (web_game.db, web_game.state)

    def _phase2(_state, _db, *_a, **_k):
        raise AssertionError('illegal summon must not reach phase2')
    monkeypatch.setattr(session_mod, 'resolve_decisions_phase2', _phase2)
    opt = normalize_rescript_layer_a_option({'label': '备', 'hint': 'h', 'action_type': 'assignment', 'assignee_name': '', 'target_kind': 'region', 'target_id': 'shaanxi', 'locality_scope': 'single', 'region_id': 'shaanxi', 'transaction_category': '督赈'})
    ledger_before = db.conn.execute('SELECT COUNT(*) AS c FROM story_ledger_entries').fetchone()['c']
    desk = _657_plant_awaiting_web(web_game, drafts=[{'title': '非法召见', 'context': 'c', 'options': [opt, {'label': 'x', 'hint': 'h', 'draft_capability': 'x'}], 'actor_name': '杨嗣昌', 'actor_office': 'o', 'actor_faction': 'f'}])
    key = desk[0]['decision_key']
    r = asyncio.run(_post_resolve([{'decision_key': key, 'action': 'summon', 'label': '召见', 'summon_target': '不存在的边将xyz'}]))
    assert r.status_code == 200
    hit = next((x for x in db.issues.list_rescript_drafts() if x['title'] == '非法召见'))
    assert hit['status'] == 'pending'
    assert not hit['choice']
    ledger_after = db.conn.execute('SELECT COUNT(*) AS c FROM story_ledger_entries').fetchone()['c']
    assert ledger_after == ledger_before


def test_657_follow_draft_ignores_client_field_overlay(game):
    from ming_sim import rescript_actions as ra
    db, state, content = game
    opt = _layer_a_option(label='权威票拟', target_id='shaanxi', region_id='shaanxi', transaction_category='督赈', title='权威标题')
    urgent, _ = _plant_urgent_desk(db, state, options=[opt, _layer_a_option(label='备')])
    key = urgent['decision_key']
    before = len(db.dossiers.list_dossiers())
    batch = ra.validate_all([urgent], [{'decision_key': key, 'action': 'follow_draft', 'draft_capability': opt['draft_capability'], 'label': opt['label'], 'target_id': 'henan', 'region_id': 'henan', 'title': '伪造标题', 'transaction_category': '练兵', 'assignee_name': '不存在的人'}])
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=content)
    after = db.dossiers.list_dossiers()
    assert len(after) == before + 1
    created = after[-1]
    payload = json.loads(str(created.get('payload_json') or '{}'))
    assert str(created.get('target_id') or payload.get('target_id') or '') == 'shaanxi'
    assert 'henan' not in {str(created.get('target_id') or ''), str(payload.get('target_id') or ''), str(created.get('region_id') or ''), str(payload.get('region_id') or '')}
    assert str(payload.get('title') or '') == '权威标题'
    assert '伪造标题' not in str(payload.get('title') or '')
    assert str(payload.get('transaction_category') or '') == '督赈'
    assert '不存在的人' not in str(payload.get('assignee_name') or '')
    assert '不存在的人' not in str(created.get('executor_id') or '')


def test_657_clear_revise_anchor_corrupt_json_fails_loud(game):
    from ming_sim import rescript_actions as ra
    from ming_sim.applier import StoredDocumentError
    db, state, _content = game
    urgent, _ = _plant_urgent_desk(db, state)
    db.conn.execute("UPDATE pending_decisions SET choice_json=?, revision_round=1 WHERE turn=? AND idx=? AND kind='rescript_draft'", ('{not-json', int(urgent['source_turn'] or urgent['turn']), int(urgent['idx'])))
    db.conn.commit()
    with pytest.raises(StoredDocumentError):
        ra.clear_return_revise_choice_anchors(db, None)
    db.conn.execute("UPDATE pending_decisions SET choice_json=? WHERE turn=? AND idx=? AND kind='rescript_draft'", ('[1,2]', int(urgent['source_turn'] or urgent['turn']), int(urgent['idx'])))
    db.conn.commit()
    with pytest.raises(StoredDocumentError):
        ra.clear_return_revise_choice_anchors(db, None)


def test_657_punishment_name_target_id_conflict_zero_writes(web_game, monkeypatch):
    from ming_sim import rescript_actions as ra
    from ming_sim.models import TurnPhase
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option
    db, state = (web_game.db, web_game.state)
    rows = db.conn.execute("SELECT name FROM characters WHERE status='active' AND power_id='ming' ORDER BY name LIMIT 2").fetchall()
    assert len(rows) >= 2
    n1, n2 = (str(rows[0]['name']), str(rows[1]['name']))
    with pytest.raises(ValueError):
        ra.map_rescript_option_or_choice({'action_type': 'punishment', 'punish_action': '廷杖', 'name': n1, 'target_kind': 'character', 'target_id': n2, 'label': '责', 'locality_scope': 'none'}, db=db, content=web_game.content, state=state)
    ok = ra.map_rescript_option_or_choice({'action_type': 'punishment', 'punish_action': '廷杖', 'name': n1, 'target_kind': 'character', 'target_id': n1, 'label': '责', 'locality_scope': 'none'}, db=db, content=web_game.content, state=state)
    assert ok['name'] == n1 and ok['target_id'] == n1
    ok_one = ra.map_rescript_option_or_choice({'action_type': 'punishment', 'punish_action': '廷杖', 'target_kind': 'character', 'target_id': n1, 'label': '责', 'locality_scope': 'none'}, db=db, content=web_game.content, state=state)
    assert ok_one['name'] == n1 and ok_one['target_id'] == n1
    opt_base = normalize_rescript_layer_a_option({'label': '责', 'hint': 'h', 'action_type': 'punishment', 'assignee_name': '', 'target_kind': 'character', 'target_id': n1, 'name': n1, 'punish_action': '廷杖', 'locality_scope': 'none', 'region_id': '', 'transaction_category': ''})
    _657_plant_awaiting_web(web_game, drafts=[{'title': '惩处冲突', 'context': 'c', 'options': [opt_base, {'label': 'x', 'hint': 'h', 'draft_capability': 'z'}], 'actor_name': n1, 'actor_office': 'o', 'actor_faction': 'f'}])
    desk = db.issues.list_rescript_desk(int(state.turn))
    key = desk[0]['decision_key']
    before_status = db.characters.get_character_status(n1)[0]
    before_dossiers = db.conn.execute('SELECT COUNT(*) AS c FROM decree_dossiers').fetchone()['c']
    body = [{'decision_key': key, 'action': 'midzhi', 'label': '责', 'action_type': 'punishment', 'punish_action': '廷杖', 'name': n1, 'target_kind': 'character', 'target_id': n2, 'locality_scope': 'none', 'participant_roster': _roster(n1)}]
    r = asyncio.run(_post_resolve(body))
    assert r.status_code == 200
    assert db.characters.get_character_status(n1)[0] == before_status
    after_dossiers = db.conn.execute('SELECT COUNT(*) AS c FROM decree_dossiers').fetchone()['c']
    assert after_dossiers == before_dossiers
    assert web_game.state.turn_phase != TurnPhase.ISSUED.value
    hit = next((row for row in db.issues.list_rescript_drafts() if row['title'] == '惩处冲突'))
    assert hit['status'] == 'pending'
    assert hit.get('choice') in (None, {})


def test_657_revise_deliberate_strict_contracts_zero_write_on_bad_shape(game, monkeypatch):
    from ming_sim.rescript_actions import PrewriteResults
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option
    from ming_sim.decree import prepare_resolve_front_half
    from ming_sim.session import GameSession
    from ming_sim.models import TurnPhase
    import ming_sim.agents as agents_mod
    db, state, content = game
    opt = normalize_rescript_layer_a_option({'label': '备', 'hint': 'h', 'action_type': 'assignment', 'assignee_name': '', 'target_kind': 'region', 'target_id': 'shaanxi', 'locality_scope': 'single', 'region_id': 'shaanxi', 'transaction_category': '督赈', 'participant_roster': _roster(_ROSTER_LEAD)})
    db.conn.execute("DELETE FROM pending_decisions WHERE kind='rescript_draft'")
    prepare_resolve_front_half(state, db, decree_text='诏', content=content)
    sql_rescript_draft(db, int(state.turn), idx=0, event_id='plant:改票契约', title='改票契约', context='c', options=[opt, {'label': 'x', 'hint': 'h', 'draft_capability': 'z'}], actor_name='杨嗣昌', actor_office='o', actor_faction='f')
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.reign.save_game_state(state)
    desk = db.issues.list_rescript_desk(int(state.turn))
    key = desk[0]['decision_key']
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.llm_config = object()
    sess.agno_db = None
    sess.registry = None
    sess.last_decree = '诏'
    sess.temporary_characters = {}

    def _bad_revise_text(*_a, **_k):
        return json.dumps({'items': [{'title': 't', 'context': 'c', 'options': [opt]}]}, ensure_ascii=False)
    monkeypatch.setattr(agents_mod, 'create_rescript_revise_agent', lambda *_a, **_k: object())
    monkeypatch.setattr(agents_mod, 'run_agent_text', _bad_revise_text)
    with pytest.raises(RuntimeError):
        sess.prepare_rescript_prewrite([{'decision_key': key, 'action': 'return_revise', 'note': '再拟'}])
    hit = next((r for r in db.issues.list_rescript_drafts() if r['title'] == '改票契约'))
    assert hit['status'] == 'pending'
    assert hit.get('choice') in (None, {})

    def _military_option(target_id):
        return normalize_rescript_layer_a_option({'label': '调驻', 'hint': 'h2', 'action_type': 'military_order', 'assignee_name': '祖大寿', 'target_kind': 'army', 'target_id': target_id, 'locality_scope': 'none', 'region_id': '', 'transaction_category': '', 'station': '宁远', 'participant_roster': _roster('祖大寿')})
    seen_payload = {}

    def _outside_army_revise_text(_agent, raw_payload, **_kwargs):
        seen_payload.update(json.loads(raw_payload))
        return json.dumps({'options': [_military_option('manchu_banners_main')]}, ensure_ascii=False)
    monkeypatch.setattr(agents_mod, 'run_agent_text', _outside_army_revise_text)
    with pytest.raises(RuntimeError):
        sess.prepare_rescript_prewrite([{'decision_key': key, 'action': 'return_revise', 'note': '再拟'}])
    targets = {row['id']: row for row in seen_payload['army_targets']}
    assert targets['guanning']['station'] == db.conn.execute("SELECT station FROM armies WHERE id='guanning'").fetchone()['station']
    assert 'manchu_banners_main' not in targets
    hit = next((r for r in db.issues.list_rescript_drafts() if r['title'] == '改票契约'))
    assert hit['status'] == 'pending'
    assert hit.get('choice') in (None, {})
    army_pay_base = {'label': '补发关宁军饷', 'hint': '边饷急', 'action_type': 'grant_allocation', 'assignee_name': '', 'target_kind': 'army', 'target_id': 'guanning', 'locality_scope': 'none', 'region_id': '', 'transaction_category': '', 'amount': 300, 'account': '国库', 'purpose': '补饷', 'participant_roster': _roster(_ROSTER_LEAD)}
    for bad_opt, failed_fields in (
        ({**army_pay_base, 'grant_action': '协饷'}, {'grant_kind'}),
        ({**army_pay_base, 'grant_kind': 'army_pay', 'grant_action': '协饷'}, {'grant_kind', 'grant_action'}),
    ):
        monkeypatch.setattr(agents_mod, 'run_agent_text', lambda *_a, _opt=bad_opt, **_k: json.dumps({'options': [_opt]}, ensure_ascii=False))
        with pytest.raises(RuntimeError) as refused:
            sess.prepare_rescript_prewrite([{'decision_key': key, 'action': 'return_revise', 'note': '再拟'}])
        assert {fact['field'] for fact in refused.value.__cause__.field_failures} == failed_fields
        hit = next((r for r in db.issues.list_rescript_drafts() if r['title'] == '改票契约'))
        assert hit['status'] == 'pending'
        assert hit.get('choice') in (None, {})
    monkeypatch.setattr(agents_mod, 'run_agent_text', lambda *_a, **_k: json.dumps({'options': [_military_option('guanning')]}, ensure_ascii=False))
    military_pre = sess.prepare_rescript_prewrite([{'decision_key': key, 'action': 'return_revise', 'note': '再拟'}])
    assert military_pre['prewrite'].revise_by_key[key][0]['target_id'] == 'guanning'
    owner_opt = {'label': '着户部继续核查陕西赈务，按月具报。', 'hint': '督赈', 'action_type': 'assignment', 'target_kind': 'region', 'target_id': 'shaanxi', 'locality_scope': 'single', 'region_id': 'shaanxi', 'assignee_name': '', 'transaction_category': '督赈', 'deadline_months': 2, 'participant_roster': _roster(_ROSTER_LEAD)}

    def _ok_revise_text(*_a, **_k):
        return json.dumps({'options': [owner_opt]}, ensure_ascii=False)
    monkeypatch.setattr(agents_mod, 'run_agent_text', _ok_revise_text)
    pre = sess.prepare_rescript_prewrite([{'decision_key': key, 'action': 'return_revise', 'note': '再拟'}])
    assert isinstance(pre.get('prewrite'), PrewriteResults)
    ro = pre['prewrite'].revise_by_key
    assert key in ro and isinstance(ro[key], list) and (len(ro[key]) >= 1)
    revised = ro[key][0]
    assert revised['action_type'] == 'assignment'
    assert revised['target_kind'] == 'region'
    assert revised['target_id'] == 'shaanxi'
    assert revised['region_id'] == 'shaanxi'
    assert revised['locality_scope'] == 'single'
    assert revised['transaction_category'] == '督赈'
    assert not str(revised.get('assignee_name') or '').strip()

    def _bad_delib(*_a, **_k):
        return json.dumps({'title': 't', 'body': 'b'}, ensure_ascii=False)
    monkeypatch.setattr(agents_mod, 'create_rescript_deliberate_agent', lambda *_a, **_k: object())
    monkeypatch.setattr(agents_mod, 'run_agent_text', _bad_delib)
    with pytest.raises(RuntimeError):
        sess.prepare_rescript_prewrite([{'decision_key': key, 'action': 'deliberate', 'label': '下部议'}])
    hit2 = next((r for r in db.issues.list_rescript_drafts() if r['title'] == '改票契约'))
    assert hit2['status'] == 'pending'
    assert hit2.get('choice') in (None, {})


def test_658_stalled_excluded_from_promulgation_validation(game, monkeypatch):
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
    assert db.dossiers.get(stalled_id)['status'] == 'proposed'
    assert _dossier_payload(db.dossiers.get(stalled_id)).get('deliberation_state') == 'stalled'


def test_658_stage_rejects_bad_backing_zero_write(game):
    from ming_sim.action_materialize import stage_punishment_candidate
    from ming_sim.credit_events import KIND_BETRAY
    db, state, content = game
    from ming_sim import rescript_actions as ra
    names = ra.list_deliberation_candidate_ids(db, content)
    actor, target = (names[0], names[1])

    def snapshot() -> tuple[int, int, int]:
        pending = int(db.conn.execute("SELECT COUNT(*) AS c FROM pending_actions WHERE status='pending'").fetchone()['c'])
        dossiers = len(db.dossiers.list_dossiers())
        edges = int(db.conn.execute('SELECT COUNT(*) AS c FROM relation_edge_events WHERE event_kind=?', (KIND_BETRAY,)).fetchone()['c'])
        return (pending, dossiers, edges)
    before = snapshot()
    for bad in (True, False, 1.9, 1.0, "1", "12", 0, -1, 999999):
        with pytest.raises(ValueError):
            stage_punishment_candidate(db, state.turn, actor, text=f'着罚{target}俸。', target_id=target, punish_action='罚俸', amount=10, backing_dossier_id=bad)
    assert snapshot() == before
    from ming_sim import rescript_actions as ra
    urgent, _ = _plant_urgent_desk(db, state)
    key = urgent['decision_key']
    batch = ra.validate_all([urgent], [{'decision_key': key, 'action': 'deliberate', 'label': '下部议'}])
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(deliberate_by_key={key: {'title': '清', 'body': 'b', 'stance': 's', 'supporter_ids': [actor]}}), content=content)
    bid = int(db.dossiers.find_by_decision_key(key)['id'])
    pid = stage_punishment_candidate(db, state.turn, actor, text=f'着罚{target}俸。', target_id=target, punish_action='罚俸', amount=10, backing_dossier_id=bid)
    assert pid > 0
    staged = json.loads(db.conn.execute('SELECT payload_json FROM pending_actions WHERE id=?', (int(pid),)).fetchone()['payload_json'])
    assert int(staged.get('backing_dossier_id') or 0) == bid
    stage_punishment_candidate(db, state.turn, actor, text=f'着罚{target}俸（改）。', target_id=target, punish_action='罚俸', amount=10)
    staged2 = json.loads(db.conn.execute('SELECT payload_json FROM pending_actions WHERE id=?', (int(pid),)).fetchone()['payload_json'])
    assert staged2.get('backing_dossier_id') in (None, '')


def test_658_candidates_require_active_status(game):
    from ming_sim import rescript_actions as ra
    db, state, content = game
    name = _summonable_name(db, content)
    assert name in ra.list_deliberation_candidate_ids(db, content)
    db.set_character_status(state, name, 'dismissed', '658-candidate')
    assert name not in ra.list_deliberation_candidate_ids(db, content)
    urgent, _ = _plant_urgent_desk(db, state)
    key = urgent['decision_key']
    before = len(db.dossiers.list_dossiers())
    batch = ra.validate_all([urgent], [{'decision_key': key, 'action': 'deliberate', 'label': '下部议'}])
    with pytest.raises(ValueError):
        ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(deliberate_by_key={key: {'title': 't', 'body': 'b', 'stance': 's', 'supporter_ids': [name]}}), content=content)
    assert len(db.dossiers.list_dossiers()) == before


def test_658_ordinary_edit_does_not_inherit_push_target(game):
    db, state, content = game
    stalled, _ = _658_plant_stalled_deliberation(db, state, content, title='旧强推')
    did = int(stalled['id'])
    dir_id = int(db.issues.add_directive(state.turn, state.year, state.period, None, '着即强推', 'test-658-edit', dossier_payload={'target_dossier_id': did}))
    db.update_directive_text(dir_id, '着清核河工', dossier_payload={'dossier_action_type': 'policy', 'target_kind': 'issue', 'target_id': 'river-works', 'mode': 'ordinary'})
    row = db.conn.execute('SELECT dossier_payload_json FROM turn_directives WHERE id=?', (dir_id,)).fetchone()
    payload = json.loads(str(row['dossier_payload_json'] or '{}'))
    assert 'target_dossier_id' not in payload
    assert payload.get('dossier_action_type') == 'policy'
    assert payload.get('target_id') == 'river-works'
    db.conn.execute('DELETE FROM pending_decisions WHERE turn=? AND event_id=?', (int(state.turn), 'plant:陕西告饥'))
    db.conn.commit()
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
    import ming_sim.cli_backend as cli_backend
    db, state, content = game
    stalled, _ = _658_plant_stalled_deliberation(db, state, content, title='混载')
    did = int(stalled['id'])
    before_dossiers = len(db.dossiers.list_dossiers())
    before_dirs = db.conn.execute('SELECT COUNT(*) AS c FROM turn_directives').fetchone()['c']

    def backend_mixed(prompt, *_a, **_k):
        return (json.dumps({'拟旨意图': '拟旨', '动作类型': 'policy', '目标类型': 'issue', '目标ID': 'river', '目标案卷ID': did}, ensure_ascii=False), 1)
    monkeypatch.setattr(cli_backend, '_run_backend_for_config', backend_mixed)
    with pytest.raises(ValueError):
        cli_backend.capture_manual_directive_payload('混载旨文', None, db=db, content=content)
    assert len(db.dossiers.list_dossiers()) == before_dossiers
    assert db.conn.execute('SELECT COUNT(*) AS c FROM turn_directives').fetchone()['c'] == before_dirs


@pytest.mark.parametrize("bad", ["missing", "nonpositive", "unknown_action", "wrong_dossier", "outsider", "duplicate", "keyless"])
def test_refuse_invalid_dossier_choices_without_writes(web_game, bad):
    db, state = web_game.db, web_game.state
    did = _plant_dossier_awaiting(db, state)
    desk = db.issues.list_rescript_desk(state.turn)
    choice = {"decision_key": desk[0]["decision_key"], "action": "decision", "label": "强颁", "dossier_id": did, "dossier_decision": "force_promulgated"}
    if bad == "missing":
        choice.pop("dossier_id")
    elif bad == "nonpositive":
        choice["dossier_id"] = -9
    elif bad == "unknown_action":
        choice["dossier_decision"] = "unsupported"
    elif bad == "wrong_dossier":
        choice["dossier_id"] = did + 1
    elif bad == "outsider":
        choice["decision_key"] = f"decision:{state.turn}:999999"
    elif bad == "keyless":
        opt = _layer_a_option(label="赈济", target_id="shaanxi", region_id="shaanxi", transaction_category="督赈")
        sql_rescript_draft(db, state.turn, idx=1, event_id="mixed-gate", title="混批", context="c", options=[opt])
        choice.pop("decision_key")
    before = db.dossiers.list_dossiers()
    turn = int(state.turn)
    response = asyncio.run(_post_resolve([choice, choice] if bad == "duplicate" else [choice]))
    assert response.status_code == 200
    from tests.test_web_audience_night_498 import _parse_sse
    assert _parse_sse(response.text)[-1]["event"] == "error"
    assert int(state.turn) == turn and state.turn_phase == TurnPhase.AWAITING_DECISION.value
    assert db.dossiers.list_dossiers() == before
    assert all(r["status"] == "pending" and not r.get("choice") for r in db.issues.list_rescript_desk(turn))


def test_lying_label_rebuilt_from_server_option(game):
    from ming_sim import rescript_actions as ra
    db, state, content = game
    did = _plant_dossier_awaiting(db, state)
    desk = db.issues.list_rescript_desk(state.turn)
    option = desk[0]["options"][0]
    note = "准。先济关宁边饷。"
    batch = ra.validate_all(desk, [{
        "decision_key": desk[0]["decision_key"], "label": "伪造选项",
        "hint": "伪造载荷", "note": note, "dossier_id": did,
        "dossier_decision": option["dossier_decision"],
    }])
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=content)
    stored = db.issues.list_pending_decisions(state.turn)[0]
    assert stored["status"] == "decided"
    choice = stored["choice"]
    assert choice["dossier_id"] == did
    assert choice["dossier_decision"] == option["dossier_decision"]
    assert choice["label"] == option["label"] and choice["hint"] == option["hint"]
    assert choice["note"] == note


def test_657_midzhi_verdict_no_party_satisfaction(game):
    from tests.dossier_test_helpers import _sat
    from ming_sim import rescript_actions as ra
    db, state, content = game
    urgent, _ = _plant_urgent_desk(db, state)
    batch = ra.validate_all([urgent], [{
        "decision_key": urgent["decision_key"], "action": "midzhi",
        "action_type": "assignment", "target_kind": "region", "target_id": "shaanxi",
        "locality_scope": "single", "region_id": "shaanxi", "transaction_category": "督赈",
        "deadline_months": 1, "participant_roster": _roster(_ROSTER_LEAD),
    }])
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=content)
    mid = next(d for d in db.dossiers.list_dossiers() if d["mode"] == "midzhi")
    before = (_sat(db, "factions", "东林"), _sat(db, "classes", "士绅"))
    db.apply_dossier_verdicts(state, [{
        "dossier_id": mid["id"], "decision": "promulgated", "affected_parties": [
            {"kind": "faction", "key": "东林", "direction": "negative", "intensity": "strong"},
            {"kind": "class", "key": "士绅", "direction": "negative", "intensity": "strong"},
        ],
    }], content=content)
    assert (_sat(db, "factions", "东林"), _sat(db, "classes", "士绅")) == before
    stored = db.conn.execute(
        "SELECT affected_parties_json FROM decree_dossier_decisions WHERE dossier_id=? ORDER BY id DESC LIMIT 1",
        (mid["id"],),
    ).fetchone()
    assert json.loads(stored["affected_parties_json"]) == []


@pytest.mark.parametrize("action", ["deliberate", "return_revise"])
@pytest.mark.parametrize("fault_type", [RuntimeError, KeyboardInterrupt])
def test_657_prewrite_failure_zero_db_writes(game, monkeypatch, action, fault_type):
    from tests.month_chain_helpers import make_light_session
    import ming_sim.agents as agents
    db, state, content = game
    urgent, _ = _plant_urgent_desk(db, state)
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    session = make_light_session(db, state, content)
    before = db.issues.list_rescript_drafts()
    fault = fault_type("injected model boundary failure")
    def fail(*_a, **_k):
        raise fault
    monkeypatch.setattr(agents, "create_rescript_deliberate_agent", lambda *_a, **_k: object())
    monkeypatch.setattr(agents, "create_rescript_revise_agent", lambda *_a, **_k: object())
    monkeypatch.setattr(agents, "run_agent_text", fail)
    with pytest.raises(fault_type) as exc:
        session.prepare_rescript_prewrite([{"decision_key": urgent["decision_key"], "action": action, "label": "输入", "note": "输入"}])
    assert (exc.value.__cause__ if fault_type is RuntimeError else exc.value) is fault
    assert db.issues.list_rescript_drafts() == before


@pytest.mark.parametrize("stored", ['{"decision_key":"other","action":"hold"}', "{}", "{broken"])
def test_657_c1_decided_mismatch_rejects_and_cas0(game, stored):
    from tests.month_chain_helpers import make_light_session
    from ming_sim.applier import StoredDocumentError
    db, state, content = game
    urgent, options = _plant_urgent_desk(db, state)
    db.conn.execute("UPDATE pending_decisions SET status='decided',choice_json=? WHERE kind='rescript_draft' AND turn=? AND idx=?", (stored, urgent["turn"], urgent["idx"]))
    db.conn.commit()
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    session = make_light_session(db, state, content)
    with pytest.raises((ValueError, StoredDocumentError)):
        session.prepare_rescript_prewrite([{"decision_key": urgent["decision_key"], "action": "follow_draft", "label": options[0]["label"], "draft_capability": options[0]["draft_capability"]}])
    assert db.conn.execute("SELECT choice_json FROM pending_decisions WHERE kind='rescript_draft' AND turn=? AND idx=?", (urgent["turn"], urgent["idx"])).fetchone()[0] == stored


@pytest.mark.parametrize("phase", [TurnPhase.SETTLING.value, TurnPhase.AWAITING_DECISION.value])
def test_1625_inflight_phase2_does_not_advertise_resume(web_game, phase):
    db, state = web_game.db, web_game.state
    db.resolve_contexts.save(state.turn, "诏", {"candidate_events": []})
    before = dict(state.metrics)
    db.capture_month_open_snapshot(state)
    state.metrics["国库"] += 17
    state.turn_phase = phase
    db.reign.save_game_state(state)
    web_app._begin_settlement_entry(web_game)
    try:
        payload = asyncio.run(_get_state())
        assert payload["turn"]["phase"] == phase
        assert payload["turn"]["settlement_display"] is True
        assert payload["metrics"]["国库"] == before["国库"]
        assert payload["settlement_entry_inflight"] is True
        assert payload["pending_decisions"] == []
        assert payload["resume_phase2"] is False
    finally:
        web_app._end_settlement_entry(web_game)
    payload = asyncio.run(_get_state())
    assert payload["settlement_entry_inflight"] is False
    assert payload["resume_phase2"] == (phase == TurnPhase.AWAITING_DECISION.value)


@pytest.mark.parametrize("dossier_prefix", [False, True])
def test_decision_requires_both_prefix_and_capability_to_enter_rescript_rail(game, dossier_prefix):
    from ming_sim import rescript_actions as ra
    db, state, content = game
    if dossier_prefix:
        _plant_due_commitment_shaped_awaiting(db, state)
    else:
        db.issues.save_pending_decisions(state.turn, [{"event_id": "mao_wenlong", "title": "边警", "options": [
            {"label": "准其销号", "hint": "事已办结"},
            {"label": "强颁", "dossier_id": 3, "dossier_decision": "hold"},
        ]}])
    desk = db.issues.list_rescript_desk(state.turn)
    option = desk[0]["options"][0]
    batch = ra.validate_all(desk, [{"decision_key": desk[0]["decision_key"], "label": option["label"], "note": "准销。"}])
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=content)
    row = db.issues.list_pending_decisions(state.turn)[0]
    assert row["status"] == "decided"
    assert row["choice"]["label"] == option["label"]
    assert not row["choice"].get("dossier_decision")


def test_applied_revise_refuses_default_hold_and_preserves_generation(game):
    from ming_sim import rescript_actions as ra
    from tests.month_chain_helpers import make_light_session
    db, state, content = game
    urgent, options = _plant_urgent_desk(db, state)
    key = urgent["decision_key"]
    batch = ra.validate_all([urgent], [{"decision_key": key, "action": "return_revise", "note": "再拟"}])
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(revise_by_key={key: options}), content=content)
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.reign.save_game_state(state)
    before = db.issues.list_rescript_drafts()
    session = make_light_session(db, state, content)
    with pytest.raises(ValueError):
        session.prepare_rescript_prewrite([{"decision_key": key, "action": ""}])
    assert db.issues.list_rescript_drafts() == before
    assert before[0]["revision_round"] == 1
    assert before[0]["choice"]["action"] == "return_revise"


@pytest.mark.parametrize("bad_option", [
    {'action_type': 'assignment', 'label': 'x', 'hint': 'h', 'target_kind': 'region', 'target_id': 'shaanxi', 'locality_scope': 'single', 'assignee_name': ''},
    {'action_type': 'assignment', 'label': 'x', 'hint': 'h', 'target_kind': 'region', 'target_id': 'shaanxi', 'locality_scope': 'single', 'region_id': 'shaanxi', 'transaction_category': '督赈', 'assignee_name': '', 'commitment_kind': 'until_stop', 'stop_condition': ''},
    {'action_type': 'grant_allocation', 'label': '加衔', 'hint': 'h', 'grant_action': '加衔', 'target_kind': 'character', 'target_id': '', 'name': '', 'locality_scope': 'none'},
    {'action_type': 'grant_allocation', 'label': '赏', 'hint': 'h', 'grant_action': '赏赉', 'target_kind': 'character', 'target_id': '毕自严', 'locality_scope': 'none'},
    {'action_type': 'grant_allocation', 'label': '赏', 'hint': 'h', 'grant_action': '赏赉', 'amount': 10, 'account': '私库', 'target_kind': 'character', 'target_id': '毕自严', 'name': '毕自严', 'locality_scope': 'none'},
    {'action_type': 'grant_allocation', 'label': '项目', 'hint': 'h', 'grant_action': '项目经费', 'amount': 500, 'target_kind': 'issue', 'target_id': '', 'locality_scope': 'none'},
    {'action_type': 'punishment', 'label': '罚', 'hint': 'h', 'punish_action': '罚俸', 'target_kind': 'character', 'target_id': '毕自严', 'locality_scope': 'none'},
    {'action_type': 'punishment', 'label': '罚', 'hint': 'h', 'punish_action': '不是刑罚', 'target_kind': 'character', 'target_id': '毕自严', 'name': '毕自严', 'locality_scope': 'none'},
    {'action_type': 'punishment', 'label': '罚', 'hint': 'h', 'punish_action': '罚俸', 'amount': 0, 'target_kind': 'character', 'target_id': '毕自严', 'name': '毕自严', 'locality_scope': 'none'},
    {'action_type': 'appointment', 'label': '授', 'hint': 'h', 'appoint_action': '任命', 'office': '', 'target_kind': 'character', 'target_id': '毕自严', 'locality_scope': 'none'},
    {'action_type': 'appointment', 'label': '授', 'hint': 'h', 'office': '兵部尚书', 'target_kind': 'character', 'target_id': '毕自严', 'name': '毕自严', 'locality_scope': 'none'},
    {'action_type': 'authorization', 'label': 'x', 'hint': 'h', 'target_kind': 'region', 'target_id': 'shaanxi', 'locality_scope': 'single'},
    {'action_type': 'military_order', 'label': 'x', 'hint': 'h', 'assignee_name': '毕自严', 'target_kind': 'region', 'target_id': 'guanning', 'locality_scope': 'none', 'station': '宁远'},
    {'action_type': 'military_order', 'label': 'x', 'hint': 'h', 'assignee_name': '毕自严', 'target_kind': 'army', 'target_id': 'no-such-army-657', 'locality_scope': 'none', 'deadline_months': 2},
    {'action_type': 'military_order', 'label': 'x', 'hint': 'h', 'assignee_name': '毕自严', 'target_kind': 'army', 'target_id': 'guanning', 'locality_scope': 'none'},
    {'action_type': 'grant_allocation', 'label': '协饷', 'hint': 'h', 'grant_action': '协饷', 'amount': 100, 'account': '国库', 'purpose': '补饷', 'target_kind': 'army', 'target_id': 'no-such-army-657', 'locality_scope': 'none'},
])
def test_invalid_rescript_action_shapes_refused_before_any_write(game, bad_option):
    from contextlib import nullcontext
    from tests.month_chain_helpers import make_light_session
    db, state, content = game
    urgent, _ = _plant_urgent_desk(db, state)
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.reign.save_game_state(state)
    session = make_light_session(db, state, content)
    before = db.conn.total_changes
    with pytest.raises(ValueError):
        session.submit_hitl_choices(
            [{"participant_roster": _roster(_ROSTER_LEAD), **bad_option,
              "decision_key": urgent["decision_key"], "action": "midzhi"}],
            write_gate=nullcontext(),
        )
    assert db.conn.total_changes == before
    assert all(row["status"] == "pending" and not row.get("choice") for row in db.issues.list_rescript_desk(state.turn))


def test_deliberation_rejects_unknown_supporter_without_writes(game):
    from ming_sim import rescript_actions as ra
    db, state, content = game
    urgent, _ = _plant_urgent_desk(db, state)
    key = urgent["decision_key"]
    batch = ra.validate_all([urgent], [{"decision_key": key, "action": "deliberate"}])
    before = db.dossiers.list_dossiers()
    with pytest.raises(ValueError):
        ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(deliberate_by_key={
            key: {"title": "议", "body": "议", "stance": "议", "supporter_ids": ["不存在的大臣XYZ"]}}), content=content)
    assert db.dossiers.list_dossiers() == before
    assert db.dossiers.find_by_decision_key(key) is None
    assert all(row["status"] == "pending" and not row.get("choice") for row in db.issues.list_rescript_desk(state.turn))


def test_imperial_deliberation_push_refuses_already_backed_target(game):
    from ming_sim import rescript_actions as ra
    db, state, content = game
    stalled, _ = _658_plant_stalled_deliberation(db, state, content)
    did = stalled["id"]
    ra.apply_imperial_deliberation_push(db, state, target_dossier_id=did, directive_identity="directive:1", commit=True)
    before = db.conn.total_changes
    with pytest.raises(ValueError):
        ra.apply_imperial_deliberation_push(db, state, target_dossier_id=did, directive_identity="directive:2", commit=True)
    assert db.conn.total_changes == before
    assert len(db.dossiers.endorsements(did)) == 1


def test_rescript_batch_replay_does_not_duplicate_domain_writes(game):
    from tests.month_chain_helpers import make_light_session
    db, state, content = game
    urgent, options = _plant_urgent_desk(db, state)
    choice = {"decision_key": urgent["decision_key"], "action": "follow_draft", "draft_capability": options[0]["draft_capability"], "label": options[0]["label"]}
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    session = make_light_session(db, state, content)
    prewrite = session.prepare_rescript_prewrite([choice])
    with session._write_gate:
        session.commit_rescript_phase1(prewrite)
    before = db.dossiers.list_dossiers()
    before_changes = db.conn.total_changes
    replay = session.prepare_rescript_prewrite([choice])
    with session._write_gate:
        result = session.commit_rescript_phase1(replay)
    assert result['apply'].skipped_keys == [urgent['decision_key']]
    assert db.dossiers.list_dossiers() == before
    assert db.conn.total_changes == before_changes
