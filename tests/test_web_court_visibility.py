from __future__ import annotations
import pytest
from tests.test_qa_c2_settlement_display_lifecycle_1343 import _shell
"""#104: 朝堂大臣列表按 DB 权威状态过滤 offstage（离场/未登场不入列）。

回归要点：过滤须用 db.characters.get_character_status（DB 权威），**不能用内存 c.status**——
auto-debut 等路径（db.set_character_status）只写 DB、不回写内存，c.status 会 stale。
issue #104 原提议的 `c.status != "offstage"` 会把「DB 已 active 但内存仍 offstage」
的已登场人物（如 debut 后的李自成/郑成功）永久挡在朝堂外，比原 bug 更糟。
"""





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
    db, state, content = read_game
    name = _active_ming_minister(db, content)
    assert content.characters[name].name in {row["name"] for row in _shell(db, state, content).state_payload()["ministers"]}


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
    assert content.characters[name].name not in {row["name"] for row in _shell(db, state, content).state_payload()["ministers"]}


def test_db_offstage_excluded_even_if_memory_active(game):
    """DB 翻 offstage、内存 c.status 仍 active（分叉）→ 应排除（DB 权威）。"""
    db, state, content = game
    name = _active_ming_minister(db, content)
    ch = content.characters[name]
    db.set_character_status(state, name, "offstage", "测试：离场")
    assert ch.status == "active"  # 内存 stale，证明分叉确实存在
    assert ch.name not in {row["name"] for row in _shell(db, state, content).state_payload()["ministers"]}
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
        assert ch.name in {row["name"] for row in _shell(db, state, content).state_payload()["ministers"]}
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


@pytest.mark.parametrize('status, surface', [("active", "ministers"), ("offstage", "talent_pool")])
def test_vassal_prince_excluded_from_court(game, status, surface):
    db, state, content = game
    name, ch = _materialized_prince(db, state, content)
    db.set_character_status(state, name, status, "测试：在世")
    # 物化后 setup 真生效：DB 确为 active+ming（否则仅 office_type 短路，测不出 gate 优先于状态）
    assert db.characters.get_character_status(name)[0] == status
    assert ch.name not in {row["name"] for row in _shell(db, state, content).state_payload()[surface]}


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
    assert content.characters[name].name in {row["name"] for row in _shell(db, state, content).state_payload()["talent_pool"]}
    # 在野不入朝堂列表（两个列表互斥，offstage 只进人才池）
    assert content.characters[name].name not in {row["name"] for row in _shell(db, state, content).state_payload()["ministers"]}


def test_active_minister_not_in_talent_pool(read_game):
    """在朝（active）大臣不进在野池——人才池只补 offstage 这一漏面。"""
    db, state, content = read_game
    name = _active_ming_minister(db, content)
    assert content.characters[name].name not in {row["name"] for row in _shell(db, state, content).state_payload()["talent_pool"]}


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
    assert ch.name not in {row["name"] for row in _shell(db, state, content).state_payload()["talent_pool"]}


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
        assert ch.name not in {row["name"] for row in _shell(db, state, content).state_payload()["talent_pool"]}
        ch.debut_month = state.period  # 月份已到 → 视为已登场，可进池
        assert ch.name in {row["name"] for row in _shell(db, state, content).state_payload()["talent_pool"]}
    finally:
        # content fixture 是 session 作用域，还原内存 debut 字段防跨用例污染
        ch.debut_year, ch.debut_month = orig


def test_consort_excluded_from_court(read_game):
    """后宫不算朝堂大臣，DB active 也不入列。"""
    db, state, content = read_game
    consort = next(
        (n for n, c in content.characters.items()
         if getattr(c, "office_type", "") == "后宫"),
        None,
    )
    if consort is None:
        import pytest
        pytest.skip("基底盘面无后宫人物")
    assert content.characters[consort].name not in {row["name"] for row in _shell(db, state, content).state_payload()["ministers"]}


def test_zongfan_cannot_be_summoned_via_can_summon(game):
    """summon_minister 工具链（session 召对 + web 流式两路）共用 session.can_summon 闸——宗藩须在此拒，
    否则裁判可绕朝堂列表按名召宗室（cmr R4：summon 工具走
    can_summon）。集中守 can_summon 一处覆盖两路；后宫不受此闸影响。"""
    import pytest
    from ming_sim.session import GameSession
    db, state, content = game
    sess = GameSession.__new__(GameSession)
    sess.db = db
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




# ── #1317 r2：身份归一 ≠ 可召资格；未仕/宗藩别名解析 + 可召排未仕 ──────────


def _session_stub(db, content):
    from ming_sim.session import GameSession

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.content = content
    return sess






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
