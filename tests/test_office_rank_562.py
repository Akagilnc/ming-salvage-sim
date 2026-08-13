import json
from pathlib import Path

from ming_sim.office_rank import (
    canonical_office_title,
    office_leverage_multiplier,
    office_rank_band,
)
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
    table = json.loads(
        (Path(__file__).resolve().parent.parent / "content" / "offices.json").read_text(
            encoding="utf-8"
        )
    )
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
    assert office_leverage_multiplier("") == 1.0
    assert dbmod._office_rank_multiplier("") == 1.0
    assert office_leverage_multiplier("副总兵") == 0.5
    assert office_leverage_multiplier("总兵") == 1.0
    assert office_leverage_multiplier("礼部尚书,东阁大学士") == 1.0
    assert dbmod._office_rank_multiplier("副总兵") == office_leverage_multiplier("副总兵")
    assert dbmod._office_rank_multiplier("礼部尚书,东阁大学士") == office_leverage_multiplier(
        "礼部尚书,东阁大学士"
    )


def test_unofficed_and_offstage_degree_labels_are_genuine_first_appointments(game):
    db, state, _content = game
    for index, (office, office_type, status) in enumerate((
        ("贡生", "生员", "active"),
        ("诸生（应天府学）", "未仕", "offstage"),
        ("泉州童子（郑芝龙子）", "未仕", "offstage"),
    )):
        name = f"初仕{index}"
        _add(db, state, name, office, office_type)
        db.conn.execute("UPDATE characters SET status=? WHERE name=?", (status, name))
        _dossier_id, payload = _appointment_dossier(db, state, name, "翰林院编修")
        assert payload["break_rank"]["basis"] == "first_appointment_regular"
        assert payload["break_rank"]["is_break_rank"] is False


def test_historical_military_commands_and_cabinet_fallback_use_nominal_bands():
    assert office_rank_band("都指挥使") < office_rank_band("指挥使")
    assert office_rank_band("不常见阁衔", "内阁") == 5


def test_one_tokenizer_preserves_real_concurrent_offices_and_drops_only_pollution():
    title = "原任东阁大学士兼礼部尚书、左都御史，罢居松江"
    assert canonical_office_title(title) == "东阁大学士,礼部尚书,左都御史"
    assert office_rank_band(title) == 2
    assert office_leverage_multiplier(title) == 1.0
    assert office_rank_band("礼部尚书兼东阁大学士") == 2


def test_leverage_uses_min_modifiers_within_title_and_max_across_offices():
    assert office_leverage_multiplier("候补总兵") == 0.25
    assert office_leverage_multiplier("候用副总兵") == 0.25
    assert office_leverage_multiplier("候补总兵,礼部侍郎") == 0.5
    assert office_leverage_multiplier("陌生卫指挥") == 1.0


def test_existing_proposed_appointment_dossier_gets_one_time_break_rank_backfill(game):
    db, state, content = game
    _add(db, state, "旧案白身", "白身", "布衣")
    dossier_id, _payload = _appointment_dossier(db, state, "旧案白身", "陕西巡抚")
    row = db.conn.execute(
        "SELECT payload_json FROM decree_dossiers WHERE id=?", (dossier_id,)
    ).fetchone()
    payload = json.loads(row["payload_json"])
    payload.pop("break_rank")
    db.conn.execute(
        "UPDATE decree_dossiers SET payload_json=? WHERE id=?",
        (json.dumps(payload, ensure_ascii=False), dossier_id),
    )
    path = db.path
    db.close()

    from ming_sim.db import GameDB
    reopened = GameDB(path, content)
    try:
        migrated = json.loads(reopened.conn.execute(
            "SELECT payload_json FROM decree_dossiers WHERE id=?", (dossier_id,)
        ).fetchone()["payload_json"])
        assert migrated["break_rank"]["basis"] == "first_appointment_high_office"
        first_json = json.dumps(migrated, ensure_ascii=False, sort_keys=True)
        reopened.close()
        reopened = GameDB(path, content)
        again = json.loads(reopened.conn.execute(
            "SELECT payload_json FROM decree_dossiers WHERE id=?", (dossier_id,)
        ).fetchone()["payload_json"])
        assert json.dumps(again, ensure_ascii=False, sort_keys=True) == first_json
    finally:
        reopened.close()


def test_recognizable_archive_title_survives_blank_or_legacy_office_type(game):
    from ming_sim.office_rank import _is_substantive_office

    assert _is_substantive_office("翰林院编修", "")
    db, state, _content = game
    name = "旧档实职"
    _add(db, state, name, "翰林院编修", "翰林院")
    db.set_character_status(state, name, "retired", "致仕")
    db.conn.execute(
        "UPDATE character_offices SET office_type='待铨' WHERE character_name=?", (name,)
    )
    _dossier_id, payload = _appointment_dossier(db, state, name, "兵部尚书")
    assert payload["break_rank"]["basis"] == "historical_office"
    assert payload["break_rank"]["is_break_rank"] is True


def test_rank_rule_offset_reanchor_preserves_existing_save_leverage_once(game):
    db, _state, content = game
    overflow_faction = "东林"
    ordinary_faction = "皇党"
    ordinary_row = db.conn.execute(
        "SELECT leverage, leverage_offset FROM factions WHERE name=?",
        (ordinary_faction,),
    ).fetchone()
    ordinary_leverage = int(ordinary_row["leverage"])
    old_offset = float(ordinary_row["leverage_offset"] or 0)
    legacy_old_sum = db._rank_rules_562_legacy_weight_sum(ordinary_faction)
    ordinary_raw_baseline = old_offset + legacy_old_sum
    ordinary_visible_baseline = max(0, min(100, round(ordinary_raw_baseline)))

    # Model an old-rules save whose raw value overflowed and was persisted clamped.
    # The raw 125 baseline lives only in offset + old weight sum, never in leverage=100.
    overflow_old_sum = db._rank_rules_562_legacy_weight_sum(overflow_faction)
    overflow_old_offset = 125.0 - overflow_old_sum
    db.conn.execute(
        "UPDATE factions SET leverage=100, leverage_offset=? WHERE name=?",
        (overflow_old_offset, overflow_faction),
    )
    db.conn.execute("DELETE FROM metrics WHERE key='__leverage_offsets_rank_rules_562'")
    db.conn.commit()
    path = db.path
    db.close()

    from ming_sim.db import GameDB
    reopened = GameDB(path, content)
    try:
        assert reopened._has_meta_flag("__leverage_offsets_rank_rules_562")
        migrated_offset = float(reopened.conn.execute(
            "SELECT leverage_offset FROM factions WHERE name=?", (overflow_faction,)
        ).fetchone()["leverage_offset"])
        current_sum = reopened._faction_office_weight_sum(overflow_faction)
        assert migrated_offset + current_sum == 125.0
        ordinary_new_offset = float(reopened.conn.execute(
            "SELECT leverage_offset FROM factions WHERE name=?", (ordinary_faction,)
        ).fetchone()["leverage_offset"])
        ordinary_current_sum = reopened._faction_office_weight_sum(ordinary_faction)
        assert ordinary_new_offset + ordinary_current_sum == ordinary_raw_baseline
        assert int(reopened.conn.execute(
            "SELECT leverage FROM factions WHERE name=?", (ordinary_faction,)
        ).fetchone()["leverage"]) == ordinary_leverage

        reopened.recompute_all_faction_leverage()
        assert int(reopened.conn.execute(
            "SELECT leverage FROM factions WHERE name=?", (overflow_faction,)
        ).fetchone()["leverage"]) == 100
        assert int(reopened.conn.execute(
            "SELECT leverage FROM factions WHERE name=?", (ordinary_faction,)
        ).fetchone()["leverage"]) == ordinary_visible_baseline

        # A later office change is absorbed by the preserved overflow rather than
        # incorrectly dropping from a baseline reconstructed from clamped 100.
        member = reopened.conn.execute(
            "SELECT name FROM characters WHERE faction=? AND status='active' "
            "AND power_id='ming' AND office<>'' LIMIT 1",
            (overflow_faction,),
        ).fetchone()
        assert member is not None
        reopened.conn.execute("UPDATE characters SET office='' WHERE name=?", (member["name"],))
        changed_sum = reopened._faction_office_weight_sum(overflow_faction)
        reopened.recompute_faction_leverage(overflow_faction)
        changed_raw = 125.0 + changed_sum - current_sum
        assert 100 < changed_raw < 125.0
        assert int(reopened.conn.execute(
            "SELECT leverage FROM factions WHERE name=?", (overflow_faction,)
        ).fetchone()["leverage"]) == 100

        offsets = {row["name"]: float(row["leverage_offset"]) for row in reopened.conn.execute(
            "SELECT name,leverage_offset FROM factions"
        ).fetchall()}
        reopened.conn.commit()
        reopened.close()
        reopened = GameDB(path, content)
        assert {row["name"]: float(row["leverage_offset"]) for row in reopened.conn.execute(
            "SELECT name,leverage_offset FROM factions"
        ).fetchall()} == offsets
    finally:
        reopened.close()


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
