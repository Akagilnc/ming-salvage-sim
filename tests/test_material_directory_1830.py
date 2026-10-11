"""#1830 S1：材料目录骨架与目录读取。

Seams: prepare_character_materials (directory + opening min set),
list_materials/read_material (API), CLI cwd/readonly flags, restore rebuild.
"""

from __future__ import annotations

import json

import pytest
from tests.dossier_test_helpers import create_test_secret_order

from ming_sim.materials import (
    _safe_segment,
    list_materials,
    material_tools,
    prepare_character_materials,
    read_material,
)


def _active_minister(db, content, *, office_type=None):
    for character in content.characters.values():
        if character.office_type in ("后宫", "宗藩"):
            continue
        if office_type and character.office_type != office_type:
            continue
        if db.get_character_status(character.name)[0] == "active":
            return character
    raise AssertionError("no active minister")


def test_prepare_writes_typed_tree_and_index(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)
    db.textual_facts.append(
        subject_kind="character",
        subject_id=character.name,
        body="本官亲见府库告罄。",
        year=state.year, period=state.period, turn=state.turn,
    )
    dest = tmp_path / "materials"
    prepared = prepare_character_materials(db, state, character, dest_root=dest)

    names = list_materials(prepared.root)
    assert "INDEX.txt" in names
    assert "人物/朝臣名册.txt" in names
    assert any(p.startswith("人物/") and p.endswith("/经历.txt") for p in names)
    assert any(p.startswith("人物/") and p.endswith("/公事档案.txt") for p in names)
    assert any(p.startswith("密令/") for p in names)
    assert any(p.startswith("荐人/") for p in names)
    assert any(p.startswith("事实/") for p in names)
    # 路径由列目录取得；人读 INDEX 不承担路径解析契约。
    # 大理寺 01a0f1f4 裁定：不重调生产渲染器逐字比正文（与被调函数同进同出，
    # 只证接线），也不扫描名册正文推断成员身份（人读正文不是结构化记录身份，
    # 一次合法换行即假红）。不保留「列目录后裸 read」空壳。


def test_same_requested_root_creates_independent_material_invocations(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)
    requested = tmp_path / "materials"

    first = prepare_character_materials(db, state, character, dest_root=requested)
    second = prepare_character_materials(db, state, character, dest_root=requested)

    # 契约＝同请求根下两次 prepare 得独立树；不靠 INDEX 裸读证明隔离。
    assert first.root != second.root
    assert first.root.exists() and second.root.exists()
    assert (first.root / "INDEX.txt").is_file()
    assert (second.root / "INDEX.txt").is_file()


def test_material_tree_contains_only_structurally_related_world_details(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)
    army = db.conn.execute("SELECT id,name FROM armies ORDER BY id LIMIT 1").fetchone()
    # Real declaration entrance (not office_slots vacancy catalog / bare DB hook).
    from ming_sim.issues import apply_person_changes_only
    applied = apply_person_changes_only(
        db, state,
        [{
            "name": character.name,
            "动作": "任命",
            "office": "陕西巡抚",
            "office_type": "地方",
            "region_id": "shaanxi",
            "reason": "test-materials-posting",
        }],
        content=content,
    )["applied_person_changes"]
    assert applied and not applied[0].get("rejected"), applied
    # 只造「本人统领该军」这一结构关系；军政／地区各项数值与载体路径断言无关，
    # 属原措辞检查的失效夹具，一并删去（大理寺 aa62c7def，硬规 #12）。
    db.conn.execute("UPDATE armies SET commander='' WHERE commander=?", (character.name,))
    db.conn.execute(
        "UPDATE armies SET commander=? WHERE id=?", (character.name, army["id"]),
    )
    db.conn.commit()

    prepared = prepare_character_materials(db, state, character, dest_root=tmp_path / "materials")
    names = list_materials(prepared.root)
    region_name = db.conn.execute(
        "SELECT name FROM regions WHERE id=?", ("shaanxi",),
    ).fetchone()["name"]
    # 契约只落载体路径：本人可见的那一个地区、那支军队各有唯一详情载体。
    # 不再逐字比 db.region_detail／db.army_roster 的输出——materials 写的就是
    # 这两个调用，同源比较只能证接线，不构成独立证明（大理寺 01a0f1f4）。
    assert [p for p in names if p.startswith("地区/")] == [
        f"地区/{_safe_segment(region_name)}/详情.txt",
    ]
    assert [p for p in names if p.startswith("军队/")] == [
        f"军队/{_safe_segment(army['name'] or army['id'])}/详情.txt",
    ]


def test_matter_carriers_follow_affair_authority_not_parallel_issue_projection(game, tmp_path):
    """人物材料事务载体与场景共用 affair 权威投影（F45），不再平行 issue 业务路。

    经手关系经真实写口建立。未挂靠事务的 issue 仍是合法机械载体（issue-N）；
    已挂靠的只出 affair-N，不并写第二份 issue 身份。路径段与场景同形（_safe_segment）。
    """
    db, state, content = game
    character = _active_minister(db, content)
    rows = db.conn.execute(
        "SELECT id,title FROM issues WHERE status='active' ORDER BY id LIMIT 2",
    ).fetchall()
    handled_id, visible_id = (int(row["id"]) for row in rows)
    db.conn.execute(
        "UPDATE issues SET participant_roster=? WHERE id=?",
        (json.dumps([{"character_id": character.name, "tier": "主办"}]), handled_id),
    )
    db.conn.commit()


    # Link visible_id to a durable affair — mechanical carrier folds into affair-N.
    linked = db.affairs.open(
        name=str(rows[1]["title"]), origin=f"issue:{visible_id}",
        year=state.year, period=state.period, turn=state.turn,
    )
    db.conn.execute(
        "UPDATE issues SET affair_id=? WHERE id=?", (int(linked.id), visible_id),
    )
    db.conn.commit()

    prepared = prepare_character_materials(
        db, state, character, dest_root=tmp_path / "materials",
    )
    matter_paths = {
        path for path in list_materials(prepared.root) if path.startswith("事务/")
    }
    handled_path = f"事务/{_safe_segment(f'issue-{handled_id}')}/当前情况.txt"
    folded_issue_path = f"事务/{_safe_segment(f'issue-{visible_id}')}/当前情况.txt"
    affair_path = f"事务/{_safe_segment(f'affair-{int(linked.id)}')}/当前情况.txt"
    assert handled_path in matter_paths
    assert folded_issue_path not in matter_paths
    assert affair_path in matter_paths


def test_prepare_fails_loud_when_dossier_read_breaks(game, tmp_path):
    """dossier 读失败响亮上抛；来源保真：冒出的须是注入的原异常对象，不锁诊断措辞。"""
    db, state, content = game
    character = _active_minister(db, content)

    fault = RuntimeError("dossier boom")

    def boom(*_a, **_k):
        raise fault

    db.list_referenceable_dossiers = boom
    try:
        prepare_character_materials(db, state, character, dest_root=tmp_path / "m")
        raise AssertionError("expected fail loud")
    except RuntimeError as exc:
        assert exc is fault


def test_read_material_stays_inside_directory(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)
    prepared = prepare_character_materials(
        db, state, character, dest_root=tmp_path / "m",
    )
    try:
        read_material(prepared.root, "../outside.txt")
        raise AssertionError("expected path confinement")
    except ValueError:
        pass
    tools = {tool.__name__: tool for tool in material_tools(prepared.root)}
    assert tools["list_materials"]("../outside") == tools["read_material"]("../outside")
    spaced_rel = f"人物/{_safe_segment('John Doe')}/经历.txt"
    spaced_path = prepared.root / spaced_rel
    spaced_path.parent.mkdir(parents=True, exist_ok=True)
    spaced_path.write_text("经历正文\n", encoding="utf-8")
    listing = tools["list_materials"]("")
    assert spaced_rel in listing.splitlines()
    assert tools["read_material"](spaced_rel) == "经历正文\n"
    gazette_rel = "邸报/1627年9月.txt"
    gazette_path = prepared.root / gazette_rel
    gazette_path.parent.mkdir(parents=True, exist_ok=True)
    gazette_path.write_text("本月邸报\n", encoding="utf-8")
    assert tools["read_material"](gazette_rel) == "本月邸报\n"
    display = f"{gazette_rel} 任意非路径后缀"
    with pytest.raises(FileNotFoundError):
        read_material(prepared.root, display)
    miss = tools["read_material"](display)
    assert isinstance(miss, str)
    assert display in miss
    assert "本月邸报" not in miss


def test_character_materials_read_archived_public_gazettes(
    game, tmp_path,
):
    """Public gazettes use the original archived records and titles."""
    db, state, content = game
    character = _active_minister(db, content)
    for month in range(1, 8):
        db.conn.execute(
            "INSERT OR REPLACE INTO turn_reports (turn, year, period, report, attendant_message) "
            "VALUES (?, ?, ?, ?, '')",
            (month, 1627, month, f"gazette body {month}"),
        )
    db.conn.execute(
        "UPDATE turn_reports SET title=? WHERE turn=?",
        ("辽东标题", 1),
    )
    db.conn.commit()

    prepared = prepare_character_materials(
        db, state, character, dest_root=tmp_path / "char-gaz",
    )
    names = list_materials(prepared.root)
    gazette_paths = [p for p in names if p.startswith("公开说法/邸报/")]
    # Each archived gazette has one material carrier.
    assert gazette_paths == [
        f"公开说法/邸报/1627年{month}月.txt" for month in range(1, 8)
    ]
    assert not any(p.startswith("邸报/") for p in names)
    assert "INDEX.txt" in names


def test_secret_order_materials_keep_full_content_and_fail_loud_on_db_error(
    game, tmp_path, monkeypatch,
):
    db, state, content = game
    character = _active_minister(db, content)
    original = (
        "逐项核验太仓出纳原簿，先将各月领银的关防、经手人及兑付日期抄录存案。\r\n"
        "\r\n边镇报领之数与户部拨发之数分列，不因账面相合便认作实付；"
        "遇有缺页，将缺页所在月份另记，携原簿来奏，不得据传闻补写。\r末页仍留原有空白。  "
    )
    create_test_secret_order(
        db, state, character.name, "长密令", original, [], deadline_months=6,
    )
    prepared = prepare_character_materials(
        db, state, character, dest_root=tmp_path / "secret-ok",
    )
    secret_path = next(p for p in list_materials(prepared.root) if p.startswith("密令/"))
    # Independent input must survive the real API read, without constraining framing.
    tools = {tool.__name__: tool for tool in material_tools(prepared.root)}
    assert original in tools["read_material"](secret_path)

    fault = RuntimeError("secret-order-db-boom")

    def boom(_name):
        raise fault

    monkeypatch.setattr(db, "get_active_secret_orders_for_minister", boom)
    with pytest.raises(RuntimeError) as ei:
        prepare_character_materials(
            db, state, character, dest_root=tmp_path / "secret-fail",
        )
    assert ei.value is fault
