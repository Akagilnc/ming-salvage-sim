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
