"""点对点测试：跳大臣对话，直接塞诏书草案 → 结算 → 查 DB。

用法：
  .venv/bin/python scripts/direct_decree_probe.py \
      --db data/probe.db \
      --start-ym 1631.08 \
      --directive "设立火器试制局，挂兵部，徐光启提督，首拨内库银十万两清基动工" \
      --directive "辽东大凌河祖大寿被困粮尽，朝廷救援不至，准其降清，power 由 ming 转 houjin"

可多次 --directive。--decree 可选，传入则跳过 LLM 写诏，直接拿来当诏书文本喂 simulator。
不传 --decree 时仍走 write_decree_with_agno（要 LLM），但完全不走 minister chat。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ming_sim.session import GameSession
from ming_sim.llm_config import load_llm_config


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True, help="测试 DB 路径")
    p.add_argument("--agno-db", default="", help="agno 记忆库；默认 <db>_agno.db")
    p.add_argument("--start-ym", default="", help="开局年月，如 1631.08；空=默认开局")
    p.add_argument("--directive", action="append", required=True,
                   help="一条诏书草案文本，可多次传入")
    p.add_argument("--decree", default="", help="最终诏书文本；空=由 LLM 写诏")
    p.add_argument("--cheat", default="", help="作弊强制结算项，拼到邸报最前喂 extractor 当既成事实")
    p.add_argument("--resume", action="store_true",
                   help="续跑既有 DB，不清库；默认不清库（脚本本身不删 DB）")
    p.add_argument("--reset", action="store_true",
                   help="跑前删除 DB / agno DB / emperor DB")
    p.add_argument("--jump-to", default="",
                   help="开局后直接把回合跳到年.月，如 1631.07。会覆写 game_state.year/period。turn 同步推进。")
    p.add_argument("--sql", action="append", default=[],
                   help="结算前执行的任意 SQL，可多次。用于直接改 DB 状态（人物/军队/数值等）。")
    p.add_argument("--set-metric", action="append", default=[], metavar="KEY=VAL",
                   help="结算前直接改核心指标内存值，如 国库=99999。metrics 是内存态，"
                        "必须走这条而非 --sql（--sql 改 DB 行会被结算回写覆盖）。可多次。")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    db_path = args.db
    agno_db = args.agno_db or db_path.replace(".db", "_agno.db")
    emperor_db = f"{agno_db}.emperor.db"

    if args.reset:
        for p in (db_path, agno_db, emperor_db):
            if os.path.exists(p):
                os.remove(p)
                print(f"[reset] 删 {p}")

    if not os.environ.get("OPENAI_API_KEY") and not os.environ.get("PLAYTEST_API_KEY"):
        print("[ERROR] 需 export OPENAI_API_KEY 或 PLAYTEST_API_KEY", file=sys.stderr)
        return 2

    base_url = os.environ.get("OPENAI_BASE_URL", "")
    model = os.environ.get("OPENAI_MODEL", "")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not base_url or not model:
        print("[ERROR] 需 export OPENAI_BASE_URL/OPENAI_MODEL", file=sys.stderr)
        return 2

    llm_config = load_llm_config(base_url, model, api_key=api_key)
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    session = GameSession(db_path, llm_config, start_ym=args.start_ym or None)

    if args.jump_to:
        try:
            y_str, m_str = args.jump_to.split(".")
            target_year, target_month = int(y_str), int(m_str)
        except Exception:
            print(f"[ERROR] --jump-to 格式错: {args.jump_to}，应为 1631.07", file=sys.stderr)
            return 2
        cur_y, cur_m = session.state.year, session.state.period
        months_diff = (target_year - cur_y) * 12 + (target_month - cur_m)
        if months_diff < 0:
            print(f"[ERROR] --jump-to {args.jump_to} 早于当前 {cur_y}.{cur_m:02d}", file=sys.stderr)
            return 2
        session.state.year = target_year
        session.state.period = target_month
        session.state.turn = session.state.turn + months_diff
        session.db.save_state(session.state)
        print(f"[jump] {cur_y}.{cur_m:02d} → {target_year}.{target_month:02d} (turn={session.state.turn})")

    snap = session.begin_turn()
    print(f"[turn] year={snap.year} period={snap.period} turn={snap.turn} phase={snap.phase}")

    for spec in args.set_metric:
        try:
            key, val = spec.split("=", 1)
            key = key.strip()
            session.state.metrics[key] = int(val)
            session.db.save_state(session.state)
            print(f"[set-metric] OK: {key}={int(val)}")
        except Exception as e:
            print(f"[set-metric] FAIL: {spec} → {e}", file=sys.stderr)
            return 2

    for sql in args.sql:
        try:
            session.db.conn.execute(sql)
            session.db.conn.commit()
            print(f"[sql] OK: {sql[:120]}")
        except Exception as e:
            print(f"[sql] FAIL: {sql[:120]} → {e}", file=sys.stderr)
            return 2

    for text in args.directive:
        view = session.add_directive(text, notes="direct-probe")
        print(f"[directive] id={view.id} text={text[:60]}")

    session.enter_review()

    def on_event(kind, data):
        if kind in ("simulator_chunk", "extractor_chunk"):
            return
        print(f"[evt] {kind}: {str(data)[:200]}")

    print("[resolve] 开始结算 ...")
    report = session.resolve_turn(decree=args.decree, on_event=on_event, cheat_directive=args.cheat)
    print(f"[resolve] 完成。Report 字符数={len(report)}")
    print("---- REPORT 头 300 ----")
    print(report[:300])
    print("----")

    session.end_turn()
    print(f"[done] DB={db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
