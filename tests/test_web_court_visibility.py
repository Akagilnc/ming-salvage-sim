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
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if db.get_character_status(name)[0] == "active":
            return name
    raise AssertionError("基底盘面无 active 的大明大臣")


def test_active_ming_minister_visible(game):
    db, _state, content = game
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


def test_active_minister_not_in_talent_pool(game):
    """在朝（active）大臣不进在野池——人才池只补 offstage 这一漏面。"""
    db, state, content = game
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


def test_consort_excluded_from_court(game):
    """后宫不算朝堂大臣，DB active 也不入列。"""
    db, _state, content = game
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
    """把 web_app.web_game 换成轻量 stub（复用真 db/content），供 _require_active_minister 端点守门测试。"""
    stub = SimpleNamespace(
        session=SimpleNamespace(temporary_characters={}),
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


def test_vassal_prince_secret_order_rejected(game, monkeypatch):
    """密令端点 api_create_secret_order 也须拒宗藩（同 /chat 的 API 直连绕过形态，cmr R5）。"""
    import asyncio
    import pytest
    from types import SimpleNamespace
    from fastapi import HTTPException
    from web_app import SecretOrderRequest
    db, state, content = game
    name = next((n for n, c in content.characters.items() if c.office_type == "宗藩"), None)
    if name is None:
        pytest.skip("基底盘面无宗藩人物")
    stub = SimpleNamespace(
        session=SimpleNamespace(content=content),
        character_power_id=lambda c: web_app._character_power_id(c, db),
    )
    monkeypatch.setattr(web_app, "web_game", stub)
    req = SecretOrderRequest(title="密查", content="着尔暗中查访")
    with pytest.raises(HTTPException) as ei:
        asyncio.run(web_app.api_create_secret_order(name, req))
    assert ei.value.status_code == 409
    assert "宗室" in ei.value.detail
