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
    create_llm_beat_generator,
)
from ming_sim.decree import _rescript_decisions
from ming_sim.models import TurnPhase
from tests.dossier_test_helpers import create_test_secret_order
from tests.conftest import (
    CHARACTER_AXIS_SENTINEL,
    active_ming_character,
    append_night_chat,
    open_audience_night,
    plant_character_axis_sentinels,
)


_CHARACTER_AXIS_KEYS = set(CHARACTER_AXIS_SENTINEL)
# 2026-08-17 22:30:36 一类墙钟不得触发忠诚=17 假阳（ISO 剥离即可；无平行 skip 表）。
_ISO_DT_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?")


def _walk_text_tokens(value) -> list[str]:
    """Collect player-meaningful text/number tokens from a payload tree."""
    out: list[str] = []
    pending: list[object] = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            for key, child in item.items():
                key_s = str(key)
                if key_s in _CHARACTER_AXIS_KEYS:
                    out.append(key_s)
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


def _assert_no_character_axis_keys(payload, *, where: str) -> None:
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


def _assert_no_character_sentinel_leak(payload, *, where: str) -> None:
    _assert_no_character_axis_keys(payload, where=where)

    # 值面：剥离墙钟后，哨兵数不得作为独立数字 token 出现
    blob = _ISO_DT_RE.sub("", _scan_blob(payload))
    for field, value in CHARACTER_AXIS_SENTINEL.items():
        token = str(value)
        # 独立数字：前后非数字，避免 117/170 误伤；时间戳已剥。
        if re.search(rf"(?<!\d){re.escape(token)}(?!\d)", blob):
            raise AssertionError(f"{where}: 人物抽象轴 {field}={value} 泄漏")


def _world_facts(db, state) -> dict[str, object]:
    army = db.conn.execute(
        "SELECT name, manpower FROM armies ORDER BY id LIMIT 1"
    ).fetchone()
    # 国库用与哨兵不重叠的显式世界事实，避免 0/空值使「放行」断言空转
    treasury = int(state.metrics.get("国库", 0) or 0)
    if treasury in CHARACTER_AXIS_SENTINEL.values() or treasury == 0:
        treasury = 120
        state.metrics["国库"] = treasury
    manpower = int(army["manpower"])
    if manpower in CHARACTER_AXIS_SENTINEL.values() or manpower == 0:
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


def _state_payload_runtime(db, state, content, *, pending_decisions=None):
    """既有轻壳（同 1234 形）+ 真 content/public_character，走 WebGame.state_payload。"""
    import web_app
    from ming_sim.skills import bind_content as bind_skills_content

    bind_skills_content(content)
    runtime = object.__new__(web_app.WebGame)
    runtime.favorites = set()
    runtime.session = SimpleNamespace(
        db=db,
        state=state,
        content=content,
        previous_summary="",
        last_decree="",
        last_report="",
        pending_count=lambda: 0,
        pending_decisions=lambda: list(pending_decisions or []),
        victory=lambda: {"status": "ongoing", "summary": ""},
    )
    runtime.directive_rows = lambda: []
    runtime.issue_payloads = lambda: []
    runtime.legacies_payload = lambda: []
    runtime.closed_this_turn_payloads = lambda: []
    runtime.map_nodes = lambda: []
    runtime.ending_payload = lambda: None
    # 真玩家输出面：绑定生产 public_character，扫 ministers/consorts/talent_pool
    runtime.public_character = lambda c: web_app.WebGame.public_character(runtime, c)
    runtime.character_power_id = lambda c: web_app.WebGame.character_power_id(runtime, c)
    return runtime


def test_guard_detector_flags_injected_character_sentinel():
    """检测器自证：payload 一旦带上人物轴哨兵值即红（AC：注入哨兵值即红）。"""
    with pytest.raises(AssertionError, match="loyalty=17"):
        _assert_no_character_sentinel_leak(
            {"content": f"其忠诚约{CHARACTER_AXIS_SENTINEL['loyalty']}"},
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
    minister = active_ming_character(db, content)
    plant_character_axis_sentinels(db, content, minister)
    facts = _world_facts(db, state)

    night_id = open_audience_night(db, state)
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
    llm_calls = []

    class _FakeAgent:
        def __init__(self, **_kwargs):
            pass

        def run(self, prompt):
            llm_calls.append(prompt)
            return SimpleNamespace(content="entry")

    monkeypatch.setattr("agno.agent.Agent", _FakeAgent)
    monkeypatch.setattr("ming_sim.llm_model.create_chat_model", lambda *_a, **_k: object())
    monkeypatch.setattr(
        "ming_sim.llm_model.extract_agent_text",
        lambda result: str(result.content),
    )
    enter_body = create_llm_beat_generator(object())(enter_inputs)
    assert len(llm_calls) == 1
    routed_materials = json.loads(llm_calls[0])
    assert routed_materials["场景节点"] == BEAT_ENTER
    assert routed_materials["人物"] == minister
    assert routed_materials["召法"] == an.METHOD_XUANRU
    an.append_ledger_entry(
        db, night_id, body=enter_body, tags=[an.TAG_ENTER],
        person_names=[minister],
    )
    _turn_id, mid = append_night_chat(
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
    _assert_no_character_axis_keys(payload, where="api_audience_scroll")
    _assert_no_character_axis_keys(scroll, where="read_night_scroll")
    _assert_no_character_axis_keys(projection, where="build_chat_projection")
    _assert_no_character_sentinel_leak(enter_inputs, where="assemble_beat_inputs")

    minister_msgs = [m for m in scroll if m.get("role") == "minister"]
    assert minister_msgs and minister_msgs[0]["highlights"] == ["辽饷", f"兵{facts['manpower']}"]
    scene_msgs = [m for m in scroll if m.get("role") == "scene"]
    assert scene_msgs and all("beat" in m and "role" in m for m in scene_msgs)
    assert all("beat" in m and "role" in m for m in payload["messages"])


def test_rescript_page_payload_keeps_sentinels_out_and_world_facts_in(game):
    """批红页：真 state_payload 信封（AWAITING_DECISION + pending_decisions）。"""
    db, state, content = game
    minister = active_ming_character(db, content)
    plant_character_axis_sentinels(db, content, minister)
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

    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)

    runtime = _state_payload_runtime(db, state, content, pending_decisions=stored)
    page = runtime.state_payload()

    assert page["pending_decisions"]
    assert "rescript_decisions" not in page
    assert "ministers" in page and "consorts" in page and "talent_pool" in page

    # 批红玩家面切片：pending_decisions + 同封 public_character 名册。
    # 不扫整封 state_payload 键面——armies.loyalty 等是军务域字段，非人物抽象轴。
    rescript_face = {
        "pending_decisions": page["pending_decisions"],
        "ministers": page["ministers"],
        "consorts": page["consorts"],
        "talent_pool": page["talent_pool"],
    }
    _assert_no_character_sentinel_leak(rescript_face, where="state_payload 批红信封")

    blob = _scan_blob(rescript_face)
    assert str(facts["year"]) in blob
    assert str(facts["period"]) in blob
    assert str(facts["manpower"]) in blob
    assert str(facts["treasury"]) in blob
    assert "批红待裁" in blob
    assert page["pending_decisions"][0]["rejection_reason"]
    assert page["pending_decisions"][0]["opposition"] == "东林"


def test_audience_archive_qiju_keeps_sentinels_out_and_world_facts_in(game, monkeypatch):
    """起居注：场档列表 + 退朝后同源卷轴只读面。"""
    import web_app

    db, state, content = game
    minister = active_ming_character(db, content)
    plant_character_axis_sentinels(db, content, minister)
    facts = _world_facts(db, state)

    night_id = open_audience_night(db, state)
    an.summon_enter(db, night_id, minister, method=an.METHOD_YUECI)
    scene_body = (
        f"{facts['year']}年{facts['period']}月密议，"
        f"库银{facts['treasury']}，边军{facts['manpower']}。"
    )
    an.append_ledger_entry(
        db, night_id, body=scene_body, tags=["军务"], person_names=[minister],
    )
    _turn_id, mid = append_night_chat(
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


# ── #570 族尾：本族新数据面扩写（认账 brief / 月度进展投影 / 案卷模拟器面）──

_FAMILY_SYSTEM_LEAK = re.compile(
    r"\b(?:promulgated|rejected|executing|proposed|force_promulgated|midzhi|"
    r"break_rank|blocked_layer|degraded|failed|fulfilled|transformed|"
    r"cabinet_drafting|palace_rescript|six_offices|is_break_rank)\b"
    r"|破格标|进展档"
)


def test_family_dossier_brief_and_progress_keep_system_words_out(game):
    """#474 族新面：认账 brief + monthly_progress 投影不得漏系统词/枚举。"""
    from ming_sim.decree import project_dossiers_for_simulator
    from ming_sim.decree_vocabulary import render_referenceable_dossier_brief
    from ming_sim.simulation import (
        build_simulator_payload,
        project_monthly_progress_for_simulator,
    )
    from tests.dossier_test_helpers import rejected_verdict

    db, state, content = game
    minister = active_ming_character(db, content)
    plant_character_axis_sentinels(db, content, minister)
    facts = _world_facts(db, state)

    dossier_id = db.create_decree_dossier(
        state,
        action_type="special_decree",
        decree_text=(
            f"{facts['year']}年发{facts['treasury']}万两，"
            f"调{facts['army_name']}{facts['manpower']}人"
        ),
        target_kind="character",
        target_id=minister,
        payload={"mode": "midzhi"},
    )
    db.apply_dossier_verdicts(state, [rejected_verdict(dossier_id, midzhi=True)])
    db.apply_dossier_promulgation(state, dossier_id, "force_promulgated")

    # monthly_progress 真源＝长差密令（护行/稽核 + deadline≥2），与 #566/#569 同缝。
    order_id = create_test_secret_order(db, 
        state, minister, f"护行{facts['army_name']}饷",
        f"逐月核兵{facts['manpower']}不得外泄", ["护行"], deadline_months=4,
    )
    errand_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    db.record_dossier_progress(
        errand_id, state.turn, "在途",
        f"密奏：已核兵{facts['manpower']}，库银约{facts['treasury']}，不得外泄",
        origin="dossier-report:monthly_errand",
    )

    candidates = db.list_referenceable_dossiers(minister, state.turn)
    brief = render_referenceable_dossier_brief(candidates)
    monthly = project_monthly_progress_for_simulator(db)
    visible = [
        row for row in (
            db.get_decree_dossier(dossier_id),
            db.get_decree_dossier(errand_id),
        )
        if row is not None
    ]
    sim_rows = project_dossiers_for_simulator(visible, db, state)
    payload = build_simulator_payload(state, db, "", "", decree_dossiers=sim_rows)

    # 玩家可读面：认账 brief + 公共 monthly_progress。
    # 推演 decree_dossiers 投影按 #569 契约保留 status/mode 结构位（机器面，非 P4 玩家面）。
    for label, surface in (
        ("认账 brief", brief),
        ("monthly_progress", monthly),
        ("simulator payload monthly", payload.get("monthly_progress")),
    ):
        _assert_no_character_sentinel_leak(surface, where=label)
        blob = surface if isinstance(surface, str) else _scan_blob(surface)
        assert _FAMILY_SYSTEM_LEAK.search(str(blob)) is None, f"{label} 漏系统词: {blob}"

    # 人物轴哨兵仍不得进机器投影键值（与既有 547 同构）。
    _assert_no_character_sentinel_leak(sim_rows, where="sim dossiers")

    # 世界事实仍可达（年月/兵额/库银）；进展档只投 band，密奏正文不进公共 monthly_progress。
    assert str(facts["year"]) in brief or str(facts["treasury"]) in brief
    assert all("memorial_text" not in row for row in monthly)
    assert any(row.get("progress_band") == "在途" for row in monthly)
    # brief 定性中文，不得把英文枚举念给皇帝。
    assert "打回" in brief or "强颁" in brief
