"""#1835 转译输出契约与分派器（C0，铺路）。

受控声明桩（模拟转译 LLM 一次产出）直接喂 ``dispatch_declaration``，验证：
真实分派链落到既有暂存（pending_actions）与 R1-R3 新记录，无漏项（AC1）；
一句话同时含拟旨 + 拨帑时只成一份载荷、只落一条 pending_actions（AC2）；
声明里引用不存在实体的项逐项拒收留痕，不带走同批其余合法项（AC3）；
召对与过月两处调用同一个 dispatch_declaration，没有第二份同构逻辑（AC4）。
"""

from __future__ import annotations

import json

import pytest

from ming_sim.content import GameContent
from ming_sim.declaration_dispatch import dispatch_declaration
import ming_sim.issues as issues_mod
from ming_sim.public_sayings import list_public_sayings


def _minister(db):
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()
    assert row is not None
    return str(row["name"])


def _army_id(db) -> str:
    row = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()
    assert row is not None
    return str(row["id"])


def test_stub_declaration_lands_on_existing_staging_and_new_records_without_missing_items(game):
    db, state, _ = game
    minister = _minister(db)
    # 既有暂存：上一轮已经暂存、本轮转译声明它「应允」。
    pre_staged_id = db.stage_pending_action(
        int(state.turn), "directive", "拟旨", minister, {"text": "已暂存旧旨"},
    )

    declaration = {
        "commissions": [{"text": "遣使赈济陕西"}],
        "promises": [{"action_id": pre_staged_id, "decision": "应允"}],
        "textual_facts": [{
            "subject_kind": "character", "subject_id": minister,
            "body": "抱恙数日，仍可视事",
        }],
        "public_sayings": [{
            "body": "坊间传户部已备赈灾银", "involved_characters": [minister],
        }],
    }

    result = dispatch_declaration(db, state, declaration, minister_name=minister)

    assert len(result.commissions.applied) == 1 and result.commissions.rejected == []
    assert len(result.promises.applied) == 1 and result.promises.rejected == []
    assert len(result.textual_facts.applied) == 1 and result.textual_facts.rejected == []
    assert len(result.public_sayings.applied) == 1 and result.public_sayings.rejected == []

    approved_row = db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (pre_staged_id,),
    ).fetchone()
    assert approved_row["night_approved"] == 1

    facts = db.textual_facts.readable_materials(subject_kind="character", subject_id=minister)
    assert [f.body for f in facts] == ["抱恙数日，仍可视事"]

    sayings = list_public_sayings(db, involved_character=minister)
    assert len(sayings) == 1
    assert sayings[0]["body"] == "坊间传户部已备赈灾银"


def test_commission_with_draft_and_grant_for_same_money_is_one_payload_one_row(game):
    db, state, _ = game
    minister = _minister(db)
    army_id = _army_id(db)
    before = db.conn.execute("SELECT COUNT(*) c FROM pending_actions").fetchone()["c"]

    declaration = {
        "commissions": [{
            "text": "拨国库十五万两协饷该军",
            "grant": {
                "amount": 150000, "account": "国库", "purpose": "补饷",
                "target_kind": "army", "target_id": army_id,
            },
        }],
    }
    result = dispatch_declaration(db, state, declaration, minister_name=minister)

    assert result.commissions.rejected == []
    assert len(result.commissions.applied) == 1
    after = db.conn.execute("SELECT COUNT(*) c FROM pending_actions").fetchone()["c"]
    assert after - before == 1

    row = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?",
        (result.commissions.applied[0]["id"],),
    ).fetchone()
    payload = json.loads(row["payload_json"])
    assert payload["text"] == "拨国库十五万两协饷该军"
    assert payload["amount"] == 150000
    assert payload["account"] == "国库"
    assert payload["target_id"] == army_id


def test_reference_to_nonexistent_entity_is_rejected_without_killing_sibling_item(game, monkeypatch):
    """AC3：单项拒收不牵连同批合法项；J1：拒收落进既有 rejection_reports 单一
    真源（DB 行），不只活在本次调用的返回值里；直接分派的 section 写入与拒收
    flush 共享同一个真实事务边界——大理寺判词打回：flush 本身失败时同批已
    处理的合法 sibling 也不得已经落库（不能只把 atomic 包住 flush，section
    分派副作用须在同一事务里）。"""
    from ming_sim.applier import RejectionCollector

    db, state, _ = game
    minister = _minister(db)

    declaration = {
        "textual_facts": [
            {"subject_kind": "character", "subject_id": "子虚乌有之人", "body": "凭空捏造"},
            {"subject_kind": "character", "subject_id": minister, "body": "如实记事"},
        ],
        "registrations": [{
            "name": "李若璉補", "office": "锦衣卫百户", "office_type": "武职",
        }],
    }

    # flush 失败路径：制造 rejection_reports flush 失败，断言合法 sibling
    # 未落库、拒收表也没有半条行（同批要么都进、要么都不进）。
    real_flush_to_db = RejectionCollector.flush_to_db

    def _boom(self, db_arg):
        raise RuntimeError("simulated flush_to_db failure")

    monkeypatch.setattr(RejectionCollector, "flush_to_db", _boom)
    with pytest.raises(RuntimeError, match="simulated flush_to_db failure"):
        dispatch_declaration(db, state, declaration, minister_name=minister)
    monkeypatch.setattr(RejectionCollector, "flush_to_db", real_flush_to_db)

    assert db.textual_facts.readable_materials(
        subject_kind="character", subject_id=minister,
    ) == ()
    assert db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='rejection_reports'",
    ).fetchone() is None
    assert db.conn.execute(
        "SELECT 1 FROM characters WHERE name=?", ("李若璉補",),
    ).fetchone() is None
    assert "李若璉補" not in db.content.characters

    # 恢复正常后，继续断成功路径：合法 sibling 落库、拒收落 durable（原有断言）。
    result = dispatch_declaration(db, state, declaration, minister_name=minister)

    assert len(result.textual_facts.rejected) == 1
    assert result.textual_facts.rejected[0].category == "hallucinated_id"
    assert result.textual_facts.rejected[0].item["subject_id"] == "子虚乌有之人"
    assert len(result.textual_facts.applied) == 1

    facts = db.textual_facts.readable_materials(subject_kind="character", subject_id=minister)
    assert [f.body for f in facts] == ["如实记事"]
    assert db.textual_facts.readable_materials(
        subject_kind="character", subject_id="子虚乌有之人",
    ) == ()

    rows = db.conn.execute(
        "SELECT section, category, item_json FROM rejection_reports WHERE turn=?",
        (int(state.turn),),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["section"] == "textual_facts"
    assert rows[0]["category"] == "hallucinated_id"
    assert "子虚乌有之人" in rows[0]["item_json"]
    assert db.conn.execute(
        "SELECT 1 FROM characters WHERE name=?", ("李若璉補",),
    ).fetchone() is not None
    assert "李若璉補" in db.content.characters


def test_unknown_top_level_section_is_rejected_durably_without_dropping_sibling(game):
    """J2：拼错/未知的顶层 section 键不静默漏项，走同一 durable 拒收单一真源；
    合法兄弟 section 照常落地（AC1 无漏项）。"""
    db, state, _ = game
    minister = _minister(db)

    declaration = {
        "textual_facts": [{
            "subject_kind": "character", "subject_id": minister, "body": "如实记事",
        }],
        "textual_fact": [{"subject_kind": "character", "subject_id": minister, "body": "拼错字段名"}],
    }
    result = dispatch_declaration(db, state, declaration, minister_name=minister)

    assert len(result.textual_facts.applied) == 1
    assert result.textual_facts.rejected == []

    rows = db.conn.execute(
        "SELECT section, category FROM rejection_reports WHERE turn=?",
        (int(state.turn),),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["section"] == "textual_fact"
    assert rows[0]["category"] == "invalid_shape"


def test_promise_refuse_withdraws_staged_action_and_missing_action_id_is_rejected(game):
    db, state, _ = game
    minister = _minister(db)
    staged_id = db.stage_pending_action(
        int(state.turn), "directive", "拟旨", minister, {"text": "待反悔的旧旨"},
    )

    declaration = {
        "promises": [
            {"action_id": staged_id, "decision": "拒绝"},
            {"action_id": staged_id + 100000, "decision": "应允"},
        ],
    }
    result = dispatch_declaration(db, state, declaration, minister_name=minister)

    assert len(result.promises.applied) == 1
    assert result.promises.applied[0] == {"action_id": staged_id, "decision": "拒绝"}
    assert len(result.promises.rejected) == 1
    assert result.promises.rejected[0].category == "missing_ref"

    row = db.conn.execute(
        "SELECT id FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()
    assert row is None


def test_promise_referencing_action_id_belonging_to_another_night_is_rejected(game):
    """AC3 的引用不存在实体拒收，对「id 真实存在但不属本声明所在夜」同样成立
    （ADR 0155：转译只认「本夜暂存清单」）——不能因为 id 恰巧撞上另一夜真实
    存在的暂存动作就误批它。"""
    db, state, _ = game
    minister = _minister(db)
    other_night_id = 987654321
    staged_id = db.stage_pending_action(
        int(state.turn), "directive", "拟旨", minister, {"text": "另一夜的暂存"},
    )
    db.conn.execute(
        "UPDATE pending_actions SET night_id=? WHERE id=?", (other_night_id, staged_id),
    )
    db.conn.commit()

    declaration = {"promises": [{"action_id": staged_id, "decision": "应允"}]}
    result = dispatch_declaration(
        db, state, declaration, minister_name=minister, night_id=0,
    )

    assert result.promises.applied == []
    assert len(result.promises.rejected) == 1
    assert result.promises.rejected[0].category == "missing_ref"
    row = db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()
    assert row["night_approved"] == 0


def test_on_scene_person_status_change_lands_and_rejects_nonexistent_person(game):
    db, state, _ = game
    minister = _minister(db)

    declaration = {
        "on_scene_facts": [
            {"name": minister, "动作": "处置", "status": "imprisoned", "reason": "下狱待勘"},
            {"name": "子虚乌有之人", "动作": "处置", "status": "dead", "reason": "凭空捏造"},
        ],
    }
    result = dispatch_declaration(db, state, declaration, minister_name=minister)

    assert len(result.on_scene_facts.applied) == 1
    assert len(result.on_scene_facts.rejected) == 1
    status, _ = db.get_character_status(minister)
    assert status == "imprisoned"


def test_on_scene_fact_attaches_declared_affair_and_rejects_unopened_affair(game):
    """各自所属事务：on_scene_facts 挂 person_logs.origin_ref（affair:<id>），
    不写 characters 单例 affair_id；引用不存在事务的项在人物变更真正发生前
    就被拒收（不产生半成品状态变更）。"""
    db, state, _ = game
    minister = _minister(db)
    affair = db.affairs.open(
        name="宁远护送", origin="拨银、调将、派兵去宁远",
        year=state.year, period=state.period, turn=state.turn,
    )

    ok = dispatch_declaration(db, state, {
        "on_scene_facts": [{
            "name": minister, "动作": "处置", "status": "imprisoned", "reason": "下狱待勘",
            "affair_declaration": {"attach": "existing", "affair_id": affair.id},
        }],
    })
    assert len(ok.on_scene_facts.applied) == 1
    assert "affair_attach_error" not in ok.on_scene_facts.applied[0]
    log = db.conn.execute(
        "SELECT origin_ref FROM person_logs WHERE person_name=? ORDER BY id DESC LIMIT 1",
        (minister,),
    ).fetchone()
    assert log["origin_ref"] == db.affairs.origin_ref(affair.id)
    # characters.affair_id is not the person-change provenance.
    row = db.conn.execute(
        "SELECT affair_id FROM characters WHERE name=?", (minister,),
    ).fetchone()
    assert int(row["affair_id"] or 0) == 0

    other_minister = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND name!=? ORDER BY name LIMIT 1",
        (minister,),
    ).fetchone()["name"]
    bad = dispatch_declaration(db, state, {
        "on_scene_facts": [{
            "name": other_minister, "动作": "处置", "status": "imprisoned", "reason": "…",
            "affair_declaration": {"attach": "existing", "affair_id": affair.id + 999999},
        }],
    })
    assert bad.on_scene_facts.applied == []
    assert len(bad.on_scene_facts.rejected) == 1
    status, _ = db.get_character_status(other_minister)
    assert status != "imprisoned"  # 拒收在变更发生前，不留半成品


def test_on_scene_fact_multi_affair_person_changes_keep_each_event_provenance(game):
    """同一人物可先后参与多事务：每次人物变动挂各自 durable origin_ref，
    后续真实变更不得因首个 affair_id 回滚。受控顺序污染仍须用当前局 content。"""
    db, state, content = game
    polluted = GameContent.load()
    assert polluted is not content
    issues_mod.bind_content(polluted)
    try:
        minister = _minister(db)
        affair_a = db.affairs.open(
            name="宁远护送", origin="拨银、调将、派兵去宁远",
            year=state.year, period=state.period, turn=state.turn,
        )
        affair_b = db.affairs.open(
            name="蓟镇募兵", origin="募兵备边",
            year=state.year, period=state.period, turn=state.turn,
        )
        first = dispatch_declaration(db, state, {
            "on_scene_facts": [{
                "name": minister, "动作": "处置", "status": "imprisoned", "reason": "下狱待勘",
                "affair_declaration": {"attach": "existing", "affair_id": affair_a.id},
            }],
        })
        assert len(first.on_scene_facts.applied) == 1
        status_before, _ = db.get_character_status(minister)
        assert status_before == "imprisoned"

        second = dispatch_declaration(db, state, {
            "on_scene_facts": [{
                "name": minister, "动作": "处置", "status": "dead", "reason": "另案牵连",
                "affair_declaration": {"attach": "existing", "affair_id": affair_b.id},
            }],
        })
        assert len(second.on_scene_facts.applied) == 1
        status_after, _ = db.get_character_status(minister)
        assert status_after == "dead"
        refs = [
            row["origin_ref"]
            for row in db.conn.execute(
                "SELECT origin_ref FROM person_logs WHERE person_name=? ORDER BY id",
                (minister,),
            ).fetchall()
        ]
        assert db.affairs.origin_ref(affair_a.id) in refs
        assert db.affairs.origin_ref(affair_b.id) in refs
        assert content.characters[minister].status == "dead"
        assert db.content.characters[minister].status == "dead"
    finally:
        issues_mod.bind_content(content)


def test_same_declaration_registration_establishes_target_before_dependent_facts(game):
    """同声明体内先入册再写依赖人物的文字事实；畸形 affair_declaration 进单项拒收；
    协饷失败按 account/purpose 枚举 vs 缺字段 vs 不存在军队 分型。"""
    db, state, _ = game
    minister = _minister(db)
    army = db.conn.execute("SELECT id FROM armies ORDER BY id LIMIT 1").fetchone()
    army_id = str(army["id"]) if army is not None else "jingying"
    result = dispatch_declaration(db, state, {
        "registrations": [{
            "name": "新入册人甲", "office": "锦衣卫百户", "office_type": "锦衣卫",
        }],
        "textual_facts": [
            {"subject_kind": "character", "subject_id": "新入册人甲", "body": "同声明入册后事实"},
            {
                "subject_kind": "character", "subject_id": minister, "body": "坏事务形状",
                "affair_declaration": "bad",
            },
        ],
        "commissions": [
            {
                "text": "拨饷坏账户",
                "grant": {
                    "amount": 1000, "account": "不是国库", "purpose": "补饷",
                    "target_kind": "army", "target_id": army_id,
                },
            },
            {
                "text": "拨饷缺目标",
                "grant": {
                    "amount": 1000, "account": "国库", "purpose": "补饷",
                    "target_kind": "army", "target_id": "",
                },
            },
            {
                "text": "拨饷幽灵军",
                "grant": {
                    "amount": 1000, "account": "国库", "purpose": "补饷",
                    "target_kind": "army", "target_id": "ghost-army-no-such",
                },
            },
        ],
    }, minister_name=minister)
    assert result.registrations.applied == [{"name": "新入册人甲"}]
    assert any(
        isinstance(f, dict) and f.get("subject_id") == "新入册人甲"
        for f in result.textual_facts.applied
    )
    assert any(
        r.category == "invalid_shape" and r.item.get("subject_id") == minister
        for r in result.textual_facts.rejected
    )
    facts = db.textual_facts.readable_materials(
        subject_kind="character", subject_id="新入册人甲",
    )
    assert [f.body for f in facts] == ["同声明入册后事实"]
    cats = {r.category for r in result.commissions.rejected}
    assert "invalid_enum" in cats  # bad account
    assert "invalid_shape" in cats  # missing target_id
    assert "hallucinated_id" in cats  # ghost army


def test_presence_lands_with_declared_body_verbatim_no_synthesized_text(game):
    """P6/P7：落账正文必须是声明自带的原文，代码不得拼「某某入殿」这类模板句。"""
    db, state, _ = game
    minister = _minister(db)
    from ming_sim.audience_night import open_night

    night = open_night(db, state)
    night_id = int(night["id"])
    declared_body = "内侍高唱，乔尚书趋步入殿，绯袍犹带风尘。"

    declaration = {
        "presence": [{"person_name": minister, "effect": "enter", "body": declared_body}],
    }
    result = dispatch_declaration(db, state, declaration, night_id=night_id)
    assert result.presence.rejected == []
    assert len(result.presence.applied) == 1

    row = db.conn.execute(
        "SELECT body FROM story_ledger_entries WHERE id=?",
        (result.presence.applied[0]["id"],),
    ).fetchone()
    assert row["body"] == declared_body  # 原样落账，代码没有拼接/替换成模板句


def test_presence_rejects_nonexistent_person_without_polluting_ledger(game):
    """AC3：有效夜下引用不存在的人物一样要逐项拒收，不能真落进 story_ledger_entries。"""
    db, state, _ = game
    from ming_sim.audience_night import open_night

    night = open_night(db, state)
    night_id = int(night["id"])
    before = db.conn.execute(
        "SELECT COUNT(*) c FROM story_ledger_entries WHERE night_id=?", (night_id,),
    ).fetchone()["c"]

    declaration = {
        "presence": [{"person_name": "子虚乌有之人", "effect": "enter", "body": "凭空捏造之人入殿。"}],
    }
    result = dispatch_declaration(db, state, declaration, night_id=night_id)

    assert result.presence.applied == []
    assert len(result.presence.rejected) == 1
    assert result.presence.rejected[0].category == "hallucinated_id"
    after = db.conn.execute(
        "SELECT COUNT(*) c FROM story_ledger_entries WHERE night_id=?", (night_id,),
    ).fetchone()["c"]
    assert after == before  # 没有孤儿账落进去


def test_presence_with_no_night_context_is_rejected_as_missing_ref(game):
    db, state, _ = game
    minister = _minister(db)

    declaration = {
        "presence": [{"person_name": minister, "effect": "enter", "body": "入殿。"}],
    }
    result = dispatch_declaration(db, state, declaration, night_id=0)
    assert result.presence.applied == []
    assert len(result.presence.rejected) == 1
    assert result.presence.rejected[0].category == "missing_ref"


def test_scene_fact_speaker_segment_lands_verbatim_and_rejects_bad_audibility_and_ghost_person(game):
    db, state, _ = game
    minister = _minister(db)
    from ming_sim.audience_night import open_night

    night = open_night(db, state)
    night_id = int(night["id"])

    declaration = {
        "scene_facts": [
            {"body": "臣领旨。", "audibility": "殿上公开", "person_names": [minister]},
            {"body": "低声私语", "audibility": "非法可闻性"},
            {"body": "凭空捏造之人插话。", "audibility": "殿上公开", "person_names": ["子虚乌有之人"]},
        ],
    }
    before = db.conn.execute(
        "SELECT COUNT(*) c FROM story_ledger_entries WHERE night_id=?", (night_id,),
    ).fetchone()["c"]
    result = dispatch_declaration(db, state, declaration, night_id=night_id)
    after = db.conn.execute(
        "SELECT COUNT(*) c FROM story_ledger_entries WHERE night_id=?", (night_id,),
    ).fetchone()["c"]

    assert len(result.scene_facts.applied) == 1
    assert after - before == 1  # 只有合法项真落账，坏项不留孤儿账
    categories = {r.category for r in result.scene_facts.rejected}
    assert categories == {"invalid_shape", "hallucinated_id"}

    row = db.conn.execute(
        "SELECT body FROM story_ledger_entries WHERE id=?",
        (result.scene_facts.applied[0]["id"],),
    ).fetchone()
    assert row["body"] == "臣领旨。"


def test_edge_event_lands_and_categorizes_unknown_kind_and_hallucinated_person_differently(game):
    db, state, _ = game
    ministers = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 2"
    ).fetchall()
    assert len(ministers) == 2
    a, b = str(ministers[0]["name"]), str(ministers[1]["name"])

    declaration = {
        "edge_events": [
            {"source": a, "target": b, "event_kind": "撑腰", "context": "当殿举荐"},
            {"source": a, "target": b, "event_kind": "不存在的类目", "context": "…"},
            {"source": a, "target": "子虚乌有之人", "event_kind": "撑腰", "context": "…"},
            {"source": a, "target": b, "event_kind": "撑腰", "context": ""},
        ],
    }
    result = dispatch_declaration(db, state, declaration)
    assert len(result.edge_events.applied) == 1
    by_category = {r.category for r in result.edge_events.rejected}
    assert by_category == {"invalid_enum", "hallucinated_id", "invalid_shape"}


def test_edge_event_attaches_declared_affair(game):
    """各自所属事务：relation_edge_events 是整数主键，直接复用 AffairStore
    通用指针（attach_pointer）绑事务。"""
    db, state, _ = game
    ministers = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 2"
    ).fetchall()
    a, b = str(ministers[0]["name"]), str(ministers[1]["name"])
    affair = db.affairs.open(
        name="宁远护送", origin="拨银、调将、派兵去宁远",
        year=state.year, period=state.period, turn=state.turn,
    )

    result = dispatch_declaration(db, state, {
        "edge_events": [{
            "source": a, "target": b, "event_kind": "撑腰", "context": "当殿举荐",
            "affair_declaration": {"attach": "existing", "affair_id": affair.id},
        }],
    })
    assert len(result.edge_events.applied) == 1
    row = db.conn.execute(
        "SELECT affair_id FROM relation_edge_events WHERE id=?",
        (result.edge_events.applied[0]["id"],),
    ).fetchone()
    assert row["affair_id"] == affair.id


def test_edge_event_conflicting_affair_pointer_is_rejected_first_binding_kept(game):
    """同一条边事件（去重键相同）第二次声明指向不同事务：指针冲突时该项整块
    回滚、不误报为 applied，也不改动第一次已绑的事务指针（写事件与绑指针在
    同一 atomic 块内）。"""
    db, state, _ = game
    ministers = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 2"
    ).fetchall()
    a, b = str(ministers[0]["name"]), str(ministers[1]["name"])
    affair_a = db.affairs.open(
        name="宁远护送", origin="拨银、调将、派兵去宁远",
        year=state.year, period=state.period, turn=state.turn,
    )
    affair_b = db.affairs.open(
        name="蓟镇募兵", origin="募兵备边",
        year=state.year, period=state.period, turn=state.turn,
    )
    same_event = {"source": a, "target": b, "event_kind": "撑腰", "context": "当殿举荐"}

    first = dispatch_declaration(db, state, {
        "edge_events": [{
            **same_event,
            "affair_declaration": {"attach": "existing", "affair_id": affair_a.id},
        }],
    })
    assert len(first.edge_events.applied) == 1
    event_id = first.edge_events.applied[0]["id"]

    second = dispatch_declaration(db, state, {
        "edge_events": [{
            **same_event,
            "affair_declaration": {"attach": "existing", "affair_id": affair_b.id},
        }],
    })
    assert second.edge_events.applied == []
    assert len(second.edge_events.rejected) == 1
    assert second.edge_events.rejected[0].category == "invalid_state"

    row = db.conn.execute(
        "SELECT affair_id FROM relation_edge_events WHERE id=?", (event_id,),
    ).fetchone()
    assert row["affair_id"] == affair_a.id


def test_protagonist_lands_and_rejects_nonexistent_person(game):
    """J7：protagonist 无既有落库口，返回的是 projected 校验结果（`validated`），
    不冒称 `SectionResult.applied`（那意味着已落库）。"""
    db, state, _ = game
    minister = _minister(db)

    ok = dispatch_declaration(db, state, {"protagonist": {"person_name": minister}})
    assert ok.protagonist.validated == {"person_name": minister}
    assert ok.protagonist.rejected == []

    bad = dispatch_declaration(db, state, {"protagonist": {"person_name": "子虚乌有之人"}})
    assert bad.protagonist.validated is None
    assert bad.protagonist.rejected[0].category == "hallucinated_id"


def test_registration_adds_new_person_to_roster_and_rejects_existing_name(game):
    db, state, _ = game
    minister = _minister(db)

    declaration = {
        "registrations": [
            {"name": "李若璉補", "office": "锦衣卫百户", "office_type": "武职", "source": "historical"},
            {"name": minister, "office": "户部尚书", "office_type": "文职"},
        ],
    }
    result = dispatch_declaration(db, state, declaration)

    assert len(result.registrations.applied) == 1
    assert result.registrations.applied[0] == {"name": "李若璉補"}
    assert len(result.registrations.rejected) == 1
    assert result.registrations.rejected[0].category == "invalid_state"

    row = db.conn.execute(
        "SELECT status, office FROM characters WHERE name=?", ("李若璉補",),
    ).fetchone()
    assert row is not None
    assert row["status"] == "active"
    assert row["office"] == "锦衣卫百户"
    assert "李若璉補" in db.content.characters


def test_registration_attaches_declared_affair(game):
    db, state, _ = game
    affair = db.affairs.open(
        name="宁远护送", origin="拨银、调将、派兵去宁远",
        year=state.year, period=state.period, turn=state.turn,
    )

    result = dispatch_declaration(db, state, {
        "registrations": [{
            "name": "李若璉補", "office": "锦衣卫百户", "office_type": "武职",
            "affair_declaration": {"attach": "existing", "affair_id": affair.id},
        }],
    })
    assert result.registrations.applied == [{"name": "李若璉補"}]
    row = db.conn.execute(
        "SELECT affair_id FROM characters WHERE name=?", ("李若璉補",),
    ).fetchone()
    assert row["affair_id"] == affair.id


def test_staged_declaration_discard_and_idempotent_settle_in_decree_order(game):
    """ADR 0157 步骤 1-2：暂存不落账，作废后不结算，按给定顺序（不是暂存顺序）
    逐旨一提交且幂等；J6：decree:1/decree:3 均存活且刻意用与暂存相反的结算
    顺序，断言落账顺序服从传入的 `decree_refs_in_order`——若结算把迭代顺序
    反了，facts 顺序会翻转、本测试变红（变异真跑）。decree:2 覆盖作废分支。
    J1：decree:3 里混一条引用不存在人物的项，断言其拒收在暂存/结算路径下
    同样落进 durable 的 rejection_reports（重新查库而非只看返回值），幂等
    重结算不重复落库。"""
    from ming_sim.declaration_dispatch import (
        discard_staged_declaration,
        settle_staged_declarations_in_decree_order,
        stage_declaration,
    )
    from ming_sim.entities.staged_declaration import DecreeAlreadySettled

    db, state, _ = game
    minister = _minister(db)

    stage_declaration(
        db, decree_ref="decree:1",
        declaration={"textual_facts": [{
            "subject_kind": "character", "subject_id": minister, "body": "旨一：暂存中",
        }]},
        turn=int(state.turn),
    )
    stage_declaration(
        db, decree_ref="decree:2",
        declaration={"textual_facts": [{
            "subject_kind": "character", "subject_id": minister, "body": "旨二：即将作废",
        }]},
        turn=int(state.turn),
    )
    stage_declaration(
        db, decree_ref="decree:3",
        declaration={"textual_facts": [
            {"subject_kind": "character", "subject_id": minister, "body": "旨三：后到之旨"},
            {"subject_kind": "character", "subject_id": "子虚乌有之人", "body": "旨三：凭空捏造"},
        ]},
        turn=int(state.turn),
    )
    # 暂存不落账。
    assert db.textual_facts.readable_materials(
        subject_kind="character", subject_id=minister,
    ) == ()

    discarded = discard_staged_declaration(db, "decree:2")
    assert discarded == 1
    with pytest.raises(DecreeAlreadySettled):
        stage_declaration(
            db, decree_ref="decree:2",
            declaration={"textual_facts": [{
                "subject_kind": "character", "subject_id": minister, "body": "resurrected",
            }]},
            turn=int(state.turn),
        )
    restaged = db.conn.execute(
        "SELECT COUNT(*) c FROM staged_declarations "
        "WHERE decree_ref='decree:2' AND status='staged'",
    ).fetchone()
    assert restaged["c"] == 0

    # discard-before-stage tombstone: no product row yet, late stage still rejected.
    ghost = discard_staged_declaration(db, "decree:ghost")
    assert ghost == 0
    with pytest.raises(DecreeAlreadySettled):
        stage_declaration(
            db, decree_ref="decree:ghost",
            declaration={"textual_facts": [{
                "subject_kind": "character", "subject_id": minister, "body": "too late",
            }]},
            turn=int(state.turn),
        )

    # 刻意把 decree:3 排在 decree:1 之前——与暂存先后（1→2→3）相反，用来断言
    # 结算真的服从传入顺序，而不是暂存插入顺序。
    results = settle_staged_declarations_in_decree_order(
        db, state, ["decree:3", "decree:1"],
    )
    assert "decree:2" not in results  # 全部作废，静默跳过
    assert len(results["decree:3"].textual_facts.applied) == 1
    assert len(results["decree:3"].textual_facts.rejected) == 1
    assert results["decree:3"].textual_facts.rejected[0].category == "hallucinated_id"
    assert len(results["decree:1"].textual_facts.applied) == 1

    facts = db.textual_facts.readable_materials(subject_kind="character", subject_id=minister)
    # 落账顺序 = 传入的结算顺序（先 decree:3 后 decree:1），不是暂存顺序。
    assert [f.body for f in facts] == ["旨三：后到之旨", "旨一：暂存中"]

    rows = db.conn.execute(
        "SELECT section, category, item_json FROM rejection_reports WHERE turn=?",
        (int(state.turn),),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["section"] == "textual_facts"
    assert rows[0]["category"] == "hallucinated_id"
    assert "子虚乌有之人" in rows[0]["item_json"]

    # 幂等：再结算一次不重复落账、不重复拒收。
    again = settle_staged_declarations_in_decree_order(db, state, ["decree:3", "decree:1"])
    assert again == {}
    facts_after = db.textual_facts.readable_materials(subject_kind="character", subject_id=minister)
    assert [f.body for f in facts_after] == ["旨三：后到之旨", "旨一：暂存中"]
    rows_after = db.conn.execute(
        "SELECT COUNT(*) c FROM rejection_reports WHERE turn=?", (int(state.turn),),
    ).fetchone()
    assert rows_after["c"] == 1


def test_staging_onto_already_settled_decree_ref_is_rejected_not_stranded(game):
    """已结算的 decree_ref 不能再暂存——否则那条新 staged 行会永远没有机会被
    结算或拒收（is_settled 一旦为真，settle 整体跳过该 ref），造成静默 stranded
    状态。改旨应发新的 decree_ref，不是向已终结的旧 ref 追加。"""
    from ming_sim.entities.staged_declaration import DecreeAlreadySettled
    from ming_sim.declaration_dispatch import (
        settle_staged_declarations_in_decree_order,
        stage_declaration,
    )

    db, state, _ = game
    minister = _minister(db)

    stage_declaration(
        db, decree_ref="decree:3",
        declaration={"textual_facts": [{
            "subject_kind": "character", "subject_id": minister, "body": "旨三：首次暂存",
        }]},
        turn=int(state.turn),
    )
    settle_staged_declarations_in_decree_order(db, state, ["decree:3"])
    facts = db.textual_facts.readable_materials(subject_kind="character", subject_id=minister)
    assert [f.body for f in facts] == ["旨三：首次暂存"]

    with pytest.raises(DecreeAlreadySettled):
        stage_declaration(
            db, decree_ref="decree:3",
            declaration={"textual_facts": [{
                "subject_kind": "character", "subject_id": minister, "body": "旨三：迟到的重复暂存",
            }]},
            turn=int(state.turn),
        )

    # 拒绝发生在写入之前：没有留下一条永远不会被结算/拒收的孤儿 staged 行。
    row = db.conn.execute(
        "SELECT COUNT(*) c FROM staged_declarations WHERE decree_ref='decree:3' AND status='staged'",
    ).fetchone()
    assert row["c"] == 0
    facts_after = db.textual_facts.readable_materials(subject_kind="character", subject_id=minister)
    assert [f.body for f in facts_after] == ["旨三：首次暂存"]


def test_declared_free_prose_is_persisted_byte_for_byte(game):
    db, state, _ = game
    minister = _minister(db)
    from ming_sim.audience_night import open_night

    night = open_night(db, state)
    night_id = int(night["id"])
    presence_body = "  前后空格正文  \n"
    scene_body = "  场景前后  "
    commission_text = "  交办前后空白  \n"
    result = dispatch_declaration(db, state, {
        "presence": [{"person_name": minister, "effect": "enter", "body": presence_body}],
        "scene_facts": [{
            "body": scene_body, "audibility": "殿上公开", "person_names": [minister],
        }],
        "commissions": [{"text": commission_text}],
    }, night_id=night_id)
    assert result.presence.rejected == []
    assert result.scene_facts.rejected == []
    assert result.commissions.rejected == []
    presence_row = db.conn.execute(
        "SELECT body FROM story_ledger_entries WHERE id=?",
        (result.presence.applied[0]["id"],),
    ).fetchone()
    scene_row = db.conn.execute(
        "SELECT body FROM story_ledger_entries WHERE id=?",
        (result.scene_facts.applied[0]["id"],),
    ).fetchone()
    payload = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?",
        (result.commissions.applied[0]["id"],),
    ).fetchone()["payload_json"])
    assert presence_row["body"] == presence_body
    assert scene_row["body"] == scene_body
    assert payload["text"] == commission_text


@pytest.mark.parametrize("section,field,bad", [
    ("presence", "body", 123),
    ("presence", "body", ["list"]),
    ("presence", "body", {"k": 1}),
    ("scene_facts", "body", 123),
    ("scene_facts", "body", ["list"]),
    ("scene_facts", "body", {"k": 1}),
    ("commissions", "text", 123),
    ("commissions", "text", ["list"]),
    ("commissions", "text", {"k": 1}),
])
def test_non_string_declared_prose_is_durable_invalid_shape(game, section, field, bad):
    db, state, _ = game
    minister = _minister(db)
    from ming_sim.audience_night import open_night

    night = open_night(db, state)
    night_id = int(night["id"])
    before_ledger = db.conn.execute(
        "SELECT COUNT(*) c FROM story_ledger_entries WHERE night_id=?", (night_id,),
    ).fetchone()["c"]
    before_pending = db.conn.execute("SELECT COUNT(*) c FROM pending_actions").fetchone()["c"]

    if section == "presence":
        declaration = {
            "presence": [{"person_name": minister, "effect": "enter", field: bad}],
        }
    elif section == "scene_facts":
        declaration = {
            "scene_facts": [{
                field: bad, "audibility": "殿上公开", "person_names": [minister],
            }],
        }
    else:
        declaration = {"commissions": [{field: bad}]}

    result = dispatch_declaration(db, state, declaration, night_id=night_id)
    section_result = getattr(result, section)
    assert section_result.applied == []
    assert section_result.rejected
    assert section_result.rejected[0].category == "invalid_shape"
    rows = db.conn.execute(
        "SELECT section, category FROM rejection_reports WHERE turn=?",
        (int(state.turn),),
    ).fetchall()
    assert (section, "invalid_shape") in {
        (row["section"], row["category"]) for row in rows
    }
    after_ledger = db.conn.execute(
        "SELECT COUNT(*) c FROM story_ledger_entries WHERE night_id=?", (night_id,),
    ).fetchone()["c"]
    after_pending = db.conn.execute("SELECT COUNT(*) c FROM pending_actions").fetchone()["c"]
    assert after_ledger == before_ledger
    assert after_pending == before_pending


@pytest.mark.parametrize("raw", [{}, "", 0])
def test_present_falsy_section_is_durable_invalid_shape(game, raw):
    db, state, _ = game
    result = dispatch_declaration(db, state, {"textual_facts": raw})
    assert result.textual_facts.applied == []
    assert result.textual_facts.rejected
    assert result.textual_facts.rejected[0].category == "invalid_shape"
    rows = db.conn.execute(
        "SELECT section, category FROM rejection_reports WHERE turn=?",
        (int(state.turn),),
    ).fetchall()
    assert [(row["section"], row["category"]) for row in rows] == [
        ("textual_facts", "invalid_shape"),
    ]

    empty_protagonist = dispatch_declaration(db, state, {"protagonist": {}})
    assert empty_protagonist.protagonist.validated is None
    assert empty_protagonist.protagonist.rejected
    assert empty_protagonist.protagonist.rejected[0].category == "invalid_shape"
