"""#173：物理移除退役的 armies.maintenance_per_turn 列。月饷由 army_needed(按兵力派生)唯一承载。

本文件验删列后的契约——维护费彻底不再是字段：
  · schema 无该列；
  · 建军唯一必填=manpower（维护费键给了也当未知键忽略；inf 等极值不崩建军）；
  · army_delta 写维护费/军费 → 别名已删 → 当非法字段逐项拒收（同信封合法字段照落）；
  · 月饷纯由兵力派生（army_needed），与已删的维护费无关；
  · extractor 写端 prompt 不再教军队维护费。
（PR2「写端脱钩」时维护费列尚在的脏值/严格度语义已随列删除一并退场。）
"""

import inspect
from pathlib import Path

import pytest

from ming_sim.flows import army_needed


def _pseudo(title="测试"):
    return type("E", (), {"id": "test", "title": title})()


def _pay_source():
    return {
        "pay_source_region": "shaanxi",
        "province_pay_share": 1.0,
        "central_pay_share": 0.0,
    }


def _disable_army_pay_source_cutover(db):
    db.conn.execute(
        """
        INSERT INTO fiscal_config (key, value, kind, note)
        VALUES ('__army_pay_source_cutover', 0, 'meta', 'legacy new-army test')
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, note = excluded.note
        """
    )
    db.conn.commit()


# ── schema：列已物理删除 ──────────────────────────────────────────────

def test_armies_table_has_no_maintenance_column(read_game):
    db, _state, _ = read_game
    cols = {r["name"] for r in db.conn.execute("PRAGMA table_info(armies)").fetchall()}
    assert "maintenance_per_turn" not in cols, "维护费列应已物理删除"


def test_drop_maintenance_column_removes_and_idempotent(game):
    # 老档迁移路径：模拟列仍在的旧档 → _drop_maintenance_column 物理移除；再调一次幂等不崩。
    db, _state, _ = game
    db.conn.execute("ALTER TABLE armies ADD COLUMN maintenance_per_turn INTEGER NOT NULL DEFAULT 0")
    db.conn.commit()
    assert "maintenance_per_turn" in {
        r["name"] for r in db.conn.execute("PRAGMA table_info(armies)").fetchall()}, "前提：列已加回"
    db._drop_maintenance_column()
    assert "maintenance_per_turn" not in {
        r["name"] for r in db.conn.execute("PRAGMA table_info(armies)").fetchall()}, "drop 后列应消失"
    db._drop_maintenance_column()  # 幂等：列已无 → no-op 不崩


def test_existing_save_drops_maintenance_column_on_open(content, tmp_path):
    # cmr drop R1(codex high)：driver 开现存档只走 GameDB.__init__→init_schema、不走 seed_static_data。
    # 维护费退役 drop 须挂 init_schema，否则现存档（maintenance NOT NULL 无 default）不删列 → 删列后
    # 建新军 INSERT（已不含该列）崩。模拟「升级前老档」：seed 后 ADD 回 maintenance 列，重开同档（纯
    # init_schema 路径）应 drop 该列、且其后建新军不崩。
    from ming_sim.db import GameDB
    path = str(tmp_path / "old_save.db")
    db = GameDB(path, content)
    db.seed_static_data()
    db.conn.execute("ALTER TABLE armies ADD COLUMN maintenance_per_turn INTEGER NOT NULL DEFAULT 5")
    db.conn.commit()
    db.close()
    # 重开：GameDB.__init__ → init_schema 的维护费退役迁移应 drop（不调 seed_static_data）。
    db2 = GameDB(path, content)
    try:
        cols = {r["name"] for r in db2.conn.execute("PRAGMA table_info(armies)").fetchall()}
        assert "maintenance_per_turn" not in cols, "现存档重开应在 init_schema 路径 drop 维护费列"
        state2 = db2.load_state()
        created = db2.create_armies_from_extraction(state2, [{
            "id": "post_drop_army", "name": "迁移后新军", "owner_power": "ming",
            "manpower": 5000, **_pay_source(),
        }])
        assert not created[0].get("rejected"), f"drop 后建新军 INSERT 应成功不崩：{created[0]}"
        assert db2.conn.execute("SELECT id FROM armies WHERE id='post_drop_army'").fetchone() is not None
    finally:
        db2.close()


# ── 建军：manpower 唯一必填，维护费不再是字段 ──────────────────────────

def test_legacy_new_army_needs_only_manpower(game):
    db, state, _ = game
    _disable_army_pay_source_cutover(db)
    created = db.create_armies_from_extraction(state, [{
        "id": "qin_army_x", "name": "秦军营", "owner_power": "ming", "manpower": 8000,
    }])
    assert not created[0].get("rejected"), f"只给 manpower 应建军成功：{created[0]}"
    assert db.conn.execute("SELECT id FROM armies WHERE id='qin_army_x'").fetchone() is not None


def test_new_army_maintenance_key_ignored(game):
    # LLM 若仍塞维护费/军费（别名已删）→ 当未知键忽略，不入库、不报错、建军照成。
    db, state, _ = game
    created = db.create_armies_from_extraction(state, [{
        "id": "qin_army_y", "name": "秦军乙", "owner_power": "ming",
        "manpower": 5000, "maintenance_per_turn": 99, "维护费": 99, **_pay_source(),
    }])
    assert not created[0].get("rejected"), f"塞维护费键不应拒整军：{created[0]}"
    assert db.conn.execute("SELECT id FROM armies WHERE id='qin_army_y'").fetchone() is not None


def test_new_army_still_requires_manpower(game):
    db, state, _ = game
    created = db.create_armies_from_extraction(state, [{
        "id": "qin_army_z", "name": "无兵营", "owner_power": "ming",
    }])
    assert created[0].get("rejected"), "缺 manpower 应拒建军"
    assert db.conn.execute("SELECT id FROM armies WHERE id='qin_army_z'").fetchone() is None


def test_new_army_inf_manpower_rejected_not_crash(game):
    # int(float("inf")) 抛 OverflowError（不在 (TypeError,ValueError) 内）→ _new_army_historically_applied
    # 须捕，否则崩建军。inf manpower 应逐项拒收留痕、不崩。
    db, state, _ = game
    created = db.create_armies_from_extraction(state, [{
        "id": "inf_army", "name": "无穷营", "owner_power": "ming", "manpower": float("inf"),
    }])
    assert created[0].get("rejected"), "inf manpower 应拒建军"
    assert db.conn.execute("SELECT id FROM armies WHERE id='inf_army'").fetchone() is None


# ── 月饷纯由兵力派生，与已删的维护费无关 ──────────────────────────────

def test_pay_derives_from_manpower(game):
    # 两军缺省 salary_rate 落同一锚点，兵力多者 army_needed 严格更大 → 月饷由兵力派生（非维护费）。
    db, state, _ = game
    db.create_armies_from_extraction(state, [
        {"id": "pay_lo", "name": "少兵营", "owner_power": "ming", "manpower": 10000, **_pay_source()},
        {"id": "pay_hi", "name": "多兵营", "owner_power": "ming", "manpower": 40000, **_pay_source()},
    ])
    lo = db.conn.execute("SELECT * FROM armies WHERE id='pay_lo'").fetchone()
    hi = db.conn.execute("SELECT * FROM armies WHERE id='pay_hi'").fetchone()
    assert army_needed(hi) > army_needed(lo) > 0, "兵力多者月饷应更大（月饷随兵力派生）"


# ── army_delta 写维护费 → 非法字段拒收（别名已删） ────────────────────

@pytest.mark.parametrize("field_key", ["维护费", "maintenance_per_turn", "军费"])
def test_army_delta_maintenance_rejected_as_invalid_field(game, field_key):
    # 维护费别名已删 → 写它不再规范化成已删列，当非法字段逐项拒收留痕（invalid_enum）。
    db, state, _ = game
    aid = str(db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"])
    changes = db.apply_army_deltas(
        state, _pseudo("加饷"), None, "户部", {aid: {field_key: 5, "reason": "诏加饷"}})
    rejected = [c for c in changes if c.get("rejected")]
    assert rejected and rejected[0]["category"] == "invalid_enum", \
        f"写维护费应作非法字段拒收(invalid_enum)：{changes}"


def test_army_delta_other_fields_still_apply(game):
    # 拒维护费不误伤同信封其它合法字段（士气照落）。
    db, state, _ = game
    aid = str(db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"])
    before = db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (aid,)).fetchone()["morale"]
    db.apply_army_deltas(
        state, _pseudo("整饬"), None, "兵部", {aid: {"维护费": 5, "士气": -3, "reason": "整饬"}})
    after = db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (aid,)).fetchone()["morale"]
    assert after == before - 3, "拒维护费不应连累同军合法字段（士气）落库"


# ── extractor 写端 prompt 不教军队维护费 ─────────────────────────────

def test_extractor_write_prompts_no_longer_teach_army_maintenance():
    # 维护费已删列——所有喂给 LLM 的写端教学面不得再教军队维护费/军费：
    #   · 2 个 score_extractor .md + cli_backend.enrich_initiative_effects；
    #   · game_world.md（喂给 simulator/extractor/decree/chapter/ending 每个 agent，cmr drop R1 f1）；
    #   · tools army_delta docstring 的合法字段列表（runtime extractor 工具面，cmr drop R2/f2）。
    # 建筑维护费在 score_extractor_issues.md，是不同字段，不在此查。
    import ming_sim.cli_backend as cb
    import ming_sim.tools as tools_mod
    base = Path(__file__).resolve().parent.parent / "content" / "prompts"
    for fname in ("score_extractor_military_external.md", "score_extractor_shared.md", "game_world.md"):
        txt = (base / fname).read_text(encoding="utf-8")
        assert "maintenance_per_turn" not in txt, f"{fname} 仍含 maintenance_per_turn 写端教学"
    assert "maintenance_per_turn" not in inspect.getsource(cb.enrich_initiative_effects)
    # tools 的 army_delta 合法字段 docstring（build_extractor_tools.submit_extraction）不得列任何维护费
    # 类字段。narrow 到该函数 source、不扫整 module（避免未来无关提及误失败，Sourcery PR R1）；查全部
    # 维护费类别名/字段而非仅 maintenance_quarter（CodeRabbit PR R2：防 maintenance_per_turn/中文别名回流）。
    tools_src = inspect.getsource(tools_mod.build_extractor_tools)
    for legacy in ("maintenance_quarter", "maintenance_per_turn", "维护费", "军费"):
        assert legacy not in tools_src, \
            f"build_extractor_tools 的 army_delta docstring 仍把维护费类字段 '{legacy}' 列为合法军队字段"
