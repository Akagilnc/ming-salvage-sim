"""#501 叙事抽取落账（站台落账 / 补跑抽取 / 响亮错误包 / 收夜前清空待补）。

外部行为契约（PRD #497「restore·崩溃一致性」「召对退出」「抽取链边界」；ADR 0035/0036）：
- 含站台情节的回话跑完 → 账上有该条（涉及人 / 可闻性正确），涉在场变化带机器可读在场效果；
- 注入垃圾 shape → 响亮错误包、不静默丢戏；
- 「回话已持久化、账未抽」→ 补跑抽取成功、对话不回滚；补跑持续失败不锁档、标待补；
- 抽取水位确定性可判：补跑不重复抽、不漏抽；单轮多条账原子（全有或全无）；
- 待补期间派生只认已落账；补账时序键=源对话轮原始时序（补跑落回原位）；
- 收夜前清空待补：成功续收 / 失败 fail-closed 中止收夜。

只 fake LLM 抽取边界（canned facts / 抛错），走真实 GameDB + 真实落账 / 派生 / 补跑编排。
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

import ming_sim.agents as agents_mod
import ming_sim.session as session_mod
import web_app
from ming_sim import audience_night as an
from ming_sim.audience_extraction import (
    ExtractionShapeError,
    catch_up_pending_extractions,
    drain_pending_before_close,
    parse_extraction_facts,
    run_extraction_for_turn,
)


# ── canned 抽取边界（唯一 fake）──────────────────────────────────────────
class _FactsAgent:
    """canned 抽取员：run() 回带 .content 的对象（extract_agent_text 读 .content）。"""

    def __init__(self, output: str):
        self._output = output

    def run(self, _material):  # noqa: D401
        return SimpleNamespace(content=self._output)


class _BoomAgent:
    """接口故障 / 持续失败的抽取员：run() 直接抛。"""

    def run(self, _material):
        raise RuntimeError("接口故障")


_STAGE_FACT_JSON = (
    '{"facts":[{"person_names":["毕自严","洪承畴"],"audibility":"殿上公开",'
    '"body":"毕自严出班为洪承畴站台作保","tags":["站台"],"presence_effect":""}]}'
)


def _minister(db, content) -> str:
    from tests.conftest import active_ming_character

    return active_ming_character(db, content)


def _open_night_with_persisted_reply(db, state, minister, reply="臣愿肩起此事。"):
    """真实开夜 + 宣入 + 建 generating 轮 + 持久化回话（升 active、链接 minister_message）。

    返回 (night_id, chat_turn_id, night_seq)——与生产 attach_chat_turn_to_night +
    persist_minister_reply 同核。回话持久化后 extract_status='' = 待抽（补跑真源）。
    """
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    an.ensure_summon_enter(db, nid, minister)
    ctid = db.create_chat_turn(state, minister, "sess", 0, night_id=nid)
    db.persist_minister_reply(minister, int(state.turn), reply, ctid)
    row = db.conn.execute(
        "SELECT night_seq FROM chat_turns WHERE id=?", (ctid,)
    ).fetchone()
    return nid, ctid, int(row["night_seq"])


# ── parse：shape 校验（AC3 正负）─────────────────────────────────────────
def test_parse_extraction_facts_accepts_valid_and_keeps_presence():
    facts = parse_extraction_facts(
        '{"facts":[{"person_names":["A"],"body":"甲自行退至殿侧",'
        '"presence_effect":"exit","tags":["退侍"]}]}'
    )
    assert len(facts) == 1
    assert facts[0]["person_names"] == ["A"]
    assert facts[0]["presence_effect"] == "exit"
    assert facts[0]["audibility"] == "殿上公开"  # 缺省公开
    # 空情节合法（无显著故事）
    assert parse_extraction_facts('{"facts":[]}') == []


@pytest.mark.parametrize(
    "raw",
    [
        "这不是 JSON",                                   # 非法 JSON
        '{"nope":[]}',                                    # 缺 facts 字段
        '{"facts":{}}',                                   # facts 非数组
        '{"facts":[{"body":""}]}',                        # body 空
        '{"facts":[{"body":"x","audibility":"喊话"}]}',  # 可闻性非法
        '{"facts":[{"body":"x","presence_effect":"fly"}]}',  # 在场效果非法
        '{"facts":[{"body":"x","person_names":"甲"}]}',  # person_names 非数组
    ],
)
def test_parse_extraction_facts_rejects_bad_shape(raw):
    with pytest.raises(ExtractionShapeError):
        parse_extraction_facts(raw)


# ── run_extraction_for_turn：落账 / 错误包（AC1/AC2/AC3/AC8）──────────────
def test_run_extraction_ledgers_staging_fact(game):
    db, state, content = game
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister)

    result = run_extraction_for_turn(
        db=db, minister_name=minister, reply="臣为洪承畴作保。",
        chat_turn_id=ctid, night_id=nid, source_night_seq=seq,
        llm_config=object(), write_gate=threading.Lock(),
        extractor_agent=_FactsAgent(_STAGE_FACT_JSON),
    )
    assert result["status"] == "done"
    assert db.get_story_extract_status(ctid) == "done"

    entries = [e for e in an.list_ledger(db, nid) if e["source_chat_turn_id"] == ctid]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["person_names"] == ["毕自严", "洪承畴"]  # 涉及人正确
    assert entry["audibility"] == "殿上公开"               # 可闻性正确
    assert entry["tags"] == ["站台"]


def test_run_extraction_bad_shape_writes_error_pack_and_marks_pending(game, tmp_path, monkeypatch):
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister)

    result = run_extraction_for_turn(
        db=db, minister_name=minister, reply="臣领旨。",
        chat_turn_id=ctid, night_id=nid, source_night_seq=seq,
        llm_config=object(), write_gate=threading.Lock(),
        extractor_agent=_FactsAgent("垃圾非 JSON 输出{{{"),
    )
    # 响亮错误包、标待补、不静默丢戏；不回滚回话、无账落地。
    assert result["status"] == "pending"
    assert result["error_pack_path"]
    import os
    assert os.path.isdir(result["error_pack_path"])
    assert db.get_story_extract_status(ctid) == "pending"
    assert [e for e in an.list_ledger(db, nid) if e["source_chat_turn_id"] == ctid] == []
    # 回话仍在（不回滚）
    row = db.conn.execute(
        "SELECT status, minister_message_id FROM chat_turns WHERE id=?", (ctid,)
    ).fetchone()
    assert row["status"] == "active" and row["minister_message_id"]


# ── 水位幂等 + 单轮原子（AC6/AC7）────────────────────────────────────────
def test_settle_watermark_idempotent_no_double_ledger(game):
    db, state, content = game
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister)
    facts = parse_extraction_facts(_STAGE_FACT_JSON)

    ids1 = db.settle_story_extraction(ctid, nid, facts, seq)
    assert len(ids1) == 1 and db.get_story_extract_status(ctid) == "done"
    # 已 'done' → 补跑幂等 no-op（不重复落账）
    ids2 = db.settle_story_extraction(ctid, nid, facts, seq)
    assert ids2 == []
    assert len([e for e in an.list_ledger(db, nid) if e["source_chat_turn_id"] == ctid]) == 1


def test_settle_is_atomic_all_or_nothing(game, monkeypatch):
    db, state, content = game
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister)
    two_facts = parse_extraction_facts(
        '{"facts":[{"body":"甲事","person_names":["甲"]},'
        '{"body":"乙事","person_names":["乙"]}]}'
    )
    # 注入「写一半崩溃」：第二条落账前 allocate_night_seq 抛。
    real_alloc = db.allocate_night_seq
    calls = {"n": 0}

    def boom_alloc(night_id):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("崩在第二条")
        return real_alloc(night_id)

    monkeypatch.setattr(db, "allocate_night_seq", boom_alloc)
    with pytest.raises(RuntimeError):
        db.settle_story_extraction(ctid, nid, two_facts, seq)
    # 全有或全无：第一条也回滚、水位未 done。
    assert [e for e in an.list_ledger(db, nid) if e["source_chat_turn_id"] == ctid] == []
    assert db.get_story_extract_status(ctid) != "done"


# ── 补跑抽取（AC4/AC6/AC8）───────────────────────────────────────────────
def test_catch_up_extracts_persisted_reply_without_rollback(game):
    """kill 掉「回话已持久化、账未抽」→ 重启补跑：账落地、对话不回滚。"""
    db, state, content = game
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister, reply="臣为其作保。")

    summary = catch_up_pending_extractions(
        db=db, llm_config=object(), write_gate=threading.Lock(),
        extractor_agent=_FactsAgent(_STAGE_FACT_JSON),
    )
    assert summary["extracted"] == 1 and summary["pending"] == 0
    assert db.get_story_extract_status(ctid) == "done"
    assert len([e for e in an.list_ledger(db, nid) if e["source_chat_turn_id"] == ctid]) == 1
    # 对话不回滚：回话消息仍在。
    msg = db.conn.execute(
        "SELECT content FROM chat_messages WHERE id="
        "(SELECT minister_message_id FROM chat_turns WHERE id=?)", (ctid,)
    ).fetchone()
    assert msg is not None and "作保" in msg["content"]
    # 抽取水位确定性：已 done 的轮不再被补跑扫到（不重复抽）。
    assert db.count_pending_story_extractions(night_id=nid) == 0


def test_catch_up_persistent_failure_does_not_lock_and_marks_pending(game, tmp_path, monkeypatch):
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister)

    # 从不抛（补跑失败不锁档），标待补。
    summary = catch_up_pending_extractions(
        db=db, llm_config=object(), write_gate=threading.Lock(),
        extractor_agent=_BoomAgent(),
    )
    assert summary["pending"] == 1 and summary["extracted"] == 0
    assert db.get_story_extract_status(ctid) == "pending"
    # 恢复照常续、待补可原地重试：换好抽取员补跑成功。
    again = catch_up_pending_extractions(
        db=db, llm_config=object(), write_gate=threading.Lock(),
        extractor_agent=_FactsAgent(_STAGE_FACT_JSON),
    )
    assert again["extracted"] == 1
    assert db.get_story_extract_status(ctid) == "done"


# ── 在场派生只认已落账 + 机器可读在场效果（AC2/AC9）──────────────────────
def test_present_roster_consumes_presence_effect_not_freetext(game):
    db, state, content = game
    minister = _minister(db, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    an.ensure_summon_enter(db, nid, "甲")
    an.ensure_summon_enter(db, nid, "乙")
    assert {"甲", "乙"} <= an.persons_present_tonight(db, nid)

    # 机器可读 exit（非自由文本解析）→ 甲退出在场；正文可随意改写不影响派生（非盯文）。
    ctid = db.create_chat_turn(state, "甲", "s", 0, night_id=nid)
    ctid_seq = db.conn.execute(
        "SELECT night_seq FROM chat_turns WHERE id=?", (ctid,)
    ).fetchone()["night_seq"]
    db.settle_story_extraction(
        ctid, nid,
        [{"person_names": ["甲"], "body": "甲告退（正文可随意改写）", "presence_effect": "exit"}],
        int(ctid_seq),
    )
    present = an.persons_present_tonight(db, nid)
    assert "甲" not in present and "乙" in present


def test_present_roster_ignores_unextracted_reply(game):
    """待补期间派生只认已落账：未抽的回话涉及人不进在场名单（AC9）。"""
    db, state, content = game
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    # 一个未经宣入、仅活在未抽回话里的人物不出现在在场名单。
    ctid = db.create_chat_turn(state, "丙", "s", 0, night_id=nid)
    db.persist_minister_reply("丙", int(state.turn), "丙近前奏事。", ctid)
    assert "丙" not in an.persons_present_tonight(db, nid)


# ── 补跑时序键 = 源对话轮原始时序（AC11）─────────────────────────────────
def test_extraction_order_key_lands_at_source_turn_position(game):
    db, state, content = game
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    # 源轮（seq 早）先建、后续轮（seq 晚）随后建。
    early = db.create_chat_turn(state, "甲", "s", 0, night_id=nid)
    early_seq = db.conn.execute(
        "SELECT night_seq FROM chat_turns WHERE id=?", (early,)
    ).fetchone()["night_seq"]
    db.persist_minister_reply("甲", int(state.turn), "甲奏。", early)
    late = db.create_chat_turn(state, "乙", "s", 0, night_id=nid)
    db.persist_minister_reply("乙", int(state.turn), "乙奏。", late)

    # 早轮的抽取**在晚轮之后**才补跑，仍须落回早轮时间位（order_key 绑源轮 seq）。
    db.settle_story_extraction(
        early, nid, [{"person_names": ["甲"], "body": "甲当场作保"}], int(early_seq)
    )
    timeline = an.list_night_timeline(db, nid)
    seqs = [ev["seq"] for ev in timeline]
    # 抽取账 order_key = early_seq + 0.5，落在早轮(=early_seq)与晚轮(晚 seq)之间。
    ledger_seq = next(
        ev["seq"] for ev in timeline if ev["kind"] == "ledger"
        and ev["payload"].get("source_chat_turn_id") == early
    )
    late_seq = db.conn.execute(
        "SELECT night_seq FROM chat_turns WHERE id=?", (late,)
    ).fetchone()["night_seq"]
    assert early_seq < ledger_seq < late_seq
    assert seqs == sorted(seqs)  # 整条时间轴单调（补跑不颠倒时序）


# ── 收夜前清空待补：成功续收 / 失败 fail-closed（AC10）────────────────────
def test_drain_before_close_clears_pending(game):
    db, state, content = game
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister, reply="臣作保。")
    # 有待补账 → drain 强制同步补跑清空后不抛（收夜可继续）。
    drain_pending_before_close(
        db=db, llm_config=object(), write_gate=threading.Lock(),
        night_id=nid, extractor_agent=_FactsAgent(_STAGE_FACT_JSON),
    )
    assert db.count_pending_story_extractions(night_id=nid) == 0
    assert db.get_story_extract_status(ctid) == "done"


def test_drain_before_close_fail_closed(game, tmp_path, monkeypatch):
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister)
    # 补跑持续失败 → fail-closed 中止收夜（响亮错误包、夜保持开、可原地重试）。
    with pytest.raises(an.AudienceNightError) as ei:
        drain_pending_before_close(
            db=db, llm_config=object(), write_gate=threading.Lock(),
            night_id=nid, extractor_agent=_BoomAgent(),
        )
    assert ei.value.code == "pending_extraction"
    assert ei.value.error_pack_path
    # 夜未被封（保持可续 / 可重试），待补仍在。
    assert an.get_night(db, nid)["status"] != an.NIGHT_STATUS_CLOSED
    assert db.count_pending_story_extractions(night_id=nid) >= 1


# ── web 真实入口 tracer：回话尾随 → 落账；收夜前 drain 门（AC1/AC5/AC10）─────
@pytest.fixture
def web_game(tmp_path, monkeypatch):
    """真实 WebGame（新档、temp DB、离线 LLM）。仅 verify_llm 与 runtime 配置被中和。"""
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    monkeypatch.setattr(session_mod, "verify_llm_available", lambda cfg: None)
    return web_app.WebGame(fresh=False)


def test_web_reply_trail_ledgers_via_real_wiring(web_game, monkeypatch):
    """真实 WebGame：进入召对（开夜挂轮）→ 落回话 → 生产尾随方法落账（AC1）。"""
    game = web_game
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent",
        lambda cfg: _FactsAgent(_STAGE_FACT_JSON),
    )
    minister = _minister(game.db, game.content)
    ctid, _snap = game._start_chat_turn(minister)  # 真实 attach_chat_turn_to_night
    reply = "臣为洪承畴作保，愿以官身担之。"
    game.db.persist_minister_reply(minister, int(game.state.turn), reply, ctid)

    # 生产尾随（chat / chat_stream 的 _spawn_extraction_trail 同核）同步驱动断言。
    result = game._trail_extraction_after_reply(minister, reply, ctid)
    assert result is not None and result["status"] == "done"
    nid = int(game.db.conn.execute(
        "SELECT night_id FROM chat_turns WHERE id=?", (ctid,)
    ).fetchone()["night_id"])
    entries = [e for e in an.list_ledger(game.db, nid) if e["source_chat_turn_id"] == ctid]
    assert len(entries) == 1 and entries[0]["person_names"] == ["毕自严", "洪承畴"]

    # 非召对夜轮（night_id=0）不入故事账（负路）。
    off = game.db.create_chat_turn(game.state, minister, "s", 0)
    assert game._trail_extraction_after_reply(minister, "闲话一句。", off) is None


def test_web_await_inflight_drains_pending_before_close(web_game, monkeypatch):
    """收夜前门（_await_audience_inflight_clear）：带待补 → fail-closed 抛，夜保持开（AC10）。"""
    game = web_game
    minister = _minister(game.db, game.content)
    ctid, _snap = game._start_chat_turn(minister)
    game.db.persist_minister_reply(minister, int(game.state.turn), "臣领旨。", ctid)
    nid = int(game.db.conn.execute(
        "SELECT night_id FROM chat_turns WHERE id=?", (ctid,)
    ).fetchone()["night_id"])

    # 持续失败抽取员 → drain fail-closed 中止收夜。
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda cfg: _BoomAgent())
    with pytest.raises(an.AudienceNightError) as ei:
        web_app._await_audience_inflight_clear(game)
    assert ei.value.code == "pending_extraction"
    assert an.get_night(game.db, nid)["status"] != an.NIGHT_STATUS_CLOSED

    # 换好抽取员 → drain 清空、门放行（收夜可继续）。
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent",
        lambda cfg: _FactsAgent(_STAGE_FACT_JSON),
    )
    web_app._await_audience_inflight_clear(game)
    assert game.db.count_pending_story_extractions(night_id=nid) == 0


# ── L2 落账走账本唯一入口：closed 夜 / 死账 enter 护栏不被旁路 ──────────────
def test_settle_refuses_on_closed_night(game):
    db, state, content = game
    minister = _minister(db, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    ctid = db.create_chat_turn(state, minister, "s", 0, night_id=nid)
    # 本用例只验 settle 的 closed 护栏，跳过 close 编排：直接置夜 closed。
    db.conn.execute("UPDATE audience_nights SET status='closed' WHERE id=?", (nid,))
    db.conn.commit()
    # settle 直灌 closed 夜被账本入口 night_closed 拒写（护栏不被旁路，L2）
    with pytest.raises(an.AudienceNightError) as ei:
        db.settle_story_extraction(
            ctid, nid, [{"body": "站台", "person_names": [minister]}], 1)
    assert ei.value.code == "night_closed"


def test_settle_refuses_dead_actor_enter_but_allows_mention(game):
    db, state, content = game
    minister = _minister(db, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    db.set_character_status(state, minister, "dead", "test 卒")
    # 「进」效果 + 死角色 → 死账校验拒写、整轮回滚、水位未 done
    ctid = db.create_chat_turn(state, minister, "s", 0, night_id=nid)
    with pytest.raises(an.AudienceNightError) as ei:
        db.settle_story_extraction(
            ctid, nid,
            [{"body": "亡者入殿", "person_names": [minister], "presence_effect": "enter"}], 1)
    assert ei.value.code == "dead_present"
    assert db.get_story_extract_status(ctid) != "done"
    # 纯提及（无 enter）不拦：死者作为叙事对象合法落账（死账仅校验「在场」）
    ctid2 = db.create_chat_turn(state, minister, "s", 0, night_id=nid)
    ids = db.settle_story_extraction(
        ctid2, nid, [{"body": f"追赠已故{minister}", "person_names": [minister]}], 2)
    assert len(ids) == 1 and db.get_story_extract_status(ctid2) == "done"


# ── L1 引擎侧 close_night drain 闸（不只挂 web 前门）──────────────────────
def test_engine_close_night_drains_pending_success(game, monkeypatch):
    db, state, content = game
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent",
        lambda *a, **k: _FactsAgent(_STAGE_FACT_JSON))
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister, reply="臣作保。")
    assert db.count_pending_story_extractions(night_id=nid) == 1
    # 带 llm/write_gate → 引擎 close 强制 drain → 收夜成功、水位 done
    result = an.close_night(
        db, state, night_id=nid, llm_config=object(), write_gate=threading.Lock())
    assert result["closed"] is True
    assert an.get_night(db, nid)["status"] == an.NIGHT_STATUS_CLOSED
    assert db.get_story_extract_status(ctid) == "done"


def test_engine_close_night_fail_closed_on_boom(game, monkeypatch, tmp_path):
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda *a, **k: _BoomAgent())
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister)
    # 持续失败 → 引擎 close fail-closed 中止收夜、夜保持开
    with pytest.raises(an.AudienceNightError) as ei:
        an.close_night(
            db, state, night_id=nid, llm_config=object(), write_gate=threading.Lock())
    assert ei.value.code == "pending_extraction"
    assert an.get_night(db, nid)["status"] != an.NIGHT_STATUS_CLOSED


def test_engine_close_night_fail_closed_without_deps(game, tmp_path, monkeypatch):
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister)
    # 无 llm/write_gate 又带待补 = 无从清空又不得带待补收夜 → fail-closed（不静默跳过）
    with pytest.raises(an.AudienceNightError) as ei:
        an.close_night(db, state, night_id=nid)
    assert ei.value.code == "pending_extraction"
    assert an.get_night(db, nid)["status"] != an.NIGHT_STATUS_CLOSED


# ── L3 settle 抛不穿 catch_up：pack + pending（补跑从不抛）──────────────────
def test_settle_failure_surfaces_pending_never_throws(game, tmp_path, monkeypatch):
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister)
    monkeypatch.setattr(
        db, "settle_story_extraction",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("落账崩")))

    # 直路：settle 抛 → run 转 pending + pack，绝不抛
    result = run_extraction_for_turn(
        db=db, minister_name=minister, reply="臣作保。",
        chat_turn_id=ctid, night_id=nid, source_night_seq=seq,
        llm_config=object(), write_gate=threading.Lock(),
        extractor_agent=_FactsAgent(_STAGE_FACT_JSON),
    )
    assert result["status"] == "pending" and result["error_pack_path"]
    assert db.get_story_extract_status(ctid) == "pending"
    # 补跑路：catch_up 逐轮不抛穿（AC8「补跑从不抛」）
    summary = catch_up_pending_extractions(
        db=db, llm_config=object(), write_gate=threading.Lock(),
        extractor_agent=_FactsAgent(_STAGE_FACT_JSON),
    )
    assert summary["pending"] >= 1


# ── L4 空白回话 → done（不占永久待补阻塞 drain）────────────────────────────
def test_blank_reply_marked_done_and_closeable(game):
    db, state, content = game
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister, reply="   ")
    # 空白完整回话经 run → done（无需 LLM），不永久占待补
    result = run_extraction_for_turn(
        db=db, minister_name=minister, reply="   ",
        chat_turn_id=ctid, night_id=nid, source_night_seq=seq,
        llm_config=None, write_gate=threading.Lock(),
    )
    assert result["status"] == "done" and result.get("fact_count") == 0
    assert db.count_pending_story_extractions(night_id=nid) == 0
    # 无待补 → 可正常收夜（无需 llm/write_gate）
    assert an.close_night(db, state, night_id=nid)["closed"] is True


# ── L5 待补对玩家可读 + 原地重试（并入既有补跑通道）────────────────────────
def test_pending_readable_and_retry_via_web(web_game, monkeypatch):
    game = web_game
    minister = _minister(game.db, game.content)
    ctid, _snap = game._start_chat_turn(minister)
    game.db.persist_minister_reply(minister, int(game.state.turn), "臣作保。", ctid)
    # 抽取失败留下待补
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda *a, **k: _BoomAgent())
    game._trail_extraction_after_reply(minister, "臣作保。", ctid)
    status = game.pending_story_extractions()
    assert status["count"] >= 1
    assert any(p["chat_turn_id"] == ctid for p in status["pending"])
    # 点重试（换好抽取员）→ 水位 done、待补清零
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent",
        lambda *a, **k: _FactsAgent(_STAGE_FACT_JSON))
    after = game.retry_story_extractions()
    assert after["count"] == 0
    assert game.db.get_story_extract_status(ctid) == "done"
