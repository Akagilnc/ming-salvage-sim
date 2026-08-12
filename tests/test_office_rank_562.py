import json

from ming_sim.office_rank import office_leverage_multiplier, office_rank_band
from ming_sim.models import Character


def _add(db, state, name, office, office_type):
    db.add_character(state, Character(
        name=name, office=office, office_type=office_type, faction="中立",
        aliases=[], personal_skills=[], loyalty=50, ability=50, integrity=50,
        courage=50, style="", power_id="ming",
    ))


def _appointment_dossier(db, state, name, office, office_type=""):
    payload = {"name": name, "office": office}
    if office_type:
        payload["office_type"] = office_type
    dossier_id = db.create_decree_dossier(
        state,
        action_type="appointment",
        decree_text=f"任命{name}为{office}",
        target_kind="character",
        target_id=name,
        payload=payload,
    )
    row = db.conn.execute(
        "SELECT * FROM decree_dossiers WHERE id=?", (dossier_id,)
    ).fetchone()
    return dossier_id, json.loads(row["payload_json"])


def test_rank_table_covers_every_office_type_and_pins_ming_direction():
    table = json.loads(open("content/offices.json", encoding="utf-8").read())
    assert {row["type"] for row in table["priority"]} | {table["fallback"]["type"]} == set(table["allowed_types"])
    assert all(1 <= row["rank_band"] <= 9 for row in [*table["priority"], table["fallback"]])
    assert office_rank_band("兵部尚书") == 2
    assert office_rank_band("翰林院编修") == 7
    assert office_rank_band("待铨") == 9


def test_white_body_high_appointment_is_marked_but_regular_first_office_is_not(game):
    db, state, _content = game
    _add(db, state, "白身甲", "白身", "布衣")
    high_id, high = _appointment_dossier(db, state, "白身甲", "陕西巡抚")
    assert high["break_rank"] == {
        "is_break_rank": True, "basis": "first_appointment_high_office",
        "new_rank_band": 3, "threshold_band": 4,
    }

    _add(db, state, "新科乙", "进士", "生员")
    _regular_id, regular = _appointment_dossier(db, state, "新科乙", "翰林院编修")
    assert regular["break_rank"]["is_break_rank"] is False
    assert regular["break_rank"]["basis"] == "first_appointment_regular"

    from ming_sim.decree import build_promulgation_judge_context

    context = build_promulgation_judge_context(
        db, state, [dict(db.conn.execute("SELECT * FROM decree_dossiers WHERE id=?", (high_id,)).fetchone())]
    )
    assert context["dossiers"][0]["break_rank"]["is_break_rank"] is True


def test_appointment_dossier_uses_declared_type_for_uncommon_target_title(game):
    db, state, _content = game
    for index, type_key in enumerate(("office_type", "new_office_type")):
        name = f"异衔{index}"
        _add(db, state, name, "白身", "布衣")
        dossier_id = db.create_decree_dossier(
            state,
            action_type="appointment",
            decree_text=f"任命{name}为钦定督理西务大臣",
            target_kind="character",
            target_id=name,
            payload={"name": name, "new_office": "钦定督理西务大臣", type_key: "边镇"},
        )
        row = db.conn.execute(
            "SELECT payload_json FROM decree_dossiers WHERE id=?", (dossier_id,)
        ).fetchone()
        payload = json.loads(row["payload_json"])

        assert payload["break_rank"]["new_rank_band"] == 5
        assert payload["break_rank"]["is_break_rank"] is False


def test_same_rank_demotion_and_two_band_promotion_follow_upward_formula(game):
    db, state, _content = game
    _add(db, state, "迁官甲", "礼部右侍郎", "礼部")
    _same_id, same = _appointment_dossier(db, state, "迁官甲", "户部左侍郎")
    assert same["break_rank"]["is_break_rank"] is False
    assert same["break_rank"]["current_rank_band"] == same["break_rank"]["new_rank_band"] == 3

    _up_id, up = _appointment_dossier(db, state, "迁官甲", "兵部尚书")
    assert up["break_rank"]["is_break_rank"] is False  # 3 - 2 is only one band

    db.set_character_office("迁官甲", "翰林院编修", "翰林院")
    _jump_id, jump = _appointment_dossier(db, state, "迁官甲", "兵部尚书")
    assert jump["break_rank"]["is_break_rank"] is True
    assert jump["break_rank"]["current_rank_band"] - jump["break_rank"]["new_rank_band"] >= 2

    db.set_character_office("迁官甲", "兵部尚书", "兵部")
    _down_id, down = _appointment_dossier(db, state, "迁官甲", "翰林院编修")
    assert down["break_rank"]["is_break_rank"] is False


def test_restoration_and_displaced_third_state_use_latest_historical_office(game):
    db, state, _content = game
    _yuan_id, yuan = _appointment_dossier(db, state, "袁可立", "陕西巡抚")
    assert yuan["break_rank"]["basis"] == "historical_office"
    assert yuan["break_rank"]["is_break_rank"] is False

    _add(db, state, "起复甲", "礼部右侍郎", "礼部")
    db.set_character_status(state, "起复甲", "retired", "致仕")
    _same_id, same = _appointment_dossier(db, state, "起复甲", "户部左侍郎")
    assert same["break_rank"]["basis"] == "historical_office"
    assert same["break_rank"]["is_break_rank"] is False
    assert same["break_rank"]["current_rank_band"] == 3

    _add(db, state, "候铨乙", "兵部尚书", "兵部")
    db.set_character_office("候铨乙", "听用候铨", "待铨")
    db.conn.execute("UPDATE characters SET reason_code='被顶替' WHERE name='候铨乙'")
    # Recreate the archived previous office, as displacement does in production.
    db.conn.execute(
        "UPDATE character_offices SET office_title='兵部尚书',office_type='兵部' WHERE character_name='候铨乙'"
    )
    _return_id, returned = _appointment_dossier(db, state, "候铨乙", "户部尚书")
    assert returned["break_rank"]["basis"] == "historical_office"
    assert returned["break_rank"]["is_break_rank"] is False

    # AC: 起复跳升 / 听用候铨跳升仍按 upward 公式（现职带−新职带≥2）打标。
    _jump_id, jumped = _appointment_dossier(db, state, "起复甲", "兵部尚书")
    assert jumped["break_rank"]["basis"] == "historical_office"
    assert jumped["break_rank"]["is_break_rank"] is False  # 3→2 only one band

    db.set_character_office("起复甲", "翰林院编修", "翰林院")
    db.set_character_status(state, "起复甲", "retired", "致仕")
    _big_id, big = _appointment_dossier(db, state, "起复甲", "兵部尚书")
    assert big["break_rank"]["basis"] == "historical_office"
    assert big["break_rank"]["is_break_rank"] is True
    assert big["break_rank"]["current_rank_band"] - big["break_rank"]["new_rank_band"] >= 2

    db.conn.execute(
        "UPDATE character_offices SET office_title='翰林院编修',office_type='翰林院' "
        "WHERE character_name='候铨乙'"
    )
    _disp_jump_id, disp_jump = _appointment_dossier(db, state, "候铨乙", "兵部尚书")
    assert disp_jump["break_rank"]["basis"] == "historical_office"
    assert disp_jump["break_rank"]["is_break_rank"] is True


def test_title_stems_keep_distinct_ming_bands_inside_same_office_type():
    """Owner #562: actual title/stem bands, not one representative band per type."""
    assert office_rank_band("兵部尚书") == 2
    assert office_rank_band("兵部侍郎") == 3
    assert office_rank_band("兵部郎中") == 5
    assert office_rank_band("兵部主事") == 6
    assert office_rank_band("副总兵") == 3
    assert office_rank_band("总兵") == 2
    assert office_rank_band("监察御史") == 7
    assert office_rank_band("少卿") == 4
    assert office_rank_band("前礼部右少卿,罢居上海") == 4
    # 边镇/地方/翰林 must not collapse to the category-wide priority.rank_band.
    assert office_rank_band("参将") == 4
    assert office_rank_band("千总") == 6
    assert office_rank_band("把总") == 7
    assert office_rank_band("经略") == 3
    assert office_rank_band("知州") == 5
    assert office_rank_band("兵备道") == 4
    assert office_rank_band("县令") == 7
    assert office_rank_band("侍读学士") == 5
    assert office_rank_band("修撰") == 6
    assert office_rank_band("皇后") == 1


def test_cabinet_titles_keep_nominal_ming_rank_instead_of_political_importance():
    """大学士是正五品；首辅/殿阁称谓不把政治权重冒充品秩。"""
    for title in (
        "大学士", "内阁大学士", "殿阁大学士", "东阁大学士", "文渊阁大学士",
        "武英殿大学士", "建极殿大学士", "中极殿大学士", "文华殿大学士",
        "内阁首辅", "内阁次辅", "辅臣", "阁臣",
    ):
        assert office_rank_band(title) == 5, title


def test_concurrent_cabinet_office_uses_the_genuinely_higher_title():
    assert office_rank_band("礼部尚书,东阁大学士") == 2
    assert office_rank_band("兵部侍郎,文华殿大学士") == 3
    # Decoration is not concurrency: the hall name cannot promote a 大学士 to band 1.
    assert office_rank_band("文华殿大学士") == 5


def test_qualified_titles_match_the_requested_axis_not_an_institutional_stem():
    assert office_rank_band("锦衣卫百户") == 6
    assert office_rank_band("翰林院检讨") == 8
    assert office_rank_band("司礼监随堂太监") == 7
    assert office_leverage_multiplier("翰林院编修") == 0.25
    assert office_leverage_multiplier("司礼监随堂太监") == 0.25


def test_leverage_multiplier_uses_canonical_office_rank_table_only():
    """AC: faction leverage consumes the same offices.json parser (full matrix in #9 suite)."""
    import ming_sim.db as dbmod

    # Thin cross-module seam only — full deputy/principal matrix lives in test_faction_leverage_9.
    assert office_leverage_multiplier("副总兵") == 0.5
    assert office_leverage_multiplier("总兵") == 1.0
    assert office_leverage_multiplier("礼部尚书,东阁大学士") == 1.0
    assert dbmod._office_rank_multiplier("副总兵") == office_leverage_multiplier("副总兵")
    assert dbmod._office_rank_multiplier("礼部尚书,东阁大学士") == office_leverage_multiplier(
        "礼部尚书,东阁大学士"
    )


def test_seed_archives_clean_historical_office_for_dismissed_ministers(game):
    db, _state, _content = game
    yuan = db.conn.execute(
        "SELECT office_title FROM character_offices WHERE character_name=?",
        ("袁可立",),
    ).fetchone()
    assert yuan is not None
    assert "巡抚" in yuan["office_title"]
    assert "罢居" not in yuan["office_title"]
    assert not yuan["office_title"].startswith("前")

    _dossier_id, payload = _appointment_dossier(db, _state, "袁可立", "陕西巡抚")
    assert payload["break_rank"]["basis"] == "historical_office"
    assert payload["break_rank"]["is_break_rank"] is False
    assert payload["break_rank"]["current_rank_band"] == 3

    # 革职候勘 / 原任 污染也须在 seed 备档洗净，供起复读最近实职带。
    hu = db.conn.execute(
        "SELECT office_title FROM character_offices WHERE character_name=?",
        ("胡廷宴",),
    ).fetchone()
    assert hu is not None
    assert hu["office_title"] == "三边总督"
    assert "革职" not in hu["office_title"]
    assert not hu["office_title"].startswith("原")
    _hid, hu_payload = _appointment_dossier(db, _state, "胡廷宴", "三边总督")
    assert hu_payload["break_rank"]["basis"] == "historical_office"
    assert hu_payload["break_rank"]["is_break_rank"] is False
    assert hu_payload["break_rank"]["current_rank_band"] == 3
