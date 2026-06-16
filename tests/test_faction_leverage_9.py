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

from driver import run_settle
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


def test_non_whitelist_faction_row_leverage_not_recomputed(game):
    """#9 cmr R5 finding#3 边界：宗室是真·在 factions 表的行(leverage=40)、但**不在**白名单
    _LEVERAGE_FACTIONS → 其在朝成员官职变动不按明官 recompute leverage。
    （原测试用「后金」——后金是 power、不在 factions 表，faction_leverage 无行返默认 50，
    前后都 50=假绿：代码永远碰不到后金、就算白名单逻辑坏了也过。改用宗室=正经非白名单 faction-表行边界。）"""
    db, state, content = game
    from ming_sim.db import _LEVERAGE_FACTIONS

    # 前提：宗室在 factions 表、且不在白名单（真边界，非假绿的「无行返默认」）。
    assert db.conn.execute(
        "SELECT 1 FROM factions WHERE name='宗室'"
    ).fetchone() is not None, "宗室应在 factions 表（真·非白名单 faction 行）"
    assert "宗室" not in _LEVERAGE_FACTIONS, "宗室应不在白名单（本测试验非白名单不被 recompute）"

    row = db.conn.execute(
        "SELECT name FROM characters WHERE faction='宗室' AND status='active' LIMIT 1"
    ).fetchone()
    assert row is not None, "宗室需有在朝成员（数据前提）"
    before = db.faction_leverage("宗室")
    db.set_character_status(state, row["name"], "dead", reason="薨")
    after = db.faction_leverage("宗室")
    assert after == before, "非白名单派系(宗室) leverage 不按明朝官职联动 recompute"


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
    result_lo = apply_office_appointment(
        db, state, content, None, name_lo, "某府知府", reason="起复地方", faction="阉党"
    )
    after_low = db.faction_leverage("阉党")

    # name_hi 起复到内阁(高权)
    result_hi = apply_office_appointment(
        db, state, content, None, name_hi, "内阁大学士", reason="起复内阁", faction="阉党"
    )
    after_high = db.faction_leverage("阉党")

    # cmr R3 finding#3 防假绿：两次任命都必须真落库（未被拒）——若低职任命被拒(inc_low=0)，
    # 高职任命成功仍满足 inc_high>inc_low，本测试会假绿（没真验「加的是新职权重」）。
    assert not result_lo.get("rejected"), f"起复到地方不应被拒：{result_lo}"
    assert not result_hi.get("rejected"), f"起复到内阁不应被拒：{result_hi}"
    # 低职起复后该人应 active 且 office 含目标低职（新职权重确被计入，而非任命形同未发生）。
    assert db.get_character_status(name_lo)[0] == "active", "低职起复后该人应 active"
    lo_office = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (name_lo,)
    ).fetchone()["office"]
    assert "知府" in (lo_office or ""), "低职起复后 office 应含目标低职"

    inc_low = after_low - base_after_both_out
    inc_high = after_high - after_low
    # 低职新权重确被计入（>0），不是被拒后的 0——这是与「加的是新职权重」相对的硬下界。
    assert inc_low > 0, (
        f"起复到地方(低权)应使 leverage 上升(新职权重确被计入)：inc_low={inc_low}"
    )
    # name_hi 起复(内阁)的增量 应大于 name_lo 起复(地方)的增量
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
    """#9 finding#4 clamp 边界：连续退场把某 faction 在朝权重和打到使 offset+和<0 → leverage 恰=0(不为负、真触底)。
    用权重和大、offset 深负的派系(阉党开局钦定 78、offset≈-78)：全员退场后权重和→0、offset+和<0→clamp 0。
    cmr R2 强化：原仅断言 >=0（残留正值也能蒙混过关），改为 (1) 先证未 clamp 的 offset+权重和 < 0
    (确属真触底场景，否则跳过)，(2) 断言 leverage 恰 == 0，真锁住下界。"""
    db, state, content = game
    # 选一个 offset 深负的白名单 faction，把其所有在朝握官成员全退场，逼权重和→0、leverage→offset(负)→clamp 0。
    faction = "阉党"  # 钦定 78、权重和重(核心多握高权官) → offset 深负，全退后必触 0
    members = db.conn.execute(
        "SELECT name FROM characters WHERE faction=? AND status='active' AND power_id='ming'",
        (faction,),
    ).fetchall()
    if not members:
        pytest.skip(f"{faction} 无在朝成员（数据依赖）")
    for m in members:
        db.set_character_status(state, m["name"], "dismissed", reason="尽贬")
    # 全员退场后权重和应≈0，未 clamp 的 offset+和 = offset；唯有 offset<0 才是真触底场景。
    offset = db.conn.execute(
        "SELECT leverage_offset FROM factions WHERE name=?", (faction,)
    ).fetchone()["leverage_offset"]
    weight_sum = db._faction_office_weight_sum(faction)
    raw = round(offset + weight_sum)
    if raw >= 0:
        pytest.skip(f"{faction} 全退后未 clamp 值非负(raw={raw})，非下界触底场景")
    after = db.faction_leverage(faction)
    assert after == 0, f"{faction} 全员退场(未 clamp raw={raw}<0)后 leverage 应恰 clamp 到 0(after={after})"
    # 再起复一人（不补 office，仅状态 active）：权重仍≈0，leverage 仍 clamp、不破对称（仍 == 0）
    db.set_character_status(state, members[0]["name"], "active", reason="复一人")
    assert db.faction_leverage(faction) == 0, "起复一人(无职)后仍应恰 clamp 到 0"


def test_add_character_appointment_lifts_faction_leverage(game):
    """#9 cmr R2 finding#2：经 apply_office_appointment 任命一个【不在册的新大臣】到白名单派系的握权官，
    该派系 leverage 应即时上升（add_character hook）。修前 add_character 不联动 → leverage 不变（红）。"""
    db, state, content = game
    faction = "东林"
    # 授「翰林院侍读学士」——office_type=翰林院(域权重 2) × 佐贰档(×0.5)=权重 2.0、非独占实职
    # (不触发 _displace 顶替别人)；权重 2.0 清掉 round() 边界（编修 0.5 会被 round(28.5)→28 吃掉），
    # 保证只测「新建成员加入 → 该派系权重和上升 → leverage 上升」这一路、不受四舍五入边界干扰。
    new_name = "#9测试新科翰林"
    assert db.conn.execute(
        "SELECT name FROM characters WHERE name=?", (new_name,)
    ).fetchone() is None, "测试用新人物不应已在册"
    before = db.faction_leverage(faction)
    before_ws = db._faction_office_weight_sum(faction)
    result = apply_office_appointment(
        db, state, content, None, new_name, "翰林院侍读学士", reason="新科入翰林", faction=faction
    )
    assert not result.get("rejected"), f"新大臣任命不应被拒：{result}"
    assert result.get("kind") == "appoint", f"应走新建档(appoint)路：{result}"
    # 新成员确入册且 active/ming（add_character 落库成功），权重和随之上升。
    after_ws = db._faction_office_weight_sum(faction)
    assert after_ws > before_ws, f"新建大臣应使{faction}权重和上升(before={before_ws} after={after_ws})"
    after = db.faction_leverage(faction)
    assert after > before, (
        f"经 add_character 新建大臣加入{faction}后 leverage 应上升(before={before} after={after})"
    )


def test_active_member_empty_office_contributes_zero_weight(game):
    """#9 cmr R2 finding#3：active + power_id='ming' + office='' + office_type 非空(理论可达边界)
    对 faction 权重和贡献为 0（无实职=不贡献 leverage）。修前 _member_office_weight 会把
    _office_rank_multiplier('') 的默认 1.0 × office_type 域权重算进去 → 误算满权重（红）。"""
    db, state, content = game
    faction = "东林"
    # 取一个该派系在朝握官成员，裸 UPDATE 把 office 清空但保留 office_type='兵部'，制造边界态。
    row = db.conn.execute(
        "SELECT name, office_type FROM characters WHERE faction=? AND status='active' AND power_id='ming' "
        "AND office_type NOT IN ('后宫','宗藩','未仕','') LIMIT 1",
        (faction,),
    ).fetchone()
    if row is None:
        pytest.skip(f"{faction} 无握官在朝成员（数据依赖）")
    name = row["name"]
    # 该成员单独的权重贡献：office 空、office_type='兵部' → 应为 0。
    db.conn.execute(
        "UPDATE characters SET office='', office_type='兵部' WHERE name=?", (name,)
    )
    db.conn.commit()
    from ming_sim.db import _member_office_weight
    assert _member_office_weight("兵部", "") == 0.0, (
        "active 但 office 空的成员 office_type 再高也应贡献 0 权重"
    )
    # 端到端：把其余在朝成员全退场后，仅剩该「空 office」成员，权重和应为 0。
    others = db.conn.execute(
        "SELECT name FROM characters WHERE faction=? AND status='active' AND power_id='ming' AND name!=?",
        (faction, name),
    ).fetchall()
    for o in others:
        db.set_character_status(state, o["name"], "dismissed", reason="清场")
    weight_sum = db._faction_office_weight_sum(faction)
    assert weight_sum == 0.0, (
        f"仅剩 active 空 office 成员时 faction 权重和应为 0(weight_sum={weight_sum})"
    )


def test_recompute_all_reconciles_drift_from_unhooked_path(game):
    """#9 cmr R2 finding#1（集中化兜底）：绕过所有 hook 的裸 UPDATE 改了 faction 成员 office_type 后，
    recompute_all_faction_leverage() 把全部白名单派系重算回公式值（结算尾兜底层等价直测）。"""
    db, state, content = game
    from ming_sim.db import _LEVERAGE_FACTIONS

    faction = "阉党"
    # 裸 UPDATE 把阉党所有在朝成员 office 清空（绕过 set_character_office/status 钩子）→ leverage 残留旧值。
    db.conn.execute(
        "UPDATE characters SET office='' WHERE faction=? AND status='active' AND power_id='ming'",
        (faction,),
    )
    db.conn.commit()
    # 此刻 leverage 仍是旧值（没有 hook 触发重算）。
    stale = db.faction_leverage(faction)
    # 兜底重算全部白名单派系。
    db.recompute_all_faction_leverage()
    db.conn.commit()
    # 重算后该派系 leverage == 公式值（offset + 当前权重和，clamp）。
    offset = db.conn.execute(
        "SELECT leverage_offset FROM factions WHERE name=?", (faction,)
    ).fetchone()["leverage_offset"]
    weight_sum = db._faction_office_weight_sum(faction)
    expected = max(0, min(100, round(offset + weight_sum)))
    reconciled = db.faction_leverage(faction)
    assert reconciled == expected, (
        f"recompute_all 后{faction} leverage 应= 公式值(stale={stale} reconciled={reconciled} expected={expected})"
    )
    # 全部白名单派系都应被重算到各自公式值。
    for f in _LEVERAGE_FACTIONS:
        row = db.conn.execute(
            "SELECT leverage, leverage_offset FROM factions WHERE name=?", (f,)
        ).fetchone()
        if row is None:
            continue
        ws = db._faction_office_weight_sum(f)
        exp = max(0, min(100, round(int(row["leverage_offset"] or 0) + ws)))
        assert row["leverage"] == exp, f"{f} 应被 recompute_all 重算到公式值(got={row['leverage']} exp={exp})"


def test_settle_path_triggers_reconcile_before_next_period(game, monkeypatch):
    """#9 cmr R3 finding#2：reconcile 兜底确由【真实结算路】在 next_period 之前触发——
    锁住生产 wiring（decree.py 结算尾 db.recompute_all_faction_leverage()）+ 其顺序。
    现有 test_recompute_all_reconciles_drift_from_unhooked_path 直调该方法、不走结算路，
    就算结算尾那行 wiring 被删/移到 next_period 之后，那测试照过、证明不了生产接线。
    本测试经 driver.run_settle（公共结算接口）跑一回合，spy 记录方法被调用时 state.turn，
    断言：(1) 被调用过；(2) 调用时 turn 仍是 before_turn（未 next_period）；(3) 结算后 turn 已 +1
    （证明 reconcile 在 next_period 之前跑过）。把结算尾 wiring 删掉则 spy 不触发 → 红。"""
    db, state, content = game
    before_turn = state.turn
    calls = []

    real = type(db).recompute_all_faction_leverage

    def _spy(self):
        # 记录被调用时刻的 turn（生产 wiring 应在 next_period 之前 → turn 仍是 before_turn）。
        calls.append(state.turn)
        return real(self)

    monkeypatch.setattr(type(db), "recompute_all_faction_leverage", _spy)

    run_settle(db, state, content, {}, narrative="x", decree_text="y")

    assert calls, "结算路应触发 recompute_all_faction_leverage（生产 wiring 未接 → 此处为空）"
    assert all(t == before_turn for t in calls), (
        f"reconcile 应在 next_period 之前被调用（调用时 turn 应={before_turn}，实得 {calls}）"
    )
    assert state.turn == before_turn + 1, "结算后回合应已推进（证明 reconcile 在 next_period 前跑过）"


def test_office_weight_takes_highest_domain_across_joint_offices():
    """#9（用户挑战：九千岁退场怎么可能影响小）：兼职跨 domain 时，官职权重取头衔各分项里【最高】的
    domain（按 offices.json 词干表确定性映射、无 LLM），不只看 office_type 单桶。
    魏忠贤 司礼监秉笔(批红 20)+东厂提督(8) → 20；来宗道 礼部尚书(5)+东阁大学士(内阁 18) → 18。
    修前只认 office_type 桶 → 魏忠贤误算 8(东厂)、来宗道误算 5(礼部)，九千岁退场只掉 8。"""
    from ming_sim.db import _member_office_weight
    # 魏忠贤：domain 取司礼监 20（秉笔/提督 均堂官档 ×1.0）——不再因 office_type=东厂 而只值 8。
    assert _member_office_weight("东厂", "司礼监秉笔太监,东厂提督") == 20.0
    # 来宗道：domain 取内阁 18（兼礼部尚书=堂官 ×1.0）——不再因 office_type=礼部 而只值 5。
    assert _member_office_weight("礼部", "礼部尚书,东阁大学士") == 18.0
    # 单职不变：兵部尚书 = 兵部 12 × 堂官 1.0。
    assert _member_office_weight("兵部", "兵部尚书") == 12.0
    # 空 office 仍 0（cafac368 守卫不被本改回归）。
    assert _member_office_weight("司礼监", "") == 0.0


def test_xingbu_has_leverage_weight_like_other_ministries():
    """#9 cmr R3 finding#1：六部齐全——刑部尚书(六部堂官)应与礼部/工部同档贡献权重，不漏成 0。
    COURT_OFFICE_TYPES/MINISTRY_OFFICE_TYPES 明列刑部为正经六部、offices.json 词干表也把
    「刑部尚书→刑部」，但 _OFFICE_LEVERAGE_WEIGHT 修前漏刑部 → 刑部尚书贡献 0、与其余五部不一致。"""
    from ming_sim.db import (
        _OFFICE_LEVERAGE_WEIGHT,
        _member_office_weight,
        MINISTRY_OFFICE_TYPES,
    )
    # 刑部尚书=刑部域权重 × 堂官档 ×1.0；与礼部/工部同「中层部务」档（=5）。
    assert _member_office_weight("刑部", "刑部尚书") == 5.0, (
        "刑部尚书(六部堂官)应贡献非零权重，与其余五部一致"
    )
    # 防再漏：六部每一部都必须在权重表里。
    for ministry in MINISTRY_OFFICE_TYPES:
        assert ministry in _OFFICE_LEVERAGE_WEIGHT, (
            f"六部之{ministry}缺 _OFFICE_LEVERAGE_WEIGHT 权重（漏配 → 该部堂官贡献 0）"
        )


def test_neiting_has_leverage_weight_like_other_court_eunuchs():
    """#9 cmr R5 finding#2：内廷(御马监/内官监等宫廷宦官)在 offices.json allowed_types，
    词干表把「御马监掌印太监→内廷」，但 _OFFICE_LEVERAGE_WEIGHT 修前漏内廷 → 这类在朝宦官
    贡献 0、与 内臣(4)/东厂(8)/司礼监(20) 等在朝宦官不一致。补「内廷:4」（与内臣同宫廷宦官档）。"""
    from ming_sim.db import _OFFICE_LEVERAGE_WEIGHT, _member_office_weight, _office_type_from_table

    # 词干表确把御马监掌印映到内廷（数据前提）。
    assert _office_type_from_table("御马监掌印太监") == "内廷", (
        "offices.json 词干表应把御马监掌印→内廷"
    )
    assert "内廷" in _OFFICE_LEVERAGE_WEIGHT, "内廷应在 _OFFICE_LEVERAGE_WEIGHT（宫廷宦官有实权）"
    # 御马监掌印太监=内廷域权重(4) × 堂官(掌印 ×1.0)=4；非零，与其余在朝宦官一致。
    assert _member_office_weight("内廷", "御马监掌印太监") == 4.0, (
        "内廷宫廷宦官(御马监掌印)应贡献非零权重"
    )


def test_all_court_allowed_types_have_leverage_weight():
    """#9 cmr R5 finding#2 完整性锁（集中化，防再漏第三个）：遍历 offices.json allowed_types，
    除纯民/无朝堂实权的 {后宫,生员,乡绅,富商,布衣,流寇,待铨} 外，每个 allowed_type 都必须在
    _OFFICE_LEVERAGE_WEIGHT。（这条本应在补刑部那轮加——加了内廷这轮就不会冒第三个。）"""
    from ming_sim.assets import load_json_asset
    from ming_sim.db import _OFFICE_LEVERAGE_WEIGHT

    allowed = load_json_asset("offices.json").get("allowed_types") or []
    assert allowed, "offices.json allowed_types 不应为空（数据前提）"
    NON_COURT = {"后宫", "生员", "乡绅", "富商", "布衣", "流寇", "待铨"}
    for t in allowed:
        if t in NON_COURT:
            continue
        assert t in _OFFICE_LEVERAGE_WEIGHT, (
            f"allowed_type「{t}」有朝堂实权却缺 _OFFICE_LEVERAGE_WEIGHT 权重（该类在朝者贡献 0）"
        )


def test_weizhongxian_ouster_drops_yandang_by_sili_weight(game):
    """#9（用户挑战）：魏忠贤(九千岁)退场对阉党的冲击应按司礼监批红(20)算，不是东厂(8)。
    他真权在司礼监秉笔=批红，office_type=东厂只是兼差。退场掉 20 而非 8。"""
    db, state, content = game
    row = db.conn.execute(
        "SELECT name, office, office_type, status FROM characters WHERE name='魏忠贤'"
    ).fetchone()
    if row is None or row["status"] != "active":
        pytest.skip("魏忠贤 非在朝（数据依赖）")
    assert "司礼监" in (row["office"] or ""), "魏忠贤 office 应含司礼监秉笔（数据前提）"
    before = db.faction_leverage("阉党")
    db.set_character_status(state, "魏忠贤", "dismissed", reason="崇祯清算九千岁")
    after = db.faction_leverage("阉党")
    drop = before - after
    assert drop == 20, f"九千岁退场应按司礼监批红掉 20（非东厂 8）：before={before} after={after} drop={drop}"


def test_whitelist_faction_delta_routes_to_offset_survives_reconcile(game):
    """#9 cmr R5 finding#1 [HIGH]：白名单派系的 LLM faction_delta.leverage 经 adjust_factions
    注入 leverage_offset（而非直写 leverage 列），随后结算尾 recompute_all_faction_leverage()
    兜底重算时不被抹回——LLM 的「影响力变化」与官职派生权重复合留存。
    修前：adjust_factions 直写 leverage 列 → recompute_all 用旧 offset 算回公式值、把 +8 抹掉（红）。
    修后：+8 进 offset → recompute_all 算出的公式值已含 +8、确认同值、不抹（绿）。"""
    db, state, content = game
    faction = "阉党"  # 白名单
    before = db.faction_leverage(faction)
    # 经 LLM faction_delta 路给阉党 +8 influence（adjust_factions 是落库单一入口）。
    db.adjust_factions({faction: {"leverage": 8}})
    after_apply = db.faction_leverage(faction)
    assert after_apply == before + 8, (
        f"faction_delta +8 应即时体现在 leverage（before={before} after_apply={after_apply}）"
    )
    # 模拟结算尾兜底 reconcile。
    db.recompute_all_faction_leverage()
    db.conn.commit()
    after_reconcile = db.faction_leverage(faction)
    assert after_reconcile == before + 8, (
        f"白名单 faction_delta +8 注入 offset 后应经 reconcile 留存、不被抹回"
        f"（before={before} after_reconcile={after_reconcile}）"
    )


def test_non_whitelist_faction_delta_direct_leverage_survives_reconcile(game):
    """#9 cmr R5 finding#1：非白名单派系(宗室)的 faction_delta.leverage 仍直写 leverage 列，
    recompute_all 不碰非白名单 → 增量留存（维持原行为）。"""
    db, state, content = game
    from ming_sim.db import _LEVERAGE_FACTIONS

    faction = "宗室"
    assert faction not in _LEVERAGE_FACTIONS, "宗室应为非白名单"
    before = db.faction_leverage(faction)
    db.adjust_factions({faction: {"leverage": 6}})
    after_apply = db.faction_leverage(faction)
    assert after_apply == before + 6, f"非白名单 +6 应直写 leverage（after_apply={after_apply}）"
    db.recompute_all_faction_leverage()
    db.conn.commit()
    after_reconcile = db.faction_leverage(faction)
    assert after_reconcile == before + 6, (
        f"非白名单(宗室) leverage 不被 reconcile 动、增量留存（after_reconcile={after_reconcile}）"
    )
