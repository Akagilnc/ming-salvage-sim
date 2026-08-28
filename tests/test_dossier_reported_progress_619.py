"""#619: 通用奏报记录持久轨（非密令执行面案卷通用化）。

双物理轨：密令仍走 secret_orders 私轨；非密令走 dossier_reported_progress。
读端统一 list_dossier_progress；写端分流。奏报永不入 apply。
"""

from __future__ import annotations

import json

import pytest

import ming_sim.issues as issue_engine
from ming_sim.db import GameDB
from tests.dossier_test_helpers import investigation_covert_task


DOSSIER_REPORT_MONTHLY = "dossier-report:monthly_errand"
DOSSIER_REPORT_VERDICT = "dossier-report:execution_verdict"


def _executing_assignment(db, state, *, text="清丈畿辅田亩", target="land-survey-619"):
    """Non-secret execution-surface dossier (policy = narrative in_transit)."""
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=text,
        target_kind="issue",
        target_id=target,
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    row = db.get_decree_dossier(dossier_id)
    assert row["status"] == "executing"
    assert row.get("secret_order_id") in (None, 0)
    return dossier_id


def _world_fingerprint(db):
    accounts = [
        tuple(row)
        for row in db.conn.execute(
            "SELECT account, balance FROM economy_accounts ORDER BY account"
        ).fetchall()
    ]
    ledger_n = db.conn.execute("SELECT COUNT(*) AS n FROM economy_ledger").fetchone()["n"]
    metrics = [
        tuple(row)
        for row in db.conn.execute(
            "SELECT key, value FROM metrics ORDER BY key"
        ).fetchall()
    ]
    regions = [
        tuple(row)
        for row in db.conn.execute(
            "SELECT id, public_support, unrest, population, tax_per_turn "
            "FROM regions ORDER BY id"
        ).fetchall()
    ]
    region_logs_n = db.conn.execute("SELECT COUNT(*) AS n FROM region_logs").fetchone()["n"]
    armies = [
        tuple(row)
        for row in db.conn.execute(
            "SELECT id, manpower, morale, arrears, supply FROM armies ORDER BY id"
        ).fetchall()
    ]
    army_logs_n = db.conn.execute("SELECT COUNT(*) AS n FROM army_logs").fetchone()["n"]
    return {
        "accounts": accounts,
        "ledger_n": ledger_n,
        "metrics": metrics,
        "regions": regions,
        "region_logs_n": region_logs_n,
        "armies": armies,
        "army_logs_n": army_logs_n,
    }


def test_execution_surface_dossier_can_record_and_list_full_history(game):
    db, state, content = game
    dossier_id = _executing_assignment(db, state)

    first = db.record_dossier_progress(
        dossier_id, state.turn, "启程", "已分派书吏出京",
        origin=DOSSIER_REPORT_MONTHLY,
    )
    second = db.record_dossier_progress(
        dossier_id, state.turn + 1, "在办", "畿南三县清册已齐",
        origin=DOSSIER_REPORT_MONTHLY,
    )
    assert first > 0 and second > 0 and second != first

    rows = db.list_dossier_progress(dossier_id)
    assert [row["turn"] for row in rows] == [state.turn, state.turn + 1]
    assert [row["progress_band"] for row in rows] == ["启程", "在办"]
    assert [row["memorial_text"] for row in rows] == [
        "已分派书吏出京", "畿南三县清册已齐",
    ]
    assert all(row["origin"] == DOSSIER_REPORT_MONTHLY for row in rows)
    assert all(row["dossier_id"] == dossier_id for row in rows)
    assert all(row["is_terminal"] is False for row in rows)

    # Physical general track only — never the secret_orders private JSON rail.
    general_count = db.conn.execute(
        "SELECT COUNT(*) AS n FROM dossier_reported_progress WHERE dossier_id=?",
        (dossier_id,),
    ).fetchone()["n"]
    assert general_count == 2
    leaked = db.conn.execute(
        "SELECT COUNT(*) AS n FROM secret_orders WHERE dossier_progress_json != '[]'"
    ).fetchone()["n"]
    assert leaked == 0

    # #883: general rail has no shared secret/track flag column.
    cols = {
        row["name"]
        for row in db.conn.execute("PRAGMA table_info(dossier_reported_progress)").fetchall()
    }
    assert "is_secret" not in cols
    assert "secret" not in cols
    assert "track" not in cols


def test_secret_monthly_path_unchanged_and_stays_on_private_rail(game):
    db, state, content = game
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"]
    order_id = db.create_secret_order(state, actor, "护行辽饷", "逐月办理", ["护行"], deadline_months=4, covert_task=investigation_covert_task("护行辽饷"))
    dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])

    db.record_monthly_dossier_progress(state.turn, [{
        "dossier_id": dossier_id,
        "progress_band": "在途",
        "memorial_text": "首批已出关619",
    }])
    rows = db.list_dossier_progress(dossier_id)
    assert len(rows) == 1
    assert rows[0]["memorial_text"] == "首批已出关619"
    assert rows[0]["origin"] == DOSSIER_REPORT_MONTHLY

    stored = db.conn.execute(
        "SELECT dossier_progress_json FROM secret_orders WHERE id=?", (order_id,),
    ).fetchone()
    assert json.loads(stored["dossier_progress_json"])[0]["memorial_text"] == "首批已出关619"
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM dossier_reported_progress WHERE dossier_id=?",
        (dossier_id,),
    ).fetchone()["n"] == 0


def test_short_and_one_shot_dossiers_have_no_empty_monthly_shell(game):
    db, state, content = game
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"]
    short_id = db.create_secret_order(state, actor, "护行急件", "一月即结", ["护行"], deadline_months=1, covert_task=investigation_covert_task("护行急件"))
    short_dossier = int(db.get_dossier_for_secret_order(short_id)["id"])
    one_shot = _executing_assignment(db, state, text="一次性清查", target="one-shot-619")

    # 一月期密令仍入 0058；非密令一次性案卷不入密令月报候选
    assert [item["dossier_id"] for item in db.list_monthly_dossier_progress_nudges()] == [short_dossier]
    assert db.list_dossier_progress(short_dossier) == []
    assert db.list_dossier_progress(one_shot) == []
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM dossier_reported_progress"
    ).fetchone()["n"] == 0
    with pytest.raises(ValueError, match="缺少本月密奏"):
        db.record_monthly_dossier_progress(state.turn, [])


def test_origin_namespace_minimum_closed_set_and_open_append(game):
    db, state, content = game
    dossier_id = _executing_assignment(db, state)

    db.record_dossier_progress(
        dossier_id, state.turn, "月报", "本月无异",
        origin=DOSSIER_REPORT_MONTHLY,
    )
    db.record_dossier_progress(
        dossier_id, state.turn, "变形陈词", "实未办成而报已成",
        is_terminal=True, origin=DOSSIER_REPORT_VERDICT,
    )
    # ID-11 open append: a future origin under the same namespace is accepted.
    extra = db.record_dossier_progress(
        dossier_id, state.turn + 1, "垂问答", "奉问补陈",
        origin="dossier-report:inquiry_reply",
    )
    assert extra > 0
    origins = {row["origin"] for row in db.list_dossier_progress(dossier_id)}
    assert DOSSIER_REPORT_MONTHLY in origins
    assert DOSSIER_REPORT_VERDICT in origins
    assert "dossier-report:inquiry_reply" in origins

    with pytest.raises(ValueError, match="origin"):
        db.record_dossier_progress(
            dossier_id, state.turn + 2, "非法", "无命名空间",
            origin="raw-unnamespaced",
        )
    with pytest.raises(ValueError, match="origin"):
        db.record_dossier_progress(
            dossier_id, state.turn + 2, "非法", "空后缀",
            origin="dossier-report:",
        )


def test_production_terminal_sidepath_records_degraded_transformed_only(game):
    db, state, content = game
    degraded_id = _executing_assignment(db, state, target="deg-619")
    transformed_id = _executing_assignment(db, state, text="变形案", target="xf-619")
    fulfilled_id = _executing_assignment(db, state, text="办妥案", target="ok-619")
    failed_id = _executing_assignment(db, state, text="失败案", target="fail-619")

    issue_engine.apply_score_extraction(
        db, state,
        {"dossier_executions": [
            {"dossier_id": degraded_id, "outcome": "degraded", "note": "只得半成"},
            {"dossier_id": transformed_id, "outcome": "transformed", "note": "名实已乖"},
            {"dossier_id": fulfilled_id, "outcome": "fulfilled", "note": "如期办妥"},
            {"dossier_id": failed_id, "outcome": "failed", "note": "事败不成"},
        ]},
        content=content,
    )

    deg = db.list_dossier_progress(degraded_id)
    xf = db.list_dossier_progress(transformed_id)
    assert len(deg) == 1 and deg[0]["is_terminal"] is True
    assert deg[0]["origin"] == DOSSIER_REPORT_VERDICT
    # #622：progress_band 定性中文，禁英文枚举；变形案 memorial 为承办人假象。
    assert deg[0]["progress_band"] not in {
        "degraded", "transformed", "fulfilled", "failed", "executing",
    }
    assert "变形" not in deg[0]["progress_band"]
    assert deg[0]["memorial_text"]  # 非空定性陈词
    assert "名实已乖" not in deg[0]["memorial_text"]  # 不回填判官 note
    assert len(xf) == 1 and xf[0]["origin"] == DOSSIER_REPORT_VERDICT
    assert xf[0]["progress_band"] not in {
        "degraded", "transformed", "fulfilled", "failed", "executing",
    }
    assert "变形" not in xf[0]["progress_band"]
    assert "名实已乖" not in xf[0]["memorial_text"]  # 假象，非判官真值
    assert db.list_dossier_progress(fulfilled_id) == []
    assert db.list_dossier_progress(failed_id) == []

    # Execution-slot / joint-liability semantics untouched: outcomes still land.
    assert db.get_decree_dossier(degraded_id)["execution_outcome"] == "degraded"
    assert db.get_decree_dossier(transformed_id)["execution_outcome"] == "transformed"
    assert db.get_decree_dossier(fulfilled_id)["execution_outcome"] == "fulfilled"
    assert db.get_decree_dossier(failed_id)["execution_outcome"] == "failed"
    # 判官真值只在执行格 note，不进奏报轨。
    assert "名实已乖" in (
        db.get_decree_dossier(transformed_id).get("execution_note") or ""
    )


def test_fake_progress_report_does_not_change_world_state(game):
    """0073 negative: 假进度奏报 → 国库/区域/军队零变化。"""
    db, state, content = game
    dossier_id = _executing_assignment(db, state)
    before = _world_fingerprint(db)

    db.record_dossier_progress(
        dossier_id, state.turn, "已全完", "田亩尽数清丈、国库应增百万",
        origin=DOSSIER_REPORT_MONTHLY,
    )
    # Also exercise the production terminal sidepath text surface.
    db.record_dossier_progress(
        dossier_id, state.turn, "变形", "奏称完结而实未动库",
        is_terminal=True, origin=DOSSIER_REPORT_VERDICT,
    )

    after = _world_fingerprint(db)
    assert after == before
    assert len(db.list_dossier_progress(dossier_id)) == 2


def test_restore_preserves_report_history(game, tmp_path, content):
    db, state, _content = game
    dossier_id = _executing_assignment(db, state)
    db.record_dossier_progress(
        dossier_id, state.turn, "启程", "出京核验",
        origin=DOSSIER_REPORT_MONTHLY,
    )
    db.record_dossier_progress(
        dossier_id, state.turn + 1, "在办", "已至保定",
        origin=DOSSIER_REPORT_MONTHLY,
    )
    expected = db.list_dossier_progress(dossier_id)
    assert len(expected) == 2

    backup = tmp_path / "restore-619.db"
    db.backup_to(str(backup))
    db.close()

    restored = GameDB(str(backup), content=content)
    try:
        rows = restored.list_dossier_progress(dossier_id)
        assert rows == expected
        # Append after restore continues the same physical history.
        restored.record_dossier_progress(
            dossier_id, state.turn + 2, "将结", "三县完册",
            origin=DOSSIER_REPORT_MONTHLY,
        )
        cont = restored.list_dossier_progress(dossier_id)
        assert [row["memorial_text"] for row in cont] == [
            "出京核验", "已至保定", "三县完册",
        ]
    finally:
        restored.close()


def test_terminal_surface_dossier_rejects_reported_progress(game):
    """Terminal/non-execution surface: record raises; general rail stays empty."""
    db, state, content = game
    holder = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"]
    dossier_id = db.create_decree_dossier(
        state,
        action_type="authorization",
        decree_text="授以便宜行事",
        target_kind="issue",
        target_id="terminal-gate-619",
        executor_kind="character",
        executor_id=holder,
        participants=[{"character_id": holder, "tier": "主办"}],
        payload={"mode": "ordinary"},
    )

    with pytest.raises(ValueError, match="非执行面"):
        db.record_dossier_progress(
            dossier_id, state.turn, "已授", "非法挂奏报",
            origin=DOSSIER_REPORT_MONTHLY,
        )

    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM dossier_reported_progress"
    ).fetchone()["n"] == 0
    assert db.list_dossier_progress(dossier_id) == []
