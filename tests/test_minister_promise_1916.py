"""#1916 大臣主动许诺记账、到期复命。

按独立行为契约组织（非历轮病史堆叠）：
- 记录与撤回：真实召对落账、供料关联、来源区分、undo
- 到期生命周期：过月→跨月未召见→开场→ACK；旧待办对照
- 材料可读：公开目录 / 个人出生名 / 到期派生供料
- 准入与责任：互斥拒收、纠错拒收、皇命违诺排除
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ming_sim.audience_night import (
    close_night,
    ensure_summon_enter,
    open_night,
)
from ming_sim.audience_translate import build_c0_declaration_shape
from ming_sim.breach_plea import scan_and_write_breach_pleas
from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.due_review import apply_pending_due_reviews, list_due_review_scenes
from ming_sim.knowledge import build_character_knowledge, origin_visible_to
from ming_sim.materials import (
    list_materials,
    prepare_scene_materials,
    release_material_tree,
)
from ming_sim.month_chain import prepare_gazette_author_materials
from ming_sim.settlement import SettlementContext, settle_delta
from ming_sim.settlement_payload import list_due_commitments
from ming_sim.staged_commitment import (
    ENTRY_KIND_STAGED,
    TODO_STATUS_PENDING,
    write_due_staged_commitment_todos,
)
from tests.conftest import (
    offline_empty_audience_translate,
    open_hall_turn,
    stub_scene_agent,
    wait_for_background_jobs,
)
from tests.dossier_test_helpers import (
    TYPED_COVERT_TASK,
    create_test_secret_order,
    promulgated_policy_origin,
)
from tests.test_audience_translate_1837 import _scene_turn, _sess
from tests.test_month_chain_1843 import _prepare_player_month


def _opening_commitment_ids(opening: str) -> list[int]:
    """真实 opening 交付边界：JSON 事实按字段读 commitment_ref（禁正文哨兵）。"""
    ids: list[int] = []
    for line in str(opening or "").splitlines():
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("commitment_ref") is not None:
            ids.append(int(obj.get("commitment_ref") or 0))
    return ids


def _active_commitments_for(db, name: str):
    rows = []
    for row in db.issues.active_commitments():
        roster = row["participant_roster"]
        if isinstance(roster, str):
            roster = json.loads(roster)
        names = []
        for item in roster or []:
            if isinstance(item, dict):
                names.append(str(item.get("character_id") or ""))
            else:
                names.append(str(item))
        if name in names:
            rows.append(row)
    return rows


def _one_month(session, db, state) -> None:
    session.resolve_turn(allow_empty_decree=True)
    wait_for_background_jobs(db)
    db.save_turn_report(state, "邸报", public_body="邸报")
    session.resolve_turn(allow_empty_decree=True)
    wait_for_background_jobs(db)


def _hall_commission_batch(db, state, promisor, commissions, *, words="尔有何话说"):
    """共用召对入口：开厅、钉源轮、dispatch 一批 commissions。"""
    night_id, chat_id = open_hall_turn(db, state, promisor)
    uid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'emperor', ?)",
        (promisor, int(state.turn), words),
    ).lastrowid
    mid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'minister', ?)",
        (promisor, int(state.turn), words),
    ).lastrowid
    db.conn.commit()
    db.reign.update_chat_turn_messages(
        int(chat_id), user_message_id=int(uid), minister_message_id=int(mid),
    )
    result = dispatch_declaration(
        db, state, {"commissions": list(commissions)},
        minister_name=promisor,
        night_id=int(night_id),
        chat_turn_id=int(chat_id),
    )
    return result, int(chat_id), int(night_id)


def _land_minister_promise(
    db, state, *, promisor: str, title: str, deadline_months=1,
    affair_declaration=None, extra=None,
):
    """真实召对分派入口落一笔自诺；复用共用批派入口。"""
    item = {
        "text": title,
        "minister_promise": _promise_item(
            promisor, title, deadline_months=deadline_months,
        ),
    }
    if affair_declaration is not None:
        item["affair_declaration"] = affair_declaration
    if extra:
        item.update(extra)
    return _hall_commission_batch(db, state, promisor, [item], words=title)


def _promise_item(promisor: str, title: str, **fields):
    """自诺输入。不传 deadline_months 则省略该键（测「没说期限」缺省，不夹具补 0）。"""
    item = {"title": title, "content": title, "promisor": promisor}
    item.update(fields)
    return item


def _paths_have_affair(paths, affair_id: int) -> bool:
    # _safe_segment 产出 affair-N-<hash> 目录名。
    key = f"affair-{int(affair_id)}"
    return any(
        part == key or part.startswith(f"{key}-")
        for path in paths
        for part in str(path).split("/")
    )


def _affair_title_key(affair_id: int) -> str:
    return f"affair-{int(affair_id)}"


def _install_person_matter_title_capture(monkeypatch):
    """prepare_scene 交付边界：捕获 matter_lines 的结构化 title 字段。"""
    import ming_sim.materials as materials_mod

    delivered: dict[str, dict[str, str]] = {}
    real = materials_mod._write_one_present_person

    def spy(tmp, db_, state_, character, knowledge, matter_lines):
        name = str(getattr(character, "name", "") or "")
        delivered[name] = {str(ln[0]): str(ln[1]) for ln in matter_lines}
        return real(tmp, db_, state_, character, knowledge, matter_lines)

    monkeypatch.setattr(materials_mod, "_write_one_present_person", spy)
    return delivered


def _install_public_affair_title_capture(monkeypatch):
    """prepare_gazette 交付边界：捕获 affair_lines 的结构化 title 字段。"""
    import ming_sim.materials as materials_mod

    delivered: dict[str, str] = {}
    real = materials_mod._write_world_tree

    def spy(
        tmp, db_, state_, public_events, affair_lines, board_text, roster_text,
        world_facts, include_fact=None, include_event=None,
        secret_turn_ids=None, exclude_dossier_ids=None, public_only=False,
    ):
        delivered.clear()
        delivered.update({str(line[0]): str(line[1]) for line in affair_lines})
        return real(
            tmp, db_, state_, public_events, affair_lines, board_text, roster_text,
            world_facts, include_fact, include_event,
            secret_turn_ids, exclude_dossier_ids, public_only,
        )

    monkeypatch.setattr(materials_mod, "_write_world_tree", spy)
    return delivered


# ── 记录与撤回 ──────────────────────────────────────────────


def test_minister_promise_lands_from_real_audience_and_undoes(game, monkeypatch):
    """有期／无期／既有关联同场落账；供料 ID 真源；不成旨意；来源互斥；撤回逆转。"""
    db, state, content = game
    promisor = "魏忠贤"
    other = "杨嗣昌"
    existing = db.affairs.open(
        name="田尔耕案", origin="test",
        year=int(state.year), period=int(state.period), turn=int(state.turn),
    )
    existing_id = int(existing.id)
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    dossiers_before = int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers",
    ).fetchone()["n"])
    issues_before = {
        int(r["id"]) for r in db.conn.execute("SELECT id FROM issues").fetchall()
    }
    affairs_before = {
        int(r["id"]) for r in db.conn.execute("SELECT id FROM affairs").fetchall()
    }
    seen_prompts: list[str] = []

    def translate(prompt, llm_config):
        text = str(prompt or "")
        seen_prompts.append(text)
        affair_id = None
        for line in text.splitlines():
            if not line.startswith("affair\t"):
                continue
            parts = line.split("\t")
            if len(parts) >= 3 and parts[2] == "田尔耕案":
                affair_id = int(parts[1])
                break
        assert affair_id == existing_id, text
        base = offline_empty_audience_translate(prompt, llm_config)
        return {
            **base,
            "commissions": [
                {
                    "text": "臣明日就办田尔耕。",
                    "minister_promise": _promise_item(
                        promisor, "办田尔耕", deadline_months=1,
                    ),
                    "affair_declaration": {
                        "attach": "new",
                        "name": "自诺事务0",
                        "origin": "大臣自诺",
                    },
                },
                {
                    "text": "臣愿扩到五万流民。",
                    # 条款2：没说期限 —— 省略 deadline_months，不夹具补 0。
                    "minister_promise": _promise_item(other, "扩到五万流民"),
                    "affair_declaration": {
                        "attach": "new",
                        "name": "自诺事务1",
                        "origin": "大臣自诺",
                    },
                },
                {
                    "text": "臣就田尔耕案再诺复命。",
                    "minister_promise": _promise_item(
                        promisor, "田尔耕案复命", deadline_months=1,
                    ),
                    "affair_declaration": {
                        "attach": "existing",
                        "affair_id": int(affair_id),
                    },
                },
            ],
        }

    class FakeAgent:
        def run(self, message):
            return SimpleNamespace(
                content="臣明日就办田尔耕。臣另愿扩到五万流民。臣就田尔耕案再诺复命。",
                tools=[],
            )

    stub_scene_agent(monkeypatch, FakeAgent())
    sess = _sess(db, state, content, monkeypatch, translate_fn=translate)
    _result, chat_turn_id = _scene_turn(
        sess, db, state, "尔等有何话说", night_id=nid,
    )

    assert seen_prompts, "真实转译未接到 prompt"
    assert "affair_declaration" in build_c0_declaration_shape()

    timed = _active_commitments_for(db, promisor)
    open_ended = _active_commitments_for(db, other)
    assert len(timed) == 2
    assert len(open_ended) == 1

    open_row = open_ended[0]
    assert int(open_row["end_turn"] or 0) == 0
    assert str(open_row["commitment_kind"] or "").strip()
    assert str(open_row["origin_kind"] or "") != "decree"

    linked = next(
        r for r in timed
        if int(db.issues.affair_id_of(int(r["id"]))) == existing_id
    )
    newborn = next(
        r for r in timed
        if int(db.issues.affair_id_of(int(r["id"]))) != existing_id
    )
    assert int(linked["end_turn"] or 0) == int(state.turn) + 1
    assert int(newborn["end_turn"] or 0) == int(state.turn) + 1
    assert str(linked["commitment_kind"] or "").strip()
    assert str(newborn["origin_kind"] or "") != "decree"

    timed_origin = str(newborn["origin_ref"] or "")
    open_origin = str(open_row["origin_ref"] or "")
    linked_origin = str(linked["origin_ref"] or "")
    assert timed_origin and open_origin and linked_origin
    assert len({timed_origin, open_origin, linked_origin}) == 3
    assert f":minister_promise:{int(newborn['id'])}" in timed_origin
    assert f":minister_promise:{int(open_row['id'])}" in open_origin
    assert origin_visible_to(db, timed_origin, promisor) is True
    assert origin_visible_to(db, open_origin, other) is True
    assert origin_visible_to(db, timed_origin, other) is False
    assert origin_visible_to(db, open_origin, promisor) is False
    assert origin_visible_to(db, timed_origin) is False

    promisor_knowledge = build_character_knowledge(db, state, promisor)
    other_knowledge = build_character_knowledge(db, state, other)
    promisor_ids = {
        int(i.get("id") or 0) for i in promisor_knowledge.get("issues") or []
    }
    other_ids = {int(i.get("id") or 0) for i in other_knowledge.get("issues") or []}
    assert int(newborn["id"]) in promisor_ids
    assert int(linked["id"]) in promisor_ids
    assert int(open_row["id"]) in other_ids
    assert int(open_row["id"]) not in promisor_ids

    pending = db.conn.execute(
        "SELECT COUNT(*) AS n FROM pending_actions "
        "WHERE turn=? AND status='pending'",
        (int(state.turn),),
    ).fetchone()["n"]
    assert int(pending) == 0
    assert int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers",
    ).fetchone()["n"]) == dossiers_before

    affairs_landed = {
        int(r["id"]) for r in db.conn.execute(
            "SELECT id FROM affairs WHERE status='open'",
        ).fetchall()
    }
    # 既有 1 + 新建 2
    assert len(affairs_landed - affairs_before) == 2

    src_before = int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM character_knowledge_sources WHERE source_id=?",
        (timed_origin,),
    ).fetchone()["n"])
    assert src_before == 1

    db.reign.set_chat_turn_status("active", int(chat_turn_id))
    db.conn.commit()
    db.undo_chat_turn(int(chat_turn_id))
    assert {
        int(r["id"]) for r in db.conn.execute("SELECT id FROM issues").fetchall()
    } == issues_before
    assert {
        int(r["id"]) for r in db.conn.execute("SELECT id FROM affairs").fetchall()
    } == affairs_before
    assert _active_commitments_for(db, promisor) == []
    assert _active_commitments_for(db, other) == []
    assert int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM character_knowledge_sources WHERE source_id=?",
        (timed_origin,),
    ).fetchone()["n"]) == 0


# ── 到期生命周期 ────────────────────────────────────────────


def test_timed_promise_due_lifecycle_and_old_todo_contrast(game, monkeypatch):
    """真实过月→跨月未召见→承诺人开场→ACK；旧分段无桥待办对照消费。"""
    db, state, content = game
    promisor = "魏忠贤"
    open_night(db, state, location="乾清宫", time_of_day="夜")
    affair = db.affairs.open(
        name="田尔耕案", origin="test",
        year=int(state.year), period=int(state.period), turn=int(state.turn),
    )
    result, _chat_id, _night_id = _land_minister_promise(
        db, state, promisor=promisor, title="办田尔耕",
        deadline_months=1,
        affair_declaration={
            "attach": "existing", "affair_id": int(affair.id),
        },
    )
    assert result.commissions.rejected == []
    assert len(result.commissions.applied) == 1
    applied = result.commissions.applied[0]
    assert applied["kind"] == "minister_promise"
    assert "issue_id" in applied
    assert "id" not in applied
    issue_id = int(applied["issue_id"])
    assert int(db.issues.affair_id_of(issue_id)) == int(affair.id)

    close_night(db, state, content=content)
    before = int(state.turn)
    session = _prepare_player_month(db, state, content, monkeypatch)

    _one_month(session, db, state)
    assert int(state.turn) == before + 1
    _one_month(session, db, state)
    assert int(state.turn) == before + 2

    todos = [
        t for t in db.dossiers.list_next_audience_todos(status=TODO_STATUS_PENDING)
        if int(t["commitment_ref"]) == issue_id
    ]
    assert len(todos) == 1
    assert len([
        s for s in list_due_review_scenes(db)
        if int(s.get("commitment_ref") or 0) == issue_id
    ]) == 1

    _one_month(session, db, state)
    assert int(state.turn) == before + 3
    assert len([
        t for t in db.dossiers.list_next_audience_todos(status=TODO_STATUS_PENDING)
        if int(t["commitment_ref"]) == issue_id
    ]) == 1
    assert len([
        s for s in list_due_review_scenes(db)
        if int(s.get("commitment_ref") or 0) == issue_id
    ]) == 1

    # C4 对照：复用主诺过月待办，不另建第二笔自诺；旧分段无桥对照消费。
    old_id = db.insert_issue(
        state,
        kind="initiative",
        title="旧分段无桥之诺",
        origin_kind="decree",
        origin_ref="legacy-no-dossier",
        stage_text="中段待办",
        participants=[{"character_id": "徐光启", "tier": "主办"}],
        end_turn=int(state.turn) + 5,
        commitment_kind="until_stop",
        stages_json=[
            {"stage_idx": 0, "due_turn": int(state.turn), "criterion_text": "中段"},
            {"stage_idx": 1, "due_turn": int(state.turn) + 3, "criterion_text": "末段"},
        ],
        commit=True,
    )
    db.dossiers.insert_next_audience_todo(
        commitment_ref=int(old_id),
        stage_idx=0,
        due_turn=int(state.turn),
        criterion_text="中段",
        origin_context="中段",
        entry_kind=ENTRY_KIND_STAGED,
        created_turn=int(state.turn) - 1,
    )
    outcomes = {
        int(r["todo_id"]): r for r in apply_pending_due_reviews(db, state)
    }
    old_todos = [
        t for t in db.dossiers.list_next_audience_todos()
        if int(t["commitment_ref"]) == int(old_id)
    ]
    promise_todos = [
        t for t in db.dossiers.list_next_audience_todos()
        if int(t["commitment_ref"]) == issue_id
    ]
    assert old_todos and str(old_todos[0]["status"]) != TODO_STATUS_PENDING
    assert promise_todos and str(promise_todos[0]["status"]) == TODO_STATUS_PENDING
    old_todo_id = int(old_todos[0]["id"])
    promise_todo_id = int(promise_todos[0]["id"])
    if old_todo_id in outcomes:
        assert outcomes[old_todo_id].get("consumed") is True
    if promise_todo_id in outcomes:
        assert outcomes[promise_todo_id].get("consumed") is False

    night2 = open_night(db, state, location="乾清宫", time_of_day="昼")
    ensure_summon_enter(db, int(night2["id"]), promisor)
    prepared = prepare_scene_materials(db, state)
    try:
        assert issue_id in _opening_commitment_ids(prepared.opening), prepared.opening
    finally:
        release_material_tree(prepared.root)

    close_out = settle_delta(
        state, db,
        {
            "close_issues": [{
                "issue_id": issue_id,
                "reason": "acknowledged",
                "narrative": "田尔耕事已复命，此诺了结。",
            }],
        },
        SettlementContext(content=content),
    )
    assert close_out.issue is not None
    assert close_out.issue.rejected == []
    assert any(
        int(c.get("issue_id") or 0) == issue_id for c in close_out.issue.closes
    )
    row = db.conn.execute(
        "SELECT status, closed_turn FROM issues WHERE id=?", (issue_id,),
    ).fetchone()
    assert str(row["status"]) == "dropped"
    assert int(row["closed_turn"] or 0) == int(state.turn)
    assert not any(
        int(i.get("id") or 0) == issue_id
        for i in build_character_knowledge(db, state, promisor).get("issues") or []
    )


# ── 材料可读：公开目录 ──────────────────────────────────────


def test_public_catalog_keeps_public_hides_private_and_mixes_lawfully(game, monkeypatch):
    """公开事务保留；私有出生不入目录；混合仅公开合法部分；名册与来源共约束。"""
    db, state, content = game
    public_titles = _install_public_affair_title_capture(monkeypatch)
    promisor = "魏忠贤"
    public_affair = db.affairs.open(
        name="公开边饷事务", origin="廷议边饷",
        year=int(state.year), period=int(state.period), turn=int(state.turn),
    )
    public_affair_id = int(public_affair.id)

    private, _c, _n = _land_minister_promise(
        db, state, promisor=promisor, title="私密自诺不入邸报",
        deadline_months=0,
        affair_declaration={
            "attach": "new",
            "name": "魏忠贤私下许诺查案",
            "origin": "御前私诺查办田尔耕",
        },
    )
    assert private.commissions.rejected == []
    assert len(private.commissions.applied) == 1
    private_issue = int(private.commissions.applied[0]["issue_id"])
    private_affair_id = int(db.issues.affair_id_of(private_issue))
    private_origin = str(db.conn.execute(
        "SELECT origin_ref FROM issues WHERE id=?", (private_issue,),
    ).fetchone()["origin_ref"] or "")
    assert private_origin
    assert origin_visible_to(db, private_origin) is False
    assert origin_visible_to(db, private_origin, promisor) is True
    assert origin_visible_to(db, private_origin, "杨嗣昌") is False

    bare, _bc, _bn = _land_minister_promise(
        db, state, promisor=promisor, title="私诺挂公开事务",
        deadline_months=0,
        affair_declaration={"attach": "existing", "affair_id": public_affair_id},
    )
    assert bare.commissions.rejected == []
    assert int(db.issues.affair_id_of(
        int(bare.commissions.applied[0]["issue_id"]),
    )) == public_affair_id

    secret_id = create_test_secret_order(
        db, state, promisor, "密查粮科", "密查粮科私卖", [],
        deadline_months=1,
        affair_declaration={
            "attach": "new", "name": "密令专属查案事务", "origin": "御前密谕查办",
        },
    )
    secret_dossier = db.dossiers.get_for_secret_order(int(secret_id))
    assert secret_dossier is not None
    secret_affair_id = int(secret_dossier["affair_id"] or 0)
    assert secret_affair_id > 0
    assert origin_visible_to(db, db.affairs.origin_ref(secret_affair_id)) is False

    priv2_name = "私密后挂事务"
    priv2, _pc, _pn = _land_minister_promise(
        db, state, promisor=promisor, title="私诺后挂公开案",
        deadline_months=0,
        affair_declaration={
            "attach": "new", "name": priv2_name, "origin": "御前私诺",
        },
    )
    priv2_id = int(db.issues.affair_id_of(int(priv2.commissions.applied[0]["issue_id"])))
    pub_dossier_id = db.create_decree_dossier(
        state, action_type="special_decree", decree_text="公开整饬案",
        target_kind="character", target_id=promisor,
        executor_kind="character", executor_id=promisor,
        payload={"affair_declaration": {
            "attach": "existing", "affair_id": priv2_id,
        }},
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing', "
        "promulgation_decision='promulgated' WHERE id=?",
        (int(pub_dossier_id),),
    )
    db.conn.commit()
    assert int(db.dossiers.affair_id_of(int(pub_dossier_id))) == priv2_id
    assert origin_visible_to(db, "", linked_dossier_id=int(pub_dossier_id)) is True

    roster_only, _rc, _rn = _land_minister_promise(
        db, state, promisor=promisor, title="私诺仅挂名册议题",
        deadline_months=0,
        affair_declaration={
            "attach": "new", "name": "名册隔离事务", "origin": "私诺名册隔离",
        },
    )
    roster_affair_id = int(db.issues.affair_id_of(
        int(roster_only.commissions.applied[0]["issue_id"]),
    ))
    assert origin_visible_to(db, db.affairs.origin_ref(roster_affair_id)) is False

    def _link_issue(roster):
        outcome = settle_delta(
            state, db,
            {"new_issues": [{
                "title": "关联议题",
                "kind": "initiative",
                "origin_kind": "decree",
                "participant_roster": roster,
                "affair_declaration": {
                    "attach": "existing", "affair_id": roster_affair_id,
                },
            }]},
            SettlementContext(
                content=content,
                open_affair_ids_at_input={roster_affair_id},
            ),
        )
        assert outcome.issue.rejected == []
        return max(
            int(row["id"]) for row in db.issues.rows_for_affair(roster_affair_id)
        )

    restricted_issue = _link_issue([{"character_id": promisor, "tier": "知情"}])
    restricted_row = db.conn.execute(
        "SELECT origin_ref FROM issues WHERE id=?", (restricted_issue,),
    ).fetchone()
    assert origin_visible_to(db, str(restricted_row["origin_ref"] or "")) is True
    public_knowledge_ids = {
        int(i["id"]) for i in build_character_knowledge(db, state, "").get("issues") or []
    }
    assert restricted_issue not in public_knowledge_ids

    prepared = prepare_gazette_author_materials(db, state)
    try:
        paths = list_materials(prepared.root)
        assert _paths_have_affair(paths, public_affair_id)
        assert not _paths_have_affair(paths, private_affair_id)
        assert not _paths_have_affair(paths, secret_affair_id)
        assert not _paths_have_affair(paths, roster_affair_id)

        assert _paths_have_affair(paths, priv2_id)
        # 混合公开合法部分：路径在，结构化 title 为空（不锁正文呈现格式）。
        assert public_titles.get(_affair_title_key(priv2_id), None) == ""
        assert public_titles.get(_affair_title_key(priv2_id), None) != priv2_name
    finally:
        release_material_tree(prepared.root)

    public_issue = _link_issue([])
    assert public_issue in {
        int(i["id"]) for i in build_character_knowledge(db, state, "").get("issues") or []
    }
    prepared_public = prepare_gazette_author_materials(db, state)
    try:
        paths = list_materials(prepared_public.root)
        assert _paths_have_affair(paths, roster_affair_id)
        # 空名册公开议题准入后，目录可见；受限议题仍不在公开知识。
        assert restricted_issue not in {
            int(i["id"])
            for i in build_character_knowledge(db, state, "").get("issues") or []
        }
    finally:
        release_material_tree(prepared_public.root)


# ── 材料可读：个人出生名 ────────────────────────────────────


def test_personal_birth_title_visible_to_cohort_not_later_link(game, monkeypatch):
    """同源名册得原名；后来公开／密令关联不解锁出生名。"""
    db, state, content = game
    promisor = "魏忠贤"
    later = "杨嗣昌"
    host, aide, witness = "乔允升", "周延儒", "孙承宗"
    person_titles = _install_person_matter_title_capture(monkeypatch)

    # 先备齐正反输入，再一次 prepare 观测出生人／同源参与人／后来关联者。
    priv_name = "私密后挂事务"
    priv, _c, _n = _land_minister_promise(
        db, state, promisor=promisor, title="私诺后挂公开案",
        deadline_months=0,
        affair_declaration={
            "attach": "new", "name": priv_name, "origin": "御前私诺",
        },
    )
    priv_id = int(db.issues.affair_id_of(int(priv.commissions.applied[0]["issue_id"])))
    priv_key = _affair_title_key(priv_id)
    birth_ref = db.affairs.origin_ref(priv_id)

    later_dossier_id = db.create_decree_dossier(
        state, action_type="special_decree", decree_text="后挂公开交办",
        target_kind="character", target_id=later,
        executor_kind="character", executor_id=later,
        participants=[{"character_id": later, "tier": "主办"}],
        payload={"affair_declaration": {
            "attach": "existing", "affair_id": priv_id,
        }},
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing', "
        "promulgation_decision='promulgated' WHERE id=?",
        (int(later_dossier_id),),
    )
    db.conn.commit()
    assert origin_visible_to(db, birth_ref, later) is False
    assert origin_visible_to(db, birth_ref, promisor) is True

    secret_name = "密令专属查案事务"
    secret_id = create_test_secret_order(
        db, state, promisor, "密查粮科", "密查粮科私卖", [],
        deadline_months=1,
        affair_declaration={
            "attach": "new", "name": secret_name, "origin": "御前密谕查办",
        },
    )
    secret_dossier = db.dossiers.get_for_secret_order(int(secret_id))
    secret_dossier_id = int(secret_dossier["id"])
    secret_affair_id = int(secret_dossier["affair_id"] or 0)
    secret_key = _affair_title_key(secret_affair_id)
    secret_affair_ref = db.affairs.origin_ref(secret_affair_id)
    db.append_decree_dossier_participants(secret_dossier_id, [{
        "character_id": promisor, "tier": "主办", "role": "密访",
    }])
    added = settle_delta(
        state, db,
        {"secret_dossier_participants": [
            {"dossier_id": secret_dossier_id, "character_id": host,
             "tier": "主办", "role": "续办", "delegator_id": promisor},
            {"dossier_id": secret_dossier_id, "character_id": aide,
             "tier": "协办", "role": "随员", "delegator_id": promisor},
            {"dossier_id": secret_dossier_id, "character_id": witness,
             "tier": "知情", "role": "知会", "delegator_id": promisor},
        ]},
        SettlementContext(secret_dossier_ids_at_input={secret_dossier_id}),
    )
    assert added is not None
    for name in (promisor, host, aide, witness):
        assert origin_visible_to(db, secret_affair_ref, name) is True

    later_secret_id = create_test_secret_order(
        db, state, later, "后挂密令", "后挂密查", [],
        deadline_months=1,
        affair_declaration={"attach": "existing", "affair_id": secret_affair_id},
    )
    assert db.dossiers.get_for_secret_order(int(later_secret_id)) is not None
    assert origin_visible_to(db, secret_affair_ref, later) is False
    promise_later_id = create_test_secret_order(
        db, state, later, "挂私诺密令", "挂私诺密查", [],
        deadline_months=1,
        affair_declaration={"attach": "existing", "affair_id": priv_id},
    )
    assert db.dossiers.get_for_secret_order(int(promise_later_id)) is not None
    assert origin_visible_to(db, birth_ref, later) is False

    close_night(db, state, content=content)
    night = open_night(db, state, location="乾清宫", time_of_day="昼")
    for name in (promisor, later, host, aide, witness):
        ensure_summon_enter(db, int(night["id"]), name)
    person_titles.clear()
    prepared = prepare_scene_materials(db, state)
    try:
        paths = list_materials(prepared.root)
        assert _paths_have_affair(paths, priv_id)
        assert person_titles.get(promisor, {}).get(priv_key) == priv_name
        for name in (promisor, host, aide, witness):
            assert person_titles.get(name, {}).get(secret_key) == secret_name
        assert person_titles.get(later, {}).get(priv_key) == ""
        assert person_titles.get(later, {}).get(priv_key) != priv_name
        assert person_titles.get(later, {}).get(secret_key, "") != secret_name
        assert person_titles.get(later, {}).get(priv_key, "") != priv_name
    finally:
        release_material_tree(prepared.root)


# ── 材料可读：到期派生供料 ──────────────────────────────────


def test_due_feeds_respect_issue_roster_and_origin(game):
    """来源公开 + 名册约束：召对开场只收合法读者可见项（作者 due 见 gazette 案）。"""
    db, state, content = game
    promisor = "魏忠贤"
    public_origin = promulgated_policy_origin(db, state, "due-roster-anchor")
    assert origin_visible_to(db, public_origin) is True

    def _due_item(title: str, roster, *, staged: bool):
        item = {
            "title": title,
            "kind": "initiative",
            "origin_kind": "decree",
            "origin_ref": public_origin,
            "stage_text": title,
            "commitment_kind": "until_stop",
            "ongoing_effects": {},
            "participant_roster": roster,
        }
        if staged:
            item["stages"] = [{
                "stage_idx": 0,
                "due_turn": int(state.turn),
                "criterion_text": title,
                "origin_context": title,
            }]
        else:
            item["end_turn"] = int(state.turn)
        return item

    due_land = settle_delta(
        state, db,
        {"new_issues": [
            _due_item("受限一次性到期", [{"character_id": promisor, "tier": "知情"}], staged=False),
            _due_item("公开一次性到期", [], staged=False),
            _due_item("受限分段到期", [{"character_id": promisor, "tier": "知情"}], staged=True),
            _due_item("公开分段到期", [], staged=True),
        ]},
        SettlementContext(content=content),
    )
    assert due_land.issue.rejected == []
    by_title = {
        str(row["title"]): int(row["issue_id"]) for row in due_land.issue.new_issues
    }
    form3_restricted = by_title["受限一次性到期"]
    form3_public = by_title["公开一次性到期"]
    staged_restricted = by_title["受限分段到期"]
    staged_public = by_title["公开分段到期"]

    public_knowledge_due = {
        int(i["id"]) for i in build_character_knowledge(db, state, "").get("issues") or []
    }
    assert form3_public in public_knowledge_due and staged_public in public_knowledge_due
    assert form3_restricted not in public_knowledge_due
    assert staged_restricted not in public_knowledge_due

    due_ledger = {int(i["issue_id"]) for i in list_due_commitments(db, state)}
    assert form3_restricted in due_ledger and form3_public in due_ledger

    written = write_due_staged_commitment_todos(db, state)
    assert written >= 2
    pending_todos = [
        t for t in db.dossiers.list_next_audience_todos(status=TODO_STATUS_PENDING)
        if int(t["commitment_ref"] or 0) in {staged_restricted, staged_public}
    ]
    assert {int(t["commitment_ref"]) for t in pending_todos} == {
        staged_restricted, staged_public,
    }

    night_empty = open_night(db, state, location="乾清宫", time_of_day="昼")
    prepared_empty = prepare_scene_materials(db, state)
    try:
        empty_ids = set(_opening_commitment_ids(prepared_empty.opening))
        assert staged_public in empty_ids
        assert staged_restricted not in empty_ids
    finally:
        release_material_tree(prepared_empty.root)

    ensure_summon_enter(db, int(night_empty["id"]), "杨嗣昌")
    prepared_uninf = prepare_scene_materials(db, state)
    try:
        uninf_ids = set(_opening_commitment_ids(prepared_uninf.opening))
        assert staged_public in uninf_ids
        assert staged_restricted not in uninf_ids
    finally:
        release_material_tree(prepared_uninf.root)

    close_night(db, state, content=content)
    night_p = open_night(db, state, location="乾清宫", time_of_day="昼")
    ensure_summon_enter(db, int(night_p["id"]), promisor)
    prepared_promisor = prepare_scene_materials(db, state)
    try:
        p_ids = set(_opening_commitment_ids(prepared_promisor.opening))
        assert staged_restricted in p_ids
        assert staged_public in p_ids
    finally:
        release_material_tree(prepared_promisor.root)

    still_pending = {
        int(t["commitment_ref"])
        for t in db.dossiers.list_next_audience_todos(status=TODO_STATUS_PENDING)
        if int(t["commitment_ref"] or 0) in {staged_restricted, staged_public}
    }
    assert still_pending == {staged_restricted, staged_public}


# ── 准入与责任边界 ──────────────────────────────────────────


def test_c2_correction_ids_rejected_on_minister_promise(game):
    """C2：自诺不得挂 resolves_rejection_ids；不崩批、不污染 pending_actions。"""
    from ming_sim.applier import Provenance

    db, state, content = game
    promisor = "魏忠贤"
    affair = db.affairs.open(
        name="拒收夹具", origin="test", year=int(state.year),
        period=int(state.period), turn=int(state.turn),
    )
    bad = {
        "origin_ref": f"affair:{affair.id}",
        "account": "不存在", "delta": -1,
        "category": "待修正", "reason": "原旨",
    }
    dispatch_declaration(
        db, state, {"effects": {"economy_moves": [bad]}},
        source=Provenance.player_decree,
    )
    rid = int(db.conn.execute(
        "SELECT id FROM rejection_reports ORDER BY id DESC LIMIT 1",
    ).fetchone()["id"])

    pending_before = {
        int(r["id"]): str(r["payload_json"] or "")
        for r in db.conn.execute("SELECT id, payload_json FROM pending_actions").fetchall()
    }

    result, _chat_id, _nid = _land_minister_promise(
        db, state, promisor=promisor, title="自诺不得修正旨意",
        extra={"resolves_rejection_ids": [rid]},
    )
    assert result.commissions.applied == []
    assert result.commissions.rejected
    assert all(
        r.category in {"invalid_shape", "hallucinated_id", "missing_ref"}
        for r in result.commissions.rejected
    )
    pending_after = {
        int(r["id"]): str(r["payload_json"] or "")
        for r in db.conn.execute("SELECT id, payload_json FROM pending_actions").fetchall()
    }
    assert pending_after == pending_before
    assert _active_commitments_for(db, promisor) == []


def _mutex_commission_pair(db, state, promisor: str, case: str):
    """三种互斥输入的最小 (mixed, legal, words, expect) 表；公共分派链复用。"""
    from ming_sim.covert_levy import PROHIBITION_ACTION

    if case == "secret_order":
        mixed = {
            "text": "密办并自诺",
            "secret_order": {
                "title": "密查", "content": "密查粮科", "assignee": promisor,
                "tags": [], "deadline_months": 1,
                "covert_task": dict(TYPED_COVERT_TASK),
            },
            "minister_promise": _promise_item(promisor, "臣自诺查清"),
        }
        legal = {
            "text": "臣另诺整饬边饷",
            "minister_promise": _promise_item(promisor, "整饬边饷"),
        }
        return mixed, legal, "尔有何话说", {
            "applied_kind": "minister_promise",
            "forbidden_pending_kinds": {"secret_order"},
            "promise_count": 1,
        }

    if case == "imperial_push":
        dossier_id = db.create_decree_dossier(
            state, action_type="special_decree", decree_text="待强推案",
            target_kind="character", target_id=promisor,
            executor_kind="character", executor_id=promisor,
        )
        mixed = {
            "text": "着即督办，臣自诺复命",
            "target_dossier_id": int(dossier_id),
            "minister_promise": _promise_item(promisor, "臣自诺复命"),
        }
        legal = {"text": "另案着即督办", "target_dossier_id": int(dossier_id)}
        return mixed, legal, "着即督办", {
            "applied_kind": "directive",
            "pending_target_dossier_id": int(dossier_id),
            "promise_count": 0,
        }

    # prohibit_levy：互斥在下游暴露生命周期之前成立，无需建暴露场面。
    mixed = {
        "text": "禁摊并自诺",
        "dossier_action_type": PROHIBITION_ACTION,
        "target_id": 1,
        "minister_promise": _promise_item(promisor, "臣自诺禁后复命"),
    }
    legal = {
        "text": "臣另诺边饷",
        "minister_promise": _promise_item(promisor, "边饷"),
    }
    return mixed, legal, "禁摊并自诺", {
        "applied_kind": "minister_promise",
        "forbidden_pending_kinds": {"directive"},
        "promise_count": 1,
    }


@pytest.mark.parametrize("case", ["secret_order", "imperial_push", "prohibit_levy"])
def test_sole_commission_actions_reject_when_mixed_with_minister_promise(game, case):
    """专有动作与自诺同件：统一准入拒收；同批合法兄弟项仍落。"""
    db, state, content = game
    promisor = "魏忠贤"
    mixed, legal, words, expect = _mutex_commission_pair(db, state, promisor, case)
    result, chat_id, _ = _hall_commission_batch(
        db, state, promisor, [mixed, legal], words=words,
    )
    assert len(result.commissions.rejected) == 1
    assert result.commissions.rejected[0].category == "invalid_shape"
    assert len(result.commissions.applied) == 1
    assert result.commissions.applied[0].get("kind") == expect["applied_kind"]

    pending_rows = list(db.conn.execute(
        "SELECT kind, payload_json FROM pending_actions WHERE source_chat_turn_id=?",
        (chat_id,),
    ).fetchall())
    pending_kinds = {str(r["kind"]) for r in pending_rows}
    for kind in expect.get("forbidden_pending_kinds") or ():
        assert kind not in pending_kinds
    if "pending_target_dossier_id" in expect:
        assert len(pending_rows) == 1
        assert int(json.loads(pending_rows[0]["payload_json"]).get(
            "target_dossier_id") or 0) == expect["pending_target_dossier_id"]
    assert int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM issues WHERE origin_kind='minister_promise'",
    ).fetchone()["n"]) == int(expect["promise_count"])


def test_c5_minister_promise_excluded_from_imperial_breach_scan(game):
    """C5：罢免自诺承诺人不得写皇命违诺哭谏/辜负边。"""
    db, state, content = game
    promisor = "魏忠贤"
    result, _c, _n = _land_minister_promise(
        db, state, promisor=promisor, title="臣下自诺非皇命",
        deadline_months=0,
    )
    issue_id = int(result.commissions.applied[0]["issue_id"])
    edges_before = int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM relation_edge_events",
    ).fetchone()["n"])

    db.conn.execute(
        "UPDATE characters SET status='dismissed' WHERE name=?", (promisor,),
    )
    db.conn.commit()
    written = scan_and_write_breach_pleas(db, state)

    linked = [
        t for t in db.dossiers.list_next_audience_todos()
        if int(t.get("commitment_ref") or 0) == issue_id
        and str(t.get("entry_kind") or "") == "midcourse_breach_plea"
    ]
    assert linked == []
    if written:
        written_refs = {
            int(t.get("commitment_ref") or 0)
            for t in db.dossiers.list_next_audience_todos()
            if int(t["id"]) in {int(x) for x in written}
        }
        assert issue_id not in written_refs
    edges_after = int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM relation_edge_events",
    ).fetchone()["n"])
    assert edges_after == edges_before
    assert str(db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (issue_id,),
    ).fetchone()["status"]) == "active"
