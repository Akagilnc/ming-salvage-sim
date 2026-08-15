"""#48/#883：密令状态承载归一，且公共 LLM 不预读密令。

根因：decree.py 把密令 DB 行（带英文 status=active/pending_review）整条塞进喂 simulator
的扁平 list，simulator 照抄进「密旨动向」邸报段 → 中文游戏里冒出「孙承宗密旨（active）」。

修法：decree.py 抽纯函数 group_secret_orders_for_sim(rows) 把行按状态分进中文键两组
（在办/待核议），条目剥掉英文 status。#883 再将该承载移出公共 simulator payload，
仅交给专用密令 extractor。

本档单测覆盖两层边界保证：
① 纯函数分组 + 剥 status + 字段保留 + done/failed 不进；
② 构建出的公共 payload 不含 secret_orders 或密令说明。
另含恢复端归一（旧 list 形状 ctx 重分组）与 resolve_context dict 往返。
两个 prompt（season_simulator.md 密旨动向段、score_extractor_personnel_secret.md 密令段）
的措辞改动 LLM 输出非确定不可单测，走 cross-model 评审。

#1185：group_* 中文桶盯文 → status→bucket 结构枚举与字段保留；隔离/恢复 keep 不动。
"""

from __future__ import annotations

# status → bucket 结构枚举（group_secret_orders_for_sim 契约）
_STATUS_TO_BUCKET = {"active": "在办", "pending_review": "待核议"}
_BUCKETS = tuple(_STATUS_TO_BUCKET.values())
_TERMINAL_STATUSES = frozenset({"done", "failed", "cancelled"})
_CARRY_FIELDS = frozenset({
    "id", "minister_name", "title", "content",
    "turn_issued", "due_turn", "progress", "sim_note",
})
_CONTENT_CAP = 120


def _row(oid, status, *, minister="孙承宗", title="查抄魏党", content="清查魏忠贤遗党赃私",
         turn_issued=1, due_turn=4, result="", sim_note=""):
    """复刻 db.list_secret_orders 返回的行形状（含英文 status）。"""
    return {
        "id": oid,
        "turn_issued": turn_issued,
        "due_turn": due_turn,
        "year_issued": 1628,
        "period_issued": 1,
        "minister_name": minister,
        "title": title,
        "content": content,
        "tags": [],
        "importance": 4,
        "status": status,
        "result": result,
        "sim_note": sim_note,
        "turn_closed": None,
    }


def test_group_buckets_by_status_into_cn_keys():
    from ming_sim.decree import group_secret_orders_for_sim

    rows = [
        _row(1, "active"),
        _row(2, "pending_review"),
        _row(3, "active"),
    ]
    grouped = group_secret_orders_for_sim(rows)

    # 结构枚举：输出键 = status→bucket 映射的值域
    assert set(grouped.keys()) == set(_BUCKETS)
    for status, bucket in _STATUS_TO_BUCKET.items():
        assert [o["id"] for o in grouped[bucket]] == [
            r["id"] for r in rows if r["status"] == status
        ]


def test_group_strips_english_status_field():
    from ming_sim.decree import group_secret_orders_for_sim

    grouped = group_secret_orders_for_sim([_row(1, "active"), _row(2, "pending_review")])

    for bucket in _BUCKETS:
        for entry in grouped[bucket]:
            assert "status" not in entry
            assert set(entry.keys()) <= _CARRY_FIELDS | {"id"}


def test_group_preserves_carry_fields_and_maps_progress():
    from ming_sim.decree import group_secret_orders_for_sim

    result_text, note_text = "已查两淮", "风声渐起"
    grouped = group_secret_orders_for_sim([
        _row(7, "active", minister="温体仁", title="密查盐课",
             turn_issued=3, due_turn=9, result=result_text, sim_note=note_text),
    ])
    bucket = _STATUS_TO_BUCKET["active"]
    entry = grouped[bucket][0]

    assert entry["id"] == 7
    assert entry["minister_name"] == "温体仁"
    assert entry["title"] == "密查盐课"
    assert entry["turn_issued"] == 3
    assert entry["due_turn"] == 9
    # result → progress 字段映射；sim_note 保留
    assert entry["progress"] == result_text
    assert entry["sim_note"] == note_text
    assert set(entry.keys()) == _CARRY_FIELDS
    assert "status" not in entry
    assert "result" not in entry
    assert "tags" not in entry


def test_group_truncates_content_to_120():
    from ming_sim.decree import group_secret_orders_for_sim

    long_content = "甲" * 300
    grouped = group_secret_orders_for_sim([_row(1, "active", content=long_content)])

    bucket = _STATUS_TO_BUCKET["active"]
    assert len(grouped[bucket][0]["content"]) == _CONTENT_CAP
    assert grouped[bucket][0]["content"] == long_content[:_CONTENT_CAP]


def test_group_drops_done_and_failed_orders():
    """done/failed 是裁决输出、无注入需求，落到分组函数时忽略，不进任何组。"""
    from ming_sim.decree import group_secret_orders_for_sim

    # 终态 status 不在 status→bucket 映射内
    for terminal in _TERMINAL_STATUSES:
        assert terminal not in _STATUS_TO_BUCKET

    rows = [
        _row(1, "active"),
        _row(2, "done"),
        _row(3, "failed"),
        _row(4, "cancelled"),
    ]
    grouped = group_secret_orders_for_sim(rows)

    assert set(grouped.keys()) == set(_BUCKETS)
    active_ids = {r["id"] for r in rows if r["status"] in _STATUS_TO_BUCKET}
    dropped_ids = {r["id"] for r in rows if r["status"] in _TERMINAL_STATUSES}
    carried = {o["id"] for bucket in _BUCKETS for o in grouped[bucket]}
    assert carried == active_ids
    assert carried.isdisjoint(dropped_ids)
    assert grouped[_STATUS_TO_BUCKET["pending_review"]] == []


def test_group_empty_input_returns_both_empty_groups():
    from ming_sim.decree import group_secret_orders_for_sim

    grouped = group_secret_orders_for_sim([])
    assert set(grouped.keys()) == set(_BUCKETS)
    assert all(grouped[bucket] == [] for bucket in _BUCKETS)


def test_group_hardens_against_malformed_input():
    """恢复路可能喂进损坏存档（非 list / 含非 dict 元素）——照 simulation._clean_* 的守门惯例
    不得崩：非 list 返回空两组，非 dict 元素跳过。"""
    from ming_sim.decree import group_secret_orders_for_sim

    empty = {bucket: [] for bucket in _BUCKETS}
    for bad in (None, "junk", 123, {"在办": []}):
        assert group_secret_orders_for_sim(bad) == empty

    grouped = group_secret_orders_for_sim([
        None, 5, "x",  # 非 dict 元素，跳过
        {"id": 1, "minister_name": "甲", "title": "t", "content": "c", "status": "active",
         "turn_issued": 1, "due_turn": 4, "result": "", "sim_note": ""},
    ])
    assert [o["id"] for o in grouped[_STATUS_TO_BUCKET["active"]]] == [1]

    # 字符串字段非字符串（损坏存档）：str() 兜底，不在 content 切片处 TypeError
    bad = group_secret_orders_for_sim([
        {"id": 7, "minister_name": 999, "title": None, "content": 12345,
         "status": "pending_review"},
    ])[_STATUS_TO_BUCKET["pending_review"]][0]
    assert bad["content"] == "12345"
    assert bad["minister_name"] == "999"
    assert isinstance(bad["title"], str)
    assert set(bad.keys()) == _CARRY_FIELDS


def test_simulator_payload_never_contains_secret_orders(game):
    """契约钉 #883：月末邸报判官的公共输入不预读任何密令。"""
    from ming_sim.decree import group_secret_orders_for_sim
    from ming_sim.simulation import build_simulator_payload

    db, state, _ = game
    oid_active = db.create_secret_order(
        state, "孙承宗", "查抄魏党", "清查魏忠贤遗党赃私" * 30, tags=[], importance=4)
    oid_review = db.create_secret_order(
        state, "温体仁", "密查盐课", "暗查两淮盐商通敌", tags=[], importance=4)
    db.conn.execute("UPDATE secret_orders SET status='pending_review' WHERE id=?", (oid_review,))
    db.conn.commit()

    grouped = group_secret_orders_for_sim(
        db.list_secret_orders(status="active")
        + db.list_secret_orders(status="pending_review")
    )
    payload = build_simulator_payload(state, db, "诏书正文", "", secret_orders=grouped)

    assert oid_active and oid_review  # setup covers both active order states.
    assert "secret_orders" not in payload
    assert "密令" not in payload["data_note"]


def test_build_simulator_payload_omits_secret_orders_when_none_are_present(read_game):
    """契约钉 #883：空盘面也不保留公共密令字段这个旁路。"""
    from ming_sim.simulation import build_simulator_payload

    db, state, _ = read_game
    payload = build_simulator_payload(state, db, "", "")
    assert "secret_orders" not in payload


def test_group_reads_progress_from_legacy_progress_key():
    """分组函数能消化『旧档承载条目』——其进度存在 `progress` 键（非 DB 行的 `result`）。

    恢复路归一旧 list 形状 ctx 时复用本函数；旧条目用 progress、新 DB 行用 result，
    两者都要落进 grouped 条目的 progress（#48 恢复端闭环）。"""
    from ming_sim.decree import group_secret_orders_for_sim

    legacy_progress = "已办到南京"
    legacy_entry = {
        "id": 5, "minister_name": "甲", "title": "t", "content": "c",
        "status": "active", "turn_issued": 1, "due_turn": 4,
        "progress": legacy_progress, "sim_note": "风声",  # 旧承载键：progress / sim_note，无 result
    }
    grouped = group_secret_orders_for_sim([legacy_entry])
    entry = grouped[_STATUS_TO_BUCKET["active"]][0]
    assert entry["progress"] == legacy_progress
    assert "status" not in entry
    assert set(entry.keys()) == _CARRY_FIELDS


def test_recovered_grouped_normalizes_legacy_list():
    """_recovered_grouped：新档 dict 原样透传；旧档 list 形状归一成分组 dict（剥 status）；杂值 → {}。"""
    from ming_sim.decree import _recovered_grouped, group_secret_orders_for_sim

    already = {"在办": [{"id": 1}], "待核议": []}
    assert _recovered_grouped(already) is already  # dict 原样

    legacy_list = [
        {"id": 1, "minister_name": "甲", "title": "t", "content": "c",
         "status": "active", "turn_issued": 1, "due_turn": 4, "progress": "p", "sim_note": ""},
        {"id": 2, "minister_name": "乙", "title": "u", "content": "d",
         "status": "pending_review", "turn_issued": 1, "due_turn": 3, "progress": "", "sim_note": ""},
    ]
    out = _recovered_grouped(legacy_list)
    assert set(out.keys()) == {"在办", "待核议"}
    assert [o["id"] for o in out["在办"]] == [1]
    assert [o["id"] for o in out["待核议"]] == [2]
    for entry in out["在办"] + out["待核议"]:
        assert "status" not in entry  # 旧档英文 status 在归一时剥掉

    assert _recovered_grouped(None) == {}
    assert _recovered_grouped("junk") == {}


def test_resolve_context_roundtrips_grouped_secret_orders_as_dict(game):
    """save→get resolve_context 保持分组 dict 形状（非空与空分组都不退成 list）。"""
    db, state, _ = game
    grouped = {
        "在办": [{"id": 1, "minister_name": "甲", "title": "t", "content": "c",
                  "turn_issued": 1, "due_turn": 4, "progress": "", "sim_note": ""}],
        "待核议": [],
    }
    db.save_resolve_context(state.turn, "诏", "邸报", {"secret_orders": grouped},
                            secret_orders=grouped, relevant_memories=[])
    ctx = db.get_resolve_context(state.turn)
    assert isinstance(ctx["secret_orders"], dict)
    assert set(ctx["secret_orders"].keys()) == {"在办", "待核议"}

    # 空分组 dict 也按 dict 存（不被 `or []` 退成 list）——契约与新 Dict 注解一致。
    db.save_resolve_context(state.turn, "诏", "邸报", {}, secret_orders={}, relevant_memories=[])
    assert db.get_resolve_context(state.turn)["secret_orders"] == {}
