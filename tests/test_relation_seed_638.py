"""#638 S7：seed 管线——开局前奠基事件导入器（ADR 0086 机械面）。

接缝（票面验收条钉死，票庭 run 01a02d3f-aa50-7c93-a396-b9f98b39172c 判词通过）：
- 生产缝＝GameSession 新开档构造：导入样例 seed（content/relation_seed.json），
  流水可查、时间戳早于开局、奠基事件入摘要奠基段。
- 导入幂等：重复导入不双写（UNIQUE 吸收＋奠基段字节等重放）。
- 旧档不受影响：game_state 行已存在的存档一律不触。
- 同一套酿制：seed 边经月末腿水位判据照常入酿输入（last_event_id 留 0）。
"""
from __future__ import annotations

import os
import tempfile

import pytest

from ming_sim.content import GameContent
from ming_sim.context import bind_content
import ming_sim.issues as issues_mod
from ming_sim.models import LLMConfig
from ming_sim.relation_seed import pregame_turn
from ming_sim.session import GameSession


@pytest.fixture
def fresh_session(tmp_path, monkeypatch):
    """fresh GameSession 构造即不连 LLM（与 test_new_game_smoke 同一守门形态）。"""
    import ming_sim.cli_backend as _cb
    import ming_sim.llm_model as llm_mod

    def _track_verify(cfg):
        raise AssertionError("fresh 构造不得调用 verify_llm_available")

    def _track_backend(prompt, llm_config=None, tag=""):
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
        try:
            sess.close()
        except Exception:
            pass


def test_seed_document_validation_is_fail_closed():
    """校验 fail-closed：未知类目/未早于开局/空语境/自指对，整份拒收。"""
    from ming_sim.relation_seed import validate_seed_document

    base = {
        "source": "甲", "target": "乙", "event_kind": "结怨",
        "context": "一句语境。", "origin": "seed:test", "year": 1625, "period": 4,
    }

    def _doc(event_overrides=None, **top):
        doc = {"events": [{**base, **(event_overrides or {})}]}
        doc.update(top)
        return doc

    with pytest.raises(ValueError, match="未知边事件类目"):
        validate_seed_document(_doc({"event_kind": "发明的类目"}), opening_year=1627, opening_period=10)
    with pytest.raises(ValueError, match="早于开局"):
        validate_seed_document(_doc({"year": 1627, "period": 10}), opening_year=1627, opening_period=10)
    with pytest.raises(ValueError, match="早于开局"):
        validate_seed_document(_doc({"year": 1628, "period": 1}), opening_year=1627, opening_period=10)
    with pytest.raises(ValueError, match="context"):
        validate_seed_document(_doc({"context": "   "}), opening_year=1627, opening_period=10)
    with pytest.raises(ValueError, match="两端不得相同"):
        validate_seed_document(_doc({"target": "甲"}), opening_year=1627, opening_period=10)
    with pytest.raises(ValueError, match="两端不得相同"):
        validate_seed_document(
            _doc(summaries=[{
                "source": "甲", "target": "甲", "founding_lines": ["自指废行。"],
            }]),
            opening_year=1627,
            opening_period=10,
        )
    # 合法文档归一：turn 刻度非正、词表过验。
    normalized = validate_seed_document(_doc(), opening_year=1627, opening_period=10)
    assert normalized["events"][0]["turn"] == pregame_turn(1625, 4) < 0


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

    sess.db.record_relation_edge_event(
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
    contexts = [e["context"] for e in new_events]
    assert any("二十四大罪" in c for c in contexts), "seed 奠基边未进酿制输入"


def test_pregame_turn_scale_matches_load_state_mapping():
    """开局前刻度：默认开局前一月＝-1；与 start_ym 映射式同锚（1627.10=开局 turn 1）。"""
    from ming_sim.constants import DEFAULT_OPENING_PERIOD, DEFAULT_OPENING_YEAR
    from ming_sim.relation_seed import pregame_turn

    assert (DEFAULT_OPENING_YEAR, DEFAULT_OPENING_PERIOD) == (1627, 10)
    assert pregame_turn(1627, 9) == -1
    assert pregame_turn(1627, 1) == -9
    assert pregame_turn(1625, 4) == (1625 - 1627) * 12 + (4 - 10)


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


def test_seed_failure_rolls_back_new_save_and_retry_imports(tmp_path, monkeypatch):
    """seed 初始化失败不得烧掉 fresh 判据；修复故障后同 DB 可正常重开。"""
    import sqlite3
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
    with pytest.raises(ValueError, match="injected seed failure"):
        GameSession(db_path=db_path, llm_config=cfg, content=content)

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM game_state").fetchone()[0] == 0

    monkeypatch.setattr(seed_mod, "import_bundled_relationship_seed", original_import)
    sess = GameSession(db_path=db_path, llm_config=cfg, content=content)
    try:
        assert sess.db.has_savegame() is True
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
    assert report is not None and doc is not None
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


def test_existing_save_is_never_touched_by_seed_import(game, monkeypatch):
    """旧档不受影响：真实构造 GameSession 后，关系流水/摘要逐字段不变且无导入日志。"""
    import ming_sim.cli_backend as _cb
    import ming_sim.llm_model as llm_mod
    import ming_sim.token_stats as token_stats

    db, _state, content = game
    assert db.has_savegame() is True
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
    logs = []
    monkeypatch.setattr(token_stats, "tlog", logs.append)
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
        assert not any("关系 seed 导入" in message for message in logs)
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
