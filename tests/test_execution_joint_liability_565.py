"""#565 执行格终值链 + 委派连坐（唯一契约 r3）。"""

import json

import pytest

import ming_sim.issues as issue_engine
from ming_sim.strict_types import validate_affected_parties


def _roster():
    """主办倪元璐←委派徐光启（协办位，仅次责）；另有协办黄道周、知情王承恩。

    委派人须同案主办/协办（db._validate_dossier_delegations）。徐光启占协办位，
    专测次责降档路径；双角色（委派人兼主办）见 test_dual_role_*。
    """
    return [
        {
            "character_id": "倪元璐", "tier": "主办", "role": "清丈",
            "delegator_id": "徐光启",
        },
        {"character_id": "徐光启", "tier": "协办", "role": "坐镇"},
        {"character_id": "黄道周", "tier": "协办", "role": "核账"},
        {"character_id": "王承恩", "tier": "知情", "role": "备悉"},
    ]


def _executing_dossier(db, state, *, roster=None):
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清丈畿辅",
        target_kind="issue", target_id="land-survey-565",
        participants=roster if roster is not None else _roster(),
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    assert db.get_decree_dossier(dossier_id)["status"] == "executing"
    return dossier_id


def _cost_events(db, dossier_id, *, identity="连坐"):
    return [dict(row) for row in db.conn.execute(
        "SELECT * FROM decree_cost_events WHERE dossier_id=? AND cost_identity=? ORDER BY id",
        (int(dossier_id), identity),
    ).fetchall()]


def _sat_events(db, dossier_id):
    return [
        row for row in _cost_events(db, dossier_id)
        if row["cost_kind"] == "satisfaction"
    ]


def _sat(db, faction):
    return db.conn.execute(
        "SELECT satisfaction FROM factions WHERE name=?", (faction,),
    ).fetchone()[0]


def _close_via_adapter(db, state, content, dossier_id, outcome, note="办理走样", **extra):
    item = {"dossier_id": dossier_id, "outcome": outcome, "note": note}
    item.update(extra)
    return issue_engine.apply_score_extraction(
        db, state, {"dossier_executions": [item]}, content=content,
    )


def test_fulfilled_writes_zero_joint_liability_rows(game):
    db, state, content = game
    dossier_id = _executing_dossier(db, state)
    before_donglin = _sat(db, "东林")
    before_xixue = _sat(db, "西学")

    result = _close_via_adapter(db, state, content, dossier_id, "fulfilled", note="如期办妥")

    assert result["dossier_executions"] == [{"dossier_id": dossier_id, "outcome": "fulfilled"}]
    assert _cost_events(db, dossier_id) == []
    assert _sat(db, "东林") == before_donglin
    assert _sat(db, "西学") == before_xixue
    assert db.get_relation_edge_events(event_kind="连坐") == []


@pytest.mark.parametrize(
    ("outcome", "lead_delta", "delegator_delta"),
    [
        ("failed", -8, -4),
        ("transformed", -8, -4),
        ("degraded", -4, None),
    ],
)
def test_terminal_outcomes_charge_lead_and_downgraded_delegator(
    game, outcome, lead_delta, delegator_delta,
):
    db, state, content = game
    dossier_id = _executing_dossier(db, state)
    before_donglin = _sat(db, "东林")
    before_xixue = _sat(db, "西学")
    before_huang = _sat(db, "皇党")

    result = _close_via_adapter(
        db, state, content, dossier_id, outcome, note="门生办砸，走样",
    )

    assert result["dossier_executions"] == [{"dossier_id": dossier_id, "outcome": outcome}]
    assert _sat(db, "东林") == max(0, before_donglin + lead_delta)
    if delegator_delta is None:
        assert _sat(db, "西学") == before_xixue
    else:
        assert _sat(db, "西学") == max(0, before_xixue + delegator_delta)
    assert _sat(db, "皇党") == before_huang

    sat = {
        (row["target_kind"], row["target_id"], row["delta"])
        for row in _sat_events(db, dossier_id)
    }
    expected = {("faction", "东林", lead_delta)}
    if delegator_delta is not None:
        expected.add(("faction", "西学", delegator_delta))
    assert sat == expected

    edges = [
        e for e in db.get_relation_edge_events(event_kind="连坐")
        if e["origin"].startswith(f"dossier:{dossier_id}:")
    ]
    targets = {e["target"] for e in edges}
    assert "倪元璐" in targets
    if delegator_delta is None:
        # degraded：委派人零机械边，但仍进走样说明
        assert "徐光启" not in targets
    else:
        assert "徐光启" in targets
    assert not {"黄道周", "王承恩"} & targets

    note = db.get_decree_dossier(dossier_id)["execution_note"]
    assert "徐光启" in note
    # P4：档位/枚举不对玩家裸露
    for banned in ("strong", "weak", "degraded", "failed", "transformed", "fulfilled"):
        assert banned not in note


def test_adapter_replay_is_idempotent_on_joint_liability_rows(game):
    db, state, content = game
    dossier_id = _executing_dossier(db, state)
    _close_via_adapter(db, state, content, dossier_id, "failed", note="初结")
    first = _cost_events(db, dossier_id)
    first_edges = [
        e for e in db.get_relation_edge_events(event_kind="连坐")
        if e["origin"].startswith(f"dossier:{dossier_id}:")
    ]
    assert first  # 确有连坐落账

    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing' WHERE id=?", (dossier_id,),
    )
    db.conn.commit()
    _close_via_adapter(db, state, content, dossier_id, "failed", note="重结")

    assert _cost_events(db, dossier_id) == first
    second_edges = [
        e for e in db.get_relation_edge_events(event_kind="连坐")
        if e["origin"].startswith(f"dossier:{dossier_id}:")
    ]
    assert second_edges == first_edges


def test_engine_auto_failed_materialize_writes_zero_joint_liability(game):
    """顺颁物化引擎自判 failed（拨帑不足额）→ 零连坐行。"""
    db, state, _content = game
    state.metrics["国库"] = 0
    db.conn.execute("UPDATE metrics SET value=0 WHERE key='国库'")
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text="拨银十两押解赴陕",
        target_kind="region",
        target_id="shaanxi",
        payload={
            "account": "国库", "amount": 10,
            "execution_surface": "in_transit",
        },
        participants=_roster(),
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")

    dossier = db.get_decree_dossier(dossier_id)
    assert dossier["execution_outcome"] == "failed"
    assert _cost_events(db, dossier_id) == []
    assert db.get_relation_edge_events(event_kind="连坐") == []


def test_dead_liable_party_skips_satisfaction_but_enters_note(game, caplog):
    db, state, content = game
    dossier_id = _executing_dossier(db, state)
    db.conn.execute("UPDATE characters SET status='dead' WHERE name='倪元璐'")
    db.conn.commit()
    before_donglin = _sat(db, "东林")
    before_xixue = _sat(db, "西学")

    _close_via_adapter(db, state, content, dossier_id, "failed", note="主事已故仍须叙明")

    assert _sat(db, "东林") == before_donglin
    assert not any(
        row["target_id"] == "东林" for row in _sat_events(db, dossier_id)
    )
    # 委派人在世，failed→次责 weak 仍落
    assert _sat(db, "西学") == max(0, before_xixue - 4)
    edges = {
        e["target"] for e in db.get_relation_edge_events(event_kind="连坐")
        if e["origin"].startswith(f"dossier:{dossier_id}:")
    }
    assert "倪元璐" not in edges
    assert "徐光启" in edges
    note = db.get_decree_dossier(dossier_id)["execution_note"]
    assert "倪元璐" in note
    assert "跳过已故" in caplog.text


def test_explicit_affected_parties_must_pass_full_key_validation(game):
    db, state, content = game
    dossier_id = _executing_dossier(db, state)
    faction_names = {
        str(row["name"]) for row in db.conn.execute("SELECT name FROM factions")
    }
    class_names = {
        str(row["name"])
        for row in db.conn.execute("SELECT DISTINCT name FROM classes")
    }

    # missing intensity → reject, zero writes
    result = _close_via_adapter(
        db, state, content, dossier_id, "failed", note="缺键",
        affected_parties=[{
            "kind": "faction", "key": "东林", "direction": "negative",
        }],
    )
    assert result["dossier_executions"][0]["rejected"] is True
    assert db.get_decree_dossier(dossier_id)["status"] == "executing"
    assert _cost_events(db, dossier_id) == []

    # 全键合法但声明 roster 推不出的派系 → accept-and-ignore（不驱动机械额度）
    outsider = "阉党"
    assert outsider in faction_names
    assert outsider not in {"东林", "西学", "皇党"}  # roster 推不出
    valid = [{
        "kind": "faction", "key": outsider,
        "direction": "negative", "intensity": "strong",
    }]
    validate_affected_parties(valid, faction_names=faction_names, class_names=class_names)
    before_outsider = _sat(db, outsider)
    result = _close_via_adapter(
        db, state, content, dossier_id, "failed", note="全键合法",
        affected_parties=valid,
    )
    assert result["dossier_executions"] == [{"dossier_id": dossier_id, "outcome": "failed"}]
    assert _sat(db, outsider) == before_outsider
    assert not any(row["target_id"] == outsider for row in _sat_events(db, dossier_id))
    # roster 映射仍落主办派系
    assert any(row["target_id"] == "东林" for row in _sat_events(db, dossier_id))


def test_assistant_row_delegator_gets_secondary_assistant_zero_mechanical(game):
    """ADR 0053 核心例：大臣遣学生为协办办砸→全权者次责；协办本人零机械。"""
    db, state, content = game
    roster = [
        {"character_id": "倪元璐", "tier": "主办", "role": "清丈"},
        {
            "character_id": "黄道周", "tier": "协办", "role": "门生听调",
            "delegator_id": "徐光启",
        },
        {"character_id": "徐光启", "tier": "协办", "role": "坐镇"},
        {"character_id": "王承恩", "tier": "知情", "role": "备悉"},
    ]
    dossier_id = _executing_dossier(db, state, roster=roster)

    parties = db.list_execution_liability_parties(dossier_id)
    by_id = {p["character_id"]: p["responsibility"] for p in parties}
    assert by_id == {"倪元璐": "primary", "徐光启": "secondary"}
    assert "黄道周" not in by_id
    assert "王承恩" not in by_id

    before_donglin = _sat(db, "东林")
    before_xixue = _sat(db, "西学")
    _close_via_adapter(
        db, state, content, dossier_id, "failed", note="所遣协办办砸",
    )

    # 主办主责 strong；协办行委派人次责 weak；协办黄道周零机械
    assert _sat(db, "东林") == max(0, before_donglin - 8)
    assert _sat(db, "西学") == max(0, before_xixue - 4)
    sat = {
        (row["target_kind"], row["target_id"], row["delta"])
        for row in _sat_events(db, dossier_id)
    }
    assert sat == {("faction", "东林", -8), ("faction", "西学", -4)}

    edges = {
        e["target"] for e in db.get_relation_edge_events(event_kind="连坐")
        if e["origin"].startswith(f"dossier:{dossier_id}:")
    }
    assert edges == {"倪元璐", "徐光启"}
    assert "黄道周" not in edges

    note = db.get_decree_dossier(dossier_id)["execution_note"]
    assert "徐光启（委派）" in note
    assert "黄道周（" not in note


def test_dual_role_lead_and_delegator_primary_wins(game):
    """合法「主办兼他人委派人」先定档后去重：primary 胜 secondary。"""
    db, state, content = game
    roster = [
        {
            "character_id": "倪元璐", "tier": "主办", "role": "清丈",
            "delegator_id": "徐光启",
        },
        {"character_id": "徐光启", "tier": "主办", "role": "总理"},
    ]
    dossier_id = _executing_dossier(db, state, roster=roster)

    # 读端：一人一档，徐光启只返回 primary
    parties = db.list_execution_liability_parties(dossier_id)
    by_id = {p["character_id"]: p["responsibility"] for p in parties}
    assert by_id == {"倪元璐": "primary", "徐光启": "primary"}
    assert sum(1 for p in parties if p["character_id"] == "徐光启") == 1

    before_donglin = _sat(db, "东林")
    before_xixue = _sat(db, "西学")
    _close_via_adapter(db, state, content, dossier_id, "failed", note="双角色主责")

    # 写路：两人均 primary/strong（-8），徐不得被锁成次责 weak/-4
    assert _sat(db, "东林") == max(0, before_donglin - 8)
    assert _sat(db, "西学") == max(0, before_xixue - 8)
    sat = {
        (row["target_kind"], row["target_id"], row["delta"])
        for row in _sat_events(db, dossier_id)
    }
    assert sat == {("faction", "东林", -8), ("faction", "西学", -8)}

    edges = {
        e["target"] for e in db.get_relation_edge_events(event_kind="连坐")
        if e["origin"].startswith(f"dossier:{dossier_id}:")
    }
    assert edges == {"倪元璐", "徐光启"}

    note = db.get_decree_dossier(dossier_id)["execution_note"]
    assert "徐光启（主办）" in note
    assert "徐光启（委派）" not in note


def test_liability_query_excludes_knowers_but_keeps_delegator_fk(game):
    db, state, _content = game
    # 写界通常禁「委派人=知情」；cmr R3 读端仍按 delegator_id 外键上溯，
    # 即便该人在名单里仅以知情档出现也背锅，且查询结果不带知情档位行。
    dossier_id = _executing_dossier(db, state, roster=[
        {"character_id": "倪元璐", "tier": "主办", "role": "清丈"},
        {"character_id": "王承恩", "tier": "知情", "role": "备悉"},
        {"character_id": "黄道周", "tier": "协办", "role": "核账"},
    ])
    injected = [
        {
            "character_id": "倪元璐", "tier": "主办", "role": "清丈",
            "delegator_id": "王承恩",
        },
        {"character_id": "王承恩", "tier": "知情", "role": "备悉", "delegator_id": None},
        {"character_id": "黄道周", "tier": "协办", "role": "核账", "delegator_id": None},
    ]
    db.conn.execute(
        "UPDATE decree_dossiers SET participant_roster=? WHERE id=?",
        (json.dumps(injected, ensure_ascii=False), dossier_id),
    )
    db.conn.commit()

    parties = db.list_execution_liability_parties(dossier_id)
    ids = [p["character_id"] for p in parties]
    roles = {p["character_id"]: p["responsibility"] for p in parties}
    assert "倪元璐" in ids
    assert roles["倪元璐"] == "primary"
    assert "王承恩" in ids
    assert roles["王承恩"] == "secondary"
    assert "黄道周" not in ids
    assert all(p.get("tier") != "知情" for p in parties)


def test_living_offstage_delegator_still_charged(game):
    db, state, content = game
    dossier_id = _executing_dossier(db, state)
    db.set_character_status(state, "徐光启", "offstage", reason="致仕在籍")
    before = _sat(db, "西学")

    _close_via_adapter(db, state, content, dossier_id, "failed", note="致仕仍追")

    assert _sat(db, "西学") == max(0, before - 4)
    targets = {
        e["target"] for e in db.get_relation_edge_events(event_kind="连坐")
        if e["origin"].startswith(f"dossier:{dossier_id}:")
    }
    assert "徐光启" in targets


def test_execution_note_merge_interface_and_restore(game):
    db, state, content = game
    dossier_id = _executing_dossier(db, state)
    _close_via_adapter(db, state, content, dossier_id, "degraded", note="初注走样")
    before = db.get_decree_dossier(dossier_id)["execution_note"]
    assert "初注走样" in before

    merged = db.merge_execution_note(dossier_id, "对账差额：应拨十两实拨三两")
    row = db.get_decree_dossier(dossier_id)
    assert "对账差额：应拨十两实拨三两" in row["execution_note"]
    assert before in row["execution_note"]
    assert merged == row["execution_note"]
    assert row["execution_outcome"] == "degraded"

    costs = _cost_events(db, dossier_id)
    path = db.path
    db.close()
    from ming_sim.db import GameDB
    restored = GameDB(path, content)
    try:
        again = restored.get_decree_dossier(dossier_id)
        assert again["execution_outcome"] == "degraded"
        assert again["execution_note"] == merged
        assert _cost_events(restored, dossier_id) == costs
    finally:
        restored.close()


def test_direct_record_dossier_execution_does_not_trigger_joint_liability(game):
    """挂载点=适配器；record_dossier_execution 本身不扫/不扣连坐。"""
    db, state, _content = game
    dossier_id = _executing_dossier(db, state)
    db.record_dossier_execution(
        dossier_id, "failed", "直写终值", state.turn, close=True,
    )
    assert _cost_events(db, dossier_id) == []
    assert db.get_relation_edge_events(event_kind="连坐") == []
