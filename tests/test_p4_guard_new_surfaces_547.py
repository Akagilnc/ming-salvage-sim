"""#547 — P4 哨兵守门扩新面：卷轴 / 判官清单 / 批红页 / 起居注。

0010/0011 先例：偏门哨兵值注入人物抽象轴后，确定性引擎产物面不得泄漏；
世界事实数值（年月 / 银两 / 兵额）不在此限（0023 D10）。
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ming_sim import audience_night as an
from ming_sim.beat_orchestration import (
    BEAT_ENTER,
    assemble_beat_inputs,
    production_beat_generator,
)
from ming_sim.decree import _rescript_decisions
from ming_sim.memories import build_timeline


# 偏门哨兵：0010/1023 口径；扫描时剥离时间戳防与日/时分假阳。
_SENTINEL = {
    "loyalty": 17,
    "ability": 37,
    "integrity": 57,
    "courage": 77,
    "identity": 97,
}
_CHARACTER_AXIS_KEYS = set(_SENTINEL)
_SKIP_VALUE_KEYS = {
    "time", "created_at", "closed_at", "timestamp", "updated_at",
}
# 2026-08-17 22:30:36 一类墙钟不得触发忠诚=17 假阳。
_ISO_DT_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?")


def _plant_character_sentinels(db, content, name: str) -> dict[str, int]:
    db.conn.execute(
        "UPDATE characters SET loyalty=?, ability=?, integrity=?, courage=?, identity=? "
        "WHERE name=?",
        (*_SENTINEL.values(), name),
    )
    db.conn.commit()
    character = content.characters[name]
    for field, value in _SENTINEL.items():
        setattr(character, field, value)
    return dict(_SENTINEL)


def _walk_text_tokens(value, *, skip_keys: set[str] = frozenset()) -> list[str]:
    """Collect player-meaningful text/number tokens; skip pure clock fields."""
    out: list[str] = []
    pending: list[object] = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            for key, child in item.items():
                key_s = str(key)
                if key_s in _CHARACTER_AXIS_KEYS:
                    out.append(key_s)
                if key_s in skip_keys or key_s in _SKIP_VALUE_KEYS:
                    continue
                pending.append(child)
        elif isinstance(item, (list, tuple, set)):
            pending.extend(item)
        elif item is None or isinstance(item, bool):
            continue
        elif isinstance(item, (int, float)):
            out.append(str(int(item)) if float(item).is_integer() else str(item))
        else:
            out.append(str(item))
    return out


def _scan_blob(value) -> str:
    return "\t".join(_walk_text_tokens(value))


def _assert_no_character_sentinel_leak(payload, *, where: str) -> None:
    # 键面：人物抽象轴英文字段名不得进玩家 payload
    keys: set[str] = set()
    pending = [payload]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            keys.update(str(k) for k in item)
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
    leaked_keys = _CHARACTER_AXIS_KEYS & keys
    assert not leaked_keys, f"{where}: payload 键面露出人物抽象轴 {leaked_keys}"

    # 值面：剥离墙钟后，哨兵数不得作为独立数字 token 出现
    blob = _ISO_DT_RE.sub("", _scan_blob(payload))
    for field, value in _SENTINEL.items():
        token = str(value)
        # 独立数字：前后非数字，避免 117/170 误伤；时间戳已剥。
        if re.search(rf"(?<!\d){re.escape(token)}(?!\d)", blob):
            raise AssertionError(f"{where}: 人物抽象轴 {field}={value} 泄漏")


def _active_minister(db, content) -> str:
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "AND office_type NOT IN ('后宫','宗藩') ORDER BY rowid LIMIT 1"
    ).fetchone()
    assert row is not None
    name = str(row["name"])
    assert name in content.characters
    return name


def _open_night(db, state) -> int:
    return int(an.open_night(db, state, time_of_day="戌时", location="乾清宫")["id"])


def _chat(db, state, night_id: int, minister: str, user_text: str, answer: str, seq: int):
    uid = db.append_chat_message(minister, state.turn, "user", user_text)
    mid = db.append_chat_message(minister, state.turn, "minister", answer)
    cur = db.conn.execute(
        "INSERT INTO chat_turns "
        "(minister_name,turn,year,period,user_message_id,minister_message_id,night_id,night_seq) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (minister, state.turn, state.year, state.period, uid, mid, night_id, seq),
    )
    db.conn.commit()
    return int(cur.lastrowid), int(mid)


def _world_facts(db, state) -> dict[str, object]:
    army = db.conn.execute(
        "SELECT name, manpower FROM armies ORDER BY id LIMIT 1"
    ).fetchone()
    # 国库用与哨兵不重叠的显式世界事实，避免 0/空值使「放行」断言空转
    treasury = int(state.metrics.get("国库", 0) or 0)
    if treasury in _SENTINEL.values() or treasury == 0:
        treasury = 120
        state.metrics["国库"] = treasury
    manpower = int(army["manpower"])
    if manpower in _SENTINEL.values() or manpower == 0:
        manpower = 3500
        db.conn.execute(
            "UPDATE armies SET manpower=? WHERE name=?",
            (manpower, army["name"]),
        )
        db.conn.commit()
    return {
        "year": int(state.year),
        "period": int(state.period),
        "manpower": manpower,
        "army_name": str(army["name"]),
        "treasury": treasury,
    }


def test_guard_detector_flags_injected_character_sentinel():
    """检测器自证：payload 一旦带上人物轴哨兵值即红（AC：注入哨兵值即红）。"""
    with pytest.raises(AssertionError, match="loyalty=17"):
        _assert_no_character_sentinel_leak(
            {"content": f"其忠诚约{_SENTINEL['loyalty']}"},
            where="detector",
        )
    with pytest.raises(AssertionError, match="人物抽象轴"):
        _assert_no_character_sentinel_leak(
            {"loyalty": "离心已显"},
            where="detector",
        )
    # 世界事实与墙钟不得误伤
    _assert_no_character_sentinel_leak(
        {
            "content": "1628年3月发帑120万两，兵3500",
            "time": "2026-08-17 22:30:36",
        },
        where="detector-world",
    )


def test_scroll_and_highlight_list_keep_sentinels_out_and_world_facts_in(game, monkeypatch):
    """场卷轴序列（scene 文案 + 判官清单 highlights）玩家读面。"""
    import web_app

    db, state, content = game
    minister = _active_minister(db, content)
    _plant_character_sentinels(db, content, minister)
    facts = _world_facts(db, state)

    night_id = _open_night(db, state)
    scene_body = (
        f"{facts['year']}年{facts['period']}月，"
        f"发帑{facts['treasury']}万两，调{facts['army_name']}兵{facts['manpower']}。"
    )
    an.append_ledger_entry(
        db, night_id, body=scene_body, tags=["军务"], person_names=[minister],
    )
    enter_inputs = assemble_beat_inputs(
        db, state, beat_kind=BEAT_ENTER, night_id=night_id,
        time_of_day="戌时", location="乾清宫",
        person_name=minister, summon_method=an.METHOD_XUANRU,
    )
    enter_body = production_beat_generator(enter_inputs)
    an.append_ledger_entry(
        db, night_id, body=enter_body, tags=[an.TAG_ENTER],
        person_names=[minister],
    )
    _turn_id, mid = _chat(
        db, state, night_id, minister,
        f"辽饷与{facts['army_name']}兵额如何？",
        f"臣请据实核账，兵约{facts['manpower']}。",
        20,
    )
    db.set_message_highlights(mid, ["辽饷", f"兵{facts['manpower']}"])

    monkeypatch.setattr(web_app, "get_game", lambda: SimpleNamespace(db=db))
    payload = TestClient(web_app.app).get("/api/audience/scroll").json()
    scroll = an.read_night_scroll(db, night_id)
    projection = db.build_chat_projection(minister)

    assert payload["messages"]
    assert scroll
    _assert_no_character_sentinel_leak(payload, where="api_audience_scroll")
    _assert_no_character_sentinel_leak(scroll, where="read_night_scroll")
    _assert_no_character_sentinel_leak(projection, where="build_chat_projection")
    _assert_no_character_sentinel_leak(enter_inputs, where="assemble_beat_inputs")
    _assert_no_character_sentinel_leak(enter_body, where="production_beat_generator")

    blob = _scan_blob({"api": payload, "scroll": scroll, "projection": projection})
    assert str(facts["year"]) in blob
    assert str(facts["period"]) in blob
    assert str(facts["manpower"]) in blob
    assert str(facts["treasury"]) in blob

    minister_msgs = [m for m in scroll if m.get("role") == "minister"]
    assert minister_msgs and minister_msgs[0]["highlights"] == ["辽饷", f"兵{facts['manpower']}"]
    scene_msgs = [m for m in scroll if m.get("role") == "scene"]
    assert any(scene_body in str(m.get("content") or "") for m in scene_msgs)


def test_rescript_page_payload_keeps_sentinels_out_and_world_facts_in(game):
    """批红页 pending_decisions 玩家读面。"""
    db, state, content = game
    minister = _active_minister(db, content)
    _plant_character_sentinels(db, content, minister)
    facts = _world_facts(db, state)

    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=(
            f"发{facts['treasury']}万两饷银，调{facts['army_name']}"
            f"{facts['manpower']}人清核河工"
        ),
        target_kind="issue",
        target_id="river-works",
        payload={"mode": "ordinary"},
    )
    dossier = next(
        row for row in db.list_decree_dossiers() if int(row["id"]) == dossier_id
    )
    verdict = {
        "dossier_id": dossier_id,
        "decision": "rejected",
        "reason": (
            f"科臣以{facts['year']}年{facts['period']}月饷额与"
            f"兵{facts['manpower']}未核为由封驳。"
        ),
        "primary_opponents": [{"kind": "faction", "key": "东林"}],
        "midzhi_unpromulgatable": False,
    }
    decisions = _rescript_decisions([verdict], [dossier])
    assert decisions and decisions[0]["title"] == "批红待裁"
    db.save_pending_decisions(state.turn, decisions)
    stored = db.list_pending_decisions(state.turn)

    page = {
        "pending_decisions": stored,
        "rescript_decisions": decisions,
    }
    _assert_no_character_sentinel_leak(page, where="批红页 pending_decisions")

    blob = _scan_blob(page)
    assert str(facts["year"]) in blob
    assert str(facts["period"]) in blob
    assert str(facts["manpower"]) in blob
    assert str(facts["treasury"]) in blob
    assert "批红待裁" in blob
    assert stored[0]["rejection_reason"]
    assert stored[0]["opposition"] == "东林"


def test_audience_archive_qiju_keeps_sentinels_out_and_world_facts_in(game, monkeypatch):
    """起居注：场档列表 + 退朝后同源卷轴只读面。"""
    import web_app

    db, state, content = game
    minister = _active_minister(db, content)
    _plant_character_sentinels(db, content, minister)
    facts = _world_facts(db, state)

    night_id = _open_night(db, state)
    an.summon_enter(db, night_id, minister, method=an.METHOD_YUECI)
    scene_body = (
        f"{facts['year']}年{facts['period']}月密议，"
        f"库银{facts['treasury']}，边军{facts['manpower']}。"
    )
    an.append_ledger_entry(
        db, night_id, body=scene_body, tags=["军务"], person_names=[minister],
    )
    _turn_id, mid = _chat(
        db, state, night_id, minister,
        "边饷如何？",
        f"边军约{facts['manpower']}可支。",
        10,
    )
    db.set_message_highlights(mid, [f"{facts['manpower']}可支"])
    db.conn.execute(
        "UPDATE audience_nights SET status='closed', closed_at=CURRENT_TIMESTAMP WHERE id=?",
        (night_id,),
    )
    db.conn.commit()

    archives = db.list_closed_night_archives()
    archived_scroll = an.read_night_scroll(db, night_id)
    monkeypatch.setattr(web_app, "get_game", lambda: SimpleNamespace(db=db))
    client = TestClient(web_app.app)
    history = client.get("/api/history/turns").json()
    scroll_http = client.get(f"/api/audience/scroll?night_id={night_id}").json()

    assert archives
    assert any(item.get("kind") == "night" for item in history["turns"])

    _assert_no_character_sentinel_leak(archives, where="list_closed_night_archives")
    _assert_no_character_sentinel_leak(history, where="api_history_turns")
    _assert_no_character_sentinel_leak(archived_scroll, where="archived read_night_scroll")
    _assert_no_character_sentinel_leak(scroll_http, where="archived api_audience_scroll")

    blob = _scan_blob({
        "archives": archives,
        "history": history,
        "scroll": archived_scroll,
        "http": scroll_http,
    })
    assert str(facts["year"]) in blob
    assert str(facts["period"]) in blob
    assert str(facts["manpower"]) in blob
    assert str(facts["treasury"]) in blob
    assert any(str(facts["year"]) in str(item.get("title") or "") for item in archives)


def test_chapter_memory_timeline_surface_allows_world_facts_not_axis_sentinels(game):
    """起居注章节浓缩进入结局时间线的确定性装配面（chapter 字段）。"""
    db, state, content = game
    minister = _active_minister(db, content)
    _plant_character_sentinels(db, content, minister)
    facts = _world_facts(db, state)

    chapter_body = (
        f"{facts['year']}年{facts['period']}月，发帑{facts['treasury']}万两，"
        f"边军{facts['manpower']}整饬；{minister}入对。"
    )
    db.save_chapter_memory(
        state,
        title=f"崇祯{facts['year']}年{facts['period']}月",
        body=chapter_body,
        tags=["军务", minister],
    )
    db.save_turn_extraction(
        state,
        decree_text=f"诏曰：发帑{facts['treasury']}万两。",
        narrative=chapter_body,
        extractor_output=json.dumps({
            "economy_moves": [{"account": "国库", "delta": -int(facts["treasury"])}],
            "army_delta": [{"name": facts["army_name"], "manpower": int(facts["manpower"])}],
        }, ensure_ascii=False),
    )

    timeline = build_timeline(db, upto_turn=state.turn)
    assert timeline
    _assert_no_character_sentinel_leak(timeline, where="build_timeline")
    blob = _scan_blob(timeline)
    assert str(facts["year"]) in blob
    assert str(facts["period"]) in blob
    assert str(facts["treasury"]) in blob
    assert any(chapter_body == str(item.get("chapter") or "") for item in timeline)
