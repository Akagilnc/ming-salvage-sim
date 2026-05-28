"""检索探针：用现有 DB 跑记忆检索，验"过几回合后还能不能召回"。

用法：
  .venv/bin/python scripts/memory_recall_probe.py \
      --db data/probe_memory.db \
      --jump-turns 2 \
      --message "陕西流寇近况如何？王嘉胤部还在吗？" \
      --minister 杨嗣昌

调三类检索：
  1. db.get_recent_event_memories(window=5)      —— build_memory_brief 路径
  2. _retrieve_memories_for_message(message)     —— chat 路径（带 LLM 抽词）
  3. db.get_memories_by_keywords(['流寇','陕西','王嘉胤'])  —— 月末 retrieval 路径
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ming_sim.session import GameSession
from ming_sim.llm_config import load_llm_config
from ming_sim.registry import build_memory_brief
from ming_sim.models import CourtContext


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True)
    p.add_argument("--jump-turns", type=int, default=2, help="把当前 turn 往后推 N 月")
    p.add_argument("--message", required=True, help="模拟皇帝向大臣提问")
    p.add_argument("--minister", default="杨嗣昌", help="召见大臣，用于 build_memory_brief")
    p.add_argument("--keywords", default="陕西,流寇,王嘉胤,徐光启", help="逗号分隔关键词")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    base_url = os.environ.get("OPENAI_BASE_URL", "")
    model = os.environ.get("OPENAI_MODEL", "")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not base_url or not model:
        print("[ERROR] 需 export OPENAI_BASE_URL/OPENAI_MODEL", file=sys.stderr)
        return 2

    llm_config = load_llm_config(base_url, model, api_key=api_key)
    session = GameSession(args.db, llm_config)

    # 跳 N 月（不结算，纯改 state）
    if args.jump_turns > 0:
        old_turn = session.state.turn
        old_ym = (session.state.year, session.state.period)
        for _ in range(args.jump_turns):
            session.state.next_period()
        session.db.save_state(session.state)
        print(f"[jump] turn {old_turn}@{old_ym[0]}.{old_ym[1]:02d} → "
              f"{session.state.turn}@{session.state.year}.{session.state.period:02d}")

    # 必须 begin_turn 才能拿 registry / context
    snap = session.begin_turn()
    print(f"[turn] phase={snap.phase} year={snap.year} period={snap.period} turn={snap.turn}")

    print("\n========== 1) build_memory_brief（大臣 prompt 月度块） ==========")
    char = session._character(args.minister)
    ctx = CourtContext(state=session.state, db=session.db)
    brief = build_memory_brief(char, ctx)
    print(f"[result] minister={args.minister} brief 字数={len(brief)}")
    if brief:
        print(brief)
    else:
        print("（空，window=1 拉不到上回合记忆）")

    print("\n========== 2) _retrieve_memories_for_message（chat 路径，LLM 抽词） ==========")
    augmented = session._retrieve_memories_for_message(args.message)
    if augmented == args.message:
        print("[result] 未命中或注入失败，message 未被改写")
    else:
        print(f"[result] message 被改写，原长 {len(args.message)} → 新长 {len(augmented)}")
        print("---- augmented head 800 ----")
        print(augmented[:800])

    print("\n========== 3) db.get_memories_by_keywords（显式关键词） ==========")
    kw_list = [k.strip() for k in args.keywords.split(",") if k.strip()]
    print(f"[query] keywords={kw_list} turn={session.state.turn}")
    rows = session.db.get_memories_by_keywords(kw_list, turn=session.state.turn, limit=10)
    print(f"[result] hit={len(rows)}")
    for r in rows:
        print(f"  - #{r['id']} {r['year']}.{r['period']:02d} "
              f"[{r['subject_type']}:{r['subject_id']}] {r['title']}"
              f" (imp={r['importance']}, src={r['source_kind']})")

    print("\n========== 4) get_recent_event_memories(window=5)（不限主体扫近 5 月） ==========")
    recent = session.db.get_recent_event_memories(turn=session.state.turn, window=5, limit=50)
    print(f"[result] hit={len(recent)}")
    for r in recent[:15]:
        print(f"  - #{r['id']} {r['year']}.{r['period']:02d} "
              f"[{r['subject_type']}:{r['subject_id']}] {r['title']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
