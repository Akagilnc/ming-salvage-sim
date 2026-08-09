"""s1 (#10) — driver.run_settle：探针确定性结算入口。

run_settle 收一份**中文 schema 形态**的稀疏 delta（我在对话里产的形态），
规范化 → pre_settle → settle_with_delta，推进一回合。CLI 子命令是它的薄壳。

注：本文件断言 turn_phase 时故意用 raw 字符串（如 "summoning"）而非 TurnPhase.X.value——
它们 pin 的是**落盘字符串值本身**（DB 持久化的真值），有意 enum 无关：若枚举重命名而
落盘值漂移，这些断言应当响亮失败。S4 把生产代码的相位比较统一到 TurnPhase enum，测试侧
的落盘断言不跟随。
"""

from __future__ import annotations

import json
import os
import shutil

import pytest

import driver
from driver import run_settle
from tests.conftest import active_ming_character


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
def test_run_settle_rejects_non_dict_raw_delta(read_game, bad):
    """run_settle 边界:非 dict(falsy 的 []/""/0 + 非 falsy 的 str/int)一律响亮报错、不推进(codex-P1a + Sourcery)。"""
    db, state, content = read_game
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


def test_run_settle_logs_chapter_memory_skip(game, capsys):
    """driver 不注入 chapter_recorder（无 llm_config，章节记忆由对话方另产），settle 时须留一条
    审计 tlog，便于事后查「哪回合没记起居注」——章节记忆这条浓缩若对话方某回合忘补=静默缺口（#19）。"""
    db, state, content = game
    before = state.turn
    run_settle(db, state, content, None)
    out = capsys.readouterr().out
    assert "跳过章节记忆" in out
    assert f"turn {before}→{before + 1}" in out  # 精确校验审计回合范围（不松到任意数字误匹配）


def test_run_settle_no_chapter_skip_audit_when_settle_aborts(game, capsys, monkeypatch):
    """settle 中途失败（SettlementAbort/异常）→回合未推进、可重试，不该误记一条「已跳章节记忆」审计
    （codex PR#133 P3：审计须在 settle_with_delta 成功之后打）。"""
    db, state, content = game
    def _boom(*a, **k):
        raise RuntimeError("settle 炸了")
    monkeypatch.setattr(driver, "settle_with_delta", _boom)
    with pytest.raises(RuntimeError):
        run_settle(db, state, content, None)
    out = capsys.readouterr().out
    assert "跳过章节记忆" not in out  # 失败回合不留误导审计


def test_run_settle_records_non_dict_nested_value(game):
    """ADR0015：实体→{字段}模块二级值非 dict 时逐实体拒收，回合仍推进。"""
    db, state, content = game
    before = state.turn
    run_settle(db, state, content, {"地区变化": {"shanxi": "动乱+5"}})
    assert state.turn == before + 1
    row = db.conn.execute("SELECT section, item_json FROM rejection_reports WHERE turn=?", (before,)).fetchone()
    assert row["section"] == "region_delta"
    assert '"entity_id": "shanxi"' in row["item_json"]


def test_run_settle_rejects_unknown_toplevel_key(read_game):
    """未知顶层 key(拼写错,如 地区变更↔地区变化)响亮报错,不静默无效推进(codex-P1b)。"""
    db, state, content = read_game
    before = state.turn
    with pytest.raises(ValueError):
        run_settle(db, state, content, {"地区变更": {"shanxi": {"动乱": 5}}})
    assert state.turn == before


def test_run_settle_records_non_dict_module_value(game):
    """ADR0015：畸形 section 值按 section 拒收，非整月 abort。"""
    db, state, content = game
    before = state.turn
    run_settle(db, state, content, {"国势变化": "foo"})
    assert state.turn == before + 1
    row = db.conn.execute("SELECT section, item_json FROM rejection_reports WHERE turn=?", (before,)).fetchone()
    assert row["section"] == "metric_delta"
    assert '"raw_value": "foo"' in row["item_json"]


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

    raw_delta = {"地区变化": {"shanxi": {"origin_ref": "盘面自发", "动乱": 5}}}
    run_settle(db, state, content, raw_delta)

    new_unrest = db.conn.execute(
        "SELECT unrest FROM regions WHERE id='shanxi'"
    ).fetchone()[0]
    assert state.turn == before + 1
    assert new_unrest == old_unrest + 5


def test_run_settle_persists_narrative_and_applied_extraction_trace(saved_game):
    """driver 传入邸报叙事 → 落 turn_report;applied 结果落 extractor_output 供玩家明细/时间线读。
    用 saved_game：断言依赖玩过存档的国库基线/结算状态，fresh seed 不复现（#5）。"""
    db, state, content = saved_game
    before = state.turn
    narrative = "【邸报·测试】山西动乱微升，余无大事。"

    run_settle(db, state, content, {"地区变化": {"shanxi": {"origin_ref": "盘面自发", "动乱": 1}}}, narrative=narrative)

    report = db.conn.execute(
        "SELECT report FROM turn_reports WHERE turn=?", (before,)
    ).fetchone()[0]
    assert report == narrative
    extr = db.conn.execute(
        "SELECT extractor_output FROM turn_extractions WHERE turn=?", (before,)
    ).fetchone()[0]
    out = json.loads(extr)
    assert out["region_changes"] == [
        {
            "region": "山西",
            "field": "unrest",
            "label": "动乱",
            "old": 60,
            "new": 61,
            "delta": 1,
            "reason": "月末整体推演",
        }
    ]


def test_run_settle_persists_applied_person_results_for_player_visible_extraction(game):
    """邸报详明/时间线读 turn_extractions,这里必须保存 applied 结果而非 raw 人物变更。"""
    db, state, content = game
    before = state.turn

    run_settle(
        db,
        state,
        content,
        {
            "人物变更": [
                {
                    "origin_ref": "盘面自发", "name": "不存在的人",
                    "动作": "任命",
                    "office": "首辅",
                    "reason": "测试拒收可见性",
                }
            ]
        },
        narrative="x",
        decree_text="y",
    )

    out = db.get_turn_extraction(before)["extractor_output"]
    assert "人物变更" not in out
    assert "person_changes" not in out
    assert "item" not in out["applied_person_changes"][0]
    assert "report_section" not in out["applied_person_changes"][0]
    assert "report_category" not in out["applied_person_changes"][0]
    assert out["applied_person_changes"] == [
        {
            "name": "不存在的人",
            "动作": "任命",
            "rejected": True,
            "reason": "非既有人物",
            "category": "hallucinated_id",
            "origin_ref": "盘面自发",
        }
    ]


def test_run_settle_preserves_legacy_person_key_order_after_issue_close(game):
    """旧 character_status_changes 兼容 replay 仍应在 issue close 后执行,不抢先改人导致结算中止。"""
    db, state, content = game
    before = state.turn
    name = active_ming_character(db, content)
    ch = content.characters[name]
    old_status = ch.status
    old_office = ch.office
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="旧键顺序复现",
        origin_kind="decree",
        bar_value=50,
        effect_on_resolve={
            "character_status_changes": [
                {"origin_ref": "盘面自发", "name": name, "status": "imprisoned", "reason": "结案下狱"}
            ]
        },
    )
    db.conn.commit()

    try:
        run_settle(
            db,
            state,
            content,
            {
                "close_issues": [{"issue_id": issue_id, "reason": "resolved", "narrative": "测试结案"}],
                "character_status_changes": [
                    {"origin_ref": "盘面自发", "name": name, "status": "dead", "reason": "同月处死"}
                ],
            },
            narrative="x",
            decree_text="y",
        )

        assert db.get_character_status(name)[0] == "imprisoned"
        out = db.get_turn_extraction(before)["extractor_output"]
        assert out["issue_summary"]["applied_person_changes"] == [
            {"name": name, "动作": "处置", "status": "imprisoned", "reason": "结案下狱"}
        ]
        assert any(
            item.get("name") == name
            and item.get("rejected")
            and item.get("status") == "dead"
            and item.get("reason") == "当前非 active（imprisoned）"
            for item in out["applied_person_changes"]
        )
    finally:
        ch.status = old_status
        ch.office = old_office


def test_run_settle_preserves_unified_person_key_order_after_issue_close(game):
    """新 人物变更 也应在 issue close 后执行,顺序不得只修旧 flat key。"""
    db, state, content = game
    before = state.turn
    name = active_ming_character(db, content)
    ch = content.characters[name]
    old_status = ch.status
    old_office = ch.office
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="新键顺序复现",
        origin_kind="decree",
        bar_value=50,
        effect_on_resolve={
            "人物变更": [
                {"origin_ref": "盘面自发", "name": name, "动作": "处置", "status": "imprisoned", "reason": "结案下狱"}
            ]
        },
    )
    db.conn.commit()

    try:
        run_settle(
            db,
            state,
            content,
            {
                "close_issues": [{"issue_id": issue_id, "reason": "resolved", "narrative": "测试结案"}],
                "人物变更": [
                    {"origin_ref": "盘面自发", "name": name, "动作": "处置", "status": "dead", "reason": "同月处死"}
                ],
            },
            narrative="x",
            decree_text="y",
        )

        assert db.get_character_status(name)[0] == "dead"
        out = db.get_turn_extraction(before)["extractor_output"]
        assert out["issue_summary"]["applied_person_changes"] == [
            {"name": name, "动作": "处置", "status": "imprisoned", "reason": "结案下狱"}
        ]
        assert {"name": name, "动作": "处置", "status": "imprisoned", "reason": "结案下狱"} in out[
            "applied_person_changes"
        ]
        assert {"name": name, "动作": "处置", "status": "dead", "reason": "同月处死",
                "origin_ref": "盘面自发"} in out["applied_person_changes"]
    finally:
        ch.status = old_status
        ch.office = old_office


def test_cli_state_prints_board(read_game, capsys):
    """`state` 子命令打印当前盘面（含纪年），返回码 0。"""
    db, state, content = read_game
    rc = driver.main(["state"], game=read_game)
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
        json.dumps({"地区变化": {"shanxi": {"origin_ref": "盘面自发", "动乱": 3}}}), encoding="utf-8"
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
        json.dumps({"narrative": narrative, "delta": {"地区变化": {"beizhili": {"origin_ref": "盘面自发", "城防炮": 3}}}}),
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


def test_cli_dump_prints_regions(read_game, capsys):
    """`dump` 打印盘面快照，含地区行（地区 id 出现在输出里），返回码 0。"""
    db, state, content = read_game
    rc = driver.main(["dump"], game=read_game)
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

    raw = {"地区变化": {"shanxi": {"origin_ref": "盘面自发", "动乱": 3}}}
    with pytest.raises(SettlementAbort) as ei:
        run_settle(db, state, content, raw, narrative="邸报", decree_text="诏")
    assert ei.value.stage == "settle"
    assert isinstance(ei.value.__cause__, RuntimeError)

    ctx = db.get_resolve_context(before_turn)
    assert ctx is not None
    # 顶层 key 已 canonical（地区变化→region_delta）；区域内层字段保持原样由 apply 解析。
    assert ctx["extracted"] == {"region_delta": {"shanxi": {"origin_ref": "盘面自发", "动乱": 3}}}
    db.clear_resolve_context(before_turn)


def test_run_settle_clears_resolve_context_on_completion(game):
    """正常完成后 context 已清（settle 内 clear 对 driver 同样生效）。"""
    db, state, content = game
    before_turn = state.turn
    run_settle(db, state, content, {"地区变化": {"shanxi": {"origin_ref": "盘面自发", "动乱": 1}}})
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
        run_settle(db, state, content, {"地区变化": {"shanxi": {"origin_ref": "盘面自发", "动乱": 1}}})

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


# ── #17: DEFAULT_DB 绝对路径 + 缺库响亮失败（不静默新建空库）──

def test_default_db_is_absolute_repo_anchored():
    """DEFAULT_DB 须绝对路径、锚 driver.py 旁的 data/probe.db（cwd 无关）——否则从非 repo 根跑
    driver 会按 cwd 静默开错/新建库（codex-P2d，#17）。
    注：不断言文件存在——data/*.db 被 .gitignore（#5），clean checkout/CI 上不在；只断言路径值
    （codex R1 critical：原 assert exists 在 CI 是假绿/真红隐患）。"""
    import os
    from pathlib import Path
    import driver as drv
    assert os.path.isabs(drv.DEFAULT_DB), f"DEFAULT_DB 须绝对路径，实得 {drv.DEFAULT_DB!r}"
    expected = Path(drv.__file__).resolve().parent / "data" / "probe.db"
    assert Path(drv.DEFAULT_DB) == expected, f"DEFAULT_DB 须锚 driver.py 旁 data/probe.db，实得 {drv.DEFAULT_DB!r}"


def test_open_game_fails_loud_on_missing_db(tmp_path):
    """缺库响亮失败：driver 只在既有探针存档上结算，绝不静默 sqlite3.connect 新建空库
    （否则 load_state 得退化盘面、玩家不知开错档，codex-P2d）。"""
    import os
    import pytest
    import driver as drv
    missing = str(tmp_path / "no_such_save.db")
    with pytest.raises(FileNotFoundError):
        drv.open_game(missing)
    assert not os.path.exists(missing), "失败路径不得被静默新建"


def test_open_game_rejects_empty_or_nonsave_db(tmp_path):
    """存在但非真存档（空文件/非 SQLite/缺 game_state id=1）也须响亮失败——否则 init_schema +
    load_state 会把它静默补成退化新局（codex R1 medium：仅查 exists 不够）。"""
    import pytest
    import driver as drv
    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")          # 0 字节存在文件
    with pytest.raises(ValueError):  # 收紧到设计抛的 ValueError，不用 Exception 兜底掩盖回归（CodeRabbit R1）
        drv.open_game(str(empty))
    garbage = tmp_path / "garbage.db"
    garbage.write_text("not a sqlite db")
    with pytest.raises(ValueError):
        drv.open_game(str(garbage))


def test_open_game_rejects_degenerate_db_with_state_but_empty_board(tmp_path):
    """退化库：有 game_state id=1 但静态盘面 regions 空（旧 bug 在空库 load_state 写了 id=1、
    没 seed_static_data）也须拒——只看 game_state 哨兵不够（codex R1 P2）。"""
    import sqlite3
    import pytest
    import driver as drv
    degen = tmp_path / "degenerate.db"
    conn = sqlite3.connect(str(degen))
    conn.execute("CREATE TABLE game_state (id INTEGER PRIMARY KEY, turn INTEGER)")
    conn.execute("INSERT INTO game_state (id, turn) VALUES (1, 5)")
    conn.execute("CREATE TABLE regions (id TEXT PRIMARY KEY)")  # 表在但无数据
    conn.commit()
    conn.close()
    with pytest.raises(ValueError):
        drv.open_game(str(degen))


def test_open_game_handles_uri_special_chars_in_path(tmp_path):
    """路径含 URI 特殊字符（空格/#）的退化库经 as_uri 编码后仍正常走 ro-probe 并响亮拒，
    不因 f'file:{path}?mode=ro' 误解析崩（codex R2 P3）。"""
    import sqlite3
    import pytest
    import driver as drv
    weird_dir = tmp_path / "a b#c"
    weird_dir.mkdir()
    degen = weird_dir / "save.db"
    conn = sqlite3.connect(str(degen))
    conn.execute("CREATE TABLE game_state (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO game_state (id) VALUES (1)")
    conn.execute("CREATE TABLE regions (id TEXT)")  # 空盘面 → 应拒
    conn.commit()
    conn.close()
    with pytest.raises(ValueError):  # 编码正确则正常走到 regions 空判定；编码错会是别的崩
        drv.open_game(str(degen))


def test_canonicalize_extraction_public_api():
    """#17：driver 等跨模块复用 simulation.canonicalize_extraction 公有 API，不引私有名；
    历史私有别名 _canonicalize_extraction 仍指向同一实现（向后兼容）。"""
    from ming_sim import simulation as sim
    assert sim.canonicalize_extraction is sim._canonicalize_extraction
    # 公有 API 真归一：验完整结构——顶层中文 key → 英文 canonical（地区变化→region_delta）；
    # 嵌套字段(动乱)此层不动，由 apply 层 REGION_FIELD_ALIASES 转（Sourcery R1：验全结构非仅 key 存在）。
    assert sim.canonicalize_extraction({"地区变化": {"shanxi": {"origin_ref": "盘面自发", "动乱": 1}}}) == {
        "region_delta": {"shanxi": {"origin_ref": "盘面自发", "动乱": 1}}
    }
    import driver as drv
    assert drv.canonicalize_extraction is sim.canonicalize_extraction


# ── ADR 0008 决定 5：拒收玩家可见性（player_decree/hitl → 邸报 in-world 提示）──

def test_run_settle_player_sourced_rejection_surfaces_diegetic_hint(game):
    """driver 默认 player_decree 来源：落库拒收 → 邸报给一句 in-world 提示（不暴露明细，明细进 DB/jsonl），
    且提示**持久化进 turn_report**（web/history/重读都见，非仅即时返回串，codex R1 high）。"""
    db, state, content = game
    before = state.turn
    report = run_settle(db, state, content,
        {"人物变更": [{"origin_ref": "盘面自发", "name": "查无此人甲", "动作": "任命", "office": "首辅", "reason": "测试拒收"}]})
    assert "有司奏" in report, "player_decree 来源的拒收须在邸报给玩家一句提示（决定 5）"
    assert "查无此人甲" not in report, "提示只一句 in-world，不暴露拒收明细（明细进 DB/jsonl）"
    # 持久化：turn_reports（web/history 读它）也须含提示，非仅 run_settle 即时返回
    persisted = db.conn.execute("SELECT report FROM turn_reports WHERE turn=?", (before,)).fetchone()[0]
    assert "有司奏" in persisted, "提示须持久化进 turn_report（codex R1：仅返回串则 web/history 看不到）"


def test_run_settle_no_rejection_no_hint(game):
    """无拒收 → 无提示（避免噪声）；且不误持久化进 turn_report（Sourcery R1）。"""
    db, state, content = game
    before = state.turn
    report = run_settle(db, state, content, {"地区变化": {"shanxi": {"origin_ref": "盘面自发", "动乱": 1}}})
    assert "有司奏" not in report
    persisted = db.conn.execute("SELECT report FROM turn_reports WHERE turn=?", (before,)).fetchone()[0]
    assert "有司奏" not in persisted, "无拒收不应把提示误持久化进 turn_report"


def test_run_settle_system_source_rejection_stays_silent(game):
    """system_simulation 来源的拒收对玩家安静——仅 player_decree/hitl_decision 给提示（决定 5）。"""
    from ming_sim.applier import Provenance
    db, state, content = game
    report = run_settle(db, state, content,
        {"人物变更": [{"origin_ref": "盘面自发", "name": "查无此人乙", "动作": "任命", "office": "首辅", "reason": "测试"}]},
        source=Provenance.system_simulation)
    assert "有司奏" not in report, "系统推演来源的拒收对玩家安静"
