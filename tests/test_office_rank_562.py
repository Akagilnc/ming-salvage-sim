import json

from ming_sim.office_rank import (
    canonical_office_title,
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
    # #1843：离事且无现职不建空备档；无 archive 时按初仕高阶识别（不锁 status_reason 反推职衔）。
    _yuan_id, yuan = _appointment_dossier(db, state, "袁可立", "陕西巡抚")
    assert yuan["break_rank"]["basis"] == "first_appointment_high_office"
    assert yuan["break_rank"]["is_break_rank"] is True

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








def test_recognizable_archive_title_survives_blank_or_legacy_office_type(game):
    """旧档 office_type 待铨/空时，任命案卷仍按历史实职识别破格（公开 break_rank）。"""
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


def test_seed_archives_clean_historical_office_for_dismissed_ministers(game):
    """#1843：离事且无现职不建空备档；起复按初仕高阶，不从 status_reason 反推职衔。"""
    db, _state, _content = game
    for name in ("袁可立", "胡廷宴"):
        row = db.conn.execute(
            "SELECT office_title FROM character_offices WHERE character_name=?",
            (name,),
        ).fetchone()
        assert row is None

    _dossier_id, payload = _appointment_dossier(db, _state, "袁可立", "陕西巡抚")
    assert payload["break_rank"]["basis"] == "first_appointment_high_office"
    assert payload["break_rank"]["is_break_rank"] is True

    _hid, hu_payload = _appointment_dossier(db, _state, "胡廷宴", "三边总督")
    assert hu_payload["break_rank"]["basis"] == "first_appointment_high_office"
    assert hu_payload["break_rank"]["is_break_rank"] is True
