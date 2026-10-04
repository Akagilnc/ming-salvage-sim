# private_helper_call_no_obs_token (102)

## [0] tests/test_audience_restore_505.py:721 `test_truncate_migrated_overlap_does_not_resurrect_via_agno_read`
flags=['private_helper_call_no_obs_token'] lines=42
```
def test_truncate_migrated_overlap_does_not_resurrect_via_agno_read(restore_env):
    """#1716 mixed-state B: official table+blob overlap must not resurrect tail."""
    env = restore_env
    db = env.db
    overlap = ["r0", "r1", "r2"]
    other = ["other-0"]
    # Official v3 migration shape: runs copied into table, legacy blob retained.
    db.conn.execute("DROP TABLE IF EXISTS agno_runs")
    db.conn.execute("DROP TABLE IF EXISTS agno_sessions")
    db.conn.execute(
        "CREATE TABLE agno_sessions ("
        "session_id TEXT PRIMARY KEY, session_type TEXT NOT NULL, "
        "agent_id TEXT, team_id TEXT, workflow_id TEXT, user_id TEXT, "
        "session_data TEXT, agent_data TEXT, team_data TEXT, workflow_data TEXT, "
        "metadata TEXT, summary TEXT, runs TEXT, "
        "created_at INTEGER NOT NULL, updated_at INTEGER)"
    )
    _ensure_agno_runs_table(db)
    for sid, ids in (("sess", overlap), ("other", other)):
        db.conn.execute(
            "INSERT INTO agno_sessions "
            "(session_id, session_type, runs, created_at, updated_at) "
            "VALUES (?, 'agent', ?, 1, 1)",
            (sid, json.dumps([{"run_id": rid} for rid in ids])),
        )
        for i, rid in enumerate(ids):
            db.conn.execute(
                "INSERT INTO agno_runs "
                "(run_id, session_id, run_type, status, run_index, run_data, created_at) "
                "VALUES (?, ?, 'agent', 'COMPLETED', ?, ?, ?)",
                (rid, sid, i, json.dumps({"run_id": rid}), i + 1),
            )
    db.conn.commit()

    assert db.agno_runs_length("sess") == 3
    db._truncate_agno_runs_in_tx("sess", 2)
    db.conn.commit()
    assert db.agno_runs_length("sess") == 2
    assert db.agno_runs_length("other") == 1

    assert _agno_public_run_ids(env.path, "sess") == ["r0", "r1"]
    assert _agno_public_run_ids(env.path, "other") == ["other-0"]
```

## [1] tests/test_breach_plea_623.py:708 `test_same_turn_dual_breach_kinds_merge_not_swallowed`
flags=['private_helper_call_no_obs_token'] lines=39
```
def test_same_turn_dual_breach_kinds_merge_not_swallowed(game):
    """同回合第二类松手不得静默吞：并入既有 pending + meta 记全被吞类。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="dual-kind")
    origin = f"dossier:{did}"
    db.record_issue_economy_move(
        state, "国库", -3, "月供", "历史供拨", origin_ref=origin, commit=True,
    )
    cid, _ = _insert_commitment(
        db, state, title="同回合双类之诺", origin_ref=origin,
        ongoing_effects={}, bar_value=20, end_turn=state.turn + 40,
        tags=["专款:国库"],
    )
    t1 = write_breach_plea_todo(
        db, state, commitment_ref=cid, breach_kind=BREACH_KIND_FUNDING,
        reason="断供", target_dossier_id=did, commit=True,
    )
    assert t1 > 0
    # 同回合第二类：改弦（不推进 turn）
    t2 = write_breach_plea_todo(
        db, state, commitment_ref=cid, breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="改弦", target_dossier_id=did, commit=True,
    )
    assert t2 == t1  # 并入同一条
    pleas = _pending_pleas(db)
    assert len(pleas) == 1
    from ming_sim.breach_plea import decode_plea_meta
    meta = decode_plea_meta(pleas[0]["origin_context"])
    assert meta.get("breach_kind") == BREACH_KIND_FUNDING
    absorbed = meta.get("absorbed_breach_kinds") or []
    assert BREACH_KIND_POLICY_REVERSAL in absorbed
    # try_defer 不得返空 todo_ids
    deferred = try_defer_revoke_to_breach_plea(
        db, state, target_dossier_id=did, reason="再撤", commit=True,
    )
    assert deferred and deferred.get("deferred")
    assert deferred.get("todo_ids"), "try_defer 不得返空 todo_ids 掩蔽"
```

## [2] tests/test_centrifuge_ledger_690.py:97 `test_t1_confiscation_direct_anchors_via_public_api`
flags=['private_helper_call_no_obs_token'] lines=25
```
def test_t1_confiscation_direct_anchors_via_public_api(game):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game
    cases = (
        (70, 7, 10),
        (10, 61, 87),
        (1, 69, 99),
    )
    for cw, expect_amount, expect_leg in cases:
        idem = f"t1|抄家|cw{cw}"
        accrue_blood_debt(
            db=db,
            turn=state.turn,
            target=_TARGET_EUNUCH,
            axis=_AXIS,
            penalty_type="抄家",
            crime_weight=cw,
            idem_base=idem,
        )
        rows = _direct_rows(db, idem_base=idem)
        assert len(rows) == 1
        assert int(rows[0]["amount"]) == expect_amount
        assert int(rows[0]["legitimacy_pct"]) == expect_leg
        assert int(rows[0]["base"]) == 70
```

## [3] tests/test_centrifuge_ledger_690.py:209 `test_t3_zero_delta_empty_namespace_is_legal_noop`
flags=['private_helper_call_no_obs_token'] lines=15
```
def test_t3_zero_delta_empty_namespace_is_legal_noop(game):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game
    before = _snapshot(db)
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="申饬",
        crime_weight=3,
        idem_base="t3|zero",
    )
    assert _snapshot(db) == before
```

## [4] tests/test_centrifuge_ledger_690.py:231 `test_t4_happy_path_and_forbidden_kwargs`
flags=['private_helper_call_no_obs_token'] lines=50
```
def test_t4_happy_path_and_forbidden_kwargs(game):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game
    before = _snapshot(db)
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="抄家",
        crime_weight=70,
        idem_base="t4|happy",
        reason_code="依律",
        source="test",
    )
    faction = _faction_of(db, _TARGET_EUNUCH)
    rows = [r for r in _log_rows(db) if str(r["idem_key"]).startswith("t4|happy|")]
    kinds = {r["kind"] for r in rows}
    assert "direct" in kinds
    assert "kinship" in kinds
    for r in rows:
        assert r["source_name"] == _TARGET_EUNUCH
        assert r["faction"] == faction
    cache = [
        r
        for r in _cache_rows(db)
        if r["faction"] == faction and r["axis"] == _AXIS
    ]
    assert cache and int(cache[0]["blood_debt"]) > 0

    for kwargs in (
        {"faction": faction},
        {"identity": 50},
        {"amount": 1},
    ):
        snap = _snapshot(db)
        with pytest.raises(TypeError):
            accrue_blood_debt(
                db=db,
                turn=state.turn,
                target=_TARGET_EUNUCH,
                axis=_AXIS,
                penalty_type="抄家",
                crime_weight=70,
                idem_base="t4|forbidden",
                **kwargs,
            )
        assert _snapshot(db) == snap
    assert before != _snapshot(db)
```

## [5] tests/test_centrifuge_ledger_690.py:288 `test_t5_bastinado_overdraw_batch_and_non_bastinado`
flags=['private_helper_call_no_obs_token'] lines=35
```
def test_t5_bastinado_overdraw_batch_and_non_bastinado(game):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game
    faction = _faction_of(db, _TARGET_EUNUCH)
    before_od = _overdraw_map(db)[faction]

    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="廷杖",
        crime_weight=1,
        idem_base="t5|廷杖",
    )
    rows = [r for r in _log_rows(db) if str(r["idem_key"]).startswith("t5|廷杖|")]
    kinds = {r["kind"] for r in rows}
    assert "overdraw" in kinds
    od = next(r for r in rows if r["kind"] == "overdraw")
    assert od["axis"] is None and od["base"] is None and od["legitimacy_pct"] is None
    assert int(od["amount"]) == 1
    assert _overdraw_map(db)[faction] == before_od + 1

    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="罢黜",
        crime_weight=1,
        idem_base="t5|罢黜",
    )
    non = [r for r in _log_rows(db) if str(r["idem_key"]).startswith("t5|罢黜|")]
    assert all(r["kind"] != "overdraw" for r in non)
```

## [6] tests/test_centrifuge_ledger_690.py:334 `test_t6_bad_target_aborts_with_zero_write`
flags=['private_helper_call_no_obs_token'] lines=16
```
def test_t6_bad_target_aborts_with_zero_write(game, bad_target):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game
    before = _snapshot(db)
    with pytest.raises(SettlementAbort):
        accrue_blood_debt(
            db=db,
            turn=state.turn,
            target=bad_target,
            axis=_AXIS,
            penalty_type="抄家",
            crime_weight=70,
            idem_base=f"t6|{bad_target!r}",
        )
    assert _snapshot(db) == before
```

## [7] tests/test_centrifuge_ledger_690.py:401 `test_t7_cross_faction_isolation`
flags=['private_helper_call_no_obs_token'] lines=29
```
def test_t7_cross_faction_isolation(game):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game
    army = _faction_of(db, _TARGET_ARMY)
    eunuch = _faction_of(db, _TARGET_EUNUCH)
    assert army != eunuch
    before_army_cache = [
        dict(r) for r in _cache_rows(db) if r["faction"] == army
    ]
    before_army_log = [
        dict(r) for r in _log_rows(db) if r["faction"] == army
    ]
    before_army_od = _overdraw_map(db)[army]

    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="抄家",
        crime_weight=70,
        idem_base="t7|eunuch",
    )
    assert [dict(r) for r in _cache_rows(db) if r["faction"] == army] == before_army_cache
    assert [dict(r) for r in _log_rows(db) if r["faction"] == army] == before_army_log
    assert _overdraw_map(db)[army] == before_army_od
    written = [r for r in _log_rows(db) if str(r["idem_key"]).startswith("t7|eunuch|")]
    assert written and all(r["faction"] == eunuch for r in written)
```

## [8] tests/test_centrifuge_ledger_690.py:437 `test_t8_detection_wariness_only_kinship`
flags=['private_helper_call_no_obs_token'] lines=42
```
def test_t8_detection_wariness_only_kinship(game):
    from ming_sim.centrifuge_ledger import accrue_detection_wariness

    db, state, _content = game
    before = _snapshot(db)
    accrue_detection_wariness(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        alert_severity=10,
        idem_base="t8|det",
        source="alert",
    )
    rows = [r for r in _log_rows(db) if str(r["idem_key"]).startswith("t8|det|")]
    assert len(rows) == 1
    assert rows[0]["kind"] == "kinship"
    assert int(rows[0]["legitimacy_pct"]) == 100
    assert rows[0]["kind"] != "direct"
    assert all(r["kind"] != "overdraw" for r in rows)
    assert all(r["kind"] != "direct" for r in rows)

    for kwargs in (
        {"penalty_type": "抄家"},
        {"crime_weight": 1},
        {"amount": 1},
        {"faction": "阉党"},
        {"identity": 1},
    ):
        snap = _snapshot(db)
        with pytest.raises(TypeError):
            accrue_detection_wariness(
                db=db,
                turn=state.turn,
                target=_TARGET_EUNUCH,
                axis=_AXIS,
                alert_severity=10,
                idem_base="t8|bad",
                **kwargs,
            )
        assert _snapshot(db) == snap
    assert _snapshot(db) != before
```

## [9] tests/test_centrifuge_ledger_690.py:486 `test_t9_idempotency_namespace_and_empty_planned`
flags=['private_helper_call_no_obs_token'] lines=114
```
def test_t9_idempotency_namespace_and_empty_planned(game):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game

    # ① replay：同参两次，第二次零增
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="抄家",
        crime_weight=70,
        idem_base="t9|replay",
        reason_code="依律",
        source="s",
    )
    mid = _snapshot(db)
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="抄家",
        crime_weight=70,
        idem_base="t9|replay",
        reason_code="依律",
        source="s",
    )
    assert _snapshot(db) == mid

    # ② 同 idem_base 异载荷（换 target）且 kinds 仍能凑集合相等 → Abort
    # 先用另一 base 写军队目标，确保军队可被写；此处专门：已有 t9|payload 写阉党后换军队
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="申饬",
        crime_weight=1,
        idem_base="t9|payload",
    )
    before_payload = _snapshot(db)
    with pytest.raises(SettlementAbort):
        accrue_blood_debt(
            db=db,
            turn=state.turn,
            target=_TARGET_ARMY,
            axis=_AXIS,
            penalty_type="申饬",
            crime_weight=1,
            idem_base="t9|payload",
        )
    assert _snapshot(db) == before_payload

    # ③ 旧批多 kind / 当前真子集：identity→0 去掉 kinship
    _set_identity(db, _TARGET_ARMY, 80)
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_ARMY,
        axis=_AXIS,
        penalty_type="申饬",
        crime_weight=1,
        idem_base="t9|subset",
    )
    kinds_first = {
        r["kind"]
        for r in _log_rows(db)
        if str(r["idem_key"]).startswith("t9|subset|")
    }
    assert kinds_first == {"direct", "kinship"}
    _set_identity(db, _TARGET_ARMY, 0)
    before_subset = _snapshot(db)
    with pytest.raises(SettlementAbort):
        accrue_blood_debt(
            db=db,
            turn=state.turn,
            target=_TARGET_ARMY,
            axis=_AXIS,
... (34 more lines)
```

## [10] tests/test_centrifuge_ledger_690.py:607 `test_t10_partial_preinserted_key_aborts`
flags=['private_helper_call_no_obs_token'] lines=38
```
def test_t10_partial_preinserted_key_aborts(game):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game
    faction = _faction_of(db, _TARGET_EUNUCH)
    # 只预插 direct，公开调用会计划 multi-kind → 集合不等
    db.conn.execute(
        "INSERT INTO centrifuge_log("
        "turn, faction, axis, kind, base, legitimacy_pct, amount, "
        "source_name, reason_code, source, idem_key"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            state.turn,
            faction,
            _AXIS,
            "direct",
            70,
            10,
            7,
            _TARGET_EUNUCH,
            None,
            None,
            "t10|partial|direct",
        ),
    )
    db.conn.commit()
    before = _snapshot(db)
    with pytest.raises(SettlementAbort):
        accrue_blood_debt(
            db=db,
            turn=state.turn,
            target=_TARGET_EUNUCH,
            axis=_AXIS,
            penalty_type="抄家",
            crime_weight=70,
            idem_base="t10|partial",
        )
    assert _snapshot(db) == before
```

## [11] tests/test_centrifuge_ledger_690.py:829 `test_t14_reason_code_sets_and_reject_unrecognized`
flags=['private_helper_call_no_obs_token'] lines=25
```
def test_t14_reason_code_sets_and_reject_unrecognized(game):
    from ming_sim.centrifuge_ledger import STIGMA_REASON_CODES, accrue_blood_debt

    db, state, _content = game
    for code in ("依律", "谋逆坐实", "贪墨坐实"):
        assert code in PERSON_REASON_CODES
        assert normalize_reason_code(code) == code

    for code in ("中旨除授", "非正途", "罗织"):
        assert code in STIGMA_REASON_CODES
        assert code not in PERSON_REASON_CODES

    before = _snapshot(db)
    with pytest.raises(SettlementAbort):
        accrue_blood_debt(
            db=db,
            turn=state.turn,
            target=_TARGET_EUNUCH,
            axis=_AXIS,
            penalty_type="抄家",
            crime_weight=70,
            idem_base="t14|bad_reason",
            reason_code="完全不是码",
        )
    assert _snapshot(db) == before
```

## [12] tests/test_chat_stream_failpaths_393.py:167 `test_prologue_finally_does_not_release_foreign_gate_holder`
flags=['private_helper_call_no_obs_token'] lines=51
```
def test_prologue_finally_does_not_release_foreign_gate_holder():
    """#542 r6g: cleanup 的 with write_gate 退出后、finally 前另一写者经
    `_serialized_web_write` 取得写路径；本线程不得误放致外来写者互斥被破坏，
    且外来写者须能自行完成写并退出临界区。"""
    db = _FailingPrologueDB()
    runtime, minister = _base_runtime(db)
    other_entered = threading.Event()
    allow_other_exit = threading.Event()
    other_completed_ok: list[bool] = []
    other_thread_holder: list[threading.Thread] = []

    def other_writer() -> None:
        try:
            with web_app._serialized_web_write(runtime):
                other_entered.set()
                allow_other_exit.wait()
            other_completed_ok.append(True)
        except Exception:
            other_completed_ok.append(False)

    original_complete = runtime._complete_pending_write

    def complete_then_hand_path_to_other(ticket=None) -> None:
        # Runs after cleanup `with write_gate` exited and released, before finally.
        original_complete(ticket)
        other = threading.Thread(target=other_writer, name="foreign-serialized-holder")
        other_thread_holder.append(other)
        other.start()
        other_entered.wait()

    runtime._complete_pending_write = complete_then_hand_path_to_other

    gen = runtime.chat_stream("殿上", "辽东军情如何？")
    with pytest.raises(RuntimeError):
        next(gen)

    assert db.failed_turns == [7]
    # Foreign holder must still own the serialized write path after prologue finally.
    assert other_entered.is_set()
    assert other_completed_ok == [], (
        "foreign holder's critical section was broken by prologue finally"
    )
    allow_other_exit.set()
    assert other_thread_holder, "foreign writer thread was not started"
    other_thread_holder[0].join()
    assert not other_thread_holder[0].is_alive()
    assert other_completed_ok == [True], (
        "foreign holder could not complete its own serialized write"
    )
    # After foreign holder exits, write path must be free for subsequent writers/drain.
    _assert_write_path_free(runtime)
```

## [13] tests/test_chat_stream_failpaths_393.py:866 `test_chat_stream_config_max_attempts_override`
flags=['private_helper_call_no_obs_token'] lines=34
```
def test_chat_stream_config_max_attempts_override(monkeypatch, tmp_path, game):
    """#1465 ①：runtime transport 改次数 → 真实召对入口行为随之变。"""
    from ming_sim import llm_config as llm_config_mod

    path = tmp_path / "runtime_llm.json"
    path.write_text(json.dumps({
        "channel": "api",
        "api": {"base_url": "https://x/v1", "model": "m", "api_key": "sk-x"},
        "cli": {"timeout_seconds": 30},
        "transport": {
            "max_attempts": 1,
            "attempt_timeout_seconds": 30,
        },
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(llm_config_mod, "RUNTIME_LLM_PATH", str(path))

    def _conn_err(_n):
        return LLMUnavailable(
            "连接失败",
            code="llm_connection_error",
            provider_message="connection reset",
        )

    agent = _CountingFailAgent(fail_times=99, error_factory=_conn_err)
    web_game, minister = _transport_web_game(game, agent, monkeypatch)
    web_game.session.llm_config = SimpleNamespace(channel="api")

    response = _post_chat_stream(monkeypatch, web_game, minister)
    events = _parse_sse(response.text)
    assert events[-1][0] == "error"
    detail = events[-1][1]
    assert agent.calls == 1
    assert detail.get("code") == "llm_connection_error"
    assert len(detail.get("transport_attempts") or []) == 1
```

## [14] tests/test_covert_levy_651.py:523 `test_false_denunciation_is_not_retroactively_made_true_by_current_fork`
flags=['private_helper_call_no_obs_token'] lines=22
```
def test_false_denunciation_is_not_retroactively_made_true_by_current_fork(game, monkeypatch):
    from ming_sim.supervision import compose_denunciation_origin

    db, state, _ = game
    did, _, _, _ = _bound_case(db, state)
    monkeypatch.setattr(db, "read_dossier_fork_state", lambda dossier_id: {
        "dossier_id": dossier_id, "fork": True, "reported_bands": ["有成"],
        "execution_outcome": "transformed", "actual_effect_count": 1, "beyond_intent": True,
    })
    values = (state.turn, "甲", "阉党", "乙", "东林", did, compose_denunciation_origin(is_true=False), "{}", "诬告")
    db.conn.execute(
        "INSERT INTO faction_denunciations(turn,accuser_name,accuser_faction,subject_name,"
        "subject_faction,target_dossier_id,origin,payload_json,memorial_text) VALUES (?,?,?,?,?,?,?,?,?)",
        values,
    )
    assert write_exposure_todos(db, state) == 0
    db.conn.execute(
        "INSERT INTO faction_denunciations(turn,accuser_name,accuser_faction,subject_name,"
        "subject_faction,target_dossier_id,origin,payload_json,memorial_text) VALUES (?,?,?,?,?,?,?,?,?)",
        (*values[:6], compose_denunciation_origin(is_true=True), "{}", "真举"),
    )
    assert write_exposure_todos(db, state) == 1
```

## [15] tests/test_decree_dossiers_571.py:1537 `test_probe_directive_shared_entry_creates_and_settles_structured_dossier`
flags=['private_helper_call_no_obs_token'] lines=34
```
def test_probe_directive_shared_entry_creates_and_settles_structured_dossier(game, monkeypatch):
    from ming_sim.decree_forecast import decree_ref_for_dossier
    from tests.test_month_chain_1843 import _prepare_player_month
    from ming_sim.session import GameSession
    from scripts.probe_directive_contract import add_narrative_probe_directive

    db, state, content = game
    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state

    directive = add_narrative_probe_directive(
        session,
        "着有司整饬河工",
        probe_id="contract-smoke",
        notes="probe smoke",
    )
    db.ensure_dossiers_for_draft_directives(state)
    dossier = db.get_dossier_for_directive(directive.id)
    assert dossier["action_type"] == "policy"
    assert dossier["target_kind"] == "issue"
    assert dossier["target_id"] == "probe:contract-smoke:1"

    db.staged_declarations.stage(
        decree_ref=decree_ref_for_dossier(db, dossier), declaration={},
        turn=int(state.turn), verdict={"decision": "promulgated"}, forecast_text="",
    )
    player = _prepare_player_month(db, state, content, monkeypatch)
    player.resolve_turn(allow_empty_decree=True)
    db.save_turn_report(state, "邸报", public_body="邸报")
    player.resolve_turn(allow_empty_decree=True)

    assert state.turn == 2
    assert db.get_decree_dossier(dossier["id"])["status"] == "executing"
```

## [17] tests/test_enter_settlement_period_1235.py:333 `test_settling_keeps_display_for_recovery`
flags=['private_helper_call_no_obs_token'] lines=15
```
def test_settling_keeps_display_for_recovery(game):
    """AC3：settling 相位下快照保留（恢复入口可达的状态口条件）。"""
    db, state, content = game
    before = _click_before(state)
    db.capture_month_open_snapshot(state)
    import ming_sim.decree as dm
    dm.pre_settle(state, db, content=content)
    assert state.turn_phase == TurnPhase.SETTLING.value
    # 真失败退出不得误清 settling 快照
    from ming_sim.month_open_snapshot import exit_settlement_display_on_failure
    assert exit_settlement_display_on_failure(db, state) is False
    assert db.get_month_open_snapshot(int(state.turn)) == before
    payload = _runtime_payload(db, state)
    assert payload["turn"]["settlement_display"] is True
    assert payload["turn"]["phase"] == "settling"
```

## [18] tests/test_enter_settlement_period_1235.py:392 `test_accept_creator_atomic_only_one_true`
flags=['private_helper_call_no_obs_token'] lines=21
```
def test_accept_creator_atomic_only_one_true(game, monkeypatch):
    """#1235 r6：双 accept 仅一 True——原子 INSERT 裁定创建者，禁后置见行假 True。

    monkeypatch get 恒 None 模拟双侧预检同空（交错窗）；连调两次须 (True, False)。
    旧后置见行路径会 (True, True) 或 IntegrityError；本测有牙。
    """
    from ming_sim.month_open_snapshot import accept_settlement_period

    db, state, _ = game
    turn = int(state.turn)
    real_get = db.get_month_open_snapshot
    monkeypatch.setattr(db, "get_month_open_snapshot", lambda _t: None)

    first = accept_settlement_period(db, state)
    second = accept_settlement_period(db, state)
    assert (first, second) == (True, False)

    # 行确实只建一次（绕过恒 None 补丁读真库）
    assert real_get(turn) is not None
    third = accept_settlement_period(db, state)
    assert third is False
```

## [19] tests/test_enter_settlement_period_1235.py:502 `test_exit_settlement_display_acquires_write_gate`
flags=['private_helper_call_no_obs_token'] lines=47
```
def test_exit_settlement_display_acquires_write_gate(web_game):
    """#1235 r2 p2 / r3：blocking=True（创建者）清快照须经 _write_gate 阻塞 acquire。"""
    import threading

    game = web_game
    turn = int(game.state.turn)
    assert web_app._accept_settlement_period(game) is True
    gate = web_app._game_write_gate(game)
    assert gate.acquire(blocking=False)
    held = {"cleared_under_gate": False}
    done = threading.Event()
    err: list = []

    orig_clear = game.db.clear_month_open_snapshot

    def _wrapped_clear(t):
        held["cleared_under_gate"] = gate.locked()
        return orig_clear(t)

    game.db.clear_month_open_snapshot = _wrapped_clear  # type: ignore[method-assign]

    def _peer_exit():
        try:
            # 创建者路径：blocking 等待 gate 后必清
            web_app._exit_settlement_display_on_failure(game, blocking=True)
        except Exception as exc:  # noqa: BLE001
            err.append(exc)
        finally:
            done.set()

    try:
        t = threading.Thread(target=_peer_exit, daemon=True)
        t.start()
        # 他持 write_gate 时 blocking exit 须堵在 acquire，不得无门完成清快照
        assert not done.is_set(), "exit 不得在 write_gate 仍被他持时无门完成"
        assert game.db.get_month_open_snapshot(turn) is not None
        gate.release()
        done.wait()
        t.join()
    finally:
        game.db.clear_month_open_snapshot = orig_clear  # type: ignore[method-assign]
        if gate.locked():
            gate.release()

    assert not err, err
    assert held["cleared_under_gate"] is True
    assert game.db.get_month_open_snapshot(turn) is None
```

## [20] tests/test_env_isolation.py:14 `test_user_data_dir_is_isolated_from_repo_data`
flags=['private_helper_call_no_obs_token'] lines=6
```
def test_user_data_dir_is_isolated_from_repo_data():
    from ming_sim.paths import user_data_dir

    assert os.environ.get("MING_SIM_USER_DATA_DIR"), "autouse 兜底未生效"
    repo_data = Path(__file__).resolve().parent.parent / "data"
    assert Path(str(user_data_dir())).resolve() != repo_data.resolve()
```

## [21] tests/test_error_pack.py:20 `test_attempt_derived_from_existing_dirs`
flags=['private_helper_call_no_obs_token'] lines=15
```
def test_attempt_derived_from_existing_dirs(game, monkeypatch, tmp_path):
    """同 turn 写两次包 → attempt=1,2（从错误目录文件数推导，不从 DB）。"""
    from ming_sim.error_pack import write_error_pack
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    exc = RuntimeError("boom")

    p1 = write_error_pack(db, state, exc=exc, extracted=None, resolve_ctx=None)
    p2 = write_error_pack(db, state, exc=exc, extracted=None, resolve_ctx=None)

    m1 = json.loads((Path(p1) / "manifest.json").read_text(encoding="utf-8"))
    m2 = json.loads((Path(p2) / "manifest.json").read_text(encoding="utf-8"))
    assert m1["attempt"] == 1
    assert m2["attempt"] == 2
    assert Path(p1) != Path(p2)
```

## [22] tests/test_error_pack.py:36 `test_write_error_pack_inside_atomic_is_rejected`
flags=['private_helper_call_no_obs_token'] lines=11
```
def test_write_error_pack_inside_atomic_is_rejected(game, monkeypatch, tmp_path):
    """在 atomic 内写包 → backup_to 守卫响亮拒绝（钉住「包必须在 atomic 外」约束）。"""
    from ming_sim.applier import atomic
    from ming_sim.error_pack import write_error_pack
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))

    with pytest.raises(RuntimeError, match="atomic"):
        with atomic(db):
            write_error_pack(db, state, exc=RuntimeError("x"),
                             extracted=None, resolve_ctx=None)
```

## [23] tests/test_error_pack.py:57 `test_rejections_jsonl_path_in_error_dir`
flags=['private_helper_call_no_obs_token'] lines=8
```
def test_rejections_jsonl_path_in_error_dir(monkeypatch, tmp_path):
    """拒收 jsonl 与错误包集中同一 user-data 错误目录（决定 7：一次打包全带走）。"""
    from ming_sim.error_pack import error_packs_root, rejections_jsonl_path
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))

    jsonl = Path(rejections_jsonl_path())
    assert jsonl.parent == error_packs_root()
    assert jsonl.name == "rejections.jsonl"
```

## [24] tests/test_error_pack.py:70 `test_attempt_never_overwrites_existing_pack`
flags=['private_helper_call_no_obs_token'] lines=18
```
def test_attempt_never_overwrites_existing_pack(game, tmp_path, monkeypatch):
    """非连续 attempt 目录下写包绝不覆盖既有包（cmr S6 r1 F2，claude+codex）。

    len+1 + exist_ok=True 会算出 attempt=2 并静默覆盖既有 turn{N}_attempt2。
    """
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    from ming_sim.error_pack import error_packs_root, write_error_pack
    db, state, content = game
    turn = state.turn

    stale = error_packs_root() / f"turn{turn}_attempt2"
    stale.mkdir(parents=True)
    (stale / "manifest.json").write_text('{"sentinel": "keep me"}', encoding="utf-8")

    pack = write_error_pack(db, state, exc=RuntimeError("x"))

    assert pack.endswith("attempt3")  # max+1，不是 len+1=2
    assert (stale / "manifest.json").read_text(encoding="utf-8") == '{"sentinel": "keep me"}'
```

## [25] tests/test_error_pack.py:89 `test_mirror_writes_to_rejections_jsonl_path`
flags=['private_helper_call_no_obs_token'] lines=18
```
def test_mirror_writes_to_rejections_jsonl_path(game, tmp_path, monkeypatch):
    """rejections_jsonl_path 开箱可写：父目录就位，mirror 直接 append（cmr S6 r1 F3）。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    from ming_sim.applier import Provenance, RejectedItem, RejectionCollector
    from ming_sim.error_pack import rejections_jsonl_path
    db, state, content = game
    db.conn.execute("DROP TABLE IF EXISTS rejection_reports")
    rc = RejectionCollector()
    rc.record("army_delta", RejectedItem(
        item={}, reason="r", category="invalid_enum", source=Provenance.unknown), turn=1)
    rc.flush_to_db(db)
    db.conn.commit()

    path = rejections_jsonl_path()
    rc.mirror_to_jsonl(path)

    lines = open(path, encoding="utf-8").readlines()
    assert len(lines) == 1
```

## [26] tests/test_error_pack.py:144 `test_next_attempt_skips_malformed_and_foreign_entries`
flags=['private_helper_call_no_obs_token'] lines=19
```
def test_next_attempt_skips_malformed_and_foreign_entries(game, monkeypatch, tmp_path):
    """attempt 推导跳过畸形后缀/他 turn/非目录项，取本 turn 数字后缀 max+1
    （PR #90 R3 sourcery：钉 _next_attempt 防御分支）。"""
    from ming_sim.error_pack import error_packs_root, write_error_pack
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    root = error_packs_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / f"turn{turn}_attempt7").mkdir()        # 有效：进 max
    (root / f"turn{turn}_attemptX").mkdir()        # 畸形后缀：忽略
    (root / f"turn{turn + 1}_attempt99").mkdir()   # 他 turn：不串号
    (root / f"turn{turn}_attempt9").write_text("")  # 同名文件非目录：忽略

    p = write_error_pack(db, state, exc=RuntimeError("boom"),
                         extracted=None, resolve_ctx=None)

    m = json.loads((Path(p) / "manifest.json").read_text(encoding="utf-8"))
    assert m["attempt"] == 8  # 7+1，不被 X/99/文件项带偏
```

## [27] tests/test_event_trigger_gate.py:868 `test_event_content_rejects_falsy_person_core_subjects`
flags=['private_helper_call_no_obs_token'] lines=25
```
def test_event_content_rejects_falsy_person_core_subjects(monkeypatch):
    """内容契约：person_core_subjects 写了就必须是字符串数组，空字符串不能吞成缺省。"""
    from ming_sim import content as content_module

    monkeypatch.setattr(
        content_module,
        "load_json_asset",
        lambda filename: [
            {"open_window": True,
                "id": "bad_person_core_subjects",
                "title": "坏人物核心事件",
                "kind": "situation",
                "summary": "x",
                "urgency": 50,
                "severity": 50,
                "credibility": 50,
                "interests": [],
                "audiences": [],
                "person_core_subjects": "",
            }
        ],
    )

    with pytest.raises(SystemExit):
        content_module.load_event_content("events.json")
```

## [28] tests/test_execution_pressure_654.py:290 `test_cli_capture_rejects_bad_target_or_scope`
flags=['private_helper_call_no_obs_token'] lines=17
```
def test_cli_capture_rejects_bad_target_or_scope(env, monkeypatch, target_kind, scope, accepted):
    from ming_sim import cli_backend as cb
    db, state, content = env
    data = {
        "拟旨意图": "拟旨", "动作类型": "assignment", "目标类型": target_kind,
        "目标ID": "shaanxi", "地区ID": "shaanxi", "施行范围": scope,
        "事务类别": "督赈", "承办人": "", "颁布方式": "普通",
        "参与人": [{"character_id": "毕自严", "tier": "主办", "role": "", "delegator_id": None}],
    }
    monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: (json.dumps(data), None))
    if accepted:
        captured = cb.capture_manual_directive_payload("陕西赈务", db=db, content=content)
        assert captured["target_kind"] == "region"
        assert captured["locality_scope"] == "single"
    else:
        with pytest.raises(ValueError):
            cb.capture_manual_directive_payload("陕西赈务", db=db, content=content)
```

## [29] tests/test_faction_denunciation_627.py:100 `test_world_materials_exclude_secret_fork_from_gazette`
flags=['private_helper_call_no_obs_token'] lines=21
```
def test_world_materials_exclude_secret_fork_from_gazette(game, tmp_path):
    import json
    from ming_sim.materials import prepare_world_materials, read_material

    db, state, content = game
    owner = next(iter(_chars_by_faction(db).values()))[0]["name"]
    public_id = _subject_dossier(db, state, owner=owner, token="public")
    from tests.dossier_test_helpers import create_test_secret_order
    order_id = create_test_secret_order(db, state, owner, "密查", "查账", [])
    secret_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    db.conn.execute("UPDATE decree_dossiers SET status='executing' WHERE id=?", (secret_id,))
    db.conn.commit()
    _make_forked(db, state, public_id)
    _make_forked(db, state, secret_id)

    prepared = prepare_world_materials(
        db, state, dest_root=tmp_path / "gazette",
        exclude_secret_order_dossiers=True,
    )
    facts = json.loads(read_material(prepared.root, "盘面/派系检举事实.txt"))
    assert {item["dossier_id"] for item in facts["forked_dossiers"]} == {public_id}
```

## [32] tests/test_fiscal_substrate_bridge.py:874 `test_settling_context_retry_does_not_recompute_substrate_hub_pre_settle`
flags=['private_helper_call_no_obs_token'] lines=24
```
def test_settling_context_retry_does_not_recompute_substrate_hub_pre_settle(fresh_game):
    from ming_sim.decree import pre_settle

    db, state = fresh_game
    turn = state.turn

    pre_settle(state, db)
    before_ledger = _hub_ledger_snapshot(db, turn=turn)
    before_containers = _hub_container_snapshot(db)
    before_balance = state.metrics["国库"]

    db.save_resolve_context(
        turn,
        "测试诏",
        {},
    )
    assert db.get_resolve_context(turn) is not None

    pre_settle(state, db)

    assert _hub_ledger_snapshot(db, turn=turn) == before_ledger
    assert _hub_container_snapshot(db) == before_containers
    assert state.metrics["国库"] == before_balance
    _assert_hub_conservation_oracle(before_ledger, before_containers)
```

## [33] tests/test_llm_channel_config.py:176 `test_create_chat_model_strips_provider_prefix_for_reasoning_family`
flags=['private_helper_call_no_obs_token'] lines=29
```
def test_create_chat_model_strips_provider_prefix_for_reasoning_family(monkeypatch):
    """#1461：openai/gpt-5.x 带 provider 前缀仍须识别为推理族（剥前缀后判）。"""
    from ming_sim.llm_config import supports_openai_reasoning_effort

    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    assert supports_openai_reasoning_effort("openai/gpt-5.4")
    assert supports_openai_reasoning_effort("openai/o3-mini")
    assert supports_openai_reasoning_effort("openai/o4-mini")
    assert not supports_openai_reasoning_effort("openai/gpt-4o")

    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="openai/o3-mini",
        channel="api",
        reasoning_strength="off",
    )
    model = create_chat_model(cfg)
    assert model.reasoning_effort == "minimal"

    cfg5 = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="openai/gpt-5.4",
        channel="api",
        reasoning_strength="off",
    )
    model5 = create_chat_model(cfg5)
    assert model5.reasoning_effort == "none"
```

## [34] tests/test_llm_channel_config.py:281 `test_scene_and_rescript_entries_pass_default_headers_at_transport`
flags=['private_helper_call_no_obs_token'] lines=42
```
def test_scene_and_rescript_entries_pass_default_headers_at_transport(monkeypatch, game, tmp_path):
    """#1794：召对/拟诏真实入口 → OpenAIChat 构造缝头表整张到达；不跑真实 LLM。"""
    from ming_sim.agents import bind_content as agents_bind, create_rescript_draft_agent
    from ming_sim.materials import PreparedMaterials
    from ming_sim.registry import create_scene_agent

    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    db, state, content = game
    agents_bind(content)

    headers = {
        "X-Custom-Session": "sess-fixed-1",
        "User-Agent": "ming-qa/1.0",
    }
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-test",
        channel="api",
        default_headers=headers,
    )

    captured: list = []
    real = llm_model.OpenAIChat

    def spy(*args, **kwargs):
        captured.append(dict(kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(llm_model, "OpenAIChat", spy)

    create_scene_agent(
        cfg, PreparedMaterials(root=tmp_path, opening="", index_lines=()),
        content=content,
    )
    assert captured, "召对入口须构造 OpenAIChat"
    assert captured[-1].get("default_headers") == headers

    before = len(captured)
    create_rescript_draft_agent(cfg, db)
    assert len(captured) == before + 1, "拟诏入口须再构造一次 OpenAIChat"
    assert captured[-1].get("default_headers") == headers
```

## [35] tests/test_llm_channel_config.py:697 `test_load_llm_config_cli_env_uses_cli_default_timeout_not_api`
flags=['private_helper_call_no_obs_token'] lines=9
```
def test_load_llm_config_cli_env_uses_cli_default_timeout_not_api(monkeypatch):
    """codex R1 #2：legacy env CLI（MING_SIM_LLM_BACKEND 设）时 cli_timeout_seconds 必须用
    CLI 槽默认（静默判死 60），不沿用 API 的 timeout_seconds（180）。"""
    from ming_sim.llm_config import load_llm_config, CLI_DEFAULT_TIMEOUT_SECONDS
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    cfg = load_llm_config(base_url="", model="m", api_key="", timeout_seconds=180.0)
    assert cfg.channel == "cli"
    assert cfg.cli_timeout_seconds == CLI_DEFAULT_TIMEOUT_SECONDS == 60.0
    assert cfg.cli_timeout_seconds != 180.0
```

## [36] tests/test_llm_channel_config.py:838 `test_gate_evidence_config_omits_max_tokens`
flags=['private_helper_call_no_obs_token'] lines=9
```
def test_gate_evidence_config_omits_max_tokens():
    """#1472：四闸证据块不再写 max_tokens。"""
    from types import SimpleNamespace
    from ming_sim import cli_backend as cb

    args = SimpleNamespace(channel="cli", runner="kimi", model="kimi-k2")
    cfg = cb.gate_llm_config_from_args(args)
    block = cb.gate_evidence_config(args, cfg)
    assert "max_tokens" not in block
```

## [37] tests/test_mechanical_tail_1845.py:59 `test_advance_schedules_mechanical_tail_after_front_month_advance`
flags=['private_helper_call_no_obs_token'] lines=27
```
def test_advance_schedules_mechanical_tail_after_front_month_advance(game, monkeypatch):
    """提交到受管后台票；前台推进后尾状态先 pending，延期执行后变 done。"""
    db, state, content = game
    closed_turn = int(state.turn)
    _forbid_extractor(monkeypatch)
    _archive_and_stub_world(db, state, monkeypatch)

    def silent_brew(_session, **_kwargs):
        return {"selected": 0, "brewed": [], "degraded": [], "skipped_events": 0}

    # 外部边界：挡真实酿制 LLM；不断言私有 brew 调用形状。
    monkeypatch.setattr("ming_sim.mechanical_tail._run_relation_brew", silent_brew)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    session.agno_db = object()

    executor = _install_deferred(monkeypatch)
    try:
        result = session.resolve_turn(allow_empty_decree=True)
        assert result.advanced is True
        assert int(state.turn) == closed_turn + 1
        assert month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"] == "pending"
    finally:
        if hasattr(executor, "fn"):
            _run_deferred(executor)
    assert get_session_write_queue(session).wait_idle(timeout_s=1)
    assert month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"] == "done"
```

## [38] tests/test_mechanical_tail_1845.py:88 `test_reopen_resumes_incomplete_mechanical_tail`
flags=['private_helper_call_no_obs_token'] lines=45
```
def test_reopen_resumes_incomplete_mechanical_tail(game, monkeypatch):
    """崩溃后只留 DB 未完标记时，同过月入口续接，不因重开跳过或重复执行。"""
    db, state, content = game
    closed_turn = int(state.turn)
    closed_year, closed_period = int(state.year), int(state.period)
    _forbid_extractor(monkeypatch)
    _archive_and_stub_world(db, state, monkeypatch)

    from ming_sim.mechanical_tail import ensure_mechanical_tails

    session = make_light_session(db, state, content)
    session.llm_config = object()
    session.agno_db = object()

    def silent_brew(_session, **_kwargs):
        return {"selected": 0, "brewed": [], "degraded": [], "skipped_events": 0}

    monkeypatch.setattr(
        "ming_sim.mechanical_tail._run_relation_brew", silent_brew,
    )
    executor = _install_deferred(monkeypatch)
    try:
        assert session.resolve_turn(allow_empty_decree=True).advanced is True
    finally:
        if hasattr(executor, "fn"):
            _run_deferred(executor)
    get_session_write_queue(session).wait_idle(timeout_s=5)
    assert month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"] == "done"

    # 模拟进程退出后只剩 DB pending、写队列票已失
    chain = month_chain._load_chain(db, closed_turn)
    chain["mechanical_tail"] = {
        "status": "pending",
        "settled_year": closed_year,
        "settled_period": closed_period,
        "ending_outcome": None,
    }
    month_chain._save_chain(db, closed_turn, chain, source=Provenance.system_simulation)
    try:
        ensure_mechanical_tails(session)
    finally:
        if not executor.future.done():
            _run_deferred(executor)
    get_session_write_queue(session).wait_idle(timeout_s=5)
    assert month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"] == "done"
```

## [39] tests/test_mechanical_tail_1845.py:135 `test_exhausted_mechanical_tail_fails_and_blocks_next_month`
flags=['private_helper_call_no_obs_token'] lines=34
```
def test_exhausted_mechanical_tail_fails_and_blocks_next_month(game, monkeypatch):
    """模型耗尽须留下失败凭据并阻断下次过月。"""
    from ming_sim.exceptions import LLMUnavailable

    db, state, content = game
    closed_turn = int(state.turn)
    _forbid_extractor(monkeypatch)
    _archive_and_stub_world(db, state, monkeypatch)

    def boom(*_a, **_k):
        raise LLMUnavailable("酿制耗尽", stage="relation-brew")

    monkeypatch.setattr(
        "ming_sim.mechanical_tail._run_relation_brew", boom,
    )
    session = make_light_session(db, state, content)
    session.llm_config = object()
    session.agno_db = object()
    executor = _install_deferred(monkeypatch)

    try:
        assert session.resolve_turn(allow_empty_decree=True).advanced is True
    finally:
        if hasattr(executor, "fn"):
            with pytest.raises(LLMUnavailable):
                _run_deferred(executor)
    assert get_session_write_queue(session).wait_idle(timeout_s=5)
    status = month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"]
    assert status == "failed"

    db.save_turn_report(state, "下月邸报")
    from ming_sim.exceptions import SettlementAbort
    with pytest.raises(SettlementAbort):
        session.resolve_turn(allow_empty_decree=True)
```

## [40] tests/test_mechanical_tail_1845.py:171 `test_real_brew_failure_reaches_tail_failure_and_retry`
flags=['private_helper_call_no_obs_token'] lines=43
```
def test_real_brew_failure_reaches_tail_failure_and_retry(game, monkeypatch):
    """过月真实酿制腿不能把模型耗尽藏在单条 degraded 报告中。"""
    from ming_sim.exceptions import LLMUnavailable
    from tests.test_relation_brew_636 import _add_edge
    from web_app import WebGame
    from types import SimpleNamespace

    db, state, content = game
    closed_turn = int(state.turn)
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="当殿讦奏", origin="audience:turn-1")
    _forbid_extractor(monkeypatch)
    _archive_and_stub_world(db, state, monkeypatch)
    monkeypatch.setattr("ming_sim.agents.create_relation_brew_agent", lambda *a: object())
    monkeypatch.setattr("ming_sim.agents.create_faction_brew_agent", lambda *a: object())
    def exhausted(*_a, **_k):
        raise LLMUnavailable("酿制耗尽", stage="relation-brew")
    monkeypatch.setattr("ming_sim.agents.run_agent_text", exhausted)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    session.agno_db = object()
    executor = _install_deferred(monkeypatch)
    try:
        assert session.resolve_turn(allow_empty_decree=True).advanced is True
    finally:
        if hasattr(executor, "fn"):
            with pytest.raises(LLMUnavailable):
                _run_deferred(executor)
    failure = WebGame.mechanical_tail_failure(SimpleNamespace(db=db, state=state))
    assert failure["error"] == "酿制耗尽"
    assert failure["error_pack_path"]
    assert month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"] == "failed"
    from ming_sim.mechanical_tail import retry_failed_mechanical_tail
    from tests.test_relation_brew_636 import _brew_fn_factory
    monkeypatch.setattr("ming_sim.agents.run_agent_text", lambda _agent, prompt, **_kw: _brew_fn_factory([])(prompt))
    retry_executor = _install_deferred(monkeypatch)
    try:
        assert retry_failed_mechanical_tail(session)
    finally:
        if hasattr(retry_executor, "fn"):
            _run_deferred(retry_executor)
    assert month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"] == "done"
    assert WebGame.mechanical_tail_failure(SimpleNamespace(db=db, state=state)) is None
```

## [41] tests/test_mechanical_tail_1845.py:268 `test_non_exhausted_tail_failure_stays_pending_and_retries`
flags=['private_helper_call_no_obs_token'] lines=64
```
def test_non_exhausted_tail_failure_stays_pending_and_retries(game, monkeypatch):
    """后台程序异常须传播至 Future 观察面并保留 pending，后续入口能重提。"""
    import ming_sim.audience_translation as audience_translation

    db, state, content = game
    closed_turn = int(state.turn)
    _forbid_extractor(monkeypatch)
    _archive_and_stub_world(db, state, monkeypatch)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    session.agno_db = object()

    class InlineExecutor:
        def submit(self, fn):
            future = Future()
            try:
                future.set_result(fn())
            except Exception as exc:
                future.set_exception(exc)
            return future

    monkeypatch.setattr(audience_translation, "_executor", InlineExecutor())

    def fail(*_a, **_kwargs):
        raise ValueError("internal failure")

    monkeypatch.setattr("ming_sim.mechanical_tail._run_relation_brew", fail)
    assert session.resolve_turn(allow_empty_decree=True).advanced is True
    assert month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"] == "failed"
    from ming_sim.mechanical_tail import ensure_mechanical_tails, retry_failed_mechanical_tail, failed_mechanical_tail
    ensure_mechanical_tails(session)
    assert failed_mechanical_tail(db, state)[0] == closed_turn
    from web_app import WebGame
    from types import SimpleNamespace
    state.ended = True
    payload = WebGame.ending_payload(SimpleNamespace(db=db, state=state))
    assert WebGame.mechanical_tail_failure(SimpleNamespace(db=db, state=state))["error"] == "internal failure"
    assert payload["summary_pending"] is False
    state.ended = False

    # 即使终局没有下一次过月，失败也由持久状态即时呈现。
    db.save_turn_report(state, "下月邸报")
    from ming_sim.exceptions import SettlementAbort
    from pathlib import Path
    with pytest.raises(SettlementAbort) as caught:
        session.resolve_turn(allow_empty_decree=True)
    assert caught.value.stage == "mechanical_tail_pending"
    assert caught.value.error_pack_path
    pack = Path(caught.value.error_pack_path)
    assert pack.is_dir()
    import json
    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["exception_type"] == "ValueError"
    assert manifest["turn"] == closed_turn + 1
    assert int(state.turn) == closed_turn + 1
    tail = month_chain._load_chain(db, closed_turn)["mechanical_tail"]
    assert tail["status"] == "failed"
    assert tail["error_pack_path"] == caught.value.error_pack_path

    monkeypatch.setattr("ming_sim.mechanical_tail._run_relation_brew", lambda *_a, **_k: None)
    assert retry_failed_mechanical_tail(session)
    assert session.resolve_turn(allow_empty_decree=True).advanced is True
    assert int(state.turn) == closed_turn + 2
    assert month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"] == "done"
```

## [42] tests/test_mechanical_tail_1845.py:492 `test_mechanical_tail_missing_llm_config_surfaces_retry`
flags=['private_helper_call_no_obs_token'] lines=56
```
def test_mechanical_tail_missing_llm_config_surfaces_retry(game, monkeypatch):
    """缺模型配置：机械尾失败，错误原文写明缺少模型配置，可点重试。"""
    from ming_sim.mechanical_tail import (
        failed_mechanical_tail,
        retry_failed_mechanical_tail,
        schedule_mechanical_tail_after_advance,
    )

    db, state, content = game
    closed_turn = int(state.turn)
    session = make_light_session(db, state, content)
    session.llm_config = None
    session.agno_db = None
    executor = _install_deferred(monkeypatch)

    schedule_mechanical_tail_after_advance(
        session,
        closed_turn=closed_turn,
        settled_year=int(state.year),
        settled_period=int(state.period),
        ending_outcome={"status": "emperor_abdicate", "summary": "退位"},
    )
    try:
        _run_deferred(executor)
    except Exception:
        pass
    assert get_session_write_queue(session).wait_idle(timeout_s=5)
    failure = failed_mechanical_tail(db, state)
    assert failure is not None
    turn, tail = failure
    assert turn == closed_turn
    assert tail["status"] == "failed"
    err = str(tail.get("error") or "")
    assert "缺少模型配置" in err
    assert tail.get("error_pack_path")

    monkeypatch.setattr(
        "ming_sim.mechanical_tail._run_relation_brew", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "ming_sim.agents.create_ending_summary_agent", lambda *a, **k: object(),
    )
    monkeypatch.setattr(
        "ming_sim.agents.run_agent_text", lambda *a, **k: "补配后总评",
    )
    session.llm_config = object()
    session.agno_db = object()
    executor2 = _install_deferred(monkeypatch)
    assert retry_failed_mechanical_tail(session) is True
    _run_deferred(executor2)
    assert get_session_write_queue(session).wait_idle(timeout_s=5)
    chain = month_chain._load_chain(db, closed_turn)
    assert chain["mechanical_tail"]["status"] == "done"
    ending = db.get_ending_summary()
    assert ending is not None
    assert ending["summary"] == "补配后总评"
```

## [43] tests/test_menu_lifecycle_drain_396.py:31 `test_drain_and_close_session_waits_for_gate_then_closes`
flags=['private_helper_call_no_obs_token'] lines=27
```
def test_drain_and_close_session_waits_for_gate_then_closes():
    queue = SessionWriteQueue()
    gate = queue.write_gate
    closed: list[int] = []
    game = SimpleNamespace(
        _write_queue=queue,
        _write_gate=gate,
        session=SimpleNamespace(close=lambda: closed.append(1)),
    )

    assert gate.acquire(blocking=False)
    done = threading.Event()

    thread = threading.Thread(
        target=lambda: (web_app._drain_and_close_session(game), done.set()),
        daemon=True,
    )
    thread.start()
    # While the live queue gate is held, drain must not close the session.
    assert not done.is_set()
    assert closed == []

    gate.release()

    done.wait()
    assert closed == [1]
    assert not gate.locked()
```

## [44] tests/test_menu_lifecycle_drain_396.py:60 `test_exit_to_menu_returns_before_delayed_close_drains`
flags=['private_helper_call_no_obs_token'] lines=27
```
def test_exit_to_menu_returns_before_delayed_close_drains(monkeypatch, tmp_path):
    queue = SessionWriteQueue()
    gate = queue.write_gate
    closed: list[int] = []
    db_path = str(tmp_path / "exit-delay.db")
    fake_game = SimpleNamespace(
        _write_queue=queue,
        _write_gate=gate,
        db_path=db_path,
        session=SimpleNamespace(close=lambda: closed.append(1)),
    )
    _reset_path_leases()
    assert web_app._register_holder(db_path, fake_game) is not None
    monkeypatch.setattr(web_app, "web_game", fake_game)

    gate.acquire()

    result = asyncio.run(web_app.api_menu_exit())

    assert result == {"ok": True}
    assert web_app.web_game is None
    assert closed == []

    gate.release()

    wait_until(lambda: closed == [1])
    assert not gate.locked()
```

## [45] tests/test_menu_lifecycle_drain_396.py:129 `test_get_main_db_path_prefers_active_db_over_launch_env`
flags=['private_helper_call_no_obs_token'] lines=10
```
def test_get_main_db_path_prefers_active_db_over_launch_env(monkeypatch, tmp_path):
    """#402 R1（Codex）：重启后 active_db.txt 必须压过启动 env，才能继续 new_game 切出的新主库。"""
    env_db_path = str(tmp_path / "launch_env.db")
    active_db_path = str(tmp_path / "active_from_new_game.db")
    monkeypatch.setenv("MING_SIM_DB", env_db_path)
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    with open(web_app._active_db_path_file(), "w", encoding="utf-8") as f:
        f.write(active_db_path)

    assert web_app._get_main_db_path() == active_db_path
```

## [46] tests/test_menu_lifecycle_drain_396.py:293 `test_drain_archive_skips_move_when_session_close_fails`
flags=['private_helper_call_no_obs_token'] lines=30
```
def test_drain_archive_skips_move_when_session_close_fails(monkeypatch, tmp_path):
    """#402 R2（CodeRabbit）+#1740：旧连接没关成功时上抛原异常，且不移动仍可能被占用的 DB 文件。"""
    db_path = str(tmp_path / "ming_sim.db")
    with open(db_path, "w", encoding="utf-8") as f:
        f.write("db")

    moves: list[tuple[str, str]] = []
    queue = SessionWriteQueue()
    game = SimpleNamespace(
        _write_queue=queue,
        _write_gate=queue.write_gate,
        db_path=db_path,
        session=SimpleNamespace(close=lambda: (_ for _ in ()).throw(RuntimeError("close failed"))),
    )
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    monkeypatch.setattr(web_app.shutil, "move", lambda src, dst: moves.append((src, dst)))

    _reset_path_leases()
    entry = web_app._register_holder(db_path, game)
    assert entry is not None
    role, op = web_app._claim_close(entry, db_path)
    assert role == "executor" and op is not None
    with pytest.raises(RuntimeError, match="close failed"):
        web_app._drain_and_close_session(game, entry=entry, close_op=op)
    # close 失败不发 AR；即使误发 C7 也被 holder 挡住
    web_app._path_request_archive(db_path)

    assert moves == []
    assert os.path.exists(db_path)
    assert not (tmp_path / "saves").exists()
```

## [47] tests/test_menu_lifecycle_drain_396.py:325 `test_restore_main_db_path_config_remove_failure_is_loud`
flags=['private_helper_call_no_obs_token'] lines=18
```
def test_restore_main_db_path_config_remove_failure_is_loud(monkeypatch, tmp_path):
    """#1749 / ADR 0005：active_db.txt 删除失败须上抛，禁静默改写成 env/default 另一身份。"""
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    active_file = web_app._active_db_path_file()
    with open(active_file, "w", encoding="utf-8") as f:
        f.write(str(tmp_path / "new.db"))
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "new.db"))
    monkeypatch.setattr(
        web_app.os, "remove",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("locked")),
    )

    with pytest.raises(PermissionError, match="locked"):
        web_app._restore_main_db_path_config((False, "", False, ""))

    # 失败后不得把身份改写成默认 ming_sim.db
    with open(active_file, "r", encoding="utf-8") as f:
        assert f.read().strip() == str(tmp_path / "new.db")
```

## [48] tests/test_menu_lifecycle_drain_396.py:561 `test_drain_waits_for_queued_chat_stream_not_just_gate_holder`
flags=['private_helper_call_no_obs_token'] lines=73
```
def test_drain_waits_for_queued_chat_stream_not_just_gate_holder():
    """#396 Gap B: drain 不能只等当前持锁 worker——已排队（阻塞在 gate.acquire()）的旧召对请求
    也须先跑完写库，drain 才关 session。否则 drain 抢到下一轮 acquire 直接关连接，排队请求要么
    永不跑、要么写 closed database。"""
    allow_finish_a = threading.Event()
    allow_finish_b = threading.Event()
    closed: list[int] = []

    char_a = minister_double("大臣甲")
    char_b = minister_double("大臣乙")
    state = SimpleNamespace(turn=1, year=1628, period=1, turn_phase="summoning")
    db = _GapBDB()

    runtime = object.__new__(web_app.WebGame)
    runtime.session = _GapBSession(
        {char_a.name: char_a, char_b.name: char_b},
        {char_a.name: _GapBAgent(allow_finish_a), char_b.name: _GapBAgent(allow_finish_b)},
        state, db)
    runtime.session.close = lambda: closed.append(1)
    runtime.chat_history = {char_a.name: [], char_b.name: [], "殿上": []}
    runtime._write_queue = SessionWriteQueue()
    runtime._write_gate = runtime._write_queue.write_gate
    runtime._runtime_write_queue = lambda: runtime._write_queue  # type: ignore
    runtime._mark_pending_write = lambda key=None: runtime._write_queue.claim(key=key or ("pending",))  # type: ignore
    runtime._complete_pending_write = lambda ticket=None: runtime._write_queue.complete(ticket)  # type: ignore
    runtime.directive_rows = lambda: []
    runtime.directive_payload = lambda row: row
    runtime.can_undo_last_chat = lambda _name: False

    # #1849 reopen：召对只剩殿上；同入口并发第二流被拒，drain 仍须等在飞 A 写完。
    stream_a = runtime.chat_stream("殿上", "请奏A")
    first_a = next(stream_a)
    assert first_a.get("type") == "delta"
    assert "content" in first_a

    b_events = list(runtime.chat_stream("殿上", "请奏B"))
    assert b_events and b_events[-1].get("type") == "error"

    drain_done = threading.Event()

    def run_drain():
        web_app._drain_and_close_session(runtime)
        drain_done.set()

    wait_prior_entered = threading.Event()
    real_wait_prior = runtime._write_queue.wait_prior

    def observe_wait_prior(ticket):
        wait_prior_entered.set()
        return real_wait_prior(ticket)

    runtime._write_queue.wait_prior = observe_wait_prior  # type: ignore[method-assign]

    thread_drain = threading.Thread(target=run_drain, daemon=True)
    thread_drain.start()
    wait_prior_entered.wait()
    assert not drain_done.is_set(), "drain 在 A 在飞写完前就关了连接"

    allow_finish_a.set()
    # 消费 A 剩余事件至 end，放行 ticket
    for item in stream_a:
        if item.get("type") in ("done", "error", "end"):
            if item.get("type") == "end":
                break

    drain_done.wait()
    assert closed == [1]
    assert not runtime._write_gate.locked()

    assert any(
        m["minister"] == "殿上" and m["role"] == "minister"
        for m in db.messages
    )
```

## [49] tests/test_menu_lifecycle_drain_396.py:636 `test_drain_rejects_late_pending_write_before_gate_acquire`
flags=['private_helper_call_no_obs_token'] lines=28
```
def test_drain_rejects_late_pending_write_before_gate_acquire():
    """#402 R3（Sourcery）：drain 开始后，迟到的旧 game 写入不得再登记进关闭队列。"""
    runtime = object.__new__(web_app.WebGame)
    runtime._write_queue = SessionWriteQueue()
    runtime._write_gate = runtime._write_queue.write_gate
    runtime._runtime_write_queue = lambda: runtime._write_queue  # type: ignore
    runtime._mark_pending_write = lambda key=None: runtime._write_queue.claim(key=key or ("pending",))  # type: ignore
    runtime._complete_pending_write = lambda ticket=None: runtime._write_queue.complete(ticket)  # type: ignore
    closed: list[int] = []
    runtime.session = SimpleNamespace(close=lambda: closed.append(1))

    runtime._write_gate.acquire()
    done = threading.Event()
    thread = threading.Thread(
        target=lambda: (web_app._drain_and_close_session(runtime), done.set()),
        daemon=True,
    )
    thread.start()

    wait_until(lambda: runtime._write_queue.is_sealed())
    assert runtime._mark_pending_write() is None
    # 屏障票据在等 gate 期间可占 1；新 claim 已拒。
    assert runtime._pending_writes_count <= 1

    runtime._write_gate.release()

    done.wait()
    assert closed == [1]
```

## [50] tests/test_month_call_recovery_1846.py:82 `test_month_entry_world_push_follows_audience_transport_policy`
flags=['private_helper_call_no_obs_token'] lines=62
```
def test_month_entry_world_push_follows_audience_transport_policy(
    game, monkeypatch, tmp_path, failure,
):
    """过月入口的世界推演走 ADR 0157 策略：429 一次终止；5xx/超时隔五秒，共三次。"""
    from ming_sim.agents import Agent, bind_content
    from ming_sim.models import LLMConfig

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bind_content(content)
    turn = int(state.turn)
    _forbid_extractor(monkeypatch)
    sleeps: list[float] = []
    monkeypatch.setattr(
        "ming_sim.llm_transport._sleep_retry_interval",
        lambda seconds: sleeps.append(float(seconds)),
    )
    sequence = (
        [_http_status_error(429)]
        if failure == "429"
        else [
            _http_status_error(500),
            APITimeoutError(request=None),
            _http_status_error(503),
        ]
    )
    calls = {"n": 0}

    def boom(self, *_args, **_kwargs):
        assert getattr(self, "id", None) == "world-segment"
        calls["n"] += 1
        raise sequence[calls["n"] - 1]

    monkeypatch.setattr(Agent, "run", boom)
    session = make_light_session(db, state, content)
    session.llm_config = LLMConfig(
        api_key="sk-test", base_url="https://api.example.com/v1",
        model="gpt-test", channel="api",
    )

    with pytest.raises(SettlementAbort) as caught:
        session.resolve_turn(allow_empty_decree=True)

    if failure == "429":
        assert calls["n"] == 1
        assert sleeps == []
    else:
        assert calls["n"] == TRANSPORT_DEFAULT_MAX_ATTEMPTS
        assert sleeps == [TRANSPORT_DEFAULT_RETRY_INTERVAL_SECONDS] * (
            TRANSPORT_DEFAULT_MAX_ATTEMPTS - 1
        )
    assert int(state.turn) == turn
    assert state.turn_phase == TurnPhase.SETTLING.value
    assert caught.value.stage == "world_text"
    chain = (db.get_resolve_context(turn) or {}).get("simulator_payload", {}).get(
        "month_chain", {},
    )
    failure_row = chain.get("call_failure") or {}
    assert failure_row.get("kind") == "model_exhausted"
    assert failure_row.get("step") == "world_text"
    assert not chain.get("world_text_ready")
    assert not chain.get("world_committed")
```

## [51] tests/test_month_call_recovery_1846.py:146 `test_forecast_exhaustion_does_not_overwrite_prior_ending`
flags=['private_helper_call_no_obs_token'] lines=64
```
def test_forecast_exhaustion_does_not_overwrite_prior_ending(game, monkeypatch, tmp_path):
    """补跑用尽只写失败标记，不得覆盖先前已提交的结局事实。"""
    import ming_sim.decree_forecast as decree_forecast

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    minister = next(iter(content.characters.values())).name
    from ming_sim.declaration_dispatch import pending_action_decree_ref

    first_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={"dossier_action_type": "policy", "target_kind": "issue",
                 "target_id": "ending", "actor": minister, "mode": "ordinary",
                 "text": "退位"},
    )
    first_ref = pending_action_decree_ref(first_id, 1)
    db.staged_declarations.stage(
        decree_ref=first_ref,
        declaration={"effects": {"emperor_fate": "abdicate"}},
        turn=int(state.turn), verdict={"decision": "promulgated"},
    )
    second_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={"dossier_action_type": "policy", "target_kind": "issue",
                 "target_id": "needs-forecast", "actor": minister, "mode": "ordinary",
                 "text": "补跑失败"},
    )
    turn = int(state.turn)
    _forbid_extractor(monkeypatch)
    failed = {"once": True}

    def produce(*_a, **_k):
        if failed["once"]:
            failed["once"] = False
            raise LLMUnavailable("catch-up exhausted")
        return {
            "verdict": {"decision": "promulgated"},
            "declaration": {"effects": {}},
            "questions": None,
            "forecast_text": "补跑完成",
        }

    monkeypatch.setattr(decree_forecast, "produce_forecast_product", produce)
    monkeypatch.setattr("ming_sim.month_chain.run_world_segment_text", lambda *_a, **_k: "")
    session = make_light_session(db, state, content)
    session.llm_config = SimpleNamespace(model="m", advanced_model="m")

    with pytest.raises(SettlementAbort):
        session.resolve_turn(allow_empty_decree=True)

    chain = (db.get_resolve_context(turn) or {}).get("simulator_payload", {}).get(
        "month_chain", {},
    )
    assert db.staged_declarations.is_settled(first_ref)
    assert (chain.get("declaration_outcome") or {}).get("status") == "emperor_abdicate"
    assert (chain.get("call_failure") or {}).get("kind") == "model_exhausted"
    assert db.get_decree_dossier(second_id) is not None

    db.save_turn_report(state, "邸报已成")
    result = session.resolve_turn(allow_empty_decree=True)
    assert result.advanced is True
    assert state.ended is True
    assert state.ending_status == "emperor_abdicate"
    assert db.staged_declarations.is_settled(first_ref)
```

## [52] tests/test_month_chain_1843.py:347 `test_world_segment_persists_declaration_ending_with_commit`
flags=['private_helper_call_no_obs_token'] lines=19
```
def test_world_segment_persists_declaration_ending_with_commit(game, monkeypatch):
    db, state, content = game
    from ming_sim.applier import Provenance

    monkeypatch.setattr(
        month_translate, "translate_month_segment",
        lambda *_a, **_k: {"effects": {"emperor_fate": "suicide"}},
    )
    chain = {"world_text_ready": True, "world_text": "世界段"}
    session = make_light_session(db, state, content)

    outcome = month_chain._run_world_segment(
        session, chain, source=Provenance.system_simulation,
    )

    assert outcome["status"] == "emperor_suicide"
    assert chain["declaration_outcome"] == outcome
    payload = db.get_resolve_context(int(state.turn))["simulator_payload"]
    assert payload["month_chain"]["declaration_outcome"] == outcome
```

## [53] tests/test_month_chain_1843.py:425 `test_staged_ending_is_available_inside_its_settlement_transaction`
flags=['private_helper_call_no_obs_token'] lines=23
```
def test_staged_ending_is_available_inside_its_settlement_transaction(game):
    db, state, _content = game
    from ming_sim.applier import Provenance
    from ming_sim.declaration_dispatch import (
        settle_staged_declarations_in_decree_order, stage_declaration,
    )

    stage_declaration(
        db, decree_ref="ending-decree", turn=int(state.turn),
        declaration={"effects": {"emperor_fate": "abdicate"}},
    )
    committed = {}
    settled = settle_staged_declarations_in_decree_order(
        db, state, ["ending-decree"], source=Provenance.player_decree,
        alongside=lambda ref, result: committed.update(
            ref=ref, outcome=month_chain._ending_from_dispatch_result(result),
        ),
    )

    assert "ending-decree" in settled
    assert committed["ref"] == "ending-decree"
    assert committed["outcome"]["status"] == "emperor_abdicate"
    assert db.staged_declarations.is_settled("ending-decree")
```

## [54] tests/test_month_chain_1843.py:581 `test_advance_uses_staged_declaration_ending`
flags=['private_helper_call_no_obs_token'] lines=18
```
def test_advance_uses_staged_declaration_ending(game, monkeypatch):
    db, state, content = game
    turn = int(state.turn)
    db.save_turn_report(state, "邸报已成")
    chain = {}
    outcome = {"status": "emperor_abdicate", "summary": "退位"}

    from ming_sim.applier import Provenance

    advanced = month_chain._advance_after_gazette(
        db, state, chain, turn, "", Provenance.system_simulation,
        declaration_outcome=outcome, content=content,
    )

    assert advanced is True
    assert state.ended is True
    assert state.ending_status == "emperor_abdicate"
    assert int(state.turn) == turn + 1
```

## [55] tests/test_month_chain_1843.py:601 `test_advance_reloads_memory_after_transaction_rollback`
flags=['private_helper_call_no_obs_token'] lines=19
```
def test_advance_reloads_memory_after_transaction_rollback(game, monkeypatch):
    db, state, content = game
    turn = int(state.turn)
    db.save_turn_report(state, "邸报已成")

    def fail_after_advance(*_args, **_kwargs):
        raise RuntimeError("injected tail failure")

    monkeypatch.setattr(
        decree_mod, "_carry_pending_clarification_actions", fail_after_advance,
    )
    with pytest.raises(RuntimeError, match="injected tail failure"):
        month_chain._advance_after_gazette(
            db, state, {}, turn, "", month_chain.Provenance.system_simulation,
            content=content,
        )

    assert int(state.turn) == turn
    assert db.load_state().turn == turn
```

## [56] tests/test_month_chain_1847.py:220 `test_answering_world_question_resumes_suffix_then_gazette`
flags=['private_helper_call_no_obs_token'] lines=58
```
def test_answering_world_question_resumes_suffix_then_gazette(game, monkeypatch):
    """真实 continue_world_after_answers：只打 LLM 外缝，续推闸与清问须落库可见。"""
    db, state, content = game
    closed_turn = int(state.turn)
    continuation_calls = []
    dispatched_segments = []

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(
        month_chain, "run_world_segment_text", lambda *a, **k: _WORLD_WITH_QUESTION,
    )
    monkeypatch.setattr(
        month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}},
    )

    def fake_continuation(session, chain, answers):
        continuation_calls.append(list(answers))
        return "准调关宁，关宁增戍。"

    real_dispatch = month_translate.dispatch_month_segment

    def spy_dispatch(db_, state_, *, segment, llm_config, source, alongside=None):
        dispatched_segments.append(str(segment))
        return real_dispatch(
            db_, state_, segment=segment, llm_config=llm_config,
            source=source, alongside=alongside,
        )

    monkeypatch.setattr(month_chain, "_run_world_continuation_text", fake_continuation)
    monkeypatch.setattr(month_translate, "dispatch_month_segment", spy_dispatch)

    session = make_light_session(db, state, content)
    session.llm_config = object()
    session.resolve_turn(allow_empty_decree=True)
    desk_row = session.pending_decisions()[0]
    choice = desk_row["options"][0]

    session.submit_hitl_choices(
        [{
            "decision_key": desk_row["decision_key"],
            "label": choice["label"],
            "hint": choice.get("hint") or "",
        }],
        write_gate=session._write_gate,
    )

    assert continuation_calls and continuation_calls[0][0]["label"] == choice["label"]
    assert any("关宁增戍" in seg for seg in dispatched_segments)
    assert session.state.turn_phase == TurnPhase.SETTLING.value
    chain = month_chain._load_chain(db, closed_turn)
    assert chain.get("world_questions") in (None, [], ())
    assert chain.get("world_continued") is True

    again = session.resolve_turn(allow_empty_decree=True)
    assert again.stage == "gazette"
    assert again.awaiting is False
    # 同回合重入不得再烧续推。
    assert len(continuation_calls) == 1
```

## [57] tests/test_month_chain_1847.py:541 `test_missing_model_does_not_mark_world_continued`
flags=['private_helper_call_no_obs_token'] lines=37
```
def test_missing_model_does_not_mark_world_continued(game, monkeypatch):
    """世界段缺模型不得记 world_continued；重试才从问处续推。"""
    db, state, content = game
    closed_turn = int(state.turn)
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(
        month_chain, "run_world_segment_text", lambda *a, **k: _WORLD_WITH_QUESTION,
    )
    monkeypatch.setattr(
        month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}},
    )
    session = make_light_session(db, state, content)
    session.llm_config = None
    session.resolve_turn(allow_empty_decree=True)
    desk_row = session.pending_decisions()[0]
    payload = _hitl_payload(desk_row)

    try:
        session.submit_hitl_choices(payload, write_gate=session._write_gate)
        raised = None
    except LLMUnavailable as exc:
        raised = exc
    assert raised is not None
    chain = month_chain._load_chain(db, closed_turn)
    assert chain.get("world_continued") is not True
    assert chain.get("world_questions")
    assert session.state.turn_phase == TurnPhase.AWAITING_DECISION.value

    monkeypatch.setattr(
        month_chain, "_run_world_continuation_text",
        lambda *a, **k: "准调关宁，关宁增戍。",
    )
    session.llm_config = object()
    session.submit_hitl_choices(payload, write_gate=session._write_gate)
    chain = month_chain._load_chain(db, closed_turn)
    assert chain.get("world_continued") is True
    assert chain.get("world_questions") in (None, [], ())
```

## [58] tests/test_month_chain_1847.py:1037 `test_decree_continuation_ending_ends_the_month`
flags=['private_helper_call_no_obs_token'] lines=45
```
def test_decree_continuation_ending_ends_the_month(game, monkeypatch):
    """旨意问后续推的退位结局写入月链，推进不得当成 ongoing。"""
    from ming_sim.models import LLMConfig

    db, state, content = game
    closed_turn = int(state.turn)
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="问后结局", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    _pending_id, ref = _stage_edict(db, state, minister, "逊国", "逊国", -1, affair.id)
    db.conn.execute(
        "UPDATE staged_declarations SET questions_json=? WHERE decree_ref=?",
        (json.dumps([{
            "title": "是否逊国", "context": "国势已去",
            "options": [{"label": "逊", "hint": "退位"}, {"label": "守", "hint": "不退"}],
        }], ensure_ascii=False), ref),
    )
    db.conn.commit()

    def translate(*_a, **kwargs):
        if "煤山" not in str(kwargs.get("segment") or ""):
            return {"effects": {}}
        return {"effects": {"emperor_fate": "abdicate"}}

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr(month_chain, "_run_decree_continuation_text", lambda *a, **k: "煤山已定。")
    monkeypatch.setattr(month_translate, "translate_month_segment", translate)
    monkeypatch.setattr(month_chain, "run_gazette_text", lambda *a, **k: ("邸报", "逊国已闻"))
    monkeypatch.setattr("ming_sim.mechanical_tail._run_tail_body", lambda *a, **k: "done")
    session = make_light_session(db, state, content)
    session.llm_config = LLMConfig(
        api_key="sk-test", base_url="https://example.invalid", model="test",
    )
    session.resolve_turn(allow_empty_decree=True)
    question = session.pending_decisions()[0]
    session.submit_hitl_choices([_choice(question)], write_gate=session._write_gate)

    again = session.resolve_turn(allow_empty_decree=True)

    assert again.advanced is True
    assert state.ended is True
    assert state.ending_status == "emperor_abdicate"
    assert month_chain._load_chain(db, closed_turn)["declaration_outcome"]["status"] == "emperor_abdicate"
```

## [59] tests/test_month_chain_1847.py:1133 `test_step_4a_no_eligible_objects_skips_run_and_completes`
flags=['private_helper_call_no_obs_token'] lines=18
```
def test_step_4a_no_eligible_objects_skips_run_and_completes(game, monkeypatch):
    """步骤 4a：无合资格长差案卷且无在办密令时，不为凑调用而起 run。"""
    db, state, content = game
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr(month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}})

    def forbidden_supply(*a, **k):
        raise AssertionError("没有合资格对象时不应调用整月供料 run")

    monkeypatch.setattr(month_chain, "run_secret_orders_supply", forbidden_supply)
    session = make_light_session(db, state, content)

    result = session.resolve_turn(allow_empty_decree=True)

    assert result.stage == "gazette"
    chain = month_chain._load_chain(db, int(state.turn))
    assert chain.get("secret_orders_supply_done") is True
```

## [60] tests/test_month_translate_1840.py:178 `test_world_segment_translates_once_and_persists_repeated_subject_facts_in_order`
flags=['private_helper_call_no_obs_token'] lines=35
```
def test_world_segment_translates_once_and_persists_repeated_subject_facts_in_order(game):
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    person, army = _character_name(db), _army_id(db)
    declaration = {
        "textual_facts": [
            {"subject_kind": "character", "subject_id": person, "body": "人物先记一事"},
            {"subject_kind": "character", "subject_id": person, "body": "人物再记一事"},
            {"subject_kind": "army", "subject_id": army, "body": "军队先记一事"},
            {"subject_kind": "army", "subject_id": army, "body": "军队再记一事"},
        ],
    }
    calls = []

    def translate(prompt, llm_config):
        calls.append((prompt, llm_config))
        return declaration

    dispatch_month_segment(
        db,
        state,
        segment="完整世界段",
        translate_fn=translate,
    )

    assert len(calls) == 1
    person_facts = db.textual_facts.readable_materials(
        subject_kind="character", subject_id=person,
    )
    army_facts = db.textual_facts.readable_materials(
        subject_kind="army", subject_id=army,
    )
    assert [fact.body for fact in person_facts] == ["人物先记一事", "人物再记一事"]
    assert [fact.body for fact in army_facts] == ["军队先记一事", "军队再记一事"]
```

## [61] tests/test_month_translate_1840.py:417 `test_world_segment_failure_rolls_back_only_current_segment`
flags=['private_helper_call_no_obs_token'] lines=39
```
def test_world_segment_failure_rolls_back_only_current_segment(game):
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    person = _character_name(db)
    dispatch_month_segment(
        db,
        state,
        segment="前一段",
        translate_fn=lambda prompt, config: {
            "textual_facts": [{
                "subject_kind": "character", "subject_id": person, "body": "前一段已落",
            }],
        },
    )
    db.conn.execute(
        "CREATE TEMP TRIGGER fail_month_segment_fact "
        "BEFORE INSERT ON textual_facts WHEN NEW.body='阻断本段' "
        "BEGIN SELECT RAISE(ABORT, 'segment write failed'); END"
    )
    db.conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        dispatch_month_segment(
            db,
            state,
            segment="发生代码侧落账异常的当前段",
            translate_fn=lambda prompt, config: {
                "textual_facts": [
                    {"subject_kind": "character", "subject_id": person, "body": "本段先写"},
                    {"subject_kind": "character", "subject_id": person, "body": "阻断本段"},
                ],
            },
        )

    facts = db.textual_facts.readable_materials(
        subject_kind="character", subject_id=person,
    )
    assert [fact.body for fact in facts] == ["前一段已落"]
```

## [62] tests/test_month_translate_1840.py:485 `test_unparseable_month_segment_does_not_stage_or_commit`
flags=['private_helper_call_no_obs_token'] lines=18
```
def test_unparseable_month_segment_does_not_stage_or_commit(game, monkeypatch):
    from ming_sim.audience_translate import AudienceTranslateError
    from ming_sim.month_translate import dispatch_month_segment, stage_month_segment

    db, state, _ = game
    monkeypatch.setattr("ming_sim.cli_backend._run_json_extractor_for_config",
                        lambda *args, **kwargs: ("not-json", ""))
    with pytest.raises(AudienceTranslateError):
        stage_month_segment(db, decree_ref="bad-json", segment="推演段",
                            turn=int(state.turn), decree_payload={})
    assert db.staged_declarations.staged_for("bad-json") == ()
    with pytest.raises(AudienceTranslateError):
        dispatch_month_segment(db, state, segment="世界段")
    assert db.staged_declarations.staged_for("bad-json") == ()

    with pytest.raises(AudienceTranslateError):
        dispatch_month_segment(db, state, segment="世界段",
                               translate_fn=lambda request, config: None)
```

## [63] tests/test_month_translate_1840.py:505 `test_staged_month_effects_keep_input_reference_authority`
flags=['private_helper_call_no_obs_token'] lines=28
```
def test_staged_month_effects_keep_input_reference_authority(game):
    from ming_sim.declaration_dispatch import settle_staged_declarations_in_decree_order
    from ming_sim.month_translate import stage_month_segment

    db, state, _ = game
    visible = db.affairs.open(name="预推可见", origin="旨意", year=state.year,
                              period=state.period, turn=state.turn)
    future_affair_id = visible.id + 1
    before = state.metrics["国库"]
    stage_month_segment(
        db, decree_ref="frozen-refs", segment="预推段", turn=int(state.turn),
        decree_payload={}, translate_fn=lambda request, config: {"effects": {"economy_moves": [
            {"origin_ref": f"affair:{visible.id}", "account": "国库", "delta": -1,
             "category": "过月支出", "reason": "可见事务"},
            {"origin_ref": f"affair:{future_affair_id}", "account": "国库", "delta": -1,
             "category": "过月支出", "reason": "预推后新开事务"},
        ]}},
    )
    assert state.metrics["国库"] == before
    hidden = db.affairs.open(name="暂存后新开", origin="世界段", year=state.year,
                             period=state.period, turn=state.turn)
    assert hidden.id == future_affair_id
    result = settle_staged_declarations_in_decree_order(db, state, ["frozen-refs"])["frozen-refs"]
    assert state.metrics["国库"] == before - 1
    rejections = result.effects.applied[0]["economy_moves_rejections"]
    assert len(rejections) == 1
    assert rejections[0]["rejected"] is True
    assert rejections[0]["item"]["origin_ref"] == f"affair:{hidden.id}"
```

## [64] tests/test_month_translate_1840.py:705 `test_hidden_affair_strategic_result_does_not_trigger_or_land`
flags=['private_helper_call_no_obs_token'] lines=31
```
def test_hidden_affair_strategic_result_does_not_trigger_or_land(game):
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    state.year, state.period = 1629, 11
    state.metrics["民心"] = 50
    hidden = db.affairs.open(
        name="已了结事务", origin="未供料", year=state.year,
        period=state.period, turn=state.turn,
    )
    db.affairs.declare_closed(hidden.id, turn=state.turn)
    metric_before = state.metrics["民心"]
    treasury_before = state.metrics["国库"]
    dispatch_month_segment(db, state, segment="不可见事务战果", translate_fn=lambda _request, _config: {
        "effects": [{
            "event_id": "jisi_lubian",
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "region_delta": {"beizhili": {
                "origin_ref": f"affair:{hidden.id}", "military_pressure": 5,
            }},
            "metric_delta": {"民心": -3},
            "economy_moves": [{
                "origin_ref": "盘面自发", "account": "国库", "delta": -1,
                "category": "过月支出", "reason": "事件所属军需",
            }],
        }],
    })
    assert db.has_event_triggered("jisi_lubian") is False
    assert state.metrics["民心"] == metric_before
    assert state.metrics["国库"] == treasury_before
```

## [65] tests/test_month_translate_1840.py:885 `test_final_strategic_rejection_leaves_no_owned_effects`
flags=['private_helper_call_no_obs_token'] lines=40
```
def test_final_strategic_rejection_leaves_no_owned_effects(game):
    """Owned fields and the event ledger stay one envelope.

    An independent same-kind delta may move the board before the event is
    judged (#1844). Whatever this entry finally records, a non-trigger must
    not keep the event's own metric or treasury delta.
    """
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    state.year, state.period = 1629, 11
    state.metrics["民心"] = 50
    db.conn.execute("UPDATE regions SET military_pressure=90 WHERE id='beizhili'")
    db.conn.commit()
    metric_before = state.metrics["民心"]
    treasury_before = state.metrics["国库"]
    dispatch_month_segment(db, state, segment="独立军压后事件战果", translate_fn=lambda _request, _config: {
        "effects": [
            {"region_delta": {"beizhili": {
                "origin_ref": "盘面自发", "military_pressure": 10,
            }}},
            {
                "event_id": "jisi_lubian",
                "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
                "事件结局": {"jisi_lubian": "入塞被遏"},
                "region_delta": {"beizhili": {
                    "origin_ref": "盘面自发", "military_pressure": 5,
                    "reason": "己巳之变敌逼京畿",
                }},
                "metric_delta": {"民心": -3},
                "economy_moves": [{
                    "origin_ref": "盘面自发", "account": "国库", "delta": -1,
                    "category": "过月支出", "reason": "事件所属军需",
                }],
            },
        ],
    })
    triggered = db.has_event_triggered("jisi_lubian")
    assert state.metrics["民心"] == metric_before + (-3 if triggered else 0)
    assert state.metrics["国库"] == treasury_before + (-1 if triggered else 0)
```

## [67] tests/test_pay_order_override_653.py:199 `test_golden2_haircut_half_is_exemption_not_debt`
flags=['private_helper_call_no_obs_token'] lines=17
```
def test_golden2_haircut_half_is_exemption_not_debt():
    """②「宗禄折半」：floor(Due×bp/10000)；折掉部分不入宗禄欠；NewDebt 只含折后未付。
    r2 golden：Due=101、bp=5000 → 应得 50、免除 51。"""
    from ming_sim.pay_order import haircut_due
    eff, exempt = haircut_due(101, 5000)
    assert eff == 50.0 and exempt == 51.0

    st, p = _board(gross=50.0)  # 省内可支＝10+50=60
    p["Due"] = {"军饷": 18.0, "官俸": 3.0, "宗禄": 101.0, "赈济": 1.0}
    p["due_haircut_bp"] = {"宗禄": 5000}
    res = settle_tick(st, p, [])
    assert res.breakdown["haircut_宗禄"] == pytest.approx(51.0)   # 折发=免除
    # 池 60：军饷18+官俸3+宗禄应得50+赈济1=72>60 → 军饷18/官俸3/宗禄39/赈济0
    assert res.breakdown["实付分账"]["宗禄"] == pytest.approx(39.0)
    assert res.new_st["宗禄欠"] == pytest.approx(11.0)  # 只含折后未付（50−39）
    # 免除的 51 绝不进 CLAIM（若无折，宗禄欠将是 101-39=62）
    assert res.new_st["宗禄欠"] < 62.0
```

## [68] tests/test_pay_order_override_653.py:1364 `test_fact_brief_province_auto_repaied_is_beneficiary_fact`
flags=['private_helper_call_no_obs_token'] lines=20
```
def test_fact_brief_province_auto_repaied_is_beneficiary_fact(game):
    """省池自动偿还（surplus waterfall）＝army_logs 当月负 delta → 军户受益事实（<0）。"""
    db, state, _content = game
    turn = db._current_settle_turn()
    db.conn.execute(
        "INSERT INTO army_logs (turn, year, period, army_id, field, old_value,"
        " new_value, delta, reason, actor)"
        " VALUES (?, 1, 1, 'shaanxi_army', 'province_pay_arrears', '16.25',"
        " '10.25', -6.0, '按省份额欠余额占比偿还', '户部')",
        (turn,),
    )
    db.conn.commit()
    entries = build_fiscal_fact_brief(db)
    repaid = [
        e for e in entries
        if e["subject_id"] == "shaanxi_army" and e["detail"] == "省源偿欠"
    ]
    assert repaid and repaid[0]["value"] == pytest.approx(-6.0)
    assert repaid[0]["region"] == "shaanxi"
    assert repaid[0]["origin_ref"].startswith("army_logs:")
```

## [69] tests/test_pihong_dossier_1490.py:505 `test_657_c1_validate_rejects_stale_capability_and_desk_outsider`
flags=['private_helper_call_no_obs_token'] lines=10
```
def test_657_c1_validate_rejects_stale_capability_and_desk_outsider(game):
    """C1.5 stale capability；desk 外键整批拒。"""
    from ming_sim import rescript_actions as ra
    db, state, _content = game
    urgent, opts = _plant_urgent_desk(db, state)
    key = urgent['decision_key']
    with pytest.raises(ValueError):
        ra.validate_all([urgent], [{'decision_key': key, 'action': 'follow_draft', 'draft_capability': 'not-a-real-cap', 'label': opts[0]['label']}])
    with pytest.raises(ValueError):
        ra.validate_all([urgent], [{'decision_key': 'rescript_draft:999:0', 'action': 'hold', 'label': '留中'}])
```

## [70] tests/test_pihong_dossier_1490.py:1855 `test_657_preferred_hitl_choice_urgent_follow_draft_ordinary_intact`
flags=['private_helper_call_no_obs_token'] lines=17
```
def test_657_preferred_hitl_choice_urgent_follow_draft_ordinary_intact():
    """② 共享首选项投影：急务=follow_draft+capability；普通 decision 不变。"""
    from ming_sim.rescript_actions import project_preferred_hitl_choice
    opt = _layer_a_option()
    urgent = {'kind': 'rescript_draft', 'decision_key': 'rescript_draft:1:0', 'title': '急', 'idx': 0, 'options': [opt, {'label': '备', 'hint': 'h', 'draft_capability': 'x'}]}
    pref = project_preferred_hitl_choice(urgent)
    assert pref['action'] == 'follow_draft'
    assert pref['draft_capability'] == opt['draft_capability']
    assert pref['decision_key'] == 'rescript_draft:1:0'
    assert pref['label'] == opt['label']
    ordinary = {'kind': 'decision', 'decision_key': 'decision:1:0', 'idx': 0, 'options': [{'label': '甲', 'hint': 'h1', 'dossier_id': 3, 'dossier_decision': 'hold'}, {'label': '乙', 'hint': 'h2'}]}
    pref2 = project_preferred_hitl_choice(ordinary)
    assert pref2.get('action') in (None, '')
    assert pref2['label'] == '甲'
    assert pref2['dossier_id'] == 3
    assert pref2['dossier_decision'] == 'hold'
    assert 'follow_draft' not in str(pref2.get('action') or '')
```

## [71] tests/test_pihong_dossier_1490.py:1889 `test_657_clear_revise_anchor_corrupt_json_fails_loud`
flags=['private_helper_call_no_obs_token'] lines=13
```
def test_657_clear_revise_anchor_corrupt_json_fails_loud(game):
    """④ 清锚扫描：choice_json 损坏 / 非 object → 响亮失败，禁静默跳过。"""
    from ming_sim import rescript_actions as ra
    db, state, _content = game
    urgent, _ = _plant_urgent_desk(db, state)
    db.conn.execute("UPDATE pending_decisions SET choice_json=?, revision_round=1 WHERE turn=? AND idx=? AND kind='rescript_draft'", ('{not-json', int(urgent['source_turn'] or urgent['turn']), int(urgent['idx'])))
    db.conn.commit()
    with pytest.raises(ValueError):
        ra.clear_return_revise_choice_anchors(db, None)
    db.conn.execute("UPDATE pending_decisions SET choice_json=? WHERE turn=? AND idx=? AND kind='rescript_draft'", ('[1,2]', int(urgent['source_turn'] or urgent['turn']), int(urgent['idx'])))
    db.conn.commit()
    with pytest.raises(ValueError):
        ra.clear_return_revise_choice_anchors(db, None)
```

## [72] tests/test_pihong_dossier_1490.py:1903 `test_657_default_hold_preserves_red_pen_note`
flags=['private_helper_call_no_obs_token'] lines=10
```
def test_657_default_hold_preserves_red_pen_note(game):
    """⑤ 默认 hold 保留朱笔 note。"""
    from ming_sim import rescript_actions as ra
    db, state, _content = game
    urgent, _ = _plant_urgent_desk(db, state)
    key = urgent['decision_key']
    batch = ra.validate_all([urgent], [{'decision_key': key, 'note': '着再议。'}], default_hold_missing=True)
    assert key in batch.default_hold_keys
    assert batch.items[0].choice.get('action') == 'hold'
    assert batch.items[0].choice.get('note') == '着再议。'
```

## [73] tests/test_pihong_dossier_1490.py:2097 `test_1625_phase1_publication_projects_only_coherent_recovery_tuples`
flags=['private_helper_call_no_obs_token'] lines=49
```
def test_1625_phase1_publication_projects_only_coherent_recovery_tuples(web_game):
    """#1625：真实 GET 横穿 phase1 发布时，旧相位必须携带 typed in-flight。"""
    db, original_state = (web_game.db, web_game.state)
    phase_sampled = threading.Event()
    phase_published = threading.Event()
    entry_ended = threading.Event()
    entry_lock = web_app._settlement_entry_lock(web_game)

    class PhaseRaceState(type(original_state)):
        _race_armed = False

        def __getattribute__(self, name):
            value = super().__getattribute__(name)
            if name == 'turn_phase' and super().__getattribute__('_race_armed'):
                super().__setattr__('_race_armed', False)
                phase_sampled.set()
                phase_published.wait()
                if not entry_lock.locked():
                    entry_ended.wait()
            return value
    state = PhaseRaceState(**original_state.__dict__)
    state.turn_phase = TurnPhase.SETTLING.value
    web_game.session.state = state
    db.save_state(state)
    db.conn.commit()
    web_app._begin_settlement_entry(web_game)
    desk_holder = {}

    def _publish_phase1():
        phase_sampled.wait()
        desk_holder['desk'] = _657_plant_awaiting_web(web_game, drafts=[{'title': '发布中的案头', 'context': 'c', 'options': [{'label': '准', 'hint': 'h', 'draft_capability': 'approve'}, {'label': '驳', 'hint': 'h', 'draft_capability': 'reject'}], 'actor_name': '杨嗣昌', 'actor_office': '兵部尚书', 'actor_faction': '帝党'}])
        phase_published.set()
        web_app._end_settlement_entry(web_game)
        entry_ended.set()
    publisher = threading.Thread(target=_publish_phase1)
    publisher.start()
    state._race_armed = True
    crossed = asyncio.run(_get_state())
    publisher.join()
    assert not publisher.is_alive()
    assert crossed['turn']['phase'] == TurnPhase.SETTLING.value
    assert crossed['settlement_entry_inflight'] is True
    assert crossed['pending_decisions'] == []
    assert crossed['resume_phase2'] is False
    durable = asyncio.run(_get_state())
    assert durable['turn']['phase'] == TurnPhase.AWAITING_DECISION.value
    assert durable['settlement_entry_inflight'] is False
    assert durable['pending_decisions'] == desk_holder['desk']
    assert durable['resume_phase2'] is False
```

## [74] tests/test_qa_c2_settlement_display_lifecycle_1343.py:130 `test_success_clear_throw_still_ends_inflight`
flags=['private_helper_call_no_obs_token'] lines=39
```
def test_success_clear_throw_still_ends_inflight(game, monkeypatch):
    """验收：成功支 clear 抛错仍执行 _end_settlement_entry（inflight 归零）。

    且 settled_ok 不得在 clear 前预置真——clear 抛须走失败 exit，
    禁「成功态 + 死遮罩」绕过失败收口。
    """
    db, state, content = game
    runtime = _shell(db, state, content)
    state.turn_phase = TurnPhase.SUMMONING.value
    db.save_state(state)
    db.capture_month_open_snapshot(state)

    monkeypatch.setattr(web_app, "_accept_settlement_period", lambda _g: True)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda _g, **_k: None)

    exit_calls = {"n": 0}
    real_exit = web_app._exit_settlement_display_on_failure

    def _spy_exit(g, *, blocking=False):
        exit_calls["n"] += 1
        return real_exit(g, blocking=blocking)

    monkeypatch.setattr(web_app, "_exit_settlement_display_on_failure", _spy_exit)

    def _boom_clear(_t):
        raise RuntimeError("clear boom")

    db.clear_month_open_snapshot = _boom_clear  # type: ignore[method-assign]

    raised = None
    try:
        with web_app._settlement_period_entry(runtime, write_cm=_blocking_gate):
            pass
    except RuntimeError as exc:
        raised = exc

    assert raised is not None and "clear boom" in str(raised)
    assert web_app._settlement_entry_inflight(runtime) == 0, "clear 抛错后 inflight 须归零"
    assert exit_calls["n"] == 1, "clear 抛须走失败 exit（settled_ok 未在 clear 前预置）"
```

## [75] tests/test_qa_c2_settlement_display_lifecycle_1343.py:171 `test_failure_exit_throw_still_ends_inflight`
flags=['private_helper_call_no_obs_token'] lines=24
```
def test_failure_exit_throw_still_ends_inflight(game, monkeypatch):
    """对称：失败支 exit 抛错亦不得卡住 inflight（嵌套 finally 销账）。"""
    db, state, content = game
    runtime = _shell(db, state, content)
    state.turn_phase = TurnPhase.SUMMONING.value
    db.save_state(state)

    monkeypatch.setattr(web_app, "_accept_settlement_period", lambda _g: True)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda _g, **_k: None)

    def _boom_exit(*_a, **_k):
        raise RuntimeError("exit boom")

    monkeypatch.setattr(web_app, "_exit_settlement_display_on_failure", _boom_exit)

    raised = None
    try:
        with web_app._settlement_period_entry(runtime, write_cm=_blocking_gate):
            raise ValueError("body fail")
    except RuntimeError as exc:
        raised = exc

    assert raised is not None and "exit boom" in str(raised)
    assert web_app._settlement_entry_inflight(runtime) == 0
```

## [76] tests/test_qa_t1_extraction_dual_source_1353.py:262 `test_empty_startup_catchup_claims_zero_tickets`
flags=['private_helper_call_no_obs_token'] lines=10
```
def test_empty_startup_catchup_claims_zero_tickets(web_game):
    """#1353 r7：无待补时 startup catch-up 不领票——禁 residual pending 竞态。"""
    game = web_game
    q = game._runtime_write_queue()
    # fresh WebGame 无未抽回话；init 时 spawn 必须早退，队列空。
    assert q.inflight_count() == 0
    assert int(game._pending_writes_count) == 0
    # 显式再调仍不领票。
    game._spawn_startup_extraction_catch_up()
    assert q.inflight_count() == 0
```

## [77] tests/test_qa_t1_extraction_dual_source_1353.py:274 `test_barrier_waits_trail_ticket_then_auto_close`
flags=['private_helper_call_no_obs_token'] lines=51
```
def test_barrier_waits_trail_ticket_then_auto_close(web_game, monkeypatch):
    """#1353 生产接缝屏障钉：尾随领票未完成时 entry 不得抢跑；完成后一次过。"""
    game = web_game
    # 空库 startup 不得占票；本钉只见自领 1 票（全量 xdist 顺序依赖根因）。
    assert int(game._pending_writes_count) == 0
    ticket = game._mark_pending_write(key=("turn", 1))
    assert ticket is not None
    assert int(game._pending_writes_count) == 1

    order: list[str] = []
    trail_holding = threading.Event()
    release = threading.Event()
    entry_done = threading.Event()

    def trail_worker() -> None:
        trail_holding.set()
        release.wait()
        order.append("trail_end")
        game._complete_pending_write(ticket)

    t = threading.Thread(target=trail_worker, name="trail-barrier", daemon=True)
    t.start()
    trail_holding.wait()

    def track_auto_close(_g, **_k):
        assert ticket._done is True
        order.append("auto_close")

    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", track_auto_close)
    monkeypatch.setattr(web_app, "_accept_settlement_period", lambda _g: False)

    def run_entry() -> None:
        with web_app._settlement_period_entry(game, write_cm=web_app._game_write_gate):
            order.append("body")
        entry_done.set()

    et = threading.Thread(target=run_entry, name="settlement-entry", daemon=True)
    et.start()
    # 确定性：trail 未放行前 entry 不得完成（事件握手，不靠 sleep 判胜负）
    assert not entry_done.is_set()
    assert "auto_close" not in order
    assert "body" not in order

    order.append("release")
    release.set()
    entry_done.wait()
    t.join()
    et.join()
    assert not t.is_alive() and not et.is_alive()
    assert order == ["release", "trail_end", "auto_close", "body"], order
    assert int(game._pending_writes_count) == 0
```

## [78] tests/test_qa_t1_extraction_dual_source_1353.py:327 `test_production_seam_cancel_blocks_trail_write`
flags=['private_helper_call_no_obs_token'] lines=38
```
def test_production_seam_cancel_blocks_trail_write(web_game):
    """生产接缝撤回钉：暂停腿 → cancel_key → 放行，TicketedWriteGate 零写。"""
    from ming_sim.session_write_queue import TicketCancelled

    game = web_game
    q = game._runtime_write_queue()
    ticket = game._mark_pending_write(key=("turn", 4242))
    assert ticket is not None

    entered = threading.Event()
    release = threading.Event()
    wrote = {"n": 0}
    outcome: dict = {}

    def paused_trail() -> None:
        entered.set()
        release.wait()
        gate = game._ticketed_write_gate(ticket)
        try:
            with gate:
                wrote["n"] += 1
            outcome["ok"] = True
        except TicketCancelled as exc:
            outcome["cancelled"] = type(exc).__name__
        finally:
            game._complete_pending_write(ticket)

    th = threading.Thread(target=paused_trail, daemon=True)
    th.start()
    entered.wait()
    n = q.cancel_key(("turn", 4242))
    assert n == 1
    release.set()
    th.join()
    assert not th.is_alive()
    assert wrote["n"] == 0
    assert outcome.get("cancelled") == "TicketCancelled"
    assert "ok" not in outcome
```

## [79] tests/test_qa_t1_extraction_dual_source_1353.py:367 `test_production_seam_post_barrier_ticket_ordered`
flags=['private_helper_call_no_obs_token'] lines=54
```
def test_production_seam_post_barrier_ticket_ordered(web_game, monkeypatch):
    """生产接缝：屏障已领后再领票，后票写不得越过屏障（经 ticketed gate）。"""
    game = web_game
    game._runtime_write_queue()
    order: list[str] = []
    barrier_in = threading.Event()
    release_barrier = threading.Event()
    late_claimed = threading.Event()
    late_done = threading.Event()

    def track_auto_close(_g, **_k):
        barrier_in.set()
        late_claimed.wait()
        order.append("barrier")
        release_barrier.wait()

    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", track_auto_close)
    monkeypatch.setattr(web_app, "_accept_settlement_period", lambda _g: False)

    entry_done = threading.Event()

    def run_entry() -> None:
        with web_app._settlement_period_entry(game, write_cm=web_app._game_write_gate):
            order.append("body")
        entry_done.set()

    et = threading.Thread(target=run_entry, daemon=True)
    et.start()
    barrier_in.wait()

    late = game._mark_pending_write(key=("turn", 77))
    assert late is not None
    late_claimed.set()

    def late_write() -> None:
        gate = game._ticketed_write_gate(late)
        with gate:
            order.append("late")
        game._complete_pending_write(late)
        late_done.set()

    lt = threading.Thread(target=late_write, daemon=True)
    lt.start()
    assert "late" not in order
    assert not late_done.is_set()

    release_barrier.set()
    entry_done.wait()
    late_done.wait()
    et.join()
    lt.join()
    # barrier 写（auto_close）先于后票；body 在 barrier 返回后
    assert order.index("barrier") < order.index("late")
    assert order.index("barrier") < order.index("body")
```

## [80] tests/test_qa_t1_extraction_dual_source_1353.py:469 `test_startup_catchup_uses_ticketed_gate_not_bare`
flags=['private_helper_call_no_obs_token'] lines=21
```
def test_startup_catchup_uses_ticketed_gate_not_bare(web_game, monkeypatch):
    """startup catch-up 须经票据写缝：非阻塞 acquire 拒收（裸 Lock 会放行）。"""
    game = web_game
    seen = {}

    def fake_catch_up(*, write_gate=None, **_k):
        # 外部契约：票据缝拒非阻塞 acquire；threading.Lock 会返回 True。
        try:
            write_gate.acquire(blocking=False)
            seen["bare_lock"] = True
            write_gate.release()
        except RuntimeError:
            seen["ticketed_contract"] = True

    monkeypatch.setattr(web_app, "catch_up_pending_translations", fake_catch_up)
    ticket = game._mark_pending_write(key=("startup",))
    assert ticket is not None
    game._run_startup_extraction_catch_up(pending_ticket=ticket)
    assert seen.get("ticketed_contract") is True
    assert seen.get("bare_lock") is not True
    assert ticket._done is True
```

## [81] tests/test_qa_t1_extraction_dual_source_1353.py:492 `test_ticketed_write_gate_rejects_none`
flags=['private_helper_call_no_obs_token'] lines=5
```
def test_ticketed_write_gate_rejects_none(web_game):
    """无票不得回落裸 runtime write_gate。"""
    game = web_game
    with pytest.raises(RuntimeError):
        game._ticketed_write_gate(None)  # type: ignore[arg-type]
```

## [82] tests/test_qa_t1_extraction_dual_source_1353.py:559 `test_seal_rejects_new_claim_after_lifecycle`
flags=['private_helper_call_no_obs_token'] lines=10
```
def test_seal_rejects_new_claim_after_lifecycle(web_game):
    """生命周期 seal 后新领票拒入（旧 _draining 语义）。"""
    game = web_game
    q = game._runtime_write_queue()
    q.seal()
    assert game._mark_pending_write() is None
    q.unseal()
    t = game._mark_pending_write()
    assert t is not None
    game._complete_pending_write(t)
```

## [83] tests/test_relation_read_640.py:163 `test_load_relation_history_before_returns_full_stable_prior_stream`
flags=['private_helper_call_no_obs_token'] lines=46
```
def test_load_relation_history_before_returns_full_stable_prior_stream(game):
    """r4：已选中有向对的严格早于 settled 年月的完整历史——多旧事全量、含和解、无裁剪。"""
    from ming_sim.relation_read import load_relation_history_before

    db, state, _ = game
    source, target = "杨嗣昌", "倪元璐"
    # 旧事 1（奠基）
    db.record_relation_edge_event(
        source=source, target=target, event_kind="结怨",
        context="杨嗣昌与倪元璐初有细缝。", origin="seed:founding:yang-ni",
        turn=0, year=1627, period=10,
    )
    # 旧事 2（后续加深）
    db.record_relation_edge_event(
        source=source, target=target, event_kind="使绊",
        context="清丈议上，杨嗣昌挡了倪元璐的硬路。", origin="audience:turn-2",
        turn=2, year=1628, period=11,
    )
    # 旧事 3（和解——同流后续，不删旧怨）
    db.record_relation_edge_event(
        source=source, target=target, event_kind="协作",
        context="二人当面言和，暂释前隙。", origin="audience:turn-3",
        turn=3, year=1629, period=3,
    )
    # 本 settled 月新事——不得进入 prior
    db.record_relation_edge_event(
        source=source, target=target, event_kind="站台",
        context="本月新站台，不应进历史包。", origin="audience:turn-4",
        turn=4, year=1630, period=5,
    )

    prior = load_relation_history_before(
        db, source=source, target=target, before_year=1630, before_period=5,
    )
    assert [row["context"] for row in prior] == [
        "杨嗣昌与倪元璐初有细缝。",
        "清丈议上，杨嗣昌挡了倪元璐的硬路。",
        "二人当面言和，暂释前隙。",
    ]
    # 稳定序＝纪年 (year, period) ＋事件 id；语境字节不改。
    assert [(int(r["year"]), int(r["period"])) for r in prior] == [
        (1627, 10), (1628, 11), (1629, 3),
    ]
    ids = [int(r["id"]) for r in prior]
    assert ids == sorted(ids)
    assert prior[2]["context"] == "二人当面言和，暂释前隙。"
```

## [84] tests/test_relation_read_640.py:211 `test_load_relation_history_before_empty_when_no_older_events`
flags=['private_helper_call_no_obs_token'] lines=15
```
def test_load_relation_history_before_empty_when_no_older_events(game):
    """r4 验收第三例：无严格更早流水 → 空列表。"""
    from ming_sim.relation_read import load_relation_history_before

    db, state, _ = game
    db.record_relation_edge_event(
        source="徐光启", target="杨嗣昌", event_kind="协作",
        context="本月当场协作。", origin="audience:now",
        turn=int(state.turn), year=int(state.year), period=int(state.period),
    )
    prior = load_relation_history_before(
        db, source="徐光启", target="杨嗣昌",
        before_year=int(state.year), before_period=int(state.period),
    )
    assert prior == []
```

## [85] tests/test_relation_seed_638.py:50 `test_seeded_pair_flows_into_month_end_brew_selection`
flags=['private_helper_call_no_obs_token'] lines=30
```
def test_seeded_pair_flows_into_month_end_brew_selection(fresh_session):
    """同一套酿制（ADR 0086 机械面）：seed 对在真实月末落新事件后，月末腿照常
    选中该对，且 seed 边因水位为 0 一并进入酿制输入。"""
    from ming_sim.relation_brew import collect_new_edge_events, select_brew_targets

    sess, _content = fresh_session
    state = sess.state
    pair_events = [
        e for e in sess.db.get_relation_edge_events()
        if e["source"] == "魏忠贤" and e["target"] == "杨涟"
    ]
    assert pair_events, "样例 seed 缺魏忠贤→杨涟奠基边"

    new_id = sess.db.record_relation_edge_event(
        source="魏忠贤", target="杨涟", event_kind="结怨",
        context="崇祯元年十月新账。",
        origin="test:month-event", turn=int(state.turn),
        year=int(state.year), period=int(state.period),
    )
    targets = select_brew_targets(db=sess.db, year=int(state.year), period=int(state.period))
    match = [t for t in targets if t["source"] == "魏忠贤" and t["target"] == "杨涟"]
    assert match, "seed 对未被月末腿选中"
    assert int(match[0]["watermark"]) == 0, "seed 导入不得推进水位"

    new_events = collect_new_edge_events(
        db=sess.db, source="魏忠贤", target="杨涟", watermark=0,
    )
    ids = {int(event["id"]) for event in new_events}
    assert int(new_id) in ids
    assert {int(event["id"]) for event in pair_events} <= ids
```

## [86] tests/test_relation_seed_638.py:270 `test_reverse_chronological_seed_keeps_latest_event_readable`
flags=['private_helper_call_no_obs_token'] lines=14
```
def test_reverse_chronological_seed_keeps_latest_event_readable(fresh_session):
    """逆序素材按史时稳定写入。"""
    from ming_sim.relation_seed import import_relationship_seed

    sess, _content = fresh_session
    doc = {"events": [
        {"source": "甲", "target": "乙", "event_kind": "结怨", "context": "后事。",
         "origin": "seed:later", "evidence": False, "year": 1626, "period": 2},
        {"source": "甲", "target": "乙", "event_kind": "结怨", "context": "前事。",
         "origin": "seed:earlier", "evidence": False, "year": 1625, "period": 2},
    ]}
    import_relationship_seed(sess.db, doc, opening_year=1627, opening_period=10)
    rows = sess.db.get_relation_edge_events(source="甲", target="乙")
    assert [(row["year"], row["period"]) for row in rows] == [(1625, 2), (1626, 2)]
```

## [87] tests/test_relation_seed_638.py:286 `test_pre_tianqi_seed_event_retains_structured_clock`
flags=['private_helper_call_no_obs_token'] lines=11
```
def test_pre_tianqi_seed_event_retains_structured_clock(fresh_session):
    from ming_sim.relation_seed import import_relationship_seed

    sess, _content = fresh_session
    doc = {"events": [{
        "source": "丙", "target": "丁", "event_kind": "结怨", "context": "旧事。",
        "origin": "seed:1620", "evidence": False, "year": 1620, "period": 1,
    }]}
    import_relationship_seed(sess.db, doc, opening_year=1627, opening_period=10)
    rows = sess.db.get_relation_edge_events(source="丙", target="丁")
    assert [(row["year"], row["period"]) for row in rows] == [(1620, 1)]
```

## [88] tests/test_relation_seed_638.py:419 `test_issue_639_seed_owner_audit_corrections`
flags=['private_helper_call_no_obs_token'] lines=108
```
def test_issue_639_seed_owner_audit_corrections(fresh_session):
    """#639 owner 裁决：史料确错改正；野史可留但不得 evidence:true；根本冲突删除。"""
    sess, _content = fresh_session
    events = [dict(row) for row in sess.db.get_relation_edge_events()]

    def by_origin_prefix(prefix: str) -> dict:
        matches = [row for row in events if str(row["origin"]).startswith(prefix)]
        assert len(matches) == 1, f"origin prefix {prefix!r} -> {matches!r}"
        return matches[0]

    # 野史/见闻把柄不得伪装成可核硬史实
    cover = by_origin_prefix("seed:founding:cui-tian-cover")
    assert cover["evidence"] is False
    assert cover["event_kind"] == "把柄"

    # 史料日期确错：崔夜投魏＝天启四年九月；黄立极入阁＝五年八月
    cui = by_origin_prefix("seed:founding:cui-wei-submission")
    assert (cui["year"], cui["period"]) == (1624, 9)
    huang = by_origin_prefix("seed:founding:wei-huangliji-promotion")
    assert (huang["year"], huang["period"]) == (1625, 8)

    # 阎鸣泰：景忠山生祠在天启七年二月，不得倒填开局前；改用史载潜结/召用
    yan = by_origin_prefix("seed:founding:yanmingtai-wei-attach")
    assert (yan["source"], yan["target"]) == ("阎鸣泰", "魏忠贤")
    assert (yan["year"], yan["period"]) == (1625, 6)
    # 李从心：禁天启七年生祠倒填；改魏→李荐引（点名/题本关照），不得复用 works origin
    assert not any(
        str(row["origin"]).startswith("seed:founding:wei-licongxin-works")
        for row in events
    )
    licongxin_edges = [
        row for row in events
        if row["source"] == "李从心" or row["target"] == "李从心"
    ]
    assert len(licongxin_edges) == 1
    li = licongxin_edges[0]
    assert (li["source"], li["target"], li["event_kind"]) == ("魏忠贤", "李从心", "荐引")
    assert str(li["origin"]).startswith("seed:founding:wei-licongxin-patronage")
    assert li["evidence"] is False

    # ADR 0086 三硬锚：盟誓 / 拦升迁 / 私怨（盟誓禁「多年」倒填）
    oath = by_origin_prefix("seed:founding:wei-cui-oath")
    assert (oath["source"], oath["target"], oath["event_kind"]) == (
        "魏忠贤", "崔呈秀", "恩义",
    )
    assert oath["evidence"] is False
    assert (int(oath["year"]), int(oath["period"])) == (1625, 6)

    block = by_origin_prefix("seed:founding:tian-liruolian-block")
    assert (block["source"], block["target"], block["event_kind"]) == (
        "田尔耕", "李若琏", "使绊",
    )
    assert block["evidence"] is False

    grudge = by_origin_prefix("seed:founding:maoyujian-tian-grudge")
    assert (grudge["source"], grudge["target"], grudge["event_kind"]) == (
        "毛羽健", "田尔耕", "结怨",
    )
    assert grudge["evidence"] is False

    # 施/张：史载依媚/生祠碑，不作魏荐引入阁；入阁月=六年七月
    shi = by_origin_prefix("seed:founding:wei-shifenglai-promotion")
    assert (shi["source"], shi["target"], shi["event_kind"]) == ("施凤来", "魏忠贤", "站台")
    assert (shi["year"], shi["period"]) == (1626, 7)
    zhang = by_origin_prefix("seed:founding:wei-zhangruitu-promotion")
    assert (zhang["source"], zhang["target"], zhang["event_kind"]) == (
        "张瑞图", "魏忠贤", "站台",
    )
    assert (zhang["year"], zhang["period"]) == (1626, 7)

    # 郭允厚：矫旨擢太仆少卿＝天启四年十二月（韩爌致仕次月）
    guo = by_origin_prefix("seed:founding:wei-guoyunhou-finance")
    assert (guo["source"], guo["target"], guo["event_kind"]) == ("魏忠贤", "郭允厚", "荐引")
    assert (guo["year"], guo["period"]) == (1624, 12)

    # 王体乾：翼护/保持语义；不得把调旨主语安在王
    wang = by_origin_prefix("seed:founding:wangtiqian-wei-support")
    assert (wang["source"], wang["target"], wang["event_kind"]) == ("王体乾", "魏忠贤", "站台")
    assert (wang["year"], wang["period"]) == (1624, 6)

... (28 more lines)
```

## [89] tests/test_rescript_choices_563.py:201 `test_financial_decision_uses_stored_option_not_client_payload`
flags=['private_helper_call_no_obs_token'] lines=52
```
def test_financial_decision_uses_stored_option_not_client_payload(amount):
    """Raw season options retain strict catalog types and remain server-authoritative."""
    from ming_sim import rescript_actions as ra
    from ming_sim.settlement_payload import parse_decision_blocks

    blocks = [
        {
            "title": "发帑", "context": "济军", "options": [{
                "label": "发内帑三十万两", "hint": "济军",
                "action_type": "grant_allocation", "grant_action": "协饷",
                "account": "内库", "amount": amount, "purpose": "补饷",
                "target_kind": "army", "target_id": "guanning", "cadence": "一次性",
            }, {"label": "暂缓", "hint": "守财"}],
        },
        {
            "title": "巡河", "context": "河工", "options": [
                {"label": "遣员巡河", "hint": "查勘"},
                {"label": "暂缓巡河", "hint": "候报"},
            ],
        },
    ]
    raw = "世界段" + "".join(
        f"<<DECISION>>{json.dumps(block, ensure_ascii=False)}<<END>>"
        for block in blocks
    )
    decisions = parse_decision_blocks(raw)
    if type(amount) is not int:
        # Parse/save boundary rejects the whole malformed typed decision.
        assert [decision["title"] for decision in decisions] == ["巡河"]
        return
    desk = [{
        "decision_key": f"decision:3:{idx}", "kind": "decision", "turn": 3,
        "idx": idx, "status": "pending", "options": decision["options"],
    } for idx, decision in enumerate(decisions)]
    requests = [
        {
            "decision_key": "decision:3:0", "label": "发内帑三十万两",
            "action_type": "punishment", "account": "国库", "amount": 999,
        },
        {"decision_key": "decision:3:1", "label": "遣员巡河"},
    ]

    batch = ra.validate_all(desk, requests)
    assert len(batch.items) == 2
    choice = batch.items[0].choice
    assert choice["action_type"] == "punishment"  # persisted request identity
    execution = batch.items[0].execution_option
    assert execution is not None
    assert execution["action_type"] == "grant_allocation"
    assert execution["account"] == "内库"
    assert execution["amount"] == 30
    assert type(execution["amount"]) is int
```

## [90] tests/test_rescript_choices_563.py:255 `test_decision_parser_rejects_unknown_typed_action_and_keeps_sibling`
flags=['private_helper_call_no_obs_token'] lines=97
```
def test_decision_parser_rejects_unknown_typed_action_and_keeps_sibling():
    from ming_sim.settlement_payload import parse_decision_blocks

    malformed = {
        "title": "发帑", "context": "济军", "options": [{
            "label": "发内帑三十万两", "hint": "济军",
            "action_type": "grant_allocaton", "grant_action": "协饷",
            "account": "内库", "amount": 30, "purpose": "补饷",
            "target_kind": "army", "target_id": "guanning", "cadence": "一次性",
        }, {"label": "暂缓", "hint": "守财"}],
    }
    blank_discriminator = {
        **malformed,
        "title": "空白拨帑",
        "options": [
            {**malformed["options"][0], "action_type": "   "},
            malformed["options"][1],
        ],
    }
    missing_discriminator = {
        **malformed,
        "title": "无类拨帑",
        "options": [
            {k: v for k, v in malformed["options"][0].items()
             if k != "action_type"},
            malformed["options"][1],
        ],
    }
    incompatible_discriminator = {
        **malformed,
        "title": "错类拨帑",
        "options": [
            {**malformed["options"][0], "action_type": "punishment"},
            malformed["options"][1],
        ],
    }
    bare_incompatible_discriminator = {
        **malformed,
        "title": "裸错类",
        "options": [
            {"label": "惩处", "hint": "候旨", "action_type": "punishment"},
            malformed["options"][1],
        ],
    }
    inapplicable_grant_action = {
        **malformed,
        "title": "错配内帑",
        "options": [
            {
                **malformed["options"][0],
                "action_type": "grant_allocation",
                "grant_action": "发内帑",
            },
            malformed["options"][1],
        ],
    }
    inapplicable_target_kind = {
        **malformed,
        "title": "错配协饷目标",
        "options": [
            {
                **malformed["options"][0],
                "action_type": "grant_allocation",
                "target_kind": "character",
            },
            malformed["options"][1],
        ],
    }
    spaced_legal = {
        **malformed,
        "title": "犒军",
        "options": [
            {**malformed["options"][0], "action_type": " grant_allocation "},
            malformed["options"][1],
        ],
    }
    sibling = {
        "title": "巡河", "context": "河工", "options": [
            {"label": "遣员巡河", "hint": "查勘"},
            {"label": "暂缓巡河", "hint": "候报"},
... (17 more lines)
```

## [91] tests/test_rescript_choices_563.py:355 `test_decision_parser_rejects_empty_or_ambiguous_labels`
flags=['private_helper_call_no_obs_token'] lines=10
```
def test_decision_parser_rejects_empty_or_ambiguous_labels(labels):
    from ming_sim.settlement_payload import parse_decision_blocks

    block = {
        "title": "歧义抉择", "context": "c",
        "options": [{"label": label, "hint": "h"} for label in labels],
    }
    raw = f"<<DECISION>>{json.dumps(block, ensure_ascii=False)}<<END>>"
    decisions = parse_decision_blocks(raw)
    assert decisions == []
```

## [92] tests/test_rescript_option_field_heal_1746.py:178 `test_run_agent_text_prior_messages_sent_as_message_list`
flags=['private_helper_call_no_obs_token'] lines=31
```
def test_run_agent_text_prior_messages_sent_as_message_list():
    from agno.models.message import Message
    from ming_sim.agents import run_agent_text

    captured: list[object] = []

    class _Agent:
        def run(self, input):
            captured.append(input)

            class _Out:
                content = '{"ok":true}'
                messages = None

            return _Out()

    prior = [
        {"role": "user", "content": "first-user"},
        {"role": "assistant", "content": "first-assistant"},
    ]
    text = run_agent_text(
        _Agent(), "heal-user", tag="rescript-draft-heal", prior_messages=prior,
    )
    assert text == '{"ok":true}'
    payload = captured[0]
    assert isinstance(payload, list) and len(payload) == 3
    assert all(isinstance(m, Message) for m in payload)
    assert [m.role for m in payload] == ["user", "assistant", "user"]
    assert [m.content for m in payload] == [
        "first-user", "first-assistant", "heal-user",
    ]
```

## [93] tests/test_rescript_option_field_heal_1746.py:211 `test_run_agent_text_without_prior_passes_plain_prompt`
flags=['private_helper_call_no_obs_token'] lines=17
```
def test_run_agent_text_without_prior_passes_plain_prompt():
    from ming_sim.agents import run_agent_text

    captured: list[object] = []

    class _Agent:
        def run(self, input):
            captured.append(input)

            class _Out:
                content = "x"
                messages = None

            return _Out()

    assert run_agent_text(_Agent(), "solo", tag="t") == "x"
    assert captured == ["solo"]
```

## [94] tests/test_runtime_llm_config.py:431 `test_cli_backend_active_explicit_cli_bogus_runner_false_despite_env`
flags=['private_helper_call_no_obs_token'] lines=10
```
def test_cli_backend_active_explicit_cli_bogus_runner_false_despite_env(monkeypatch):
    # ship-pre CMR Group F'：显式 channel=cli + 不支持 runner，即便 env 有 agy
    # 也不该误报 active（否则执行期 _run_backend_for_config 仍会崩）。
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    from ming_sim import cli_backend
    from ming_sim.models import LLMConfig

    cfg = LLMConfig(api_key="cli-backend", base_url="", model="", channel="cli", cli_runner="bogus")

    assert cli_backend.cli_backend_active(cfg) is False
```

## [95] tests/test_runtime_llm_config.py:443 `test_cli_backend_active_total_on_unsupported_runner`
flags=['private_helper_call_no_obs_token'] lines=9
```
def test_cli_backend_active_total_on_unsupported_runner(monkeypatch):
    # ship-pre CMR Group F：不支持的 runner 不该让守卫崩（应判 not-active，不抛 RuntimeError）。
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    from ming_sim import cli_backend
    from ming_sim.models import LLMConfig

    cfg = LLMConfig(api_key="cli-backend", base_url="", model="", channel="cli", cli_runner="bogus")

    assert cli_backend.cli_backend_active(cfg) is False
```

## [96] tests/test_runtime_llm_config.py:454 `test_create_chat_model_unsupported_cli_runner_raises_unavailable`
flags=['private_helper_call_no_obs_token'] lines=13
```
def test_create_chat_model_unsupported_cli_runner_raises_unavailable(monkeypatch):
    # ship-pre CMR round-3：显式不支持的 CLI runner 在构造期优雅抛 LLMUnavailable，
    # 而非返回 CliChat、等首次 invoke 才 raw RuntimeError。
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    import pytest as _pytest
    from ming_sim.llm_model import create_chat_model
    from ming_sim.exceptions import LLMUnavailable
    from ming_sim.models import LLMConfig

    cfg = LLMConfig(api_key="cli-backend", base_url="", model="x", channel="cli", cli_runner="bogus")

    with _pytest.raises(LLMUnavailable):
        create_chat_model(cfg)
```

## [97] tests/test_runtime_llm_config.py:469 `test_for_role_advanced_drops_placeholder_key`
flags=['private_helper_call_no_obs_token'] lines=13
```
def test_for_role_advanced_drops_placeholder_key():
    # ship-pre CMR round-4：advanced_api_key 占位符不该泄漏到 advanced 角色的 OpenAI client。
    from ming_sim.llm_config import for_role
    from ming_sim.models import LLMConfig

    cfg = LLMConfig(
        api_key="sk-main", base_url="https://api.x/v1", model="m",
        advanced_model="gpt-adv", advanced_api_key="cli-backend", channel="api",
    )
    adv = for_role(cfg, "simulator")

    assert adv.api_key == "sk-main"
    assert adv.api_key != "cli-backend"
```

## [98] tests/test_runtime_llm_config.py:542 `test_runtime_llm_transport_nonpositive_falls_back_to_defaults`
flags=['private_helper_call_no_obs_token'] lines=49
```
def test_runtime_llm_transport_nonpositive_falls_back_to_defaults(tmp_path, monkeypatch):
    """#1465 fo2Nb / #1792：预算非正数（0/负）回落 typed 默认，不进空 range/即死预算。

    静默判死阈值同理，且它的真源是设置页那一格（cli.timeout_seconds）——坏值回落
    CLI_DEFAULT_TIMEOUT_SECONDS。
    """
    from ming_sim.llm_transport import transport_policy_from_mapping
    from ming_sim.models import (
        CLI_DEFAULT_TIMEOUT_SECONDS,
        TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS,
        TRANSPORT_DEFAULT_MAX_ATTEMPTS,
        TRANSPORT_DEFAULT_RETRY_INTERVAL_SECONDS,
    )

    path = tmp_path / "runtime_llm.json"
    path.write_text(json.dumps({
        "channel": "cli",
        "api": {"base_url": "https://x/v1", "model": "m", "api_key": "sk-x"},
        "cli": {"runner": "codex", "model": "gpt-5.5", "timeout_seconds": 0},
        "transport": {
            "max_attempts": 0,
            "attempt_timeout_seconds": -1,
            "retry_interval_seconds": 0,
        },
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))
    out = llm_config.load_runtime_llm()
    assert out["transport"]["max_attempts"] == TRANSPORT_DEFAULT_MAX_ATTEMPTS
    assert out["transport"]["attempt_timeout_seconds"] == TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS
    assert out["transport"]["retry_interval_seconds"] == TRANSPORT_DEFAULT_RETRY_INTERVAL_SECONDS
    policy = transport_policy_from_mapping(out)
    assert policy.max_attempts == TRANSPORT_DEFAULT_MAX_ATTEMPTS
    assert policy.attempt_timeout_seconds == TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS
    assert policy.retry_interval_seconds == TRANSPORT_DEFAULT_RETRY_INTERVAL_SECONDS
    assert policy.idle_timeout_seconds == CLI_DEFAULT_TIMEOUT_SECONDS
    # 保存路径同样经单权威：显式 0 不得落盘为 0
    llm_config.save_runtime_llm(
        base_url="https://x/v1",
        model="m",
        api_key="sk-x",
        channel="api",
        transport_max_attempts=0,
        transport_attempt_timeout_seconds=0.0,
        transport_retry_interval_seconds=0.0,
    )
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["transport"]["max_attempts"] == TRANSPORT_DEFAULT_MAX_ATTEMPTS
    assert saved["transport"]["attempt_timeout_seconds"] == TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS
    assert saved["transport"]["retry_interval_seconds"] == TRANSPORT_DEFAULT_RETRY_INTERVAL_SECONDS
```

## [99] tests/test_session_write_queue_1353.py:475 `test_get_session_write_queue_wiring_fail_loud_no_broad_swallow`
flags=['private_helper_call_no_obs_token'] lines=20
```
def test_get_session_write_queue_wiring_fail_loud_no_broad_swallow():
    """WebGame/session 共享同一写入队列。"""
    from ming_sim.session_write_queue import get_session_write_queue

    class _Sess:
        pass

    class _Owner:
        def __init__(self) -> None:
            self.session = _Sess()

    owner = _Owner()
    q1 = get_session_write_queue(owner)
    q2 = get_session_write_queue(owner)
    q3 = get_session_write_queue(owner.session)
    assert q1 is q2 is q3
    assert owner._write_queue is q1
    assert owner.session._write_queue is q1
    assert owner._write_gate is q1.write_gate
    assert owner.session._write_gate is q1.write_gate
```

## [100] tests/test_settlement_write_guard_393.py:133 `test_directive_capture_runs_outside_write_gate`
flags=['private_helper_call_no_obs_token'] lines=45
```
def test_directive_capture_runs_outside_write_gate(
    monkeypatch, operation,
):
    """capture 在写闸外执行：闸内可另写；API 可见结果落草案响应。"""
    import ming_sim.cli_backend as cli_backend

    game = _FakeGame(TurnPhase.SUMMONING.value)
    payload = {
        "dossier_action_type": "policy",
        "target_kind": "issue", "target_id": "land-survey",
    }

    captured_context = []

    def capture(text, llm_config, **context):
        captured_context.append(context)
        with web_app._serialized_web_write(game):
            game.db.writes.append("unrelated-write")
        return payload

    game.session.llm_config = SimpleNamespace()
    game.session.add_directive = lambda text, notes, dossier_payload: (
        SimpleNamespace(id=8, text=text, status="draft")
    )
    game.session.update_directive = (
        lambda directive_id, text, dossier_payload: None
    )
    monkeypatch.setattr(cli_backend, "capture_manual_directive_payload", capture)
    monkeypatch.setattr(web_app, "get_game", lambda: game)

    if operation == "create":
        body = _invoke(web_app.api_create_directive(
            web_app.DirectiveRequest(text="清丈田亩"),
        ))
        assert body["directive"]["id"] == 8
        assert body["directive"]["text"] == "清丈田亩"
        assert body["directive"]["status"] == "draft"
    else:
        body = _invoke(web_app.api_update_directive(
            7, web_app.DirectivePatch(text="重定清丈田亩"),
        ))
        assert "directives" in body
        assert captured_context[0]["existing_mode"] == "midzhi"
    # 闸契约：capture 期间能完成另一次串行写（证明不在占用写闸时抽取）
    assert game.db.writes == ["unrelated-write"]
```

## [101] tests/test_state_reload.py:298 `test_atomic_and_reload_reloads_and_reraises_at_depth0`
flags=['private_helper_call_no_obs_token'] lines=13
```
def test_atomic_and_reload_reloads_and_reraises_at_depth0(game):
    """最外层 body 抛错：回滚后 reload 刷净内存，原异常透传。"""
    from ming_sim.decree import atomic_and_reload
    db, state, content = game
    state.metrics["国库"] = 999999  # 脏内存
    with pytest.raises(RuntimeError, match="boom"):
        with atomic_and_reload(db, state, content=content):
            db.conn.execute("UPDATE metrics SET value = 7 WHERE key = '国库'")
            raise RuntimeError("boom")
    # 回滚 + reload：内存与 DB 同源，脏值被刷掉
    fresh = db.load_state()
    assert state.metrics == fresh.metrics
    assert state.metrics["国库"] != 999999
```

## [102] tests/test_structured_decree_contract_1624.py:128 `test_shared_validate_rejects_region_id_and_category_holes`
flags=['private_helper_call_no_obs_token'] lines=78
```
def test_shared_validate_rejects_region_id_and_category_holes(game, monkeypatch):
    """共同 assemble/validate 最低可证层：钉原洞 typed 拒绝。

    class1 原洞 = 非 region + national 夹带 region_id（旧闸只拒 scope==none）；
    class2 原洞 = 非 assignment 非空非法类别（旧闸闭集只罩 assignment）；
    action_alias_conflict = action_type 与 dossier_action_type 双非空且不同。
    #1778：动作×national 白名单已取消，national 只受 8×3 矩阵约束。
    """
    from ming_sim import cli_backend as cb

    db, state, content = game

    def create(payload):
        data = {
            **payload, "拟旨意图": "拟旨", "动作类型": payload["action_type"],
            "目标类型": payload["target_kind"], "目标ID": payload["target_id"],
            "地区ID": payload.get("region_id", ""), "事务类别": payload.get("transaction_category", ""),
            "施行范围": payload.get("locality_scope", "none"), "颁布方式": "普通",
            "承办人": payload.get("assignee", ""), "参与人": [dict(item) for item in _OWNER_ROSTER],
            "期限月数": 3,
        }
        monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: (json.dumps(data), 1))
        return cb.extract_draft_intent_with_roster_heal("拟旨", "准入样本", db=db, content=content)

    with pytest.raises(StructuredDecreeCombinationError):
        create({
            "action_type": "policy",
            "target_kind": "policy",
            "target_id": "x",
            "locality_scope": "national",
            "region_id": "shaanxi",
        })
    with pytest.raises(StructuredDecreeCombinationError):
        create({
            "action_type": "military_order",
            "target_kind": "army",
            "target_id": "xuanfu",
            "locality_scope": "none",
            "assignee_name": "祖大寿",
            "transaction_category": "INVALID",
        })
    with pytest.raises(StructuredDecreeCombinationError):
        create({
            "action_type": "punishment",
            "target_kind": "character",
            "target_id": "毕自严",
            "locality_scope": "none",
            "transaction_category": "INVALID",
        })
    # 双非空动作身份冲突：默认 validate 入口 typed 拒绝，failed_fields 含两键
    with pytest.raises(StructuredDecreeCombinationError) as ei:
        create({
            "action_type": "assignment",
            "dossier_action_type": "policy",
            "target_kind": "policy",
            "target_id": "x",
            "locality_scope": "none",
            "transaction_category": "督赈",
        })
    assert ei.value.failed_fields == frozenset(
        {"action_type", "dossier_action_type"}
    )
    # 同值或一侧空：维持现状（不因 alias 比较误伤）
    same = create({
        "action_type": "policy",
        "dossier_action_type": "policy",
        "target_kind": "policy",
        "target_id": "x",
        "locality_scope": "none",
    })
    assert same["action_type"] == "policy"
    only_action = create({
        "action_type": "policy",
        "target_kind": "policy",
        "target_id": "x",
        "locality_scope": "none",
    })
    assert only_action["action_type"] == "policy"
```

## [103] tests/test_verify_llm_clocks_884.py:164 `test_cli_channel_does_not_smoke_retained_api_advanced_slot`
flags=['private_helper_call_no_obs_token'] lines=27
```
def test_cli_channel_does_not_smoke_retained_api_advanced_slot(monkeypatch):
    """CLI 通道只验当前 CLI 主槽；保留的 API advanced 槽不另起一腿。"""
    seen: list[LLMConfig] = []

    def fake_verify(cfg, **_k):
        seen.append(cfg)

    monkeypatch.setattr(web_app, "verify_llm_available", fake_verify)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-main",
        advanced_model="gpt-advanced",
        advanced_base_url="https://adv.example.com/v1",
        advanced_api_key="sk-adv",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-cli",
    )
    web_app._verify_llm_configs_or_raise(cfg)
    assert len(seen) == 1
    assert seen[0].channel == "cli"
    assert seen[0].cli_model == "gpt-cli"
    assert seen[0].model != "gpt-advanced"
    assert cfg.advanced_model == "gpt-advanced"
    assert cfg.advanced_api_key == "sk-adv"
    assert cfg.advanced_base_url == "https://adv.example.com/v1"
```

## [104] tests/test_web_llm_runtime_config.py:17 `test_advanced_llm_verification_preserves_api_channel_over_backend_env`
flags=['private_helper_call_no_obs_token'] lines=15
```
def test_advanced_llm_verification_preserves_api_channel_over_backend_env(monkeypatch):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    seen = []
    monkeypatch.setattr(web_app, "verify_llm_available", lambda cfg: seen.append(cfg))
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-main",
        advanced_model="gpt-advanced",
        channel="api",
    )

    web_app._verify_llm_configs_or_raise(cfg)

    assert [item.channel for item in seen] == ["api", "api"]
```

## [105] tests/test_web_llm_runtime_config.py:34 `test_advanced_llm_verification_preserves_reasoning_strength`
flags=['private_helper_call_no_obs_token'] lines=19
```
def test_advanced_llm_verification_preserves_reasoning_strength(monkeypatch):
    seen = []
    monkeypatch.setattr(web_app, "verify_llm_available", lambda cfg: seen.append(cfg))
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-main",
        advanced_model="gpt-advanced",
        channel="api",
        reasoning_strength="high",
        advanced_thinking_level="minimal",
    )

    web_app._verify_llm_configs_or_raise(cfg)

    by_model = {item.model: item for item in seen}
    assert by_model["gpt-main"].reasoning_strength == "high"
    assert by_model["gpt-advanced"].reasoning_strength == "high"
    assert by_model["gpt-advanced"].thinking_level == ""
```
