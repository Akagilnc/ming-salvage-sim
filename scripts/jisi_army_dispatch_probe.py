"""Probe Jisi Incident army dispatch for enemy and Ming armies.

Runs two fixed turns:
1. Huangtaiji moves Manchu banners into Beizhili while Ming armies encircle.
2. Manchu banners are repelled and move back to Jianzhou.
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
        "turn1_banners_enter_beizhili",
        "奉天承运皇帝诏曰：皇太极率满洲八旗主力绕道蒙古，自喜峰口、龙井关破边墙入塞，"
        "满洲八旗主力驻地改为北直隶 / 遵化三河一线，状态改为入塞劫掠、逼近京畿。"
        "着京营调驻京师九门与德胜门外，蓟镇兵调驻喜峰口残关堵截，宣大边军调驻居庸关、昌平一线，"
        "关宁军 / 宁锦防线抽精锐调驻山海关至通州勤王线，四军合围八旗，不得各自观望。钦此。",
    ),
    (
        "turn2_banners_retreat_jianzhou",
        "奉天承运皇帝诏曰：京营、蓟镇、宣大、关宁诸军合围之后，满洲八旗主力在通州、三河间受阻，"
        "粮草不继，皇太极撤军。满洲八旗主力驻地改回建州 / 赫图阿拉，状态改为入塞受挫后退回建州整补。"
        "京营驻地改回京师，蓟镇兵驻地改回蓟镇边墙，宣大边军驻地改回宣府大同，"
        "关宁军 / 宁锦防线驻地改回辽东 / 宁远锦州。钦此。",
    ),
]


ARMY_IDS = ("manchu_banners_main", "jingying", "jizhen", "xuan_da", "guanning")


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
    placeholders = ",".join("?" for _ in ARMY_IDS)
    db = sess.db
    armies = [
        dict(r)
        for r in db.conn.execute(
            f"""
            SELECT id,name,owner_power,station,commander,troop_type,
                   manpower,maintenance_per_turn,supply,morale,training,equipment,
                   arrears,mobility,loyalty,status
            FROM armies
            WHERE id IN ({placeholders})
            ORDER BY id
            """,
            ARMY_IDS,
        ).fetchall()
    ]
    logs = [
        dict(r)
        for r in db.conn.execute(
            f"""
            SELECT turn,year,period,army_id,field,old_value,new_value,delta,reason
            FROM army_logs
            WHERE army_id IN ({placeholders})
            ORDER BY id
            """,
            ARMY_IDS,
        ).fetchall()
    ]
    reports = [
        dict(r)
        for r in db.conn.execute(
            "SELECT turn,year,period,substr(report,1,1200) AS report FROM turn_reports ORDER BY turn"
        ).fetchall()
    ]
    return {"armies": armies, "army_logs": logs, "reports": reports}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/jisi_dispatch_probe.db")
    parser.add_argument("--start-ym", default="1629.11")
    parser.add_argument("--out", default="scripts/runs/jisi_dispatch_probe_result.json")
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

    output = {"db": str(db_path), "turns": results, "final": final}
    text = json.dumps(output, ensure_ascii=False, indent=2)
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"[probe] wrote {out_path}")
    print(text[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
