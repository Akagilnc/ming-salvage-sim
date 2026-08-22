"""Ming #721 / ADR 0117：承办人主办档确定性路由聚焦测试。

覆盖：覆盖域判别（入/排除两侧 golden）、点将多人=多主办、职司词干表
兜底路由（钱粮/缉捕/清丈/任免样张）、缺位降档链、未命中映射 fail-loud
进 rejections（不落怠办）、restore 往返只读 DB 无损接续。
"""

from __future__ import annotations

import json

import pytest

import pytest

from ming_sim.executor_routing import (
    apply_lead_binding,
    classify_execution_coverage,
    duty_route_office_type,
    resolve_lead_executors,
)


@pytest.fixture
def env(game):
    db, _state, content = game
    return db, content


# ── 覆盖域判别（0116 三类 vs 立即 delta 排除）───────────────────────────


@pytest.mark.parametrize(
    "action_type,expected",
    [
        ("assignment", "multi_month"),  # 多月执行类（清丈/督赈差务）
        ("military_order", "multi_month"),
        ("punishment", "strike"),  # 打击类（抄家/缉拿）差务化
        ("appointment", "appointment"),  # 任免过执行层
        ("acting_appointment", "appointment"),
    ],
)
def test_coverage_included_actions(action_type, expected):
    assert classify_execution_coverage(action_type) == expected


@pytest.mark.parametrize(
    "action_type",
    [
        "grant_allocation",  # 赏赐/开仓等立即 delta 类 → 排除
        "pacification",
        "authorization",
        "secret_order",
        "policy",
        "",
    ],
)
def test_coverage_excluded_actions(action_type):
    assert classify_execution_coverage(action_type) is None


# ── 事务类别→职司映射数据件（offices.json 同族显式扩展）───────────────


def test_duty_route_table_golden():
    assert duty_route_office_type("钱粮") == "户部"
    assert duty_route_office_type("清丈") == "户部"
    assert duty_route_office_type("督赈") == "户部"
    assert duty_route_office_type("缉拿") == "锦衣卫"
    assert duty_route_office_type("缉捕") == "刑部"
    assert duty_route_office_type("河工") == "工部"


def test_duty_route_unmapped_returns_none():
    """未命中映射 = fail-loud 哨兵 None，不是空串也不是静默兜底。"""
    assert duty_route_office_type("修仙") is None
    assert duty_route_office_type("") is None


# ── 路由：任免＝被任命者本人 ─────────────────────────────────────────


def test_appointment_routes_to_appointee(env):
    db, _ = env
    result = resolve_lead_executors(
        db.conn,
        action_type="appointment",
        target_id="陈新甲",
    )
    assert result["route"] == "appointment_self"
    assert result["leads"] == ["陈新甲"]
    assert result["signal"] is None


def test_appointment_without_target_is_idle_start(env):
    db, _ = env
    result = resolve_lead_executors(db.conn, action_type="appointment")
    assert result["leads"] == []
    assert result["signal"]["code"] == "idle_start"


# ── 点将优先：多人＝多主办；未点将走职司兜底 ─────────────────────────


def test_named_multiple_leads(env):
    db, _ = env
    roster = [
        {"tier": "主办", "character_id": "毕自严"},
        {"tier": "主办", "character_id": "陈新甲", "delegator_id": ""},
        {"tier": "协办", "character_id": "某人"},
        {"tier": "主办", "delegator_id": "毕自严", "character_id": "门生"},  # 大臣遣≠皇帝点将
    ]
    result = resolve_lead_executors(
        db.conn,
        action_type="assignment",
        transaction_category="钱粮",
        participant_roster=roster,
    )
    assert result["route"] == "named"
    assert result["leads"] == ["毕自严", "陈新甲"]  # 0053 主办可多人，顺序确定


def test_duty_table_fallback_single_lead(env):
    """seed 开局盘面上 清丈→户部 主官（毕自严，户部尚书）确定性命中。"""
    conn = env[0].conn
    result = resolve_lead_executors(
        conn,
        action_type="assignment",
        transaction_category="清丈",
        participant_roster=[],
    )
    assert result["route"] == "duty_table"
    assert result["office_type"] == "户部"
    assert result["leads"] == ["毕自严"]
    assert result["downgrade_step"] == "主官"


def test_vacancy_downgrade_chain_chief_to_acting(env):
    """主官出缺 → 降档到署理；映射仍命中（非 rejections）。"""
    conn = env[0].conn
    conn.execute(
        "INSERT INTO characters(name, office, office_type, faction, personal_skills,"
        " loyalty, ability, integrity, courage, style, power_id)"
        " VALUES('署理侍郎甲','署理户部侍郎','户部','朝','',5,5,5,5,'','ming')"
    )
    # 主官全出缺（真除者不在任）
    conn.execute(
        "UPDATE characters SET status='retired'"
        " WHERE office_type='户部' AND name != '署理侍郎甲'"
    )
    result = resolve_lead_executors(
        conn,
        action_type="assignment",
        transaction_category="钱粮",
    )
    assert result["leads"] == ["署理侍郎甲"]
    assert result["downgrade_step"] == "署理降档"


def test_vacancy_chain_exhausted_idle_start_not_rejection(env):
    """映射命中但在任者全出缺 → 怠办起步信号（非 rejections）。"""
    db, _ = env
    # 映射命中（钱粮→户部）但户部在任者全出缺
    db.conn.execute("UPDATE characters SET status='retired' WHERE office_type='户部'")
    result = resolve_lead_executors(
        db.conn,
        action_type="assignment",
        transaction_category="钱粮",
    )
    assert result["leads"] == []
    assert result["office_type"] == "户部"
    assert result["signal"]["code"] == "idle_start"
    assert result["rejection"] is None


def test_unmapped_category_fails_loud_as_rejection(env):
    """未命中映射 ≠ 无人可承：fail-loud 进 rejections，不落怠办。"""
    db, _ = env
    result = resolve_lead_executors(
        db.conn,
        action_type="assignment",
        transaction_category="修仙",
    )
    assert result["signal"] is None
    rejection = result["rejection"]
    assert rejection["section"] == "executor_routing"
    assert rejection["reason_code"] == "duty_route_unmapped"
    assert rejection["category"] == "修仙"


def test_routing_deterministic_same_inputs_same_output(env):
    conn = env[0].conn
    kwargs = dict(action_type="assignment", transaction_category="缉捕")
    a = resolve_lead_executors(conn, **kwargs)
    b = resolve_lead_executors(conn, **kwargs)
    assert a == b


# ── 落库绑定与 restore 往返 ──────────────────────────────────────────


def _insert_dossier(conn, *, action_type, target_id="", category="", roster=None):
    cur = conn.execute(
        "INSERT INTO decree_dossiers(action_type, target_kind, target_id,"
        " payload_json, participant_roster, created_turn, created_year, created_period)"
        " VALUES(?,?,?,?,?,?,0,0)",
        (
            action_type,
            "character" if target_id else "",
            target_id,
            json.dumps({"transaction_category": category}, ensure_ascii=False),
            json.dumps(roster or [], ensure_ascii=False),
            1,
        ),
    )
    return cur.lastrowid


def test_apply_lead_binding_persists_and_restore_roundtrip(env):
    db, content = env
    conn = db.conn
    expected = resolve_lead_executors(conn, action_type="assignment", transaction_category="缉拿")
    assert expected["leads"], "seed 盘面锦衣卫应有在任主官"
    dossier_id = _insert_dossier(
        conn,
        action_type="assignment",
        category="缉拿",
        roster=[
            {"tier": "主办", "character_id": "锦衣千户", "delegator_id": "某督"},
            {"tier": "知情", "character_id": "路人"},
        ],
    )
    result = apply_lead_binding(conn, dossier_id)
    assert result["leads"] == expected["leads"]
    lead_name = result["leads"][0]
    conn.commit()  # 落库归调用方事务；restore 前显式提交

    # restore 往返：重开连接只读 DB 无损接续
    path = db.path
    db.close()
    from ming_sim.db import GameDB

    db2 = GameDB(path, content)
    try:
        row = db2.conn.execute(
            "SELECT participant_roster FROM decree_dossiers WHERE id=?",
            (dossier_id,),
        ).fetchone()
        entries = [e for e in json.loads(row[0]) if e.get("tier") == "主办"]
        assert [e.get("character_id") for e in entries] == [lead_name]
    finally:
        db2.close()


def test_apply_lead_binding_idempotent_no_duplicate_leads(env):
    conn = env[0].conn
    dossier_id = _insert_dossier(conn, action_type="appointment", target_id="陈新甲")
    apply_lead_binding(conn, dossier_id)
    apply_lead_binding(conn, dossier_id)
    row = conn.execute(
        "SELECT participant_roster FROM decree_dossiers WHERE id=?", (dossier_id,)
    ).fetchone()
    leads = [
        e for e in json.loads(row[0]) if e.get("tier") == "主办"
    ]
    assert len(leads) == 1
