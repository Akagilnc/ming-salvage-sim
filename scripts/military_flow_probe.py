"""Probe military flow extraction across multiple turns.

Runs three fixed decrees against a disposable DB:
1. Replace Guanning leader with Sun Chengzong and create a new army.
2. Expand, shrink, reorganize, and dispatch that army to Liaodong.
3. Partially disband the new army and remove remaining old/weak troops.
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
        "turn1_replace_and_create",
        "奉天承运皇帝诏曰：辽东军务不可再悬。着起用孙承宗总理关宁军务，"
        "关宁军 / 宁锦防线统帅由袁崇焕改为孙承宗，"
        "袁崇焕回京候用。另于京师昌平新建一支成建制新军，军号“神枢新军”，"
        "归属大明，驻地京师昌平，统帅徐光启，"
        "兵种为火器步兵、炮兵、选锋步卒，初募八千人，月维护费二万两，"
        "补给五十五、士气六十、训练三十五、装备五十、欠饷零、机动四十五、忠诚六十五。"
        "此军独立成营，不并入京营。钦此。",
    ),
    (
        "turn2_resize_reform_dispatch",
        "奉天承运皇帝诏曰：神枢新军既已成营，着扩编精锐三千人，另裁汰老弱一千人，"
        "净增二千人，月维护费增一万两。其兵种改为火器步兵、炮兵、车营辎重，"
        "统帅改为孙承宗。即日起自京师昌平调往辽东宁远，"
        "状态改为赴辽东驻防并操演火器。因长途出关，补给暂减五、机动暂减五；"
        "因专操火器，训练增八、装备增五。钦此。",
    ),
    (
        "turn3_disband_part",
        "奉天承运皇帝诏曰：神枢新军赴辽后，军中老弱、逃亡及不习火器者仍多。"
        "着裁撤神枢新军三千人，月维护费减一万两，余部留驻辽东宁远，由孙承宗统帅，"
        "状态改为裁撤老弱后驻辽东。另关宁军中年老病弱与空额兵裁撤五千人，"
        "月维护费减一万两，状态改为裁汰空额后整饬。钦此。",
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
    armies = [
        dict(r)
        for r in db.conn.execute(
            """
            SELECT id,name,owner_power,station,commander,troop_type,
                   manpower,maintenance_per_turn,supply,morale,training,equipment,
                   arrears,mobility,loyalty,status
            FROM armies
            WHERE id IN ('guanning','shen_shu_new_army')
               OR name LIKE '%神枢%'
            ORDER BY id
            """
        ).fetchall()
    ]
    logs = [
        dict(r)
        for r in db.conn.execute(
            """
            SELECT turn,year,period,army_id,field,old_value,new_value,delta,reason
            FROM army_logs
            WHERE army_id IN ('guanning','shen_shu_new_army')
               OR army_id IN (SELECT id FROM armies WHERE name LIKE '%神枢%')
            ORDER BY id
            """
        ).fetchall()
    ]
    issues = [
        dict(r)
        for r in db.conn.execute(
            "SELECT id,title,bar_value,status,stage_text FROM issues ORDER BY id"
        ).fetchall()
    ]
    reports = [
        dict(r)
        for r in db.conn.execute(
            "SELECT turn,year,period,substr(report,1,500) AS narrative FROM turn_reports ORDER BY turn"
        ).fetchall()
    ]
    return {"armies": armies, "army_logs": logs, "issues": issues, "reports": reports}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/military_flow_probe.db")
    parser.add_argument("--start-ym", default="1627.10")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    _env_from_dotenv()
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
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
    if args.out:
        out_path = ROOT / args.out
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        print(f"[probe] wrote {out_path}")
    print(text[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
