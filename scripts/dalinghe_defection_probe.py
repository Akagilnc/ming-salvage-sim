"""Probe Zu Dashou's Dalinghe defection to Later Jin.

Runs two fixed turns from the month before the event window:
1. Guanning / Zu Dashou's troops move into Dalinghe and are besieged.
2. Zu Dashou defects to Later Jin; his surrendered troops change owner.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ming_sim.content import GameContent
from ming_sim.llm_config import load_llm_config
from ming_sim.session import GameSession


DECREES = [
    (
        "turn1_dalinghe_besieged",
        "奉天承运皇帝诏曰：辽东大凌河筑城急迫，着祖大寿率关宁军 / 宁锦防线中精锐二万人移驻"
        "辽东 / 大凌河城，协守未成城垣。关宁军 / 宁锦防线驻地改为辽东 / 大凌河城，"
        "统帅改为祖大寿，状态改为大凌河被围、粮道断绝、待援；因筑城被围，补给减十五、士气减六、"
        "机动减十。孙承宗督辽东诸军筹援，但本月不得虚写解围。钦此。",
    ),
    (
        "turn2_zu_dashou_defects",
        "奉天承运皇帝诏曰：大凌河城粮尽援绝，祖大寿明文降后金，归属改为后金，"
        "其在大凌河所部二万人成建制投后金。关宁军 / 宁锦防线中大凌河所部脱离明军，"
        "关宁军 / 宁锦防线人数减二万人，维护费减四万两，补给减十、士气减十二、忠诚减二十，"
        "状态改为大凌河所部投后金、宁锦余部退守锦州宁远。后金将祖大寿大凌河降兵另立为"
        "“祖大寿降军”，归属后金，驻地辽东 / 大凌河降营，统帅祖大寿，兵种降军步骑、火器兵，"
        "兵额二万人，月维护费零，补给四十、士气四十二、训练六十、装备五十五、欠饷零、机动四十、"
        "忠诚三十五，状态为新降后金、待皇太极改编。此事必须在邸报人事中写明祖大寿降后金，"
        "在军事中写明关宁军大凌河所部脱离明军，并新建归属后金的祖大寿降军。钦此。",
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
    characters = [
        dict(r)
        for r in db.conn.execute(
            """
            SELECT name,power_id,status,office,status_reason
            FROM characters
            WHERE name='祖大寿'
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
            WHERE id='guanning'
               OR name LIKE '%祖%'
               OR commander LIKE '%祖大寿%'
               OR owner_power='houjin'
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
            WHERE army_id='guanning'
               OR army_id IN (
                   SELECT id FROM armies
                   WHERE name LIKE '%祖%' OR commander LIKE '%祖大寿%' OR owner_power='houjin'
               )
            ORDER BY id
            """
        ).fetchall()
    ]
    extractions = [
        dict(r)
        for r in db.conn.execute(
            """
            SELECT turn,year,period,substr(extractor_output,1,2600) AS extractor_output
            FROM turn_extractions
            ORDER BY turn
            """
        ).fetchall()
    ]
    reports = [
        dict(r)
        for r in db.conn.execute(
            "SELECT turn,year,period,substr(report,1,1600) AS report FROM turn_reports ORDER BY turn"
        ).fetchall()
    ]
    return {
        "characters": characters,
        "armies": armies,
        "army_logs": army_logs,
        "extractions": extractions,
        "reports": reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/dalinghe_defection_probe.db")
    parser.add_argument("--start-ym", default="1631.07")
    parser.add_argument("--out", default="scripts/runs/dalinghe_defection_probe_result.json")
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
                "report_head": report[:1600],
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
