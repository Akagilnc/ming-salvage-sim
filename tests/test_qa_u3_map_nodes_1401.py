"""#1274 QA 包⑦ / #1401：地图 theater 无名 + 军队双挂 + theater 针塌缩。

钉测：
1. 一军一挂——同一 army.id 不得出现在两个 map_nodes 的 armies 里
2. 无名节点——每个节点须有可见名（region.name 或 theater label）
3. liaodong / shenyang_liaoyang 坐标不得贴脸（断言 emit 且前端会用的坐标）
4. theater 针 emit（dongjiang/xuan_da/shanhaiguan/liaodong）+ 东江军可达 + guanning 在 liaodong
"""

from __future__ import annotations

from types import SimpleNamespace

import web_app


def _map_nodes(db):
    rt = object.__new__(web_app.WebGame)
    rt.session = SimpleNamespace(db=db)
    return web_app.WebGame.map_nodes(rt)


def test_map_nodes_no_double_army_hang(game):
    """#1401：theater 优先挂；未命中再 region——一军不得双挂。"""
    db, _state, _content = game
    nodes = _map_nodes(db)
    seen: dict[str, str] = {}
    for node in nodes:
        nid = str(node["id"])
        for army in node.get("armies") or []:
            aid = str(army["id"])
            assert aid not in seen, (
                f"army {aid} double-hung on {seen[aid]} and {nid}"
            )
            seen[aid] = nid
    # 开局盘面应至少挂上关宁等已知军，防止空投影假绿
    assert "guanning" in seen
    assert seen["guanning"] == "liaodong"


def test_map_nodes_theater_pins_emit_and_dongjiang_reachable(game):
    """#1401 r1：theater 关键词优先——东江/宣大/山海关针 emit；东江军在可选 theater 针。"""
    db, _state, _content = game
    nodes = _map_nodes(db)
    by_id = {str(n["id"]): n for n in nodes}
    for tid in ("dongjiang", "xuan_da", "shanhaiguan", "liaodong"):
        assert tid in by_id, f"missing theater pin {tid}"
        assert by_id[tid].get("kind") == "theater", (
            f"{tid} kind={by_id[tid].get('kind')!r}, want theater"
        )
        assert str(by_id[tid].get("label") or "").strip(), f"{tid} missing label"

    # 东江军须挂在地图可选节点（theater pin，非无 path 的 dongjiang_area  alone）
    dongjiang_armies = [str(a["id"]) for a in (by_id["dongjiang"].get("armies") or [])]
    assert "dongjiang" in dongjiang_armies, (
        f"dongjiang army not on selectable theater pin; armies={dongjiang_armies}"
    )
    # 宣大 / 山海关本军各归其针
    assert any(str(a["id"]) == "xuan_da" for a in (by_id["xuan_da"].get("armies") or []))
    assert any(str(a["id"]) == "shanhaiguan" for a in (by_id["shanhaiguan"].get("armies") or []))
    # liaodong 合并节点仍收关宁
    assert any(str(a["id"]) == "guanning" for a in (by_id["liaodong"].get("armies") or []))

    # 仍无双挂（与 no_double 同口径，钉在本场景）
    seen: dict[str, str] = {}
    for node in nodes:
        nid = str(node["id"])
        for army in node.get("armies") or []:
            aid = str(army["id"])
            assert aid not in seen, f"army {aid} double-hung on {seen[aid]} and {nid}"
            seen[aid] = nid


def test_map_nodes_no_nameless_nodes(game):
    """#1401：theater/region/external 节点皆须有可见名，禁无名点；id 不得双份。"""
    db, _state, _content = game
    nodes = _map_nodes(db)
    assert nodes, "map_nodes 空投影"
    ids = [str(n["id"]) for n in nodes]
    # 同 id 双节点（region+theater 撞车）→ 前端 Map 后写覆盖、theater 无 region 变无名
    assert len(ids) == len(set(ids)), (
        f"duplicate map node ids: {[i for i in ids if ids.count(i) > 1]}"
    )
    for node in nodes:
        region = node.get("region") or {}
        name = (
            (region.get("name") if isinstance(region, dict) else None)
            or node.get("label")
            or node.get("name")
        )
        assert name and str(name).strip(), (
            f"nameless map node id={node.get('id')!r} kind={node.get('kind')!r}"
        )
        # theater 契约：label 必填；与 region 同 id 的 theater 须带 region 字段（可见省名）
        if node.get("kind") == "theater":
            assert str(node.get("label") or "").strip(), (
                f"theater node {node.get('id')!r} missing label"
            )
            if str(node.get("id")) == "liaodong":
                assert isinstance(node.get("region"), dict) and node["region"].get("name"), (
                    "liaodong theater must carry region.name (no nameless pin)"
                )


def test_map_nodes_liaodong_shenyang_not_face_to_face(game):
    """#1401：辽东 theater 针与沈阳/辽阳 emit 坐标不得贴脸（前端实际读取的 x/y）。"""
    db, _state, _content = game
    nodes = _map_nodes(db)
    by_id = {str(n["id"]): n for n in nodes}
    assert "liaodong" in by_id
    assert "shenyang_liaoyang" in by_id
    a, b = by_id["liaodong"], by_id["shenyang_liaoyang"]
    # 真源：liaodong 合并节点 kind=theater，坐标来自 theater_positions（非死改 region_positions）
    assert a.get("kind") == "theater"
    dx = float(a["x"]) - float(b["x"])
    dy = float(a["y"]) - float(b["y"])
    dist = (dx * dx + dy * dy) ** 0.5
    # 旧 region 坐标对 ≈2.02；theater 针 vs 沈阳须明显可辨（阈值 4.0）
    assert dist >= 4.0, f"liaodong/shenyang still face-to-face: dist={dist:.3f} ({a['x']},{a['y']}) vs ({b['x']},{b['y']})"
