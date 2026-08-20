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
        if db.get_character_status(name)[0] == "active":
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
    assert db.get_character_status(name)[0] == "active"
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
    assert db.get_character_status(name)[0] == "offstage"  # 物化后 setup 真生效
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
    assert db.get_character_status(name)[0] == "offstage"
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


def _stub_game(monkeypatch, db, content):
    """把 web_app.web_game 换成轻量 stub（复用真 db/content），供 _require_active_minister 端点守门测试。

    #1402：端点改调 session.can_summon 取文案——stub 须挂真 GameSession.can_summon
    （db + temporary_characters），不得再空壳 SimpleNamespace。
    """
    from ming_sim.session import GameSession

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.temporary_characters = {}
    stub = SimpleNamespace(
        session=sess,
        content=content,
        db=db,
        character_power_id=lambda c: web_app._character_power_id(c, db),
    )
    monkeypatch.setattr(web_app, "web_game", stub)


def test_vassal_prince_chat_rejected(game, monkeypatch):
    """宗藩不仅被朝堂列表挡，/chat 端点（_require_active_minister）也须拒绝——否则可绕列表
    按名经 API 直接召对（cmr R1 finding D）。即便 active+ming 也拒。"""
    import pytest
    from fastapi import HTTPException
    db, state, content = game
    name, _ch = _materialized_prince(db, state, content)
    db.set_character_status(state, name, "active", "测试：在世")
    assert db.get_character_status(name)[0] == "active"  # 物化后 setup 真生效：即便 active 也拒
    _stub_game(monkeypatch, db, content)
    with pytest.raises(HTTPException) as ei:
        web_app._require_active_minister(name)
    assert ei.value.status_code == 409
    assert "宗室" in ei.value.detail


def test_active_consort_chat_not_rejected(game, monkeypatch):
    """后宫不在 _require_active_minister 的宗藩闸内——嫔妃 chat 复用本端点，active+ming 后宫
    须能召对（finding D「别误伤后宫」反向锁）。"""
    import pytest
    db, state, content = game
    consort = next(
        (n for n, c in content.characters.items()
         if getattr(c, "office_type", "") == "后宫" and getattr(c, "power_id", "ming") == "ming"),
        None,
    )
    if consort is None:
        pytest.skip("基底盘面无大明后宫人物")
    # 物化进 DB 后 set_character_status 才真生效（选中的 content 后宫未必在 probe.db 旧档，
    # 缺行时 set 是 no-op、status 只靠缺行默认 active 兜——gemini R4）。物化使「active 后宫过闸」可证。
    db.add_character(state, content.characters[consort], source="测试物化")
    db.set_character_status(state, consort, "active", "测试：在位")
    assert db.get_character_status(consort)[0] == "active"
    _stub_game(monkeypatch, db, content)
    web_app._require_active_minister(consort)  # 不抛 = 通过（后宫未被宗藩闸误伤）


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
    assert db.get_character_status(prince)[0] == "active"  # 即便 active 也拒
    ok, reason = sess.can_summon(content.characters[prince])
    assert ok is False
    assert "宗室" in reason
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
    assert db.get_character_status(enemy)[0] == "active"  # active 也拒
    ok, reason = sess.can_summon(content.characters[enemy])
    assert ok is False
    assert "大明" in reason  # 拒因须点明非大明，而非误报「尚未登场」等状态话术


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


def test_normal_ming_minister_still_summonable(read_game):
    """回归：正常大明 active 大臣不受 #125 power 闸影响，照常可召。"""
    db, state, content = read_game
    sess = _bare_session(db)
    name = _active_ming_minister(db, content)
    ok, _ = sess.can_summon(content.characters[name])
    assert ok is True


def test_list_ministers_uses_db_power_id(game):
    """召见名册 list_ministers 须与 can_summon 同口径（DB 权威 power_id，#125 centralize）：
    招抚归明者(DB翻ming/content仍旧势力) 入册；外藩 active 不入册。否则可召却不在册、两端不一致。"""
    from ming_sim.session import GameSession
    import pytest
    db, state, content = game
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.content = content
    # 招抚归明者：content 非 ming，DB 翻 ming → 应入册
    归明 = next((n for n, c in content.characters.items()
                if getattr(c, "power_id", "ming") != "ming"
                and c.office_type not in ("后宫", "宗藩", "未仕")), None)
    if 归明 is None:
        pytest.skip("基底盘面无非 ming 可招抚人物")
    db.conn.execute("UPDATE characters SET power_id='ming' WHERE name=?", (归明,))
    db.conn.commit()
    db.set_character_status(state, 归明, "active", "测试：招抚归明")
    names = {v.name for v in sess.list_ministers()}
    assert 归明 in names, "DB 已归明者却被内存值挡出召见名册"
    # 外藩 active（DB 非 ming）不入册
    enemy = _enemy_active_name(db, content)
    assert enemy not in {v.name for v in sess.list_ministers()}


def test_find_existing_minister_uses_db_power_id(game):
    """_find_existing_minister 是罢黜/任命去重/密令 canonical 的 ming-guard，须与 can_summon 同口径
    （DB 权威，#125 R2 codex high）：招抚归明者(DB翻ming/content仍旧势力)可召就必须可查到（可罢/可任）；
    外藩(皇太极 DB houjin)仍查不到，防误黜外藩的保护不丢。"""
    from ming_sim.session import _find_existing_minister
    import pytest
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
    assert _find_existing_minister(content, 归明, db) == 归明, "DB 已归明者却被内存值挡出 ming-guard（可召不可罢）"
    # 外藩 active（DB houjin）仍查不到（防误黜皇太极）
    enemy = _enemy_active_name(db, content)
    assert _find_existing_minister(content, enemy, db) is None


def test_db_resolve_power_id_authoritative(game):
    """db.resolve_power_id：DB 行 power_id 优先于内存，DB 无行时回退内存，再默认 ming。"""
    db, state, content = game
    name = _active_ming_minister(db, content)
    ch = content.characters[name]
    db.conn.execute("UPDATE characters SET power_id='houjin' WHERE name=?", (name,))
    db.conn.commit()
    assert db.resolve_power_id(ch) == "houjin"  # DB 权威压过内存的 ming
    # DB 无该行 → 回退内存 power_id
    ghost = SimpleNamespace(name="查无此人_测试", power_id="mongol")
    assert db.resolve_power_id(ghost) == "mongol"
    # 内存也无 → 默认 ming
    ghost2 = SimpleNamespace(name="查无此人_测试2")
    assert db.resolve_power_id(ghost2) == "ming"


def test_vassal_prince_secret_order_rejected(read_game, monkeypatch):
    """密令端点 api_create_secret_order 也须拒宗藩（同 /chat 的 API 直连绕过形态，cmr R5）。"""
    import asyncio
    import pytest
    from types import MethodType, SimpleNamespace
    from fastapi import HTTPException
    from ming_sim.session import GameSession
    from web_app import SecretOrderRequest
    db, state, content = read_game
    name = next((n for n, c in content.characters.items() if c.office_type == "宗藩"), None)
    if name is None:
        pytest.skip("基底盘面无宗藩人物")
    sess = SimpleNamespace(content=content, temporary_characters=set(), db=db)
    sess.can_summon = MethodType(GameSession.can_summon, sess)
    stub = SimpleNamespace(
        content=content,
        session=sess,
        character_power_id=lambda c: web_app._character_power_id(c, db),
    )
    monkeypatch.setattr(web_app, "web_game", stub)
    req = SecretOrderRequest(title="密查", content="着尔暗中查访")
    with pytest.raises(HTTPException) as ei:
        asyncio.run(web_app.api_create_secret_order(name, req))
    assert ei.value.status_code == 409
    assert "宗室" in ei.value.detail


def test_secret_order_endpoint_preserves_long_title_into_confirmation(game, monkeypatch):
    """#1357 真缝：长标题经生产 _chat_with_write_gate_held 进入 session.chat 消息。"""
    import asyncio
    from ming_sim.session import ChatTurnResult
    from tests.test_qa_c3_secret_order_path_1357_1376 import (
        webgame_shell_for_secret_order,
    )
    from web_app import SecretOrderRequest

    db, state, content = game
    minister = next(
        c for c in content.characters.values()
        if c.office_type not in ("后宫", "宗藩", "未仕")
        and db.get_character_status(c.name)[0] == "active"
    )
    seen = {}

    def _session_chat(minister_name, message, *, chat_turn_id=0):
        seen.update(name=minister_name, message=message)
        return ChatTurnResult(answer="臣领旨。")

    runtime = webgame_shell_for_secret_order(
        db, state, content, session_chat=_session_chat,
    )
    monkeypatch.setattr(web_app, "web_game", runtime)
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    title = "超过二十个字的密令标题应完整进入确认与持久化恢复链路甲乙丙丁"

    asyncio.run(web_app.api_create_secret_order(
        minister.name, SecretOrderRequest(title=title, content="着尔暗中查访"),
    ))

    assert title in seen["message"]


# ── #1317 r2：身份归一 ≠ 可召资格；未仕/宗藩别名解析 + 可召排未仕 ──────────


def _session_stub(db, content):
    from ming_sim.session import GameSession

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.content = content
    sess.temporary_characters = {}
    return sess


def test_shi_kefa_not_in_summonable_court_roster(read_game):
    """#1317：史可法 office=诸生/未仕，不得以在朝身份入可召名册。

    接缝：list_ministers + can_summon + visible_in_court 三面同拒。
    同型先例：郑成功/张煌言等诸生童生 offstage（非钱谦益——钱为罢居礼部）。
    """
    db, _state, content = read_game
    assert "史可法" in content.characters, "seed 须含史可法"
    ch = content.characters["史可法"]
    assert ch.office_type == "未仕"
    assert "诸生" in (ch.office or "")

    sess = _session_stub(db, content)
    names = {v.name for v in sess.list_ministers()}
    assert "史可法" not in names, "史可法不得入 list_ministers 可召名册"

    ok, reason = sess.can_summon(ch)
    assert ok is False, f"史可法 can_summon 应拒，实际放行 reason={reason!r}"
    assert reason

    assert visible_in_court(ch, db) is False, "史可法不得入 web 朝堂 ministers 投影"


def test_real_court_ministers_not_collateral_damaged_by_1317(read_game):
    """#1317 回归：真在朝大臣（非未仕）仍可召、仍在名册——禁谓词收窄误伤。"""
    db, _state, content = read_game
    sess = _session_stub(db, content)

    for name in ("温体仁", "毕自严", "张瑞图"):
        assert name in content.characters, f"seed 缺 {name}"
        ch = content.characters[name]
        assert ch.office_type != "未仕"
        assert db.get_character_status(name)[0] == "active", name
        assert visible_in_court(ch, db) is True, name
        ok, reason = sess.can_summon(ch)
        assert ok is True, f"{name} 被误伤：{reason}"

    roster_names = {v.name for v in sess.list_ministers()}
    for name in ("温体仁", "毕自严", "张瑞图"):
        assert name in roster_names, f"{name} 被挡出 list_ministers"


def test_no_active_weishi_in_summonable_roster_including_1642_1645(game):
    """#1317 r2 类防御：开局 + 强行 active + 1642/1645 debut 未仕均不漏入可召名册。

    钉张煌言(debut 1642)/郑成功(debut 1645) 等同型诸生童生——不靠单一史可法 seed status。
    """
    from ming_sim.simulation import _extractor_context_payload, build_simulator_payload

    db, state, content = game
    sess = _session_stub(db, content)

    leaked = [
        v.name for v in sess.list_ministers()
        if getattr(content.characters.get(v.name), "office_type", "") == "未仕"
    ]
    assert leaked == [], f"未仕漏入可召名册：{leaked}"

    weishi = [
        (n, c) for n, c in content.characters.items()
        if getattr(c, "office_type", "") == "未仕"
        and getattr(c, "power_id", "ming") == "ming"
    ]
    assert weishi, "seed 须有未仕样本（史可法/郑成功/张煌言等同型）"
    names_pinned = {n for n, _ in weishi}
    assert "张煌言" in names_pinned and int(getattr(content.characters["张煌言"], "debut_year", 0) or 0) == 1642
    assert "郑成功" in names_pinned and int(getattr(content.characters["郑成功"], "debut_year", 0) or 0) == 1645

    for name, ch in weishi:
        db.conn.execute(
            "UPDATE characters SET status='active', power_id='ming' WHERE name=?", (name,),
        )
        db.conn.commit()
        ok, _ = sess.can_summon(ch)
        assert ok is False, f"active 未仕 {name} 仍可召"
        assert name not in {v.name for v in sess.list_ministers()}
        assert visible_in_court(ch, db) is False

    # LLM/extractor 受守面同口径（simulation court_roster / active_ministers）
    sim = build_simulator_payload(state, db, decree_text="", previous_narrative="")
    assert "史可法" not in str(sim.get("court_roster", ""))
    assert "张煌言" not in str(sim.get("court_roster", ""))
    assert "郑成功" not in str(sim.get("court_roster", ""))
    ext = _extractor_context_payload(db, state, narrative="", decree_text="")
    assert "史可法" not in str(ext.get("active_ministers", ""))
    assert "张煌言" not in str(ext.get("active_ministers", ""))
    assert "郑成功" not in str(ext.get("active_ministers", ""))


def test_identity_resolves_weishi_and_vassal_aliases_no_duplicate_file(game):
    """#1317 r2 钉：身份归一认识未仕/宗藩——史宪之入仕不建重档；福王别名撞宗藩闸。"""
    from ming_sim import issues
    from ming_sim.session import _find_existing_minister

    db, state, content = game

    assert "史可法" in content.characters
    assert "史宪之" in (content.characters["史可法"].aliases or [])
    assert _find_existing_minister(content, "史可法", db) == "史可法"
    assert _find_existing_minister(content, "史宪之", db) == "史可法"

    before = {
        r["name"]
        for r in db.conn.execute("SELECT name FROM characters").fetchall()
    }
    res = issues.apply_office_appointment(
        db, state, content, None, "史宪之", "兵部职方司主事",
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
    assert _find_existing_minister(content, "福王", db) == prince
    before_p = {
        r["name"]
        for r in db.conn.execute("SELECT name FROM characters").fetchall()
    }
    res_p = issues.apply_office_appointment(
        db, state, content, None, "福王", "兵部尚书", reason="幻觉授宗藩",
    )
    assert res_p.get("rejected") is True
    assert "宗藩" in str(res_p.get("reason") or "")
    after_p = {
        r["name"]
        for r in db.conn.execute("SELECT name FROM characters").fetchall()
    }
    assert after_p == before_p, f"福王别名不得建重档，多出：{after_p - before_p}"


def test_choose_minister_real_entry_excludes_weishi_includes_court(game, monkeypatch):
    """#1317 r2：CLI choose_minister 真入口与可召谓词同口径（排未仕，留真臣）。"""
    from ming_sim.cli import terminal as term

    db, _state, content = game
    sess = _session_stub(db, content)

    # 强行 active 未仕，确认真入口仍不列
    db.conn.execute(
        "UPDATE characters SET status='active' WHERE name=?", ("史可法",),
    )
    db.conn.commit()

    printed: list[str] = []

    def fake_print(*args, **_kwargs):
        printed.append(" ".join(str(a) for a in args))

    # quit ∈ COURT_BREAK_COMMANDS → 返回 None（退朝），只验证列名册副作用
    monkeypatch.setattr("builtins.print", fake_print)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "quit")

    assert term.choose_minister(sess) is None

    blob = "\n".join(printed)
    assert "可召见大臣" in blob
    assert "史可法" not in blob
    assert "温体仁" in blob or "毕自严" in blob
