"""契约钉 #883·密令源头隔离 + #976 召对写入接缝结构分流。

密令及一切派生只进 ①密令本体表 ②接令者专用密令简报表；
不进任何共享存储；披露事件是唯一公开化通道；
公共产出 LLM 输入构建器永不预读密令。

#976：召对 user 行 hold 至分类事件；密令血缘 withheld 永不进共享轨；
公开内容放行共享轨。禁止内容匹配擦洗（子串/n-gram）。
"""

from __future__ import annotations

import pytest

from ming_sim import issues
from ming_sim.decree import settle_with_delta
from tests.conftest import with_monthly_reports
from ming_sim.simulation import build_extractor_shared_context, build_simulator_payload
from tests.dossier_test_helpers import TYPED_COVERT_TASK, create_test_secret_order


def _active_ministers(db, content):
    return [
        character
        for character in content.characters.values()
        if character.office_type not in ("后宫", "宗藩")
        and db.get_character_status(character.name)[0] == "active"
    ]


def _shared_bodies(db):
    return [
        row["body"] or ""
        for row in db.conn.execute("SELECT body FROM character_knowledge_sources").fetchall()
    ]


def _event_bodies(db):
    return [
        row["body"] or ""
        for row in db.conn.execute("SELECT body FROM character_knowledge_events").fetchall()
    ]


def test_883_two_turn_probe_secret_never_enters_shared_archives(game):
    """两回合探针：T1 下密令 → T2 结算 → 共享档无派生；接令者简报表有。

    结构保证：公共 LLM/结算叙事永不预读密令；brief 不进 knowledge_items。
    不把密令正文注入 raw 邸报再靠文本擦洗——那是被拆除的范式。
    """
    db, state, content = game
    assignee, other = _active_ministers(db, content)[:2]
    marker = "乙巳密查内廷账目883探针"

    oid = create_test_secret_order(db, state, assignee.name, "乙巳密查", marker, [])
    assert oid > 0

    # T1 → T2：纯公开结算叙事（模拟公共 LLM 无密令预读）。
    settle_with_delta(
        state, db, with_monthly_reports(db, {}), before_turn=state.turn, content=content,
        narrative="本月朝局平缓，无非常之事。",
    )
    db.save_turn_report(state, "邸报：本月朝局平缓。")
    db.save_chapter_memory(state, "朝局", "章节：本月朝局平缓。")

    brief = db.conn.execute(
        "SELECT body, minister_name FROM secret_order_briefs WHERE order_id=?", (oid,)
    ).fetchone()
    source_count = db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id LIKE 'secret_order:%'"
    ).fetchone()[0]
    chapter_text = " ".join(item["body"] for item in db.list_chapter_memories())
    report_text = " ".join(item["report"] for item in db.list_turn_reports())
    other_view = db.get_character_knowledge(state, other.name)
    other_text = " ".join(
        item.get("body", "")
        for item in [*other_view["events"], *other_view["public_events"]]
    )
    assignee_view = db.get_character_knowledge(state, assignee.name)
    assignee_text = " ".join(item.get("body", "") for item in assignee_view["events"])

    assert brief is not None
    assert brief["minister_name"] == assignee.name
    assert marker in (brief["body"] or "")
    assert source_count == 0
    assert marker not in chapter_text
    assert marker not in report_text
    assert marker not in other_text
    assert marker in assignee_text
    # Brief body must not auto-materialize into shared sources.
    assert all(marker not in body for body in _shared_bodies(db))


def test_883_shared_summary_write_seam_rejects_secret_order_source(game):
    """共享汇总写入接缝单点拒收：secret_order 不得进 character_knowledge_sources。"""
    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    marker = "共享源拒收密令正文883"

    raised = False
    try:
        db.register_character_knowledge_source(
            state,
            [{"character_id": assignee.name, "tier": "主办"}],
            "secret_order",
            "密查",
            marker,
            source_id="secret_order:force-shared",
        )
    except ValueError:
        raised = True

    count = db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id LIKE 'secret_order:%'"
    ).fetchone()[0]
    # #883 write seam raises ValueError on secret_order kind/source_id (loud reject).
    assert raised
    assert count == 0
    assert all(marker not in (body or "") for body in _shared_bodies(db))


def test_883_audience_chat_path_does_not_leave_secret_in_shared_sources(game):
    """真实召对路径：append_chat_message → create_secret_order 后共享源无密令原话。

    #976 hold-and-release：user 行 hold，分类时 withheld，永不进共享轨。
    """
    db, state, content = game
    assignee, other = _active_ministers(db, content)[:2]
    marker = "密令：真实召对密令旁路883，不可外泄"

    mid = db.append_chat_message(assignee.name, state.turn, "user", marker)
    # Classification 前不得进共享库。
    held = db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid,)
    ).fetchone()
    assert held is not None and held["knowledge_status"] == "held"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id=?",
        (f"chat_message:{mid}",),
    ).fetchone()[0] == 0

    oid = create_test_secret_order(db, state, assignee.name, "乙巳密查旁路", marker, [])
    assert oid > 0

    status = db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid,)
    ).fetchone()["knowledge_status"]
    assert status == "withheld"

    brief = db.conn.execute(
        "SELECT body, minister_name FROM secret_order_briefs WHERE order_id=?", (oid,)
    ).fetchone()
    other_view = db.get_character_knowledge(state, other.name)
    other_text = " ".join(
        item.get("body", "")
        for item in [*other_view["events"], *other_view["public_events"]]
    )
    assignee_view = db.get_character_knowledge(state, assignee.name)
    assignee_text = " ".join(item.get("body", "") for item in assignee_view["events"])

    assert brief is not None
    assert brief["minister_name"] == assignee.name
    assert marker in (brief["body"] or "")
    assert all(marker not in body for body in _shared_bodies(db))
    assert all(marker not in body for body in _event_bodies(db))
    assert marker not in other_text
    assert marker in assignee_text


def test_883_audience_chat_paraphrase_does_not_leave_origin_in_shared_sources(game):
    """召对原话 ≠ 密令 title/body 时，结构隔离仍须扣留接令者 user 血缘。

    #976：识别靠 role+接令者 provenance，不靠文本 needle；零字面重叠润稿同样成立。
    """
    db, state, content = game
    assignee, other = _active_ministers(db, content)[:2]
    chat_origin = (
        "着尔密访国丈家产虚实，凡田宅典当与内库往来账目，皆须暗中簿记，"
        "不得走漏半句，亦不可经司礼监转呈。"
    )
    extracted_title = "密查国丈"
    extracted_body = "暗访国丈田宅典当及内库往来，事密勿使司礼监知。"

    assert extracted_body not in chat_origin
    assert chat_origin not in extracted_body
    assert extracted_title not in chat_origin

    db.append_chat_message(assignee.name, state.turn, "user", chat_origin)
    db.append_chat_message(
        assignee.name, state.turn, "minister", "臣领密旨，即暗中查办，不敢外泄。"
    )
    # 同回合无关召对（另一大臣）应进共享轨。
    other_public = "臣报：山东漕粮本月起运如常，无阻。"
    db.append_chat_message(other.name, state.turn, "user", other_public)

    oid = create_test_secret_order(db,
        state, assignee.name, extracted_title, extracted_body, [],
    )
    assert oid > 0

    brief = db.conn.execute(
        "SELECT body, minister_name FROM secret_order_briefs WHERE order_id=?", (oid,)
    ).fetchone()
    other_view = db.get_character_knowledge(state, other.name)
    other_text = " ".join(
        item.get("body", "")
        for item in [*other_view["events"], *other_view["public_events"]]
    )
    assignee_view = db.get_character_knowledge(state, assignee.name)
    assignee_text = " ".join(item.get("body", "") for item in assignee_view["events"])
    shared_bodies = _shared_bodies(db)

    assert brief is not None
    assert brief["minister_name"] == assignee.name
    assert extracted_body in (brief["body"] or "")
    # 原话与润稿正文均不得残留共享存储。
    assert all(chat_origin not in body for body in shared_bodies)
    assert all(chat_origin not in body for body in _event_bodies(db))
    assert all(extracted_body not in body for body in shared_bodies)
    assert all(extracted_body not in body for body in _event_bodies(db))
    assert chat_origin not in other_text
    assert extracted_body not in other_text
    # 接令者仍从专用简报读到密令。
    assert extracted_body in assignee_text
    # #976 message-level：分类 release 仅 scoped 到接令者/口谕 speaker，
    # 他臣纯公开 held 不因 create(A) 全局投轨（病根1）；settle/显式 release 后才进共享。
    other_status = db.conn.execute(
        "SELECT knowledge_status FROM chat_messages "
        "WHERE minister_name=? AND content=? ORDER BY id DESC LIMIT 1",
        (other.name, other_public),
    ).fetchone()["knowledge_status"]
    assert other_status in ("held", "released")
    assert other_status != "withheld"
    if other_status == "held":
        db.release_held_audience_knowledge()
    assert any(other_public in body for body in _shared_bodies(db))


def test_883_shared_write_seam_keeps_public_assignee_audience(game):
    """接令者身份不改变公开 audience 行本身的 provenance。"""
    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    marker = "已存简报原话不得再入共享883"

    oid = create_test_secret_order(db, state, assignee.name, "密查简报", marker, [])
    assert oid > 0

    db.register_character_knowledge_source(
        state,
        [{"character_id": assignee.name}],
        "audience",
        "召对",
        f"臣复述密旨：{marker}",
        source_id="chat_message:replay-secret",
    )
    assert any(marker in body for body in _shared_bodies(db))


def test_883_public_audience_same_turn_survives_secret_classification(game):
    """F1：接令者同回合先公开后密令时，公开大臣回话不得被吞掉（私有事件轨 参与即知）。

    分类后接令者 active → 非 user held 行进 private 轨（非共享）；
    臣领密旨类应答不得残留共享 sources。
    """
    db, state, content = game
    assignee, other = _active_ministers(db, content)[:2]
    public_line = "臣报：京营操练如常，无异常。"
    secret_chat = (
        "着尔密访国丈家产虚实，凡田宅典当与内库往来账目，皆须暗中簿记，"
        "不得走漏半句，亦不可经司礼监转呈。"
    )
    ack = "臣领密旨，即暗中查办。"
    extracted = "暗访国丈田宅典当及内库往来，事密勿使司礼监知。"

    db.append_chat_message(assignee.name, state.turn, "user", "近来京营操练如何？")
    mid_public = db.append_chat_message(assignee.name, state.turn, "minister", public_line)
    db.append_chat_message(assignee.name, state.turn, "user", secret_chat)
    mid_ack = db.append_chat_message(assignee.name, state.turn, "minister", ack)
    # 分类前：大臣回话也 hold，不可见于共享投影。
    assert db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid_public,)
    ).fetchone()["knowledge_status"] == "held"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id=?",
        (f"chat_message:{mid_public}",),
    ).fetchone()[0] == 0

    oid = create_test_secret_order(db, state, assignee.name, "密查国丈", extracted, [])
    assert oid > 0

    shared_bodies = _shared_bodies(db)
    event_bodies = _event_bodies(db)
    assignee_view = db.get_character_knowledge(state, assignee.name)
    assignee_text = " ".join(
        item.get("body", "") for item in assignee_view["events"] + assignee_view.get("public_events", [])
    )
    other_view = db.get_character_knowledge(state, other.name)
    other_text = " ".join(
        item.get("body", "")
        for item in [*other_view["events"], *other_view.get("public_events", [])]
    )

    # 同一大臣另有密令不改变一条公开召对的消息级 provenance。
    assert db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid_public,)
    ).fetchone()["knowledge_status"] == "released"
    assert public_line in assignee_text
    assert any(public_line in body for body in shared_bodies)
    # 未钉 explicit origin 的应答仍是公开行，不能靠接令者身份改判。
    assert db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid_ack,)
    ).fetchone()["knowledge_status"] == "released"
    assert any(ack in body for body in shared_bodies)
    # 密令原话与润稿不得残留共享存储；他臣不得见。
    assert all(secret_chat not in body for body in shared_bodies)
    assert all(extracted not in body for body in shared_bodies)
    assert secret_chat not in other_text
    assert extracted not in other_text
    assert extracted in assignee_text


def test_883_post_brief_public_audience_enters_shared_sources(game):
    """brief 已存在也不能把无 explicit origin 的 audience 行改判为私有。"""
    db, state, content = game
    assignee, other = _active_ministers(db, content)[:2]
    marker_body = "密查阉党余孽在京城私结会所并藏匿禁书"
    oid = create_test_secret_order(db, state, assignee.name, "密查阉党", marker_body, [])
    assert oid > 0

    paraphrase = "臣已暗中查访阉党旧部在京活动，尚未惊动外廷。"
    assert marker_body not in paraphrase
    assert "密查阉党" not in paraphrase

    mid = db.append_chat_message(assignee.name, state.turn, "minister", paraphrase)
    # 分类后仍 hold，直至 release 单点投轨。
    assert db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid,)
    ).fetchone()["knowledge_status"] == "held"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id=?",
        (f"chat_message:{mid}",),
    ).fetchone()[0] == 0

    db.release_held_audience_knowledge()
    status = db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid,)
    ).fetchone()["knowledge_status"]
    assert status == "released"
    assert any(paraphrase in body for body in _shared_bodies(db))


def test_883_pure_public_archive_lands_while_secret_brief_active(game):
    """F3：世上存在 active brief 时，纯公开月末叙事/邸报仍应入档（不整闸吞公开层）。"""
    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    public = "本月山东漕粮起运如常，无阻无欠。"
    secret_marker = "不得入档的密令正文883"
    create_test_secret_order(db, state, assignee.name, "密查某事", secret_marker, [])

    db.save_turn_report(state, public)
    db.save_chapter_memory(state, "朝局公开", public)
    report_blob = " ".join(item["report"] for item in db.list_turn_reports())
    chapter_blob = " ".join(item["body"] for item in db.list_chapter_memories())
    assert public in report_blob
    assert public in chapter_blob
    # Brief content does not auto-flow into archives.
    assert secret_marker not in report_blob
    assert secret_marker not in chapter_blob

    from ming_sim.decree import _record_settlement_narrative_sources
    _record_settlement_narrative_sources(db, state, public, commit=True)
    settlement = list(
        db.conn.execute(
            "SELECT body FROM character_knowledge_events WHERE source_id=?",
            (f"settlement:narrative:{state.turn}",),
        ).fetchall()
    )
    assert settlement and public in (settlement[0]["body"] or "")


def test_883_cross_turn_chat_origin_withheld_on_late_secret_create(game):
    """F4：召对原话在 T hold，T+1 才 create（润稿 body）仍须 withheld，永不进共享。"""
    db, state, content = game
    assignee, other = _active_ministers(db, content)[:2]
    chat_origin = (
        "着尔密访国丈家产虚实，凡田宅典当与内库往来账目，皆须暗中簿记，"
        "不得走漏半句，亦不可经司礼监转呈。"
    )
    extracted = "暗访国丈田宅典当及内库往来，事密勿使司礼监知。"
    assert extracted not in chat_origin and chat_origin not in extracted

    mid = db.append_chat_message(assignee.name, state.turn, "user", chat_origin)
    # Still held across turn boundary — never entered shared.
    assert db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid,)
    ).fetchone()["knowledge_status"] == "held"
    state.turn = int(state.turn) + 1
    db.save_state(state)
    oid = create_test_secret_order(db, state, assignee.name, "密查国丈", extracted, [])
    assert oid > 0
    assert db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid,)
    ).fetchone()["knowledge_status"] == "withheld"

    other_view = db.get_character_knowledge(state, other.name)
    other_text = " ".join(
        item.get("body", "")
        for item in [*other_view["events"], *other_view.get("public_events", [])]
    )
    assert all(chat_origin not in body for body in _shared_bodies(db))
    assert all(chat_origin not in body for body in _event_bodies(db))
    assert chat_origin not in other_text


def test_883_zero_overlap_semantic_rewrite_withholds_prior_audience_origin(game):
    """跨回合零重叠润稿：原话与 extracted 无共同四字窗时，仍按 user 血缘 withheld。"""
    db, state, content = game
    assignee, other = _active_ministers(db, content)[:2]
    chat_origin = "着人暗访勋贵藏银田契，切莫声张"
    extracted_title = "秘密核验"
    extracted_body = "秘密核验国丈私财庄宅，避开耳目"
    # Fixture property: no shared 4-char window (documents zero-overlap case).
    compact_o = "".join(chat_origin.split())
    compact_e = "".join((extracted_title + extracted_body).split())
    o_grams = {compact_o[i : i + 4] for i in range(max(0, len(compact_o) - 3))}
    e_grams = {compact_e[i : i + 4] for i in range(max(0, len(compact_e) - 3))}
    assert o_grams.isdisjoint(e_grams), "fixture must be zero 4-gram overlap"

    db.append_chat_message(assignee.name, state.turn, "user", chat_origin)
    state.turn = int(state.turn) + 1
    db.save_state(state)
    oid = create_test_secret_order(db,
        state, assignee.name, extracted_title, extracted_body, [],
    )
    assert oid > 0

    other_view = db.get_character_knowledge(state, other.name)
    other_text = " ".join(
        item.get("body", "")
        for item in [*other_view["events"], *other_view.get("public_events", [])]
    )
    assignee_view = db.get_character_knowledge(state, assignee.name)
    assignee_text = " ".join(item.get("body", "") for item in assignee_view["events"])
    brief = db.conn.execute(
        "SELECT body FROM secret_order_briefs WHERE order_id=?", (oid,)
    ).fetchone()

    assert brief is not None and extracted_body in (brief["body"] or "")
    assert all(chat_origin not in body for body in _shared_bodies(db))
    assert all(chat_origin not in body for body in _event_bodies(db))
    assert chat_origin not in other_text
    assert extracted_body in assignee_text


def test_883_thematic_public_audience_survives_secret_create(game):
    """同主题纯公开召对不得被密令分类误伤（S3 参与即知）。

    全 hold 后分类：接令者大臣公开回话进 private 轨（不进共享 sources）；
    接令者仍从私有事件读到；密令润稿不进他臣面。
    """
    db, state, content = game
    assignee, other = _active_ministers(db, content)[:2]
    public_line = "京营操练如常，兵士按期点卯"
    sec_title = "密查京营操练"
    sec_body = "密查京营兵士点卯虚实，勿使外廷知"

    mid = db.append_chat_message(assignee.name, state.turn, "minister", public_line)
    assert db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid,)
    ).fetchone()["knowledge_status"] == "held"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id=?",
        (f"chat_message:{mid}",),
    ).fetchone()[0] == 0

    oid = create_test_secret_order(db, state, assignee.name, sec_title, sec_body, [])
    assert oid > 0

    status = db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid,)
    ).fetchone()["knowledge_status"]
    assert status == "released"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id=?",
        (f"chat_message:{mid}",),
    ).fetchone()[0] == 1
    after_events = db.conn.execute(
        "SELECT COUNT(*) AS n FROM character_knowledge_events WHERE body LIKE ?",
        (f"%{public_line}%",),
    ).fetchone()["n"]
    assignee_view = db.get_character_knowledge(state, assignee.name)
    assignee_text = " ".join(
        item.get("body", "")
        for item in assignee_view["events"] + assignee_view.get("public_events", [])
    )
    other_view = db.get_character_knowledge(state, other.name)
    other_text = " ".join(
        item.get("body", "")
        for item in [*other_view["events"], *other_view.get("public_events", [])]
    )

    assert after_events >= 1
    assert public_line in assignee_text
    assert any(public_line in body for body in _shared_bodies(db))
    assert sec_body not in other_text


def test_976_minister_reply_not_shared_before_classification(game):
    """#976 must：分类前大臣回话不可见于共享投影（负）。"""
    db, state, content = game
    minister = _active_ministers(db, content)[0]
    reply = "臣报：山东漕运本月起运如常。"

    mid = db.append_chat_message(minister.name, state.turn, "minister", reply)
    assert db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid,)
    ).fetchone()["knowledge_status"] == "held"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id=?",
        (f"chat_message:{mid}",),
    ).fetchone()[0] == 0
    assert all(reply not in body for body in _shared_bodies(db))
    assert all(reply not in body for body in _event_bodies(db))


def test_976_pure_public_minister_reply_released_after_settle(game):
    """#976 must：纯公开召对的大臣回话 settle 后正常放行共享轨（正）。"""
    db, state, content = game
    minister = _active_ministers(db, content)[0]
    reply = "臣报：京营点卯无缺，操练如常。"

    mid = db.append_chat_message(minister.name, state.turn, "minister", reply)
    settle_with_delta(
        state, db, with_monthly_reports(db, {}), before_turn=state.turn, content=content,
        narrative="本月朝局平缓。",
    )
    status = db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid,)
    ).fetchone()["knowledge_status"]
    assert status == "released"
    row = db.conn.execute(
        "SELECT body FROM character_knowledge_sources WHERE source_id=?",
        (f"chat_message:{mid}",),
    ).fetchone()
    assert row is not None and reply in (row["body"] or "")


def test_976_secret_chat_turn_withholds_both_sides_but_public_turn_survives(game):
    """#976：密令血缘跟随完整召对轮，纯公开召对仍进共享轨。"""
    db, state, content = game
    assignee, other = _active_ministers(db, content)[:2]
    origin = "着尔密访国丈家产，勿使外廷知。"
    ack = "臣领密旨，即暗中查办，不敢外泄。"
    extracted = "暗访国丈家产虚实"
    public_q = "京营今日操练如何？"
    public_reply = "回陛下，京营操练如常。"

    secret_turn = db.create_chat_turn(state, assignee.name, "secret-turn-976", 0)
    mid_origin = db.append_chat_message(assignee.name, state.turn, "user", origin)
    db.update_chat_turn_messages(
        secret_turn, user_message_id=mid_origin,
    )
    oid = create_test_secret_order(db, state, assignee.name, "密查国丈", extracted, [])
    assert oid > 0
    mid_ack = db.append_chat_message(assignee.name, state.turn, "minister", ack)
    db.update_chat_turn_messages(secret_turn, minister_message_id=mid_ack)

    public_turn = db.create_chat_turn(state, assignee.name, "public-turn-976", 0)
    mid_public_q = db.append_chat_message(assignee.name, state.turn, "user", public_q)
    mid_public_reply = db.append_chat_message(
        assignee.name, state.turn, "minister", public_reply,
    )
    db.update_chat_turn_messages(
        public_turn,
        user_message_id=mid_public_q,
        minister_message_id=mid_public_reply,
    )
    db.release_held_audience_knowledge()

    statuses = {
        row["id"]: row["knowledge_status"]
        for row in db.conn.execute(
            "SELECT id, knowledge_status FROM chat_messages WHERE id IN (?,?,?,?)",
            (mid_origin, mid_ack, mid_public_q, mid_public_reply),
        ).fetchall()
    }
    assert statuses[mid_origin] == statuses[mid_ack] == "withheld"
    assert statuses[mid_public_q] == statuses[mid_public_reply] == "released"
    brief = db.conn.execute(
        "SELECT body FROM secret_order_briefs WHERE order_id=?", (oid,)
    ).fetchone()
    assert brief is not None and extracted in (brief["body"] or "")
    other_view = db.get_character_knowledge(state, other.name)
    other_text = " ".join(
        item.get("body", "")
        for item in [*other_view["events"], *other_view.get("public_events", [])]
    )
    assert ack not in other_text
    assert origin not in other_text
    assert extracted not in other_text
    shared_text = " ".join(
        row["body"] or ""
        for row in db.conn.execute(
            "SELECT body FROM character_knowledge_sources WHERE source_id IN (?,?)",
            (f"chat_message:{mid_public_q}", f"chat_message:{mid_public_reply}"),
        ).fetchall()
    )
    assert public_q in shared_text
    assert public_reply in shared_text


def test_976_withhold_does_not_yank_old_released_public_user(game):
    """S1：withhold 不连坐抽回久远已放行的纯公开 user 召对。

    旧公开已 released 且 turn 远早于 settle 窗口时，后下密令不得把它从共享源抹掉。
    跨回合 held 原话仍须 withheld（既有 F4 / zero-overlap 钉）。
    """
    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    old_public = "问卿：山东漕粮起运是否如期？"
    secret_origin = "着尔密访国丈家产虚实，勿使外廷知。"

    mid_old = db.append_chat_message(assignee.name, state.turn, "user", old_public)
    db.release_held_audience_knowledge()
    assert db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid_old,)
    ).fetchone()["knowledge_status"] == "released"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id=?",
        (f"chat_message:{mid_old}",),
    ).fetchone()[0] == 1

    # 远离开 settle 窗口（>1 回合）。
    state.turn = int(state.turn) + 5
    db.save_state(state)
    mid_secret = db.append_chat_message(assignee.name, state.turn, "user", secret_origin)
    oid = create_test_secret_order(db,
        state, assignee.name, "密查国丈", "暗访国丈家产", [],
    )
    assert oid > 0

    assert db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid_old,)
    ).fetchone()["knowledge_status"] == "released"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id=?",
        (f"chat_message:{mid_old}",),
    ).fetchone()[0] == 1
    assert db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid_secret,)
    ).fetchone()["knowledge_status"] == "withheld"
    assert all(secret_origin not in body for body in _shared_bodies(db))
    assert any(old_public in body for body in _shared_bodies(db))


def test_976_release_stamps_original_message_date(game):
    """N1：跨年投轨的 turn/year/period 均用原发话时间。"""
    db, state, content = game
    minister = _active_ministers(db, content)[0]
    reply = "臣报：本月辽饷解送如常。"
    origin_turn = int(state.turn)
    origin_year = int(state.year)
    origin_period = int(state.period)
    mid = db.append_chat_message(minister.name, origin_turn, "minister", reply)

    for _ in range(13):
        state.next_period()
    db.save_state(state)
    db.release_held_audience_knowledge()

    row = db.conn.execute(
        "SELECT turn, year, period FROM character_knowledge_sources WHERE source_id=?",
        (f"chat_message:{mid}",),
    ).fetchone()
    assert row is not None
    assert (int(row["turn"]), int(row["year"]), int(row["period"])) == (
        origin_turn, origin_year, origin_period,
    )
    event = db.conn.execute(
        "SELECT turn, year, period FROM character_knowledge_events WHERE source_id=?",
        (f"chat_message:{mid}",),
    ).fetchone()
    assert event is not None
    assert (int(event["turn"]), int(event["year"]), int(event["period"])) == (
        origin_turn, origin_year, origin_period,
    )


def test_883_shared_archive_bypass_positive_and_negative(game):
    """复审员旁路：结构保证——密令简报不自动入档；纯公开文可入（有/无 brief 皆然）。"""
    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    secret_marker = "旁路密令正负883"
    public_marker = "旁路公开正负883"

    # 负向结构：密令只在 brief；纯公开入档；brief 正文不自动流入共享档。
    create_test_secret_order(db, state, assignee.name, "旁路密查", secret_marker, [])
    db.save_turn_report(state, "公开句；本月漕运如常。")
    db.save_chapter_memory(state, "朝局", "公开句；本月漕运如常。")
    report_blob = " ".join(item["report"] for item in db.list_turn_reports())
    chapter_blob = " ".join(item["body"] for item in db.list_chapter_memories())
    assert secret_marker not in report_blob
    assert secret_marker not in chapter_blob
    assert "公开句" in report_blob
    assert "公开句" in chapter_blob
    assert all(secret_marker not in body for body in _shared_bodies(db))

    # 正向：无未公开密令简报时，纯公开正文可落共享档。
    db.conn.execute("DELETE FROM secret_order_briefs")
    db.conn.execute("DELETE FROM secret_orders")
    db.conn.commit()
    db.save_turn_report(state, public_marker)
    db.save_chapter_memory(state, "朝局公开", public_marker)
    report_blob = " ".join(item["report"] for item in db.list_turn_reports())
    chapter_blob = " ".join(item["body"] for item in db.list_chapter_memories())
    assert public_marker in report_blob
    assert public_marker in chapter_blob


def test_976_held_user_chat_released_when_never_classified_as_secret(game):
    """纯公开皇帝回话：hold 至月末 release，不因 hold 永久丢 参与即知。"""
    db, state, content = game
    minister = _active_ministers(db, content)[0]
    public_user = "问卿：山东漕粮起运是否如期？"

    mid = db.append_chat_message(minister.name, state.turn, "user", public_user)
    assert db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid,)
    ).fetchone()["knowledge_status"] == "held"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id=?",
        (f"chat_message:{mid}",),
    ).fetchone()[0] == 0

    n = db.release_held_audience_knowledge()
    assert n >= 1
    assert db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid,)
    ).fetchone()["knowledge_status"] == "released"
    row = db.conn.execute(
        "SELECT body FROM character_knowledge_sources WHERE source_id=?",
        (f"chat_message:{mid}",),
    ).fetchone()
    assert row is not None and public_user in (row["body"] or "")


def test_883_only_explicit_leak_conclusion_promotes_secret_order_to_public(game):
    """泄漏接线：无泄漏结论不公开；显式泄漏结论 → 披露事件 → 进入公共面。"""
    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    oid = create_test_secret_order(db, state, assignee.name, "密查盐案", "甲子密查盐案883", [])

    hidden = issues.apply_score_extraction(
        db, state,
        {"secret_order_updates": [{"order_id": oid, "sim_note": "风声渐起"}]},
        content=content,
    )
    assert hidden["secret_order_updates"][0]["disclosed"] is False
    assert not any(
        str(item.get("source_id") or "").startswith("secret_order_disclosure:")
        for item in db._character_knowledge_events("")
    )

    shown = issues.apply_score_extraction(
        db, state,
        {"secret_order_updates": [
            {"order_id": oid, "sim_note": "密事已公开883", "disclosed": True},
        ]},
        content=content,
    )
    assert shown["secret_order_updates"][0]["disclosed"] is True
    public_events = db._character_knowledge_events("")
    assert any(
        str(item.get("source_id") or "").startswith("secret_order_disclosure:")
        and "密事已公开883" in (item.get("body") or "")
        for item in public_events
    )


def test_883_cross_turn_repeat_disclosed_does_not_mint_duplicate_public_event(game):
    """跨回合幂等：同一密令多次 disclosed=true 只留一条 secret_order_disclosure 事件。"""
    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    oid = create_test_secret_order(db, state, assignee.name, "密查仓案", "丙寅密查仓案883", [])

    first = issues.apply_score_extraction(
        db, state,
        {"secret_order_updates": [
            {"order_id": oid, "sim_note": "首度公开883", "disclosed": True},
        ]},
        content=content,
    )
    assert first["secret_order_updates"][0]["disclosed"] is True
    prefix = f"secret_order_disclosure:{oid}:"
    after_first = [
        item for item in db._character_knowledge_events("")
        if str(item.get("source_id") or "").startswith(prefix)
    ]
    assert len(after_first) == 1
    assert "首度公开883" in (after_first[0].get("body") or "")

    # Advance turn so source_id turn suffix would differ if re-inserted.
    state.turn = int(state.turn) + 1
    second = issues.apply_score_extraction(
        db, state,
        {"secret_order_updates": [
            {"order_id": oid, "sim_note": "再次填写泄漏结论883", "disclosed": True},
        ]},
        content=content,
    )
    assert second["secret_order_updates"][0]["disclosed"] is True
    after_second = [
        item for item in db._character_knowledge_events("")
        if str(item.get("source_id") or "").startswith(prefix)
    ]
    assert len(after_second) == 1
    assert after_second[0]["source_id"] == after_first[0]["source_id"]
    assert "首度公开883" in (after_second[0].get("body") or "")


def test_883_public_llm_contexts_never_preload_secret_orders(game):
    """契约钉 #883：仅 personnel_secret 可读密令；公共 LLM 输入不得预读。"""
    db, state, _content = game
    marker = "乙巳密查内廷账目公共输入"
    secret_orders = {"在办": [{"id": 883, "content": marker}], "待核议": []}

    simulator_payload = build_simulator_payload(
        state, db, "", "", secret_orders=secret_orders,
    )
    public_contexts = [
        build_extractor_shared_context(
            db, state, "", "", secret_orders=secret_orders, module=module
        )
        for module in ("internal", "military_external", "issues")
    ]
    secret_context = build_extractor_shared_context(
        db, state, "", "", secret_orders=secret_orders, module="personnel_secret",
    )

    assert "secret_orders" not in simulator_payload
    assert marker not in str(simulator_payload)
    assert all(marker not in str(context) for context in public_contexts)
    assert secret_context["secret_orders"]["在办"][0]["content"] == marker

    # 默认路径（不传 secret_orders）：公共 payload 不得出现 secret_orders 键/空壳
    default_sim = build_simulator_payload(state, db, "", "")
    assert "secret_orders" not in default_sim
    for module in ("internal", "military_external", "issues"):
        ctx = build_extractor_shared_context(
            db, state, "", "", module=module
        )
        assert "secret_orders" not in ctx


def test_976_cross_person_speaker_user_origin_withheld_not_shared(game):
    """跨人承办：密令口谕在召对 speaker 侧，分类须绑 speaker 血缘，不得 release 进共享。

    皇帝对甲召对口述密令，工具登记 assignee=乙；withhold 不得只看乙。
    """
    db, state, content = game
    speaker, assignee = _active_ministers(db, content)[:2]
    assert speaker.name != assignee.name
    secret_text = "密令：着尔密查国丈家产虚实，勿使外廷知。"
    extracted = "暗访国丈家产虚实"

    mid = db.append_chat_message(speaker.name, state.turn, "user", secret_text)
    oid = create_test_secret_order(db,
        state, assignee.name, "密查国丈", extracted, [],
        origin_minister_name=speaker.name,
    )
    assert oid > 0

    status = db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid,)
    ).fetchone()["knowledge_status"]
    assert status == "withheld"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id=?",
        (f"chat_message:{mid}",),
    ).fetchone()[0] == 0
    assert all(secret_text not in body for body in _shared_bodies(db))
    assert all(secret_text not in body for body in _event_bodies(db))

    other = next(
        m for m in _active_ministers(db, content)
        if m.name not in (speaker.name, assignee.name)
    )
    other_view = db.get_character_knowledge(state, other.name)
    other_text = " ".join(
        item.get("body", "")
        for item in [*other_view["events"], *other_view.get("public_events", [])]
    )
    assert secret_text not in other_text
    assert extracted not in other_text


def test_976_same_window_pure_public_user_survives_secret_classification(game):
    """同窗口先公开后密令：纯公开 user 不得被整窗 withheld 吞掉（S3 参与即知）。

    现实现把 assignee 全部 held user 永久 withheld；公开问话既不进共享也不进私有事件。
    收窄后：仅最新同回合密令口谕 user withheld；更早公开 user 至少进接令者私有轨。
    """
    db, state, content = game
    assignee, other = _active_ministers(db, content)[:2]
    public_q = "近来京营操练如何？"
    public_a = "臣报：京营操练如常，无异常。"
    secret_q = (
        "着尔密访国丈家产虚实，凡田宅典当与内库往来账目，皆须暗中簿记，"
        "不得走漏半句，亦不可经司礼监转呈。"
    )
    extracted = "暗访国丈田宅典当及内库往来，事密勿使司礼监知。"

    mid_pub = db.append_chat_message(assignee.name, state.turn, "user", public_q)
    mid_ans = db.append_chat_message(assignee.name, state.turn, "minister", public_a)
    mid_sec = db.append_chat_message(assignee.name, state.turn, "user", secret_q)
    oid = create_test_secret_order(db, state, assignee.name, "密查国丈", extracted, [])
    assert oid > 0

    pub_status = db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid_pub,)
    ).fetchone()["knowledge_status"]
    sec_status = db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid_sec,)
    ).fetchone()["knowledge_status"]
    ans_status = db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid_ans,)
    ).fetchone()["knowledge_status"]

    assert sec_status == "withheld"
    assert ans_status == "released"
    # Pure public user must not black-hole: private (assignee active brief) or released.
    assert pub_status in ("private", "released")
    assert pub_status != "withheld"

    assignee_view = db.get_character_knowledge(state, assignee.name)
    assignee_text = " ".join(
        item.get("body", "")
        for item in assignee_view["events"] + assignee_view.get("public_events", [])
    )
    assert public_q in assignee_text
    assert public_a in assignee_text

    # Secret oral line never shared; other ministers must not see it.
    assert all(secret_q not in body for body in _shared_bodies(db))
    assert all(secret_q not in body for body in _event_bodies(db))
    other_view = db.get_character_knowledge(state, other.name)
    other_text = " ".join(
        item.get("body", "")
        for item in [*other_view["events"], *other_view.get("public_events", [])]
    )
    assert secret_q not in other_text
    assert extracted not in other_text


def test_976_stage_confirm_pin_provenance_not_max_held_user(game):
    """pending 确认路径：同回合后续确认语不得被 max(held id) 误判为密令血缘。

    皇帝对甲口述密令 → stage；后一句「准」确认 → commit。
    口谕 chat_message 须 withheld；确认语不得顶替血缘导致口谕 release 进共享。
    跨人承办：assignee=乙，origin speaker=甲。
    """
    db, state, content = game
    speaker, assignee = _active_ministers(db, content)[:2]
    assert speaker.name != assignee.name
    secret_q = (
        "着尔密访国丈家产虚实，凡田宅典当与内库往来账目，皆须暗中簿记，"
        "不得走漏半句，亦不可经司礼监转呈。"
    )
    extracted = "暗访国丈田宅典当及内库往来，事密勿使司礼监知。"
    confirm_q = "准。就按此办。"

    mid_sec = db.append_chat_message(speaker.name, state.turn, "user", secret_q)
    pid = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建",
        minister_name=speaker.name, target_id=None,
        payload={
            "title": "密查国丈",
            "content": extracted,
            "assignee": assignee.name,
            "tags": [],
            "deadline_months": 0,
            "excluded_names": [],
            "excluded_offices": [],
            "covert_task": TYPED_COVERT_TASK,
        },
    )
    import json as _json
    staged = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pid,)
    ).fetchone()
    staged_payload = _json.loads(staged["payload_json"] or "{}")
    assert int(staged_payload.get("origin_chat_message_id") or 0) == mid_sec

    # Confirmation utterance lands *after* stage — larger id than oral decree.
    mid_confirm = db.append_chat_message(speaker.name, state.turn, "user", confirm_q)
    assert mid_confirm > mid_sec

    applied = db.commit_pending_actions(
        state, minister_name=speaker.name, action_ids={pid}, content=content,
    )
    assert applied and applied[0]["kind"] == "secret_order"

    sec_status = db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid_sec,)
    ).fetchone()["knowledge_status"]
    conf_status = db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid_confirm,)
    ).fetchone()["knowledge_status"]

    assert sec_status == "withheld"
    # Confirm is not secret-origin bloodline — must not steal the pin.
    assert conf_status != "withheld"
    # Critical: oral decree never enters shared knowledge.
    assert db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id=?",
        (f"chat_message:{mid_sec}",),
    ).fetchone()[0] == 0
    assert all(secret_q not in body for body in _shared_bodies(db))
    assert all(secret_q not in body for body in _event_bodies(db))

    other = next(
        m for m in _active_ministers(db, content)
        if m.name not in (speaker.name, assignee.name)
    )
    other_view = db.get_character_knowledge(state, other.name)
    other_text = " ".join(
        item.get("body", "")
        for item in [*other_view["events"], *other_view.get("public_events", [])]
    )
    assert secret_q not in other_text
    assert extracted not in other_text


def _assert_oral_decree_withheld_not_shared(db, state, *, mid_sec, secret_q, speakers, content):
    """Shared assertions: oral pin withheld; never enters shared knowledge sources."""
    sec_status = db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid_sec,)
    ).fetchone()["knowledge_status"]
    assert sec_status == "withheld"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id=?",
        (f"chat_message:{mid_sec}",),
    ).fetchone()[0] == 0
    assert all(secret_q not in body for body in _shared_bodies(db))
    assert all(secret_q not in body for body in _event_bodies(db))
    other = next(
        m for m in _active_ministers(db, content)
        if m.name not in speakers
    )
    other_view = db.get_character_knowledge(state, other.name)
    other_text = " ".join(
        item.get("body", "")
        for item in [*other_view["events"], *other_view.get("public_events", [])]
    )
    assert secret_q not in other_text


def test_976_non_create_stage_commit_update_withholds_oral_pin(game):
    """非新建 pending「更新」：显式 pin 在 commit 必须消费，口谕 withheld 不进共享。

    已有密令 → 皇帝对甲口述改旨 → stage 更新（显式 pin）→ 确认语 → commit。
    跨人承办：assignee=乙，origin speaker=甲。
    非新建不默认 auto-pin held；新口谕须显式 origin_chat_message_id。
    """
    import json as _json

    db, state, content = game
    speaker, assignee = _active_ministers(db, content)[:2]
    assert speaker.name != assignee.name
    oid = create_test_secret_order(db,
        state, assignee.name, "密查国丈", "初旨：暗访田宅。", [],
    )
    assert oid > 0

    secret_q = (
        "前令范围太窄，着尔扩至国丈典当与内库往来账目，皆须暗中簿记，"
        "不得走漏半句，亦不可经司礼监转呈。"
    )
    new_content = "扩查国丈典当及内库往来，事密勿使司礼监知。"
    confirm_q = "准。就按此改。"

    mid_sec = db.append_chat_message(speaker.name, state.turn, "user", secret_q)
    pid = db.stage_pending_action(
        state.turn, kind="secret_order", action="更新",
        minister_name=speaker.name, target_id=oid,
        payload={
            "new_title": "密查国丈（扩）",
            "new_content": new_content,
            "deadline_months": 0,
            "origin_chat_message_id": mid_sec,
        },
    )
    staged = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pid,)
    ).fetchone()
    staged_payload = _json.loads(staged["payload_json"] or "{}")
    assert int(staged_payload.get("origin_chat_message_id") or 0) == mid_sec

    mid_confirm = db.append_chat_message(speaker.name, state.turn, "user", confirm_q)
    assert mid_confirm > mid_sec

    applied = db.commit_pending_actions(
        state, minister_name=speaker.name, action_ids={pid}, content=content,
    )
    assert applied and applied[0]["kind"] == "secret_order"

    order = db.get_secret_order(oid)
    assert order is not None
    assert new_content in (order.get("content") or "")

    _assert_oral_decree_withheld_not_shared(
        db, state, mid_sec=mid_sec, secret_q=secret_q,
        speakers={speaker.name, assignee.name}, content=content,
    )
    conf_status = db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid_confirm,)
    ).fetchone()["knowledge_status"]
    # Confirm must not steal pin (may release/private/held; must not be the sole withheld).
    assert conf_status != "withheld" or mid_confirm == mid_sec


def test_976_non_create_stage_commit_rush_withholds_oral_pin(game):
    """非新建 pending「催办」：显式 pin 在 commit 必须消费，口谕 withheld 不进共享。"""
    import json as _json

    db, state, content = game
    speaker, assignee = _active_ministers(db, content)[:2]
    oid = create_test_secret_order(db,
        state, assignee.name, "密查国丈", "暗访田宅。", [], deadline_months=6,
    )
    assert oid > 0

    secret_q = (
        "前令限得太宽，着尔一个月内办结回奏，事密勿使司礼监转呈，亦不得走漏半句。"
    )
    confirm_q = "准。加紧催办。"

    mid_sec = db.append_chat_message(speaker.name, state.turn, "user", secret_q)
    pid = db.stage_pending_action(
        state.turn, kind="secret_order", action="催办",
        minister_name=speaker.name, target_id=oid,
        payload={
            "deadline_months": 1,
            "reason": "御限收紧",
            "origin_chat_message_id": mid_sec,
        },
    )
    staged = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pid,)
    ).fetchone()
    staged_payload = _json.loads(staged["payload_json"] or "{}")
    assert int(staged_payload.get("origin_chat_message_id") or 0) == mid_sec

    mid_confirm = db.append_chat_message(speaker.name, state.turn, "user", confirm_q)
    assert mid_confirm > mid_sec

    applied = db.commit_pending_actions(
        state, minister_name=speaker.name, action_ids={pid}, content=content,
    )
    assert applied and applied[0]["kind"] == "secret_order"

    _assert_oral_decree_withheld_not_shared(
        db, state, mid_sec=mid_sec, secret_q=secret_q,
        speakers={speaker.name, assignee.name}, content=content,
    )
    conf_status = db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid_confirm,)
    ).fetchone()["knowledge_status"]
    assert conf_status != "withheld" or mid_confirm == mid_sec


def test_976_non_create_stage_commit_progress_and_review_withhold_oral_pin(game):
    """非新建「记进展」「提交核议」：显式 pin 消费后口谕 withheld（修类 sweep）。"""
    import json as _json

    db, state, content = game
    speaker, assignee = _active_ministers(db, content)[:2]

    for action, payload_extra, setup in (
        (
            "记进展",
            {"note": "已密访东城典当三处。"},
            lambda: create_test_secret_order(db,
                state, assignee.name, "密查甲", "暗访田宅甲。", [],
            ),
        ),
        (
            "提交核议",
            {"claim": "国丈田宅已暗记在册，请核。"},
            lambda: create_test_secret_order(db,
                state, assignee.name, "密查乙", "暗访田宅乙。", [],
            ),
        ),
    ):
        oid = setup()
        secret_q = (
            f"关于{action}：着尔按朕口谕办理，凡内库往来皆须暗中簿记，"
            "不得走漏半句，亦不可经司礼监转呈。"
        )
        mid_sec = db.append_chat_message(speaker.name, state.turn, "user", secret_q)
        payload = {**payload_extra, "origin_chat_message_id": mid_sec}
        pid = db.stage_pending_action(
            state.turn, kind="secret_order", action=action,
            minister_name=speaker.name, target_id=oid,
            payload=payload,
        )
        staged = db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (pid,)
        ).fetchone()
        staged_payload = _json.loads(staged["payload_json"] or "{}")
        assert int(staged_payload.get("origin_chat_message_id") or 0) == mid_sec, action

        db.append_chat_message(speaker.name, state.turn, "user", f"准。{action}。")
        applied = db.commit_pending_actions(
            state, minister_name=speaker.name, action_ids={pid}, content=content,
        )
        assert applied and applied[0]["kind"] == "secret_order", action
        _assert_oral_decree_withheld_not_shared(
            db, state, mid_sec=mid_sec, secret_q=secret_q,
            speakers={speaker.name, assignee.name}, content=content,
        )


def test_976_non_create_pure_public_not_auto_pinned_as_secret_origin(game):
    """无新口谕时非新建 stage 不得 auto-pin 纯公开 held → withheld 吞 S3 参与即知。

    已有密令 → 纯公开问话 → stage 催办/记进展（无显式 pin）→ commit。
    纯公开不得被误标密令血缘；可 held 至 settle，或 private/released；永非 withheld。
    修类：催办 + 记进展；跨人 speaker≠assignee 与同人各一。
    """
    import json as _json

    db, state, content = game
    speaker, assignee = _active_ministers(db, content)[:2]
    public_q = "近来京营操练如何？先催办前令。"

    for action, payload, same_person in (
        (
            "催办",
            {"deadline_months": 1, "reason": "御限收紧"},
            False,
        ),
        (
            "记进展",
            {"note": "已密访东城典当三处。"},
            True,
        ),
    ):
        minister = assignee.name if same_person else speaker.name
        oid = create_test_secret_order(db,
            state, assignee.name, f"密查-{action}", f"暗访-{action}。", [],
            deadline_months=6,
        )
        assert oid > 0
        mid_pub = db.append_chat_message(minister, state.turn, "user", public_q)
        pid = db.stage_pending_action(
            state.turn, kind="secret_order", action=action,
            minister_name=minister, target_id=oid,
            payload=dict(payload),
        )
        staged = db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (pid,)
        ).fetchone()
        staged_payload = _json.loads(staged["payload_json"] or "{}")
        # 非新建无显式 pin → 不得把纯公开 held 钉成 origin
        assert staged_payload.get("origin_chat_message_id") in (None, "", 0), (
            f"{action}: auto-pinned pure public as origin"
        )

        applied = db.commit_pending_actions(
            state, minister_name=minister, action_ids={pid}, content=content,
        )
        assert applied and applied[0]["kind"] == "secret_order", action

        pub_status = db.conn.execute(
            "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid_pub,)
        ).fetchone()["knowledge_status"]
        assert pub_status != "withheld", (
            f"{action}: pure public swallowed as secret origin (status={pub_status})"
        )
        assert pub_status in ("held", "private", "released"), action
        # 不得进 withheld 终态后从知识面消失：held 等 settle 放行亦可；
        # private/released 则接令者/参与者当即可记。
        if pub_status in ("private", "released"):
            view = db.get_character_knowledge(state, minister)
            text = " ".join(
                item.get("body", "")
                for item in view["events"] + view.get("public_events", [])
            )
            assert public_q in text, f"{action}: pure public not remembered after project"


def test_976_production_tools_non_create_no_pure_public_auto_pin(game):
    """生产 tools 非新建（催办/记进展/提交核议）不得 auto-pin held。

    tools 无「更新」动作；新口谕改旨走 extract「更新」才钉 pin。
    纯公开问话 + 催办 不得把 held 钉成密令血缘 → withheld 吞 S3 参与即知。
    修类：记进展 / 催办 / 提交核议。
    """
    import json as _json
    from ming_sim.models import CourtContext
    from ming_sim.tools import build_minister_tools

    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    public_q = "近来京营操练如何？先催办前令。"

    cases = (
        ("progress", {"progress": "已密访东城典当三处。"}, "记进展"),
        ("rush", {"deadline_months": 1, "reason": "御限收紧"}, "催办"),
        ("submit", {"claim": "国丈田宅已暗记在册，请核。"}, "提交核议"),
    )
    for tool_action, kwargs, expected_sa in cases:
        oid = create_test_secret_order(db,
            state, assignee.name, f"密查-{tool_action}", f"暗访-{tool_action}。", [],
            deadline_months=6,
        )
        if int(db.get_secret_order(oid)["turn_issued"] or 0) == int(state.turn):
            db.conn.execute(
                "UPDATE secret_orders SET turn_issued=? WHERE id=?",
                (state.turn - 1, oid),
            )
            db.conn.commit()
        mid_pub = db.append_chat_message(assignee.name, state.turn, "user", public_q)
        context = CourtContext(state=state, db=db)
        tools = build_minister_tools(assignee, context)
        secret_order = next(t for t in tools if getattr(t, "__name__", "") == "secret_order")
        out = secret_order(action=tool_action, order_id=oid, **kwargs)
        assert out.startswith("__secret_action__"), tool_action
        data = _json.loads(out.removeprefix("__secret_action__"))
        assert data["action"] == expected_sa, tool_action
        pin = (data.get("payload") or {}).get("origin_chat_message_id")
        assert pin in (None, "", 0), (
            f"{tool_action}: tools must not auto-pin pure-public held as origin"
        )
        # stage+commit via production payload must not swallow pure public
        pid = db.stage_pending_action(
            state.turn, kind="secret_order", action=expected_sa,
            minister_name=assignee.name, target_id=oid,
            payload=dict(data.get("payload") or {}),
        )
        applied = db.commit_pending_actions(
            state, minister_name=assignee.name, action_ids={pid}, content=content,
        )
        assert applied and applied[0]["kind"] == "secret_order", tool_action
        pub_status = db.conn.execute(
            "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid_pub,),
        ).fetchone()["knowledge_status"]
        assert pub_status != "withheld", (
            f"{tool_action}: pure public swallowed as secret origin (status={pub_status})"
        )


def test_976_production_session_tool_path_progress_not_shared(game):
    """生产 session tool 记进展：无结构 pin 不从密嘱字面猜 provenance。

    tools 仅 own-order；口谕 held 在承办人名下。无 pin → settle release = private
    （S3 参与即知），永不进 character_knowledge_sources。跨人 shared 泄漏仅 DB
    直 stage 可达，非生产 tools 路径。
    """
    import json as _json
    from types import SimpleNamespace

    from ming_sim.session import GameSession

    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    other = next(m for m in _active_ministers(db, content) if m.name != assignee.name)
    oid = create_test_secret_order(db,
        state, assignee.name, "密查国丈", "初旨：暗访田宅。", [],
    )
    db.conn.execute(
        "UPDATE secret_orders SET turn_issued=? WHERE id=?",
        (state.turn - 1, oid),
    )
    db.conn.commit()

    secret_q = (
        "前令太窄，着尔扩至国丈典当与内库往来，皆须暗中簿记，"
        "不得走漏半句，亦不可经司礼监转呈。记尔进展。"
    )
    mid_sec = db.append_chat_message(assignee.name, state.turn, "user", secret_q)

    from ming_sim.models import CourtContext
    from ming_sim.tools import build_minister_tools

    context = CourtContext(state=state, db=db)
    tools = build_minister_tools(assignee, context)
    secret_order = next(t for t in tools if getattr(t, "__name__", "") == "secret_order")
    tool_out = secret_order(
        action="progress", order_id=oid, progress="已密访东城典当三处。",
    )
    assert tool_out.startswith("__secret_action__")
    tool_data = _json.loads(tool_out.removeprefix("__secret_action__"))
    assert (tool_data.get("payload") or {}).get("origin_chat_message_id") in (None, "", 0)

    class Agent:
        def run(self, _message):
            return SimpleNamespace(
                content="臣已记下进展，请陛下定夺。",
                tools=[SimpleNamespace(tool_name="secret_order", result=tool_out)],
            )

    class Registry:
        def get(self, _character):
            return Agent()


    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = Registry()
    sess.llm_config = SimpleNamespace(channel="api")
    sess.temporary_characters = set()
    sess._audience_prompt_for_message = lambda message, *a, **k: message
    sess._start_cli_action_intent = lambda *_args, **_kwargs: None
    sess._finish_cli_action_intent = lambda *_args, **_kwargs: None

    result = GameSession.chat(sess, assignee.name, secret_q)
    assert result.pending_action_id
    staged = db.conn.execute(
        "SELECT payload_json, action FROM pending_actions WHERE id=?",
        (result.pending_action_id,),
    ).fetchone()
    assert staged["action"] == "记进展"
    staged_payload = _json.loads(staged["payload_json"] or "{}")
    assert staged_payload.get("origin_chat_message_id") in (None, "", 0)

    applied = db.commit_pending_actions(
        state, minister_name=assignee.name,
        action_ids={int(result.pending_action_id)}, content=content,
    )
    assert applied and applied[0]["kind"] == "secret_order"
    # 无 explicit origin pin 的进展口谕按公开 provenance 放行。
    db.release_held_audience_knowledge(commit=True)
    sec_status = db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid_sec,),
    ).fetchone()["knowledge_status"]
    assert sec_status == "released"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id=?",
        (f"chat_message:{mid_sec}",),
    ).fetchone()[0] == 1
    assert any(secret_q in body for body in _shared_bodies(db))
    other_view = db.get_character_knowledge(state, other.name)
    other_text = " ".join(
        item.get("body", "")
        for item in [*other_view["events"], *other_view.get("public_events", [])]
    )
    assert secret_q not in other_text


def test_976_production_session_extract_update_withholds_oral(game, monkeypatch):
    """生产 extract「更新」：新口谕须 pin → stage → commit → withheld 不进共享。

    建议修法红测：口述更新→stage→commit→oral withheld shared=false。
    催办/记进展 无新正文不 pin（见 tools pure-public 测）；仅 更新 钉 pin。
    """
    import json as _json
    import types
    from types import SimpleNamespace

    import ming_sim.cli_backend as cb
    from ming_sim.session import GameSession

    db, state, content = game
    # extract 路径只对召对对象名下 active 密令 stage；承办人=召对对象。
    assignee = _active_ministers(db, content)[0]
    oid = create_test_secret_order(db,
        state, assignee.name, "密查国丈", "初旨：暗访田宅。", [],
    )
    secret_q = (
        "前令范围太窄，着尔扩至国丈典当与内库往来账目，皆须暗中簿记，"
        "不得走漏半句，亦不可经司礼监转呈。"
    )
    new_content = "扩查国丈典当及内库往来，事密勿使司礼监知。"
    mid_sec = db.append_chat_message(assignee.name, state.turn, "user", secret_q)

    # CLI extract 路径：api channel 会 early-return；需 CLI backend env。
    # 非 classifier 契约：显式 candidate，禁止 serial classify → 真 subprocess。
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "更新", "order_id": oid,
        "new_title": "密查国丈（扩）", "new_content": new_content,
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": "",
    })
    monkeypatch.setattr(cb, "extract_confirmation_intent", lambda *a, **k: "")
    monkeypatch.setattr(cb, "extract_appointment_action", lambda *a, **k: {
        "appoint_action": "无", "name": "", "office": "",
    })
    monkeypatch.setattr(cb, "resolve_minister_actions", lambda *a, **k: {
        "decree_text": None, "secret_order": None,
    })

    sess = SimpleNamespace(
        db=db, state=state, registry=None, content=content,
        llm_config=SimpleNamespace(channel=""),
    )
    sess.apply_cli_conversation_actions = types.MethodType(
        GameSession.apply_cli_conversation_actions, sess,
    )
    out = sess.apply_cli_conversation_actions(
        SimpleNamespace(name=assignee.name, office_type="兵部"),
        secret_q, "臣领旨，已拟改旨，请陛下定夺。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={
            "kind": "secret", "secret_action": "更新", "order_id": oid,
            "new_title": "密查国丈（扩）", "new_content": new_content,
            "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": "",
        },
    )
    pid = int(out.get("pending_action_id") or 0)
    assert pid > 0
    staged = db.conn.execute(
        "SELECT payload_json, action FROM pending_actions WHERE id=?", (pid,),
    ).fetchone()
    assert staged["action"] == "更新"
    staged_payload = _json.loads(staged["payload_json"] or "{}")
    assert int(staged_payload.get("origin_chat_message_id") or 0) == mid_sec

    applied = db.commit_pending_actions(
        state, minister_name=assignee.name, action_ids={pid}, content=content,
    )
    assert applied and applied[0]["kind"] == "secret_order"
    order = db.get_secret_order(oid)
    assert new_content in (order.get("content") or "")
    _assert_oral_decree_withheld_not_shared(
        db, state, mid_sec=mid_sec, secret_q=secret_q,
        speakers={assignee.name}, content=content,
    )


def test_976_production_extract_rush_progress_no_pure_public_pin(game, monkeypatch):
    """生产 extract 催办/记进展：仅 update/显式 pin 才 classified，late chat 不猜字面。"""
    import json as _json
    import types
    from types import SimpleNamespace

    import ming_sim.cli_backend as cb
    from ming_sim.session import GameSession

    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    public_q = "近来京营操练如何？先催办前令。"

    for secret_action, extra in (
        ("催办", {"deadline_months": 1}),
        ("记进展", {}),
    ):
        oid = create_test_secret_order(db,
            state, assignee.name, f"密查-{secret_action}", f"暗访-{secret_action}。", [],
            deadline_months=6,
        )
        if int(db.get_secret_order(oid)["turn_issued"] or 0) == int(state.turn):
            db.conn.execute(
                "UPDATE secret_orders SET turn_issued=? WHERE id=?",
                (state.turn - 1, oid),
            )
            db.conn.commit()
        mid_pub = db.append_chat_message(assignee.name, state.turn, "user", public_q)
        # 非 classifier 契约：显式 candidate，禁止 serial classify → 真 subprocess。
        monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
        monkeypatch.setattr(cb, "_trace", lambda rec: None)
        monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
            "secret_action": secret_action, "order_id": oid,
            "new_title": "", "new_content": "",
            "deadline_months": int(extra.get("deadline_months") or 0),
            "cultivate_skill": "", "cultivate_trait": "",
        })
        monkeypatch.setattr(cb, "extract_confirmation_intent", lambda *a, **k: "")
        monkeypatch.setattr(cb, "extract_appointment_action", lambda *a, **k: {
            "appoint_action": "无", "name": "", "office": "",
        })
        monkeypatch.setattr(cb, "resolve_minister_actions", lambda *a, **k: {
            "decree_text": None, "secret_order": None,
        })
        sess = SimpleNamespace(
            db=db, state=state, registry=None, content=content,
            llm_config=SimpleNamespace(channel=""),
        )
        sess.apply_cli_conversation_actions = types.MethodType(
            GameSession.apply_cli_conversation_actions, sess,
        )
        out = sess.apply_cli_conversation_actions(
            SimpleNamespace(name=assignee.name, office_type="兵部"),
            public_q, "臣遵旨催办/记进展。",
            has_directive=False, secret_order_id=None,
            preclassified_intent={
                "kind": "secret", "secret_action": secret_action, "order_id": oid,
                "new_title": "", "new_content": "",
                "deadline_months": int(extra.get("deadline_months") or 0),
                "cultivate_skill": "", "cultivate_trait": "",
            },
        )
        pid = int(out.get("pending_action_id") or 0)
        assert pid > 0, secret_action
        staged = db.conn.execute(
            "SELECT payload_json, action FROM pending_actions WHERE id=?", (pid,),
        ).fetchone()
        assert staged["action"] == secret_action
        staged_payload = _json.loads(staged["payload_json"] or "{}")
        assert staged_payload.get("origin_chat_message_id") in (None, "", 0), secret_action
        applied = db.commit_pending_actions(
            state, minister_name=assignee.name, action_ids={pid}, content=content,
        )
        assert applied and applied[0]["kind"] == "secret_order", secret_action
        pub_status = db.conn.execute(
            "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid_pub,),
        ).fetchone()["knowledge_status"]
        assert pub_status != "withheld", secret_action


# ── #976 红队四轴 + 消息级 provenance 根治（正负配对，真实接缝）──────────────


def _ks(db, mid: int) -> str:
    row = db.conn.execute(
        "SELECT knowledge_status FROM chat_messages WHERE id=?", (mid,),
    ).fetchone()
    return row["knowledge_status"] if row else ""


def _shared_source_count(db, mid: int) -> int:
    return db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id=?",
        (f"chat_message:{mid}",),
    ).fetchone()[0]


def _view_text(db, state, name: str) -> str:
    view = db.get_character_knowledge(state, name)
    return " ".join(
        item.get("body", "")
        for item in [*view.get("events", []), *view.get("public_events", [])]
    )


def _stage_new_secret(db, state, minister_name: str, marker: str) -> tuple[int, int]:
    mid = db.append_chat_message(minister_name, state.turn, "user", marker)
    pid = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建",
        minister_name=minister_name, target_id=None,
        payload={
            "title": marker[:20], "content": marker, "assignee": minister_name,
            "tags": [], "deadline_months": 0,
            "excluded_names": [], "excluded_offices": [],
            "covert_task": TYPED_COVERT_TASK,
        },
    )
    return mid, pid


def test_976_pending_secret_pin_survives_partial_commit_same_minister(game):
    """尚未确认的密令口谕不得被同臣另一密令的局部提交放行。"""
    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    marker_a = "待确认甲密：暗查内库亏空-A976"
    marker_b = "已确认乙密：密访京营虚额-B976"

    mid_a, pending_a = _stage_new_secret(db, state, assignee.name, marker_a)
    reply_a = "臣已领会甲密，容臣拟妥章程再请圣裁。"
    mid_a_reply = db.append_chat_message(
        assignee.name, state.turn, "minister", reply_a,
    )
    chat_turn_a = db.create_chat_turn(state, assignee.name, "pending-secret-a", 0)
    db.update_chat_turn_messages(
        chat_turn_a, user_message_id=mid_a, minister_message_id=mid_a_reply,
    )
    mid_b, pending_b = _stage_new_secret(db, state, assignee.name, marker_b)

    applied = db.commit_pending_actions(
        state, minister_name=assignee.name, action_ids={pending_b}, content=content,
    )

    assert [item["id"] for item in applied] == [pending_b]
    assert _ks(db, mid_b) == "withheld"
    assert _ks(db, mid_a) in ("held", "withheld")
    assert _ks(db, mid_a_reply) in ("held", "withheld")
    assert _shared_source_count(db, mid_a) == 0
    assert _shared_source_count(db, mid_a_reply) == 0
    assert all(marker_a not in body for body in _shared_bodies(db))
    assert all(reply_a not in body for body in _shared_bodies(db))

    # 明确拒绝后，pin 退出可重试生命周期；下一次既有 release 可按公开召对投轨。
    assert db.drop_pending_actions_for_minister(
        state.turn, assignee.name, action_ids={pending_a},
    ) == 1
    db.release_held_audience_knowledge()
    assert _ks(db, mid_a) == "released"
    assert _ks(db, mid_a_reply) == "released"
    assert _shared_source_count(db, mid_a) == 1
    assert _shared_source_count(db, mid_a_reply) == 1


def test_976_retryable_failed_secret_pin_stays_withheld_during_other_commit(game):
    """落库失败仍可原对话重试，故 pin 在失败生命周期内继续禁行。"""
    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    failed_marker = "失败可重试甲密：暗查不存在案卷-A976"
    committed_marker = "已确认乙密：密访仓场亏空-B976"

    mid_failed = db.append_chat_message(
        assignee.name, state.turn, "user", failed_marker,
    )
    failed_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="更新",
        minister_name=assignee.name, target_id=999999,
        payload={
            "title": "暗查不存在案卷", "content": failed_marker,
            "origin_chat_message_id": mid_failed,
        },
    )
    assert db.commit_pending_actions(
        state, minister_name=assignee.name, action_ids={failed_id}, content=content,
    ) == []
    assert db.list_failed_secret_order_actions(assignee.name)[0]["id"] == failed_id

    mid_committed, committed_id = _stage_new_secret(
        db, state, assignee.name, committed_marker,
    )
    assert db.commit_pending_actions(
        state, minister_name=assignee.name, action_ids={committed_id}, content=content,
    )

    assert _ks(db, mid_committed) == "withheld"
    assert _ks(db, mid_failed) in ("held", "withheld")
    assert _shared_source_count(db, mid_failed) == 0
    assert all(failed_marker not in body for body in _shared_bodies(db))


def test_976_rt01_two_secret_orders_different_assignees_no_cross_track(game):
    """红队① must：双密令跨接令者 — create(A) 不得把 B 的 held 口谕/应答投进共享库。

    病根1：upsert 内全局 release 无过滤。根治后 A/B origin 血缘互不串轨。
    """
    db, state, content = game
    ministers = _active_ministers(db, content)
    a, b, other = ministers[0], ministers[1], ministers[2]
    marker_a = "红队甲密：暗查国丈田宅典当虚实-A976"
    marker_b = "红队乙密：密访阉党京城私结-B976"
    ack_a = "臣领甲密旨，暗中查办，不敢外泄。"
    ack_b = "臣领乙密旨，即日密访，绝不声张。"

    mid_a_user = db.append_chat_message(a.name, state.turn, "user", marker_a)
    mid_a_min = db.append_chat_message(a.name, state.turn, "minister", ack_a)
    mid_b_user = db.append_chat_message(b.name, state.turn, "user", marker_b)
    mid_b_min = db.append_chat_message(b.name, state.turn, "minister", ack_b)

    for mid in (mid_a_user, mid_a_min, mid_b_user, mid_b_min):
        assert _ks(db, mid) == "held"

    oid_a = create_test_secret_order(db, state, a.name, "甲密查国丈", marker_a, [])
    assert oid_a > 0

    # create(A) 后 B 仍 held（不得 prematurely release 进共享）
    assert _ks(db, mid_a_user) == "withheld"
    assert _ks(db, mid_a_min) == "released"
    assert _ks(db, mid_b_user) == "held"
    assert _ks(db, mid_b_min) == "held"
    assert _shared_source_count(db, mid_b_user) == 0
    assert _shared_source_count(db, mid_b_min) == 0
    assert all(marker_b not in body for body in _shared_bodies(db))
    assert all(ack_b not in body for body in _shared_bodies(db))

    # brief 持久化 A 的 origin message id
    brief_a = db.conn.execute(
        "SELECT origin_chat_message_ids FROM secret_order_briefs WHERE order_id=?",
        (oid_a,),
    ).fetchone()
    import json as _json
    pins_a = _json.loads(brief_a["origin_chat_message_ids"] or "[]")
    assert mid_a_user in pins_a

    oid_b = create_test_secret_order(db, state, b.name, "乙密查阉党", marker_b, [])
    assert oid_b > 0

    assert _ks(db, mid_b_user) == "withheld"
    assert _ks(db, mid_b_min) == "released"
    assert _ks(db, mid_a_user) == "withheld"
    assert _ks(db, mid_a_min) == "released"
    assert _shared_source_count(db, mid_a_min) == 1
    assert _shared_source_count(db, mid_b_min) == 1
    assert all(marker_a not in body for body in _shared_bodies(db))
    assert all(marker_b not in body for body in _shared_bodies(db))
    assert any(ack_a in body for body in _shared_bodies(db))
    assert any(ack_b in body for body in _shared_bodies(db))

    assert marker_a not in _view_text(db, state, b.name)
    assert marker_b not in _view_text(db, state, a.name)
    assert marker_a not in _view_text(db, state, other.name)
    assert marker_b not in _view_text(db, state, other.name)


def test_976_rt02_misassigned_provenance_follows_origin_message(game):
    """红队② must：错位 provenance — 密令正文来自 A 场、派给 B，A 口谕不进共享。

    跟 origin message 走，不跟 assignee 走。create 无 origin pin 时 scoped release
    也不得把 A 的 held 口谕当纯公开投轨。
    """
    db, state, content = game
    a, b = _active_ministers(db, content)[:2]
    origin_on_a = "着尔密查内库亏空根由，事密勿使司礼监与户部堂官知-错位A976"
    extracted_for_b = "密查内库亏空根由，避开司礼监户部-指派B976"
    public_on_b = "臣报：山东漕粮起运如常。"

    mid_a_user = db.append_chat_message(a.name, state.turn, "user", origin_on_a)
    db.append_chat_message(
        a.name, state.turn, "minister", "臣领旨，密查内库，不敢外泄。",
    )
    mid_b_user = db.append_chat_message(b.name, state.turn, "user", "问卿漕运？")
    mid_b_min = db.append_chat_message(b.name, state.turn, "minister", public_on_b)

    # 错位：无 origin_minister_name / pin — 仅 assignee=B
    oid = create_test_secret_order(db, state, b.name, "密查内库", extracted_for_b, [])
    assert oid > 0

    # A 口谕不得 released 进共享（scoped：create(B) 不投 A 的 held）
    assert _ks(db, mid_a_user) != "released"
    assert _shared_source_count(db, mid_a_user) == 0
    assert all(origin_on_a not in body for body in _shared_bodies(db))
    assert all(extracted_for_b not in body for body in _shared_bodies(db))

    # 显式 pin 路径：origin 血缘跟 message id，不跟 assignee
    mid_a2 = db.append_chat_message(
        a.name, state.turn, "user",
        "续密：再查内库出纳簿-显式pin976",
    )
    oid2 = create_test_secret_order(db,
        state, b.name, "续密内库", "续查内库出纳簿", [],
        origin_minister_name=a.name,
        origin_chat_message_id=mid_a2,
    )
    assert oid2 > 0
    assert _ks(db, mid_a2) == "withheld"
    assert _shared_source_count(db, mid_a2) == 0
    brief2 = db.conn.execute(
        "SELECT origin_chat_message_ids, minister_name FROM secret_order_briefs "
        "WHERE order_id=?",
        (oid2,),
    ).fetchone()
    import json as _json
    pins2 = _json.loads(brief2["origin_chat_message_ids"] or "[]")
    assert mid_a2 in pins2
    assert brief2["minister_name"] == b.name
    # shared must not contain oral line (origin follows message id, not assignee)
    assert all("续密：再查内库出纳簿-显式pin976" not in body for body in _shared_bodies(db))
    assert all("续密：再查内库出纳簿-显式pin976" not in body for body in _event_bodies(db))

    # B 的公开 minister 应答不得消失（private 因 active assignee）
    assert _ks(db, mid_b_min) in ("private", "released", "held")
    assert _ks(db, mid_b_user) in ("withheld", "private", "released", "held")


def test_976_rt03_late_chat_after_create_same_turn(game):
    """红队③ should：密令 create 后同回合晚到行 — 接令者 private，他臣公开 released。"""
    db, state, content = game
    a, b = _active_ministers(db, content)[:2]
    secret = "密令正文：暗访边饷虚报-晚到976"
    oid = create_test_secret_order(db, state, a.name, "密查边饷", secret, [])
    assert oid > 0

    late_user = "再密嘱：勿使总督知会-晚到user"
    late_ack = "臣谨遵续旨，绝不走漏-晚到ack"
    other_public = "臣报：京营点卯无缺-晚到公开"

    mid_late_user = db.append_chat_message(a.name, state.turn, "user", late_user)
    mid_late_ack = db.append_chat_message(a.name, state.turn, "minister", late_ack)
    mid_other = db.append_chat_message(b.name, state.turn, "minister", other_public)

    assert _ks(db, mid_late_user) == "held"
    assert _ks(db, mid_late_ack) == "held"
    assert _ks(db, mid_other) == "held"

    db.release_held_audience_knowledge()
    assert _ks(db, mid_late_user) == "released"
    assert _ks(db, mid_late_ack) == "released"
    assert _ks(db, mid_other) == "released"
    assert any(late_user in body for body in _shared_bodies(db))
    assert any(late_ack in body for body in _shared_bodies(db))
    assert any(other_public in body for body in _shared_bodies(db))
    assert all(secret not in body for body in _shared_bodies(db))

    mid_even_later = db.append_chat_message(
        a.name, state.turn, "user", "第三次密嘱：焚稿-更晚976",
    )
    db.update_secret_order_by_id(state, oid, "密查边饷", secret + "；补焚稿", [])
    st_upd = _ks(db, mid_even_later)
    assert st_upd == "released"
    assert any("焚稿-更晚976" in body for body in _shared_bodies(db))


def test_976_rt04_undo_chat_turn_secret_order_brief_consistent(game):
    """红队④ should：undo 含密令口谕 — secret_orders 与 secret_order_briefs 回滚一致。

    真实 undo 删除密令父行后由 FK CASCADE 删除 brief；其它密令不受影响。
    """
    db, state, content = game
    a, b = _active_ministers(db, content)[:2]
    marker = "undo密令正文：密查火器局虚报-UNDO976"
    public_early = "臣报：漕运无阻-先轮公开976"

    ctid_early = db.create_chat_turn(state, b.name, "sess-early-976", 0)
    snap0 = db.capture_chat_rollback_snapshot()
    mid_b_pub = db.append_chat_message(b.name, state.turn, "minister", public_early)
    db.update_chat_turn_messages(ctid_early, minister_message_id=mid_b_pub)
    db.record_chat_turn_rollback_diffs(
        ctid_early, snap0, db.capture_chat_rollback_snapshot(),
    )
    unrelated_oid = create_test_secret_order(db,
        state, b.name, "巡查漕运", "未撤销密令正文-KEEP1026", [],
    )

    ctid = db.create_chat_turn(state, a.name, "sess-secret-undo-976", 0)
    before = db.capture_chat_rollback_snapshot()
    mid_u = db.append_chat_message(a.name, state.turn, "user", marker)
    mid_m = db.append_chat_message(
        a.name, state.turn, "minister", "臣领密旨，即查火器局。",
    )
    db.update_chat_turn_messages(ctid, user_message_id=mid_u, minister_message_id=mid_m)
    oid = create_test_secret_order(db, state, a.name, "密查火器局", marker, [])
    after = db.capture_chat_rollback_snapshot()
    db.record_chat_turn_rollback_diffs(ctid, before, after)

    assert oid > 0
    assert db.conn.execute(
        "SELECT COUNT(*) FROM secret_order_briefs WHERE order_id=?", (oid,),
    ).fetchone()[0] == 1
    assert db.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    undone = db.undo_chat_turn(ctid)
    assert undone is not None
    assert int(undone.get("id") or 0) == ctid
    assert db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["status"] == "undone"

    order_left = db.conn.execute(
        "SELECT COUNT(*) FROM secret_orders WHERE id=?", (oid,),
    ).fetchone()[0]
    brief_left = db.conn.execute(
        "SELECT COUNT(*) FROM secret_order_briefs WHERE order_id=?", (oid,),
    ).fetchone()[0]
    msg_u = db.conn.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE id=?", (mid_u,),
    ).fetchone()[0]
    msg_m = db.conn.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE id=?", (mid_m,),
    ).fetchone()[0]
    msg_b = db.conn.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE id=?", (mid_b_pub,),
    ).fetchone()[0]

    assert order_left == 0, f"secret_orders survived undo count={order_left}"
    assert brief_left == 0, f"secret_order_briefs orphan after undo count={brief_left}"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM secret_order_briefs WHERE order_id=?", (unrelated_oid,),
    ).fetchone()[0] == 1, "未撤销密令的 brief 不应受级联影响"
    assert msg_u == 0 and msg_m == 0
    assert msg_b == 1, "early B public message wrongly deleted"
    assert all(marker not in body for body in _shared_bodies(db))
    assert all(marker not in body for body in _event_bodies(db))
    assert not db._is_active_secret_order_assignee(a.name)


@pytest.mark.parametrize("rollback_entry", ["undo_chat_turn", "fail_chat_turn"])
def test_1026_secret_order_update_rollback_restores_existing_brief(game, rollback_entry):
    db, state, content = game
    minister = _active_ministers(db, content)[0]
    old_message_id = db.append_chat_message(
        minister.name, state.turn, "user", "旧令：密查旧案",
    )
    order_id = create_test_secret_order(db,
        state, minister.name, "旧密令", "旧密文", [],
        origin_chat_message_ids=[old_message_id],
    )
    old_brief = dict(db.conn.execute(
        "SELECT title, body, origin_chat_message_ids FROM secret_order_briefs WHERE order_id=?",
        (order_id,),
    ).fetchone())

    chat_turn_id = db.create_chat_turn(state, minister.name, f"{rollback_entry}-1026", 0)
    before = db.capture_chat_rollback_snapshot()
    user_message_id = db.append_chat_message(
        minister.name, state.turn, "user", "改令：转查新案",
    )
    minister_message_id = db.append_chat_message(
        minister.name, state.turn, "minister", "臣领修改后的密旨。",
    )
    db.update_chat_turn_messages(
        chat_turn_id,
        user_message_id=user_message_id,
        minister_message_id=minister_message_id,
    )
    assert db.update_secret_order_by_id(
        state, order_id, "新密令", "新密文", [],
        origin_chat_message_id=user_message_id,
        origin_minister_name=minister.name,
    )
    db.record_chat_turn_rollback_diffs(
        chat_turn_id, before, db.capture_chat_rollback_snapshot(),
    )

    getattr(db, rollback_entry)(chat_turn_id)

    restored_order = db.conn.execute(
        "SELECT title, content FROM secret_orders WHERE id=?", (order_id,),
    ).fetchone()
    restored_brief = db.conn.execute(
        "SELECT title, body, origin_chat_message_ids FROM secret_order_briefs WHERE order_id=?",
        (order_id,),
    ).fetchone()
    assert dict(restored_order) == {"title": "旧密令", "content": "旧密文"}
    assert dict(restored_brief) == old_brief


def test_976_rt05_save_restore_between_hold_and_release(game):
    """红队⑤ should：存档-恢复夹在 hold 与 release 之间 — P1 无损。"""
    import os

    db, state, content = game
    a, b = _active_ministers(db, content)[:2]
    marker = "存档夹心密令：密查驿递虚冒-SAVE976"
    pending_public = "臣报：延绥军情平稳-夹心held公开"

    mid_u = db.append_chat_message(a.name, state.turn, "user", marker)
    mid_ack = db.append_chat_message(
        a.name, state.turn, "minister", "臣领密旨查驿递。",
    )
    mid_pub = db.append_chat_message(b.name, state.turn, "minister", pending_public)

    oid = create_test_secret_order(db, state, a.name, "密查驿递", marker, [])
    st_pre = {
        "u": _ks(db, mid_u),
        "ack": _ks(db, mid_ack),
        "pub": _ks(db, mid_pub),
    }
    assert st_pre["u"] == "withheld"
    # create(A) scoped：B 的公开仍 held（不因全局 release 提前投轨）
    assert st_pre["pub"] == "held"

    late = "续谈：边墙修补进度-夹心后held"
    mid_late = db.append_chat_message(b.name, state.turn, "minister", late)
    assert _ks(db, mid_late) == "held"

    path = db.path
    backup_path = path + ".backup976"
    db.backup_to(backup_path)
    db.close()

    db2 = __import__("ming_sim.db", fromlist=["GameDB"]).GameDB(backup_path, content)
    try:
        state2 = db2.load_state()
        st_post = {
            "u": _ks(db2, mid_u),
            "ack": _ks(db2, mid_ack),
            "pub": _ks(db2, mid_pub),
            "late": _ks(db2, mid_late),
        }
        assert st_post["u"] == st_pre["u"]
        assert st_post["ack"] == st_pre["ack"]
        assert st_post["pub"] == st_pre["pub"]
        assert st_post["late"] == "held"

        brief = db2.conn.execute(
            "SELECT body, origin_chat_message_ids FROM secret_order_briefs "
            "WHERE order_id=?",
            (oid,),
        ).fetchone()
        order = db2.conn.execute(
            "SELECT status FROM secret_orders WHERE id=?", (oid,),
        ).fetchone()
        assert order is not None and order["status"] == "active"
        assert brief is not None and marker in (brief["body"] or "")
        import json as _json
        pins = _json.loads(brief["origin_chat_message_ids"] or "[]")
        assert mid_u in pins

        db2.release_held_audience_knowledge()
        assert _ks(db2, mid_u) == "withheld"
        assert all(marker not in body for body in _shared_bodies(db2))
        assert _ks(db2, mid_late) == "released"
        assert any(late in body for body in _shared_bodies(db2))
        assert _ks(db2, mid_pub) == "released"
        assert any(pending_public in body for body in _shared_bodies(db2))
        # silence: state2 used
        assert state2.turn == state.turn
    finally:
        db2.close()
        if os.path.exists(backup_path):
            os.remove(backup_path)


def test_976_message_level_origin_persisted_on_brief(game):
    """契约：密令分类后 brief.origin_chat_message_ids 持久化消息级血缘。"""
    import json as _json

    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    secret_q = "着尔密访国丈家产虚实，勿使外廷知-provenance976"
    mid = db.append_chat_message(assignee.name, state.turn, "user", secret_q)
    oid = create_test_secret_order(db,
        state, assignee.name, "密查国丈", "暗访国丈家产", [],
        origin_chat_message_id=mid,
    )
    brief = db.conn.execute(
        "SELECT origin_chat_message_ids FROM secret_order_briefs WHERE order_id=?",
        (oid,),
    ).fetchone()
    pins = _json.loads(brief["origin_chat_message_ids"] or "[]")
    assert pins == [mid]
    assert _ks(db, mid) == "withheld"
    # release 不得把已注册 origin 投轨
    db.release_held_audience_knowledge()
    assert _ks(db, mid) == "withheld"
    assert _shared_source_count(db, mid) == 0
