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
import time
from types import SimpleNamespace

import pytest

import ming_sim.agents as agents_mod
import web_app
from ming_sim import audience_night as an
from ming_sim.exceptions import LLMUnavailable
from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE
from ming_sim.audience_extraction import (
    ExtractionShapeError,
    catch_up_pending_extractions,
    drain_pending_before_close,
    parse_extraction_facts,
    run_extraction_for_turn,
)
from ming_sim.models import LLMConfig


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
    # Finished turn reclaims single-flight ownership (no Future/result store):
    # a second claim completes immediately via durable done watermark, no double ledger.
    again = run_extraction_for_turn(
        db=db, minister_name=minister, reply="臣为洪承畴作保。",
        chat_turn_id=ctid, night_id=nid, source_night_seq=seq,
        llm_config=object(), write_gate=threading.Lock(),
        extractor_agent=_FactsAgent(_STAGE_FACT_JSON),
    )
    assert again["status"] == "done"
    assert len([e for e in an.list_ledger(db, nid) if e["source_chat_turn_id"] == ctid]) == 1


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


def test_catch_up_processes_source_turns_serially_even_on_parallel_safe_backend(game):
    """跨轮补跑不得并行：在场派生只认已落账，后轮必须看见前轮已 settle 的进出账。"""
    db, state, content = game
    minister = _minister(db, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    an.ensure_summon_enter(db, nid, minister)
    first = db.create_chat_turn(state, minister, "sess", 0, night_id=nid)
    db.persist_minister_reply(minister, int(state.turn), "臣请退至殿侧。", first)
    second = db.create_chat_turn(state, minister, "sess", 0, night_id=nid)
    db.persist_minister_reply(minister, int(state.turn), "近前再奏。", second)
    seen_present: list[tuple[str, list[str]]] = []
    started = threading.Event()
    release_first = threading.Event()

    class _PresenceAwareAgent:
        def run(self, materials):
            payload = __import__("json").loads(materials)
            reply = str(payload.get("回话原文") or "")
            seen_present.append((reply, list(payload.get("当前在场") or [])))
            if "退至殿侧" in reply:
                started.set()
                assert release_first.wait(5)
                return (
                    '{"facts":[{"body":"自行退至殿侧","person_names":["'
                    + minister + '"],"presence_effect":"exit"}]}'
                )
            return (
                '{"facts":[{"body":"近前再奏","person_names":["'
                + minister + '"],"presence_effect":"enter"}]}'
            )

    cfg = LLMConfig(
        api_key="cli-backend", base_url="", model="m",
        channel="cli", cli_runner="codex",
    )
    worker = threading.Thread(target=lambda: catch_up_pending_extractions(
        db=db, llm_config=cfg, write_gate=threading.Lock(),
        extractor_agent=_PresenceAwareAgent(),
    ))
    worker.start()
    assert started.wait(5)
    time.sleep(0.05)
    assert len(seen_present) == 1
    release_first.set()
    worker.join(5)
    assert not worker.is_alive()
    assert [reply for reply, _present in seen_present] == [
        "臣请退至殿侧。", "近前再奏。",
    ]
    assert minister not in seen_present[1][1]
    assert minister in an.persons_present_tonight(db, nid)


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


def test_extraction_exit_with_open_tag_leaves_all_presence_derivers(game):
    """单一在场模型：抽取退场（presence_effect=exit，tags 为开放叙事标签「退侍」而非口令常量）
    须同时反映于 present_names_at 与 audible_entries_for，不得只在 persons_present_tonight 生效。

    防双真源分叉——present_names_at 若仍只认 tags，退场者会留在名单、其退场后的殿上公开条目
    仍流入其可闻区间（见知泄漏）。"""
    db, state, content = game
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    an.ensure_summon_enter(db, nid, "甲")
    an.ensure_summon_enter(db, nid, "乙")

    ctid = db.create_chat_turn(state, "甲", "s", 0, night_id=nid)
    ctid_seq = db.conn.execute(
        "SELECT night_seq FROM chat_turns WHERE id=?", (ctid,)
    ).fetchone()["night_seq"]
    # 开放叙事标签「退侍」≠ 口令常量 TAG_EXIT；退场只由机器可读 presence_effect 承载。
    db.settle_story_extraction(
        ctid, nid,
        [{"person_names": ["甲"], "body": "甲自行退至殿侧后离去", "presence_effect": "exit",
          "tags": ["退侍"]}],
        int(ctid_seq),
    )
    # 甲退场后又有一条殿上公开入殿账（丙宣入）——甲已不在场，不该闻此后公开条目。
    an.ensure_summon_enter(db, nid, "丙")

    present = an.present_names_at(db, nid)
    assert "甲" not in present  # 与 persons_present_tonight 一致，不留在名单
    assert an.persons_present_tonight(db, nid) == present  # 两派生同核
    audible_bodies = [e["body"] for e in an.audible_entries_for(db, nid, "甲")]
    assert not any("丙" in b for b in audible_bodies)  # 退场后公开条目不泄漏给甲


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
    # 补跑持续失败 → 失败单源（LLMUnavailable），夜保持开可重按过月。
    with pytest.raises(LLMUnavailable) as ei:
        drain_pending_before_close(
            db=db, llm_config=object(), write_gate=threading.Lock(),
            night_id=nid, extractor_agent=_BoomAgent(),
        )
    assert ei.value.code == "pending_extraction"
    assert ei.value.message == CLI_RUNNER_PLAYER_MESSAGE
    # 夜未被封（保持可续 / 可重按），待补仍在（诊断面）。
    assert an.get_night(db, nid)["status"] != an.NIGHT_STATUS_CLOSED
    assert db.count_pending_story_extractions(night_id=nid) >= 1


# ── web 真实入口 tracer：回话尾随 → 落账；收夜前 drain 门（AC1/AC5/AC10）─────
@pytest.fixture
def web_game(tmp_path, monkeypatch):
    """真实 WebGame（新档、temp DB）；构造即不连 LLM，仅 runtime 配置中和。"""
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    # #544 / #1353 r6：高亮判官 LLM 边界离线中和，禁 sk-test 真网。
    monkeypatch.setattr(web_app, "run_highlight_judge", lambda **_k: [])
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


def test_cli_trail_extraction_runs_after_reply_persist(game, monkeypatch):
    """#501 CLI：回话入档后自动尾随抽取（与 Web 同核；不靠玩家手动「重试补写」）。"""
    from ming_sim.cli import terminal as term

    db, state, content = game
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent",
        lambda cfg: _FactsAgent(_STAGE_FACT_JSON),
    )
    minister = _minister(db, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    an.ensure_summon_enter(db, nid, minister)
    ctid = db.create_chat_turn(state, minister, "cli:s", 0, night_id=nid)
    reply = "臣为洪承畴作保，愿以官身担之。"
    # 模拟 CLI 正常回话落库（append + update_chat_turn_messages）
    mid = db.append_chat_message(minister, int(state.turn), "minister", reply)
    db.update_chat_turn_messages(ctid, minister_message_id=int(mid))

    # llm_config 非 None 才会进 create_audience_extractor_agent（与 web 同）；离线用 object 即可。
    session = SimpleNamespace(
        db=db, state=state, content=content, llm_config=object(),
        _write_gate=threading.Lock(),
    )
    # 生产 CLI 尾随入口（minister_chat / 重试回话成功后同调）
    term._trail_extraction_after_reply_cli(session, minister, reply, ctid)

    assert db.get_story_extract_status(ctid) == "done"
    entries = [e for e in an.list_ledger(db, nid) if e["source_chat_turn_id"] == ctid]
    assert len(entries) == 1 and "洪承畴" in entries[0]["person_names"]
    # 无待补——自动尾随后不应再挂 pending 逼玩家手动补
    assert db.count_pending_story_extractions(night_id=nid) == 0


def test_cli_trail_extraction_failure_marks_pending_not_raises(game, monkeypatch):
    """#501 CLI 负向：抽取失败标待补、不抛、回话不回滚。"""
    from ming_sim.cli import terminal as term

    db, state, content = game
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda *a, **k: _BoomAgent(),
    )
    minister = _minister(db, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    an.ensure_summon_enter(db, nid, minister)
    ctid = db.create_chat_turn(state, minister, "cli:s", 0, night_id=nid)
    reply = "臣作保。"
    mid = db.append_chat_message(minister, int(state.turn), "minister", reply)
    db.update_chat_turn_messages(ctid, minister_message_id=int(mid))
    session = SimpleNamespace(
        db=db, state=state, content=content, llm_config=object(),
        _write_gate=threading.Lock(),
    )
    # 不得抛
    term._trail_extraction_after_reply_cli(session, minister, reply, ctid)
    # 回话仍在、标待补
    assert db.conn.execute(
        "SELECT content FROM chat_messages WHERE id=?", (mid,)
    ).fetchone()["content"] == reply
    assert db.get_story_extract_status(ctid) == "pending"


def test_web_await_inflight_does_not_pre_drain_pending(web_game, monkeypatch):
    """Web 前门只等在飞；待补留给创建案卷后的 close-night 单一 owner。"""
    game = web_game
    minister = _minister(game.db, game.content)
    ctid, _snap = game._start_chat_turn(minister)
    game.db.persist_minister_reply(minister, int(game.state.turn), "臣领旨。", ctid)
    nid = int(game.db.conn.execute(
        "SELECT night_id FROM chat_turns WHERE id=?", (ctid,)
    ).fetchone()["night_id"])

    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda cfg: _BoomAgent())
    # #1353：前门屏障/等待不得预清待补——待补留给 close-night 单一 owner。
    from ming_sim.session_write_queue import get_session_write_queue
    get_session_write_queue(game).barrier(lambda: None)
    assert game.db.count_pending_story_extractions(night_id=nid) == 1
    assert an.get_night(game.db, nid)["status"] == an.NIGHT_STATUS_OPEN


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

    # CLOSING：默认调用拒写（不得仅凭 status 自动授权）；close-owned 显式 allow_closing 成功。
    night2 = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid2 = int(night2["id"])
    ctid2 = db.create_chat_turn(state, minister, "s", 0, night_id=nid2)
    db.conn.execute(
        "UPDATE audience_nights SET status=? WHERE id=?",
        (an.NIGHT_STATUS_CLOSING, nid2),
    )
    db.conn.commit()
    with pytest.raises(an.AudienceNightError) as ei_closing:
        db.settle_story_extraction(
            ctid2, nid2, [{"body": "默认拒", "person_names": [minister]}], 1,
        )
    assert ei_closing.value.code == "night_closing"
    assert db.get_story_extract_status(ctid2) != "done"
    ids = db.settle_story_extraction(
        ctid2, nid2, [{"body": "close-owned 落账", "person_names": [minister]}], 1,
        allow_closing=True,
    )
    assert len(ids) == 1 and db.get_story_extract_status(ctid2) == "done"


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


def test_extraction_open_tag_enter_does_not_drive_presence(game):
    """抽取账开放 tags=[入殿] 不驱动在场（机器承重态只认 presence_effect，ADR 0035 R2）——
    与 settle 死账 check_dead=(effect==enter) 对称。口令账 TAG_ENTER 仍驱动在场。"""
    db, state, content = game
    minister = _minister(db, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])

    # 抽取账（source_chat_turn_id>0）带开放 tag「入殿」但 effect='' → 不入在场
    ctid = db.create_chat_turn(state, minister, "s", 0, night_id=nid)
    seq = db.conn.execute(
        "SELECT night_seq FROM chat_turns WHERE id=?", (ctid,)).fetchone()["night_seq"]
    db.settle_story_extraction(
        ctid, nid,
        [{"body": "旁白称其入殿", "person_names": [minister], "tags": ["入殿"],
          "presence_effect": ""}],
        int(seq),
    )
    assert minister not in an.persons_present_tonight(db, nid)
    # 同人抽取账 effect=enter（机器字段）→ 入在场
    ctid2 = db.create_chat_turn(state, minister, "s", 0, night_id=nid)
    seq2 = db.conn.execute(
        "SELECT night_seq FROM chat_turns WHERE id=?", (ctid2,)).fetchone()["night_seq"]
    db.settle_story_extraction(
        ctid2, nid,
        [{"body": "近前奏对", "person_names": [minister], "presence_effect": "enter"}],
        int(seq2),
    )
    assert minister in an.persons_present_tonight(db, nid)


def test_dead_actor_open_tag_enter_does_not_bypass_dead_check(game):
    """L1 对称：亡者 + 抽取账开放 tags=[入殿]/effect='' → 落账（叙事）但**不入在场名单**
    （不旁路 ADR 0035 廉价死账校验）；effect=enter 仍被死账拒写。"""
    db, state, content = game
    minister = _minister(db, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    db.set_character_status(state, minister, "dead", "test 卒")

    ctid = db.create_chat_turn(state, minister, "s", 0, night_id=nid)
    seq = db.conn.execute(
        "SELECT night_seq FROM chat_turns WHERE id=?", (ctid,)).fetchone()["night_seq"]
    # 开放 tag「入殿」+ effect='' → 死账校验（只认 effect）不触发 → 落账，但亡者不入在场
    db.settle_story_extraction(
        ctid, nid,
        [{"body": "旁白称亡者入殿", "person_names": [minister], "tags": ["入殿"],
          "presence_effect": ""}],
        int(seq),
    )
    assert minister not in an.persons_present_tonight(db, nid)
    # effect=enter → 死账拒写（对称仍拦）
    ctid2 = db.create_chat_turn(state, minister, "s", 0, night_id=nid)
    with pytest.raises(an.AudienceNightError) as ei:
        db.settle_story_extraction(
            ctid2, nid,
            [{"body": "亡者入殿", "person_names": [minister], "presence_effect": "enter"}], 9)
    assert ei.value.code == "dead_present"


# ── L1 引擎侧 close_night drain 闸（不只挂 web 前门）──────────────────────
def test_engine_close_night_drains_pending_success(game, monkeypatch):
    db, state, content = game
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent",
        lambda *a, **k: _FactsAgent(_STAGE_FACT_JSON))
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister, reply="臣作保。")
    assert db.count_pending_story_extractions(night_id=nid) == 1
    # 带 llm/write_gate → 引擎 close 强制 drain（显式 allow_closing）→ 收夜成功、水位 done
    result = an.close_night(
        db, state, night_id=nid, llm_config=object(), write_gate=threading.Lock())
    assert result["closed"] is True
    assert an.get_night(db, nid)["status"] == an.NIGHT_STATUS_CLOSED
    assert db.get_story_extract_status(ctid) == "done"
    # close-owned drain 落出的抽取账真实存在（非跳过）。
    assert db.conn.execute(
        "SELECT COUNT(*) AS c FROM story_ledger_entries "
        "WHERE night_id=? AND source_chat_turn_id=?",
        (nid, ctid),
    ).fetchone()["c"] >= 1


def test_engine_close_night_fail_closed_on_boom(game, monkeypatch, tmp_path):
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda *a, **k: _BoomAgent())
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister)
    # 持续失败 → 引擎 close 失败单源中止收夜、夜保持开
    with pytest.raises(LLMUnavailable) as ei:
        an.close_night(
            db, state, night_id=nid, llm_config=object(), write_gate=threading.Lock())
    assert ei.value.code == "pending_extraction"
    assert ei.value.message == CLI_RUNNER_PLAYER_MESSAGE
    assert an.get_night(db, nid)["status"] != an.NIGHT_STATUS_CLOSED


def test_engine_close_night_fail_closed_without_deps(game, tmp_path, monkeypatch):
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid, seq = _open_night_with_persisted_reply(db, state, minister)
    # 无 llm/write_gate 又带待补 = 无从清空又不得带待补收夜 → 失败单源（不静默跳过）
    with pytest.raises(LLMUnavailable) as ei:
        an.close_night(db, state, night_id=nid)
    assert ei.value.code == "pending_extraction"
    assert ei.value.message == CLI_RUNNER_PLAYER_MESSAGE
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


# ── L5 待补只读诊断 + 内部 catch_up（#1353：无玩家手动补写面）─────────────
def test_pending_readable_and_internal_catch_up(web_game, monkeypatch):
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
    # 内部 catch_up（换好抽取员）→ 水位 done、待补清零；禁 retry_story_extractions 包装
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent",
        lambda *a, **k: _FactsAgent(_STAGE_FACT_JSON))
    nid = int(status.get("night_id") or 0) or None
    catch_up_pending_extractions(
        db=game.db,
        llm_config=getattr(game.session, "llm_config", None),
        write_gate=game._runtime_write_gate(),
        night_id=nid,
    )
    after = game.pending_story_extractions()
    assert after["count"] == 0
    assert game.db.get_story_extract_status(ctid) == "done"
    assert not hasattr(game, "retry_story_extractions")


def test_catch_up_list_unextracted_waits_prior_via_ticketed_gate():
    """#1353：catch_up 首碰 list_unextracted 必须经 TicketedWriteGate wait_prior。

    触发：启动 catch-up / 收夜 drain 在过月屏障之后领票。闸外 list 与
    barrier close / chat 裸写并发同一 sqlite 连接 → Row IndexError。
    """
    from ming_sim.session_write_queue import SessionWriteQueue

    q = SessionWriteQueue()
    listed = threading.Event()
    entered_catch = threading.Event()
    barrier_hold = threading.Event()
    barrier_entered = threading.Event()
    done = threading.Event()

    class _FakeDB:
        def list_unextracted_replies(self, night_id=None):
            listed.set()
            return []

    def barrier_body() -> None:
        barrier_entered.set()
        assert barrier_hold.wait(2.0)

    bt = threading.Thread(target=lambda: q.barrier(barrier_body), daemon=True)
    bt.start()
    assert barrier_entered.wait(2.0)

    ticket = q.claim(key=("startup",))
    assert ticket is not None
    gate = q.ticketed_gate(ticket)

    def run_catch() -> None:
        entered_catch.set()
        catch_up_pending_extractions(
            db=_FakeDB(), llm_config=None, write_gate=gate,
        )
        q.complete(ticket)
        done.set()

    th = threading.Thread(target=run_catch, daemon=True)
    th.start()
    assert entered_catch.wait(2.0)
    # 屏障未放行前不得碰共享 conn
    assert not listed.is_set()
    barrier_hold.set()
    assert listed.wait(2.0)
    assert done.wait(2.0)
    bt.join(timeout=2.0)
    th.join(timeout=2.0)
    assert not bt.is_alive() and not th.is_alive()


def test_catch_up_cancelled_ticket_does_not_touch_db():
    """取消票：catch_up 不得闸外/闸内 list，且从不抛（ADR 0036）。"""
    from ming_sim.session_write_queue import SessionWriteQueue

    q = SessionWriteQueue()
    ticket = q.claim(key=("startup",))
    assert ticket is not None
    q.cancel(ticket)
    calls = {"n": 0}

    class _FakeDB:
        def list_unextracted_replies(self, night_id=None):
            calls["n"] += 1
            return []

    summary = catch_up_pending_extractions(
        db=_FakeDB(), llm_config=None, write_gate=q.ticketed_gate(ticket),
    )
    assert calls["n"] == 0
    assert summary == {"extracted": 0, "pending": 0, "scanned": 0}
