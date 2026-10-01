"""#1896：目标遮掩因子（ADR 0108 阴谋能力）交付与消费。

陛下 2026-10-01 选了问卷第二项「这次就补上」（第一项是「先不做，票面写明
(Recommended)」；编号是问卷选项，不是大理寺 decisionGate）。本片交付
per-character `characters.intrigue` 列及其 seed 数据件，并把它接进 0098 逐证难度。
此前一轮施工自行延期该因子（以 identity 冒充或干脆留白），本片把那处欠交结清。

覆盖面按票面「怎么验」：
- 人物账本接缝：当前格式新开局装载 → 持久存读 → 同格式重开读回不变；
- 领域查案接缝：控制其余条件仅改目标 intrigue → 逐证难度与相同实投下查获有差异，
  且**不是**代理轴（identity / 自由类目 / 关系网计数皆不动难度）；
- P4：角色输入只吃定性投影，人物呈现上下文不见裸 int。
"""

from __future__ import annotations


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


def test_current_format_reopen_keeps_seeded_and_played_intrigue(tmp_path, content):
    """当前格式重开读回不变：开局 seed 与其后改过的值都不被重写。"""
    from ming_sim.db import GameDB

    path = tmp_path / "current.db"
    first = GameDB(str(path), content)
    first.seed_static_data()
    seeded = content.characters["魏忠贤"].intrigue
    assert first.conn.execute(
        "SELECT intrigue FROM characters WHERE name=?", ("魏忠贤",),
    ).fetchone()["intrigue"] == seeded
    first.conn.execute("UPDATE characters SET intrigue=17 WHERE name=?", ("黄道周",))
    first.conn.commit()
    first.close()

    restored = GameDB(str(path), content)
    assert restored.conn.execute(
        "SELECT intrigue FROM characters WHERE name=?", ("魏忠贤",),
    ).fetchone()["intrigue"] == seeded
    assert restored.conn.execute(
        "SELECT intrigue FROM characters WHERE name=?", ("黄道周",),
    ).fetchone()["intrigue"] == 17
    restored.close()


def test_new_character_enters_roster_with_intrigue(game):
    """新增人物沿同一入册路径写入 characters.intrigue。"""
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


def test_intrigue_reaches_character_input_only_as_a_qualitative_band(game):
    """结构化轴不是裸整数。"""
    from ming_sim.qualitative import qualitative_character_axes

    _db, _state, content = game
    character = content.characters["魏忠贤"]
    projected = qualitative_character_axes(character)["阴谋"]
    assert isinstance(projected, str)
    assert projected != str(int(character.intrigue))
    assert not projected.strip().isdigit()
