"""#1896：目标遮掩因子（ADR 0108 阴谋能力）交付与消费。

陛下 2026-10-01 就大理寺上呈的 decisionGate 第一项答「这次就补上」——本片交付
per-character `characters.intrigue` 列及其 seed 数据件，并把它接进 0098 逐证难度。
此前一轮施工自行延期该因子（以 identity 冒充或干脆留白），本片把那处欠交结清。

覆盖面按票面「怎么验」：
- 人物账本接缝：真实开局装载 → 持久存读 → 存档重开读回不变（老档迁移同款路径）；
- 领域查案接缝：控制其余条件仅改目标 intrigue → 逐证难度与相同实投下查获有差异，
  且**不是**代理轴（identity / 自由类目 / 关系网计数皆不动难度）；
- P4：角色输入只吃定性投影，人物呈现上下文不见裸 int。
"""

from __future__ import annotations

import json

import pytest

from ming_sim.qualitative import intrigue_band, qualitative_character_axes


# ---------------------------------------------------------------- 人物账本接缝


def test_intrigue_is_seeded_from_roster_and_persisted(game):
    """真实开局：名册 seed 值落进 characters 行，厂卫/权阉顶格、清流低。"""
    db, _state, content = game

    魏忠贤 = db.conn.execute(
        "SELECT intrigue FROM characters WHERE name=?", ("魏忠贤",),
    ).fetchone()["intrigue"]
    许显纯 = db.conn.execute(
        "SELECT intrigue FROM characters WHERE name=?", ("许显纯",),
    ).fetchone()["intrigue"]
    黄道周 = db.conn.execute(
        "SELECT intrigue FROM characters WHERE name=?", ("黄道周",),
    ).fetchone()["intrigue"]

    assert 魏忠贤 == content.characters["魏忠贤"].intrigue
    assert 许显纯 == content.characters["许显纯"].intrigue
    assert 黄道周 == content.characters["黄道周"].intrigue
    # ADR 0108 seed 口径：厂卫/权阉顶格、清流低（方向而非定值，值随数据件校准）。
    assert 魏忠贤 > 80 and 许显纯 > 80
    assert 黄道周 < 30


def test_intrigue_never_equals_the_column_default(game):
    """seed 不得与 DDL 缺省 50 撞——否则老档一次性回填的守卫无法分辨"未迁移"。

    ``_migrate_character_identity_seed`` 只补仍在缺省上的行；名册里若有人的 seed
    恰是 50，他的老档行会永远停在缺省、拿不到真值。故在数据件层就禁掉。
    """
    _db, _state, content = game
    assert all(c.intrigue != 50 for c in content.characters.values())


def test_intrigue_survives_reopen_and_old_save_migration(tmp_path, content):
    """存档重开读回不变；pre-intrigue 老档经 ensure_column + 一次性回填拿到真值。"""
    from ming_sim.db import GameDB

    path = tmp_path / "pre-intrigue.db"
    first = GameDB(str(path), content)
    first.seed_static_data()
    assert first.conn.execute(
        "SELECT intrigue FROM characters WHERE name=?", ("魏忠贤",),
    ).fetchone()["intrigue"] == content.characters["魏忠贤"].intrigue
    first.close()

    # 模拟 pre-intrigue 老档：该列不存在、meta flag 未落。
    legacy = GameDB(str(path), content)
    legacy.conn.execute("ALTER TABLE characters DROP COLUMN intrigue")
    legacy.conn.execute("DELETE FROM metrics WHERE key='__intrigue_seed_v1'")
    legacy.conn.commit()
    legacy.close()

    restored = GameDB(str(path), content)
    row = restored.conn.execute(
        "SELECT intrigue FROM characters WHERE name=?", ("魏忠贤",),
    ).fetchone()
    assert row["intrigue"] == content.characters["魏忠贤"].intrigue
    restored.close()


def test_intrigue_migration_does_not_rewrite_a_played_value(tmp_path, content):
    """老档里已被玩过的值不得被回填覆盖（同 identity 守卫的形状）。"""
    from ming_sim.db import GameDB

    path = tmp_path / "played.db"
    first = GameDB(str(path), content)
    first.seed_static_data()
    first.close()

    # 造一个 pre-intrigue 老档：列不存在、meta flag 未落（DDL/DML 各自显式 commit，
    # 否则隐式事务回滚会只撤一半、造出既非新档也非老档的第三种形状）。
    legacy = GameDB(str(path), content)
    legacy.conn.execute("ALTER TABLE characters DROP COLUMN intrigue")
    legacy.conn.commit()
    legacy.conn.execute("DELETE FROM metrics WHERE key='__intrigue_seed_v1'")
    legacy.conn.commit()
    legacy.close()

    # 重开：ensure_column 补出该列（全体落 DDL 缺省 50），回填把名册行刷成 seed
    # 真值——再把一人改成别的值，模拟"玩家已玩过、值已不是缺省"。
    between = GameDB(str(path), content)
    assert between.conn.execute(
        "SELECT intrigue FROM characters WHERE name=?", ("魏忠贤",),
    ).fetchone()["intrigue"] == content.characters["魏忠贤"].intrigue
    between.conn.execute("UPDATE characters SET intrigue=17 WHERE name=?", ("黄道周",))
    between.conn.commit()
    between.close()

    # 再开：一次性回填已落 flag，不得重跑、不得覆盖玩过的值。
    restored = GameDB(str(path), content)
    assert restored.conn.execute(
        "SELECT intrigue FROM characters WHERE name=?", ("黄道周",),
    ).fetchone()["intrigue"] == 17
    assert restored.conn.execute(
        "SELECT intrigue FROM characters WHERE name=?", ("魏忠贤",),
    ).fetchone()["intrigue"] == content.characters["魏忠贤"].intrigue
    restored.close()


def test_new_character_enters_roster_with_a_consumable_intrigue(game):
    """新增人物沿同一入册路径，属性可被查案接缝消费（不是只在开局名册里有）。"""
    from ming_sim.covert_progress import investigation_fact_difficulty
    from ming_sim.session import register_unlisted_person_record

    db, state, content = game
    created = register_unlisted_person_record(
        db, state, content,
        name="周慎行", office="兵部主事", office_type="兵部", faction="东林",
        region_id="京师",
    )
    assert created is not None
    assert db.conn.execute(
        "SELECT intrigue FROM characters WHERE name=?", ("周慎行",),
    ).fetchone()["intrigue"] == created.intrigue

    # 消费口读得到：不是只在开局名册里才有值的死字段。
    assert investigation_fact_difficulty(
        db, target="周慎行", fact_key="周慎行", investigator="黄道周",
    ) > 0.0


# ---------------------------------------------------------------- 领域查案接缝


def _seed_guilty_pair(db, *, investigator="黄道周", target="魏忠贤"):
    """一桩最小真案：目标有 seed_guilt，承办人在场，其余轴全部钉死。"""
    db.conn.execute(
        "UPDATE characters SET seed_guilt=? WHERE name=?",
        (json.dumps({"crime": "侵冒", "severity": "中"}, ensure_ascii=False), target),
    )
    db.conn.execute(
        "UPDATE characters SET loyalty=90, identity=50, ability=60, intrigue=50 "
        "WHERE name IN (?,?)",
        (investigator, target),
    )
    db.conn.execute(
        "UPDATE characters SET location='京师', transit_to='' "
        "WHERE name IN (?,?)",
        (investigator, target),
    )
    db.conn.commit()


def test_only_target_intrigue_moves_the_difficulty(game):
    """控制其余条件，仅改目标 intrigue → 难度按其反向单调变化（非代理轴、非占位常量）。"""
    from ming_sim.covert_progress import investigation_fact_difficulty

    db, _state, _content = game
    _seed_guilty_pair(db)
    key = "魏忠贤"

    low = investigation_fact_difficulty(
        db, target="魏忠贤", fact_key=key, investigator="黄道周")

    db.conn.execute("UPDATE characters SET intrigue=100 WHERE name=?", ("魏忠贤",))
    db.conn.commit()
    high = investigation_fact_difficulty(
        db, target="魏忠贤", fact_key=key, investigator="黄道周")

    assert high > low, "目标越会遮掩越难查（已准设计原句）"

    db.conn.execute("UPDATE characters SET intrigue=1 WHERE name=?", ("魏忠贤",))
    db.conn.commit()
    bottom = investigation_fact_difficulty(
        db, target="魏忠贤", fact_key=key, investigator="黄道周")

    assert bottom < low, "遮掩低者更易查；单向轴不是常数偏移"

    # 0 是闭集下端的合法值（content 侧 0–100），且必须与 1 同落最易查的边缘——
    # 跳过乘子会让"最不会遮掩的人"与参考值同难度，在单调轴上凭空造一道台阶。
    db.conn.execute("UPDATE characters SET intrigue=0 WHERE name=?", ("魏忠贤",))
    db.conn.commit()
    zero = investigation_fact_difficulty(
        db, target="魏忠贤", fact_key=key, investigator="黄道周")
    assert zero <= bottom, "0 不得比 1 更难查"
    assert zero < low, "最不会遮掩者不得与常人同难度"

    # 参考值 50 是中性点：50/50 不乘不除。
    db.conn.execute("UPDATE characters SET intrigue=50 WHERE name=?", ("魏忠贤",))
    db.conn.commit()
    assert investigation_fact_difficulty(
        db, target="魏忠贤", fact_key=key, investigator="黄道周",
    ) == pytest.approx(low)


def test_intrigue_is_not_a_proxy_axis(game):
    """遮掩只吃 intrigue：identity、自由类目边、有无其它人物皆不改难度。"""
    from ming_sim.covert_progress import investigation_fact_difficulty

    db, _state, _content = game
    _seed_guilty_pair(db)
    key = "魏忠贤"
    base = investigation_fact_difficulty(
        db, target="魏忠贤", fact_key=key, investigator="黄道周")

    # 党籍认同是孤臣轴，不是掩人耳目之能（ADR 0108:5,7／CONTEXT.md）。
    db.conn.execute("UPDATE characters SET identity=99 WHERE name=?", ("魏忠贤",))
    db.conn.commit()
    assert investigation_fact_difficulty(
        db, target="魏忠贤", fact_key=key, investigator="黄道周") == base

    # 承办人自己的阴谋能力不是目标轴——查案人再鬼也不因此更难查。
    db.conn.execute("UPDATE characters SET intrigue=100 WHERE name=?", ("黄道周",))
    db.conn.commit()
    assert investigation_fact_difficulty(
        db, target="魏忠贤", fact_key=key, investigator="黄道周") == base


def test_unknown_target_degenerates_the_axis_instead_of_inventing_one(game):
    """查案对象不是真人物行时该轴退化不参与——不假装他会遮掩。"""
    from ming_sim.covert_progress import investigation_fact_difficulty

    db, _state, _content = game
    _seed_guilty_pair(db)

    known = investigation_fact_difficulty(
        db, target="魏忠贤", fact_key="某把柄", investigator="黄道周")
    # 题名式查案对象（非真人物行）：该轴放行，不取任何人的遮掩冒充。
    unknown = investigation_fact_difficulty(
        db, target="江南粮饷", fact_key="某把柄", investigator="黄道周")

    assert known > 0.0 and unknown > 0.0
    # 放行意味着"无此轴"，不是"借了某人的值"：与把目标换成 50 缺省时同档。
    db.conn.execute("UPDATE characters SET intrigue=50 WHERE name=?", ("魏忠贤",))
    db.conn.commit()
    assert investigation_fact_difficulty(
        db, target="魏忠贤", fact_key="某把柄", investigator="黄道周",
    ) == pytest.approx(unknown)


@pytest.mark.parametrize(
    "target,intrigue,expect_mastered",
    [
        # 同一强度、同一承办人、同一实投折算路径（各自独占一档，容量可比）：
        # 门槛只因目标遮掩不同而分出高下。
        ("黄道周", 1, True),
        ("魏忠贤", 100, False),
    ],
)
def test_equal_effort_lands_differently_by_target_concealment(
    game, target, intrigue, expect_mastered,
):
    """相同实投下，低遮掩者已掌握、高遮掩者尚未——门槛差异真落到查获上。"""
    from ming_sim.covert_progress import apply_investigation_monthly_effort

    db, state, _content = game
    investigator = "袁可立"
    _seed_guilty_pair(db, investigator=investigator, target=target)
    db.conn.execute(
        "UPDATE characters SET intrigue=? WHERE name=?", (intrigue, target))
    db.conn.commit()

    oid = db.create_secret_order(
        state, investigator, "密查", "密查", [],
        deadline_months=6,
        covert_task={
            "kind": "查核", "axes": ["既得利益"], "direction": 1,
            "investigation_target": target,
            "delivery": {
                "target_units": 1.0, "effect_sign": 1,
                "investigation_target": target,
            },
        },
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])

    apply_investigation_monthly_effort(
        db, did, target, investigator,
        fact_key=target, intensity=1.0, commit=True,
    )

    lane = next(
        row for row in json.loads(db.conn.execute(
            "SELECT payload_json FROM decree_dossiers WHERE id=?", (did,),
        ).fetchone()["payload_json"])["fact_lanes"]
        if row["fact_key"] == target
    )
    # 同一强度、同一承办人、同一容量路径 → 实投真同，差异只在门槛。
    assert lane["effort"] == pytest.approx(1.0)
    assert lane["mastered"] is expect_mastered
    if expect_mastered:
        assert lane["effort"] >= lane["difficulty"], "实投达门槛才记掌握"
    else:
        assert lane["effort"] < lane["difficulty"], "实投未达门槛不得查获"


# ---------------------------------------------------------------- P4 呈现接缝


def test_intrigue_reaches_character_input_only_as_a_qualitative_band(game):
    """ADR 0143/0122：扮演输入只吃定性档，人物呈现上下文不见裸 int。"""
    from ming_sim.context import character_context

    db, _state, content = game
    character = content.characters["魏忠贤"]
    axes = qualitative_character_axes(character)

    assert axes["阴谋"] == f"阴谋{intrigue_band(character.intrigue)}"
    assert str(character.intrigue) not in axes["阴谋"]

    rendered = character_context(character)
    assert "intrigue" not in rendered
    assert str(character.intrigue) not in rendered
    assert axes["阴谋"] in rendered

    # 同一档词表，不因人物而异（唯一词面真源）。
    assert intrigue_band(0) != intrigue_band(100)
    assert len({intrigue_band(v) for v in (0, 30, 50, 70, 100)}) == 5
