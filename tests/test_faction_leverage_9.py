"""#9：派系势力(faction leverage) 随「在朝成员官职权重」全重算联动。

修前 set_character_status 不动 leverage、character_status_changes 与派系势力无联动，
实测阉党三核心(田尔耕/崔呈秀/王体乾)退场后 leverage 仍挂 78(全场第一)。

方案（全重算、offset 锚定钦定基线）：
  leverage(faction) = clamp(0,100, offset + 当前在朝(active)成员官职权重和)
  offset = 钦定基线 − 开局校准时的权重和 → 开局==钦定基线(保平衡)，退场跌、起复/升迁涨。
  权重 = office_type 域权重 × 品级档(从 office 头衔解析)；绝对重算 → 无 clamp 漂移、时序无关。
只对白名单朝堂派系{阉党,东林,皇党,中立,军队,西学}；外族/后宫/宗室/流寇不联动。
双 hook：set_character_status + set_character_office 都全重算（升迁/起复都联动）。
"""

from __future__ import annotations

import pytest

from ming_sim.issues import apply_office_appointment


def _yandang_core(db):
    """取阉党一个握高权官(内阁/司礼监/吏部/兵部)的在朝核心。"""
    return db.conn.execute(
        "SELECT name, office_type, office FROM characters WHERE faction='阉党' AND status='active' "
        "AND office_type IN ('内阁','司礼监','吏部','兵部') LIMIT 1"
    ).fetchone()


def test_faction_leverage_drops_when_core_minister_ousted(game):
    """#9 核心：握高权官的阉党在朝核心退场 → 阉党 leverage 全重算后下跌。"""
    db, state, content = game
    row = _yandang_core(db)
    assert row is not None, "阉党需有握高权官(内阁/司礼监/吏部/兵部)的在朝核心"
    before = db.faction_leverage("阉党")
    db.set_character_status(state, row["name"], "dismissed", reason="清算阉党")
    after = db.faction_leverage("阉党")
    assert after < before, f"核心退场后阉党 leverage 应联动下跌(before={before} after={after})"


def test_faction_leverage_rises_back_when_minister_restored(game):
    """#9 对称：退场核心起复(active) → leverage 回到原值（绝对重算、无漂移）。"""
    db, state, content = game
    row = _yandang_core(db)
    assert row is not None
    base = db.faction_leverage("阉党")
    db.set_character_status(state, row["name"], "dismissed", reason="清算")
    dropped = db.faction_leverage("阉党")
    # 起复后还原其原官职（起复路真实序列：set_character_status(active) 不带回 office，
    # 再 set_character_office(原职) 才补回权重——这里手动复刻这两步，验末值对称回原）。
    db.set_character_status(state, row["name"], "active", reason="起复")
    db.set_character_office(row["name"], row["office"], row["office_type"])
    restored = db.faction_leverage("阉党")
    assert dropped < base, "退场应跌"
    assert restored == base, f"起复+复职应回到原值(base={base} restored={restored})"


def test_foreign_faction_leverage_not_touched(game):
    """#9 边界：外族(后金)非白名单 → 其成员状态变不联动 leverage(不按明官算)。"""
    db, state, content = game
    row = db.conn.execute(
        "SELECT name FROM characters WHERE faction='后金' AND status='active' LIMIT 1"
    ).fetchone()
    if row is None:
        pytest.skip("基底盘面无后金在朝成员（数据依赖）")
    before = db.faction_leverage("后金")
    db.set_character_status(state, row["name"], "dead", reason="阵亡")
    after = db.faction_leverage("后金")
    assert after == before, "外族派系 leverage 不按明朝官职联动"


def test_xixue_faction_in_whitelist_drops_when_member_ousted(game):
    """#9 finding#1：西学在白名单 → 其握明官成员(徐光启/孙元化)退场，西学 leverage 联动下跌。"""
    db, state, content = game
    row = db.conn.execute(
        "SELECT name, office_type FROM characters WHERE faction='西学' AND status='active' "
        "AND office_type NOT IN ('后宫','宗藩','未仕','') LIMIT 1"
    ).fetchone()
    assert row is not None, "西学需有握明官的在朝成员"
    before = db.faction_leverage("西学")
    db.set_character_status(state, row["name"], "dismissed", reason="逐西学")
    after = db.faction_leverage("西学")
    assert after < before, f"西学成员退场后 leverage 应联动下跌(before={before} after={after})"


def test_rank_tier_modulates_impact(game):
    """#9 finding#5：同 office_type 不同品级，退场冲击不同。
    崔呈秀=兵部尚书(堂官 ×1.0) 退场对阉党的冲击 > 孙元化=兵部职方(属官 ×0.25) 退场对西学的冲击。
    （两人同为 office_type='兵部'，品级 multiplier 差 4 倍 → 权重差 4 倍 → leverage 跌幅差 ~4 倍。）"""
    db, state, content = game
    chong = db.conn.execute(
        "SELECT name, office FROM characters WHERE name='崔呈秀' AND status='active'"
    ).fetchone()
    sun = db.conn.execute(
        "SELECT name, office FROM characters WHERE name='孙元化' AND status='active'"
    ).fetchone()
    if chong is None or sun is None:
        pytest.skip("基底盘面缺 崔呈秀/孙元化（数据依赖）")
    assert "尚书" in (chong["office"] or ""), "崔呈秀应为兵部尚书(堂官)"
    assert "职方" in (sun["office"] or ""), "孙元化应为兵部职方(属官)"

    yd_before = db.faction_leverage("阉党")
    db.set_character_status(state, "崔呈秀", "dismissed", reason="清算")
    chong_drop = yd_before - db.faction_leverage("阉党")

    xx_before = db.faction_leverage("西学")
    db.set_character_status(state, "孙元化", "dismissed", reason="清算")
    sun_drop = xx_before - db.faction_leverage("西学")

    assert chong_drop > 0 and sun_drop > 0, "两人退场都应使各自 faction 下跌"
    assert chong_drop > sun_drop, (
        f"兵部尚书(堂官 ×1.0)退场冲击应大于兵部职方(属官 ×0.25)："
        f"崔呈秀跌{chong_drop} vs 孙元化跌{sun_drop}"
    )


def test_restore_uses_new_office_weight_not_old(game):
    """#9 finding#3 时序：先把人 dismissed(低职/无职)，再经 apply_office_appointment 起复到不同权官，
    leverage 加的是**新职**权重——起复到内阁(高权)后比起复到地方(低权)后更高。"""
    db, state, content = game
    # 取一个阉党在朝成员，先退场，再分别试起复到内阁 vs 地方，比末值。
    # 用两份独立的人各跑一边，避免相互污染（同一 faction、同一回合两次起复会叠加）。
    cands = db.conn.execute(
        "SELECT name FROM characters WHERE faction='阉党' AND status='active' "
        "AND office_type NOT IN ('后宫','宗藩','未仕','') LIMIT 2"
    ).fetchall()
    if len(cands) < 2:
        pytest.skip("阉党在朝握官成员不足 2（数据依赖）")
    name_hi, name_lo = cands[0]["name"], cands[1]["name"]

    # 两人都退场（清各自权重），记基准
    db.set_character_status(state, name_hi, "dismissed", reason="清算")
    db.set_character_status(state, name_lo, "dismissed", reason="清算")
    base_after_both_out = db.faction_leverage("阉党")

    # name_lo 起复到地方(低权)
    apply_office_appointment(
        db, state, content, None, name_lo, "某府知府", reason="起复地方", faction="阉党"
    )
    after_low = db.faction_leverage("阉党")

    # name_hi 起复到内阁(高权)
    apply_office_appointment(
        db, state, content, None, name_hi, "内阁大学士", reason="起复内阁", faction="阉党"
    )
    after_high = db.faction_leverage("阉党")

    assert after_low >= base_after_both_out, "起复到地方应至少不降"
    # name_hi 起复(内阁)的增量 应大于 name_lo 起复(地方)的增量
    inc_low = after_low - base_after_both_out
    inc_high = after_high - after_low
    assert inc_high > inc_low, (
        f"起复到内阁(高权)的 leverage 增量应大于起复到地方(低权)：内阁+{inc_high} vs 地方+{inc_low}"
    )


def test_promotion_via_set_character_office_raises_leverage(game):
    """#9 finding(双hook)：active 成员从低权官调到高权官(set_character_office) → faction leverage 上升。
    增量版只挂 set_character_status、漏了升迁联动；全重算双 hook 修此。"""
    db, state, content = game
    # 取一个阉党在朝低权官（地方/外臣），升迁到内阁，验 leverage 涨。
    row = db.conn.execute(
        "SELECT name, office_type FROM characters WHERE faction='阉党' AND status='active' "
        "AND office_type IN ('地方','外臣','翰林院','内臣') LIMIT 1"
    ).fetchone()
    if row is None:
        # 退而求其次：任取一个握官成员升到内阁尚书堂官，验非降（多数情况会涨）。
        row = db.conn.execute(
            "SELECT name, office_type FROM characters WHERE faction='阉党' AND status='active' "
            "AND office_type NOT IN ('后宫','宗藩','未仕','','内阁','司礼监') LIMIT 1"
        ).fetchone()
    if row is None:
        pytest.skip("阉党无可升迁的在朝低权官（数据依赖）")
    before = db.faction_leverage("阉党")
    db.set_character_office(row["name"], "内阁大学士", "内阁")
    after = db.faction_leverage("阉党")
    assert after > before, f"升迁到内阁后 leverage 应上升(before={before} after={after})"


def test_failed_appointment_rolls_back_faction_leverage(game):
    """#9 finding#2 事务回滚：失败的 apply_office_appointment（走 _restore_person_write_state）后，
    该 faction leverage 与调用前一致（中途全重算被回滚、不漂移）。"""
    db, state, content = game
    # 构造失败：起复一个在册阉党成员，但 set_character_office 抛错（授个会让 infer 报错的非法链）。
    # 更稳的失败注入：monkeypatch set_character_office 抛错，验回滚还原 leverage。
    name = db.conn.execute(
        "SELECT name FROM characters WHERE faction='阉党' AND status='active' "
        "AND office_type NOT IN ('后宫','宗藩','未仕','') LIMIT 1"
    ).fetchone()
    assert name is not None
    name = name["name"]
    # 先退场，制造一个「起复」场景（起复路会 set_character_status(active)→全重算→再 set_character_office）。
    db.set_character_status(state, name, "dismissed", reason="清算")
    before = db.faction_leverage("阉党")

    orig = db.set_character_office

    def _boom(*a, **k):
        raise RuntimeError("注入故障：授官落库失败")

    db.set_character_office = _boom  # type: ignore[assignment]
    try:
        result = apply_office_appointment(
            db, state, content, None, name, "内阁大学士", reason="起复内阁", faction="阉党"
        )
    finally:
        db.set_character_office = orig  # type: ignore[assignment]

    assert result.get("rejected"), f"注入故障应使任命 rejected：{result}"
    after = db.faction_leverage("阉党")
    assert after == before, (
        f"失败任命回滚后阉党 leverage 应不变(before={before} after={after})"
    )
    # 人物状态也应回滚（仍 dismissed，未被中途 set_character_status(active) 残留）
    assert db.get_character_status(name)[0] == "dismissed", "失败任命应回滚人物状态"


def test_displaced_minister_faction_leverage_recomputed(game):
    """#9 cmr R1：顶替路也要重算【被顶替者】所属派系 leverage。
    新任者属 A 派系(东林)，经 apply_office_appointment 任命到独占实职(兵部尚书)，
    顶替掉持该职、属 B 派系(阉党≠东林)的在朝核心崔呈秀。
    _displace_duplicate_offices 用裸 UPDATE 把崔呈秀的 office_type 改成低权(剥兵部尚书后只剩左都御史
    /或身名分)，绕过 set_character_office 钩子 → 修前 B(阉党) leverage 不被重算、残留偏高。
    断言：任命后阉党 leverage < 任命前（被顶替者权重下跌、其派系全重算联动）。"""
    db, state, content = game
    chong = db.conn.execute(
        "SELECT name, office, office_type, faction FROM characters WHERE name='崔呈秀' AND status='active'"
    ).fetchone()
    # 新任者属东林（≠阉党），无需 active——apply_office_appointment 会起复激活后再授官。
    new_holder = db.conn.execute(
        "SELECT name, faction FROM characters WHERE name='孙承宗'"
    ).fetchone()
    if chong is None or new_holder is None:
        pytest.skip("基底盘面缺 崔呈秀/孙承宗（数据依赖）")
    assert chong["faction"] == "阉党", "崔呈秀应为阉党"
    assert new_holder["faction"] == "东林", "孙承宗应为东林(≠阉党)"
    assert "兵部尚书" in (chong["office"] or ""), "崔呈秀应持兵部尚书(独占实职)"

    before = db.faction_leverage("阉党")
    result = apply_office_appointment(
        db, state, content, None, "孙承宗", "兵部尚书", reason="起复掌兵部", faction="东林"
    )
    assert not result.get("rejected"), f"任命不应被拒：{result}"
    assert result.get("displaced"), f"应顶替崔呈秀的兵部尚书：{result}"
    after = db.faction_leverage("阉党")
    assert after < before, (
        f"被顶替者(崔呈秀)所属阉党 leverage 应在顶替后全重算下跌(before={before} after={after})"
    )


def test_offset_not_re_anchored_on_reload_after_clamp(game):
    """#9 cmr R3：老档每次 load 重锚 offset，clamp 后腐蚀基线。
    seed 后取白名单派系 offset；手动把 leverage 打到 0（模拟 clamp 触底）；再开一个 GameDB
    （生产里每次 GameSession init = 新 GameDB.__init__→init_schema→seed_static_data，是真正的 reload，
    offset 列已存在于 DB 文件 → ensure_column 返 False）。修前老档分支每次 load 都
    offset=round(0−weight_sum)≠原值（被腐蚀）；修后因「列已存在 + 非新档」直接 return，offset 不变。"""
    from ming_sim.db import GameDB

    db, state, content = game
    faction = "阉党"
    before_offset = db.conn.execute(
        "SELECT leverage_offset FROM factions WHERE name=?", (faction,)
    ).fetchone()["leverage_offset"]

    # 模拟 leverage 被 clamp 到 0 触底（玩过后的脏值）
    db.conn.execute("UPDATE factions SET leverage=0 WHERE name=?", (faction,))
    db.conn.commit()

    # 真·reload：在同一 DB 文件上新开 GameDB（init_schema 见 offset 列已存在 → flag=False），再 seed。
    reloaded = GameDB(db.path, content)
    try:
        reloaded.seed_static_data()
        after_offset = reloaded.conn.execute(
            "SELECT leverage_offset FROM factions WHERE name=?", (faction,)
        ).fetchone()["leverage_offset"]
    finally:
        reloaded.close()
    assert after_offset == before_offset, (
        f"reload(clamp 后)不应重锚 offset：before={before_offset} after={after_offset}"
    )


def test_leverage_clamps_at_zero_no_negative(game):
    """#9 finding#4 clamp 边界：连续退场把某 faction 在朝权重和打到使 offset+和<0 → leverage=0(不为负)。
    用 offset 较小的派系(东林开局钦定 28、offset 负)更易触底；这里把白名单某 faction 全员退场验 ≥0。"""
    db, state, content = game
    # 选一个白名单 faction，把其所有在朝握官成员全退场，逼权重和→0、leverage→offset(可能负)→clamp 0。
    faction = "东林"  # 钦定 28、人多但多为低权/罢居 → offset 偏负，全退后易触 0
    members = db.conn.execute(
        "SELECT name FROM characters WHERE faction=? AND status='active' AND power_id='ming'",
        (faction,),
    ).fetchall()
    if not members:
        pytest.skip(f"{faction} 无在朝成员（数据依赖）")
    for m in members:
        db.set_character_status(state, m["name"], "dismissed", reason="尽贬")
    after = db.faction_leverage(faction)
    assert after >= 0, f"{faction} 全员退场后 leverage 不应为负(after={after})"
    # 再起复一人（不补 office，仅状态 active）：权重仍≈0，leverage 仍 clamp、不破对称（不为负）
    db.set_character_status(state, members[0]["name"], "active", reason="复一人")
    assert db.faction_leverage(faction) >= 0, "起复后仍不应为负"
