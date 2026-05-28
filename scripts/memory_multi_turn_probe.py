"""验同一召见内连续多句皇帝消息每条都跑检索。"""
from __future__ import annotations
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ming_sim.session import GameSession
from ming_sim.llm_config import load_llm_config


def main():
    db = "data/probe_memory.db"
    llm_config = load_llm_config(
        os.environ["OPENAI_BASE_URL"],
        os.environ["OPENAI_MODEL"],
        api_key=os.environ.get("OPENAI_API_KEY", ""),
    )
    session = GameSession(db, llm_config)
    session.begin_turn()

    msgs = [
        "近来钱粮如何？",                          # 1
        "陕西流寇近况？",                          # 2
        "再细说王嘉胤部人数变动",                  # 3
        "徐光启入阁可有掣肘？",                    # 4
        "辽东宁锦现状又如何？",                    # 5 命中辽东
        "那王嘉胤眼下还在陕北？",                  # 6 又问王嘉胤+陕西
    ]
    for i, m in enumerate(msgs, 1):
        print(f"\n===== 第 {i} 句皇帝消息: {m!r} =====")
        augmented = session._retrieve_memories_for_message(m)
        print(f"原长 {len(m)} → 注入后 {len(augmented)} 字")
        if augmented != m:
            print("HEAD:", augmented.split("\n\n")[0][:300])
        else:
            print("（未注入）")


if __name__ == "__main__":
    main()
