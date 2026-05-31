"""结算链 token 基准：1 回合 = N 轮大臣对话 + M 道诏书 + 推演结算，统计 token。

与 token-benchmark（play_as_emperor 驱动、带玩家崇祯 agent）的区别：
- 本脚本**不起玩家 agent**，问话是脚本内置的轮换模板 → 省掉玩家侧 LLM，只测**游戏侧**
  （大臣对话 + 拟诏 + simulator + extractor）真实 token。
- 直接调 GameSession.chat / add_directive / resolve_turn，比走 CLI pexpect 稳、快、可复现。

token 抓取：import ming_sim.llm_model 时自动 install_token_stats_patch()（llm_model.py:72），
每次 completion 打 `[TOKEN] caller=.. model=.. prompt=.. cached=.. completion=.. total=..`；
跑完 print_token_summary() 出汇总。再用 scripts/sum_token_log.py 细分。

用法：
  set -a; source .env; set +a   # 或显式 export OPENAI_BASE_URL/MODEL/API_KEY
  .venv/bin/python scripts/decree_bench.py --db data/decree_bench.db --reset \
      --chats 30 --decrees 10 --log scripts/runs/decree_bench_$(date +%s).log
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ming_sim.session import GameSession            # noqa: E402
from ming_sim.llm_config import load_llm_config     # noqa: E402
from ming_sim.token_stats import print_token_summary  # noqa: E402

# 轮换问话模板：5 大议题，循环喂给在朝大臣（不依赖具体人名，谁在朝问谁）。
QUESTION_BANK = [
    "如今太仓存银几何？辽饷、官俸、宗禄、京营军饷月支缺口多大，可有开源节流之策？",
    "辽东宁锦防线虚实如何？关宁军欠饷几月，士卒可有鼓噪？建虏近日有何异动？",
    "陕西连岁亢旱，流民盗匪渐起，赈济可曾到位？若激成民变，何以弭之？",
    "朝中党争未息，东林与阉党余孽各执一词，卿以为当如何持平用人、整肃纲纪？",
    "内廷用度、织造、皇庄岁入近况如何？厂卫与司礼监可有逾矩之处？",
    "九边各镇兵额、马政、屯田废弛已久，卿可有整饬边备、核实军伍之议？",
]
# 10 道诏书草案：覆盖财政/边防/民变/人事/内廷/军工，喂结算链。
DECREE_BANK = [
    "着户部毕自严核两京十三省积欠钱粮，造册具奏，凡侵欺挪移者依律追比。",
    "特从内库拨银三十万两专补关宁军欠饷，余镇由户部统筹分摊，限一月议定。",
    "陕西大旱，着该省巡抚开仓平粜、蠲免本年田赋三成，发赈银十万两活饥民。",
    "着工部于京营增筑火器局一所，命徐光启提督，督造红夷炮与火铳装备京军。",
    "整饬九边马政屯田，着各镇督抚核实兵额、清查虚冒，岁终考成具奏。",
    "盐政积弊，着两淮巡盐御史清查盐引、革除浮费，岁额不足者议处。",
    "着都察院遣巡按御史分赴各省，纠劾贪墨、清理积案、抚绥流移。",
    "宗藩禄米浩繁，着礼部会同户部议定折色裁减之法，以纾国用。",
    "京营操练废弛，着提督京营戎政大臣严加操演、汰老弱、补精壮。",
    "着兵部移文蓟辽督师，整饬宁锦防务、储粮缮城，毋使建虏乘虚。",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/decree_bench.db", help="基准库（别用 ming_sim.db）")
    p.add_argument("--agno-db", default="", help="agno 记忆库；默认 <db>_agno.db")
    p.add_argument("--chats", type=int, default=30, help="大臣对话轮数")
    p.add_argument("--decrees", type=int, default=10, help="诏书草案条数")
    p.add_argument("--start-ym", default="", help="开局年月，如 1629.04；空=默认开局")
    p.add_argument("--reset", action="store_true", help="跑前删库重开（基准可比）")
    p.add_argument("--log", default="", help="同时把 stdout 落盘到该文件")
    return p.parse_args()


class _Tee:
    """把 stdout 同时写终端与文件，便于 sum_token_log.py 事后扫 [TOKEN] 行。"""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, s):
        for st in self._streams:
            st.write(s)
            st.flush()

    def flush(self):
        for st in self._streams:
            st.flush()


def _active_ministers(session: GameSession, limit: int) -> list[str]:
    rows = session.db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND office_type!='后宫' ORDER BY rowid"
    ).fetchall()
    names = [r["name"] for r in rows]
    if not names:
        raise SystemExit("无在朝大臣，无法跑对话基准。")
    return names[:limit] if limit else names


def main() -> int:
    args = parse_args()
    log_fh = open(args.log, "w", encoding="utf-8") if args.log else None
    if log_fh:
        sys.stdout = _Tee(sys.__stdout__, log_fh)
        sys.stderr = _Tee(sys.__stderr__, log_fh)

    db_path = args.db
    agno_db = args.agno_db or db_path.replace(".db", "_agno.db")
    emperor_db = f"{agno_db}.emperor.db"
    if args.reset:
        for pth in (db_path, agno_db, emperor_db):
            if os.path.exists(pth):
                os.remove(pth)
                print(f"[reset] 删 {pth}")

    base_url = os.environ.get("OPENAI_BASE_URL", "")
    model = os.environ.get("OPENAI_MODEL", "")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not base_url or not model or not api_key:
        print("[ERROR] 需 export OPENAI_BASE_URL/OPENAI_MODEL/OPENAI_API_KEY", file=sys.stderr)
        return 2
    llm_config = load_llm_config(base_url, model, api_key=api_key)
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    print(f"[bench] EXTRACTOR_MODE={os.environ.get('MING_SIM_EXTRACTOR', 'module')} "
          f"model={model} chats={args.chats} decrees={args.decrees}")
    session = GameSession(db_path, llm_config, start_ym=args.start_ym or None)
    snap = session.begin_turn()
    print(f"[turn] year={snap.year} period={snap.period} turn={snap.turn}")

    # ── N 轮大臣对话：在朝大臣 round-robin，问话题库轮换 ──
    ministers = _active_ministers(session, limit=8)  # 取前 8 位轮着问，覆盖各派
    print(f"[chat] 召见大臣池: {ministers}")
    for i in range(args.chats):
        name = ministers[i % len(ministers)]
        q = QUESTION_BANK[i % len(QUESTION_BANK)]
        try:
            res = session.chat(name, q)
            ans = (res.answer or "").strip().replace("\n", " ")
            print(f"[chat {i+1}/{args.chats}] {name}: {ans[:80]}")
        except Exception as e:  # noqa: BLE001 — 单轮失败不终止基准
            print(f"[chat {i+1}/{args.chats}] {name} 失败: {e}")

    # ── M 道诏书草案入档 ──
    for j in range(args.decrees):
        text = DECREE_BANK[j % len(DECREE_BANK)]
        view = session.add_directive(text, notes="decree-bench")
        print(f"[directive {j+1}/{args.decrees}] id={view.id} {text[:40]}")

    # ── 拟诏 + 推演结算（拟诏走 LLM；不传 decree=由 LLM 合并草案）──
    session.enter_review()

    def on_event(kind, data):
        if kind in ("simulator_chunk", "extractor_chunk"):
            return
        print(f"[evt] {kind}: {str(data)[:120]}")

    print("[resolve] 开始结算（拟诏 + simulator + extractor）...")
    report = session.resolve_turn(on_event=on_event)
    print(f"[resolve] 完成。邸报 {len(report)} 字。")
    session.end_turn()

    print("\n[bench] 全部 LLM 调用完成，下面是 token 汇总：")
    print_token_summary()
    print(f"\n[bench] 细分按 caller： .venv/bin/python scripts/sum_token_log.py --by-caller {args.log or '<your.log>'}")
    print(f"[done] DB={db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
