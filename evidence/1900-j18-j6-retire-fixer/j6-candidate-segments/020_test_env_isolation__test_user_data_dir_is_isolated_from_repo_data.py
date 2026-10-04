def test_user_data_dir_is_isolated_from_repo_data():
    from ming_sim.paths import user_data_dir

    assert os.environ.get("MING_SIM_USER_DATA_DIR"), "autouse 兜底未生效"
    repo_data = Path(__file__).resolve().parent.parent / "data"
    assert Path(str(user_data_dir())).resolve() != repo_data.resolve()
