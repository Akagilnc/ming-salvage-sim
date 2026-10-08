"""#1504 B 包：密令机械实进度 + 到期缺口对账 + 拆 secret_order_closes 真源。

Seams:
- dossier_actual_progress 实况容器（origin 纪律；≠ dossier_progress_json）
- apply_monthly_covert_actual_progress + settle_due_secret_orders（settle 同 atomic）
- 正反例：已交付→done、缺口→failed；表报背离不翻实账
- secret_order_closes 不再落库结案
- auto_submit 不再翻 pending_review；到期不写玩家模板
"""

from __future__ import annotations

import json

import pytest

from ming_sim.covert_progress import (
    CONTRACT_KEY,
    FACT_LANES_KEY,
    INVESTIGATION_TIPS_KEY,
    INVESTIGATION_ACTS_KEY,
    CovertContractError,
    apply_investigation_spoliation,
    build_covert_task_contract,
    decide_secret_order_settlement,
    investigation_clue_records,
    live_investigation_fact_keys,
    read_covert_task_contract,
    seed_guilt_counts_as_debt,
    apply_monthly_covert_actual_progress,
    investigation_lane_actual_units,
    settle_due_secret_orders,
)
from ming_sim.applier import Provenance
from ming_sim.month_chain import build_secret_orders_supply_feed
from ming_sim.exceptions import SettlementAbort
from ming_sim.issues import apply_score_extraction
from tests.conftest import offline_empty_audience_translate, stub_audience_translate, stub_scene_agent

def _task(*, kind, axes, unit, target, direction=1, investigation_target="", effect_sign=None):
    if investigation_target:
        sign = 1 if effect_sign is None else int(effect_sign)
        return {
            "kind": kind,
            "axes": list(axes),
            "direction": int(direction),
            "investigation_target": investigation_target,
            "delivery": {
                "target_units": float(target),
                "effect_sign": sign,
                "investigation_target": investigation_target,
            },
        }
    identity = {
        "万两": {"purpose": "其它", "category": "密令差务", "account": "内库", "effect_sign": -1},
        "人犯": {"person_action": "处置", "effect_sign": 1},
        "万亩": {"region": "henan", "field": "registered_land", "target": "421", "effect_sign": 1},
    }[unit]
    if effect_sign is not None:
        identity = {**identity, "effect_sign": int(effect_sign)}
    return {
        "kind": kind,
        "axes": list(axes),
        "direction": int(direction),
        "delivery": {"unit": unit, "target_units": float(target), **identity},
    }

def _issue(db, state, name, title, content, *, months, target, kind="查案",
           axes=None, unit="万两", tags=None, investigation_target=""):
    return db.create_secret_order(
        state, name, title, content, tags if tags is not None else [],
        deadline_months=months,
        covert_task=_task(
            kind=kind, axes=axes or ["实务事功"], unit=unit, target=target,
            investigation_target=investigation_target,
        ),
    )

def _minister(db):
    row = db.conn.execute(
        "SELECT name FROM characters "
        "WHERE status='active' AND power_id='ming' "
        "AND office_type NOT IN ('后宫','宗藩','未仕') "
        "ORDER BY name LIMIT 1"
    ).fetchone()
    assert row is not None
    return row["name"]

def _structured_guilt(crime="侵冒"):
    return json.dumps({"crime": crime, "severity": "中"}, ensure_ascii=False)

def _set_axes(db, name, *, loyalty, identity, faction=None, seed_guilt=""):
    if faction is None:
        faction = db.conn.execute(
            "SELECT faction FROM characters WHERE name=?", (name,)
        ).fetchone()["faction"]
    db.conn.execute(
        "UPDATE characters SET loyalty=?, identity=?, seed_guilt=? WHERE name=?",
        (int(loyalty), int(identity), seed_guilt, name),
    )
    if faction:
        db.conn.execute(
            "UPDATE factions SET satisfaction=? WHERE name=?",
            (60, faction),
        )
    db.conn.commit()

def _co_locate(db, *names, place="beizhili"):
    """把相关人物放在同一处（#1896「办案人得身在当地」的前置）。

    查案逐证核算要求承办人身在目标当地才投得进力，故断言"深挖即查获"的
    用例须先把人放到一地；这不是给引擎放水，是把用例的前提摆明。
    """
    for name in names:
        db.conn.execute(
            "UPDATE characters SET location=?, transit_to='' WHERE name=?",
            (place, str(name)),
        )
    db.conn.commit()

def _next_month(db, state):
    """推进一个月（落库 state），供逐月核算用。"""
    state.turn += 1
    db.save_state(state)
    return state

def _run_supply_4a(db, state, selections):
    """经真实月链接缝跑步骤 4a，返回该月链状态。

    查案落账的唯一生产入口在月链里，故端到端断言都走这里，不直接打引擎内层。
    4a 产物按 #1846 的"已存产物接续"相位预置（``secret_orders_supply_product``），
    不真调模型。
    """
    import ming_sim.month_chain as month_chain

    turn = int(state.turn)
    chain: dict = {
        "secret_orders_supply_product": {
            "dossier_progress_reports": [
                {
                    "dossier_id": int(row["dossier_id"]),
                    "progress_band": "持平",
                    "memorial_text": "据实以奏",
                }
                for row in db.list_monthly_dossier_progress_nudges(turn)
            ],
            "covert_exec_selections": list(selections),
        },
    }
    try:
        month_chain._step_4a_secret_order_supply(
            db, state, chain,
            turn=turn, decree_text="", source=Provenance.secret_order, llm_config=None,
        )
    except SettlementAbort:
        pass  # 停续：回读已持久化的月链相位（call_failure / invalid 标记）
    else:
        return chain
    return month_chain._load_chain(db, turn)

def _declare_tip(db, state, oid, source):
    """经真实 4a 入口声明一次真实通风报信（知情判定的声明真源）。"""
    _next_month(db, state)
    return _run_supply_4a(db, state, [{
        "order_id": oid, "effort": 0.0, "tip_off": {"source": source},
    }])

def _originate_work(db, state, content, dossier_id, *, delta=-1):
    apply_score_extraction(
        db, state,
        {
            "economy_moves": [{
                "account": "内库",
                "delta": int(delta),
                "category": "密令差务",
                "reason": "差务实办开支",
                "origin_ref": f"dossier:{int(dossier_id)}",
            }],
        },
        content=content,
    )

def _catch_names(db, exclude, n=3):
    rows = db.conn.execute(
        "SELECT name FROM characters "
        "WHERE status='active' AND power_id='ming' "
        "AND office_type NOT IN ('后宫','宗藩','未仕') AND name!=? "
        "ORDER BY name LIMIT ?",
        (exclude, int(n)),
    ).fetchall()
    names = [str(r["name"]) for r in rows]
    assert len(names) >= int(n)
    return names

def _originate_catches(db, state, content, dossier_id, names):
    apply_score_extraction(
        db, state,
        {
            "人物变更": [
                {
                    "name": name,
                    "动作": "处置",
                    "status": "imprisoned",
                    "reason": "密令缉获",
                    "origin_ref": f"dossier:{int(dossier_id)}",
                }
                for name in names
            ],
        },
        content=content,
    )


def test_confirm_persists_task_specific_contract_absent_before(game):
    db, state, _ = game
    name = _minister(db)
    before = db.conn.execute("SELECT COUNT(*) AS n FROM secret_orders").fetchone()["n"]
    assert before == 0
    oid = _issue(
        db, state, name, "密查辽饷", "不得声张",
        months=3, target=3, kind="补发饷银", axes=["既得利益"], unit="万两",
        tags=["辽饷", "兵部", "密查"],
    )
    contract = read_covert_task_contract(db.get_dossier_for_secret_order(oid))
    assert contract is not None
    assert contract["kind"] == "补发饷银"
    assert contract["axes"] == ["既得利益"]
    assert contract["delivery"]["unit"] == "万两"
    assert contract["delivery"]["target_units"] == 3.0
    catch_id = _issue(
        db, state, name, "缉获私贩", "拿人犯",
        months=2, target=2, kind="缉获人犯", unit="人犯",
        tags=["密查"],
    )
    catch = read_covert_task_contract(db.get_dossier_for_secret_order(catch_id))
    assert catch["kind"] == "缉获人犯"
    assert catch["delivery"]["unit"] == "人犯"
    assert catch["delivery"]["target_units"] == 2.0

def test_supply_call_writes_identity_materials_into_its_own_tree(game, monkeypatch):
    """#1896 R1/F2：4a 生产入口自己把身份材料写进树——不是测试自己动手。

    走真实 ``run_secret_orders_supply``，只桩掉外部模型边界。抓 ``prepared``
    断言 materials_path 在模型将读的树上可读；列目录核身份事务边界与隔离。
    身份备料失败须传播并清理本树。不锁材料正文措辞/同源等值。
    """
    import json as _json

    import ming_sim.agents as agents_mod
    import ming_sim.month_chain as month_chain
    from pathlib import Path
    import ming_sim.materials as materials_mod
    from ming_sim.materials import list_materials, material_tools, read_material
    from ming_sim.models import LLMConfig

    db, state, _ = game
    name = _minister(db)
    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    _set_axes(db, name, loyalty=90, identity=30)
    _co_locate(db, name, target)
    oid = _issue(
        db, state, name, "查核", "查核", months=3, target=1,
        kind="查核", axes=["既得利益"], investigation_target=target,
    )
    # 下月才进在办密令（开案当月属 issuance-turn，会被在办清单滤掉）
    _next_month(db, state)

    # 两条真实事务分别只授予本人，显式排除另一个同场人物。
    issue_rows = db.conn.execute(
        "SELECT id,title FROM issues WHERE status='active' ORDER BY id LIMIT 2",
    ).fetchall()
    for row, who, other in zip(issue_rows, (name, target), (target, name)):
        db.conn.execute(
            "UPDATE issues SET participant_roster=? WHERE id=?",
            (_json.dumps([{"character_id": who, "tier": "主办"}]), row["id"]),
        )
        db.record_character_participation(
            state, [who], "case", row["title"], "本人的办案经历",
            source_id=f"issue:{row['id']}", excluded_names=[other],
        )
    db.conn.commit()
    captured = {}
    roots = []
    real_prepare = materials_mod.prepare_world_materials

    def prepare(*args, **kwargs):
        prepared = real_prepare(*args, **kwargs)
        roots.append(prepared.root)
        return prepared

    monkeypatch.setattr(materials_mod, "prepare_world_materials", prepare)

    def _fake_agent(llm_config, prepared=None):
        captured["root"] = getattr(prepared, "root", None)
        return object()

    def _fake_run_text(agent, prompt, tag, **_kwargs):
        # 此刻树还在（run_secret_orders_supply 收尾才释放），就地读路径集合
        captured["prompt"] = prompt
        feed = _json.loads(prompt)
        paths = {}
        tools = {tool.__name__: tool for tool in material_tools(captured["root"])}
        for entry in feed.get("active_secret_orders") or []:
            for side in ("investigator_identity_materials",
                         "investigation_target_identity_materials"):
                who = str((entry.get(side) or {}).get("name") or "")
                rel = str((entry.get(side) or {}).get("materials_path") or "")
                if who and rel:
                    # 路径可读即可；不锁正文措辞、不比同源等值。
                    assert read_material(captured["root"], rel) is not None
                    base = Path(rel).parent.as_posix()
                    listed = list_materials(captured["root"], base)
                    assert set(tools["list_materials"](base).splitlines()) == set(listed)
                    for path in listed:
                        assert tools["read_material"](path) is not None
                    paths[who] = {Path(path).relative_to(base).as_posix() for path in listed}
        captured["paths"] = paths
        return _json.dumps({"dossier_progress_reports": [], "covert_exec_selections": []})

    monkeypatch.setattr(agents_mod, "create_secret_order_supply_agent", _fake_agent)
    monkeypatch.setattr(agents_mod, "run_agent_text", _fake_run_text)

    cfg = LLMConfig(api_key="", base_url="http://unused", model="unused")
    month_chain.run_secret_orders_supply(db, state, cfg, {})

    assert captured["root"] is not None, "生产入口没有把备好的材料树交给 agent"
    feed = _json.loads(captured["prompt"])
    order = next(o for o in feed["active_secret_orders"] if int(o["id"]) == oid)
    for side, who in (
        ("investigator_identity_materials", name),
        ("investigation_target_identity_materials", target),
    ):
        rel = order[side]["materials_path"]
        assert "materials" not in order[side]
        assert rel
        visible = {int(row["id"]) for row in db.get_character_knowledge(state, who)["issues"]}
        paths = captured["paths"][who]
        assert {path for path in paths if path.startswith("事务/issue-")} == {
            f"事务/issue-{i}/当前情况.txt" for i in visible
        }
        assert any(path.endswith("/经历.txt") for path in paths)
        assert any(path.endswith("/公事档案.txt") for path in paths)
        assert not any(path.startswith("盘面/") for path in paths)
    assert f"事务/issue-{issue_rows[0]['id']}/当前情况.txt" in captured["paths"][name]
    assert f"事务/issue-{issue_rows[0]['id']}/当前情况.txt" not in captured["paths"][target]
    assert f"事务/issue-{issue_rows[1]['id']}/当前情况.txt" in captured["paths"][target]
    assert f"事务/issue-{issue_rows[1]['id']}/当前情况.txt" not in captured["paths"][name]
    assert not roots[-1].exists()

    # 在身份写手读取公事档案时注入失败，仍走真实 4a 生命周期。
    error = RuntimeError("identity archive unavailable")
    def broken_archive(*args, **kwargs):
        raise error
    monkeypatch.setattr(db, "list_referenceable_dossiers", broken_archive)
    with pytest.raises(RuntimeError) as failed:
        month_chain.run_secret_orders_supply(db, state, cfg, {})
    assert failed.value is error
    assert len(roots) == 2
    assert not roots[-1].exists()



def test_actual_progress_container_separate_from_reported_rail(game):
    db, state, _ = game
    name = _minister(db)
    oid = _issue(db, state, name, "密查国丈", "查周奎私通状", months=3, target=3)
    dossier = db.get_dossier_for_secret_order(oid)
    did = int(dossier["id"])

    db.record_dossier_actual_progress(
        did, state.turn, units=1.0, fidelity_state="忠实", floor_state="忠实",
        note="实况一笔",
    )
    # 奏报轨另写
    db.record_dossier_progress(
        did, state.turn, "在办", "臣称已有端绪", is_terminal=False,
    )

    actual = db.list_dossier_actual_progress(did)
    reported = db.list_dossier_progress(did)
    assert len(actual) == 1
    assert actual[0]["units"] == 1.0
    assert actual[0]["origin_ref"] == f"dossier:{did}"
    assert db.sum_dossier_actual_progress_units(did) == 1.0
    # 两轨分立
    assert reported[0]["progress_band"] == "在办"
    assert not reported[0]["is_terminal"]
    assert "dossier_progress_json" not in actual[0]
    # list_dossier_durable_effects 仍只 economy+fiscal；实进度走并列读口
    durable = db.list_dossier_durable_effects(did)
    assert all("account" in r or "key" in r or "delta" in r for r in durable) or durable == []
    assert db.list_dossier_actual_rail(did)  # 含 actual_progress 行

def test_settle_due_reads_actual_rail_only_report_does_not_flip_verdict(game):
    """窄接缝：settle_due_secret_orders 只读 actual rail；奏报灌满不翻 verdict。

    """
    db, state, _ = game
    name = _minister(db)
    _set_axes(db, name, loyalty=20, identity=80)
    oid = _issue(db, state, name, "空转密查", "查无实据之案", months=1, target=1)
    dossier = db.get_dossier_for_secret_order(oid)
    did = int(dossier["id"])
    # 只写奏报，不写实况
    db.record_dossier_progress(
        did, state.turn, "办成", "臣已查明全部", is_terminal=False,
    )
    # 推 due 到当月
    db.conn.execute(
        "UPDATE secret_orders SET due_turn=? WHERE id=?",
        (state.turn, oid),
    )
    db.conn.commit()

    out = settle_due_secret_orders(db, state, commit=True)
    row = next(r for r in out if r["order_id"] == oid)
    assert row["status"] == "failed"
    assert row["actual_units"] == 0.0
    closed = db.get_secret_order(oid)
    assert closed["status"] == "failed"


def test_monthly_actual_then_delivered_done(game):
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    oid = _issue(db, state, name, "三月密查", "限期三月查明", months=3, target=3)
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    for _ in range(3):
        state.turn += 1
        db.save_state(state)
        _originate_work(db, state, content, did)
        apply_monthly_covert_actual_progress(
            db, state,
            selections=[{"order_id": oid, "fidelity": "忠实"}],
            commit=True,
        )

    order = db.conn.execute(
        "SELECT due_turn, deadline_span FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()
    assert state.turn == int(order["due_turn"])

    out = settle_due_secret_orders(db, state, commit=True)
    row = next(r for r in out if r["order_id"] == oid)
    assert row["status"] == "done", row
    assert row["delivered"] is True
    assert db.get_secret_order(oid)["status"] == "done"
    dossier = db.get_dossier_for_secret_order(oid)
    assert dossier["status"] == "closed"
    assert dossier["execution_outcome"] == "fulfilled"

def test_gap_after_months_failed(game):
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=15, identity=85, seed_guilt="旧案")
    oid = _issue(db, state, name, "必败密查", "无人真办", months=2, target=2)
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    # 两月有 origin 实物，执行态反噬仍不产生实进度（跳过发令月）
    for _ in range(2):
        state.turn += 1
        db.save_state(state)
        _originate_work(db, state, content, did)
        apply_monthly_covert_actual_progress(
            db, state, selections=[{"order_id": oid, "fidelity": "反噬"}], commit=True,
        )
    assert db.sum_dossier_actual_progress_units(did) == 0.0
    due = db.conn.execute(
        "SELECT due_turn FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()["due_turn"]
    assert state.turn == int(due)

    out = settle_due_secret_orders(db, state, commit=True)
    row = next(r for r in out if r["order_id"] == oid)
    assert row["status"] == "failed"
    assert row["actual_units"] < row["target_units"]
    assert db.get_secret_order(oid)["status"] == "failed"

@pytest.mark.parametrize(
    "off_status",
    ["offstage", "dismissed", "imprisoned", "exiled", "retired", "dead"],
)
def test_offstage_minister_no_progress_no_world_effects(game, off_status):
    """扫描资格门：status 非 active 时不写进度/支出（直接写 status，避开 oust 连带关令）。"""
    db, state, _ = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    oid = _issue(db, state, name, "离场密令", "不应再办", months=2, target=2)
    # 离开发令月
    state.turn += 1
    db.save_state(state)
    before_neiku = int(state.metrics.get("内库", 0))
    # 直接改 status：令仍 active，专测月度扫描资格门
    db.conn.execute(
        "UPDATE characters SET status=? WHERE name=?", (off_status, name),
    )
    db.conn.commit()
    assert db.get_secret_order(oid)["status"] == "active"
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    out = apply_monthly_covert_actual_progress(
        db, state,
        selections=[{"order_id": oid, "fidelity": "忠实"}],
        commit=True,
    )
    row = next(r for r in out if r["order_id"] == oid)
    assert row.get("skipped") is True
    assert db.sum_dossier_actual_progress_units(did) == 0.0
    assert db.list_dossier_actual_progress(did) == []
    assert int(state.metrics.get("内库", 0)) == before_neiku

def test_missing_minister_row_no_progress(game):
    db, state, _ = game
    name = _minister(db)
    oid = _issue(db, state, name, "幽灵承办", "人已不在册", months=2, target=2)
    state.turn += 1
    db.save_state(state)
    # 承办名改为不在册（缺行）；保留 FK 指向的原人物行
    db.conn.execute(
        "UPDATE secret_orders SET minister_name=? WHERE id=?",
        ("不存在的承办人_1504", oid),
    )
    db.conn.commit()
    out = apply_monthly_covert_actual_progress(
        db, state,
        selections=[{"order_id": oid, "fidelity": "忠实"}],
        commit=True,
    )
    row = next(r for r in out if r["order_id"] == oid)
    assert row.get("skipped") is True

def test_mid_month_restore_preserves_actual_progress(game):
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=85, identity=40)
    oid = _issue(db, state, name, "可恢复密查", "查案", months=4, target=4)
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    # 跳过发令月再落笔
    state.turn += 1
    db.save_state(state)
    _originate_work(db, state, content, did)
    apply_monthly_covert_actual_progress(
        db, state,
        selections=[{"order_id": oid, "fidelity": "忠实"}],
        commit=True,
    )
    before = db.list_dossier_actual_progress(did)
    assert len(before) == 1 and before[0]["units"] == 1.0

    path = db.path
    db.close()
    db2 = type(db)(path, content)
    try:
        restored = db2.list_dossier_actual_progress(did)
        assert len(restored) == 1
        assert restored[0]["units"] == 1.0
        assert restored[0]["fidelity_state"] == "忠实"
        assert db2.sum_dossier_actual_progress_units(did) == 1.0
    finally:
        db2.close()

def test_secret_order_closes_field_is_ignored(game):
    db, state, content = game
    name = _minister(db)
    oid = _issue(db, state, name, "旧链密令", "不应被 closes 结", months=3, target=3)
    out = apply_score_extraction(
        db, state,
        {
            "secret_order_closes": [
                {"order_id": oid, "status": "done", "result": "LLM 伪结案"},
            ],
        },
        content=content,
    )
    assert "secret_order_closes" not in out
    assert db.get_secret_order(oid)["status"] == "active"

def test_auto_submit_due_no_longer_flips_pending_review(game):
    db, state, _ = game
    name = _minister(db)
    oid = _issue(db, state, name, "到期仍在办", "到期对账前保持 active", months=1, target=1)
    due = db.conn.execute(
        "SELECT due_turn FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()["due_turn"]
    state.turn = int(due)
    db.save_state(state)

    submitted = db.auto_submit_due_secret_orders(state)
    order = db.get_secret_order(oid)
    assert order["status"] == "active", order
    assert all(item.get("id") != oid or item.get("status") != "pending_review"
               for item in (submitted or [{"id": oid, "status": order["status"]}]))
    dossier = db.get_dossier_for_secret_order(oid)
    payload = json.loads(str(dossier["payload_json"]))
    assert "due_machine" not in payload

def test_monthly_actual_progress_preserves_selected_fidelity_in_sqlite(game):
    db, state, _ = game
    name = _minister(db)
    # The old loyalty-derived floor must not rewrite the selected execution state.
    _set_axes(db, name, loyalty=20, identity=80, seed_guilt="x")
    oid = _issue(db, state, name, "执行态由推演者决定", "本月执行态由推演者决定", months=2, target=2)
    state.turn += 1
    db.save_state(state)
    out = apply_monthly_covert_actual_progress(
        db, state,
        selections=[{"order_id": oid, "fidelity": "忠实"}],
        commit=True,
    )
    row = next(r for r in out if r["order_id"] == oid)
    assert row["fidelity"] == "忠实"
    persisted = db.list_dossier_actual_progress(row["dossier_id"])
    assert persisted[-1]["fidelity_state"] == "忠实"

def test_monthly_actual_does_not_invent_generic_world_package(game):
    """月度实况不发明 loyalty/内库/unrest 套餐；交付差务无 origin 则 units=0（不锁查核机械带）。"""
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    oid = _issue(db, state, name, "空转一月", "无实办", months=1, target=1)
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    state.turn += 1
    db.save_state(state)
    before_loyalty = int(db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (name,)
    ).fetchone()["loyalty"])
    before_neiku = int(state.metrics.get("内库", 0))
    out = apply_monthly_covert_actual_progress(
        db, state,
        selections=[{"order_id": oid, "fidelity": "忠实"}],
        commit=True,
    )
    row = next(r for r in out if r["order_id"] == oid)
    assert row["units"] == 0.0
    assert row.get("originated_quantity") == 0
    after_loyalty = int(db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (name,)
    ).fetchone()["loyalty"])
    assert after_loyalty == before_loyalty
    assert int(state.metrics.get("内库", 0)) == before_neiku
    assert db.list_economy_moves_for_dossier(did) == []

def test_submit_unlimited_keeps_frozen_target(game):
    db, state, _ = game
    name = _minister(db)
    oid = _issue(
        db, state, name, "无期补发饷银", "补发饷银",
        months=0, target=3, kind="补发饷银", axes=["既得利益"], unit="万两",
        tags=["辽饷", "兵部", "密查"],
    )
    contract0 = read_covert_task_contract(db.get_dossier_for_secret_order(oid))
    assert contract0["delivery"]["target_units"] == 3.0
    assert int(db.get_secret_order(oid)["due_turn"] or 0) == 0
    pending = settle_due_secret_orders(db, state, commit=True)
    assert all(int(row.get("order_id") or 0) != oid for row in pending)

    ok = db.submit_secret_order_for_review(oid, "臣已办结", state.year, state.period)
    assert ok is True
    live = db.get_secret_order(oid)
    assert int(live["due_turn"]) == int(state.turn)
    contract = read_covert_task_contract(db.get_dossier_for_secret_order(oid))
    assert contract["delivery"]["target_units"] == 3.0
    assert contract["kind"] == "补发饷银"
    assert contract["delivery"]["unit"] == "万两"

    out = settle_due_secret_orders(db, state, commit=True)
    row = next(r for r in out if r["order_id"] == oid)
    assert row["status"] == "failed"
    assert row["actual_units"] == 0.0
    assert not row["delivered"]
    assert db.get_secret_order(oid)["status"] == "failed"

def test_rush_preserves_frozen_contract(game):
    db, state, _ = game
    name = _minister(db)
    oid = _issue(
        db, state, name, "无期缉获", "拿人",
        months=0, target=3, kind="缉获人犯", unit="人犯",
    )
    db.rush_secret_order(oid, state, deadline_months=0, reason="即核")
    live = db.get_secret_order(oid)
    assert int(live["due_turn"]) == int(state.turn)
    contract = read_covert_task_contract(db.get_dossier_for_secret_order(oid))
    assert contract["delivery"]["target_units"] == 3.0
    assert contract["kind"] == "缉获人犯"
    assert contract["delivery"]["unit"] == "人犯"

@pytest.mark.parametrize("due_action", ["submit", "rush"])
def test_unlimited_investigation_due_now_reads_real_acquisitions(game, due_action):
    """#1896：无期限查核经提交/即核到期，结案读真实查获——不再按"一月配额"判。

    取代旧 test_..._uses_one_month_quota（拿期限月数当固定配额＝旧轨满统一阈残影）。
    此处密令约定取证 1 条，承办人真投入到该条难度 → 已掌握 1 条 → 办结。
    """
    db, state, _ = game
    name = _minister(db)
    target = db.conn.execute(
        "SELECT name FROM characters WHERE name<>? AND status='active' LIMIT 1",
        (name,),
    ).fetchone()["name"]
    _set_axes(db, name, loyalty=90, identity=30)
    db.conn.execute("UPDATE characters SET seed_guilt=? WHERE name=?", (_structured_guilt(), target))
    _co_locate(db, name, target)
    oid = _issue(
        db, state, name, "无期查核", "查核侵冒",
        months=0, target=1, kind="查核侵冒", axes=["既得利益"],
        investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    _dig_months(db, state, oid, target, months=2)
    assert investigation_lane_actual_units(db, did) == 1.0

    if due_action == "submit":
        assert db.submit_secret_order_for_review(
            oid, "臣已办结", state.year, state.period,
        ) is True
    else:
        db.rush_secret_order(oid, state, deadline_months=0, reason="即核")

    live = db.get_secret_order(oid)
    assert int(live["due_turn"]) == int(state.turn)
    span = db.conn.execute(
        "SELECT deadline_span FROM secret_orders WHERE id=?", (oid,),
    ).fetchone()["deadline_span"]
    assert int(span) == 0
    out = settle_due_secret_orders(db, state, commit=True)
    row = next(item for item in out if item["order_id"] == oid)
    assert row["status"] == "done"
    assert row["actual_units"] == 1.0        # 已掌握 1 条罪证
    assert row["target_units"] == 1.0        # 对密令约定的取证条数，与期限月数无关

def test_1376_candidate_confirm_freezes_explicit_typed_contract(game):
    db, state, content = game
    name = _minister(db)
    pid = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建",
        minister_name=name, target_id=None,
        payload={
            "title": "核辽饷侵冒",
            "content": "按数追赃补发",
            "assignee": name,
            "tags": ["辽饷", "兵部", "密查"],
            "deadline_months": 3,
            "covert_task": _task(
                kind="补发饷银", axes=["既得利益"], unit="万两", target=5,
            ),
        },
    )
    applied = db.commit_pending_actions(state, content=content, action_ids=[pid])
    assert applied
    oid = int(db.list_secret_orders(status="active")[0]["id"])
    contract = read_covert_task_contract(db.get_dossier_for_secret_order(oid))
    assert contract["kind"] == "补发饷银"
    assert contract["axes"] == ["既得利益"]
    assert contract["delivery"]["unit"] == "万两"
    assert contract["delivery"]["target_units"] == 5.0
    assert contract["kind"] != "稽核"

def test_non_finite_effort_is_invalid_not_full_investment(game):
    """#1896 R2：非有限数值不是"下了死力"，是坏产物——拒收，不洗成满额投入。

    float("NaN")/float("inf") 都成功，而 clamp 遇 NaN 原样返回：曾把 "NaN"
    洗成 1.0 的满额投入当月坐实。这里钉住：整段 4a 产物判 invalid 重来。
    """
    db, state, _ = game
    name = _minister(db)
    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    _set_axes(db, name, loyalty=90, identity=30)
    _co_locate(db, name, target)
    key = live_investigation_fact_keys(db, target)[0]
    oid = _issue(
        db, state, name, "查核", "查核", months=6, target=1,
        kind="查核", axes=["既得利益"], investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])

    for bad in ("NaN", "nan", "inf", "-inf", "Infinity"):
        _next_month(db, state)
        chain = _run_supply_4a(
            db, state, [{"order_id": oid, "fact_key": key, "effort": bad}],
        )
        assert chain.get("secret_orders_supply_invalid") is True, bad
        # 无效声明不落实况、不动 lane：没有"洗成满额投入"的合法完成
        assert investigation_lane_actual_units(db, did) == 0.0, bad
        assert _lanes(db, oid)[key]["effort"] == 0.0, bad

    # 对照：合法的显式 0 是零投入（不是无效），显式 1 才是真下功夫
    _next_month(db, state)
    chain = _run_supply_4a(
        db, state, [{"order_id": oid, "fact_key": key, "effort": 0}],
    )
    assert chain.get("secret_orders_supply_invalid") is not True
    assert _lanes(db, oid)[key]["effort"] == 0.0

def test_investigator_away_from_target_cannot_acquire_evidence(game):
    """#1896 R3：未到当地仍不能查获——不在目标当地，本月实投为零。

    已准设计原句「办案人得身在当地」。只查 transit_to 会漏掉"人根本不在
    那一省"这种形状：大理寺反例里承办人在云南、目标在北直隶，照样首月坐实。
    """
    db, state, _ = game
    name = _minister(db)
    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    _set_axes(db, name, loyalty=90, identity=30)
    db.conn.execute("UPDATE characters SET location='yunnan' WHERE name=?", (name,))
    db.conn.execute("UPDATE characters SET location='beizhili' WHERE name=?", (target,))
    db.conn.commit()
    key = live_investigation_fact_keys(db, target)[0]
    oid = _issue(
        db, state, name, "查核", "查核", months=6, target=1,
        kind="查核", axes=["既得利益"], investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])

    # 人在远地、真下死力（声明 1.2）→ 仍查不动
    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": oid, "fact_key": key, "effort": 1.2}])
    # 未到差 → 投入零，且查不动
    assert _lanes(db, oid)[key]["effort"] == 0.0
    assert investigation_lane_actual_units(db, did) == 0.0

    # 在途（人尚在路上）→ 同样查不动（0097：人未到差，差没开张）
    db.conn.execute(
        "UPDATE characters SET location='beizhili', transit_to='yunnan' WHERE name=?", (name,),
    )
    db.conn.commit()
    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": oid, "fact_key": key, "effort": 1.2}])
    assert investigation_lane_actual_units(db, did) == 0.0

    # 真到当地 → 同一份投入照常生效（该闸不是一刀切封死查案）
    db.conn.execute("UPDATE characters SET transit_to='' WHERE name=?", (name,))
    db.conn.commit()
    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": oid, "fact_key": key, "effort": 1.2}])
    assert _lanes(db, oid)[key]["effort"] > 0.0

def test_reaction_declarations_need_real_knowledge_across_months(game):
    """#1896 R5：知情是跨月持续的事实——上月真递到的话，本月照样承接毁证/压案。

    旧实现只取本次声明附带的来源，于是"先报信、次月毁证"落空（报信真实、
    毁证声明合法，spoiled 却仍是 []）。同时未知情时压案不得落账。
    """
    db, state, _ = game
    name = _minister(db)
    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    _set_axes(db, name, loyalty=90, identity=30)
    _co_locate(db, name, target)
    informer = _relation_informer(db, name, target)
    key = live_investigation_fact_keys(db, target)[0]
    oid = _issue(
        db, state, name, "查核", "查核", months=6, target=1,
        kind="查核", axes=["既得利益"], investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])

    # 未知情时声明压案 → 不落这项事实（引擎不替不知情的人记下他压了案）
    _next_month(db, state)
    _run_supply_4a(db, state, [
        {"order_id": oid, "effort": 0.0, "suppression": {"form": "行贿说项"}},
    ])
    payload = json.loads(db.get_dossier_for_secret_order(oid)["payload_json"])
    assert not any(
        "suppression" in a for a in payload.get(INVESTIGATION_ACTS_KEY, [])
    )

    # 本月真实报信
    _next_month(db, state)
    _run_supply_4a(db, state, [
        {"order_id": oid, "effort": 0.0, "tip_off": {"source": informer}},
    ])
    # 次月只声明毁证、不重复附来源（知情已由案卷已落的传话记录承接）
    _next_month(db, state)
    _run_supply_4a(db, state, [
        {"order_id": oid, "effort": 0.0,
         "spoliation": {"effect": "harder", "fact_key": key},
         "suppression": {"form": "托人斡旋"}},
    ])
    spoiled = db.list_investigation_spoiled_facts(target)
    assert [s["fact_key"] for s in spoiled] == [key]
    payload = json.loads(db.get_dossier_for_secret_order(oid)["payload_json"])
    acts = payload.get(INVESTIGATION_ACTS_KEY, [])
    assert acts[-1]["suppression"]["form"] == "托人斡旋"

def test_case_opening_source_clue_assists_its_fact(game):
    """#1896 R6：开案这条来源自身就是真实线索，与汇案来源同一条接线。

    旧实现只在汇案分支递交线索，首次开案的来源指针躺在合同里没人消费
    （同一合同：先开案 clues=[]，后汇案才拿到对应 clue）。
    """
    db, state, _ = game
    name = _minister(db)
    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    _set_axes(db, name, loyalty=90, identity=30)
    _co_locate(db, name, target)
    key = live_investigation_fact_keys(db, target)[0]
    task = {
        "kind": "查案", "axes": ["实务事功"], "direction": 1,
        "investigation_target": target,
        "investigation_fact": key,
        "delivery": {"target_units": 1.0, "effect_sign": 1,
                     "investigation_target": target},
    }
    oid = db.create_secret_order(
        state, name, "查核", "查核", [], deadline_months=6, covert_task=task,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    clues = investigation_clue_records(db, did)
    assert [c["fact_key"] for c in clues] == [key]
    # 真实助一次：线索把该条累计实投推上去（不替人物挑本月下手的对象）
    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": oid, "effort": 0.0}])
    assert _lanes(db, oid)[key]["effort"] > 0.0
    # 一次性消费：重开不双计
    credited = investigation_clue_records(db, did)[0]["credited"]
    assert credited is True

def test_case_opening_without_pointer_creates_no_clue(game):
    """#1896 F1：合同没带 investigation_fact 的开案**不造线索**。

    ADR 0098:11 的「各源加成」与兜底路由只作用于真实存在的来源（检举、证词、
    苦主这类确实带着案情而来的消息），「开案」这个动作本身不是来源。若无指针
    也照样记一条空线索，再让它走兜底路由，每道查案密令首月就会白得一次实投——
    「敷衍＝零投入」因此不成立。
    """
    db, state, _ = game
    name = _minister(db)
    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    _set_axes(db, name, loyalty=90, identity=30)
    _co_locate(db, name, target)
    key = live_investigation_fact_keys(db, target)[0]
    oid = db.create_secret_order(
        state, name, "查核", "查核", [], deadline_months=6,
        covert_task={
            "kind": "查案", "axes": ["实务事功"], "direction": 1,
            "investigation_target": target,
            "delivery": {"target_units": 1.0, "effect_sign": 1,
                         "investigation_target": target},
        },
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    assert investigation_clue_records(db, did) == []
    # 敷衍一月 → 该条实投确为 0（不因开案白送）
    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": oid, "effort": 0.0}])
    assert _lanes(db, oid)[key]["effort"] == 0.0
    assert investigation_lane_actual_units(db, did) == 0.0

def test_investigation_history_is_not_truncated(game):
    """#1896 R7：案卷里的行动／报信历史不截尾，供料给完整历史。

    ADR 0155:8 撤除硬历史上限；尾取 200／最后 6 条会让跨月的知情与因果承接
    读不到上月记录（也就是 R5 的一半病根）。
    """
    db, state, _ = game
    name = _minister(db)
    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    _set_axes(db, name, loyalty=90, identity=30)
    _co_locate(db, name, target)
    informer = _relation_informer(db, name, target)
    oid = _issue(
        db, state, name, "查核", "查核", months=30, target=1,
        kind="查核", axes=["既得利益"], investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    months = 9
    for i in range(months):
        _next_month(db, state)
        _run_supply_4a(db, state, [{
            "order_id": oid, "effort": 0.0, "method": f"第{i}月查法",
        }])
    payload = json.loads(db.get_dossier_for_secret_order(oid)["payload_json"])
    assert len(payload[INVESTIGATION_ACTS_KEY]) == months
    feed = build_secret_orders_supply_feed(db, state, {})
    order = next(o for o in feed["active_secret_orders"] if int(o["id"]) == oid)
    assert len(order["investigation_actions"]) == months
    assert order["investigation_actions"][0]["method"] == "第0月查法"

def test_no_evidence_case_opens_and_stays_empty(game):
    """#1896：无证可开案（空 lane 集合法）——不造罪，也不是免费清白神谕。

    清白目标照样占案、照样到期结案为查无实据，不即时拒开、不产查获。
    """
    db, state, _ = game
    name = _minister(db)
    # 取真相底确无实有罪证者（无 seed_guilt 且无 evidence 边）＝空 lane 集
    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters "
            "WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if not live_investigation_fact_keys(db, row["name"])
    )
    assert live_investigation_fact_keys(db, target) == []
    _set_axes(db, name, loyalty=90, identity=30)
    oid = _issue(
        db, state, name, "查核清白者", "查核清白者",
        months=1, target=1, kind="查核", axes=["既得利益"],
        investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    assert db.get_secret_order(oid)["status"] == "active"  # 照开
    state.turn += 1
    db.save_state(state)
    out = apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "effort": 1.0}], commit=True,
    )
    row = next(r for r in out if r["order_id"] == oid)
    assert row["effort_applied"] == 0.0  # 空 lane 集：投入无处可施，no-op 不抛
    assert row["units"] == 0.0
    assert investigation_lane_actual_units(db, did) == 0.0
    settled = settle_due_secret_orders(db, state, commit=True)
    close = next(r for r in settled if r["order_id"] == oid)
    assert close["status"] == "failed"
    assert close["actual_units"] == 0.0

def _relation_informer(db, source, target, *, context="通风报信之路"):
    """取与目标真有 0081 关系边的人；无则先落一条真实边（知情须有真实关系可循）。"""
    for edge in db.get_relation_edge_events(person=target):
        who = str(edge["source"]) if str(edge["target"]) == target else str(edge["target"])
        if who and who != target:
            return who
    db.record_relation_edge_event(
        source=source, target=target, event_kind="恩义",
        context=context, origin="test:1896-informer", evidence=False,
    )
    return str(source)

def test_spoliation_requires_real_knowledge_source(game):
    """#1896：开案不等于被查者知情——无真实关系网来源，引擎不代其毁证。"""
    db, state, _ = game
    name = _minister(db)
    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    _set_axes(db, name, loyalty=90, identity=30)
    key = live_investigation_fact_keys(db, target)[0]

    # 无来源 → 不毁
    out = apply_investigation_spoliation(
        db, target=target, fact_key=key, effect="gone", commit=True,
    )
    # 断言行为（未毁、实证不动），不锁诊断散文的措辞
    assert out["applied"] is False
    assert out["reason"]
    assert db.list_investigation_spoiled_facts(target) == []

    # 凭空捏造一个不相干的人 → 仍不毁（账本里查无此关系边）
    stranger = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name NOT IN (?,?)",
            (name, target),
        ).fetchall()
        if not db.get_relation_edge_events(person=target)
        or all(
            str(e["source"]) != row["name"] and str(e["target"]) != row["name"]
            for e in db.get_relation_edge_events(person=target)
        )
    )
    out = apply_investigation_spoliation(
        db, target=target, fact_key=key, effect="gone",
        knowledge_source=stranger, commit=True,
    )
    assert out["applied"] is False
    assert db.list_investigation_spoiled_facts(target) == []

    # 光有关系边不够：没有真实传话声明，仍判未知情（关系边存在 ≠ 话递到了）
    informer = _relation_informer(db, name, target)
    out = apply_investigation_spoliation(
        db, target=target, fact_key=key, effect="gone",
        knowledge_source=informer, commit=True,
    )
    assert out["applied"] is False
    assert db.list_investigation_spoiled_facts(target) == []

    # 真实关系网里的人确经关系网把话递到（4a 声明）→ 知情成立，毁证被承接
    oid = _issue(
        db, state, name, "查核待毁", "查核待毁",
        months=3, target=1, kind="查核", axes=["既得利益"],
        investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    _declare_tip(db, state, oid, informer)
    out = apply_investigation_spoliation(
        db, target=target, fact_key=key, effect="gone",
        knowledge_source=informer, dossier_id=did, commit=True,
    )
    assert out["applied"] is True
    assert out["knowledge_source"] == informer
    spoiled = db.list_investigation_spoiled_facts(target)
    assert [(row["fact_key"], row["effect"]) for row in spoiled] == [(key, "gone")]

def test_4a_unknown_target_declaring_spoliation_is_rejected(game):
    """#1896 贯穿 4a：被查者不知情而声明毁证 → 落账拒，实证不动。"""
    db, state, _ = game
    name = _minister(db)
    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    _set_axes(db, name, loyalty=90, identity=30)
    _co_locate(db, name, target)
    key = live_investigation_fact_keys(db, target)[0]
    oid = _issue(
        db, state, name, "查核无从下手", "查核无从下手",
        months=2, target=1, kind="查核", axes=["既得利益"],
        investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    state.turn += 1
    db.save_state(state)
    apply_monthly_covert_actual_progress(
        db, state,
        selections=[{
            "order_id": oid,
            "effort": 0.0,
            # 无知情来源的毁证声明
            "spoliation": {"effect": "gone", "fact_key": key},
        }],
        commit=True,
    )
    assert db.list_investigation_spoiled_facts(target) == []
    assert key in live_investigation_fact_keys(db, target)
    assert investigation_lane_actual_units(db, did) == 0.0

def test_spoliation_makes_fact_harder_and_survives_case_reopen(game):
    """#1896 / ADR 0100 后出：毁证按事实改可查性，不团灭，重开案不恢复。

    抬难后的难度是开案时账上难度的 1.5 倍，写在该条 lane 上。
    同目标另一条罪的难度不动。毁成 gone 之后，本案和后来的新案都投不进。
    """
    db, state, _ = game
    name = _minister(db)
    target = db.conn.execute(
        "SELECT name FROM characters WHERE name<>? AND status='active' LIMIT 1",
        (name,),
    ).fetchone()["name"]
    _set_axes(db, name, loyalty=90, identity=30)
    db.conn.execute(
        "UPDATE characters SET seed_guilt=?, intrigue=50, ability=60, "
        "location='京师', transit_to='' WHERE name=?",
        (_structured_guilt(), target),
    )
    db.conn.execute(
        "UPDATE characters SET ability=60, location='京师', transit_to='' WHERE name=?",
        (name,),
    )
    db.conn.commit()
    edge_id = db.record_relation_edge_event(
        source=name, target=target, event_kind="把柄",
        context="另一条罪证", origin="test:spoil", evidence=True,
    )
    _co_locate(db, name, target, place="京师")
    informer = _relation_informer(db, name, target)
    oid = _issue(
        db, state, name, "查核待毁", "查核待毁",
        months=6, target=1, kind="查核", axes=["既得利益"],
        investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": oid, "fact_key": target, "effort": 0.0}])
    guilt_before = float(_lanes(db, oid)[target]["difficulty"])
    edge_before = float(_lanes(db, oid)[str(edge_id)]["difficulty"])

    _next_month(db, state)
    _run_supply_4a(db, state, [{
        "order_id": oid,
        "effort": 0.0,
        "tip_off": {"source": informer},
        "spoliation": {"effect": "harder", "fact_key": target},
    }])
    spoiled = db.list_investigation_spoiled_facts(target)
    assert [(row["fact_key"], row["effect"]) for row in spoiled] == [(target, "harder")]

    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": oid, "fact_key": target, "effort": 1.0}])
    assert _lanes(db, oid)[target]["difficulty"] == pytest.approx(guilt_before * 1.5)
    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": oid, "fact_key": str(edge_id), "effort": 1.0}])
    assert _lanes(db, oid)[str(edge_id)]["difficulty"] == pytest.approx(edge_before)

    _next_month(db, state)
    _run_supply_4a(db, state, [{
        "order_id": oid,
        "effort": 0.0,
        "spoliation": {"effect": "gone", "fact_key": target},
    }])
    held = float(_lanes(db, oid)[target]["effort"])
    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": oid, "fact_key": target, "effort": 1.0}])
    assert float(_lanes(db, oid)[target]["effort"]) == held
    assert investigation_lane_actual_units(db, did) == 0.0

    _retire_order(db, oid)
    reopen = _issue(
        db, state, name, "重开查案", "重开查案",
        months=3, target=1, kind="查核", axes=["既得利益"],
        investigation_target=target,
    )
    reopen_did = int(db.get_dossier_for_secret_order(reopen)["id"])
    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": reopen, "fact_key": target, "effort": 1.0}])
    assert _lanes(db, reopen)[target]["effort"] == 0.0
    assert investigation_lane_actual_units(db, reopen_did) == 0.0
    assert target in live_investigation_fact_keys(db, target)
    rows = [
        row for row in db.list_investigation_spoiled_facts(target)
        if row["fact_key"] == target
    ]
    assert [row["effect"] for row in rows] == ["harder", "gone"]

def test_false_memorial_does_not_create_or_erase_evidence(game):
    """#1896：奏报可以谎——假密奏不造罪也不抹证，结案只读实账。"""
    db, state, _ = game
    name = _minister(db)
    target = db.conn.execute(
        "SELECT name FROM characters WHERE name<>? AND status='active' LIMIT 1",
        (name,),
    ).fetchone()["name"]
    _set_axes(db, name, loyalty=90, identity=30)
    db.conn.execute("UPDATE characters SET seed_guilt=? WHERE name=?", ('{"crime": "无", "severity": "无"}', target))
    _co_locate(db, name, target)
    oid = _issue(
        db, state, name, "谎报密查", "谎报密查",
        months=6, target=1, kind="查核", axes=["既得利益"],
        investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    for guilt in ('{"crime": "无", "severity": "无"}', ""):
        db.conn.execute(
            "UPDATE characters SET seed_guilt=? WHERE name=?",
            (guilt, target),
        )
        db.conn.commit()
        state.turn += 1
        db.save_state(state)
        apply_monthly_covert_actual_progress(
            db, state, selections=[{"order_id": oid, "effort": 0.0}], commit=True,
        )
        payload = json.loads(db.get_dossier_for_secret_order(oid)["payload_json"])
        keys = {row["fact_key"] for row in payload.get(FACT_LANES_KEY) or []}
        assert target not in keys

    db.conn.execute("UPDATE characters SET seed_guilt=? WHERE name=?", (_structured_guilt(), target))
    db.conn.commit()
    state.turn += 1
    db.save_state(state)
    # 奏报自称"已查明全部" + 零投入
    db.record_dossier_progress(
        did, state.turn, "办成", "臣已查明全部罪状", is_terminal=False,
    )
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "effort": 0.0}], commit=True,
    )
    state.turn = int(db.get_secret_order(oid)["due_turn"])
    db.save_state(state)
    settled = settle_due_secret_orders(db, state, commit=True)
    close = next(r for r in settled if r["order_id"] == oid)
    assert close["status"] == "failed"
    assert close["actual_units"] == 0.0
    # 实证未被奏报改动：罪仍在真相底
    assert target in live_investigation_fact_keys(db, target)

def test_4a_declaration_lands_actions_and_spoliation_through_month_chain(game):
    """#1896 贯穿 4a 接缝：查法/传话/投入/毁证/压案声明都走既有写口落账。

    不新增人物调用、不新增转译调用、不新增第二写口——既有
    ``covert_exec_selections`` 里的查案项按新形状被读、被算、被记。
    """
    db, state, _ = game
    name = _minister(db)
    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    _set_axes(db, name, loyalty=90, identity=30)
    edge_id = db.record_relation_edge_event(
        source=name, target=target, event_kind="把柄",
        context="第二条罪证", origin="test:1896-e2e", evidence=True,
    )
    assert str(edge_id) in live_investigation_fact_keys(db, target)
    oid = _issue(
        db, state, name, "查核两罪", "查核两罪",
        months=2, target=1, kind="查核", axes=["既得利益"],
        investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    informer = _relation_informer(db, name, target)

    # 4a 产物形状：查法 + 真实递话 + 深挖一条 + 知情后毁另一条 + 压案
    selection = {
        "order_id": oid,
        "effort": 1.0,
        "fact_key": target,
        "method": "访查旧账",
        "tip_off": {"source": informer},
        "spoliation": {"effect": "harder", "fact_key": str(edge_id)},
        "suppression": {"form": "托人说项"},
        "note": "臣已查得实据",
    }
    _next_month(db, state)
    chain = _run_supply_4a(db, state, [selection])
    assert chain.get("covert_progress_done") is True
    assert chain.get("secret_orders_supply_invalid") is not True

    # 声明落账：传话、查法、压案都是账上事实（P1 全量落库）
    payload = json.loads(db.get_dossier_for_secret_order(oid)["payload_json"])
    assert payload[INVESTIGATION_TIPS_KEY][-1]["source"] == informer
    acts = payload[INVESTIGATION_ACTS_KEY][-1]
    assert acts["method"] == "访查旧账"
    assert acts["suppression"] == {"form": "托人说项"}

    # 深挖落在所点的那条罪上。毁证落在账上，不改真相底。
    lane = _lanes(db, oid)[target]
    assert lane["effort"] > 0.0
    spoiled = db.list_investigation_spoiled_facts(target)
    assert [(row["fact_key"], row["effect"]) for row in spoiled] == [(str(edge_id), "harder")]
    assert str(edge_id) in live_investigation_fact_keys(db, target)
    assert target in live_investigation_fact_keys(db, target)
    rows = db.list_dossier_actual_progress(did)
    assert len(rows) == 1
    assert rows[-1]["units"] == investigation_lane_actual_units(db, did)

def _dig_months(db, state, oid, fact_key, intensity=1.0, months=1):
    """逐月推进 turn 并经真实 4a 入口落一条声明（供结算类用例连推数月）。"""
    for _ in range(int(months)):
        _next_month(db, state)
        apply_monthly_covert_actual_progress(
            db, state,
            selections=[{"order_id": oid, "fact_key": fact_key, "effort": intensity}],
            commit=True,
        )

def _lanes(db, oid):
    payload = json.loads(db.get_dossier_for_secret_order(oid)["payload_json"])
    return {r["fact_key"]: r for r in payload[FACT_LANES_KEY]}

def _open_errands(db, name, *, except_dossier=0):
    return int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers "
        "WHERE executor_kind='character' AND executor_id=? "
        "AND status IN ('promulgated','executing') AND id<>?",
        (name, int(except_dossier)),
    ).fetchone()["n"])

def _retire_order(db, order_id):
    db.conn.execute(
        "UPDATE secret_orders SET status='cancelled' WHERE id=?", (int(order_id),),
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET status='closed' WHERE secret_order_id=?",
        (int(order_id),),
    )
    db.conn.commit()

def _clear_open_errands(db, name):
    db.conn.execute(
        "UPDATE decree_dossiers SET status='closed' "
        "WHERE executor_kind='character' AND executor_id=? "
        "AND status IN ('promulgated','executing')",
        (name,),
    )
    db.conn.commit()

def test_deep_dig_lands_through_month_chain_entry(game):
    """#1896 贯穿：4a 声明经真实月链接缝落账。

    能力、未结差务、遮掩和逐证掌握都在这一条入口上见结果。实投数字来自
    契约常量，不回读当月产能函数。
    """
    from ming_sim.session import register_unlisted_person_record

    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    _clear_open_errands(db, name)
    db.conn.execute(
        "UPDATE characters SET ability=60, transit_to='' WHERE name=?", (name,),
    )
    db.conn.commit()

    # 承办人能力与未结差务：同一 4a 入口上的四组独立常量。
    cap_target = "周慎行"
    register_unlisted_person_record(
        db, state, content,
        name=cap_target, office="兵部主事", office_type="兵部", faction="东林",
        region_id="京师",
    )
    db.conn.execute(
        "UPDATE characters SET seed_guilt=?, intrigue=100, location='京师', transit_to='' "
        "WHERE name=?",
        (_structured_guilt(), cap_target),
    )
    db.conn.commit()
    _co_locate(db, name, cap_target, place="京师")
    def _one_month(ability):
        db.conn.execute(
            "UPDATE characters SET ability=? WHERE name=?", (ability, name),
        )
        db.conn.commit()
        oid = _issue(
            db, state, name, "查核产能", "查核产能", months=12, target=1,
            kind="查核", axes=["既得利益"], investigation_target=cap_target,
        )
        did = int(db.get_dossier_for_secret_order(oid)["id"])
        _next_month(db, state)
        selections = [{"order_id": oid, "fact_key": cap_target, "effort": 1.0}]
        selections.extend(
            {"order_id": int(order["id"]), "fidelity": "忠实"}
            for order in db.list_secret_orders(status="active")
            if int(order["id"]) != oid
        )
        chain = _run_supply_4a(db, state, selections)
        assert chain.get("covert_progress_done") is True
        assert chain.get("secret_orders_supply_invalid") is not True
        effort = float(_lanes(db, oid)[cap_target]["effort"])
        _retire_order(db, oid)
        return did, effort

    _did, effort = _one_month(0)
    assert _open_errands(db, name) == 0
    assert effort == pytest.approx(0.5)
    _did, effort = _one_month(1)
    assert effort == pytest.approx(0.5083333333333333)
    _did, effort = _one_month(60)
    assert effort == pytest.approx(1.0)
    errands = [
        _issue(
            db, state, name, title, title, months=6, target=1,
            kind="缉获人犯", unit="人犯",
        )
        for title in ("旁务甲", "旁务乙", "旁务丙")
    ]
    busy_did, effort = _one_month(60)
    assert _open_errands(db, name, except_dossier=busy_did) == 3
    assert effort == pytest.approx(0.55)
    for extra in errands:
        _retire_order(db, extra)
    assert _open_errands(db, name) == 0

    # 相同满强度：遮掩低者已掌握，遮掩高者尚未。零遮掩不比低遮掩更难。
    investigator = name
    seen = {}
    for suspect, intrigue in (("黄道周", 0), ("魏忠贤", 1), ("王在晋", 100)):
        db.conn.execute(
            "UPDATE characters SET seed_guilt=?, intrigue=?, location='京师', transit_to='' "
            "WHERE name=?",
            (_structured_guilt(), intrigue, suspect),
        )
        db.conn.execute(
            "UPDATE characters SET ability=60, location='京师', transit_to='' WHERE name=?",
            (investigator,),
        )
        db.conn.commit()
        oid = _issue(
            db, state, investigator, "密查", "密查", months=6, target=1,
            kind="查核", axes=["既得利益"], investigation_target=suspect,
        )
        did = int(db.get_dossier_for_secret_order(oid)["id"])
        _next_month(db, state)
        chain = _run_supply_4a(
            db, state, [{"order_id": oid, "fact_key": suspect, "effort": 1.0}],
        )
        assert chain.get("covert_progress_done") is True
        assert chain.get("secret_orders_supply_invalid") is not True
        seen[intrigue] = investigation_lane_actual_units(db, did)
        _retire_order(db, oid)
    assert seen[0] >= 1.0
    assert seen[1] >= 1.0
    assert seen[100] == 0.0

    # 关系网只认结构化 evidence 边。无边、或只有自由类目边：满月实投 1 即掌握。
    # 一条把柄边把难度抬到 1.05，同一实投掌握不了。党籍认同不进这道账。
    def _network_month(suspect, *, identity, edge=None):
        assert register_unlisted_person_record(
            db, state, content,
            name=suspect, office="兵部主事", office_type="兵部", faction="东林",
            region_id="京师",
        ) is not None
        db.conn.execute(
            "UPDATE characters SET seed_guilt=?, intrigue=50, identity=?, "
            "ability=60, location='京师', transit_to='' WHERE name=?",
            (_structured_guilt(), identity, suspect),
        )
        db.conn.execute(
            "UPDATE characters SET ability=60, location='京师', transit_to='' WHERE name=?",
            (name,),
        )
        db.conn.commit()
        _co_locate(db, name, suspect, place="京师")
        if edge is not None:
            kind, evidence = edge
            db.record_relation_edge_event(
                source=name, target=suspect, event_kind=kind,
                context="关系网对照", origin=f"test:1896-{suspect}", evidence=evidence,
            )
        oid = _issue(
            db, state, name, "查核关系网", "查核关系网", months=6, target=1,
            kind="查核", axes=["既得利益"], investigation_target=suspect,
        )
        _next_month(db, state)
        chain = _run_supply_4a(
            db, state, [{"order_id": oid, "fact_key": suspect, "effort": 1.0}],
        )
        assert chain.get("covert_progress_done") is True
        assert chain.get("secret_orders_supply_invalid") is not True
        lane = _lanes(db, oid)[suspect]
        _retire_order(db, oid)
        return lane

    plain = _network_month("查网甲", identity=95)
    assert plain["effort"] == pytest.approx(1.0)
    assert plain["difficulty"] == pytest.approx(1.0)
    assert plain["mastered"] is True
    category = _network_month("查网乙", identity=5, edge=("站台", False))
    assert category["effort"] == pytest.approx(1.0)
    assert category["difficulty"] == pytest.approx(1.0)
    assert category["mastered"] is True
    levered = _network_month("查网丙", identity=95, edge=("把柄", True))
    assert levered["effort"] == pytest.approx(1.0)
    assert levered["difficulty"] == pytest.approx(1.05)
    assert levered["mastered"] is False

    # 未指明罪证不下手；未达难度不掌握；达到后掌握。新边是新 lane。再投入不双计。
    db.conn.execute(
        "UPDATE characters SET ability=60, transit_to='' WHERE name=?", (name,),
    )
    db.conn.commit()
    assert _open_errands(db, name) == 0
    topic = "申用嘉"
    register_unlisted_person_record(
        db, state, content,
        name=topic, office="户部主事", office_type="户部", faction="东林",
        region_id="京师",
    )
    db.conn.execute(
        "UPDATE characters SET seed_guilt=?, intrigue=50, location='京师', transit_to='' "
        "WHERE name=?",
        (_structured_guilt(), topic),
    )
    db.conn.commit()
    _co_locate(db, name, topic, place="京师")
    oid = _issue(
        db, state, name, "查核掌握", "查核掌握", months=24, target=2,
        kind="查核", axes=["既得利益"], investigation_target=topic,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    _next_month(db, state)
    chain = _run_supply_4a(db, state, [{"order_id": oid, "effort": 1.0}])
    assert chain.get("secret_orders_supply_invalid") is not True
    assert _lanes(db, oid)[topic]["effort"] == 0.0
    assert investigation_lane_actual_units(db, did) == 0.0

    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": oid, "fact_key": topic, "effort": 0.2}])
    assert _lanes(db, oid)[topic]["effort"] == pytest.approx(0.2)
    assert _lanes(db, oid)[topic]["mastered"] is False
    assert investigation_lane_actual_units(db, did) == 0.0

    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": oid, "fact_key": topic, "effort": 1.0}])
    lane = _lanes(db, oid)[topic]
    assert lane["effort"] == pytest.approx(1.2)
    assert lane["mastered"] is True
    assert set(lane) == {"fact_key", "effort", "difficulty", "months", "mastered"}
    assert investigation_lane_actual_units(db, did) == 1.0
    fed = build_secret_orders_supply_feed(db, state, {})
    fed_order = next(item for item in fed["active_secret_orders"] if int(item["id"]) == oid)
    fed_fact = next(item for item in fed_order["investigation_facts"] if item["fact_key"] == topic)
    assert fed_fact["state"] == "已掌握"
    assert "difficulty" not in fed_fact

    edge_id = db.record_relation_edge_event(
        source=name, target=topic, event_kind="把柄",
        context="侵冒把柄", origin=f"test:{did}", evidence=True,
    )
    # 把柄边基准 1.4，一条 evidence 边再乘 1.05 → 1.47。满月实投 1，一月不够，两月掌握。
    _next_month(db, state)
    _run_supply_4a(
        db, state, [{"order_id": oid, "fact_key": str(edge_id), "effort": 1.0}],
    )
    edge_lane = _lanes(db, oid)[str(edge_id)]
    assert edge_lane["effort"] == pytest.approx(1.0)
    assert edge_lane["difficulty"] == pytest.approx(1.47)
    assert edge_lane["mastered"] is False
    _next_month(db, state)
    _run_supply_4a(
        db, state, [{"order_id": oid, "fact_key": str(edge_id), "effort": 1.0}],
    )
    edge_lane = _lanes(db, oid)[str(edge_id)]
    assert edge_lane["effort"] == pytest.approx(2.0)
    assert edge_lane["mastered"] is True
    assert investigation_lane_actual_units(db, did) == 2.0
    held = float(_lanes(db, oid)[topic]["effort"])
    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": oid, "fact_key": topic, "effort": 1.0}])
    assert float(_lanes(db, oid)[topic]["effort"]) == held
    assert investigation_lane_actual_units(db, did) == 2.0
    _retire_order(db, oid)

    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    _co_locate(db, name, target)
    key = live_investigation_fact_keys(db, target)[0]
    oid = _issue(
        db, state, name, "查核", "查核", months=6, target=1,
        kind="查核", axes=["既得利益"], investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])

    # 模型把 effort 填到荒谬的 100 → 引擎只吃强度，实投由人物处境折算
    _next_month(db, state)
    chain = _run_supply_4a(
        db, state, [{"order_id": oid, "fact_key": key, "effort": 100}],
    )
    assert chain.get("covert_progress_done") is True
    assert chain.get("secret_orders_supply_invalid") is not True
    lane = _lanes(db, oid)[key]
    assert lane["effort"] == pytest.approx(1.0)
    assert lane["effort"] != 100
    assert investigation_lane_actual_units(db, did) == float(lane["mastered"])

    # 敷衍（显式 0）下月零投入：不增投入、不重复计数
    _next_month(db, state)
    _run_supply_4a(
        db, state, [{"order_id": oid, "fact_key": key, "effort": 0.0}],
    )
    assert _lanes(db, oid)[key]["effort"] == lane["effort"]

    # 未到差（人在途中）→ 本月查不动当地罪证，即便声明满强度
    db.conn.execute(
        "UPDATE characters SET transit_to='yunnan', transit_distance_remaining=3.5 "
        "WHERE name=?",
        (name,),
    )
    db.conn.commit()
    before = investigation_lane_actual_units(db, did)
    _next_month(db, state)
    _run_supply_4a(
        db, state, [{"order_id": oid, "fact_key": key, "effort": 1.0}],
    )
    assert _lanes(db, oid)[key]["effort"] == lane["effort"]
    assert investigation_lane_actual_units(db, did) == before

    # 人未到差时，带指针的汇案来源也不加成、不标已消费；回到当地后仍可一次性消费。
    db.create_secret_order(
        state, name, "在途来源", "在途来源", [],
        deadline_months=3,
        covert_task={
            "kind": "查核", "axes": ["既得利益"], "direction": 1,
            "investigation_target": target, "investigation_fact": key,
            "delivery": {
                "target_units": 1.0, "effect_sign": 1,
                "investigation_target": target, "investigation_fact": key,
            },
        },
    )
    frozen = float(_lanes(db, oid)[key]["effort"])
    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": oid, "fact_key": key, "effort": 0.0}])
    assert float(_lanes(db, oid)[key]["effort"]) == frozen
    assert investigation_clue_records(db, did)[-1]["credited"] is False
    db.conn.execute(
        "UPDATE characters SET transit_to='' WHERE name=?", (name,),
    )
    db.conn.commit()
    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": oid, "fact_key": key, "effort": 0.0}])
    assert float(_lanes(db, oid)[key]["effort"]) > frozen
    assert investigation_clue_records(db, did)[-1]["credited"] is True

def test_invalid_investigation_declaration_is_rejected_not_zero_effort(game):
    """#1896：缺 effort／effort 非数字／只给旧执行态＝无效声明，不是合法零投入。

    拒收且不写实况行；合法零投入只有一种写法：显式 effort: 0。
    """
    db, state, _ = game
    name = _minister(db)
    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    _set_axes(db, name, loyalty=90, identity=30)
    _co_locate(db, name, target)
    key = live_investigation_fact_keys(db, target)[0]
    oid = _issue(
        db, state, name, "查核", "查核", months=6, target=1,
        kind="查核", axes=["既得利益"], investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    _next_month(db, state)

    for bad in ({}, {"effort": "尽力"}, {"fidelity": "忠实", "fact_key": key}):
        out = apply_monthly_covert_actual_progress(
            db, state, selections=[{"order_id": oid, **bad}], commit=True,
        )
        row = next(r for r in out if r["order_id"] == oid)
        assert row["rejected"] is True
        assert row["invalid"] is True
        assert row["category"] == "invalid_enum"
        assert db.list_dossier_actual_progress(did) == []
        assert _lanes(db, oid)[key]["effort"] == 0.0

    # 合法零投入：显式 0 → 正常落账、无查获
    out = apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "effort": 0.0}], commit=True,
    )
    row = next(r for r in out if r["order_id"] == oid)
    assert "rejected" not in row
    assert row["units"] == 0.0
    assert len(db.list_dossier_actual_progress(did)) == 1

@pytest.mark.parametrize("bad", [{}, {"effort": "尽力"}, {"fidelity": "忠实"}])
def test_invalid_declaration_stops_month_chain_and_marks_invalid(game, bad):
    """#1896 月链层：无效查案声明不冒充合法完成——4a 停续并走 #1846 失效重起。

    走真实入口（``_run_supply_4a`` → month_chain._step_4a_secret_order_supply）：
    本段回滚、置 invalid、写 call_failure、重试弃产物重来；合法零投入不受影响。
    """
    db, state, _ = game
    name = _minister(db)
    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    _set_axes(db, name, loyalty=90, identity=30)
    _co_locate(db, name, target)
    key = live_investigation_fact_keys(db, target)[0]
    oid = _issue(
        db, state, name, "查核", "查核", months=6, target=1,
        kind="查核", axes=["既得利益"], investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    _next_month(db, state)

    chain = _run_supply_4a(db, state, [{"order_id": oid, **bad}])
    assert chain.get("covert_progress_done") is not True
    assert chain.get("secret_orders_supply_done") is not True
    assert chain.get("secret_orders_supply_invalid") is True
    assert (chain.get("call_failure") or {}).get("step") == "secret_orders_supply"
    # 本段不留半截实况行、不改实证
    assert db.list_dossier_actual_progress(did) == []
    assert _lanes(db, oid)[key]["effort"] == 0.0
    assert investigation_lane_actual_units(db, did) == 0.0

    # 重试走**真实**的 #1846 失效重起接缝：玩家点重试 → _consume_call_failure_for_retry
    # 弃掉无效产物与 invalid 标记 → 再入主链续未成相位。（此前此用例每次都新建
    # chain，等于绕过了真正的重试口，证明不了失效重起真的接得上。）
    import ming_sim.month_chain as month_chain

    month_chain._consume_call_failure_for_retry(
        db, chain, int(state.turn), decree_text="", source=Provenance.secret_order,
    )
    resumed = month_chain._load_chain(db, int(state.turn))
    assert "secret_orders_supply_product" not in resumed
    assert "secret_orders_supply_invalid" not in resumed
    assert "call_failure" not in resumed
    # 重入主链会**真的重调** 4a（这正是失效重起）：桩掉外部模型边界，返回一份
    # 合法产物。桩只代模型调用本身，不代月链相位。
    calls = []

    def _fake_supply(db_, state_, llm_config_, chain_):
        calls.append(True)
        return {
            "dossier_progress_reports": [
                {"dossier_id": int(r["dossier_id"]), "progress_band": "持平",
                 "memorial_text": "据实以奏"}
                for r in db_.list_monthly_dossier_progress_nudges(int(state_.turn))
            ],
            "covert_exec_selections": [
                {"order_id": oid, "fact_key": key, "effort": 1.0},
            ],
        }

    monkey = pytest.MonkeyPatch()
    monkey.setattr(month_chain, "run_secret_orders_supply", _fake_supply)
    try:
        month_chain._step_4a_secret_order_supply(
            db, state, resumed,
            turn=int(state.turn), decree_text="", source=Provenance.secret_order,
            llm_config=object(),
        )
    except SettlementAbort as exc:  # pragma: no cover - 只在桩之外失败时出现
        raise AssertionError(f"失效重起后不该再停续：{exc}")
    finally:
        monkey.undo()
    assert calls, "重试未真正重调 4a——说明仍在复用被废弃的无效产物"
    assert resumed.get("covert_progress_done") is True
    assert resumed.get("secret_orders_supply_done") is True
    assert _lanes(db, oid)[key]["effort"] > 0.0

def test_repeated_pointerless_orders_do_not_mint_clues(game):
    """连续无指针下令不是来源。已落库的空指针旧线索仍按 ADR 0098:11 路由。"""
    db, state, _ = game
    name = _minister(db)
    target = db.conn.execute(
        "SELECT name FROM characters WHERE name<>? AND status='active' LIMIT 1",
        (name,),
    ).fetchone()["name"]
    _set_axes(db, name, loyalty=90, identity=30)
    db.conn.execute(
        "UPDATE characters SET seed_guilt=? WHERE name=?",
        (_structured_guilt(), target),
    )
    _co_locate(db, name, target)
    edge_id = db.record_relation_edge_event(
        source=name, target=target, event_kind="把柄",
        context="另指一条", origin="test:1896-nopointer", evidence=True,
    )
    oid = _issue(
        db, state, name, "查核", "查核", months=6, target=1,
        kind="查核", axes=["既得利益"], investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    assert investigation_clue_records(db, did) == []
    for _ in range(4):
        merged = db.create_secret_order(
            state, name, "并案泛指", "有人泛泛告发一端",
            [], deadline_months=3,
            covert_task={
                "kind": "查核", "axes": ["既得利益"], "direction": 1,
                "investigation_target": target,
                "delivery": {"target_units": 1.0, "effect_sign": 1,
                             "investigation_target": target},
            },
        )
        assert merged == oid
    assert investigation_clue_records(db, did) == []
    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": oid, "fact_key": target, "effort": 0.0}])
    assert float(_lanes(db, oid)[target]["effort"]) == 0.0
    assert float(_lanes(db, oid)[str(edge_id)]["effort"]) == 0.0

    # 旧档里已经写下的空指针线索，仍一次性归 seed_guilt lane，不落到边事件。
    payload = json.loads(db.get_dossier_for_secret_order(oid)["payload_json"])
    payload["investigation_clues"] = [{
        "fact_key": "", "credited": False, "turn": int(state.turn),
    }]
    db.update_decree_dossier_payload(did, payload, commit=True)
    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": oid, "fact_key": target, "effort": 0.0}])
    clue = investigation_clue_records(db, did)[-1]
    assert clue["routed_fact_key"] == target
    assert clue["credited"] is True
    assert float(_lanes(db, oid)[target]["effort"]) > 0.0
    assert float(_lanes(db, oid)[str(edge_id)]["effort"]) == 0.0

    clean = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name NOT IN (?,?) ORDER BY name",
            (name, target),
        ).fetchall()
        if not live_investigation_fact_keys(db, row["name"])
    )
    _co_locate(db, name, clean)
    clean_oid = _issue(
        db, state, name, "查核清白", "查核清白", months=3, target=1,
        kind="查核", axes=["既得利益"], investigation_target=clean,
    )
    clean_did = int(db.get_dossier_for_secret_order(clean_oid)["id"])
    again = db.create_secret_order(
        state, name, "并案泛指", "有人泛泛告发一端", [], deadline_months=3,
        covert_task={
            "kind": "查核", "axes": ["既得利益"], "direction": 1,
            "investigation_target": clean,
            "delivery": {"target_units": 1.0, "effect_sign": 1,
                         "investigation_target": clean},
        },
    )
    assert again == clean_oid
    assert investigation_clue_records(db, clean_did) == []
    _next_month(db, state)
    _run_supply_4a(db, state, [
        {"order_id": oid, "fact_key": target, "effort": 0.0},
        {"order_id": clean_oid, "effort": 0.0},
    ])
    assert investigation_lane_actual_units(db, clean_did) == 0.0

def test_merged_clue_assists_the_fact_it_points_at(game):
    """#1896：汇案的真实线索助它所指的实证，一次性消费；指向不存在的罪则丢弃。"""
    db, state, _ = game
    name = _minister(db)
    target = db.conn.execute(
        "SELECT name FROM characters WHERE name<>? AND status='active' LIMIT 1",
        (name,),
    ).fetchone()["name"]
    _set_axes(db, name, loyalty=90, identity=30)
    db.conn.execute("UPDATE characters SET seed_guilt=? WHERE name=?", (_structured_guilt(), target))
    _co_locate(db, name, target)
    edge_id = db.record_relation_edge_event(
        source=name, target=target, event_kind="把柄",
        context="另指一条", origin="test:1896-clue", evidence=True,
    )
    oid = _issue(
        db, state, name, "查核", "查核", months=6, target=1,
        kind="查核", axes=["既得利益"], investigation_target=target,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])

    # 另一来源就同一目标再下一条密令 → 汇案，并带线索指针
    merged = db.create_secret_order(
        state, name, "并案线索", "有人告发一端",
        [], deadline_months=3,
        covert_task={
            "kind": "查核", "axes": ["既得利益"], "direction": 1,
            "investigation_target": target, "investigation_fact": str(edge_id),
            "delivery": {
                "target_units": 1.0, "effect_sign": 1, "investigation_target": target,
                "investigation_fact": str(edge_id),
            },
        },
    )
    assert merged == oid  # 同目标汇案，不另开
    assert investigation_clue_records(db, did)[-1]["fact_key"] == str(edge_id)

    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": oid, "fact_key": target, "effort": 0.0}])
    lanes = _lanes(db, oid)
    assert lanes[str(edge_id)]["effort"] > 0.0      # 线索助了它所指的那条
    assert investigation_clue_records(db, did)[-1]["credited"] is True
    assert lanes[target]["effort"] == 0.0           # 没助别的罪

    # 同一线索不再二次消费
    consumed = float(lanes[str(edge_id)]["effort"])
    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": oid, "fact_key": target, "effort": 0.0}])
    assert float(_lanes(db, oid)[str(edge_id)]["effort"]) == consumed

    # 旧证已掌握后，同月仍声明旧键、另汇一条独立新证：新证线索照样承接。
    for _ in range(6):
        if _lanes(db, oid)[target].get("mastered"):
            break
        _next_month(db, state)
        _run_supply_4a(db, state, [{"order_id": oid, "fact_key": target, "effort": 1.0}])
    assert _lanes(db, oid)[target]["mastered"] is True
    fresh = db.record_relation_edge_event(
        source=name, target=target, event_kind="把柄",
        context="独立新证", origin="test:1896-fresh", evidence=True,
    )
    db.create_secret_order(
        state, name, "并案新证", "另有一条",
        [], deadline_months=3,
        covert_task={
            "kind": "查核", "axes": ["既得利益"], "direction": 1,
            "investigation_target": target, "investigation_fact": str(fresh),
            "delivery": {
                "target_units": 1.0, "effect_sign": 1,
                "investigation_target": target, "investigation_fact": str(fresh),
            },
        },
    )
    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": oid, "fact_key": target, "effort": 0.0}])
    assert investigation_clue_records(db, did)[-1]["credited"] is True
    assert float(_lanes(db, oid)[str(fresh)]["effort"]) > 0.0

    # 指向不存在的罪 → 确定性丢弃，不造罪
    db.conn.execute(
        "UPDATE decree_dossiers SET payload_json=json_set(payload_json, "
        "'$.fact_lanes[0].mastered', 0) WHERE id=?",
        (did,),
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET payload_json=json_set(payload_json, "
        "'$.fact_lanes[0].effort', 0) WHERE id=?",
        (did,),
    )
    db.conn.commit()
    bogus = db.create_secret_order(
        state, name, "并案乱指", "指了一条不存在的罪",
        [], deadline_months=3,
        covert_task={
            "kind": "查核", "axes": ["既得利益"], "direction": 1,
            "investigation_target": target, "investigation_fact": "查无此证",
            "delivery": {
                "target_units": 1.0, "effect_sign": 1, "investigation_target": target,
                "investigation_fact": "查无此证",
            },
        },
    )
    assert bogus == oid
    _next_month(db, state)
    _run_supply_4a(db, state, [{"order_id": oid, "fact_key": target, "effort": 0.0}])
    assert investigation_clue_records(db, did)[-1]["dropped_fact_key"] == "查无此证"
    assert "查无此证" not in _lanes(db, oid)
    assert "查无此证" not in live_investigation_fact_keys(db, target)
    # 本月声明去查一条真相底没有的罪：不造罪，已有实投也不动。
    held_units = investigation_lane_actual_units(db, did)
    held_effort = {
        key: float(lane["effort"]) for key, lane in _lanes(db, oid).items()
    }
    _next_month(db, state)
    _run_supply_4a(db, state, [{
        "order_id": oid, "fact_key": "不存在的罪证键", "effort": 1.0,
    }])
    assert "不存在的罪证键" not in _lanes(db, oid)
    assert "不存在的罪证键" not in live_investigation_fact_keys(db, target)
    assert investigation_lane_actual_units(db, did) == held_units
    assert {
        key: float(lane["effort"]) for key, lane in _lanes(db, oid).items()
    } == held_effort

def test_supply_feed_identity_material_is_empty_for_topic_target(game):
    """#1896：查案对象不是真人物时，身份材料如实留空——不编造、不炸掉整月供料。"""
    from ming_sim.month_chain import build_secret_orders_supply_feed

    db, state, _ = game
    name = _minister(db)
    topic = "辽饷转运及押运相关人员"
    _issue(
        db, state, name, "查核题名", "查核题名",
        months=3, target=1, kind="查核", axes=["既得利益"],
        investigation_target=topic,
    )
    _next_month(db, state)
    feed = build_secret_orders_supply_feed(db, state, {})
    order = next(
        o for o in feed["active_secret_orders"]
        if o.get("investigation_target") == topic
    )
    assert order["investigation_facts"] == []
    assert order["investigation_target_identity_materials"] == {"name": topic}
    assert order["investigator_identity_materials"]["name"] == name

def test_supply_feed_carries_per_fact_investigation_materials(game):
    """#1896：4a 供料带逐证清单（键/难度/已投入/状态），模型才可能声明 fact_key。

    空 lane 集（清白目标）照发空清单——不因无证而拒开案。
    """
    from ming_sim.month_chain import build_secret_orders_supply_feed

    db, state, _ = game
    name = _minister(db)
    guilty = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    clean = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if not live_investigation_fact_keys(db, row["name"])
    )
    _set_axes(db, name, loyalty=90, identity=30)
    oid = _issue(
        db, state, name, "密查有罪者", "密查有罪者",
        months=3, target=1, kind="查核", axes=["既得利益"],
        investigation_target=guilty,
    )
    clean_oid = _issue(
        db, state, name, "密查清白者", "密查清白者",
        months=3, target=1, kind="查核", axes=["既得利益"],
        investigation_target=clean,
    )
    state.turn += 1
    db.save_state(state)

    feed = build_secret_orders_supply_feed(db, state, {})
    orders = {int(o["id"]): o for o in feed["active_secret_orders"]}
    assert oid in orders and clean_oid in orders
    hot = orders[oid]
    assert hot["investigation_target"] == guilty
    keys = [f["fact_key"] for f in hot["investigation_facts"]]
    assert keys == live_investigation_fact_keys(db, guilty)
    fact = hot["investigation_facts"][0]
    assert fact["state"] == "在查"
    assert fact["effort_so_far"] == 0.0
    assert fact["months_under_investigation"] == 0
    # 难度是引擎的账，不递给模型当答案
    assert "difficulty" not in fact
    # 清白目标：照开案、照列空清单
    assert orders[clean_oid]["investigation_facts"] == []

def test_spoliated_fact_reported_as_unreachable_in_feed(game):
    """#1896：被毁成 gone 的罪证在供料里标湮灭，难度不给数字（inf 不外泄）。"""
    from ming_sim.month_chain import build_secret_orders_supply_feed

    db, state, _ = game
    name = _minister(db)
    target = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND name<>? ORDER BY name",
            (name,),
        ).fetchall()
        if live_investigation_fact_keys(db, row["name"])
    )
    _set_axes(db, name, loyalty=90, identity=30)
    key = live_investigation_fact_keys(db, target)[0]
    informer = _relation_informer(db, name, target)
    spoiler = _issue(
        db, state, name, "先毁证", "先毁证",
        months=3, target=1, kind="查核", axes=["既得利益"],
        investigation_target=target,
    )
    spoiler_did = int(db.get_dossier_for_secret_order(spoiler)["id"])
    _declare_tip(db, state, spoiler, informer)
    apply_investigation_spoliation(
        db, target=target, fact_key=key, effect="gone",
        knowledge_source=informer, dossier_id=spoiler_did, commit=True,
    )
    untouched = next(
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
            "AND name NOT IN (?, ?) ORDER BY name",
            (name, target),
        ).fetchall()
    )
    db.conn.execute(
        "UPDATE characters SET seed_guilt=? WHERE name=?",
        (_structured_guilt(), untouched),
    )
    db.conn.execute("UPDATE characters SET ability=0 WHERE name=?", (name,))
    db.conn.commit()
    zero_oid = _issue(
        db, state, name, "零能力查未毁之罪", "零能力查未毁之罪",
        months=3, target=1, kind="查核", axes=["既得利益"],
        investigation_target=untouched,
    )
    oid = _issue(
        db, state, name, "密查被毁证者", "密查被毁证者",
        months=3, target=1, kind="查核", axes=["既得利益"],
        investigation_target=target,
    )
    _next_month(db, state)
    feed = build_secret_orders_supply_feed(db, state, {})
    order = next(o for o in feed["active_secret_orders"] if int(o["id"]) == oid)
    fact = next(f for f in order["investigation_facts"] if f["fact_key"] == key)
    assert fact["state"] == "已被毁证湮灭"
    assert "difficulty" not in fact  # 不把难度／inf 摆给模型
    # 能力为零把难度乘成 inf，不能因此把未毁的罪证说成已湮灭。
    zero_order = next(o for o in feed["active_secret_orders"] if int(o["id"]) == zero_oid)
    zero_fact = next(f for f in zero_order["investigation_facts"] if f["fact_key"] == untouched)
    assert zero_fact["state"] == "在查"
    assert db.list_investigation_spoiled_facts(untouched) == []

def test_closed_case_blocks_same_fact_on_later_case_and_due(game):
    """#1896：同一事实不重复查获——换案重查同一罪证不再计入本案查获。

    另一对象的案不受牵连（逐 lane 记账，不按人整体清零）。
    """
    db, state, _ = game
    name = _minister(db)
    target = db.conn.execute(
        "SELECT name FROM characters WHERE name<>? AND status='active' LIMIT 1",
        (name,),
    ).fetchone()["name"]
    other = db.conn.execute(
        "SELECT name FROM characters WHERE name NOT IN (?,?) AND status='active' LIMIT 1",
        (name, target),
    ).fetchone()["name"]
    _set_axes(db, name, loyalty=90, identity=30)
    db.conn.execute("UPDATE characters SET seed_guilt=? WHERE name=?", (_structured_guilt(), target))
    db.conn.execute("UPDATE characters SET seed_guilt=? WHERE name=?", (_structured_guilt(), other))
    db.conn.commit()
    oid = _issue(
        db, state, name, "查核辽饷侵冒", "查核辽饷侵冒",
        months=1, target=1, kind="查核辽饷侵冒", axes=["既得利益"],
        investigation_target=target,
    )
    state.turn += 1
    db.save_state(state)
    _dig_months(db, state, oid, target, months=2)
    assert investigation_lane_actual_units(
        db, int(db.get_dossier_for_secret_order(oid)["id"])
    ) == 1.0
    first = settle_due_secret_orders(db, state, commit=True)
    assert first and first[0]["status"] == "done"
    assert first[0]["target_units"] == 1.0
    assert db.get_secret_order(oid)["status"] == "done"

    oid2 = _issue(
        db, state, name, "再查同人", "再查同人",
        months=1, target=1, kind="查核辽饷侵冒", axes=["既得利益"],
        investigation_target=target,
    )
    did2 = int(db.get_dossier_for_secret_order(oid2)["id"])
    oid_other = _issue(
        db, state, name, "另一对象", "另一对象",
        months=1, target=1, kind="查核辽饷侵冒", axes=["既得利益"],
        investigation_target=other,
    )
    did_other = int(db.get_dossier_for_secret_order(oid_other)["id"])
    state.turn += 1
    db.save_state(state)
    _co_locate(db, name, target, other, place="京师")
    db.conn.execute(
        "UPDATE characters SET ability=60 WHERE name=?", (name,),
    )
    db.conn.execute(
        "UPDATE characters SET intrigue=50 WHERE name IN (?, ?)", (target, other),
    )
    db.conn.commit()
    apply_monthly_covert_actual_progress(
        db, state,
        selections=[
            {"order_id": oid2, "fact_key": target, "effort": 1.0},
            {"order_id": oid_other, "fact_key": other, "effort": 0.2},
        ],
        commit=True,
    )
    # 同一事实已被前案查获 → 本案投入确定性丢弃，不重复查获
    assert investigation_lane_actual_units(db, did2) == 0.0
    # 另一对象：实投 0.2，低于这条罪的难度，未查获
    assert investigation_lane_actual_units(db, did_other) == 0.0

    out = settle_due_secret_orders(db, state, commit=True)
    by_id = {r["order_id"]: r for r in out}
    assert by_id[oid2]["status"] == "failed"
    assert by_id[oid2]["actual_units"] == 0.0
    assert by_id[oid_other]["status"] == "failed"
    assert by_id[oid_other]["actual_units"] == 0.0

def test_fiscal_quantity_tracer_same_unit_done_and_gap(game):
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    oid = _issue(
        db, state, name, "补发五千", "补发饷银",
        months=1, target=20, kind="补发饷银", axes=["既得利益"], unit="万两",
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    state.turn += 1
    db.save_state(state)
    apply_score_extraction(
        db, state,
        {
            "economy_moves": [{
                "account": "内库",
                "delta": 9,
                "category": "抄没",
                "reason": "无关同案收入不得充交付",
                "origin_ref": f"dossier:{did}",
            }],
        },
        content=content,
    )
    _originate_work(db, state, content, did, delta=-20)
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "忠实"}], commit=True,
    )
    settle_due_secret_orders(db, state, commit=True)
    assert db.sum_dossier_actual_progress_units(did) == 20.0
    assert db.get_secret_order(oid)["status"] == "done"

    oid2 = _issue(
        db, state, name, "补发缺口", "补发饷银",
        months=1, target=20, kind="补发饷银", axes=["既得利益"], unit="万两",
    )
    did2 = int(db.get_dossier_for_secret_order(oid2)["id"])
    state.turn += 1
    db.save_state(state)
    _originate_work(db, state, content, did2, delta=-4)
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid2, "fidelity": "忠实"}], commit=True,
    )
    settle_due_secret_orders(db, state, commit=True)
    assert db.sum_dossier_actual_progress_units(did2) == 4.0
    assert db.get_secret_order(oid2)["status"] == "failed"

@pytest.mark.parametrize("mismatch", ["region", "field"])
def test_region_quantity_ignores_same_origin_turn_with_mismatched_identity(game, mismatch):
    db, state, _ = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    oid = _issue(db, state, name, "清丈河南", "清丈", months=1, target=1, unit="万亩")
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    state.turn += 1
    db.save_state(state)
    wrong = {
        "region": ("shandong", "registered_land", "520", "521"),
        "field": ("henan", "hidden_land", "420", "421"),
    }[mismatch]
    db.conn.execute(
        "INSERT INTO region_logs "
        "(turn, year, period, region_id, field, old_value, new_value, delta, reason, origin_ref) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 7, 'test', ?)",
        (state.turn, state.year, state.period, *wrong, f"dossier:{did}"),
    )
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "忠实"}], commit=True,
    )
    assert db.sum_dossier_actual_progress_units(did) == 0.0

def test_catch_quantity_tracer_same_unit_done_and_mismatch_ignored(game):
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    targets = _catch_names(db, name, n=3)
    oid = _issue(
        db, state, name, "缉获三人", "拿人犯",
        months=1, target=3, kind="缉获人犯", unit="人犯",
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    state.turn += 1
    db.save_state(state)
    _originate_work(db, state, content, did, delta=-9)
    db.conn.execute(
        "INSERT INTO person_logs "
        "(turn, year, period, person_name, action, origin_ref) VALUES (?, ?, ?, ?, ?, ?)",
        (state.turn, state.year, state.period, name, "任命", f"dossier:{did}"),
    )
    _originate_catches(db, state, content, did, targets)
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "忠实"}], commit=True,
    )
    assert db.sum_dossier_actual_progress_units(did) == 3.0
    out = settle_due_secret_orders(db, state, commit=True)
    row = next(r for r in out if r["order_id"] == oid)
    assert row["status"] == "done"
    assert row["actual_units"] == 3.0
    assert row["target_units"] == 3.0

def test_create_secret_order_rejects_missing_contract(game):
    db, state, _ = game
    name = _minister(db)
    with pytest.raises(CovertContractError):
        db.create_secret_order(
            state, name, "无合同密令", "无显式差务", [], deadline_months=1,
        )
    assert db.list_secret_orders() == []

def test_purpose_liaoxiang_canonicalizes_to_other_and_counts(game):
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    frozen = build_covert_task_contract(
        kind="核发辽饷", axes=["实务事功"], direction=1,
        delivery_unit="万两", delivery_target_units=3, effect_sign=-1,
        purpose="辽饷", category="密令差务", account="内库",
    )
    assert frozen["delivery"]["purpose"] == "其它"
    with pytest.raises(CovertContractError):
        build_covert_task_contract(
            kind="核发辽饷", axes=["实务事功"], direction=1,
            delivery_unit="万两", delivery_target_units=3,
            purpose="辽饷", category="密令差务", account="内库",
        )
    oid = db.create_secret_order(
        state, name, "核发辽饷", "核发辽饷", [],
        deadline_months=1, covert_task=frozen,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    contract = read_covert_task_contract(db.get_dossier_for_secret_order(oid))
    assert contract["delivery"]["purpose"] == "其它"
    state.turn += 1
    db.save_state(state)
    _originate_work(db, state, content, did, delta=-3)
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "忠实"}], commit=True,
    )
    settle_due_secret_orders(db, state, commit=True)
    assert db.sum_dossier_actual_progress_units(did) == 3.0
    assert db.get_secret_order(oid)["status"] == "done"

def test_region_monthly_progress_sums_increments_without_final_value_gate(game):
    db, state, _ = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    oid = _issue(db, state, name, "清丈河南", "清丈", months=2, target=5, unit="万亩")
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    state.turn += 1
    db.save_state(state)
    db.conn.execute(
        "INSERT INTO region_logs "
        "(turn, year, period, region_id, field, old_value, new_value, delta, reason, origin_ref) "
        "VALUES (?, ?, ?, 'henan', 'registered_land', '420', '422', 2, 'test', ?)",
        (state.turn, state.year, state.period, f"dossier:{did}"),
    )
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "忠实"}], commit=True,
    )
    assert db.sum_dossier_actual_progress_units(did) == 2.0
    state.turn += 1
    db.save_state(state)
    db.conn.execute(
        "INSERT INTO region_logs "
        "(turn, year, period, region_id, field, old_value, new_value, delta, reason, origin_ref) "
        "VALUES (?, ?, ?, 'henan', 'registered_land', '422', '425', 3, 'test', ?)",
        (state.turn, state.year, state.period, f"dossier:{did}"),
    )
    apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "忠实"}], commit=True,
    )
    assert db.sum_dossier_actual_progress_units(did) == 5.0
    out = settle_due_secret_orders(db, state, commit=True)
    row = next(r for r in out if r["order_id"] == oid)
    assert row["status"] == "done"

def test_positive_inflow_does_not_freeze_purpose_and_counts(game):
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    frozen = build_covert_task_contract(
        kind="抄家入帑", axes=["实务事功"], direction=1,
        delivery_unit="万两", delivery_target_units=1, effect_sign=1,
        purpose="其它", category="密令差务", account="内库",
    )
    assert "purpose" not in frozen["delivery"]
    with pytest.raises(CovertContractError):
        build_covert_task_contract(
            kind="抄家入帑", axes=["实务事功"], direction=1,
            delivery_unit="万两", delivery_target_units=1, effect_sign=1,
            purpose="补饷", category="密令差务", account="内库",
        )
    oid = db.create_secret_order(
        state, name, "抄家入帑", "入内库", [],
        deadline_months=1, covert_task=frozen,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    state.turn += 1
    db.save_state(state)
    _originate_work(db, state, content, did, delta=1)
    row = db.conn.execute(
        "SELECT purpose, delta FROM economy_ledger WHERE origin_ref=? ORDER BY id DESC LIMIT 1",
        (f"dossier:{did}",),
    ).fetchone()
    assert row is not None
    assert int(row["delta"]) == 1
    assert row["purpose"] in (None, "")
    out = apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "fidelity": "忠实"}], commit=True,
    )
    applied = next(r for r in out if r.get("order_id") == oid)
    assert applied.get("originated_quantity") == 1.0
    assert db.sum_dossier_actual_progress_units(did) == 1.0
    settled = settle_due_secret_orders(db, state, commit=True)
    row_s = next(r for r in settled if r["order_id"] == oid)
    assert row_s["status"] == "done"

def test_topic_investigation_backlash_fails_without_world_package(game):
    db, state, _ = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    topic = "辽饷转运及押运相关人员"
    oid = _issue(
        db, state, name, "查核辽饷侵冒、勿使杨嗣昌与闻", "查核辽饷侵冒、勿使杨嗣昌与闻",
        months=1, target=4, kind="查核辽饷侵冒", axes=["既得利益"],
        investigation_target=topic,
    )
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    before_loyalty = int(db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (name,)
    ).fetchone()["loyalty"])
    before_neiku = int(state.metrics.get("内库", 0))
    state.turn += 1
    db.save_state(state)
    out = apply_monthly_covert_actual_progress(
        db, state, selections=[{"order_id": oid, "effort": 1.0}], commit=True,
    )
    row = next(r for r in out if r["order_id"] == oid)
    assert row["units"] == 0.0
    assert row["effort_applied"] == 0.0  # 题名式对象无实有罪证 → 无从下手
    after_loyalty = int(db.conn.execute(
        "SELECT loyalty FROM characters WHERE name=?", (name,)
    ).fetchone()["loyalty"])
    assert after_loyalty == before_loyalty
    assert int(state.metrics.get("内库", 0)) == before_neiku
    assert db.list_economy_moves_for_dossier(did) == []
    db.conn.execute("UPDATE secret_orders SET due_turn=? WHERE id=?", (state.turn, oid))
    db.conn.commit()
    settled = settle_due_secret_orders(db, state, commit=True)
    close = next(r for r in settled if r["order_id"] == oid)
    assert close["status"] == "failed"
    assert close["actual_units"] == 0.0


def test_n_month_deadline_yields_exactly_n_ticks(game):
    """N 月期限恰 N 次实进度 tick（发令月排除）。"""
    db, state, content = game
    name = _minister(db)
    _set_axes(db, name, loyalty=90, identity=30)
    n = 3
    oid = _issue(db, state, name, "恰三月", "验窗口", months=n, target=n)
    issued = int(state.turn)
    did = int(db.get_dossier_for_secret_order(oid)["id"])
    out0 = apply_monthly_covert_actual_progress(
        db, state,
        selections=[{"order_id": oid, "fidelity": "忠实"}],
        commit=True,
    )
    assert not any(r.get("order_id") == oid and not r.get("skipped") and r.get("units") is not None
                   and not r.get("rejected") for r in out0 if r.get("order_id") == oid and "units" in r)
    assert db.sum_dossier_actual_progress_units(did) == 0.0

    ticks = 0
    for _ in range(n):
        state.turn += 1
        db.save_state(state)
        _originate_work(db, state, content, did)
        out = apply_monthly_covert_actual_progress(
            db, state,
            selections=[{"order_id": oid, "fidelity": "打折"}],
            commit=True,
        )
        row = next(r for r in out if r.get("order_id") == oid)
        assert row.get("units") == 0.5
        ticks += 1
    assert ticks == n
    assert len(db.list_dossier_actual_progress(did)) == n
    assert db.sum_dossier_actual_progress_units(did) == pytest.approx(0.5 * n)
    due = int(db.conn.execute(
        "SELECT due_turn FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()["due_turn"])
    assert due == issued + n
    assert state.turn == due


# --- #1897 HEAD duties kept ---

def test_create_secret_order_fact_lanes_follow_structured_severity_only(game):
    """#1897 R2：真实 create_secret_order 开案——只认 severity∈{轻,中,重}。

    说明散文、解析失败、非对象不得把目标名写入 live 实证集或案卷 fact_lanes。
    不测 helper 自洽；观测 create 后的结构化 truth_keys／lanes。
    """
    db, state, _ = game
    name = _minister(db)
    target = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND name<>? "
        "ORDER BY name LIMIT 1",
        (name,),
    ).fetchone()["name"]
    _set_axes(db, name, loyalty=90, identity=30)
    _clear_open_errands(db, name)

    cases = [
        ("", False),
        (json.dumps({"crime": "无", "severity": "无"}, ensure_ascii=False), False),
        (json.dumps({"crime": "查无实据", "severity": "无"}, ensure_ascii=False), False),
        (json.dumps({"crime": "血债累累", "severity": "无"}, ensure_ascii=False), False),
        ("血债", False),
        ("{not-json", False),
        (json.dumps(["not", "object"], ensure_ascii=False), False),
        (json.dumps({"crime": "交结近侍", "severity": "中"}, ensure_ascii=False), True),
    ]
    for seed, expect_seed_lane in cases:
        db.conn.execute(
            "UPDATE characters SET seed_guilt=? WHERE name=?", (seed, target),
        )
        db.conn.commit()
        assert (target in live_investigation_fact_keys(db, target)) is expect_seed_lane, seed
        oid = _issue(
            db, state, name, "验罪情入集", "结构化罪情契约",
            months=1, target=1, kind="查核", axes=["既得利益"],
            investigation_target=target,
        )
        lanes = _lanes(db, oid)
        assert (target in lanes) is expect_seed_lane, seed
        _retire_order(db, oid)


def test_create_secret_order_rejects_tags_without_explicit_fields(game):
    """生产闸：tags 不得代替显式 typed 字段（create 真入口）。"""
    db, state, _ = game
    name = _minister(db)
    with pytest.raises(CovertContractError):
        db.create_secret_order(
            state, name, "仅标签密令", "不得凭 tags 成案",
            ["辽饷", "兵部", "密查", "稽核"],
            deadline_months=1,
            covert_task={"tags": ["辽饷", "兵部", "密查", "稽核"]},
        )
    assert db.list_secret_orders() == []


@pytest.mark.parametrize(
    ("unit", "identity", "sign"),
    [
        ("万两", {"category": "密令差务", "account": "内库"}, -1),
        ("万两", {"purpose": "其它", "account": "内库"}, -1),
        ("万两", {"purpose": "其它", "category": "密令差务"}, -1),
        ("人犯", {}, 1),
        ("万亩", {"field": "registered_land", "target": "421"}, 1),
        ("万亩", {"region": "henan", "target": "421"}, 1),
        ("万亩", {"region": "henan", "field": "registered_land"}, 1),
    ],
)
def test_create_secret_order_rejects_incomplete_delivery_identity(
    game, unit, identity, sign,
):
    """生产闸：交付 identity 七参数缺失拒收（create→build_covert_task_contract）。"""
    db, state, _ = game
    name = _minister(db)
    with pytest.raises(CovertContractError):
        db.create_secret_order(
            state, name, "缺 identity", "结构化负向", [],
            deadline_months=1,
            covert_task={
                "kind": "差务",
                "axes": ["实务事功"],
                "direction": 1,
                "delivery_unit": unit,
                "delivery_target_units": 1,
                "effect_sign": sign,
                **identity,
            },
        )
    assert db.list_secret_orders() == []


def test_create_and_settle_reject_zero_target_not_delivered(game):
    """零目标不算交付：create 拒收；案卷若被置零，settle 读合同闸响亮失败，不静默 done。

    decide_secret_order_settlement 仅由 settle_due 在 require_covert_task_contract
    之后调用；coerce 已拒 qty<=0，故真入口覆盖 = create 拒 + settle 不结案。
    """
    db, state, _ = game
    name = _minister(db)
    with pytest.raises(CovertContractError):
        db.create_secret_order(
            state, name, "零目标密令", "不得成案", [],
            deadline_months=1,
            covert_task=_task(
                kind="查案", axes=["实务事功"], unit="万两", target=0,
            ),
        )
    assert db.list_secret_orders() == []

    oid = _issue(db, state, name, "零目标密令", "目标被置零", months=1, target=1)
    dossier = db.get_dossier_for_secret_order(oid)
    did = int(dossier["id"])
    payload = json.loads(str(dossier["payload_json"]))
    contract = dict(payload[CONTRACT_KEY])
    delivery = dict(contract["delivery"])
    delivery["target_units"] = 0.0
    contract["delivery"] = delivery
    payload[CONTRACT_KEY] = contract
    db.update_decree_dossier_payload(did, payload, commit=True)
    db.conn.execute(
        "UPDATE secret_orders SET due_turn=? WHERE id=?",
        (state.turn, oid),
    )
    db.conn.commit()
    with pytest.raises(CovertContractError):
        settle_due_secret_orders(db, state, commit=True)
    assert db.get_secret_order(oid)["status"] == "active"


def test_settle_due_close_follows_surviving_memorial_and_actual(game):
    """记进展与同月密奏是同一条奏报。结案取留下的结构化奏报，实况为零则不成。"""
    db, state, _ = game
    name = _minister(db)
    _set_axes(db, name, loyalty=20, identity=80)
    oid = _issue(db, state, name, "空转密查", "查无实据之案", months=1, target=1)
    dossier = db.get_dossier_for_secret_order(oid)
    did = int(dossier["id"])
    db.update_secret_order_progress(oid, "承办人已报进展时间线", year=state.year, period=state.period)
    assert str(db.get_secret_order(oid)["result"] or "") == ""
    db.record_dossier_progress(
        did, state.turn, "办成", "臣已查明全部", is_terminal=False,
    )
    open_reports = [row for row in db.list_dossier_progress(did) if not row["is_terminal"]]
    assert len(open_reports) == 1
    db.conn.execute(
        "UPDATE secret_orders SET due_turn=? WHERE id=?",
        (state.turn, oid),
    )
    db.conn.commit()

    out = settle_due_secret_orders(db, state, commit=True)
    row = next(r for r in out if r["order_id"] == oid)
    closed = db.get_secret_order(oid)
    assert row["status"] == "failed"
    assert row["actual_units"] == 0.0
    assert closed["status"] == "failed"
    surviving = [item for item in db.list_dossier_progress(did) if not item["is_terminal"]]
    assert len(surviving) == 1

