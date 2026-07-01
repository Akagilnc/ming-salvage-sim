from __future__ import annotations

import inspect
from pathlib import Path

from driver import run_settle
import ming_sim.tools as tools_mod


ROOT = Path(__file__).resolve().parents[1]


def test_ming_new_army_pay_source_contract_is_documented_across_extractor_surfaces():
    """#302 review fix: model-facing contracts must teach the required pay-source fields.

    Otherwise a prompt-following extractor can emit owner_power=ming new_armies that
    the new pay-source write guard rejects.
    """
    shared = (ROOT / "content/prompts/score_extractor_shared.md").read_text(encoding="utf-8")
    military = (ROOT / "content/prompts/score_extractor_military_external.md").read_text(
        encoding="utf-8"
    )
    submit_doc = inspect.getsource(tools_mod.build_extractor_tools)

    for surface_name, surface in {
        "shared extractor contract": shared,
        "military extractor prompt": military,
        "submit_extraction tool docs": submit_doc,
    }.items():
        assert "owner_power=\"ming\"" in surface, surface_name
        assert "pay_source_region" in surface, surface_name
        assert "province_pay_share" in surface, surface_name
        assert "central_pay_share" in surface, surface_name
        assert "饷源省" in surface, surface_name
        assert "省份额" in surface, surface_name
        assert "中央份额" in surface, surface_name


def test_army_delta_arrears_contract_is_documented_across_extractor_surfaces():
    """既有军只允许正值外生加欠；补饷/核销不能靠 army_delta 负值绕真钱流。"""
    shared = (ROOT / "content/prompts/score_extractor_shared.md").read_text(encoding="utf-8")
    military = (ROOT / "content/prompts/score_extractor_military_external.md").read_text(
        encoding="utf-8"
    )
    delta_schema = (ROOT / "docs/DELTA_SCHEMA.md").read_text(encoding="utf-8")
    submit_doc = inspect.getsource(tools_mod.build_extractor_tools)

    for surface_name, surface in {
        "shared extractor contract": shared,
        "military extractor prompt": military,
        "delta schema": delta_schema,
        "submit_extraction tool docs": submit_doc,
    }.items():
        assert "army_delta.arrears" in surface, surface_name
        assert "正值" in surface, surface_name
        assert "外生" in surface, surface_name
        assert "负值" in surface, surface_name
        assert "economy_moves" in surface, surface_name
        assert "补饷" in surface, surface_name
        assert "按饷源比例" in surface, surface_name
        assert "新军" in surface, surface_name


def test_prompt_compatible_ming_new_army_pay_source_aliases_land(game):
    """Chinese prompt aliases for new_armies pay source fields must reach the DB."""
    db, state, content = game

    run_settle(
        db,
        state,
        content,
        {
            "新建军队": [
                {
                    "id": "prompt_pay_source_army",
                    "name": "饷源契约军",
                    "owner_power": "ming",
                    "station": "陕西/西安",
                    "commander": "孙传庭",
                    "troop_type": "募兵步骑",
                    "manpower": 8000,
                    "饷源省": "shaanxi",
                    "省份额": 0.65,
                    "中央份额": 0.35,
                    "状态": "新募，亟待操练",
                }
            ]
        },
        narrative="朝廷于陕西新募饷源契约军，省存留与中央京运分担。",
        decree_text="募陕西新军，陕西省存留六成半、中央三成半。",
    )

    row = db.conn.execute(
        """
        SELECT pay_source_region, province_pay_share, central_pay_share
        FROM armies
        WHERE id = 'prompt_pay_source_army'
        """
    ).fetchone()
    assert row is not None
    assert row["pay_source_region"] == "shaanxi"
    assert row["province_pay_share"] == 0.65
    assert row["central_pay_share"] == 0.35
