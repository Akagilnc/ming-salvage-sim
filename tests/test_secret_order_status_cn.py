"""#48：密令英文 status enum 不得泄漏进喂 simulator/extractor 的承载层。

根因：decree.py 把密令 DB 行（带英文 status=active/pending_review）整条塞进喂 simulator
的扁平 list，simulator 照抄进「密旨动向」邸报段 → 中文游戏里冒出「孙承宗密旨（active）」。

修法：decree.py 抽纯函数 group_secret_orders_for_sim(rows) 把行按状态分进中文键两组
（在办/待核议），条目剥掉英文 status。simulator/extractor 收到的密令承载零英文 enum，
泄漏「构造上消失」。

本档单测覆盖两层边界保证：
① 纯函数分组 + 剥 status + 字段保留 + done/failed 不进；
② 构建出的 simulator_payload 的 secret_orders 字段与 data_note 序列化后零 active/pending_review/status 字面。
两个 prompt（season_simulator.md 密旨动向段、score_extractor_personnel_secret.md 密令段）
的措辞改动 LLM 输出非确定不可单测，走 cross-model 评审。
"""

from __future__ import annotations

import json


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
    assert entry["progress"] == "已查两淮"   # 承办人自报进度，来自 row.result
    assert entry["sim_note"] == "风声渐起"    # 上轮推演副作用
    # 承载字段恰好这 8 个，不夹带 status/result/tags 等
    assert set(entry.keys()) == {
        "id", "minister_name", "title", "content",
        "turn_issued", "due_turn", "progress", "sim_note",
    }


def test_group_truncates_content_to_120():
    from ming_sim.decree import group_secret_orders_for_sim

    long_content = "甲" * 300
    grouped = group_secret_orders_for_sim([_row(1, "active", content=long_content)])

    assert len(grouped["在办"][0]["content"]) == 120


def test_group_drops_done_and_failed_orders():
    """done/failed 是裁决输出、无注入需求，落到分组函数时忽略，不进任何组。"""
    from ming_sim.decree import group_secret_orders_for_sim

    grouped = group_secret_orders_for_sim([
        _row(1, "active"),
        _row(2, "done"),
        _row(3, "failed"),
        _row(4, "cancelled"),
    ])

    assert [o["id"] for o in grouped["在办"]] == [1]
    assert grouped["待核议"] == []


def test_group_empty_input_returns_both_empty_groups():
    from ming_sim.decree import group_secret_orders_for_sim

    grouped = group_secret_orders_for_sim([])
    assert grouped == {"在办": [], "待核议": []}


def test_simulator_payload_secret_orders_has_no_english_enum(game):
    """边界保证：构建出的 simulator_payload 的 secret_orders 字段 + data_note
    序列化后零 active/pending_review/status 字面——LLM 收不到英文 enum，泄漏构造上消失。"""
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

    # 正向：分组承载结构在
    assert set(payload["secret_orders"].keys()) == {"在办", "待核议"}
    assert any(o["id"] == oid_active for o in payload["secret_orders"]["在办"])
    assert any(o["id"] == oid_review for o in payload["secret_orders"]["待核议"])

    # 边界：密令承载序列化零英文 enum / status 字面
    blob = json.dumps(payload["secret_orders"], ensure_ascii=False)
    assert "active" not in blob
    assert "pending_review" not in blob
    assert "status" not in blob

    # data_note 同为 LLM 可见，密令条目说明里不得再述 status 字段
    assert "status" not in payload["data_note"]


def test_build_simulator_payload_defaults_secret_orders_to_empty_dict(game):
    """无密令时 secret_orders 默认空 dict（嵌套中文键承载的空形状），不是空 list。"""
    from ming_sim.simulation import build_simulator_payload

    db, state, _ = game
    payload = build_simulator_payload(state, db, "", "")
    assert payload["secret_orders"] == {}
