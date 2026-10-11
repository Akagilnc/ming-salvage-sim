"""#104: 朝堂大臣列表按 DB 权威状态过滤 offstage（离场/未登场不入列）。

回归要点：过滤须用 db.get_character_status（DB 权威），**不能用内存 c.status**——
auto-debut 等路径（db.set_character_status）只写 DB、不回写内存，c.status 会 stale。
issue #104 原提议的 `c.status != "offstage"` 会把「DB 已 active 但内存仍 offstage」
的已登场人物（如 debut 后的李自成/郑成功）永久挡在朝堂外，比原 bug 更糟。
"""
from __future__ import annotations

from types import SimpleNamespace

import web_app
from web_app import in_talent_pool, visible_in_court


def _active_ming_minister(db, content) -> str:
    for name, ch in content.characters.items():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        # #1317：未仕/后宫/宗藩非朝臣可召样本
        if getattr(ch, "office_type", "") in ("后宫", "宗藩", "未仕"):
            continue
        if db.characters.get_character_status(name)[0] == "active":
            return name
    raise AssertionError("基底盘面无 active 的大明大臣")


def test_active_ming_minister_visible(read_game):
    db, _state, content = read_game
    name = _active_ming_minister(db, content)
    assert visible_in_court(content.characters[name], db) is True


def test_active_non_ming_character_not_in_court(game):
    """非 ming 治下人物即便 DB active 也不入朝堂（锁 power_id 过滤，Sourcery R1）。"""
    db, state, content = game
    name = next(
        (n for n, c in content.characters.items()
         if getattr(c, "power_id", "ming") != "ming"
         and getattr(c, "office_type", "") != "后宫"),
        None,
    )
    if name is None:
        import pytest
        pytest.skip("基底盘面无非 ming 人物")
    db.set_character_status(state, name, "active", "测试：在世")
    assert visible_in_court(content.characters[name], db) is False


def test_db_offstage_excluded_even_if_memory_active(game):
    """DB 翻 offstage、内存 c.status 仍 active（分叉）→ 应排除（DB 权威）。"""
    db, state, content = game
    name = _active_ming_minister(db, content)
    ch = content.characters[name]
    db.set_character_status(state, name, "offstage", "测试：离场")
    assert ch.status == "active"  # 内存 stale，证明分叉确实存在
    assert visible_in_court(ch, db) is False
    assert name not in {row["name"] for row in db.characters.current_court_rows(state.year, state.period)}


def test_db_active_included_even_if_memory_offstage(game):
    """内存 c.status=offstage 但 DB=active（debut 后场景）→ 应入列。
    这正是 issue 原 one-liner（c.status != "offstage"）会错杀的 case。"""
    db, state, content = game
    name = _active_ming_minister(db, content)
    ch = content.characters[name]
    original_status = ch.status
    try:
        ch.status = "offstage"  # 模拟 JSON seed / stale 内存
        db.set_character_status(state, name, "active", "测试：历史登场")
        assert visible_in_court(ch, db) is True
    finally:
        # content fixture 是 session 作用域，还原内存 status 防跨用例污染（Codex R2）
        ch.status = original_status


def _materialized_prince(db, state, content):
    """把一个 content 宗藩王真正物化进测试 DB 后返回 (name, character)。

    probe.db 是旧档、没有宗藩行（朱常洵 等只在 characters.json），对缺行的
    db.set_character_status 是 no-op、status/power_id 只能靠缺行默认值兜——setup 形同虚设、
    断言无法验真 DB 态（cmr R2 codex sec1）。先 add_character 物化（保 office_type=宗藩/
    power_id=ming），后续 set_character_status 才真生效、断言才证得了「即便 active+ming 也拒」。"""
    name = next(
        (n for n, c in content.characters.items() if getattr(c, "office_type", "") == "宗藩"),
        None,
    )
    if name is None:
        import pytest
        pytest.skip("基底盘面无宗藩人物")
    ch = content.characters[name]
    db.add_character(state, ch, source="测试物化")
    return name, ch


def test_vassal_prince_excluded_from_court(game):
    """宗室/就藩藩王（office_type=宗藩）不是可召见/可任免的朝堂官员，即便 ming+active 也不入列
    （用户 2026-06-14 拍：宗室要隐藏）。藩王在册数据照旧留 DB（事件按名引用不受影响），只是不进
    朝堂/任免列表 UI。"""
    db, state, content = game
    name, ch = _materialized_prince(db, state, content)
    db.set_character_status(state, name, "active", "测试：在世")
    # 物化后 setup 真生效：DB 确为 active+ming（否则仅 office_type 短路，测不出 gate 优先于状态）
    assert db.characters.get_character_status(name)[0] == "active"
    assert web_app._character_power_id(ch, db) == "ming"
    assert visible_in_court(ch, db) is False


def test_offstage_former_minister_in_talent_pool(game):
    """罢居/在野前臣（offstage + ming + 朝堂类、非未来登场）入「在野人才池」，供浏览起复
    （#120 / docs/HISTORICAL_CASE_LIBRARY.md:41）。这正是 #104 把 offstage 挡出朝堂后丢失的读取面。"""
    db, state, content = game
    name = next(
        (n for n, c in content.characters.items()
         if getattr(c, "power_id", "ming") == "ming"
         and getattr(c, "office_type", "") not in ("后宫", "宗藩", "流寇", "未仕")
         and int(getattr(c, "debut_year", 0) or 0) == 0),
        None,
    )
    if name is None:
        import pytest
        pytest.skip("基底盘面无合适的朝堂类前臣")
    db.set_character_status(state, name, "offstage", "测试：自请罢居")
    assert in_talent_pool(content.characters[name], db, state.year, state.period) is True
    # 在野不入朝堂列表（两个列表互斥，offstage 只进人才池）
    assert visible_in_court(content.characters[name], db) is False


def test_active_minister_not_in_talent_pool(read_game):
    """在朝（active）大臣不进在野池——人才池只补 offstage 这一漏面。"""
    db, state, content = read_game
    name = _active_ming_minister(db, content)
    assert in_talent_pool(content.characters[name], db, state.year, state.period) is False


def test_vassal_prince_excluded_from_talent_pool(game):
    """宗藩（藩王不入仕）即便 offstage+ming 也不进人才池（按 office_type 排除）。"""
    db, state, content = game
    name, ch = _materialized_prince(db, state, content)
    db.set_character_status(state, name, "offstage", "测试")
    assert db.characters.get_character_status(name)[0] == "offstage"  # 物化后 setup 真生效
    assert in_talent_pool(ch, db, state.year, state.period) is False


def test_amnestied_rebel_excluded_from_talent_pool(game):
    """流寇按 faction 排除，非 office_type——盘面无 office_type=流寇（实为 外臣/未仕）。
    招抚归明后 power_id 翻 ming（character_power_changes），若仅靠 power_id 闸会把前流寇漏进
    起复池；faction='流寇' 才是真闸。故设 offstage + power_id=ming（招抚末态），断言仍排除。"""
    db, state, content = game
    name = next(
        (n for n, c in content.characters.items() if getattr(c, "faction", "") == "流寇"),
        None,
    )
    if name is None:
        import pytest
        pytest.skip("基底盘面无流寇人物")
    ch = content.characters[name]
    db.set_character_status(state, name, "offstage", "测试：招抚后罢居")
    db.conn.execute("UPDATE characters SET power_id='ming' WHERE name=?", (name,))
    db.conn.commit()
    assert db.characters.get_character_status(name)[0] == "offstage"
    assert in_talent_pool(ch, db, state.year, state.period) is False


def test_same_year_future_month_debut_excluded_from_talent_pool(game):
    """登场判据须对齐 db.apply_historical_debuts 的 year+month：同年但月份未到
    （debut_month 晚于当前 period）的人物仍未登场，不得提前进人才池（剧透）。"""
    db, state, content = game
    if state.period >= 12:
        import pytest
        pytest.skip("当前已是年末，无法构造同年未来月份")
    name = _active_ming_minister(db, content)
    ch = content.characters[name]
    orig = (ch.debut_year, ch.debut_month)
    try:
        db.set_character_status(state, name, "offstage", "测试")
        ch.debut_year, ch.debut_month = state.year, state.period + 1  # 同年下月才登场
        assert in_talent_pool(ch, db, state.year, state.period) is False
        ch.debut_month = state.period  # 月份已到 → 视为已登场，可进池
        assert in_talent_pool(ch, db, state.year, state.period) is True
    finally:
        # content fixture 是 session 作用域，还原内存 debut 字段防跨用例污染
        ch.debut_year, ch.debut_month = orig


def test_consort_excluded_from_court(read_game):
    """后宫不算朝堂大臣，DB active 也不入列。"""
    db, _state, content = read_game
    consort = next(
        (n for n, c in content.characters.items()
         if getattr(c, "office_type", "") == "后宫"),
        None,
    )
    if consort is None:
        import pytest
        pytest.skip("基底盘面无后宫人物")
    assert visible_in_court(content.characters[consort], db) is False


def test_zongfan_cannot_be_summoned_via_can_summon(game):
    """summon_minister 工具链（session 召对 + web 流式两路）共用 session.can_summon 闸——宗藩须在此拒，
    否则裁判可绕朝堂列表按名召宗室（cmr R4：_require_active_minister 只守 /chat 直连，summon 工具走
    can_summon）。集中守 can_summon 一处覆盖两路；后宫不受此闸影响。"""
    import pytest
    from ming_sim.session import GameSession
    db, state, content = game
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.temporary_characters = {}
    prince = next((n for n, c in content.characters.items() if c.office_type == "宗藩"), None)
    if prince is None:
        pytest.skip("基底盘面无宗藩人物")
    db.add_character(state, content.characters[prince], source="测试物化")
    db.set_character_status(state, prince, "active", "测试：在世")
    assert db.characters.get_character_status(prince)[0] == "active"  # 即便 active 也拒
    ok, _reason = sess.can_summon(content.characters[prince])
    assert ok is False
    # 后宫不受宗藩闸影响：active+ming 后宫仍可召
    consort = next((n for n, c in content.characters.items()
                    if c.office_type == "后宫" and getattr(c, "power_id", "ming") == "ming"), None)
    if consort:
        db.add_character(state, content.characters[consort], source="测试物化")
        db.set_character_status(state, consort, "active", "测试")
        ok2, _ = sess.can_summon(content.characters[consort])
        assert ok2 is True


def _bare_session(db):
    from ming_sim.session import GameSession
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.temporary_characters = {}
    return sess


def _enemy_active_name(db, content) -> str:
    """content 里有、且 DB 权威 power_id 非 ming、status=active 的人物（皇太极等外藩）。"""
    import pytest
    for name, ch in content.characters.items():
        row = db.conn.execute("SELECT power_id, status FROM characters WHERE name=?", (name,)).fetchone()
        if row and (row["power_id"] or "ming") != "ming" and row["status"] == "active":
            return name
    pytest.skip("基底盘面无 active 外藩人物")


def test_enemy_active_character_cannot_be_summoned(read_game):
    """非大明势力（后金/蒙古/朝鲜/流寇）即便 active 也不可召见——皇帝召的是大明朝廷命官，
    不能召对敌酋（如皇太极）。can_summon 是 summon_minister 工具链共用闸，集中守此一处（#125）。
    现状 bug：can_summon 只查 status，active 外藩按名召直接放行。"""
    db, state, content = read_game
    sess = _bare_session(db)
    enemy = _enemy_active_name(db, content)
    assert db.characters.get_character_status(enemy)[0] == "active"  # active 也拒
    ok, _reason = sess.can_summon(content.characters[enemy])
    assert ok is False


def test_summon_power_check_uses_db_not_content(game):
    """招抚归明者：流寇/降将 power_id 经 apply_character_power_changes 翻 ming，但 content/内存
    仍是旧势力。can_summon 须认 **DB 权威 power_id**，否则按内存把归明者误拒在朝堂外（#125 核心）。"""
    db, state, content = game
    sess = _bare_session(db)
    # 找一个 content 内存非 ming 的人物，把其 DB power_id 翻成 ming（模拟招抚归明落库）
    name = next((n for n, c in content.characters.items()
                 if getattr(c, "power_id", "ming") != "ming"
                 and c.office_type not in ("后宫", "宗藩", "未仕")), None)
    import pytest
    if name is None:
        pytest.skip("基底盘面无非 ming 可招抚人物")
    db.conn.execute("UPDATE characters SET power_id='ming' WHERE name=?", (name,))
    db.conn.commit()
    db.set_character_status(state, name, "active", "测试：招抚归明")
    assert getattr(content.characters[name], "power_id", "ming") != "ming"  # 内存仍旧势力
    ok, reason = sess.can_summon(content.characters[name])
    assert ok is True, f"DB 已归明却被内存值误拒：{reason}"


def test_find_existing_minister_uses_db_power_id(game):
    """真实任命认 DB 归明身份；外藩不得因在世而被授大明官职。"""
    import pytest
    from ming_sim import issues
    db, state, content = game
    # 招抚归明者：DB 翻 ming、content 仍非 ming、active → 应被 _find_existing_minister 命中
    归明 = next((n for n, c in content.characters.items()
                if getattr(c, "power_id", "ming") != "ming"
                and c.office_type not in ("后宫", "宗藩", "未仕") and c.status != "candidate"), None)
    if 归明 is None:
        pytest.skip("基底盘面无非 ming 可招抚人物")
    db.conn.execute("UPDATE characters SET power_id='ming' WHERE name=?", (归明,))
    db.conn.commit()
    db.set_character_status(state, 归明, "active", "测试：招抚归明")
    appointed = issues.apply_office_appointment(
        db, state, content, 归明, "兵部郎中", new_office_type="兵部",
    )
    assert not appointed.get("rejected"), appointed
    assert db.conn.execute("SELECT office FROM characters WHERE name=?", (归明,)).fetchone()["office"] == "兵部郎中"
    enemy = _enemy_active_name(db, content)
    before = dict(db.conn.execute("SELECT * FROM characters WHERE name=?", (enemy,)).fetchone())
    refused = issues.apply_office_appointment(
        db, state, content, enemy, "兵部郎中", new_office_type="兵部",
    )
    assert refused.get("rejected") is True
    assert dict(db.conn.execute("SELECT * FROM characters WHERE name=?", (enemy,)).fetchone()) == before


# ── #1317 r2：身份归一 ≠ 可召资格；未仕/宗藩别名解析 + 可召排未仕 ──────────


def _session_stub(db, content):
    from ming_sim.session import GameSession

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.content = content
    sess.temporary_characters = {}
    return sess


def test_identity_resolves_weishi_and_vassal_aliases_no_duplicate_file(game):
    """#1317 r2 钉：身份归一认识未仕/宗藩——史宪之入仕不建重档；福王别名撞宗藩闸。"""
    from ming_sim import issues

    db, state, content = game

    assert "史可法" in content.characters
    assert "史宪之" in (content.characters["史可法"].aliases or [])

    before = {
        r["name"]
        for r in db.conn.execute("SELECT name FROM characters").fetchall()
    }
    res = issues.apply_office_appointment(
        db, state, content, "史宪之", "兵部职方司主事",
        reason="#1317 r2 别名入仕", new_office_type="兵部",
    )
    assert not res.get("rejected"), res
    assert res.get("name") == "史可法"
    after = {
        r["name"]
        for r in db.conn.execute("SELECT name FROM characters").fetchall()
    }
    assert after == before, f"史宪之入仕不得建重档，多出：{after - before}"
    row = db.conn.execute(
        "SELECT status, office FROM characters WHERE name=?", ("史可法",),
    ).fetchone()
    assert row["status"] == "active"
    assert "职方" in (row["office"] or "") or "兵部" in (row["office"] or "")

    # 福王别名 → 朱常洵 → 宗藩硬闸，不建档
    prince = next(
        (n for n, c in content.characters.items()
         if c.office_type == "宗藩" and "福王" in (c.aliases or [])),
        None,
    )
    assert prince is not None, "seed 须有福王别名宗藩（朱常洵）"
    before_p = {
        r["name"]
        for r in db.conn.execute("SELECT name FROM characters").fetchall()
    }
    res_p = issues.apply_office_appointment(
        db, state, content, "福王", "兵部尚书", reason="幻觉授宗藩",
    )
    assert res_p.get("rejected") is True
    after_p = {
        r["name"]
        for r in db.conn.execute("SELECT name FROM characters").fetchall()
    }
    assert after_p == before_p, f"福王别名不得建重档，多出：{after_p - before_p}"


def test_choose_minister_real_entry_excludes_weishi_includes_court(game, monkeypatch):
    """#1317 r2：CLI choose_minister 真入口与可召谓词同口径（排未仕，留真臣）。"""
    from ming_sim.cli import terminal as term

    db, state, content = game
    sess = _session_stub(db, content)
    sess.state = state

    # Active status must not bypass the real CLI admission gate.
    db.conn.execute(
        "UPDATE characters SET status='active',location='beizhili',transit_to='' "
        "WHERE name IN (?,?)", ("史可法", "温体仁"),
    )
    db.conn.commit()

    answers = iter(("史可法", "温体仁"))
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: next(answers))
    chosen = term.choose_minister(sess)
    assert chosen is content.characters["温体仁"]


def test_role_roster_only_lists_current_active_ming_people(game):
    db, state, content = game
    names = list(content.characters)[:4]
    for name, status, debut_year, power_id in zip(
        names, ("dismissed", "offstage", "active", "active"),
        (0, 0, state.year + 1, 0), ("ming", "ming", "ming", "houjin"),
    ):
        db.conn.execute(
            "UPDATE characters SET office_type='礼部', status=?, debut_year=?, power_id=? WHERE name=?",
            (status, debut_year, power_id, name),
        )
    db.conn.commit()
    listed = {row["name"] for row in db.characters.current_court_rows(state.year, state.period)}
    assert set(names).isdisjoint(listed)
