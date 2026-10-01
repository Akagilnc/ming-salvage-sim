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
    for rel in names:
        assert read_material(prepared.root, rel)
    # 路径由列目录取得；人读 INDEX 不承担路径解析契约。
    # 大理寺 01a0f1f4 裁定：不重调生产渲染器逐字比正文（与被调函数同进同出，
    # 只证接线），也不扫描名册正文推断成员身份（人读正文不是结构化记录身份，
    # 一次合法换行即假红）。


def test_same_requested_root_creates_independent_material_invocations(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)
    requested = tmp_path / "materials"

    first = prepare_character_materials(db, state, character, dest_root=requested)
    second = prepare_character_materials(db, state, character, dest_root=requested)

    assert first.root != second.root
    assert read_material(first.root, "INDEX.txt")
    assert read_material(second.root, "INDEX.txt")


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


def test_matter_carriers_follow_the_real_knowledge_projection(game, tmp_path):
    """事务载体路径集合恰等于该角色真实可见投影内每条事务的唯一载体。

    经手关系经 `issues.participant_roster` + `record_character_participation`
    两条真实写口建立，可见性取自 `db.get_character_knowledge` 真实投影；
    不替换知识输入，也不另调内部 helper 把投影重算一遍当证据。

    开场「正经手事务」只列经手事务这半条不在本文件承担：`PreparedMaterials`
    只导出 root/opening/index_lines，开场里没有事务号的结构化出口，而解析
    开场正文去认段头措辞正是本类禁止的盯文。按票面不为此新增生产测试钩子。
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
    db.record_character_participation(
        state, [character.name], "case", str(rows[0]["title"]), "案由正文",
        source_id=f"issue:{handled_id}",
    )

    prepared = prepare_character_materials(
        db, state, character, dest_root=tmp_path / "materials",
    )
    # 经手的那条与只是可见的那条都在真实可见投影内，各有唯一载体路径。
    visible_ids = {
        int(row["id"]) for row in db.get_character_knowledge(state, character.name)["issues"]
    }
    assert {handled_id, visible_id} <= visible_ids
    issue_paths = {path for path in list_materials(prepared.root) if path.startswith("事务/issue-")}
    assert issue_paths == {f"事务/issue-{i}/当前情况.txt" for i in visible_ids}


def test_prepare_fails_loud_when_dossier_read_breaks(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)

    def boom(*_a, **_k):
        raise RuntimeError("dossier boom")

    db.list_referenceable_dossiers = boom
    try:
        prepare_character_materials(db, state, character, dest_root=tmp_path / "m")
        raise AssertionError("expected fail loud")
    except RuntimeError as exc:
        assert "dossier boom" in str(exc)


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
    display = f"{gazette_rel} 任意非路径后缀"
    assert tools["read_material"](gazette_rel) == "本月邸报\n"
    with pytest.raises(FileNotFoundError):
        read_material(prepared.root, display)
    miss = tools["read_material"](display)
    assert isinstance(miss, str)
    assert display in miss
    assert "本月邸报" not in miss


def test_character_materials_exclude_legacy_raw_turn_report_and_keep_public_gazettes(
    game, tmp_path,
):
    """#883/#1832: raw turn_reports do not authorize person gazette files.

    Typed public counterparts still land under 公开说法/邸报/。契约只落结构化
    字段：载体路径集合（数量与所属月份）；INDEX 只检查独立入档标题原文搬运，
    不解析展示行。载体归属与准入由路径集合承担。
    """
    db, state, content = game
    character = _active_minister(db, content)
    db.conn.execute(
        "INSERT INTO turn_reports (turn, year, period, report, attendant_message) "
        "VALUES (?, ?, ?, ?, '')",
        (max(1, int(state.turn) + 7), 1628, 1, "raw turn report body"),
    )
    db.conn.commit()

    from ming_sim.models import GameState

    for month in range(1, 8):
        past = GameState(
            turn=month, year=1627, period=month, metrics=dict(state.metrics),
        )
        db.record_public_knowledge_event(
            past, "邸报", f"gazette body {month}", source_id=f"turn_report:{month}:public",
        )
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
    # 载体路径集合恰是七份已入档 typed 公开邸报；那份只有 raw report 的 1628 年
    # 记录不产生任何人物邸报载体。
    assert gazette_paths == [
        f"公开说法/邸报/1627年{month}月.txt" for month in range(1, 8)
    ]
    assert not any(p.startswith("邸报/") for p in names)
    assert "辽东标题" in read_material(prepared.root, "INDEX.txt")


def test_secret_order_materials_keep_full_content_and_fail_loud_on_db_error(
    game, tmp_path, monkeypatch,
):
    db, state, content = game
    character = _active_minister(db, content)
    create_test_secret_order(
        db, state, character.name, "长密令", "密令长正文", [], deadline_months=6,
    )
    prepared = prepare_character_materials(
        db, state, character, dest_root=tmp_path / "secret-ok",
    )
    secret_path = next(p for p in list_materials(prepared.root) if p.startswith("密令/"))
    assert read_material(prepared.root, secret_path)
    # 只钉载体存在与 DB 失败即抛（大理寺 01a0f1f4 裁定）：自由正文不作行集
    # 成员关系推断——splitlines 按文本行边界切，一次合法换行即假红。

    def boom(_name):
        raise RuntimeError("secret-order-db-boom")

    monkeypatch.setattr(db, "get_active_secret_orders_for_minister", boom)
    with pytest.raises(RuntimeError, match="secret-order-db-boom"):
        prepare_character_materials(
            db, state, character, dest_root=tmp_path / "secret-fail",
        )
