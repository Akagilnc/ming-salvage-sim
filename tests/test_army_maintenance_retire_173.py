"""#173 PR2 写端脱钩：extractor 写端从退役的 maintenance_per_turn 切到不依赖。

月饷已由 army_needed(派生自 salary_rate + 兵力)唯一承载（#44）；maintenance_per_turn 退役为
死列（不再驱动扣费/显示）。PR2 让 extractor：
  ① 建军不再必填维护费（缺省 0，月饷靠兵力派生）；
  ② 改维护费 = 拒收留痕（替原 silent no-op，避免 LLM 以为改了月饷其实没改）。
列本身留到「删 maintenance」PR 物理移除，本切片只断写端依赖。
"""

import pytest


def _maint(db, aid):
    return db.conn.execute(
        "SELECT maintenance_per_turn FROM armies WHERE id=?", (aid,)
    ).fetchone()["maintenance_per_turn"]


def _pseudo(title="测试"):
    return type("E", (), {"id": "test", "title": title})()


# ── 建军：维护费不再必填 ────────────────────────────────────────────────

def test_new_army_without_maintenance_succeeds(game):
    # 建军只给 manpower、不给 maintenance_per_turn → 应建成功（月饷靠 army_needed 派生），
    # 不再因「缺维护费」被拒。PR2 前：必填维护费，此项被 invalid_enum 拒。
    db, state, _ = game
    created = db.create_armies_from_extraction(state, [{
        "id": "qin_army_pr2", "name": "秦军新营", "owner_power": "ming",
        "manpower": 8000,
    }])
    assert len(created) == 1
    assert not created[0].get("rejected"), f"建军不应被拒：{created[0]}"
    row = db.conn.execute(
        "SELECT id FROM armies WHERE id='qin_army_pr2'").fetchone()
    assert row is not None, "缺维护费的新军应已入库"


def test_new_army_without_maintenance_defaults_zero(game):
    # 缺维护费 → maintenance 列缺省 0（列尚在、NOT NULL，本切片不删列）。
    db, state, _ = game
    db.create_armies_from_extraction(state, [{
        "id": "qin_army_pr2b", "name": "秦军乙营", "owner_power": "ming",
        "manpower": 5000,
    }])
    assert _maint(db, "qin_army_pr2b") == 0


def test_new_army_still_requires_manpower(game):
    # 回归：维护费不再必填，但 manpower 仍必填（缺 → 拒）。
    db, state, _ = game
    created = db.create_armies_from_extraction(state, [{
        "id": "qin_army_pr2c", "name": "无兵营", "owner_power": "ming",
        "maintenance_per_turn": 2,
    }])
    assert created[0].get("rejected"), "缺 manpower 仍应拒建军"
    assert db.conn.execute(
        "SELECT id FROM armies WHERE id='qin_army_pr2c'").fetchone() is None


def test_new_army_pay_derives_from_manpower_not_maintenance(game):
    # 即便 LLM 仍塞了 maintenance，月饷只认 army_needed（salary_rate×兵力），维护费不参与扣费。
    # 用「同兵力、维护费悬殊两军 army_needed 相等」断言，不耦合具体 salary_rate 锚点值（Sourcery R1）。
    from ming_sim.flows import army_needed
    db, state, _ = game
    db.create_armies_from_extraction(state, [
        {"id": "qin_pr2d_lo", "name": "秦军丁营低维护", "owner_power": "ming",
         "manpower": 10000, "maintenance_per_turn": 1},
        {"id": "qin_pr2d_hi", "name": "秦军丁营高维护", "owner_power": "ming",
         "manpower": 10000, "maintenance_per_turn": 999},
    ])
    row_lo = db.conn.execute("SELECT * FROM armies WHERE id='qin_pr2d_lo'").fetchone()
    row_hi = db.conn.execute("SELECT * FROM armies WHERE id='qin_pr2d_hi'").fetchone()
    # 月饷完全由兵力 + salary_rate 派生，与 maintenance_per_turn 无关 → 同兵力两军同饷。
    assert army_needed(row_lo) == army_needed(row_hi)


# ── 改军：维护费 pay-change 拒收 ────────────────────────────────────────

@pytest.mark.parametrize("field_key", ["维护费", "maintenance_per_turn", "军费"])
def test_army_delta_rejects_maintenance_paychange(game, field_key):
    # 改维护费 → 拒收留痕（替 silent no-op）。PR2 前：silent 落库改死列、LLM 误以为改了月饷。
    db, state, _ = game
    aid = str(db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"])
    before_maint = _maint(db, aid)
    before_logs = db.conn.execute(
        "SELECT COUNT(*) FROM army_logs WHERE army_id=? AND field='maintenance_per_turn'",
        (aid,)).fetchone()[0]
    changes = db.apply_army_deltas(
        state, _pseudo("加饷"), None, "户部", {aid: {field_key: 5, "reason": "诏加饷"}})
    rejected = [c for c in changes if c.get("rejected")]
    assert rejected, f"改维护费应拒收留痕，实得 changes={changes}"
    assert _maint(db, aid) == before_maint, "维护费 pay-change 不应落库改死列"
    after_logs = db.conn.execute(
        "SELECT COUNT(*) FROM army_logs WHERE army_id=? AND field='maintenance_per_turn'",
        (aid,)).fetchone()[0]
    assert after_logs == before_logs, "拒收的维护费 pay-change 不应留 army_log"


def test_army_delta_other_fields_still_apply(game):
    # 回归：拒维护费不误伤同信封其它合法字段（士气照落）；且混合信封里维护费 reject 项须被
    # 记录(rejected/invalid_enum)——锁 reject-and-record 契约的两面(cmr R2 codex low)。
    db, state, _ = game
    aid = str(db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"])
    before = db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (aid,)).fetchone()["morale"]
    changes = db.apply_army_deltas(
        state, _pseudo("整饬"), None, "兵部",
        {aid: {"维护费": 5, "士气": -3, "reason": "整饬"}})
    after = db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (aid,)).fetchone()["morale"]
    assert after == before - 3, "拒维护费不应连累同军合法字段（士气）落库"
    rejected = [c for c in changes if c.get("rejected") and c.get("field") == "维护费"]
    assert rejected and rejected[0]["category"] == "invalid_enum", \
        "混合信封里维护费 reject 项须被记录(invalid_enum),不静默吞"


# ── cmr R1 P2(codex R2)：维护费拒收保留 issue 路脏值历史严格度 ──────────

def test_maintenance_dirty_string_stays_strict_on_issue_path(game):
    # 维护费退役、一律拒收，但 issue 结案路对脏值的历史严格度须保留：原 maintenance 落库
    # 分支在数值脏值校验之后，故非数字串/None 历史走严格 invalid-value（issue_strict=True →
    # 结案路 raise）。前置拒收若硬 issue_strict=False 会把脏串维护费从严格降级为容忍（回归）。
    import ming_sim.issues as I
    db, state, _ = game
    aid = str(db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"])
    # 非数字串维护费 → issue 路严格 raise（与 morale=None/串 同治，对称）
    with pytest.raises(ValueError):
        I._apply_issue_entities(
            db, state, {"army_delta": {aid: {"维护费": "五万"}}}, "局势#测试结案")
    # None 维护费 → 同样严格 raise
    with pytest.raises(ValueError):
        I._apply_issue_entities(
            db, state, {"army_delta": {aid: {"维护费": None}}}, "局势#测试结案")


def test_maintenance_numeric_paychange_tolerated_on_issue_path(game):
    # 合法 int / float 维护费 → 退役拒收但容忍（历史会静默落库/套用，不升级崩结案路）。
    import ming_sim.issues as I
    db, state, _ = game
    aid = str(db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"])
    I._apply_issue_entities(
        db, state, {"army_delta": {aid: {"维护费": 5}}}, "局势#测试结案")     # int → 不抛
    I._apply_issue_entities(
        db, state, {"army_delta": {aid: {"维护费": 3.7}}}, "局势#测试结案")   # float → 不抛


# ── cmr R1 P3(Claude f2)：建军维护费脏值兜底分支覆盖 ──────────────────

@pytest.mark.parametrize(
    "dirty,tag", [(-5, "neg"), (3.7, "flt"), (True, "bool"), ("两万", "str"), (None, "none")])
def test_new_army_dirty_maintenance_tolerated_defaults_zero(game, dirty, tag):
    # 建军维护费脏值（负 int/float/bool/串/None）→ 不拒整军、兜底 0（死列值无意义，月饷不看它）。
    # 负 int 显式锁「只认非负 int」契约（Sourcery R1）。
    db, state, _ = game
    aid = f"qin_pr2_dirty_{tag}"
    created = db.create_armies_from_extraction(state, [{
        "id": aid, "name": "脏饷营", "owner_power": "ming",
        "manpower": 5000, "maintenance_per_turn": dirty,
    }])
    assert not created[0].get("rejected"), f"脏维护费不应拒整军：{created[0]}"
    assert _maint(db, aid) == 0, "脏维护费应兜底 0"


# ── cmr R1 P1(Claude f1 + codex R1)：所有 extractor 写端教学面停教军队维护费 ──

def test_extractor_write_prompts_no_longer_teach_army_maintenance():
    # 3 处 extractor 写端教学面——2 个 .md + cli_backend.enrich_initiative_effects（国策建军
    # 效果的结构化产出 prompt）——不得再教 LLM 给 new_armies 填 maintenance_per_turn（维护费退役、
    # 月饷由兵力 army_needed 派生）。防回归：cli_backend 这第三处曾被漏改（cmr R1 跨厂 concur 抓出）。
    # 建筑维护费在 score_extractor_issues.md，是不同字段，不在此查。
    import inspect
    from pathlib import Path
    import ming_sim.cli_backend as cb
    base = Path(__file__).resolve().parent.parent / "content" / "prompts"
    for fname in ("score_extractor_military_external.md", "score_extractor_shared.md"):
        txt = (base / fname).read_text(encoding="utf-8")
        assert "maintenance_per_turn" not in txt, f"{fname} 仍含 maintenance_per_turn 写端教学"
    src = inspect.getsource(cb.enrich_initiative_effects)
    assert "maintenance_per_turn" not in src, "enrich_initiative_effects 仍教 maintenance_per_turn"


# ── 线上 R2(CodeRabbit Major)：int(float('inf')) 抛 OverflowError 不得崩结算咽喉 ──

def test_maintenance_inf_paychange_no_crash_on_issue_path(game):
    # int(float("inf")) 抛 OverflowError，不在 (TypeError,ValueError) 捕获内 → 维护费=inf 改军
    # 会崩 issue 结案路。须捕 OverflowError、按 float 类容忍（对齐 _coerce_new_salary_rate 的
    # 非有限值不 fail-loud 设计：结算咽喉为一个脏字段抛错会崩整月）。
    import ming_sim.issues as I
    db, state, _ = game
    aid = str(db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"])
    for v in (float("inf"), float("-inf")):
        I._apply_issue_entities(
            db, state, {"army_delta": {aid: {"维护费": v}}}, "局势#测试结案")  # 不崩(容忍)


def test_new_army_inf_manpower_rejected_not_crash(game):
    # _new_army_historically_applied 的 int(manpower) 对 inf 抛 OverflowError 漏网会崩建军;
    # inf manpower 应逐项拒收留痕、不崩(谓词捕 OverflowError → 历史致命=严格)。
    db, state, _ = game
    created = db.create_armies_from_extraction(state, [{
        "id": "inf_army", "name": "无穷营", "owner_power": "ming", "manpower": float("inf"),
    }])
    assert created[0].get("rejected"), "inf manpower 应拒建军"
    assert db.conn.execute(
        "SELECT id FROM armies WHERE id='inf_army'").fetchone() is None
