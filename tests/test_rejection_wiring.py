"""PR2-S0(ADR 0008 决定 5/8,#91)——拒收收集器接进结算管线。

生命周期与事务对齐:apply 产生的拒收项 → 事务内 flush 进 rejection_reports →
commit 成功后镜像 jsonl → 回滚路 reset 不留行不留镜像。attempt 从错误目录推导
(不从 DB 取,随回滚重置即失真)。经 driver.run_settle 端到端驱动(公共接口)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from driver import run_settle
from tests.conftest import active_ming_character


def _rejection_rows(db, turn):
    try:
        return db.conn.execute(
            "SELECT section, reason, category, source, attempt FROM rejection_reports"
            " WHERE turn=? ORDER BY id", (turn,)
        ).fetchall()
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


def test_engine_extractor_path_stamps_system_simulation(game, monkeypatch, tmp_path):
    """引擎 resolve 路(simulator→extractor→settle)的拒收行 source=system_simulation
    ——extractor 产出属推演管线,与 driver 信封(unknown 兜底)区分(决定 5 provenance)。"""
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
            {"name": "查无此人丁", "status": "dead", "reason": "测试"}]}, "out", "in"))

    decree_mod.resolve_directives(state, db, None, None, [1], "减赋诏",
                                  content=content, registry=None)

    rows = _rejection_rows(db, turn)
    assert len(rows) == 1
    assert rows[0][3] == "system_simulation"  # source


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
        "appointments": [{"name": existing, "office": "贵妃", "office_type": "后宫",
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
        effect_on_resolve={"army_delta": {aid: {"morale": 1, "士气大振": 9}}},
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
        "power_updates": {"查无此势力": {"leverage": 5}},
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
                        "name": name,
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
                    "name": name,
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
                    "name": name,
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
