"""Probe a maxed Guanning northern expedition to recover Liaodong/Jianzhou."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ming_sim.content import GameContent
from ming_sim.context import victory_status
from ming_sim.llm_config import load_llm_config
from ming_sim.session import GameSession


DECREES = [
    (
        "turn1_max_guanning",
        "奉天承运皇帝诏曰：倾内帑与太仓优先整饬辽东，关宁军 / 宁锦防线欠饷全清，"
        "补给、士气、训练、装备、忠诚皆拉满至九十五以上，兵额补至八万，月维护费增至二十万两，"
        "驻地仍辽东 / 宁远锦州，统帅孙承宗，状态改为饷足粮丰、火器齐备、可主动北伐。"
        "山海关守军与东江镇协同策应，登莱水师保障海运粮道。军事章必须写清关宁军补给、士气、"
        "训练、装备均超过满洲八旗主力。钦此。",
    ),
    (
        "turn2_recover_liaoshen",
        "奉天承运皇帝诏曰：关宁军 / 宁锦防线以优势火器和充足粮饷出宁锦，山海关守军护后路，"
        "东江镇牵制辽南，登莱水师转运粮械，合攻沈阳 / 辽阳。满洲八旗主力败退，驻地改回建州 / 赫图阿拉，"
        "状态改为辽沈战败、退守建州。沈阳 / 辽阳控制改为大明，辽东 / 宁锦军事压力大降，"
        "关宁军驻地改为辽东 / 沈阳辽阳一线，状态改为收复辽沈、整补待进。后金实力、经济、威望大降。"
        "军事章写军队调度和八旗退回建州；地方章写沈阳 / 辽阳控制改为明。钦此。",
    ),
    (
        "turn3_recover_jianzhou",
        "奉天承运皇帝诏曰：辽沈既复，关宁军 / 宁锦防线会同山海关守军、东江镇、登莱水师，"
        "分三路进逼建州 / 赫图阿拉。满洲八旗主力再败，人数减三万，补给、士气、训练、装备、忠诚大降，"
        "状态改为主力溃散、贝勒内讧、余部北遁。建州 / 赫图阿拉控制改为大明，沈阳 / 辽阳仍归大明，"
        "关宁军驻地改为建州 / 赫图阿拉，状态改为收复建州、辽东威胁解除。后金实力、经济、威望降至低位。"
        "地方章必须写建州 / 赫图阿拉控制改为明；军事章必须写满洲八旗主力战败溃散。钦此。",
    ),
]


def _env_from_dotenv() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    for src, dst in (
        ("CLI_API_KEY", "OPENAI_API_KEY"),
        ("CLI_BASE_URL", "OPENAI_BASE_URL"),
        ("CLI_MODEL", "OPENAI_MODEL"),
    ):
        if os.environ.get(src) and not os.environ.get(dst):
            os.environ[dst] = os.environ[src]


def _query_snapshot(sess: GameSession) -> dict[str, object]:
    db = sess.db
    regions = [
        dict(r)
        for r in db.conn.execute(
            """
            SELECT id,name,controlled_by,military_pressure,public_support,unrest,status
            FROM regions
            WHERE id IN ('liaodong','shenyang_liaoyang','jianzhou','dongjiang_area')
            ORDER BY id
            """
        ).fetchall()
    ]
    armies = [
        dict(r)
        for r in db.conn.execute(
            """
            SELECT id,name,owner_power,station,commander,troop_type,
                   manpower,maintenance_per_turn,supply,morale,training,equipment,
                   arrears,mobility,loyalty,status
            FROM armies
            WHERE id IN ('guanning','manchu_banners_main','shanhaiguan','dongjiang','denglai')
            ORDER BY id
            """
        ).fetchall()
    ]
    powers = [
        dict(r)
        for r in db.conn.execute(
            """
            SELECT id,name,leader,leverage,military_strength,cohesion,supply,status,last_action
            FROM powers
            WHERE id IN ('houjin','manchu_banners','han_banners','korea','mongol')
            ORDER BY id
            """
        ).fetchall()
    ]
    region_logs = [
        dict(r)
        for r in db.conn.execute(
            """
            SELECT turn,year,period,region_id,field,old_value,new_value,delta,reason
            FROM region_logs
            WHERE region_id IN ('liaodong','shenyang_liaoyang','jianzhou')
            ORDER BY id
            """
        ).fetchall()
    ]
    army_logs = [
        dict(r)
        for r in db.conn.execute(
            """
            SELECT turn,year,period,army_id,field,old_value,new_value,delta,reason
            FROM army_logs
            WHERE army_id IN ('guanning','manchu_banners_main','shanhaiguan','dongjiang','denglai')
            ORDER BY id
            """
        ).fetchall()
    ]
    extractions = [
        dict(r)
        for r in db.conn.execute(
            """
            SELECT turn,year,period,substr(extractor_output,1,3000) AS extractor_output
            FROM turn_extractions
            ORDER BY turn
            """
        ).fetchall()
    ]
    return {
        "regions": regions,
        "armies": armies,
        "powers": powers,
        "region_logs": region_logs,
        "army_logs": army_logs,
        "extractions": extractions,
        "victory_status": victory_status(db, sess.state),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/guanning_northern_expedition_probe.db")
    parser.add_argument("--start-ym", default="1632.01")
    parser.add_argument("--out", default="scripts/runs/guanning_northern_expedition_probe_result.json")
    args = parser.parse_args()

    _env_from_dotenv()
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY missing")

    db_path = ROOT / args.db
    for suffix in ("", "_agno.db", "_agno.db.emperor.db"):
        path = Path(str(db_path).removesuffix(".db") + suffix) if suffix else db_path
        if path.exists():
            path.unlink()

    content = GameContent.load()
    llm = load_llm_config(
        os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    )
    sess = GameSession(str(db_path), llm, content=content, verify_llm=True, start_ym=args.start_ym)
    results: list[dict[str, object]] = []
    try:
        for label, decree in DECREES:
            sess.begin_turn()
            sess.add_directive(decree, notes=label)
            print(f"[probe] resolving {label} at {sess.state.year}.{sess.state.period} turn={sess.state.turn}", flush=True)
            report = sess.resolve_turn(decree=decree)
            results.append({
                "label": label,
                "decree": decree,
                "report_head": report[:1800],
                "snapshot": _query_snapshot(sess),
            })
            sess.end_turn()
        final = _query_snapshot(sess)
    finally:
        sess.close()

    output = {"db": str(db_path), "start_ym": args.start_ym, "turns": results, "final": final}
    text = json.dumps(output, ensure_ascii=False, indent=2)
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"[probe] wrote {out_path}")
    print(text[:5000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
