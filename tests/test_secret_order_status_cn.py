"""#48：密令状态承载归一（group_secret_orders_for_sim 纯函数）。

现行 schema 只注入 active；due_commitment ACK 仍走 augment 待核议分组。
"""

from __future__ import annotations


def _row(oid, status, *, minister="孙承宗", title="查抄魏党", content="清查魏忠贤遗党赃私",
         turn_issued=1, due_turn=4, result="", sim_note=""):
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
        _row(3, "active"),
    ])

    assert set(grouped.keys()) == {"在办", "待核议"}
    assert [o["id"] for o in grouped["在办"]] == [1, 3]
    assert grouped["待核议"] == []


def test_group_strips_english_status_field():
    from ming_sim.decree import group_secret_orders_for_sim

    grouped = group_secret_orders_for_sim([_row(1, "active")])

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


def test_resolve_context_roundtrips_grouped_secret_orders_as_dict(game):
    db, state, _ = game
    grouped = {
        "在办": [{"id": 1, "minister_name": "甲", "title": "t", "content": "c",
                  "turn_issued": 1, "due_turn": 4, "progress": "", "sim_note": ""}],
        "待核议": [],
    }
    db.save_resolve_context(
        state.turn, "诏", "邸报", {}, secret_orders=grouped, relevant_memories=[],
    )
    ctx = db.get_resolve_context(state.turn)
    assert isinstance(ctx["secret_orders"], dict)
    assert set(ctx["secret_orders"].keys()) == {"在办", "待核议"}
    assert "secret_orders" not in (ctx.get("simulator_payload") or {})

    db.save_resolve_context(state.turn, "诏", "邸报", {}, secret_orders={}, relevant_memories=[])
    assert db.get_resolve_context(state.turn)["secret_orders"] == {}
