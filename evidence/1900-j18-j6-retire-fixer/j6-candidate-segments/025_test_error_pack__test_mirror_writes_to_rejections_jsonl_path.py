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
