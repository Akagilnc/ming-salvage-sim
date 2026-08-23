"""#651（[#477 S4]）暗渠摊派：缺口悬置→摊派变形两本账→暴露→处置三选。

canonical＝ADR 0089（唯一新拍契约：财政缺口悬置→摊派变形的触发与落账，
触发因子并入 0072 判官口径）；两本账/分叉读端骑 #622 轨；入池骑 #649 S2
转移原语（reason='摊派' 与明渠加派合流同一本流民账）。

测试预算 ≤3：
① AC1 触发契约确定性：欠饷月数 ≥N 才出触发因子、边界 mutation 钉死、未悬置绝不触发
② AC2+AC3+AC5 两本账落库 tracer：奏报面 vs 实况账不同 origin；入池与明渠同账合流；
   一案一活跃暗账幂等；restore 后两本账＋案件状态只读 DB 无损
③ AC4 暴露三通道读端＋处置三选各代价当回合落账（禁→缺口重新可见；默许→池可续涨；
   查办→经手人处置事件）

戒条（票庭判词 run 01a02d3f-c99d-7d01-a8cb-0b11a6b92b9e）遵守：
(a) 奏报侧「已筹措」由承办 LLM 从特征化输入长出——测内以 record_dossier_progress
    公开写轨代承办陈词，实现不硬编码模板句；
(b) N 月以命名常量 COVERT_LEVY_SUSPENDED_MONTHS 钉死，①内配边界 mutation；
(c) 查办代价走 character_status_changes 单核（issues._apply_person_changes 同款）
    当回合落库。
"""

from __future__ import annotations

import pytest

from ming_sim.covert_levy import (
    COVERT_LEVY_SUSPENDED_MONTHS,
    book_covert_levy_case,
    build_covert_levy_trigger_factor,
    get_covert_levy_case,
    read_shortfall_suspension_facts,
)
from ming_sim.db import GameDB
from ming_sim.due_review import build_due_review_input
from ming_sim.flows import army_needed
from ming_sim.issues import apply_score_extraction
from tests.test_deformation_dual_rail_622 import _executing_policy, _world_fingerprint

# content/classes.json 冻结 seed 字面（独立 oracle，非实现推导）
FARMER_SHAANXI = 6000000
DISPLACED_SHAANXI = 150000

ARMY_ID = "shaanxi_army"          # content/armies.json 冻结 seed：42000×1.4 → needed=6
REGION_ID = "shaanxi"


# ── shared helpers ────────────────────────────────────────────────────


def _zero_all_arrears(db) -> None:
    db.conn.execute("UPDATE armies SET arrears=0")
    db.conn.commit()


def _set_arrears(db, army_id: str, value: float) -> None:
    db.conn.execute("UPDATE armies SET arrears=? WHERE id=?", (value, army_id))
    db.conn.commit()


def _needed(db, army_id: str) -> int:
    row = db.conn.execute("SELECT * FROM armies WHERE id=?", (army_id,)).fetchone()
    return army_needed(row)


def _pop(db, name: str, region_id: str) -> int:
    row = db.conn.execute(
        "SELECT population FROM classes WHERE name=? AND region_id=?",
        (name, region_id),
    ).fetchone()
    return int(row[0]) if row else 0


def _active_character(db) -> str:
    return db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()[0]


def _prime_eligible_army(db) -> int:
    """零化全军欠饷后把陕西边军欠饷顶到恰好 N 月（确定性触发底料）。"""
    _zero_all_arrears(db)
    needed = _needed(db, ARMY_ID)
    _set_arrears(db, ARMY_ID, needed * COVERT_LEVY_SUSPENDED_MONTHS)
    return needed


def _review_todo() -> dict:
    """合成 staged todo（缺 commitment 元数据按既有空形降级，_issue_meta 已容忍）。"""
    return {
        "id": 0,
        "commitment_ref": 0,
        "stage_idx": 0,
        "due_turn": 1,
        "criterion_text": "军饷如额筹措",
        "origin_context": "",
        "entry_kind": "staged",
        "status": "pending",
        "created_turn": 0,
    }


# ── ① AC1 触发契约确定性 ──────────────────────────────────────────────


def test_ac1_shortfall_suspension_trigger_gate_boundary(game):
    """欠饷月数 floor(arrears/needed)≥N 才出因子；N-1 月边界不出；判官输入面键随之有无。"""
    db, state, _content = game
    _zero_all_arrears(db)

    # 未悬置：因子不出现，判官输入面无键（不满足绝不触发）
    assert build_covert_levy_trigger_factor(db) is None
    review_input = build_due_review_input(db, _review_todo())
    assert "covert_levy_trigger" not in review_input

    # 边界 mutation（戒条 b）：恰好 N-1 月欠饷 → 不出因子
    needed = _needed(db, ARMY_ID)
    assert needed > 0
    _set_arrears(db, ARMY_ID, needed * COVERT_LEVY_SUSPENDED_MONTHS - 1)
    assert build_covert_levy_trigger_factor(db) is None
    assert "covert_levy_trigger" not in build_due_review_input(db, _review_todo())

    # 恰好 N 月 → 因子出现，事实底料可断言（army/月数/欠饷额）
    _set_arrears(db, ARMY_ID, needed * COVERT_LEVY_SUSPENDED_MONTHS)
    facts = read_shortfall_suspension_facts(db)
    hit = next(f for f in facts if f["army_id"] == ARMY_ID)
    assert hit["months_in_arrears"] >= COVERT_LEVY_SUSPENDED_MONTHS
    factor = build_covert_levy_trigger_factor(db)
    assert factor is not None
    assert any(f["army_id"] == ARMY_ID for f in factor["suspended_armies"])
    assert factor["suspended_months_gate"] == COVERT_LEVY_SUSPENDED_MONTHS

    # 无案卷的合成 todo 不得被 A 军污染；显式相关财政 scope 才取得 A 军事实。
    review_input = build_due_review_input(db, _review_todo())
    assert "covert_levy_trigger" not in review_input
    scoped = build_covert_levy_trigger_factor(db, scope_text="陕西边军军饷筹措")
    assert scoped and scoped["suspended_armies"][0]["army_id"] == ARMY_ID
    assert build_covert_levy_trigger_factor(db, scope_text="京营军饷筹措") is None


# ── ② AC2+AC3+AC5 两本账 tracer ───────────────────────────────────────


def test_ac2_ac3_dual_ledger_booking_merges_pool_and_restores(game, tmp_path):
    """暗账落库：实况账＝摊派转移入池（与明渠加派同账合流）＋旨外国库流水；
    奏报面只留承办陈词；一案一活跃暗账；restore 后两本账＋案件状态无损。"""
    db, state, content = game
    needed = _prime_eligible_army(db)
    dossier_id = _executing_policy(db, state, token="covert-651")
    db.conn.execute("UPDATE decree_dossiers SET decree_text=? WHERE id=?", ("陕西边军军饷筹措", dossier_id))
    db.conn.commit()
    handler = _active_character(db)

    # 戒条(a)：奏报侧「已筹措」由承办 LLM 长出——此处经公开奏报写轨代承办陈词
    db.record_dossier_progress(
        int(dossier_id), state.turn, "已办", "军饷已多方筹措、如数解到",
        is_terminal=False, commit=True,
    )
    before_fp = _world_fingerprint(db)

    booked = book_covert_levy_case(
        db, state,
        dossier_id=int(dossier_id), army_id=ARMY_ID, region_id=REGION_ID,
        handler_name=handler,
        displaced_amount=3000, squeezed_silver=5,
    )
    assert booked.get("rejected") is False, booked
    case_id = int(booked["case_id"])

    # 实况账①：入池走 S2 转移原语、与明渠合流同一本流民账（AC3）
    applied = apply_score_extraction(db, state, {
        "population_transfers": [{
            "origin_ref": f"dossier:{int(dossier_id)}",
            "source": f"农民@{REGION_ID}", "target": f"流民@{REGION_ID}",
            "amount": 7000, "reason": "加派",
        }],
    }, content, None)
    assert not applied["population_transfers_rejections"]
    assert _pop(db, "农民", REGION_ID) == FARMER_SHAANXI - 3000 - 7000
    assert _pop(db, "流民", REGION_ID) == DISPLACED_SHAANXI + 3000 + 7000

    # 实况账②：旨外国库流水同 origin 落库（骑 #622 轨）→ 分叉可机械读出（AC2）
    moves = db.list_economy_moves_for_dossier(int(dossier_id))
    assert len(moves) == 1 and moves[0]["beyond_intent"] is True
    fork = db.read_dossier_fork_state(int(dossier_id))
    assert fork["fork"] is True and fork["beyond_intent"] is True

    # 奏报面只留承办陈词；执行格未裁（P4：暴露前皇帝只见奏报口径）
    progress = db.list_dossier_progress(int(dossier_id))
    assert progress and all("暗渠" not in r["memorial_text"] for r in progress)
    assert db.get_decree_dossier(int(dossier_id))["execution_outcome"] == ""

    # 案件行（处置状态载体）：active、全字段可溯
    case = get_covert_levy_case(db, case_id)
    assert case["status"] == "active"
    assert case["dossier_id"] == int(dossier_id) and case["army_id"] == ARMY_ID
    assert case["region_id"] == REGION_ID and case["handler_name"] == handler
    assert case["displaced_amount"] == 3000 and case["squeezed_silver"] == 5

    # 一案一活跃暗账：重复落账响亮拒绝、世界不变
    dup = book_covert_levy_case(
        db, state,
        dossier_id=int(dossier_id), army_id=ARMY_ID, region_id=REGION_ID,
        handler_name=handler,
        displaced_amount=1, squeezed_silver=1,
    )
    assert dup.get("rejected") is True
    assert _world_fingerprint(db) != before_fp  # 首笔已入 apply
    fp_after = _world_fingerprint(db)

    # AC5：restore 接续——两本账与案件状态只读 DB 无损
    backup = tmp_path / "restore-651.db"
    db.backup_to(str(backup))
    restored = GameDB(str(backup), content=content)
    try:
        assert _pop(restored, "农民", REGION_ID) == FARMER_SHAANXI - 10000
        assert _pop(restored, "流民", REGION_ID) == DISPLACED_SHAANXI + 10000
        r_moves = restored.list_economy_moves_for_dossier(int(dossier_id))
        assert r_moves and r_moves[0]["beyond_intent"] is True
        r_case = get_covert_levy_case(restored, case_id)
        assert r_case["status"] == "active"
        assert r_case["handler_name"] == handler
    finally:
        restored.close()
    assert _world_fingerprint(db) == fp_after


# ── ③ AC4 暴露读端＋处置三选 ──────────────────────────────────────────


def _book(db, state, token: str, handler: str, *, displaced=100, silver=1):
    dossier_id = _executing_policy(db, state, token=token)
    db.conn.execute("UPDATE decree_dossiers SET decree_text=? WHERE id=?", (f"陕西边军军饷筹措·{token}", dossier_id))
    db.conn.commit()
    out = book_covert_levy_case(
        db, state,
        dossier_id=int(dossier_id), army_id=ARMY_ID, region_id=REGION_ID,
        handler_name=handler,
        displaced_amount=displaced, squeezed_silver=silver,
    )
    assert out.get("rejected") is False, out
    return int(dossier_id), int(out["case_id"])


def _memorialize(db, state, dossier_id: int) -> None:
    db.record_dossier_progress(
        int(dossier_id), state.turn, "已办", "军饷已多方筹措、如数解到",
        is_terminal=False, commit=True,
    )


def test_ac4_exposure_channels_then_three_dispositions_book_costs(game):
    """暴露＝分叉事实可机械读出（三通道同源 fork 谓词，通道留痕）；处置三选
    各代价当回合落账：禁→缺口重新可见＋该军不得再开暗账；默许→不结案、池可续涨；
    查办→经手人处置事件＋结怨边；未暴露不可处置、未知处置响亮拒绝。"""
    from ming_sim.covert_levy import (
        apply_covert_levy_disposition,
        refresh_covert_levy_exposures,
    )

    db, state, content = game
    needed = _prime_eligible_army(db)
    handler_a = _active_character(db)
    handler_d = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1 OFFSET 1"
    ).fetchone()[0]

    # 四案同军：A 素案（先无奏报）；B 素奏报；C 检举；D 稽核链
    d_a, case_a = _book(db, state, "cl-a", handler_a)
    d_b, case_b = _book(db, state, "cl-b", handler_a)
    d_c, case_c = _book(db, state, "cl-c", handler_a)
    d_d, case_d = _book(db, state, "cl-d", handler_d, displaced=200, silver=2)
    _memorialize(db, state, d_b)
    _memorialize(db, state, d_c)
    _memorialize(db, state, d_d)
    # C：政敌检举底料（#627 同表，去重键=检举人×案卷×真伪类）
    db.conn.execute(
        """INSERT INTO faction_denunciations
           (turn, accuser_name, accuser_faction, subject_name, subject_faction,
            target_dossier_id, origin, payload_json, memorial_text)
           VALUES (?, '温体仁', '阉党', '承办官', '朝堂', ?, '检举', '{}',
                   '臣劾承办官假筹措、实摊派')""",
        (state.turn, d_c),
    )
    # D：稽核链（#622 同款关联写端）
    auditor = _executing_policy(db, state, token="cl-auditor")
    db.add_dossier_links(int(auditor), [{
        "target_dossier_id": d_d, "relation_type": "稽核", "note": "密查该路军饷",
    }])
    db.conn.commit()

    # 未暴露：无奏报 → 分叉不成立 → 案件保持 active；且未暴露不可处置
    exposed = refresh_covert_levy_exposures(db, state)
    assert get_covert_levy_case(db, case_a)["status"] == "active"
    early = apply_covert_levy_disposition(db, state, case_a, "禁摊派")
    assert early.get("rejected") is True and "未暴露" in early["reason"]

    # 素案随后有奏报和真实检举，二者俱全才可暴露；无信号的 B 仍不得伪称民变。
    _memorialize(db, state, d_a)
    db.conn.execute(
        """INSERT INTO faction_denunciations
           (turn, accuser_name, accuser_faction, subject_name, subject_faction,
            target_dossier_id, origin, payload_json, memorial_text)
           VALUES (?, '温体仁', '阉党', '承办官', '朝堂', ?, '检举', '{}', '臣劾暗中摊派')""",
        (state.turn, d_a),
    )
    db.conn.commit()
    late = refresh_covert_levy_exposures(db, state)
    assert [int(e["case_id"]) for e in late] == [case_a]
    assert late[0]["exposed_channel"] == "政敌检举"
    assert get_covert_levy_case(db, case_b)["status"] == "active"

    # 暴露：真实检举与稽核分别命中、通道留痕。
    exposed = {int(e["case_id"]): e for e in exposed}
    assert set(exposed) == {case_c, case_d}
    assert exposed[case_c]["exposed_channel"] == "政敌检举"
    assert exposed[case_d]["exposed_channel"] == "稽核"
    assert all(int(e["exposed_turn"]) == int(state.turn) for e in exposed.values())

    displaced_mid = _pop(db, "流民", REGION_ID)

    # 默许（C）：不结案、处置留档；池继续涨——新案 E 可再开暗账
    out_c = apply_covert_levy_disposition(db, state, case_c, "默许")
    assert out_c.get("rejected") is False, out_c
    c_after = get_covert_levy_case(db, case_c)
    assert c_after["status"] == "exposed" and c_after["disposition"] == "默许"
    _, case_e = _book(db, state, "cl-e", handler_a, displaced=300, silver=1)
    assert _pop(db, "流民", REGION_ID) == displaced_mid + 300

    # 禁摊派（A）：缺口重新顶回皇帝案头——悬置军仍在触发因子里；该军禁开新暗账
    out_a = apply_covert_levy_disposition(db, state, case_a, "禁摊派")
    assert out_a.get("rejected") is False, out_a
    a_after = get_covert_levy_case(db, case_a)
    assert a_after["status"] == "disposed" and a_after["disposition"] == "禁摊派"
    factor = build_covert_levy_trigger_factor(db)
    assert any(f["army_id"] == ARMY_ID for f in factor["suspended_armies"])
    d_f = _executing_policy(db, state, token="cl-f")
    db.conn.execute("UPDATE decree_dossiers SET decree_text='陕西边军军饷筹措' WHERE id=?", (d_f,))
    db.conn.commit()
    banned = book_covert_levy_case(
        db, state,
        dossier_id=int(d_f), army_id=ARMY_ID, region_id=REGION_ID,
        handler_name=handler_a, displaced_amount=1, squeezed_silver=1,
    )
    assert banned.get("rejected") is True and "禁摊派" in banned["reason"]
    cost_kinds_a = [
        r["cost_kind"] for r in db.conn.execute(
            "SELECT cost_kind FROM decree_cost_events WHERE dossier_id=?", (d_a,)
        ).fetchall()
    ]
    assert "禁摊派" in cost_kinds_a

    # 查办（D）：经手人处置事件当回合落库（戒条 c）＋结怨边＋代价留痕
    out_d = apply_covert_levy_disposition(db, state, case_d, "查办")
    assert out_d.get("rejected") is False, out_d
    d_row = db.conn.execute(
        "SELECT status FROM characters WHERE name=?", (handler_d,)
    ).fetchone()
    assert str(d_row["status"]) == "imprisoned"
    edge = db.conn.execute(
        """SELECT 1 FROM relation_edge_events
           WHERE source='皇帝' AND target=? AND event_kind='结怨'
             AND origin LIKE ?""",
        (handler_d, f"dossier:{d_d}%"),
    ).fetchone()
    assert edge is not None
    cost_kinds_d = [
        r["cost_kind"] for r in db.conn.execute(
            "SELECT cost_kind FROM decree_cost_events WHERE dossier_id=?", (d_d,)
        ).fetchall()
    ]
    assert "查办" in cost_kinds_d

    # 未知处置响亮拒绝（ADR 0005 fail-loud）
    with pytest.raises(ValueError):
        apply_covert_levy_disposition(db, state, case_e, "赦免")
