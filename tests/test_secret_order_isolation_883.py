"""契约钉 #883·密令源头隔离。

密令及一切派生只进 ①密令本体表 ②接令者专用密令简报表；
不进任何共享存储；披露事件是唯一公开化通道；
公共产出 LLM 输入构建器永不预读密令。
"""

from __future__ import annotations

from ming_sim import issues
from ming_sim.decree import settle_with_delta
from ming_sim.simulation import build_extractor_shared_context, build_simulator_payload


def _active_ministers(db, content):
    return [
        character
        for character in content.characters.values()
        if character.office_type not in ("后宫", "宗藩")
        and db.get_character_status(character.name)[0] == "active"
    ]


def test_883_two_turn_probe_secret_never_enters_shared_archives(game):
    """两回合探针：T1 下密令 → T2 结算 → 共享档无派生；接令者简报表有。"""
    db, state, content = game
    assignee, other = _active_ministers(db, content)[:2]
    marker = "乙巳密查内廷账目883探针"

    oid = db.create_secret_order(state, assignee.name, "乙巳密查", marker, [])
    assert oid > 0

    # T1 → T2：推进一回合再写共享汇总（跨回合旁路才是病灶）。
    settle_with_delta(
        state, db, {}, before_turn=state.turn, content=content,
        narrative=f"本月朝局平缓。{marker} 之类密事不得入邸报。",
    )
    db.save_turn_report(state, f"邸报复述：{marker}")
    db.save_chapter_memory(state, "朝局", f"章节复述：{marker}")

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
    bodies = [
        row["body"]
        for row in db.conn.execute("SELECT body FROM character_knowledge_sources").fetchall()
    ]
    assert all(marker not in (body or "") for body in bodies)


def test_883_audience_chat_path_does_not_leave_secret_in_shared_sources(game):
    """真实召对路径：append_chat_message → create_secret_order 后共享源无密令原话。

    #883 结构隔离：密令正文只进本体表 + 接令者简报；不得以 audience/chat_message
    行残留在 character_knowledge_sources（单点拒收 kind=secret_order 盖不住此旁路）。
    """
    db, state, content = game
    assignee, other = _active_ministers(db, content)[:2]
    marker = "密令：真实召对密令旁路883，不可外泄"

    db.append_chat_message(assignee.name, state.turn, "user", marker)
    oid = db.create_secret_order(state, assignee.name, "乙巳密查旁路", marker, [])
    assert oid > 0

    shared_bodies = [
        row["body"] or ""
        for row in db.conn.execute("SELECT body FROM character_knowledge_sources").fetchall()
    ]
    shared_event_bodies = [
        row["body"] or ""
        for row in db.conn.execute("SELECT body FROM character_knowledge_events").fetchall()
    ]
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
    assert all(marker not in body for body in shared_bodies)
    assert all(marker not in body for body in shared_event_bodies)
    assert marker not in other_text
    assert marker in assignee_text


def test_883_audience_chat_paraphrase_does_not_leave_origin_in_shared_sources(game):
    """召对原话 ≠ 密令 title/body 时，结构隔离仍须清掉同次召对 audience 共享行。

    文本 needle 只覆盖精确子串；LLM 润稿后的 title/body 与皇帝原话不一致时，
    必须按 turn+接令者血缘清 audience/chat_message 共享源（#883 结构隔离）。
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
    # 同回合无关召对（另一大臣）不得被误清。
    other_public = "臣报：山东漕粮本月起运如常，无阻。"
    db.append_chat_message(other.name, state.turn, "user", other_public)

    oid = db.create_secret_order(
        state, assignee.name, extracted_title, extracted_body, [],
    )
    assert oid > 0

    shared_bodies = [
        row["body"] or ""
        for row in db.conn.execute("SELECT body FROM character_knowledge_sources").fetchall()
    ]
    shared_event_bodies = [
        row["body"] or ""
        for row in db.conn.execute("SELECT body FROM character_knowledge_events").fetchall()
    ]
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
    assert extracted_body in (brief["body"] or "")
    # 原话与润稿正文均不得残留共享存储。
    assert all(chat_origin not in body for body in shared_bodies)
    assert all(chat_origin not in body for body in shared_event_bodies)
    assert all(extracted_body not in body for body in shared_bodies)
    assert all(extracted_body not in body for body in shared_event_bodies)
    assert chat_origin not in other_text
    assert extracted_body not in other_text
    # 接令者仍从专用简报读到密令；同回合他人公开召对不受误伤。
    assert extracted_body in assignee_text
    assert any(other_public in body for body in shared_bodies)


def test_883_shared_write_seam_refuses_body_matching_active_secret_brief(game):
    """共享写入接缝：正文携带已有密令简报原文时，不得以 audience 等形态落共享源。"""
    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    marker = "已存简报原话不得再入共享883"

    oid = db.create_secret_order(state, assignee.name, "密查简报", marker, [])
    assert oid > 0

    db.register_character_knowledge_source(
        state,
        [{"character_id": assignee.name}],
        "audience",
        "召对",
        f"臣复述密旨：{marker}",
        source_id="chat_message:replay-secret",
    )
    bodies = [
        row["body"] or ""
        for row in db.conn.execute("SELECT body FROM character_knowledge_sources").fetchall()
    ]
    assert all(marker not in body for body in bodies)


def test_883_public_audience_same_turn_survives_secret_scrub(game):
    """F1：接令者同回合先公开后密令时，公开召对 audience 不得被结构 scrub 一并吞掉。"""
    db, state, content = game
    assignee, other = _active_ministers(db, content)[:2]
    public_line = "臣报：京营操练如常，无异常。"
    secret_chat = (
        "着尔密访国丈家产虚实，凡田宅典当与内库往来账目，皆须暗中簿记，"
        "不得走漏半句，亦不可经司礼监转呈。"
    )
    extracted = "暗访国丈田宅典当及内库往来，事密勿使司礼监知。"

    db.append_chat_message(assignee.name, state.turn, "user", "近来京营操练如何？")
    db.append_chat_message(assignee.name, state.turn, "minister", public_line)
    db.append_chat_message(assignee.name, state.turn, "user", secret_chat)
    db.append_chat_message(assignee.name, state.turn, "minister", "臣领密旨，即暗中查办。")
    oid = db.create_secret_order(state, assignee.name, "密查国丈", extracted, [])
    assert oid > 0

    shared_bodies = [
        row["body"] or ""
        for row in db.conn.execute("SELECT body FROM character_knowledge_sources").fetchall()
    ]
    event_bodies = [
        row["body"] or ""
        for row in db.conn.execute("SELECT body FROM character_knowledge_events").fetchall()
    ]
    assignee_view = db.get_character_knowledge(state, assignee.name)
    assignee_text = " ".join(
        item.get("body", "") for item in assignee_view["events"] + assignee_view.get("public_events", [])
    )
    other_view = db.get_character_knowledge(state, other.name)
    other_text = " ".join(
        item.get("body", "")
        for item in [*other_view["events"], *other_view.get("public_events", [])]
    )

    # 公开召对仍在共享见闻 / 接令者参与即知面。
    assert any(public_line in body for body in shared_bodies + event_bodies)
    assert public_line in assignee_text
    # 密令原话与润稿不得残留共享存储；他臣不得见。
    assert all(secret_chat not in body for body in shared_bodies)
    assert all(extracted not in body for body in shared_bodies)
    assert secret_chat not in other_text
    assert extracted not in other_text
    assert extracted in assignee_text


def test_883_post_brief_paraphrase_audience_never_enters_shared_sources(game):
    """F2：brief 已存在后，不含 title/body 精确子串的改写转述不得写入共享 audience 源。"""
    db, state, content = game
    assignee, other = _active_ministers(db, content)[:2]
    marker_body = "密查阉党余孽在京城私结会所并藏匿禁书"
    oid = db.create_secret_order(state, assignee.name, "密查阉党", marker_body, [])
    assert oid > 0

    paraphrase = "臣已暗中查访阉党旧部在京活动，尚未惊动外廷。"
    assert marker_body not in paraphrase
    assert "密查阉党" not in paraphrase

    mid = db.append_chat_message(assignee.name, state.turn, "minister", paraphrase)
    shared = list(
        db.conn.execute(
            "SELECT body, kind FROM character_knowledge_sources WHERE source_id=?",
            (f"chat_message:{mid}",),
        ).fetchall()
    )
    assert shared == []
    bodies = [
        row["body"] or ""
        for row in db.conn.execute("SELECT body FROM character_knowledge_sources").fetchall()
    ]
    assert all(paraphrase not in body for body in bodies)
    other_view = db.get_character_knowledge(state, other.name)
    other_text = " ".join(
        item.get("body", "")
        for item in [*other_view["events"], *other_view.get("public_events", [])]
    )
    assert paraphrase not in other_text


def test_883_pure_public_archive_lands_while_secret_brief_active(game):
    """F3：世上存在 active brief 时，纯公开月末叙事/邸报仍应入档（不整闸吞公开层）。"""
    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    public = "本月山东漕粮起运如常，无阻无欠。"
    secret_marker = "不得入档的密令正文883"
    db.create_secret_order(state, assignee.name, "密查某事", secret_marker, [])

    db.save_turn_report(state, public)
    db.save_chapter_memory(state, "朝局公开", public)
    report_blob = " ".join(item["report"] for item in db.list_turn_reports())
    chapter_blob = " ".join(item["body"] for item in db.list_chapter_memories())
    assert public in report_blob
    assert public in chapter_blob
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


def test_883_cross_turn_chat_origin_scrubbed_on_late_secret_create(game):
    """F4：召对原话在 T 写入共享后，T+1 才 create（润稿 body）仍须清掉跨回合残留。"""
    db, state, content = game
    assignee, other = _active_ministers(db, content)[:2]
    chat_origin = (
        "着尔密访国丈家产虚实，凡田宅典当与内库往来账目，皆须暗中簿记，"
        "不得走漏半句，亦不可经司礼监转呈。"
    )
    extracted = "暗访国丈田宅典当及内库往来，事密勿使司礼监知。"
    assert extracted not in chat_origin and chat_origin not in extracted

    db.append_chat_message(assignee.name, state.turn, "user", chat_origin)
    state.turn = int(state.turn) + 1
    db.save_state(state)
    oid = db.create_secret_order(state, assignee.name, "密查国丈", extracted, [])
    assert oid > 0

    shared_bodies = [
        row["body"] or ""
        for row in db.conn.execute("SELECT body FROM character_knowledge_sources").fetchall()
    ]
    event_bodies = [
        row["body"] or ""
        for row in db.conn.execute("SELECT body FROM character_knowledge_events").fetchall()
    ]
    other_view = db.get_character_knowledge(state, other.name)
    other_text = " ".join(
        item.get("body", "")
        for item in [*other_view["events"], *other_view.get("public_events", [])]
    )
    assert all(chat_origin not in body for body in shared_bodies)
    assert all(chat_origin not in body for body in event_bodies)
    assert chat_origin not in other_text


def test_883_shared_archive_bypass_positive_and_negative(game):
    """复审员旁路：共享汇总正负断言——有密令时 raw 报告不得原样入档；无密令时公开文可入。"""
    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    secret_marker = "旁路密令正负883"
    public_marker = "旁路公开正负883"

    # 负向：存在未公开密令时，聚合 raw 报告不得把密令正文写入共享档。
    db.create_secret_order(state, assignee.name, "旁路密查", secret_marker, [])
    db.save_turn_report(state, f"公开句；{secret_marker}")
    db.save_chapter_memory(state, "朝局", f"公开句；{secret_marker}")
    report_blob = " ".join(item["report"] for item in db.list_turn_reports())
    chapter_blob = " ".join(item["body"] for item in db.list_chapter_memories())
    assert secret_marker not in report_blob
    assert secret_marker not in chapter_blob
    # 同闸：有密令时纯公开句仍可入档（F3；不因 brief 存在整闸吞公开层）。
    assert "公开句" in report_blob
    assert "公开句" in chapter_blob

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


def test_883_only_explicit_leak_conclusion_promotes_secret_order_to_public(game):
    """泄漏接线：无泄漏结论不公开；显式泄漏结论 → 披露事件 → 进入公共面。"""
    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    oid = db.create_secret_order(state, assignee.name, "密查盐案", "甲子密查盐案883", [])

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
    oid = db.create_secret_order(state, assignee.name, "密查仓案", "丙寅密查仓案883", [])

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
            db, state, "", "", secret_orders=secret_orders, module=module,
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
