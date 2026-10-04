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
