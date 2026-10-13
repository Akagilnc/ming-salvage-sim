from __future__ import annotations
from ming_sim.settlement.dossier import apply_dossier_promulgation
from ming_sim.db import GameDB
from ming_sim.supervision import (
    ORIGIN_MARK_DENUNCIATION_FALSE,
    ORIGIN_MARK_DENUNCIATION_TRUE,
    faction_relation,
    origin_has_mark,
)
from tests.test_dossier_reported_progress_619 import _world_fingerprint
from tests.dossier_test_helpers import create_test_secret_order
"""#627 政敌检举轨——真伪底与带私货审计（ID-12，r4 宪法版）。

引擎三职：供事实（注入既有叙事 LLM 步）/ 承接落库（clamp）/ 真伪底派生。
禁：烈度门/quota/文字模板（P6/P7）。

Seams:
- supervision.is_reported_actual_fork（fork 判据单源）
- GameDB.read_dossier_fork_state / build_faction_denunciation_facts
- GameDB.accept_faction_denunciations（结构化承接）
- compose_denunciation_origin + derive_denunciation_is_true
"""




# ── helpers ───────────────────────────────────────────────────────

def _chars_by_faction(db) -> dict[str, list]:
    rows = db.conn.execute(
        "SELECT name, faction FROM characters "
        "WHERE status='active' AND COALESCE(faction,'') NOT IN "
        "('','流寇','后金','宗室','嫔妃','宠妃','中宫','蒙古','朝鲜') "
        "ORDER BY name"
    ).fetchall()
    by_f: dict[str, list] = {}
    for row in rows:
        by_f.setdefault(str(row["faction"]), []).append(row)
    return by_f

def _pair_enemy(db):
    by_f = _chars_by_faction(db)
    facs = [f for f, rs in by_f.items() if rs]
    assert len(facs) >= 2
    # 找确为 enemy 的两派
    for i, fa in enumerate(facs):
        for fb in facs[i + 1:]:
            if faction_relation(fa, fb) == "enemy":
                return by_f[fa][0], by_f[fb][0]
    return by_f[facs[0]][0], by_f[facs[1]][0]

def _enemy_accuser(db, subject_faction: str) -> str:
    by_f = _chars_by_faction(db)
    for fac, rows in by_f.items():
        if faction_relation(fac, subject_faction) == "enemy" and rows:
            return str(rows[0]["name"])
    raise AssertionError("无敌对派系在朝人物")

def _subject_dossier(db, state, *, owner: str, token: str = "subj"):
    did = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"清丈{token}",
        target_kind="issue",
        target_id=f"land-{token}",
        executor_kind="character",
        executor_id=owner,
        participants=[{"character_id": owner, "tier": "主办"}],
    )
    apply_dossier_promulgation(db, state, did, "promulgated")
    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing' WHERE id=?", (did,),
    )
    db.conn.commit()
    return did

def _make_forked(db, state, dossier_id: int, *, token: str = "fork"):
    """奏报 + 旨外实况 → fork 单源读端为真。"""
    db.dossiers.record_dossier_progress(
        dossier_id, state.turn, "已竣", f"奏称{token}已完",
        is_terminal=False, commit=True,
    )
    db.record_issue_economy_move(
        state, "国库", 5, "浮收", "借旨行私",
        origin_ref=f"dossier:{dossier_id}", beyond_intent=True, commit=True,
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET execution_outcome='transformed' WHERE id=?",
        (dossier_id,),
    )
    db.conn.commit()

def test_world_materials_exclude_secret_fork_from_gazette(game, tmp_path, monkeypatch):
    """公开材料只列入有奏报且与旨外或执行格分叉的案；密令案与未分叉案不入。"""
    from ming_sim.materials import prepare_world_materials

    db, state, content = game
    owner = next(iter(_chars_by_faction(db).values()))[0]["name"]

    def _report(dossier_id: int, token: str) -> None:
        db.dossiers.record_dossier_progress(
            dossier_id, state.turn, "已竣", f"奏称{token}已完",
            is_terminal=False, commit=True,
        )

    def _beyond(dossier_id: int, token: str) -> None:
        db.record_issue_economy_move(
            state, "国库", 5, "浮收", f"借旨行私{token}",
            origin_ref=f"dossier:{dossier_id}", beyond_intent=True, commit=True,
        )

    def _outcome(dossier_id: int, outcome: str) -> None:
        db.conn.execute(
            "UPDATE decree_dossiers SET execution_outcome=? WHERE id=?",
            (outcome, dossier_id),
        )
        db.conn.commit()

    beyond_executing = _subject_dossier(db, state, owner=owner, token="beyond-exec")
    _report(beyond_executing, "beyond-exec")
    _beyond(beyond_executing, "beyond-exec")
    _outcome(beyond_executing, "executing")

    report_transformed = _subject_dossier(db, state, owner=owner, token="report-xf")
    _report(report_transformed, "report-xf")
    _outcome(report_transformed, "transformed")

    report_fulfilled = _subject_dossier(db, state, owner=owner, token="report-ok")
    _report(report_fulfilled, "report-ok")
    _outcome(report_fulfilled, "fulfilled")

    silent_beyond = _subject_dossier(db, state, owner=owner, token="silent")
    _beyond(silent_beyond, "silent")
    _outcome(silent_beyond, "transformed")

    order_id = create_test_secret_order(db, state, owner, "密查", "查账", [])
    secret_id = int(db.dossiers.get_for_secret_order(order_id)["id"])
    db.conn.execute("UPDATE decree_dossiers SET status='executing' WHERE id=?", (secret_id,))
    db.conn.commit()
    _make_forked(db, state, secret_id)

    import ming_sim.materials as materials
    captured = {}
    write_world = materials._write_world_tree

    def record_world(*args, **kwargs):
        captured.update(args[7])
        return write_world(*args, **kwargs)

    monkeypatch.setattr(materials, "_write_world_tree", record_world)
    prepared = prepare_world_materials(
        db, state, dest_root=tmp_path / "gazette",
        exclude_secret_order_dossiers=True,
    )
    facts = captured["denunciation"]
    assert (prepared.root / "盘面/派系检举事实.txt").is_file()
    assert {item["dossier_id"] for item in facts["forked_dossiers"]} == {
        beyond_executing,
        report_transformed,
    }

def _make_transformed_no_fork(db, state, dossier_id: int):
    """变形但无奏报分叉（无私货/无旨外）——fork 读端为假。"""
    db.conn.execute(
        "UPDATE decree_dossiers SET execution_outcome='transformed' WHERE id=?",
        (dossier_id,),
    )
    db.conn.commit()

def _escalate_fork(db, state, dossier_id: int, *, token: str = "esc"):
    """案情升级：再落一笔旨外恶果（actual_effect_count↑）。"""
    db.record_issue_economy_move(
        state, "国库", 3, "再浮收", f"升级{token}",
        origin_ref=f"dossier:{dossier_id}", beyond_intent=True, commit=True,
    )




def _scripted_entry(
    *,
    accuser: str,
    subject: str,
    dossier_id: int,
    body: str = "臣闻承办清丈有异状，请按问。",
) -> dict:
    return {
        "accuser_name": accuser,
        "subject_name": subject,
        "target_dossier_id": dossier_id,
        "memorial_text": body,
    }

# ── AC2 承接与 clamp ──────────────────────────────────────────────

def test_ac2_scripted_accept_and_clamp(game):
    db, state, _content = game
    subject, _ = _pair_enemy(db)
    subject_name = str(subject["name"])
    subject_faction = str(subject["faction"])
    accuser = _enemy_accuser(db, subject_faction)

    did = _subject_dossier(db, state, owner=subject_name, token="acc")
    _make_forked(db, state, did, token="acc")

    body = f"{accuser}奏：{subject_name}清丈有私，请皇上按问。"
    res = db.accept_faction_denunciations(
        state,
        [_scripted_entry(
            accuser=accuser, subject=subject_name, dossier_id=did, body=body,
        )],
        commit=True,
    )
    hits = res.applied
    assert len(hits) == 1
    hit = hits[0]
    assert hit["accuser_name"] == accuser
    assert int(hit["target_dossier_id"]) == did
    assert hit["memorial_text"] == body
    assert origin_has_mark(hit["origin"], ORIGIN_MARK_DENUNCIATION_TRUE)

    rows = db.dossiers.denunciations(turn=state.turn, target_dossier_id=did)
    assert len(rows) == 1
    assert rows[0]["memorial_text"] == body

    # 所指案卷不存在 → 拒
    missing = db.accept_faction_denunciations(
        state,
        [_scripted_entry(
            accuser=accuser, subject=subject_name, dossier_id=9_999_999,
        )],
        commit=True,
    )
    assert missing.applied == []
    assert len(missing.rejected) == 1

    # 检举人不在场 → 拒
    ghost = db.accept_faction_denunciations(
        state,
        [_scripted_entry(
            accuser="不存在之人甲乙丙", subject=subject_name, dossier_id=did,
        )],
        commit=True,
    )
    assert ghost.applied == []
    assert len(ghost.rejected) == 1

# ── AC3 真伪底派生 ────────────────────────────────────────────────

def test_ac3_veracity_true_and_false_from_fork(game):
    db, state, _content = game
    subject, _ = _pair_enemy(db)
    subject_name = str(subject["name"])
    subject_faction = str(subject["faction"])
    accuser = _enemy_accuser(db, subject_faction)

    did_true = _subject_dossier(db, state, owner=subject_name, token="vt")
    _make_forked(db, state, did_true, token="vt")
    assert db.read_dossier_fork_state(did_true)["fork"] is True

    did_false = _subject_dossier(db, state, owner=subject_name, token="vf")
    _make_transformed_no_fork(db, state, did_false)
    assert db.read_dossier_fork_state(did_false)["fork"] is False

    hits = db.accept_faction_denunciations(
        state,
        [
            _scripted_entry(
                accuser=accuser, subject=subject_name, dossier_id=did_true,
            ),
            _scripted_entry(
                accuser=accuser, subject=subject_name, dossier_id=did_false,
            ),
        ],
        commit=True,
    ).applied
    by_did = {int(h["target_dossier_id"]): h for h in hits}
    assert origin_has_mark(by_did[did_true]["origin"], ORIGIN_MARK_DENUNCIATION_TRUE)
    assert by_did[did_true]["is_true"] is True
    assert by_did[did_true]["payload"].get("fork") is True
    assert "fork_exposure" in by_did[did_true]["payload"]

    assert origin_has_mark(by_did[did_false]["origin"], ORIGIN_MARK_DENUNCIATION_FALSE)
    assert by_did[did_false]["is_true"] is False
    assert "fork_exposure" not in by_did[did_false]["payload"]

# ── AC4 重复语义三断言 + restore ──────────────────────────────────

def test_ac4_dedup_upgrade_closed_and_restore(game, tmp_path, content):
    db, state, _content = game
    subject, _ = _pair_enemy(db)
    subject_name = str(subject["name"])
    subject_faction = str(subject["faction"])
    accuser = _enemy_accuser(db, subject_faction)

    did = _subject_dossier(db, state, owner=subject_name, token="dedup")
    _make_forked(db, state, did, token="dedup")
    entry = _scripted_entry(
        accuser=accuser, subject=subject_name, dossier_id=did,
    )

    first = db.accept_faction_denunciations(state, [entry], commit=True).applied
    assert len(first) == 1

    # 同 turn 同键二次拒（去重由承接查询单源，非 UNIQUE）
    same_turn_dup = db.accept_faction_denunciations(state, [entry], commit=True).applied
    assert same_turn_dup == []
    assert len(db.dossiers.denunciations(target_dossier_id=did)) == 1

    # 同 turn 案情升级可再落（禁 UNIQUE(turn,...)：否则 IntegrityError）
    _escalate_fork(db, state, did, token="same-turn")
    same_turn_up = db.accept_faction_denunciations(
        state,
        [_scripted_entry(
            accuser=accuser, subject=subject_name, dossier_id=did,
        )],
        commit=True,
    ).applied
    assert len(same_turn_up) == 1
    assert len(db.dossiers.denunciations(target_dossier_id=did)) == 2

    # 同人同案同真伪类跨 turn 亦拒（去重键不含 turn）
    state.turn = int(state.turn) + 1
    db.reign.save_game_state(state)
    second = db.accept_faction_denunciations(state, [entry], commit=True).applied
    assert second == []
    assert len(db.dossiers.denunciations(target_dossier_id=did)) == 2

    # 跨 turn 案情再升级可再落
    _escalate_fork(db, state, did, token="up")
    upgraded = db.accept_faction_denunciations(
        state,
        [_scripted_entry(
            accuser=accuser, subject=subject_name, dossier_id=did,
        )],
        commit=True,
    ).applied
    assert len(upgraded) == 1
    assert len(db.dossiers.denunciations(target_dossier_id=did)) == 3

    # closed 案卷拒
    did_closed = _subject_dossier(db, state, owner=subject_name, token="cls")
    _make_forked(db, state, did_closed, token="cls")
    db.conn.execute(
        "UPDATE decree_dossiers SET status='closed' WHERE id=?", (did_closed,),
    )
    db.conn.commit()
    closed_res = db.accept_faction_denunciations(
        state,
        [_scripted_entry(
            accuser=accuser, subject=subject_name, dossier_id=did_closed,
        )],
        commit=True,
    )
    assert closed_res.applied == []
    assert len(closed_res.rejected) == 1

    # restore 无损接续
    expected = db.dossiers.denunciations()
    backup = tmp_path / "restore-627.db"
    db.backup_to(str(backup))
    db.conn.close()

    restored = GameDB(str(backup), content=content)
    try:
        got = restored.dossiers.denunciations()
        assert got == expected
        # restore 后同键重跑不双计
        again = restored.accept_faction_denunciations(
            state,
            [_scripted_entry(
                accuser=accuser, subject=subject_name, dossier_id=did,
            )],
            commit=True,
        ).applied
        assert again == []
        assert restored.dossiers.denunciations() == expected
    finally:
        restored.conn.close()

# ── AC5 零模板 + 暴露载体 ────────────────────────────────────────

def test_ac5_zero_template_exposure_and_622(game):
    db, state, _content = game
    subject, _ = _pair_enemy(db)
    subject_name = str(subject["name"])
    subject_faction = str(subject["faction"])
    accuser = _enemy_accuser(db, subject_faction)

    did = _subject_dossier(db, state, owner=subject_name, token="ban")
    _make_forked(db, state, did, token="ban")

    fp_before = _world_fingerprint(db)
    loophole_before = db.dossiers.exposure_rows(did)
    knowledge_n_before = db.conn.execute(
        "SELECT COUNT(*) AS n FROM character_knowledge_events"
    ).fetchone()["n"]
    inv_before = db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers "
        "WHERE action_type IN ('investigation','密查','查访')"
    ).fetchone()["n"]
    dossier_n_before = db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers"
    ).fetchone()["n"]

    body = f"{accuser}疏称{subject_name}清丈借旨行私，请按问以肃官箴。"
    hits = db.accept_faction_denunciations(
        state,
        [_scripted_entry(
            accuser=accuser, subject=subject_name, dossier_id=did, body=body,
        )],
        commit=True,
    ).applied
    assert hits
    for h in hits:
        # 正文即 LLM/scripted 原文，非引擎模板壳
        assert h["memorial_text"] == body

    # 暴露落条目自身，不写 loophole、不回注知识轨、不改世界状态
    assert hits[0]["payload"].get("fork_exposure", {}).get("fork") is True
    assert db.dossiers.exposure_rows(did) == loophole_before
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM character_knowledge_events"
    ).fetchone()["n"] == knowledge_n_before
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers "
        "WHERE action_type IN ('investigation','密查','查访')"
    ).fetchone()["n"] == inv_before
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers"
    ).fetchone()["n"] == dossier_n_before
    assert _world_fingerprint(db) == fp_before

    # 知识轨没有新增条目（由上面的结构化计数证明）。

    # 引擎侧零模板句：产出路径无固定文案常量（正则扫生产源码＝盯文，
    # 已在 #1901 J3 整类删除；P7 的真实闸案在呈现层 LLM 产出不可篡改）

    # #622 读端改调 public fork 单源
    actor = subject_name
    audit_order = create_test_secret_order(db,
        state, actor, "密查清丈", "逐月密奏", ["稽核"], deadline_months=4,
    )
    audit_dossier = int(db.dossiers.get_for_secret_order(audit_order)["id"])
    db.dossiers.add_links(
        audit_dossier,
        [{"target_dossier_id": did, "relation_type": "稽核", "note": "密查"}],
    )
    nudges = db.list_monthly_dossier_progress_nudges()
    audit_nudge = next(n for n in nudges if int(n["dossier_id"]) == audit_dossier)
    signals = audit_nudge["audit_fork_signals"]
    hit = next(s for s in signals if int(s["target_dossier_id"]) == did)
    assert hit["fork"] is True
    assert hit["fork"] == db.read_dossier_fork_state(did)["fork"]


def test_k9_accept_faction_denunciations_bad_items_and_containers_refused(game):
    """K9: 所有原先静默跳过的检举坏项均结构化拒收留痕，合法兄弟条目正常落账；非 list 容器经分派形状拒收。"""
    from ming_sim.applier import Provenance
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, _ = game
    accuser, inactive = [row["name"] for row in db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 2"
    )]
    db.conn.execute("UPDATE characters SET status='dead' WHERE name=?", (inactive,))
    did_open = db.create_decree_dossier(
        state, action_type="policy", decree_text="在途案卷",
        target_kind="issue", target_id="1", payload={},
    )
    did_closed = db.create_decree_dossier(
        state, action_type="policy", decree_text="已结案卷",
        target_kind="issue", target_id="1", payload={},
    )
    db.conn.execute("UPDATE decree_dossiers SET status='closed' WHERE id=?", (did_closed,))
    db.conn.commit()

    bad_items = [
        "not_a_dict",
        {"memorial_text": "缺检举人", "target_dossier_id": did_open},
        {"accuser_name": accuser, "target_dossier_id": did_open},
        {"accuser_name": accuser, "memorial_text": "零ID", "target_dossier_id": 0},
        {"accuser_name": accuser, "memorial_text": "字串ID", "target_dossier_id": "not_an_int"},
        {"accuser_name": inactive, "memorial_text": "检举人已退场", "target_dossier_id": did_open},
        {"accuser_name": "ghost_accuser", "memorial_text": "查无此人", "target_dossier_id": did_open},
        {"accuser_name": accuser, "memorial_text": "查无案卷", "target_dossier_id": 999999},
        {"accuser_name": accuser, "memorial_text": "闭卷检举", "target_dossier_id": did_closed},
    ]
    good_item = {"accuser_name": accuser, "memorial_text": "证据确凿", "target_dossier_id": did_open}

    dispatch_declaration(
        db, state,
        {"effects": [{"faction_denunciations": [*bad_items, good_item]}]},
        source=Provenance.system_simulation,
        defer_disclosure=True,
    )
    # 合法 sibling 存活落库
    assert db.conn.execute(
        "SELECT COUNT(*) FROM faction_denunciations WHERE target_dossier_id=?", (did_open,)
    ).fetchone()[0] == 1
    # 坏项全部持久化拒收留痕
    rejections = db.conn.execute(
        "SELECT category FROM rejection_reports WHERE section='faction_denunciations' ORDER BY id"
    ).fetchall()
    assert [r["category"] for r in rejections] == [
        "invalid_shape", "invalid_shape", "invalid_shape", "invalid_shape",
        "invalid_shape",
        "missing_ref", "missing_ref", "missing_ref", "invalid_status",
    ]

    # 非 list 容器通过既有 dispatch 形状拒收
    dispatch_declaration(
        db, state,
        {"effects": [{"faction_denunciations": "not_a_list"}]},
        source=Provenance.system_simulation,
        defer_disclosure=True,
    )
    non_list_count = db.conn.execute(
        "SELECT COUNT(*) FROM rejection_reports WHERE section='faction_denunciations' AND category='invalid_shape'"
    ).fetchone()[0]
    assert non_list_count == 6

    # K9: 密令选态坏编号与未知编号逐项拒收，合法兄弟项正常落账
    order_id = create_test_secret_order(
        db, state, accuser, "密查清丈", "逐月密奏", ["稽核"], deadline_months=4,
    )
    db.conn.execute("UPDATE secret_orders SET turn_issued=? WHERE id=?", (state.turn - 1, order_id))
    db.conn.commit()

    dispatch_declaration(
        db, state,
        {"effects": [{
            "covert_exec_selections": [
                {"order_id": "not_an_id", "fidelity": "忠实"},
                {"order_id": 999999, "fidelity": "忠实"},
                {"order_id": order_id, "fidelity": "忠实"},
            ],
        }]},
        source=Provenance.system_simulation,
        defer_disclosure=False,
    )
    secret_rejections = db.conn.execute(
        "SELECT category FROM rejection_reports WHERE section='covert_exec_selections' ORDER BY id"
    ).fetchall()
    assert [r["category"] for r in secret_rejections] == ["invalid_shape", "missing_ref"]
    assert db.conn.execute(
        "SELECT COUNT(*) FROM dossier_actual_progress WHERE fidelity_state='忠实'"
    ).fetchone()[0] == 1
