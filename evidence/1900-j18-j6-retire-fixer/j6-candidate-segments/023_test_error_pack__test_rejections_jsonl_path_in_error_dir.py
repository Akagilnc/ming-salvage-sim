def test_rejections_jsonl_path_in_error_dir(monkeypatch, tmp_path):
    """拒收 jsonl 与错误包集中同一 user-data 错误目录（决定 7：一次打包全带走）。"""
    from ming_sim.error_pack import error_packs_root, rejections_jsonl_path
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))

    jsonl = Path(rejections_jsonl_path())
    assert jsonl.parent == error_packs_root()
    assert jsonl.name == "rejections.jsonl"
