"""#638 S7：seed 管线——开局前奠基事件导入器（ADR 0086 机械面）。

接缝（票面验收条钉死，票庭 run 01a02d3f-aa50-7c93-a396-b9f98b39172c 判词通过）：
- 生产缝＝GameSession 新开档构造：导入样例 seed（content/relation_seed.json），
  流水可查、时间戳早于开局、奠基事件入摘要奠基段。
- 导入幂等：重复导入不双写（UNIQUE 吸收＋奠基段字节等重放）。
- 旧档不受影响：game_state 行已存在的存档一律不触。
- 同一套酿制：seed 边经月末腿水位判据照常入酿输入（last_event_id 留 0）。
"""
from __future__ import annotations

import sqlite3

import pytest

from ming_sim.content import GameContent
from ming_sim.context import bind_content
import ming_sim.issues as issues_mod
from ming_sim.models import LLMConfig
from ming_sim.session import GameSession


@pytest.fixture
def fresh_session(tmp_path, monkeypatch):
    """fresh GameSession 构造即不连 LLM（与 test_new_game_smoke 同一守门形态）。"""
    import ming_sim.cli_backend as _cb
    import ming_sim.llm_model as llm_mod

    def _track_verify(cfg):
        raise AssertionError("fresh 构造不得调用 verify_llm_available")

    def _track_backend(prompt, llm_config=None, tag="", *, policy=None):
        raise AssertionError(f"fresh 构造不得调用 CLI 后端 tag={tag!r}")

    monkeypatch.setattr(llm_mod, "verify_llm_available", _track_verify)
    monkeypatch.setattr(_cb, "_run_backend_for_config", _track_backend)

    content = GameContent.load()
    bind_content(content)
    issues_mod.bind_content(content)
    cfg = LLMConfig(api_key="", base_url="http://unused", model="unused")
    dbp = str(tmp_path / "newgame.db")
    sess = GameSession(db_path=dbp, llm_config=cfg, content=content)
    try:
        yield sess, content
    finally:
        sess.close()


def test_seeded_pair_flows_into_month_end_brew_selection(fresh_session):
    """同一套酿制（ADR 0086 机械面）：seed 对在真实月末落新事件后，月末腿照常
    选中该对，且 seed 边因水位为 0 一并进入酿制输入。"""
    from ming_sim.relation_brew import collect_new_edge_events, select_brew_targets

    sess, _content = fresh_session
    state = sess.state
    pair_events = [
        e for e in sess.db.get_relation_edge_events()
        if e["source"] == "魏忠贤" and e["target"] == "杨涟"
    ]
    assert pair_events, "样例 seed 缺魏忠贤→杨涟奠基边"

    new_id = sess.db.record_relation_edge_event(
        source="魏忠贤", target="杨涟", event_kind="结怨",
        context="崇祯元年十月新账。",
        origin="test:month-event", turn=int(state.turn),
        year=int(state.year), period=int(state.period),
    )
    targets = select_brew_targets(db=sess.db, year=int(state.year), period=int(state.period))
    match = [t for t in targets if t["source"] == "魏忠贤" and t["target"] == "杨涟"]
    assert match, "seed 对未被月末腿选中"
    assert int(match[0]["watermark"]) == 0, "seed 导入不得推进水位"

    new_events = collect_new_edge_events(
        db=sess.db, source="魏忠贤", target="杨涟", watermark=0,
    )
    ids = {int(event["id"]) for event in new_events}
    assert int(new_id) in ids
    assert {int(event["id"]) for event in pair_events} <= ids


def test_earliest_legal_start_imports_only_earlier_seed_events(tmp_path, monkeypatch):
    """db.py 接受的最早开局也必须能完成真实新档初始化。"""
    import ming_sim.cli_backend as cli_backend
    import ming_sim.llm_model as llm_mod

    monkeypatch.setattr(
        llm_mod, "verify_llm_available",
        lambda cfg: (_ for _ in ()).throw(AssertionError("新档构造不得验证 LLM")),
    )
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("新档构造不得调用 LLM")),
    )
    content = GameContent.load()
    cfg = LLMConfig(api_key="", base_url="http://unused", model="unused")
    sess = GameSession(
        db_path=str(tmp_path / "earliest.db"), llm_config=cfg,
        content=content, start_ym="1627.01",
    )
    try:
        assert (int(sess.state.year), int(sess.state.period)) == (1627, 1)
        events = sess.db.get_relation_edge_events()
        assert events
        assert all((int(row["year"]), int(row["period"])) < (1627, 1) for row in events)
    finally:
        sess.close()


def test_missing_bundled_seed_fails_new_save_and_retry_imports(tmp_path, monkeypatch):
    """必需 bundled seed 缺失时新档响亮失败，恢复后同 DB 可重试。"""
    import ming_sim.cli_backend as cli_backend
    import ming_sim.llm_model as llm_mod
    import ming_sim.relation_seed as seed_mod

    monkeypatch.setattr(llm_mod, "verify_llm_available", lambda cfg: None)
    monkeypatch.setattr(cli_backend, "_run_backend_for_config", lambda *args, **kwargs: "")
    original_bundled_path = seed_mod.bundled_path
    missing_seed_path = tmp_path / "missing" / "relation_seed.json"
    monkeypatch.setattr(seed_mod, "bundled_path", lambda *parts: str(missing_seed_path))
    db_path = str(tmp_path / "missing-seed.db")
    content = GameContent.load()
    cfg = LLMConfig(api_key="", base_url="http://unused", model="unused")

    with pytest.raises(FileNotFoundError):
        GameSession(db_path=db_path, llm_config=cfg, content=content)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM game_state").fetchone()[0] == 0

    monkeypatch.setattr(seed_mod, "bundled_path", original_bundled_path)
    sess = GameSession(db_path=db_path, llm_config=cfg, content=content)
    try:
        assert sess.db.has_state() is True
        assert sess.db.get_relation_edge_events()
    finally:
        sess.close()


_INVALID_SEED_DOCUMENTS = [
    {}, {"summaries": []}, {"events": []},
    *[{"events": [{
        "source": "崔呈秀", "target": "田尔耕", "event_kind": "结怨",
        "context": "一句语境。", "origin": "seed:test", "evidence": False,
        "year": 1625, "period": 4, **override,
    }]} for override in (
        {"evidence": 1}, {"event_kind": "发明的类目"},
        {"year": 1627, "period": 10}, {"year": 1628, "period": 1},
        {"year": 0}, {"year": -1}, {"context": "   "},
        {"target": "崔呈秀"}, {"source": " 崔呈秀"}, {"target": " 田尔耕"},
    )],
    *[{"events": [{
        "source": "崔呈秀", "target": "田尔耕", "event_kind": "结怨",
        "context": "一句语境。", "origin": "seed:test", "evidence": False,
        "year": 1625, "period": 4,
    }], "summaries": summaries} for summaries in (
        [{"source": "崔呈秀", "target": "田尔耕 ", "founding_lines": []}],
        [{"source": "崔呈秀", "target": "崔呈秀", "founding_lines": ["自指废行。"]}],
        [{"source": "崔呈秀", "target": "田尔耕", "founding_lines": [line]}
         for line in ("一", "二")],
    )],
]


def test_invalid_bundled_seed_rolls_back_new_save_and_can_retry(tmp_path, monkeypatch):
    """空 seed 在写入前拒绝，不烧 fresh 判据；恢复合法资源后同 DB 可重试。"""
    import ming_sim.relation_seed as seed_mod

    original_load = seed_mod.load_bundled_seed_document
    db_path = str(tmp_path / "invalid-seed.db")
    content = GameContent.load()
    cfg = LLMConfig(api_key="", base_url="http://unused", model="unused")
    monkeypatch.setattr(seed_mod, "load_bundled_seed_document", lambda: {"events": []})
    with pytest.raises(ValueError):
        GameSession(db_path=db_path, llm_config=cfg, content=content)
    from ming_sim.db import GameDB
    db = GameDB(db_path, content)
    try:
        for invalid in _INVALID_SEED_DOCUMENTS:
            monkeypatch.setattr(seed_mod, "load_bundled_seed_document", lambda: invalid)
            with pytest.raises(ValueError):
                seed_mod.import_bundled_relationship_seed(
                    db, opening_year=1627, opening_period=10,
                )
            assert db.conn.execute("SELECT COUNT(*) FROM game_state").fetchone()[0] == 0
            assert db.conn.execute("SELECT COUNT(*) FROM relation_edge_events").fetchone()[0] == 0
            assert db.conn.execute("SELECT COUNT(*) FROM relation_summaries").fetchone()[0] == 0
    finally:
        db.close()

    monkeypatch.setattr(seed_mod, "load_bundled_seed_document", original_load)
    sess = GameSession(db_path=db_path, llm_config=cfg, content=content)
    try:
        # 恢复合法 seed 后同 DB 可重试；盖印把柄为游戏/野史边，不得 evidence:true。
        cover = sess.db.get_relation_edge_events(source="崔呈秀", target="田尔耕")
        assert cover and all(row["evidence"] is False for row in cover)
        assert any(row["event_kind"] == "把柄" for row in cover)
    finally:
        sess.close()


def test_seed_founding_write_does_not_swallow_execute_error_with_bad_rollback():
    """窄写口不擅自 rollback；因此 rollback 故障不能遮蔽原始写入异常。"""
    from ming_sim.db import GameDB

    class FailingConnection:
        def execute(self, *args, **kwargs):
            raise RuntimeError("injected write failure")

        def rollback(self):
            raise AssertionError("写口不得拥有 rollback")

    class FakeDB:
        conn = FailingConnection()

        @staticmethod
        def owns_transaction():
            return True

    with pytest.raises(RuntimeError):
        GameDB.apply_seed_founding_segment(
            FakeDB(), source="甲", target="乙", dimension="大臣", founding_segment="旧事"
        )


def test_seed_failure_rolls_back_new_save_and_retry_imports(tmp_path, monkeypatch):
    """seed 初始化失败不得烧掉 fresh 判据；修复故障后同 DB 可正常重开。"""
    import ming_sim.cli_backend as cli_backend
    import ming_sim.llm_model as llm_mod
    import ming_sim.relation_seed as seed_mod

    monkeypatch.setattr(llm_mod, "verify_llm_available", lambda cfg: None)
    monkeypatch.setattr(cli_backend, "_run_backend_for_config", lambda *args, **kwargs: "")
    original_import = seed_mod.import_bundled_relationship_seed
    monkeypatch.setattr(
        seed_mod, "import_bundled_relationship_seed",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("injected seed failure")),
    )
    db_path = str(tmp_path / "retry.db")
    content = GameContent.load()
    cfg = LLMConfig(api_key="", base_url="http://unused", model="unused")
    with pytest.raises(ValueError):
        GameSession(db_path=db_path, llm_config=cfg, content=content)

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM game_state").fetchone()[0] == 0

    monkeypatch.setattr(seed_mod, "import_bundled_relationship_seed", original_import)
    sess = GameSession(db_path=db_path, llm_config=cfg, content=content)
    try:
        assert sess.db.has_state() is True
        assert sess.db.get_relation_edge_events()
    finally:
        sess.close()


def test_new_save_imports_sample_seed_ledger_queryable_and_pregame(fresh_session):
    """新开档导入样例 seed：流水可查、时间戳早于开局（验收条①前半）。"""
    sess, _content = fresh_session
    state = sess.state
    events = sess.db.get_relation_edge_events()
    assert events, "新开档样例 seed 未导入：边事件流水为空"
    opening = (int(state.year), int(state.period))
    for event in events:
        assert (int(event["year"]), int(event["period"])) < opening, (
            f"seed 边事件时间戳不早于开局：{dict(event)}"
        )
        assert int(event["turn"]) <= 0, f"seed 边事件 turn 落进游戏内刻度：{dict(event)}"


def test_reverse_chronological_seed_keeps_latest_event_readable(fresh_session):
    """逆序素材按史时稳定写入。"""
    from ming_sim.relation_seed import import_relationship_seed

    sess, _content = fresh_session
    doc = {"events": [
        {"source": "甲", "target": "乙", "event_kind": "结怨", "context": "后事。",
         "origin": "seed:later", "evidence": False, "year": 1626, "period": 2},
        {"source": "甲", "target": "乙", "event_kind": "结怨", "context": "前事。",
         "origin": "seed:earlier", "evidence": False, "year": 1625, "period": 2},
    ]}
    import_relationship_seed(sess.db, doc, opening_year=1627, opening_period=10)
    rows = sess.db.get_relation_edge_events(source="甲", target="乙")
    assert [(row["year"], row["period"]) for row in rows] == [(1625, 2), (1626, 2)]


def test_pre_tianqi_seed_event_retains_structured_clock(fresh_session):
    from ming_sim.relation_seed import import_relationship_seed

    sess, _content = fresh_session
    doc = {"events": [{
        "source": "丙", "target": "丁", "event_kind": "结怨", "context": "旧事。",
        "origin": "seed:1620", "evidence": False, "year": 1620, "period": 1,
    }]}
    import_relationship_seed(sess.db, doc, opening_year=1627, opening_period=10)
    rows = sess.db.get_relation_edge_events(source="丙", target="丁")
    assert [(row["year"], row["period"]) for row in rows] == [(1620, 1)]


def test_repeated_import_is_idempotent_no_double_write(fresh_session):
    """导入幂等：同一文档重复导入不双写（验收条③）。"""
    sess, _content = fresh_session
    state = sess.state
    events_before = [dict(row) for row in sess.db.get_relation_edge_events()]
    summaries_before = {
        (row["source"], row["target"]): dict(row)
        for row in sess.db.get_relation_summaries()
    }

    from ming_sim.relation_seed import (
        import_bundled_relationship_seed,
        load_bundled_seed_document,
    )
    doc = load_bundled_seed_document()
    report = import_bundled_relationship_seed(
        sess.db, opening_year=int(state.year), opening_period=int(state.period)
    )
    assert doc
    assert report["events_imported"] == 0, f"重复导入新写了边事件：{report}"
    assert report["events_total"] == len(events_before)

    events_after = [dict(row) for row in sess.db.get_relation_edge_events()]
    assert events_after == events_before, "重复导入后流水发生变化"
    summaries_after = {
        (row["source"], row["target"]): dict(row)
        for row in sess.db.get_relation_summaries()
    }
    # 奠基段字节不变（updated_at 变化不在比较面：dict 含该键，逐字段比内容）。
    for key, before_row in summaries_before.items():
        after_row = summaries_after[key]
        assert after_row["founding_segment"] == before_row["founding_segment"]
        assert after_row["recent_segment"] == before_row["recent_segment"]
        assert int(after_row["last_event_id"]) == int(before_row["last_event_id"])


def test_seed_replay_does_not_overwrite_later_brew_summary(fresh_session):
    """已有摘要即 no-op：brew 追加后的全部摘要字段不得被 seed 重放改回。"""
    from ming_sim.relation_seed import import_relationship_seed

    sess, _content = fresh_session
    source, target = "皇帝", "王承恩"
    old = sess.db.get_relation_summary(source, target)
    sess.db.apply_relation_brew_result(
        source=source, target=target, dimension=old["dimension"],
        founding_segment=str(old["founding_segment"]) + "\n后添奠基。",
        recent_segment="后来近况。", last_event_id=17,
        turn=8, year=1628, period=5,
    )
    before = sess.db.get_relation_summary(source, target)
    doc = {
        "events": [{
            "source": source, "target": target, "event_kind": "恩义", "context": "信邸旧事。",
            "origin": "seed:replay-check", "evidence": True, "year": 1626, "period": 2,
        }],
        "summaries": [{"source": source, "target": target, "founding_lines": ["信邸旧事。"]}],
    }
    first = import_relationship_seed(sess.db, doc, opening_year=1627, opening_period=10)
    events_after_first = len(sess.db.get_relation_edge_events())
    second = import_relationship_seed(sess.db, doc, opening_year=1627, opening_period=10)
    assert first["summaries_written"] == second["summaries_written"] == 0
    assert len(sess.db.get_relation_edge_events()) == events_after_first
    assert sess.db.get_relation_summary(source, target) == before


def test_existing_save_is_never_touched_by_seed_import(game, monkeypatch):
    """旧档不受影响：真实构造 GameSession 后，关系流水/摘要逐字段不变且无导入日志。"""
    import ming_sim.cli_backend as _cb
    import ming_sim.llm_model as llm_mod

    db, _state, content = game
    assert db.has_state() is True
    events_before = [tuple(row) for row in db.conn.execute(
        "SELECT * FROM relation_edge_events ORDER BY id"
    ).fetchall()]
    summaries_before = [tuple(row) for row in db.conn.execute(
        "SELECT * FROM relation_summaries ORDER BY source, target"
    ).fetchall()]
    db_path = db.path
    db.close()

    monkeypatch.setattr(
        llm_mod, "verify_llm_available",
        lambda cfg: (_ for _ in ()).throw(AssertionError("读旧档不得验证 LLM")),
    )
    monkeypatch.setattr(
        _cb, "_run_backend_for_config",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("读旧档不得调用 LLM")),
    )
    cfg = LLMConfig(api_key="", base_url="http://unused", model="unused")
    sess = GameSession(db_path=db_path, llm_config=cfg, content=content)
    try:
        events_after = [tuple(row) for row in sess.db.conn.execute(
            "SELECT * FROM relation_edge_events ORDER BY id"
        ).fetchall()]
        summaries_after = [tuple(row) for row in sess.db.conn.execute(
            "SELECT * FROM relation_summaries ORDER BY source, target"
        ).fetchall()]
        assert events_after == events_before
        assert summaries_after == summaries_before
    finally:
        sess.close()


def test_new_save_seed_founding_events_enter_founding_segment(fresh_session):
    """新开档导入样例 seed：奠基事件入摘要奠基段（验收条①后半）。"""
    sess, _content = fresh_session
    summaries = {
        (row["source"], row["target"]): row for row in sess.db.get_relation_summaries()
    }
    # 样例 seed 自带可选初始摘要（皇帝→王承恩 信邸君臣边）；奠基段必须非空。
    assert ("皇帝", "王承恩") in summaries, "样例 seed 初始摘要未入摘要层"
    row = summaries[("皇帝", "王承恩")]
    assert row["dimension"] == "君臣"
    founding = str(row["founding_segment"])
    assert founding.strip(), "奠基段为空：可选初始摘要未落"
    assert str(row["recent_segment"]) == "", "seed 导入不得写近况段（近况段归月末酿制）"
    assert int(row["last_event_id"]) == 0, "seed 导入不得推进水位（同一套酿制判据）"


def test_issue_639_seed_owner_audit_corrections(fresh_session):
    """#639 owner 裁决：史料确错改正；野史可留但不得 evidence:true；根本冲突删除。"""
    sess, _content = fresh_session
    events = [dict(row) for row in sess.db.get_relation_edge_events()]

    def by_origin_prefix(prefix: str) -> dict:
        matches = [row for row in events if str(row["origin"]).startswith(prefix)]
        assert len(matches) == 1, f"origin prefix {prefix!r} -> {matches!r}"
        return matches[0]

    # 野史/见闻把柄不得伪装成可核硬史实
    cover = by_origin_prefix("seed:founding:cui-tian-cover")
    assert cover["evidence"] is False
    assert cover["event_kind"] == "把柄"

    # 史料日期确错：崔夜投魏＝天启四年九月；黄立极入阁＝五年八月
    cui = by_origin_prefix("seed:founding:cui-wei-submission")
    assert (cui["year"], cui["period"]) == (1624, 9)
    huang = by_origin_prefix("seed:founding:wei-huangliji-promotion")
    assert (huang["year"], huang["period"]) == (1625, 8)

    # 阎鸣泰：景忠山生祠在天启七年二月，不得倒填开局前；改用史载潜结/召用
    yan = by_origin_prefix("seed:founding:yanmingtai-wei-attach")
    assert (yan["source"], yan["target"]) == ("阎鸣泰", "魏忠贤")
    assert (yan["year"], yan["period"]) == (1625, 6)
    # 李从心：禁天启七年生祠倒填；改魏→李荐引（点名/题本关照），不得复用 works origin
    assert not any(
        str(row["origin"]).startswith("seed:founding:wei-licongxin-works")
        for row in events
    )
    licongxin_edges = [
        row for row in events
        if row["source"] == "李从心" or row["target"] == "李从心"
    ]
    assert len(licongxin_edges) == 1
    li = licongxin_edges[0]
    assert (li["source"], li["target"], li["event_kind"]) == ("魏忠贤", "李从心", "荐引")
    assert str(li["origin"]).startswith("seed:founding:wei-licongxin-patronage")
    assert li["evidence"] is False

    # ADR 0086 三硬锚：盟誓 / 拦升迁 / 私怨（盟誓禁「多年」倒填）
    oath = by_origin_prefix("seed:founding:wei-cui-oath")
    assert (oath["source"], oath["target"], oath["event_kind"]) == (
        "魏忠贤", "崔呈秀", "恩义",
    )
    assert oath["evidence"] is False
    assert (int(oath["year"]), int(oath["period"])) == (1625, 6)

    block = by_origin_prefix("seed:founding:tian-liruolian-block")
    assert (block["source"], block["target"], block["event_kind"]) == (
        "田尔耕", "李若琏", "使绊",
    )
    assert block["evidence"] is False

    grudge = by_origin_prefix("seed:founding:maoyujian-tian-grudge")
    assert (grudge["source"], grudge["target"], grudge["event_kind"]) == (
        "毛羽健", "田尔耕", "结怨",
    )
    assert grudge["evidence"] is False

    # 施/张：史载依媚/生祠碑，不作魏荐引入阁；入阁月=六年七月
    shi = by_origin_prefix("seed:founding:wei-shifenglai-promotion")
    assert (shi["source"], shi["target"], shi["event_kind"]) == ("施凤来", "魏忠贤", "站台")
    assert (shi["year"], shi["period"]) == (1626, 7)
    zhang = by_origin_prefix("seed:founding:wei-zhangruitu-promotion")
    assert (zhang["source"], zhang["target"], zhang["event_kind"]) == (
        "张瑞图", "魏忠贤", "站台",
    )
    assert (zhang["year"], zhang["period"]) == (1626, 7)

    # 郭允厚：矫旨擢太仆少卿＝天启四年十二月（韩爌致仕次月）
    guo = by_origin_prefix("seed:founding:wei-guoyunhou-finance")
    assert (guo["source"], guo["target"], guo["event_kind"]) == ("魏忠贤", "郭允厚", "荐引")
    assert (guo["year"], guo["period"]) == (1624, 12)

    # 王体乾：翼护/保持语义；不得把调旨主语安在王
    wang = by_origin_prefix("seed:founding:wangtiqian-wei-support")
    assert (wang["source"], wang["target"], wang["event_kind"]) == ("王体乾", "魏忠贤", "站台")
    assert (wang["year"], wang["period"]) == (1624, 6)

    # 来宗道 1627.11 入阁晚于开局——删除伪天启末魏荐引入阁；保留开局前依附野史边
    assert not any(
        str(row["origin"]).startswith("seed:founding:wei-laizongdao-promotion")
        for row in events
    )
    lai = by_origin_prefix("seed:founding:laizongdao-wei-attach")
    assert (lai["source"], lai["target"]) == ("来宗道", "魏忠贤")

    # 信邸边：潜邸旧人可留；不得把「新君即位」伪造成 1626 年事实
    for prefix in ("seed:founding:liruolian-xindi", "seed:founding:caohuachun-xindi"):
        row = by_origin_prefix(prefix)
        assert row["source"] == "皇帝"
        assert (int(row["year"]), int(row["period"])) < (1627, 1)

    # 全部 seed 边不得把无核材料标成 evidence:true；且须兼容最早开局 1627.1
    assert all(row["evidence"] is False for row in events)
    assert all((int(row["year"]), int(row["period"])) < (1627, 1) for row in events)

    # 修后精确计数：18+4 事件；魏→崔双事件合并故全知 pair=21
    assert len(events) == 22
    from ming_sim.relation_read import project_relation_ledger

    projection = project_relation_ledger(sess.db, viewer=None)
    assert len(projection) == 21
    assert any(
        row["source"] == "魏忠贤" and row["target"] == "崔呈秀"
        for row in projection
    )
