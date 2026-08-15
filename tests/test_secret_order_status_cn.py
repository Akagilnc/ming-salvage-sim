"""#48：密令状态承载归一（group_secret_orders_for_sim 纯函数 + 恢复端）。

根因：decree.py 把密令 DB 行（带英文 status=active/pending_review）整条塞进喂 simulator
的扁平 list，simulator 照抄进「密旨动向」邸报段 → 中文游戏里冒出「孙承宗密旨（active）」。

修法：decree.py 抽纯函数 group_secret_orders_for_sim(rows) 把行按状态分进中文键两组
（在办/待核议），条目剥掉英文 status。

#1185 合并：公共 LLM 不预读密令的隔离面迁 test_secret_order_isolation_883.py
（test_883_public_llm_contexts_never_preload_secret_orders）。本档只留 group 纯函数
与恢复/resolve_context 形状契约。
"""

from __future__ import annotations


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

    grouped = group_secret_orders_for_sim([
        _row(1, "active"),
        _row(2, "pending_review"),
        _row(3, "active"),
    ])

    # 结构键契约（分组 API 真源），非展示串盯文
    assert set(grouped.keys()) == {"在办", "待核议"}
    assert [o["id"] for o in grouped["在办"]] == [1, 3]
    assert [o["id"] for o in grouped["待核议"]] == [2]


def test_group_strips_english_status_field():
    from ming_sim.decree import group_secret_orders_for_sim

    grouped = group_secret_orders_for_sim([_row(1, "active"), _row(2, "pending_review")])

    for entry in grouped["在办"] + grouped["待核议"]:
        assert "status" not in entry, "条目不得保留英文 status 字段"


def test_group_preserves_carry_fields_and_maps_progress():
    from ming_sim.decree import group_secret_orders_for_sim

    grouped = group_secret_orders_for_sim([
        _row(7, "active", minister="温体仁", title="密查盐课",
             turn_issued=3, due_turn=9, result="已查两淮", sim_note="风声渐起"),
    ])
    entry = grouped["在办"][0]

    assert entry["id"] == 7
    assert entry["minister_name"] == "温体仁"
    assert entry["title"] == "密查盐课"
    assert entry["turn_issued"] == 3
    assert entry["due_turn"] == 9
    assert entry["progress"] == "已查两淮"
    assert entry["sim_note"] == "风声渐起"
    assert set(entry.keys()) == {
        "id", "minister_name", "title", "content",
        "turn_issued", "due_turn", "progress", "sim_note",
    }


def test_group_truncates_content_to_120():
    from ming_sim.decree import group_secret_orders_for_sim

    long_content = "甲" * 300
    grouped = group_secret_orders_for_sim([_row(1, "active", content=long_content)])

    assert len(grouped["在办"][0]["content"]) == 120
    assert grouped["在办"][0]["content"] == long_content[:120]


def test_group_drops_done_and_failed_orders():
    """done/failed 是裁决输出、无注入需求，落到分组函数时忽略。"""
    from ming_sim.decree import group_secret_orders_for_sim

    grouped = group_secret_orders_for_sim([
        _row(1, "active"),
        _row(2, "done"),
        _row(3, "failed"),
        _row(4, "cancelled"),
    ])

    assert [o["id"] for o in grouped["在办"]] == [1]
    assert grouped["待核议"] == []
    assert {o["id"] for bucket in grouped.values() for o in bucket} == {1}


def test_group_empty_input_returns_both_empty_groups():
    from ming_sim.decree import group_secret_orders_for_sim

    grouped = group_secret_orders_for_sim([])
    assert grouped == {"在办": [], "待核议": []}


def test_group_hardens_against_malformed_input():
    """恢复路损坏存档不得崩：非 list→空两组，非 dict 元素跳过。"""
    from ming_sim.decree import group_secret_orders_for_sim

    for bad in (None, "junk", 123, {"在办": []}):
        assert group_secret_orders_for_sim(bad) == {"在办": [], "待核议": []}

    grouped = group_secret_orders_for_sim([
        None, 5, "x",
        {"id": 1, "minister_name": "甲", "title": "t", "content": "c", "status": "active",
         "turn_issued": 1, "due_turn": 4, "result": "", "sim_note": ""},
    ])
    assert [o["id"] for o in grouped["在办"]] == [1]

    bad = group_secret_orders_for_sim([
        {"id": 7, "minister_name": 999, "title": None, "content": 12345,
         "status": "pending_review"},
    ])["待核议"][0]
    assert bad["content"] == "12345"
    assert bad["minister_name"] == "999"
    assert isinstance(bad["title"], str)


def test_group_reads_progress_from_legacy_progress_key():
    """旧档承载条目 progress 键也能落入 grouped.progress。"""
    from ming_sim.decree import group_secret_orders_for_sim

    legacy_entry = {
        "id": 5, "minister_name": "甲", "title": "t", "content": "c",
        "status": "active", "turn_issued": 1, "due_turn": 4,
        "progress": "已办到南京", "sim_note": "风声",
    }
    grouped = group_secret_orders_for_sim([legacy_entry])
    entry = grouped["在办"][0]
    assert entry["progress"] == "已办到南京"
    assert "status" not in entry


def test_recovered_grouped_normalizes_legacy_list():
    """_recovered_grouped：dict 透传；旧 list 归一；杂值 → {}。"""
    from ming_sim.decree import _recovered_grouped

    already = {"在办": [{"id": 1}], "待核议": []}
    assert _recovered_grouped(already) is already

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
        assert "status" not in entry

    assert _recovered_grouped(None) == {}
    assert _recovered_grouped("junk") == {}


def test_resolve_context_roundtrips_grouped_secret_orders_as_dict(game):
    """save→get resolve_context 保持分组 dict 形状（恢复端，非公共 LLM 隔离）。"""
    db, state, _ = game
    grouped = {
        "在办": [{"id": 1, "minister_name": "甲", "title": "t", "content": "c",
                  "turn_issued": 1, "due_turn": 4, "progress": "", "sim_note": ""}],
        "待核议": [],
    }
    # 首 save 不重复塞 grouped 进 general context，只经专用 secret_orders 参数
    db.save_resolve_context(
        state.turn, "诏", "邸报", {}, secret_orders=grouped, relevant_memories=[],
    )
    ctx = db.get_resolve_context(state.turn)
    assert isinstance(ctx["secret_orders"], dict)
    assert set(ctx["secret_orders"].keys()) == {"在办", "待核议"}
    assert "secret_orders" not in (ctx.get("simulator_payload") or {})

    db.save_resolve_context(state.turn, "诏", "邸报", {}, secret_orders={}, relevant_memories=[])
    assert db.get_resolve_context(state.turn)["secret_orders"] == {}
