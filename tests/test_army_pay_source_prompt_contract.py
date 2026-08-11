from driver import run_settle


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
                    "origin_ref": "盘面自发",
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
