"""新档冒烟（#96 release 清单 / #92 E2E 确定性核）：开新档 → driver.run_settle 跑 3 回合全链
（pre_settle 固定财政 tick → settle_with_delta 落库/inertia/结局/推进，同真实核 ADR 0004）→
restore 接续。含 #66 省级财政基座 shadow 推进的真实链路验证。无需 LLM（driver 收确定性 delta）。

实玩（真 LLM 邸报/extractor + 浏览器多机兼容）是另一层，需真人 + LLM 后端，不在本确定性冒烟内。
"""
import json
import os
import sqlite3
import tempfile

import pytest

from ming_sim.content import GameContent
from ming_sim.context import bind_content
from ming_sim.db import GameDB
import ming_sim.issues as issues_mod
from ming_sim.models import LLMConfig
from ming_sim.session import GameSession
from driver import run_settle, open_game


def _shaanxi_settle(db):
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    return json.loads(str(row["fiscal"] or "{}")).get("settle")


def _shaanxi_source_arrears(db):
    return float(db.conn.execute(
        """
        SELECT COALESCE(SUM(province_pay_arrears), 0) AS total
        FROM armies
        WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
          AND pay_source_region = 'shaanxi'
          AND province_pay_share > 0
        """
    ).fetchone()["total"] or 0)


@pytest.fixture
def fresh_game_dir(tmp_path, monkeypatch):
    """#1228：fresh GameSession 构造即不连 LLM；夹具期间拦截连通/后端调用。"""
    import ming_sim.cli_backend as _cb
    import ming_sim.llm_model as llm_mod

    calls: list[str] = []

    def _track_verify(cfg):
        calls.append("verify_llm_available")
        raise AssertionError("fresh 构造不得调用 verify_llm_available")

    def _track_backend(prompt, llm_config=None, tag=""):
        calls.append(f"backend:{tag or ''}")
        raise AssertionError(f"fresh 构造不得调用 CLI 后端 tag={tag!r}")

    monkeypatch.setattr(llm_mod, "verify_llm_available", _track_verify)
    monkeypatch.setattr(_cb, "_run_backend_for_config", _track_backend)

    content = GameContent.load()
    bind_content(content)
    issues_mod.bind_content(content)
    cfg = LLMConfig(api_key="", base_url="http://unused", model="unused")
    dbp = str(tmp_path / "newgame.db")
    sess = GameSession(db_path=dbp, llm_config=cfg, content=content)
    assert calls == [], f"fresh 构造零 LLM 调用，实得 {calls}"
    try:
        yield sess, dbp, content
    finally:
        try:
            sess.close()
        except Exception:
            pass


def test_new_game_has_fiscal_substrate(fresh_game_dir):
    sess, _dbp, _content = fresh_game_dir
    settle = _shaanxi_settle(sess.db)
    assert isinstance(settle, dict) and "st" in settle and "p" in settle, \
        "新档陕西应带 #66 省级财政基座"
    assert settle["st"]["军饷欠"] == pytest.approx(_shaanxi_source_arrears(sess.db))


def test_new_game_enforces_foreign_keys_without_seed_violations(fresh_game_dir):
    sess, _dbp, _content = fresh_game_dir
    assert sess.db.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert sess.db.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_unknown_event_id_fails_without_synthesizing_parent(fresh_game_dir):
    sess, _dbp, _content = fresh_game_dir
    event_id = "__unknown_event_1026__"
    with pytest.raises(ValueError, match="未定义事件"):
        sess.db.mark_event_triggered(sess.state, event_id)
    assert sess.db.conn.execute(
        "SELECT 1 FROM events WHERE id=?", (event_id,),
    ).fetchone() is None


def test_unknown_office_type_fails_without_synthesizing_parent(fresh_game_dir):
    sess, _dbp, _content = fresh_game_dir
    minister = sess.db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' LIMIT 1"
    ).fetchone()[0]
    with pytest.raises(ValueError, match="未定义官类"):
        sess.db.set_character_office(minister, "试授虚衔", "__unknown_office_1026__")
    assert sess.db.conn.execute(
        "SELECT 1 FROM offices WHERE office_type='__unknown_office_1026__'"
    ).fetchone() is None


def test_person_title_kind_does_not_materialize_office_parent(fresh_game_dir):
    sess, _dbp, _content = fresh_game_dir
    minister = sess.db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' LIMIT 1"
    ).fetchone()[0]
    sess.db.set_character_office(minister, "降臣", "身名分")
    assert sess.db.conn.execute(
        "SELECT 1 FROM offices WHERE office_type='身名分'"
    ).fetchone() is None
    assert sess.db.conn.execute(
        "SELECT 1 FROM character_offices WHERE character_name=?", (minister,)
    ).fetchone() is None


def test_existing_office_fk_violation_is_normalized_on_reopen(fresh_game_dir):
    sess, dbp, content = fresh_game_dir
    character = sess.db.conn.execute(
        "SELECT name, office_type FROM characters ORDER BY name LIMIT 1"
    ).fetchone()
    sess.close()
    raw = sqlite3.connect(dbp)
    raw.execute("PRAGMA foreign_keys=OFF")
    raw.execute(
        "UPDATE character_offices SET office_type='__stale_office_1026__' "
        "WHERE character_name=?",
        (character["name"],),
    )
    raw.commit()
    raw.close()

    reopened = GameDB(dbp, content=content)
    try:
        office = reopened.conn.execute(
            "SELECT office_type FROM character_offices WHERE character_name=?",
            (character["name"],),
        ).fetchone()
        assert office["office_type"] == character["office_type"]
        assert reopened.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert reopened.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        reopened.close()


def test_new_game_three_turn_chain_advances_substrate_and_restores(fresh_game_dir):
    sess, dbp, content = fresh_game_dir
    db, state = sess.db, sess.state
    start_turn = state.turn
    seed_tax_arrears = _shaanxi_settle(db)["st"]["民欠旧赋"]
    for i in range(3):
        before = state.turn
        report = run_settle(
            db, state, content,
            {"economy_moves": [{"account": "国库", "delta": 30, "reason": f"smoke{i}"}]},
            narrative=f"第{i}月邸报",
        )
        assert isinstance(report, str)
        assert state.turn == before + 1, f"回合{i} 应推进一回合"
        st = _shaanxi_settle(db)["st"]
        # #66 shadow：固定财政相位每回合推进基座，末态有效（省库非 None、军饷欠有限非负）
        assert st["省库库银"] is not None
        assert st["军饷欠"] == pytest.approx(_shaanxi_source_arrears(db))
    assert state.turn == start_turn + 3
    end_tax_arrears = _shaanxi_settle(db)["st"]["民欠旧赋"]
    assert end_tax_arrears > seed_tax_arrears, \
        f"3 回合后民欠应累积（{seed_tax_arrears}→{end_tax_arrears}），证明基座在固定财政相位真推进"

    # restore：关库重开 → 状态接续（turn 一致 + 基座仍在）
    db.close()
    db2, state2, _content2 = open_game(dbp)
    try:
        assert state2.turn == state.turn, "restore 接续：turn 一致"
        assert _shaanxi_settle(db2) is not None, "restore 后 #66 基座仍在 DB"
    finally:
        db2.close()
