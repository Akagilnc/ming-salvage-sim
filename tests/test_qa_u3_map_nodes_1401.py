"""#1505 QA 包：地图 typed station_region 单归属 + 同 id 合 theater+region。

钉测：
1. 一军一挂——同一 army.id 不得出现在两个 map_nodes 的 armies 里
2. 无名节点——每个节点须有可见名（region.name 或 theater label）
3. typed station_region 单归属：东江→dongjiang_area、宣大→shanxi、山海关→beizhili、关宁→liaodong
4. 外线军不误吞 liaodong：manchu→jianzhou、han_liaoren→shenyang_liaoyang
5. 空 station_region（如 southwest_tusi）不挂在任何地图节点
6. dongjiang_area 与 liaodong 一样是前端可渲染的同 id 合并 pin
"""

from __future__ import annotations

from types import SimpleNamespace

import web_app


def _map_nodes(db):
    rt = object.__new__(web_app.WebGame)
    rt.session = SimpleNamespace(db=db)
    return web_app.WebGame.map_nodes(rt)


def test_map_nodes_no_double_army_hang(game):
    """#1505：typed station_region 单归属——同一 army.id 不得出现在两个 map_nodes 的 armies 里。"""
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


def test_map_nodes_province_garrison_co_node(game):
    """#1505：typed station_region 单归属——province nodes carry tax + garrison。

    纯 theater 针（dongjiang/xuan_da/shanhaiguan）不再 emit；军挂在其
    station_region 对应节点上。dongjiang_area 与 liaodong 同为带 region 的合并 pin。
    """
    db, _state, _content = game

    # station 文本似省但 typed 驻地为空时，不得猜挂。
    db.conn.execute(
        "INSERT INTO armies ("
        " id, name, station, station_region, theater, commander, controller,"
        " troop_type, manpower, supply, morale, training, equipment, arrears,"
        " mobility, loyalty, status, owner_power"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "temp_boundary_army", "临时驻防探针", "山西 / 临时驻防", "",
            "西南", "驻军", "兵部", "边军、步卒", 4000, 50, 50, 50, 50, 0,
            40, 50, "边界探针：typed station_region 为空不挂点", "ming",
        ),
    )
    db.conn.commit()

    nodes = _map_nodes(db)
    by_id = {str(n["id"]): n for n in nodes}

    assert not any(
        str(a["id"]) == "temp_boundary_army"
        for n in nodes for a in (n.get("armies") or [])
    ), "station_region='' 的探针军（station 含省名）不应挂在任何地图节点"

    # dongjiang army → dongjiang_area 同 id 合并 pin（NOT 旧 dongjiang 纯 theater）
    assert "dongjiang" not in by_id, "旧 dongjiang 纯 theater 针不得复活"
    assert "dongjiang_area" in by_id, "dongjiang_area merged pin missing"
    dj = by_id["dongjiang_area"]
    assert dj.get("kind") == "theater", (
        f"dongjiang_area 须为可点击合并 theater pin，got kind={dj.get('kind')!r}"
    )
    assert str(dj.get("label") or "").strip(), "dongjiang_area merged pin missing label"
    dongjiang_armies = [str(a["id"]) for a in (dj.get("armies") or [])]
    assert "dongjiang" in dongjiang_armies, (
        f"dongjiang army not on dongjiang_area node; armies={dongjiang_armies}"
    )
    # 节点同时携带 region tax payload
    assert isinstance(dj.get("region"), dict) and dj["region"].get("name"), (
        "dongjiang_area node must carry region tax payload"
    )

    # xuan_da army → shanxi province node
    assert "shanxi" in by_id, "shanxi province node missing"
    xuan_da_armies = [str(a["id"]) for a in (by_id["shanxi"].get("armies") or [])]
    assert "xuan_da" in xuan_da_armies, (
        f"xuan_da army not on shanxi node; armies={xuan_da_armies}"
    )
    assert isinstance(by_id["shanxi"].get("region"), dict) and by_id["shanxi"]["region"].get("name"), (
        "shanxi node must carry region tax payload"
    )

    # shanhaiguan army → beizhili province node
    assert "beizhili" in by_id, "beizhili province node missing"
    shanhaiguan_armies = [str(a["id"]) for a in (by_id["beizhili"].get("armies") or [])]
    assert "shanhaiguan" in shanhaiguan_armies, (
        f"shanhaiguan army not on beizhili node; armies={shanhaiguan_armies}"
    )
    assert isinstance(by_id["beizhili"].get("region"), dict) and by_id["beizhili"]["region"].get("name"), (
        "beizhili node must carry region tax payload"
    )

    # liaodong 合并 theater+region 节点仍收关宁
    assert any(str(a["id"]) == "guanning" for a in (by_id["liaodong"].get("armies") or [])), (
        "guanning not on liaodong merged node"
    )

    # 外线军不得被吞进 liaodong；各归其 province region
    liaodong_army_ids = {str(a["id"]) for a in (by_id["liaodong"].get("armies") or [])}
    assert "manchu_banners_main" not in liaodong_army_ids
    assert "han_liaoren_corps" not in liaodong_army_ids
    assert "jianzhou" in by_id
    assert "shenyang_liaoyang" in by_id
    jianzhou_army_ids = {str(a["id"]) for a in (by_id["jianzhou"].get("armies") or [])}
    shenyang_army_ids = {str(a["id"]) for a in (by_id["shenyang_liaoyang"].get("armies") or [])}
    assert "manchu_banners_main" in jianzhou_army_ids, (
        f"manchu_banners_main not on jianzhou; armies={sorted(jianzhou_army_ids)}"
    )
    assert "han_liaoren_corps" in shenyang_army_ids, (
        f"han_liaoren_corps not on shenyang_liaoyang; armies={sorted(shenyang_army_ids)}"
    )


def test_map_nodes_no_nameless_nodes(game):
    """#1505：theater/region/external 节点皆须有可见名，禁无名点；id 不得双份。"""
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
            if str(node.get("id")) in {"liaodong", "dongjiang_area"}:
                assert isinstance(node.get("region"), dict) and node["region"].get("name"), (
                    f"{node.get('id')} theater must carry region.name (no nameless pin)"
                )
