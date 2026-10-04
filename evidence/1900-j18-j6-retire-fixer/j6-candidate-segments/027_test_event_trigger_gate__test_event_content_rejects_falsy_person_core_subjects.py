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
