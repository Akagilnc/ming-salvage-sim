"""#1832 S2：按职位裁切衙门底账、密令黑名单、递话人同规则。

Seams: prepare_character_materials (directory contents),
build_mindreading_materials (递话人材料，不含目标真值).
"""

from __future__ import annotations

from dataclasses import replace

from ming_sim.materials import (
    list_materials,
    prepare_character_materials,
    read_material,
)
from ming_sim.mindreading import build_mindreading_materials
from ming_sim.public_sayings import record_public_saying
from tests.dossier_test_helpers import create_test_secret_order


def _blob(prepared) -> str:
    return "\n".join(
        read_material(prepared.root, path)
        for path in list_materials(prepared.root)
        if path != "INDEX.txt"
    )


def _office_archive(prepared, name: str) -> str:
    return read_material(prepared.root, f"人物/{name}/公事档案.txt")


def _experience(prepared, name: str) -> str:
    return read_material(prepared.root, f"人物/{name}/经历.txt")


def _by_office(content, office_type: str):
    return next(
        c for c in content.characters.values() if c.office_type == office_type
    )


def test_household_reads_taicang_war_reads_register_cabinet_only_reports_and_dossiers(
    game, tmp_path,
):
    db, state, content = game
    household = content.characters["毕自严"]
    war = content.characters["崔呈秀"]
    cabinet = _by_office(content, "内阁")
    personnel = _by_office(content, "吏部")
    treasury = db.treasury_report(state)
    armies = db.army_report(limit=30)
    roster = db.current_court_roster_rows(state)
    assert treasury
    assert "建档兵力合计" in armies
    assert roster

    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="SENTINEL_CABINET_DOSSIER_1832",
        target_kind="issue", target_id="validation",
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    record_public_saying(db, state, "SENTINEL_PUBLIC_REPORT_1832")

    house_dir = prepare_character_materials(
        db, state, household, dest_root=tmp_path / "house",
    )
    war_dir = prepare_character_materials(
        db, state, war, dest_root=tmp_path / "war",
    )
    cab_dir = prepare_character_materials(
        db, state, cabinet, dest_root=tmp_path / "cab",
    )
    person_dir = prepare_character_materials(
        db, state, personnel, dest_root=tmp_path / "person",
    )
    house_archive = _office_archive(house_dir, household.name)
    war_archive = _office_archive(war_dir, war.name)
    cab_archive = _office_archive(cab_dir, cabinet.name)
    person_archive = _office_archive(person_dir, personnel.name)
    cab_blob = _blob(cab_dir)

    assert treasury.strip() in house_archive
    assert armies.strip() not in house_archive
    assert "建档兵力合计" in war_archive
    assert treasury.strip() not in war_archive
    assert treasury.strip() not in cab_archive
    assert armies.strip() not in cab_archive
    assert "SENTINEL_CABINET_DOSSIER_1832" in cab_archive
    assert "SENTINEL_PUBLIC_REPORT_1832" in cab_blob
    assert "任免簿" in person_archive
    assert roster[0]["name"] in person_archive
    assert treasury.strip() not in person_archive
    assert armies.strip() not in person_archive


def test_secret_blacklist_vetoes_directory_over_public_and_office_bucket(game, tmp_path):
    db, state, content = game
    hidden = _by_office(content, "礼部")
    knower = content.characters["毕自严"]
    marker = "SENTINEL_BLACKLIST_MATTER_1832"
    order = create_test_secret_order(
        db, state, knower.name, "暗查亏空", marker, [],
        excluded_names=[hidden.name],
    )
    db.record_public_knowledge_event(
        state, "密事公开层", marker, source_id=f"secret_order:{order}",
    )

    hidden_blob = _blob(prepare_character_materials(
        db, state, hidden, dest_root=tmp_path / "hidden",
    ))
    knower_blob = _blob(prepare_character_materials(
        db, state, knower, dest_root=tmp_path / "knower",
    ))
    assert marker not in hidden_blob
    assert marker in knower_blob


def test_messenger_knows_yuan_death_only_as_public_saying_without_target_truths(
    game, tmp_path,
):
    db, state, content = game
    messenger = content.characters["王承恩"]
    target = content.characters["袁崇焕"]
    private_truth = "SENTINEL_YUAN_PRIVATE_TRUTH_1832"
    public_body = "袁崇焕已死于宁远"
    db.set_character_status(state, target.name, "dead", "伏法")
    db.record_character_participation(
        state, ["温体仁"], "witness", "密闻死讯", private_truth,
    )
    record_public_saying(
        db, state, public_body, involved_characters=[target.name],
    )
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="SENTINEL_ATTENDANT_DOSSIER_1832",
        target_kind="issue", target_id="validation",
    )
    db.record_dossier_decision(dossier_id, "promulgated")

    prepared = prepare_character_materials(
        db, state, messenger, dest_root=tmp_path / "messenger",
    )
    blob = _blob(prepared)
    assert public_body in blob
    assert private_truth not in blob
    assert private_truth not in _experience(prepared, messenger.name)

    materials = build_mindreading_materials(
        db, state, messenger, content.characters["温体仁"], "臣有本奏。",
    )
    archive = _office_archive(prepared, messenger.name)
    office = materials["reader_context"]["公事档案"]
    assert "SENTINEL_ATTENDANT_DOSSIER_1832" in archive
    assert office.strip() == archive.strip()
    assert "SENTINEL_ATTENDANT_DOSSIER_1832" in office
    assert "truths" not in materials
    dumped = str(materials)
    assert "对君的真心" not in dumped
    assert "名义党派" not in dumped
    assert "底案留有" not in dumped
    assert "seed_guilt" not in dumped
    assert "loyalty" not in dumped


def test_attendant_moved_to_court_office_keeps_dossiers_not_faction_truth(
    game, tmp_path,
):
    db, state, content = game
    previous_live = content.characters["王承恩"]
    messenger_live = content.characters["曹化淳"]
    previous = replace(
        previous_live, office=previous_live.office, office_type=previous_live.office_type,
    )
    messenger = replace(
        messenger_live, office=messenger_live.office, office_type=messenger_live.office_type,
    )
    db.set_character_office(previous.name, "内廷随侍", "内廷")
    db.set_character_office(messenger.name, "御前近臣", "内廷")
    assert db.conn.execute(
        "SELECT office_type FROM characters WHERE name=?", (previous.name,),
    ).fetchone()["office_type"] == "内廷"
    from ming_sim.mindreading import current_inner_court_attendant_name, is_inner_court_attendant
    assert not is_inner_court_attendant(messenger)
    assert is_inner_court_attendant(previous)
    assert current_inner_court_attendant_name(db) == messenger.name
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="SENTINEL_COURT_ATTENDANT_DOSSIER_1832",
        target_kind="issue", target_id="validation",
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    faction = db.faction_report(audience=True)
    assert "皇党" in faction

    prepared = prepare_character_materials(
        db, state, messenger, dest_root=tmp_path / "court-attendant",
    )
    archive = _office_archive(prepared, messenger.name)
    materials = build_mindreading_materials(
        db, state, messenger, content.characters["温体仁"], "臣有本奏。",
    )
    office = materials["reader_context"]["公事档案"]
    assert "SENTINEL_COURT_ATTENDANT_DOSSIER_1832" in archive
    assert office.strip() == archive.strip()
    assert faction not in archive
    assert faction not in office
    assert "court：" not in archive
    dumped = str(materials)
    assert "皇党" not in dumped
    assert "truths" not in materials
    previous_archive = _office_archive(
        prepare_character_materials(
            db, state, previous, dest_root=tmp_path / "former-attendant",
        ),
        previous.name,
    )
    assert faction in previous_archive
    assert "court：" in previous_archive


def test_successor_reads_office_archive_not_predecessor_private(game, tmp_path):
    db, state, content = game
    predecessor = content.characters["郭允厚"]
    successor = _by_office(content, "礼部")
    private = "SENTINEL_PRED_PRIVATE_1832"
    db.record_character_participation(
        state, [predecessor.name], "audience", "前任私密交代", private,
    )
    db.set_character_office(successor.name, "户部尚书", "户部")
    treasury = db.treasury_report(state)

    succ_dir = prepare_character_materials(
        db, state, successor, dest_root=tmp_path / "succ",
    )
    pred_dir = prepare_character_materials(
        db, state, predecessor, dest_root=tmp_path / "pred",
    )
    succ_archive = _office_archive(succ_dir, successor.name)
    succ_exp = _experience(succ_dir, successor.name)
    pred_exp = _experience(pred_dir, predecessor.name)

    assert treasury.strip() in succ_archive
    assert private not in succ_exp
    assert private not in succ_archive
    assert private in pred_exp
