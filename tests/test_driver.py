"""s1 (#10) — driver.run_settle：探针确定性结算入口。

run_settle 收一份**中文 schema 形态**的稀疏 delta（我在对话里产的形态），
规范化 → pre_settle → settle_with_delta，推进一回合。CLI 子命令是它的薄壳。
"""

from __future__ import annotations

import json
import os
import shutil

import pytest

import driver
from driver import run_settle


def test_cli_settle_rejects_non_dict_envelope_delta(game, tmp_path):
    """信封的 delta 不是 object(dict)时,响亮报错(不静默吞成空 delta 照样结算)。"""
    db, state, content = game
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"narrative": "x", "delta": "not-a-dict"}), encoding="utf-8"
    )
    # 库层抛 ValueError,CLI main 转退出码 1(不让 ValueError 透到用户)。
    assert driver.main(["settle", "--delta", str(bad)], game=game) == 1


@pytest.mark.parametrize("bad", [[], "", 0, "foo", 5])
def test_run_settle_rejects_non_dict_raw_delta(game, bad):
    """run_settle 边界:非 dict(falsy 的 []/""/0 + 非 falsy 的 str/int)一律响亮报错、不推进(codex-P1a + Sourcery)。"""
    db, state, content = game
    before = state.turn
    with pytest.raises(ValueError):
        run_settle(db, state, content, bad)
    assert state.turn == before


def test_run_settle_none_delta_is_empty_turn(game):
    """None = 空回合(本月无变化):不报错、正常推进 turn+1(Sourcery 正向用例)。"""
    db, state, content = game
    before = state.turn
    run_settle(db, state, content, None)
    assert state.turn == before + 1


def test_run_settle_rejects_non_dict_nested_value(game):
    """实体→{字段}模块(如 地区变化)的二级值非 dict 时结算前响亮报错、不半落库(Gemini R1 G2)。"""
    db, state, content = game
    before = state.turn
    with pytest.raises(ValueError):
        run_settle(db, state, content, {"地区变化": {"shanxi": "动乱+5"}})
    assert state.turn == before


def test_run_settle_rejects_unknown_toplevel_key(game):
    """未知顶层 key(拼写错,如 地区变更↔地区变化)响亮报错,不静默无效推进(codex-P1b)。"""
    db, state, content = game
    before = state.turn
    with pytest.raises(ValueError):
        run_settle(db, state, content, {"地区变更": {"shanxi": {"动乱": 5}}})
    assert state.turn == before


def test_run_settle_rejects_non_dict_module_value(game):
    """畸形模块值(国势变化="foo"→metric_delta 非 dict)在 pre_settle 动 DB 前响亮报错,回合不半推进。"""
    db, state, content = game
    before = state.turn
    with pytest.raises(ValueError):
        run_settle(db, state, content, {"国势变化": "foo"})
    assert state.turn == before  # 崩前拦住,未推进、未半落库


def test_open_game_loads_board(tmp_path):
    """open_game 按路径打开存档，返回 (db, state, content)，盘面已加载（turn>0）。"""
    src = os.path.join(os.path.dirname(__file__), "..", "data", "probe.db")
    if not os.path.exists(src):
        pytest.skip("缺基底存档 data/probe.db")
    dst = tmp_path / "probe.db"
    shutil.copy(src, dst)

    db, state, content = driver.open_game(str(dst))
    try:
        assert state.turn > 0
        assert content is not None
    finally:
        db.conn.close()


def test_run_settle_normalizes_chinese_delta_and_advances(game):
    """喂中文 key 的 delta（地区变化/动乱），规范化后落库且推进 turn+1。"""
    db, state, content = game
    before = state.turn
    old_unrest = db.conn.execute(
        "SELECT unrest FROM regions WHERE id='shanxi'"
    ).fetchone()[0]

    raw_delta = {"地区变化": {"shanxi": {"动乱": 5}}}
    run_settle(db, state, content, raw_delta)

    new_unrest = db.conn.execute(
        "SELECT unrest FROM regions WHERE id='shanxi'"
    ).fetchone()[0]
    assert state.turn == before + 1
    assert new_unrest == old_unrest + 5


def test_run_settle_persists_narrative_and_delta_trace(game):
    """driver 传入邸报叙事 → 落 turn_report;delta 以 JSON 落 turn_extractions.extractor_output（供 replay 重建）。"""
    db, state, content = game
    before = state.turn
    narrative = "【邸报·测试】山西动乱微升，余无大事。"

    run_settle(db, state, content, {"地区变化": {"shanxi": {"动乱": 1}}}, narrative=narrative)

    report = db.conn.execute(
        "SELECT report FROM turn_reports WHERE turn=?", (before,)
    ).fetchone()[0]
    assert report == narrative
    extr = db.conn.execute(
        "SELECT extractor_output FROM turn_extractions WHERE turn=?", (before,)
    ).fetchone()[0]
    # canonical delta 以 JSON 落 extractor_output,replay/timeline 可解析重建。
    # 注:region 字段别名(动乱→unrest)在 apply_region_deltas 做,_canonicalize 不动它,故留中文 key。
    assert json.loads(extr) == {"region_delta": {"shanxi": {"动乱": 1}}}


def test_cli_state_prints_board(game, capsys):
    """`state` 子命令打印当前盘面（含纪年），返回码 0。"""
    db, state, content = game
    rc = driver.main(["state"], game=game)
    out = capsys.readouterr().out
    assert rc == 0
    assert str(state.year) in out


def test_cli_settle_applies_delta_file(game, tmp_path, capsys):
    """`settle --delta <json>` 读中文 delta 文件，落库并推进 turn+1，返回码 0。"""
    db, state, content = game
    before = state.turn
    old_unrest = db.conn.execute(
        "SELECT unrest FROM regions WHERE id='shanxi'"
    ).fetchone()[0]
    delta_file = tmp_path / "delta.json"
    delta_file.write_text(
        json.dumps({"地区变化": {"shanxi": {"动乱": 3}}}), encoding="utf-8"
    )

    rc = driver.main(["settle", "--delta", str(delta_file)], game=game)

    new_unrest = db.conn.execute(
        "SELECT unrest FROM regions WHERE id='shanxi'"
    ).fetchone()[0]
    assert rc == 0
    assert state.turn == before + 1
    assert new_unrest == old_unrest + 3


def test_cli_settle_envelope_persists_narrative(game, tmp_path):
    """`settle --delta` 吃信封 {narrative, delta} 时,邸报落 turn_report;裸 delta 仍兼容。"""
    db, state, content = game
    before = state.turn
    narrative = "【邸报·信封测试】京师城防新增红夷炮数门。"
    env_file = tmp_path / "turn.json"
    env_file.write_text(
        json.dumps({"narrative": narrative, "delta": {"地区变化": {"beizhili": {"城防炮": 3}}}}),
        encoding="utf-8",
    )

    rc = driver.main(["settle", "--delta", str(env_file)], game=game)

    assert rc == 0
    report = db.conn.execute(
        "SELECT report FROM turn_reports WHERE turn=?", (before,)
    ).fetchone()[0]
    assert report == narrative
    cannon = db.conn.execute(
        "SELECT cannon FROM regions WHERE id='beizhili'"
    ).fetchone()[0]
    assert cannon == 3


def test_cli_dump_prints_regions(game, capsys):
    """`dump` 打印盘面快照，含地区行（地区 id 出现在输出里），返回码 0。"""
    db, state, content = game
    rc = driver.main(["dump"], game=game)
    out = capsys.readouterr().out
    assert rc == 0
    assert "shanxi" in out


def test_run_settle_persists_resolve_context_before_settle(game, monkeypatch, tmp_path):
    """崩在 settle 内 → resolve_context 已持久化，delta 有 DB 真源可重放（cmr S2+S3 r3）。

    driver 与真实流程同核同语义（ADR 0004/0008）：turn_extractions 在 settle 内部才写，
    没有 persist 的话 pre_settle 已落账而 delta 只活在调用方易失上下文（违 P1）。
    S7：settle 整段包 atomic，代码异常上抛后被包成 SettlementAbort(stage="settle")，
    DB 整体回滚——但 resolve_context 在 settle 之前已 persist（其行随回滚消失？否：persist
    在 pre_settle 之后、settle 的 atomic 之外单独 commit，故崩在 settle 内时 context 仍在）。
    """
    from ming_sim.exceptions import SettlementAbort
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    before_turn = state.turn

    def _boom(*a, **k):
        raise RuntimeError("simulated apply crash")
    monkeypatch.setattr(driver, "apply_score_extraction", _boom)

    raw = {"地区变化": {"shanxi": {"动乱": 3}}}
    with pytest.raises(SettlementAbort) as ei:
        run_settle(db, state, content, raw, narrative="邸报", decree_text="诏")
    assert ei.value.stage == "settle"
    assert isinstance(ei.value.__cause__, RuntimeError)

    ctx = db.get_resolve_context(before_turn)
    assert ctx is not None
    # 顶层 key 已 canonical（地区变化→region_delta）；区域内层字段保持原样由 apply 解析。
    assert ctx["extracted"] == {"region_delta": {"shanxi": {"动乱": 3}}}
    db.clear_resolve_context(before_turn)


def test_run_settle_clears_resolve_context_on_completion(game):
    """正常完成后 context 已清（settle 内 clear 对 driver 同样生效）。"""
    db, state, content = game
    before_turn = state.turn
    run_settle(db, state, content, {"地区变化": {"shanxi": {"动乱": 1}}})
    assert db.get_resolve_context(before_turn) is None


def test_crash_inside_pre_settle_leaves_no_ready_context(game, monkeypatch):
    """崩在 pre_settle 内 → 不留 ready=1 行（cmr S2+S3 r5）。

    ready=1 须统一意为「前半段已提交，只剩 settle」；persist 在 pre_settle 前的话，
    崩在 pre_settle 内留下「ready=1 但财政未落」态，恢复入口直入 apply 会跳过
    pre_settle=整月固定财政静默丢。
    """
    db, state, content = game
    before_turn = state.turn

    def _boom(*a, **k):
        raise RuntimeError("simulated pre_settle crash")
    monkeypatch.setattr(driver, "pre_settle", _boom)

    with pytest.raises(RuntimeError, match="pre_settle crash"):
        run_settle(db, state, content, {"地区变化": {"shanxi": {"动乱": 1}}})

    assert db.get_resolve_context(before_turn) is None


def test_persist_crash_rolls_back_pre_settle(game, monkeypatch):
    """pre_settle 与 ready=1 持久化同事务（PR #90 R1 codex P2 同窗，driver 路）：
    persist 崩 → 财政/相位整体回滚，不留「settling 而无 context 行」的盘。"""
    db, state, content = game
    turn = state.turn
    before = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)
    ).fetchone()[0]

    def _boom(*a, **k):
        raise RuntimeError("persist crash")
    monkeypatch.setattr(driver, "persist_resolve_context", _boom)

    with pytest.raises(RuntimeError, match="persist crash"):
        run_settle(db, state, content, {}, narrative="x", decree_text="y")

    assert state.turn == turn
    assert state.turn_phase == "summoning"
    assert db.load_state().turn_phase == "summoning"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)
    ).fetchone()[0] == before
