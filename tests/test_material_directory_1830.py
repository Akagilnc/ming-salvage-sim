"""#1830 S1：材料目录骨架与目录读取。

Seams: prepare_character_materials (directory + opening min set),
list_materials/read_material (API), CLI cwd/readonly flags, restore rebuild.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ming_sim.audience_night import (
    AUDIBILITY_PUBLIC,
    append_ledger_entry,
    open_night,
    summon_enter,
)
from ming_sim.materials import list_materials, prepare_character_materials, read_material
from ming_sim.models import CourtContext, LLMConfig
from ming_sim.registry import create_minister_agent
from ming_sim.session import GameSession


def _active_minister(db, content, *, office_type=None):
    for character in content.characters.values():
        if character.office_type in ("后宫", "宗藩"):
            continue
        if office_type and character.office_type != office_type:
            continue
        if db.get_character_status(character.name)[0] == "active":
            return character
    raise AssertionError("no active minister")


def _ctx(game):
    db, state, _ = game
    return CourtContext(state=state, db=db, previous_summary="")


def test_prepare_writes_typed_tree_and_index(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)
    # #1812：并入既有真实入口 tracer——不另立平行测试。
    # (a) 仅因非法字符被替换而撞名的两件「局势」，目录须各占一格，不得合并/覆盖。
    db.insert_issue(
        state, kind="situation", title="甲/乙",
        origin_kind="decree", stage_text="第一件的近况",
    )
    db.insert_issue(
        state, kind="situation", title="甲\\乙",
        origin_kind="decree", stage_text="第二件的近况",
    )
    # (b) durable 事务（案卷参与人 + 挂事务文字事实）须投影进目录与开场最小集，
    # 不能只靠旧「局势」投影（AffairStore.input_brief/current_situation 是真源）。
    affair = db.affairs.open(
        name="宁远护送", origin="拨银、调将、派兵去宁远",
        year=state.year, period=state.period, turn=state.turn,
    )
    dossier_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="调将赴宁远",
        target_kind="issue", target_id="ningyuan-general",
        executor_kind="character", executor_id=character.name,
        pending_action_id=93001, payload={"assignee_id": character.name},
    )
    db.affairs.point_dossier(dossier_id, affair.id)
    # (c) ADR 0156：文字事实只追加不覆盖，读时按时间顺序全部提供——目录须给
    # 该事务全部月份的事实，不能只留最新一条；开场仍只放最新一句（最小集）。
    affair_situation_old = "护送启程，尚在筹备"
    affair_situation_new = "护送银两已出京，尚未抵宁远"
    db.textual_facts.append(
        subject_kind="affair", subject_id=str(affair.id), body=affair_situation_old,
        year=state.year, period=max(1, state.period - 1), turn=state.turn,
    )
    db.textual_facts.append(
        subject_kind="affair", subject_id=str(affair.id), body=affair_situation_new,
        year=state.year, period=state.period, turn=state.turn,
    )
    # (d) ADR 0154：已指向该事务的 issue 是其机械载体——单一投影不丢内容：
    # 不另立 事务/issue-N 第二身份，但它自己的机械材料须并进 事务/affair-N。
    linked_issue_stage = "不得单独露面但材料不能丢"
    linked_issue_id = db.insert_issue(
        state, kind="situation", title="宁远护送机械载体",
        origin_kind="decree", stage_text=linked_issue_stage,
    )
    db.affairs.point_issue(linked_issue_id, affair.id)
    # (e) 单一投影不得连带丢材料：另一件事务 character 不是案卷参与人，但挂靠
    # 它的 issue 无参与名单（公开可见）——原有知识透视仍看得到，合并须把它
    # 归到该事务的 affair-N 身份（含它自己的机械材料），不能因为不是 dossier
    # 参与人就整条消失，也不冒出对应的 issue-N。
    bystander_affair = db.affairs.open(
        name="辽东军情", origin="边镇急报",
        year=state.year, period=state.period, turn=state.turn,
    )
    bystander_situation = "辽东军情已奏闻，尚候圣裁"
    db.textual_facts.append(
        subject_kind="affair", subject_id=str(bystander_affair.id),
        body=bystander_situation,
        year=state.year, period=state.period, turn=state.turn,
    )
    bystander_issue_stage = "旁观者也不该看不见的机械材料"
    bystander_issue_id = db.insert_issue(
        state, kind="situation", title="辽东军情机械载体",
        origin_kind="decree", stage_text=bystander_issue_stage,
    )
    db.affairs.point_issue(bystander_issue_id, bystander_affair.id)
    # (f) 事务了结不等于该事务的 durable 身份/全史从目录消失（#1819
    # Resolution 3/7 各事务全史常驻目录）：closed_affair 是合法关闭（无 active
    # linked issue，ADR 0154 `affair-close-requires-no-active-linked-issues`）
    # ——关闭前留一条历史文字事实，关闭后仍可在同一 事务/affair-N 查到。
    closed_affair = db.affairs.open(
        name="宣府欠饷", origin="宣府镇奏报欠饷",
        year=state.year, period=state.period, turn=state.turn,
    )
    closed_dossier_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="核实宣府欠饷",
        target_kind="issue", target_id="xuanfu-arrears",
        executor_kind="character", executor_id=character.name,
        pending_action_id=93002, payload={"assignee_id": character.name},
    )
    db.affairs.point_dossier(closed_dossier_id, closed_affair.id)
    closed_affair_fact = "宣府欠饷已核实，尚待补发"
    db.textual_facts.append(
        subject_kind="affair", subject_id=str(closed_affair.id), body=closed_affair_fact,
        year=state.year, period=state.period, turn=state.turn,
    )
    db.affairs.declare_closed(closed_affair.id, turn=state.turn)

    dest = tmp_path / "materials"
    prepared = prepare_character_materials(db, state, character, dest_root=dest)

    names = list_materials(prepared.root)
    assert "INDEX.txt" in names
    assert "人物/朝臣名册.txt" in names
    assert any(p.startswith("人物/") and p.endswith("/经历.txt") for p in names)
    assert any(p.startswith("人物/") and p.endswith("/公事档案.txt") for p in names)
    index = read_material(prepared.root, "INDEX.txt")
    assert "人物/朝臣名册.txt" in index.splitlines()
    for line in index.splitlines():
        if line.strip():
            assert line.strip() in names
            assert read_material(prepared.root, line.strip())
    roster = read_material(prepared.root, "人物/朝臣名册.txt")
    status, _reason = db.get_character_status(character.name)
    assert character.name in roster
    assert (character.office or "无现任官职") in roster
    assert status in roster
    # #1812：无裸副本——真实 prepare 输出里不该出现世界库/JSON 转储文件。
    assert not any(n.lower().endswith((".db", ".sqlite", ".sqlite3", ".json")) for n in names)

    affair_files = [p for p in list_materials(prepared.root) if p.startswith("事务/")]
    bodies = [read_material(prepared.root, p) for p in affair_files]
    assert any("第一件的近况" in b for b in bodies)
    assert any("第二件的近况" in b for b in bodies)
    # (c) 目录给该事务全部月份的事实，早晚两条都在、按时间顺序；开场只放最新。
    affair_path = next(p for p in affair_files if p.startswith(f"事务/affair-{affair.id}/"))
    affair_body = read_material(prepared.root, affair_path)
    assert affair_situation_old in affair_body
    assert affair_situation_new in affair_body
    assert affair_body.index(affair_situation_old) < affair_body.index(affair_situation_new)
    assert affair.name in prepared.opening
    assert affair_situation_new in prepared.opening
    assert affair_situation_old not in prepared.opening
    # (d) 已挂靠该事务的 issue 不另立一个 事务/issue-N 身份，但它自己的机械
    # 材料须并进 事务/affair-N，不得丢弃。
    assert not any(
        p.startswith(f"事务/issue-{linked_issue_id}/") for p in affair_files
    )
    assert linked_issue_stage in affair_body
    # (e) 非案卷参与人但可见 linked issue：材料不得整条消失——归并到该事务
    # 自己的 affair-N 身份（挂事务文字事实 + linked issue 机械材料），也不
    # 冒出对应的 issue-N。
    bystander_path = next(
        p for p in affair_files if p.startswith(f"事务/affair-{bystander_affair.id}/")
    )
    bystander_body = read_material(prepared.root, bystander_path)
    assert bystander_situation in bystander_body
    assert bystander_issue_stage in bystander_body
    assert not any(
        p.startswith(f"事务/issue-{bystander_issue_id}/") for p in affair_files
    )
    # 目录可见 ≠ 开场经手（#1830 最小集）：character 只是旁观者，既非该事务
    # 案卷参与人，挂靠的 issue 也无参与名单/audience 命中——不得被开场宣告
    # 「正经手事务」在办这件事。
    assert bystander_affair.name not in prepared.opening
    assert bystander_situation not in prepared.opening
    # (f) 事务了结不清空其 durable 身份或全史（#1819 Resolution 3/7）：已关闭
    # 的 closed_affair 仍在同一 事务/affair-N 里能查到真名与关闭前的历史
    # 文字事实。
    closed_path = next(
        p for p in affair_files if p.startswith(f"事务/affair-{closed_affair.id}/")
    )
    closed_body = read_material(prepared.root, closed_path)
    assert closed_affair.name in closed_body
    assert closed_affair_fact in closed_body


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


def test_opening_is_minimum_set_not_full_projection(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)
    prepared = prepare_character_materials(
        db, state, character, dest_root=tmp_path / "m",
    )
    opening = prepared.opening
    assert character.name in opening
    assert character.office in opening
    knowledge = db.get_character_knowledge(state, character.name)
    world = knowledge.get("world") or {}
    for key in ("treasury", "military", "personnel", "security", "regional", "construction"):
        value = str(world.get(key) or "").strip()
        if value:
            assert value not in opening
    blob = "\n".join(
        read_material(prepared.root, path)
        for path in list_materials(prepared.root)
        if path != "INDEX.txt"
    )
    assert blob


def test_audience_agent_exposes_directory_tools_and_min_instructions(game):
    db, state, content = game
    character = _active_minister(db, content)
    captured = {}

    def fake_agent(**kwargs):
        captured.update(kwargs)
        return kwargs

    cfg = LLMConfig(api_key="", base_url="", model="test", channel="cli", cli_runner="codex")
    with patch("ming_sim.registry.Agent", side_effect=fake_agent), \
         patch("ming_sim.registry.create_chat_model", return_value=MagicMock()):
        create_minister_agent(character, cfg, _ctx(game), db)

    instructions = "\n".join(captured["instructions"])
    assert character.name in instructions
    knowledge = db.get_character_knowledge(state, character.name)
    world = knowledge.get("world") or {}
    for key in ("treasury", "military", "personnel", "security", "regional", "construction"):
        value = str(world.get(key) or "").strip()
        if value:
            assert value not in instructions
    tool_names = {getattr(fn, "__name__", "") for fn in captured["tools"]}
    assert "list_materials" in tool_names
    assert "read_material" in tool_names
    assert "propose_directive" in tool_names
    retired_reads = {
        "list_regions", "inspect_region", "read_past_report", "search_memories",
        "inspect_treasury_ledger", "check_treasury", "list_memorials",
        "inspect_memorial", "list_buildings", "inspect_building",
        "estimate_resistance", "query_court_roster", "query_army_roster",
        "allocate_payroll", "audit_tax_arrears",
    }
    assert not (tool_names & retired_reads)
    tools = {fn.__name__: fn for fn in captured["tools"]}
    listing = tools["list_materials"]()
    rel = next(line for line in listing.splitlines() if line.endswith("经历.txt"))
    body = tools["read_material"](rel)
    assert body


def test_audience_prompt_rebuilds_from_directory_and_persisted_turns(game):
    db, state, content = game
    character = _active_minister(db, content)
    night = open_night(db, state, location="乾清宫", time_of_day="戌时")
    summon_enter(db, int(night["id"]), character.name)
    from ming_sim.audience_night import attach_chat_turn_to_night
    _nid, ct = attach_chat_turn_to_night(
        db, state, character.name, agno_session_id="sess", agno_runs_before=0,
    )
    spoken = "SENTINEL_NIGHT_SPOKEN_1830"
    uid = db.append_chat_message(character.name, state.turn, "user", "问边饷")
    db.update_chat_turn_messages(ct, user_message_id=uid)
    mid = db.append_chat_message(character.name, state.turn, "minister", spoken)
    db.update_chat_turn_messages(ct, minister_message_id=mid)
    db.conn.execute("UPDATE chat_turns SET extract_status='done' WHERE id=?", (ct,))
    db.conn.commit()
    append_ledger_entry(
        db, int(night["id"]), person_names=[character.name],
        body=spoken, audibility=AUDIBILITY_PUBLIC,
    )

    session = SimpleNamespace(db=db, state=state, registry=None)
    prompt = GameSession._audience_prompt_for_message(
        session, "下一句", character,
    )
    assert spoken in prompt
    assert "下一句" in prompt
    knowledge = db.get_character_knowledge(state, character.name)
    world = knowledge.get("world") or {}
    for key in ("treasury", "military", "personnel", "security", "regional", "construction"):
        value = str(world.get(key) or "").strip()
        if value:
            assert value not in prompt

    path = str(db.path)
    db.close()
    from ming_sim.db import GameDB
    restored = GameDB(path, content)
    try:
        state2 = restored.load_state()
        character2 = content.characters[character.name]
        session2 = SimpleNamespace(db=restored, state=state2, registry=None)
        prompt2 = GameSession._audience_prompt_for_message(
            session2, "重开后一句", character2,
        )
        assert spoken in prompt2
        prepared = prepare_character_materials(restored, state2, character2)
        restored_names = list_materials(prepared.root)
        assert not any(
            n.lower().endswith((".db", ".sqlite", ".sqlite3", ".json")) for n in restored_names
        )
        rel = next(p for p in list_materials(prepared.root) if p.endswith("经历.txt"))
        assert read_material(prepared.root, rel)
    finally:
        restored.close()
