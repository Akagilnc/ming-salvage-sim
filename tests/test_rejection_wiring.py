"""PR2-S0(ADR 0008 决定 5/8,#91)——拒收收集器接进结算管线。

生命周期与事务对齐:apply 产生的拒收项 → 事务内 flush 进 rejection_reports →
commit 成功后镜像 jsonl → 回滚路 reset 不留行不留镜像。attempt 从错误目录推导
(不从 DB 取,随回滚重置即失真)。经 driver.run_settle 端到端驱动(公共接口)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.section_rejection_helpers import prepare_then_settle as run_settle
from tests.section_rejection_helpers import game, rejection_rows
from tests.conftest import active_ming_character


def _rejection_rows(db, turn):
    try:
        return rejection_rows(
            db, turn, columns="section, reason, category, source, attempt"
        )
    except Exception:
        return []


def test_rejected_item_lands_in_reports_and_jsonl(game, monkeypatch, tmp_path):
    """坏 delta 项(查无此人的人物状态变化)经结算后:rejection_reports 落行 +
    commit 后镜像 jsonl——「哪个 section 最常被喂脏」从此可聚合(决定 5)。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn

    run_settle(db, state, content, {
        "人物状态变化": [{"name": "查无此人甲", "status": "dead", "reason": "测试"}],
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn)
    assert len(rows) == 1
    section, reason, category, source, attempt = rows[0]
    assert section == "character_status_changes"
    assert reason  # 人读原因非空
    assert attempt == 1
    jsonl = tmp_path / "error_packs" / "rejections.jsonl"
    assert jsonl.exists()
    lines = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1
    assert lines[0]["section"] == "character_status_changes"
    assert lines[0]["turn"] == turn


def test_rollback_leaves_no_rows_and_no_jsonl(game, monkeypatch, tmp_path):
    """settle 在 flush 之后崩 → 事务回滚:rejection_reports 无行、jsonl 无镜像
    (镜像只在 commit 成功后写,否则留「DB 没有、文件却有」的孤立行)。"""
    import ming_sim.decree as decree_mod
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn

    real_clear = type(db).clear_resolve_context
    def _boom(self, t):
        raise RuntimeError("crash after flush")
    monkeypatch.setattr(type(db), "clear_resolve_context", _boom)

    with pytest.raises(SettlementAbort):
        run_settle(db, state, content, {
            "人物状态变化": [{"name": "查无此人乙", "status": "dead", "reason": "测试"}],
        }, narrative="x", decree_text="y")

    monkeypatch.setattr(type(db), "clear_resolve_context", real_clear)
    assert _rejection_rows(db, turn) == []
    assert not (tmp_path / "error_packs" / "rejections.jsonl").exists()


def test_attempt_derived_from_error_pack_dirs(game, monkeypatch, tmp_path):
    """同回合已有 attempt1 错误包(上次失败)→ 本次重试的拒收行 attempt=2:
    拒收与错误包同号,事后能对上「第几次重试产生的」(决定 5,不从 DB 取)。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    (tmp_path / "error_packs" / f"turn{turn}_attempt1").mkdir(parents=True)

    run_settle(db, state, content, {
        "人物状态变化": [{"name": "查无此人丙", "status": "dead", "reason": "测试"}],
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn)
    assert len(rows) == 1
    assert rows[0][4] == 2  # attempt


def test_engine_extractor_path_stamps_player_decree(game, monkeypatch, tmp_path):
    """#146(A 方案)：皇帝下旨触发的结算(resolve_directives)→ extractor 产出整批标 player_decree
    ——皇帝下旨这回合的拒收要给皇帝可见提示(整批按触发源；无旨自动推进/世界自演变才 system)。
    原断言 system_simulation 已废：player_decree 来源此前从未实装、皇帝下旨被拒从不提示(#146)。"""
    import ming_sim.decree as decree_mod

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn

    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "simulate_season_with_payload",
                        lambda *a, **k: ("本月邸报。", k.get("simulator_payload") or {}))
    monkeypatch.setattr(decree_mod, "build_extractor_shared_context", lambda *a, **k: "")
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({"character_status_changes": [
            {"origin_ref": "盘面自发", "name": "查无此人丁", "status": "dead", "reason": "测试"}]}, "out", "in"))

    decree_mod.resolve_directives(state, db, None, None, [1], "减赋诏",
                                  content=content, registry=None)

    rows = _rejection_rows(db, turn)
    assert len(rows) == 1
    assert rows[0][3] == "player_decree"  # #146 A：皇帝下旨=玩家来源


def test_issue_summary_nested_rejections_are_collected(game, monkeypatch, tmp_path):
    """issue_summary 是 dict(嵌套 new_issues/cancels 列表),桥接不能只看顶层 list
    ——new_issues 正是实测最常被喂脏的段(origin_kind 缺失被拒,agy 实录),
    决定 5 的「哪个 section 最常被喂脏」聚合对它失明即失去主要价值(cmr S0 r1,2/2)。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn

    run_settle(db, state, content, {
        "new_issues": [{"title": "臆造局势", "kind": "initiative"}],  # 缺 origin_kind → 拒
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn)
    assert len(rows) == 1
    assert rows[0][0] == "issue_summary.new_issues"
    assert "decree/event_pool" in rows[0][1]  # 拒收原因原样保留


def test_nested_atomic_success_path_does_not_orphan_jsonl(game, monkeypatch, tmp_path):
    """嵌套 atomic 内跑 settle:mirror 必须等最外层 commit——否则外层回滚后
    DB 行消失而 jsonl 已写=孤立镜像行(违决定 5「commit 成功后才 append」;
    异常路有对称守门,成功路同样要有)(cmr S0 r1,2/2)。"""
    from ming_sim.applier import atomic

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn

    with pytest.raises(RuntimeError, match="outer rollback"):
        with atomic(db):
            run_settle(db, state, content, {
                "人物状态变化": [{"name": "查无此人戊", "status": "dead", "reason": "测试"}],
            }, narrative="x", decree_text="y")
            raise RuntimeError("outer rollback")

    assert _rejection_rows(db, turn) == []  # DB 行随外层回滚消失
    assert not (tmp_path / "error_packs" / "rejections.jsonl").exists()  # 镜像未先写


def test_attempt_derivation_failure_does_not_abort_settlement(game, monkeypatch, tmp_path):
    """attempt 推导(扫错误目录)是诊断侧路径——它自身故障(目录不可遍历等)不得
    崩掉正常结算,回落 attempt=1(与 mirror 失败同向:副信道绝不拖垮主流程)
    (cmr S0 r2 codex P2)。"""
    import ming_sim.decree as decree_mod

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn

    def _boom(t):
        raise OSError("error_packs root not traversable")
    monkeypatch.setattr(decree_mod, "_next_attempt", _boom)

    run_settle(db, state, content, {
        "人物状态变化": [{"name": "查无此人己", "status": "dead", "reason": "测试"}],
    }, narrative="x", decree_text="y")  # 不抛=结算完成

    rows = _rejection_rows(db, turn)
    assert len(rows) == 1
    assert rows[0][4] == 1  # attempt 回落 1


def test_noncancellable_cancel_rejection_carries_reason(game, monkeypatch, tmp_path):
    """不可撤国策被诏书撤销→转强推(皇威-2)的拒收记录必须带人读 reason
    ——ADR 决定 5 拒收行含原因,空字符串行无法聚合分析(cmr S0 r2 codex P2)。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn

    row = db.conn.execute(
        "SELECT id FROM issues WHERE status='active' LIMIT 1").fetchone()
    assert row is not None, "probe.db 需至少一条 active issue"
    issue_id = int(row[0])
    db.conn.execute("UPDATE issues SET cancellable='no' WHERE id=?", (issue_id,))
    db.conn.commit()

    run_settle(db, state, content, {
        "cancels": [{"issue_id": issue_id, "narrative": "测试撤销"}],
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn) if r[0] == "issue_summary.cancels"]
    assert len(rows) == 1
    assert rows[0][1]  # reason 非空


def test_rejected_appointment_carries_rejection_cause(game, monkeypatch, tmp_path):
    """后宫纳妃被拒(重名/字段不合/未获准)的拒收行 reason=拒收原因,不是 LLM 任命
    理由回显——与 r2 cancels 同类缺陷的另一 producer(cmr S0 r3,2/2)。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    existing = next(iter(content.characters))  # 重名 → apply_appointment 拒

    run_settle(db, state, content, {
        "appointments": [{"origin_ref": "盘面自发", "name": existing, "office": "贵妃", "office_type": "后宫",
                          "reason": "椒房之选"}],
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn) if r[0] == "appointments"]
    assert len(rows) == 1
    assert rows[0][1] and rows[0][1] != "椒房之选"  # 拒收原因,非任命理由回显
    assert rows[0][2] == "appointment_rejected"


def test_bridge_synthesizes_reason_when_producer_omits(game):
    """桥接层集中守 ADR「拒收行必带原因」不变式:任何 producer 漏给 reason,
    落库前合成非空兜底——规则写一处,未来新 section 免疫同类缺陷(fix-coverage
    drift 处方:集中化,cmr S0 r3)。"""
    from ming_sim.applier import Provenance, RejectionCollector
    from ming_sim.decree import _collect_inline_rejections

    db, state, content = game
    collector = RejectionCollector()
    _collect_inline_rejections(collector, {
        "some_section": [{"rejected": True}],  # producer 没给 reason
    }, 1, Provenance.unknown)
    collector.flush_to_db(db)
    db.conn.commit()

    row = db.conn.execute(
        "SELECT reason FROM rejection_reports WHERE section='some_section'").fetchone()
    assert row is not None and row[0]  # 非空兜底


def test_inertia_tolerated_rejections_reach_reports(game, monkeypatch, tmp_path):
    """inertia 自然结案的容忍拒收项也要进 rejection_reports——桥接在 inertia 前
    已跑,只 tlog 等于这条路永远脱离收集器/attempt/provenance 管线,与 tracker-close
    路(issue_summary.entity_rejections 有行)同输入两判(ship-pre r1 codex high)。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    aid = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()[0]
    db.insert_issue(
        state, kind="initiative", title="惯性留痕测试", origin_kind="decree",
        origin_ref="", bar_value=99, bar_good_meaning="成", bar_bad_meaning="败",
        inertia=5, stage_text="", severity=50, region_hint="", faction_hint="",
        tags=[], ongoing_effects={}, cancellable="decree", cancel_cost={},
        effect_on_resolve={"army_delta": {aid: {"origin_ref": "盘面自发", "morale": 1, "士气大振": 9}}},
        effect_on_fail={}, resolve_condition="", fail_condition="",
    )
    db.conn.commit()

    run_settle(db, state, content, {}, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn)
            if r[0] == "issue_inertia.entity_rejections"]
    assert len(rows) == 1
    assert "士气大振" in rows[0][1] or "非法字段" in rows[0][1]


def test_item_json_is_original_delta_item_when_producer_carries_it(game, monkeypatch, tmp_path):
    """rejection_reports.item_json = 原始 delta 项(ADR 决定 5「原 item 原样保留」)
    ——S1-S3 producers 已在 wrapper 里带原件('item' 键),桥接应解包而非存整个
    wrapper(嵌套结构破坏重放分析消费形状,ship-pre r3 codex)。"""
    import json as _json

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn

    run_settle(db, state, content, {
        "power_updates": {"查无此势力": {"origin_ref": "盘面自发", "leverage": 5}},
    }, narrative="x", decree_text="y")

    row = db.conn.execute(
        "SELECT item_json FROM rejection_reports WHERE turn=? AND section='power_changes'",
        (turn,)).fetchone()
    assert row is not None
    item = _json.loads(row[0])
    assert "rejected" not in item  # 不是 wrapper
    assert item == {"power_id": "查无此势力", "changes": {"leverage": 5}}  # 原件


def test_person_change_rejection_item_json_keeps_original_delta_item(game, monkeypatch, tmp_path):
    """人物变更拒收也必须把原始条目带进 rejection_reports，不能只存截断 wrapper。"""
    import json as _json

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    raw_item = {"name": "孔有德", "动作": "行止", "location": "辽东"}

    run_settle(
        db,
        state,
        content,
        {"人物变更": [raw_item]},
        narrative="x",
        decree_text="y",
    )

    row = db.conn.execute(
        "SELECT item_json FROM rejection_reports WHERE turn=? AND section='applied_person_changes'",
        (turn,),
    ).fetchone()
    assert row is not None
    item = _json.loads(row[0])
    assert "rejected" not in item
    assert item == raw_item


def test_power_move_rejection_item_json_keeps_original_person_delta_item(game, monkeypatch, tmp_path):
    """易主委托底层 power helper 后的拒收,也要保留完整 ADR0009 原始条目。"""
    import json as _json

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    name = active_ming_character(db, content)
    raw_item = {
        "name": name,
        "动作": "易主",
        "new_power": "ghost_power",
        "方式": "主动投敌",
        "反噬": {},
        "reason": "测试非法势力",
    }

    run_settle(
        db,
        state,
        content,
        {"人物变更": [raw_item]},
        narrative="x",
        decree_text="y",
    )

    row = db.conn.execute(
        "SELECT item_json FROM rejection_reports WHERE turn=? AND section='applied_person_changes'",
        (turn,),
    ).fetchone()
    assert row is not None
    item = _json.loads(row[0])
    assert "rejected" not in item
    assert item == raw_item


def test_office_change_rejection_item_json_keeps_original_person_delta_item(game, monkeypatch, tmp_path):
    """任命/调任委托任官 helper 后的拒收,也要保留完整 ADR0009 原始条目。"""
    import json as _json

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    name = active_ming_character(db, content)
    raw_item = {"name": name, "动作": "任命", "reason": "漏填官职"}

    run_settle(
        db,
        state,
        content,
        {"人物变更": [raw_item]},
        narrative="x",
        decree_text="y",
    )

    row = db.conn.execute(
        "SELECT category, item_json FROM rejection_reports "
        "WHERE turn=? AND section='applied_person_changes'",
        (turn,),
    ).fetchone()
    assert row is not None
    assert row["category"] == "missing_field"
    item = _json.loads(row["item_json"])
    assert "rejected" not in item
    assert item == raw_item


def test_non_ming_appointment_rejection_keeps_original_person_delta_item(game, monkeypatch, tmp_path):
    """非明人物任大明官被拒时,也要保留完整 ADR0009 原始条目。"""
    import json as _json

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    name = active_ming_character(db, content)
    ch = content.characters[name]
    old_power = ch.power_id
    raw_item = {"name": name, "动作": "任命", "office": "陕西总督", "reason": "测试错授外臣"}

    try:
        ch.power_id = "houjin"
        db.conn.execute("UPDATE characters SET power_id=? WHERE name=?", ("houjin", name))
        db.conn.commit()

        run_settle(
            db,
            state,
            content,
            {"人物变更": [raw_item]},
            narrative="x",
            decree_text="y",
        )

        row = db.conn.execute(
            "SELECT category, item_json FROM rejection_reports "
            "WHERE turn=? AND section='applied_person_changes'",
            (turn,),
        ).fetchone()
        assert row is not None
        assert row["category"] == "invalid_transition"
        item = _json.loads(row["item_json"])
        assert "rejected" not in item
        assert item == raw_item
    finally:
        ch.power_id = old_power
        db.conn.execute("UPDATE characters SET power_id=? WHERE name=?", (old_power, name))
        db.conn.commit()


def test_power_move_backlash_rejection_lands_in_reports(game, monkeypatch, tmp_path):
    """易主本身可落库时,嵌套反噬拒收也要进入 rejection_reports,不能藏在成功项内部。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    name = next(
        candidate
        for candidate, ch in content.characters.items()
        if getattr(ch, "power_id", "ming") == "ming"
        and getattr(ch, "office_type", "") != "后宫"
        and db.get_character_status(candidate)[0] == "active"
    )
    ch = content.characters[name]
    old_power = ch.power_id
    old_office = ch.office
    old_office_type = ch.office_type

    try:
        run_settle(
            db,
            state,
            content,
            {
                "人物变更": [
                    {
                        "origin_ref": "盘面自发", "name": name,
                        "动作": "易主",
                        "new_power": "houjin",
                        "方式": "主动投敌",
                        "反噬": {"查无此势力": {"leverage": 5}},
                        "reason": "测试反噬拒收",
                    }
                ]
            },
            narrative="x",
            decree_text="y",
        )

        rows = [
            dict(row)
            for row in db.conn.execute(
                "SELECT section, reason, category, item_json FROM rejection_reports "
                "WHERE turn=? ORDER BY id",
                (turn,),
            ).fetchall()
        ]
        assert len(rows) == 1
        assert rows[0]["section"] == "applied_person_changes.backlash_results"
        assert rows[0]["reason"] == "power_updates 引用未入库势力 '查无此势力'"
        assert rows[0]["category"] == "hallucinated_id"
        assert json.loads(rows[0]["item_json"]) == {
            "power_id": "查无此势力",
            "changes": {"leverage": 5},
        }
    finally:
        ch.power_id = old_power
        ch.office = old_office
        ch.office_type = old_office_type


def test_issue_close_power_move_backlash_rejection_is_not_duplicated(game, monkeypatch, tmp_path):
    """结案人物变更同时挂 close 详情与 issue_summary 聚合时,嵌套拒收只应入库一次。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    name = active_ming_character(db, content)
    ch = content.characters[name]
    old_power = ch.power_id
    old_office = ch.office
    old_office_type = ch.office_type

    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="结案反噬去重测试",
        origin_kind="decree",
        bar_value=50,
        effect_on_resolve={
            "人物变更": [
                {
                    "origin_ref": "盘面自发", "name": name,
                    "动作": "易主",
                    "new_power": "houjin",
                    "方式": "主动投敌",
                    "反噬": {"查无此势力": {"leverage": 5}},
                    "reason": "测试结案反噬拒收",
                }
            ]
        },
    )
    db.conn.commit()

    try:
        run_settle(
            db,
            state,
            content,
            {"close_issues": [{"issue_id": issue_id, "reason": "resolved", "narrative": "测试结案"}]},
            narrative="x",
            decree_text="y",
        )

        rows = [
            dict(row)
            for row in db.conn.execute(
                "SELECT section, reason, category, item_json FROM rejection_reports "
                "WHERE turn=? ORDER BY id",
                (turn,),
            ).fetchall()
        ]
        assert len(rows) == 1
        assert rows[0]["section"] == "issue_summary.applied_person_changes.backlash_results"
        assert rows[0]["reason"] == "power_updates 引用未入库势力 '查无此势力'"
        assert rows[0]["category"] == "hallucinated_id"
        assert json.loads(rows[0]["item_json"]) == {
            "power_id": "查无此势力",
            "changes": {"leverage": 5},
        }
    finally:
        ch.power_id = old_power
        ch.office = old_office
        ch.office_type = old_office_type


def test_inertia_power_move_backlash_rejection_lands_in_reports(game, monkeypatch, tmp_path):
    """自然结案的人物易主反噬拒收也要入 rejection_reports,不能只藏在 applied 输出里。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    name = active_ming_character(db, content)
    ch = content.characters[name]
    old_power = ch.power_id
    old_office = ch.office
    old_office_type = ch.office_type

    db.insert_issue(
        state,
        kind="situation",
        title="惯性反噬留痕测试",
        bar_value=99,
        inertia=1,
        effect_on_resolve={
            "人物变更": [
                {
                    "origin_ref": "盘面自发", "name": name,
                    "动作": "易主",
                    "new_power": "houjin",
                    "方式": "主动投敌",
                    "反噬": {"查无此势力": {"leverage": 5}},
                    "reason": "测试惯性反噬拒收",
                }
            ]
        },
    )
    db.conn.commit()

    try:
        run_settle(db, state, content, {}, narrative="x", decree_text="y")

        rows = [
            dict(row)
            for row in db.conn.execute(
                "SELECT section, reason, category, item_json FROM rejection_reports "
                "WHERE turn=? ORDER BY id",
                (turn,),
            ).fetchall()
        ]
        assert len(rows) == 1
        assert rows[0]["section"] == "issue_summary.applied_person_changes.backlash_results"
        assert rows[0]["reason"] == "power_updates 引用未入库势力 '查无此势力'"
        assert rows[0]["category"] == "hallucinated_id"
    finally:
        ch.power_id = old_power
        ch.office = old_office
        ch.office_type = old_office_type


def test_resimulation_inherits_player_source_from_ctx(game, monkeypatch, tmp_path):
    """#146 A：HITL 续跑 / 崩溃重抽走 resolve_decisions_phase2 → _settle_after_narrative 时，source 从
    ctx['source'] 继承（phase1 皇帝下旨存的 player_decree），不因重抽退化成 system。重抽是格式重跑、
    皇帝原旨没变 → 来源不变（用户拍）。验：重抽路拒收 source 仍 player_decree。"""
    import ming_sim.decree as decree_mod
    from ming_sim.applier import Provenance
    from ming_sim.models import TurnPhase

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    # phase1：皇帝下旨暂停存 ctx（source=player_decree, ready=0 占位）+ 决策点
    db.save_resolve_context(turn, "减赋诏", "本月邸报。", {},
                            secret_orders={}, relevant_memories=[],
                            source=Provenance.player_decree.value)
    db.save_pending_decisions(turn, [{"title": "T", "options": ["a", "b"], "chosen": "a"}])
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    # phase2 重新推演：extractor 产坏 delta（拒收）
    monkeypatch.setattr(decree_mod, "build_extractor_shared_context", lambda *a, **k: "")
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({"character_status_changes": [
            {"origin_ref": "盘面自发", "name": "查无此人辛", "status": "dead", "reason": "测试"}]}, "out", "in"))

    decree_mod.resolve_decisions_phase2(state, db, None, None, content=content, registry=None)

    rows = _rejection_rows(db, turn)
    assert len(rows) == 1
    assert rows[0][3] == "player_decree"  # #146 A：重抽贯穿 ctx 的 player，不退化 system


def test_player_decree_rejection_surfaces_prompt_in_turn_report(game, monkeypatch, tmp_path):
    """#146 A 闭环：皇帝下旨结算里 delta 被拒（player_decree 来源）→ 邸报附「窒碍未行」可见提示、落
    turn_reports（决定 5）。修前 source 恒 system、has_player_visible_rejection 永 False、提示从不出。"""
    import ming_sim.decree as decree_mod

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "simulate_season_with_payload",
                        lambda *a, **k: ("本月邸报。", k.get("simulator_payload") or {}))
    monkeypatch.setattr(decree_mod, "build_extractor_shared_context", lambda *a, **k: "")
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({"character_status_changes": [
            {"origin_ref": "盘面自发", "name": "查无此人壬", "status": "dead", "reason": "测试"}]}, "out", "in"))

    decree_mod.resolve_directives(state, db, None, None, [1], "减赋诏",
                                  content=content, registry=None)

    report = db.conn.execute(
        "SELECT report FROM turn_reports WHERE turn=?", (turn,)).fetchone()
    assert report is not None
    assert "窒碍未行" in report[0]  # #146 A：皇帝来源拒收 → 邸报可见提示（修前恒静默）


def test_system_rejection_stays_silent_and_keeps_system_provenance(game, monkeypatch, tmp_path):
    """#146 A 对照（B 面，Sourcery #175 建议）：无旨 / 世界自演变（system_simulation 来源）的 delta 被拒
    → 拒收记 system_simulation、且邸报**不**出「窒碍未行」可见提示（系统拒收对玩家静默）。与
    test_player_decree_rejection_surfaces_prompt_in_turn_report 构成 A/B 对照，锁死「可见性↔来源」
    契约：玩家来源拒收提示、系统来源静默（决定 5），防回归把系统拒收暴露给皇帝。
    走重抽路（resolve_decisions_phase2 从 ctx['source'] 继承）顺带覆盖 _provenance_from_stored。"""
    import ming_sim.decree as decree_mod
    from ming_sim.applier import Provenance
    from ming_sim.models import TurnPhase

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    # phase1：无旨自演变暂停存 ctx（source=system_simulation, ready=0 占位）+ 决策点
    db.save_resolve_context(turn, "", "本月邸报。", {},
                            secret_orders={}, relevant_memories=[],
                            source=Provenance.system_simulation.value)
    db.save_pending_decisions(turn, [{"title": "T", "options": ["a", "b"], "chosen": "a"}])
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    # phase2 重新推演：extractor 产坏 delta（拒收）——与 player 路同款坏 payload，仅来源不同
    monkeypatch.setattr(decree_mod, "build_extractor_shared_context", lambda *a, **k: "")
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({"character_status_changes": [
            {"origin_ref": "盘面自发", "name": "查无此人癸", "status": "dead", "reason": "测试"}]}, "out", "in"))

    decree_mod.resolve_decisions_phase2(state, db, None, None, content=content, registry=None)

    # A 来源：拒收来自 system_simulation（重抽继承 ctx、不误标 player）
    rows = _rejection_rows(db, turn)
    assert len(rows) == 1
    assert rows[0][3] == "system_simulation"

    # B 可见性：系统来源拒收对玩家静默——邸报无「窒碍未行」提示
    report = db.conn.execute(
        "SELECT report FROM turn_reports WHERE turn=?", (turn,)).fetchone()
    assert report is not None
    assert "窒碍未行" not in report[0]


def test_provenance_from_stored_recovers_all_forms():
    """#146/#175 R2（gemini + coderabbit concur）：_provenance_from_stored 三层兼容——
    Provenance 实例、纯值字符串、历史误序列化的 'Provenance.<name>' 脏串都能还原回原来源，
    不静默退化成 system_simulation；只有真正非法/缺失才回落。"""
    from ming_sim.decree import _provenance_from_stored
    from ming_sim.applier import Provenance

    # ① Provenance 实例原样返回
    assert _provenance_from_stored(Provenance.player_decree) is Provenance.player_decree
    # ② 纯值字符串（正常持久化形态）
    assert _provenance_from_stored("player_decree") == Provenance.player_decree
    assert _provenance_from_stored("system_simulation") == Provenance.system_simulation
    # ③ 历史 str(枚举实例) 脏串 'Provenance.player_decree'——剥前缀按成员名查回（本轮硬化点）
    assert _provenance_from_stored("Provenance.player_decree") == Provenance.player_decree
    assert _provenance_from_stored("Provenance.system_simulation") == Provenance.system_simulation
    # ④ 非法/缺失 → system_simulation 回落
    assert _provenance_from_stored("") == Provenance.system_simulation
    assert _provenance_from_stored(None) == Provenance.system_simulation
    assert _provenance_from_stored("查无此来源") == Provenance.system_simulation
    assert _provenance_from_stored("Provenance.查无此成员") == Provenance.system_simulation


def test_settling_recovery_fallthrough_preserves_system_source(content, tmp_path, monkeypatch):
    """#146 cmr r2（Claude clarity + codex medium concur）：SETTLING 非 ready 崩溃恢复
    fallthrough（ctx 存在但 extracted is None）重走 resolve_directives 重新推演结算时，必须把存档
    ctx['source'] 经 _provenance_from_stored 穿透传入——provenance 按构造保真。

    构造一条 source=system_simulation 的非 ready SETTLING ctx（clear_for_resimulation 把 ready ctx
    降级成 ready=0 保留 source、driver persist system 来源 ctx 都会留下此形态），让 extractor 产个会被拒
    的坏 delta，经 session.resolve_turn() 走恢复 fallthrough 结算，断言：拒收行 source==system_simulation
    （不被误标 player_decree）+ 邸报无「窒碍未行」（系统拒收对玩家静默）。

    红验：把 step2 的 source 穿透改回硬编码 player_decree（resolve_directives 不读 ct'source）→ 该测试红
    （source 误标 player、邸报出现「窒碍未行」）；恢复穿透后绿。"""
    import ming_sim.decree as decree_mod
    from ming_sim.applier import Provenance
    from ming_sim.models import LLMConfig, TurnPhase
    from ming_sim.session import GameSession

    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "user_data"))
    cfg = LLMConfig(api_key="", base_url="http://unused", model="unused")
    dbp = str(tmp_path / "recovery.db")
    sess = GameSession(db_path=dbp, llm_config=cfg, content=content)
    try:
        db, state = sess.db, sess.state
        turn = state.turn

        # 模拟崩溃后的非 ready SETTLING 状态：source=system_simulation 的占位 ctx（ready=0，无 extracted），
        # decree_text 作哨兵草案（FRONT_HALF_DONE 免草案恢复路据它续跑）。
        db.save_resolve_context(
            turn, "某诏", "本月邸报。", {},
            secret_orders={}, relevant_memories=[],
            source=Provenance.system_simulation.value,
        )
        state.turn_phase = TurnPhase.SETTLING.value
        db.save_state(state)
        # 跨进程恢复：内存 last_decree 已被 begin_turn 清空（哨兵草案从 ctx['decree_text'] 恢复）。
        sess.last_decree = ""

        # 重新推演：simulator 出无决策块邸报、extractor 产坏 delta（拒收）。
        monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
        monkeypatch.setattr(decree_mod, "simulate_season_with_payload",
                            lambda *a, **k: ("本月邸报。", k.get("simulator_payload") or {}))
        monkeypatch.setattr(decree_mod, "build_extractor_shared_context", lambda *a, **k: "")
        monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
        monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: None)
        monkeypatch.setattr(
            decree_mod, "extract_scores_by_modules_with_agno",
            lambda *a, **k: ({"character_status_changes": [
                {"origin_ref": "盘面自发", "name": "查无此人子", "status": "dead", "reason": "测试"}]}, "out", "in"))

        sess.resolve_turn()

        # A 来源：恢复 fallthrough 穿透 ctx['source'] → 拒收记 system_simulation，不误标 player。
        rows = _rejection_rows(db, turn)
        assert len(rows) == 1
        assert rows[0][3] == "system_simulation"

        # B 可见性：系统来源拒收对玩家静默——邸报无「窒碍未行」提示。
        report = db.conn.execute(
            "SELECT report FROM turn_reports WHERE turn=?", (turn,)).fetchone()
        assert report is not None
        assert "窒碍未行" not in report[0]
    finally:
        try:
            sess.close()
        except Exception:
            pass
