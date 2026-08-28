"""#569: 照账演与认账 — 补钉契约 A–H 机械 AC。"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from ming_sim.decree import project_dossiers_for_simulator
from ming_sim.decree_vocabulary import (
    SIM_DOSSIER_EXECUTION_KEYS,
    SIM_DOSSIER_NARRATIVE_KEYS,
    render_referenceable_dossier_brief,
)
from ming_sim.simulation import build_extractor_shared_context, build_simulator_payload
from tests.dossier_test_helpers import TYPED_COVERT_TASK, rejected_verdict as _rejected_verdict
from tests.dossier_test_helpers import create_test_secret_order


_REPO = Path(__file__).resolve().parents[1]
_SEASON_SIM = _REPO / "content" / "prompts" / "season_simulator.md"
_ENGLISH_LEAK = re.compile(
    r"\b(?:promulgated|rejected|executing|proposed|force_promulgated|midzhi)\b"
)


def _active_minister(db) -> str:
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "ORDER BY name LIMIT 1"
    ).fetchone()["name"])


def _long_secret(db, state, *, title="护行辽饷密件", memorial="密奏：已验关防，不得外泄"):
    actor = _active_minister(db)
    order_id = create_test_secret_order(db, 
        state, actor, title, "逐月办理不得外泄", ["护行"], deadline_months=4,
        covert_task=TYPED_COVERT_TASK,
    )
    dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    db.record_dossier_progress(dossier_id, state.turn, "在途核验", memorial)
    return order_id, dossier_id, title, memorial


# ── A. monthly_progress 公共安全投影 ─────────────────────────────────


def test_a_monthly_progress_public_safe_projection(game):
    db, state, _content = game
    _order_id, dossier_id, secret_title, memorial = _long_secret(db, state)

    payload = build_simulator_payload(state, db, "着核边饷", "")
    dumped = json.dumps(payload, ensure_ascii=False)

    assert "monthly_progress" in payload
    assert memorial not in dumped
    assert secret_title not in dumped
    assert "memorial_text" not in dumped

    hit = next(
        item for item in payload["monthly_progress"]
        if int(item["dossier_id"]) == dossier_id
    )
    assert set(hit) <= {"dossier_id", "turn", "progress_band", "title_summary"}
    assert set(hit) >= {"dossier_id", "turn", "progress_band"}
    assert int(hit["turn"]) == state.turn
    assert hit["progress_band"] == "在途核验"
    assert "memorial_text" not in hit


def test_a_personnel_secret_rail_and_secret_order_exclusion_unchanged(game):
    db, state, _content = game
    _order_id, dossier_id, secret_title, memorial = _long_secret(db, state)

    private = build_extractor_shared_context(
        db, state, "邸报", "", module="personnel_secret",
    )
    assert any(
        int(item["dossier_id"]) == dossier_id
        for item in private["monthly_dossier_reports"]
    )
    private_dump = json.dumps(private, ensure_ascii=False)
    assert memorial in private_dump or any(
        any(
            str(p.get("memorial_text") or "") == memorial
            for p in (item.get("progress") or [])
        )
        for item in private["monthly_dossier_reports"]
    )

    public_ids = {
        int(row["id"]) for row in db.list_decree_dossiers_for_simulation(state.turn)
    }
    assert dossier_id not in public_ids
    assert all(
        row.get("action_type") != "secret_order"
        for row in db.list_decree_dossiers_for_simulation(state.turn)
    )


# ── B. 结构化案卷投影契约 ───────────────────────────────────────────


def test_b_narrative_and_execution_projection_keysets(game):
    db, state, content = game
    older = db.create_decree_dossier(
        state, action_type="policy", decree_text="旧案清丈",
        target_kind="issue", target_id="survey",
    )
    narrative_id = db.create_decree_dossier(
        state, action_type="special_decree", decree_text="着核边饷",
        target_kind="issue", target_id="frontier-pay",
        payload={"mode": "ordinary"},
    )
    db.add_dossier_links(
        narrative_id,
        [{"target_dossier_id": older, "relation_type": "接应", "note": "续核边饷"}],
    )
    db.apply_dossier_verdicts(
        state, [{"dossier_id": narrative_id, "decision": "promulgated"}],
        content=content,
    )

    actor = _active_minister(db)
    exec_id = db.create_decree_dossier(
        state, action_type="grant_allocation",
        decree_text="发内帑银十万两济辽",
        target_kind="army", target_id="guanning",
        executor_kind="character", executor_id=actor,
        payload={"amount": 10, "account": "内库", "execution_surface": "in_transit"},
    )
    db.apply_dossier_verdicts(
        state, [{"dossier_id": exec_id, "decision": "promulgated"}],
        content=content,
    )

    visible = []
    for row in db.list_decree_dossiers_for_simulation(state.turn):
        item = dict(row)
        if int(item["id"]) in {narrative_id, exec_id}:
            item["settlement_verdict"] = "promulgated"
        visible.append(item)
    projected = project_dossiers_for_simulator(visible, db=db, state=state)
    by_id = {int(row["id"]): row for row in projected}

    narr = by_id[narrative_id]
    assert set(narr) == SIM_DOSSIER_NARRATIVE_KEYS
    assert narr["decree_text"] == "着核边饷"
    assert narr["decision"] == "顺颁"
    assert isinstance(narr["links"], list) and narr["links"]
    assert "payload_json" not in narr and "stigma_json" not in narr
    assert "payload" not in narr

    exe = by_id[exec_id]
    assert set(exe) == SIM_DOSSIER_EXECUTION_KEYS
    assert "decree_text" not in exe
    assert "execution_summary" in exe
    assert "payload_json" not in exe and "stigma_json" not in exe
    dumped = json.dumps(projected, ensure_ascii=False)
    assert "payload_json" not in dumped
    assert "stigma_json" not in dumped


# ── C. decree_text 权威降级（字段保留；extractor 零改） ──────────────


def test_c_decree_text_retained_and_extractor_surface_untouched(game):
    db, state, _content = game
    payload = build_simulator_payload(state, db, "着户部核辽饷", "")
    assert payload.get("decree_text") == "着户部核辽饷"
    assert payload["decree_text"]

    src = (_REPO / "ming_sim" / "simulation.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "build_extractor_shared_context"
    )
    # extractor 仍按既有 slim 字段投影，不吃 simulator 全量案卷键
    body = ast.get_source_segment(src, fn) or ""
    assert 'origin_ref' in body
    assert "monthly_progress" not in body

    prompt_dir = _REPO / "content" / "prompts"
    for name in (
        "score_extractor_shared.md",
        "score_extractor_issues.md",
        "score_extractor_personnel_secret.md",
        "score_extractor_military_external.md",
        "score_extractor_economy_internal.md",
    ):
        path = prompt_dir / name
        if path.exists():
            # 本片不得改 extractor prompt：以 git 为证在 test 外；此处只钉仍存在
            assert path.read_text(encoding="utf-8").strip()


# ── D. 对账输入位 ───────────────────────────────────────────────────


def test_d_reconciliation_inputs_default_serializable(game):
    db, state, _content = game
    payload = build_simulator_payload(state, db, "", "")
    assert "reconciliation_inputs" in payload
    assert payload["reconciliation_inputs"] in ([], None)
    json.dumps(payload, ensure_ascii=False)


# ── E. 认账 brief 定性中文 ───────────────────────────────────────────


def test_e_audience_brief_uses_qualitative_chinese_for_rejected(game, monkeypatch):
    from ming_sim.session import GameSession
    from ming_sim.models import Character

    db, state, _content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="special_decree", decree_text="着破格授阁臣",
        target_kind="character", target_id=_active_minister(db),
        payload={"mode": "midzhi"},
    )
    db.apply_dossier_verdicts(state, [_rejected_verdict(dossier_id, midzhi=True)])
    db.apply_dossier_promulgation(state, dossier_id, "force_promulgated")

    candidates = db.list_referenceable_dossiers("孙承宗", state.turn)
    assert dossier_id in {int(row["id"]) for row in candidates}
    brief = render_referenceable_dossier_brief(candidates)
    assert "打回" in brief or "强颁" in brief
    assert _ENGLISH_LEAK.search(brief) is None

    # 生产接缝：session 组装走同一 brief 渲染，不得裸奔英文枚举
    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    minister = Character(
        name="孙承宗", office="兵部尚书", office_type="兵部",
        faction="东林", aliases=[], personal_skills=[],
        loyalty=50, ability=50, integrity=50, courage=50,
        style="", status="active", power_id="ming",
    )
    monkeypatch.setattr(
        "ming_sim.session.render_character_knowledge", lambda *a, **k: "",
    )
    monkeypatch.setattr(
        session.db, "get_character_knowledge",
        lambda *a, **k: {"events": [], "facts": []},
    )
    prompt = GameSession._audience_prompt_for_message(
        session, "卿以为前旨如何？", minister,
    )
    assert _ENGLISH_LEAK.search(prompt) is None
    assert "打回" in prompt or "强颁" in prompt
    assert "可参考既有旨意" in prompt


# ── F. prompt 改域 + 判决无关章节零改 ────────────────────────────────


def test_f_season_simulator_whitelist_and_untouched_chapters():
    text = _SEASON_SIM.read_text(encoding="utf-8")
    headings = re.findall(r"^### .+$", text, re.M)
    assert "### 军事（有军务盘面动作才写）" in headings
    assert "### 探子回报" in headings
    # 权威改为案卷列表
    assert "decree_dossiers" in text
    assert "照账演" in text
    assert "monthly_progress" in text or "月度进展" in text
    assert "reconciliation_inputs" in text or "对账" in text
    assert "打回" in text and ("不得写成已办成" in text or "禁写成办成" in text or "严禁写成" in text)

    military = re.search(r"### 军事（有军务盘面动作才写）.+?(?=\n### |\Z)", text, re.S)
    assert military is not None
    # 军事章不得被本片改写成照账演/案卷输入
    assert "照账演" not in military.group(0)
    assert "decree_dossiers" not in military.group(0)
    assert "monthly_progress" not in military.group(0)


# ── G. judge-in-loop 确定性前置 ──────────────────────────────────────


def test_g_midzhi_stigma_projected_and_prompt_has_ledger_play(game):
    db, state, _content = game
    actor = _active_minister(db)
    # 任免案卷 + 中旨 stigma；本片只读投影，不经任免物化写口（H）。
    dossier_id = db.create_decree_dossier(
        state, action_type="appointment",
        decree_text=f"着以{actor}为礼部尚书",
        target_kind="character", target_id=actor,
        executor_kind="character", executor_id=actor,
        payload={
            "mode": "midzhi",
            "name": actor,
            "office": "礼部尚书",
            "office_type": "礼部",
            "_minister_name": actor,
            "_office_action": "任命",
        },
    )
    db._append_midzhi_stigma(
        dossier_id, decision="promulgated", turn=state.turn,
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing', "
        "promulgation_decision='promulgated' WHERE id=?",
        (dossier_id,),
    )
    db.conn.commit()
    row = db.get_decree_dossier(dossier_id)
    assert any(
        isinstance(item, dict) and item.get("kind") == "midzhi"
        for item in (row.get("stigma") or [])
    )

    visible = [dict(r) for r in db.list_decree_dossiers_for_simulation(state.turn)]
    projected = project_dossiers_for_simulator(visible, db=db, state=state)
    hit = next(r for r in projected if int(r["id"]) == dossier_id)
    assert any(
        isinstance(item, dict) and item.get("kind") == "midzhi"
        for item in (hit.get("stigma") or [])
    )
    prompt = _SEASON_SIM.read_text(encoding="utf-8")
    assert "照账演" in prompt
    assert "传奉" in prompt or "辞让" in prompt or "科参" in prompt


# ── H. 只读守门（本片测试不写 execution_outcome / stigma） ───────────


def test_h_projection_is_read_only(game):
    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="着清丈",
        target_kind="issue", target_id="survey",
    )
    before = db.get_decree_dossier(dossier_id)
    visible = [dict(row) for row in db.list_decree_dossiers_for_simulation(state.turn)]
    project_dossiers_for_simulator(visible, db=db, state=state)
    build_simulator_payload(state, db, "着清丈", "")
    after = db.get_decree_dossier(dossier_id)
    assert after["execution_outcome"] == before["execution_outcome"]
    assert after["stigma"] == before["stigma"]
    assert after["status"] == before["status"]
