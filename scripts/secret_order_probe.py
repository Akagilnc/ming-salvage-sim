"""一回合密令推演探针：给曹化淳下密令，跑真 LLM 推演，看「密旨动向」章 + status。

验 done 红线修复：曹化淳若瞒报/扣册/称未核实，应判 active 不判 done。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# .env 用 CLI_* 命名，代码读 OPENAI_*，在此映射
_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip().strip('"').strip("'")
for src, dst in (("CLI_API_KEY", "OPENAI_API_KEY"),
                 ("CLI_BASE_URL", "OPENAI_BASE_URL"),
                 ("CLI_MODEL", "OPENAI_MODEL")):
    if os.environ.get(src) and not os.environ.get(dst):
        os.environ[dst] = os.environ[src]

from ming_sim.content import GameContent
from ming_sim.llm_config import load_llm_config
from ming_sim.session import GameSession

DB = "data/secret_test.db"
ASSIGNEE = "曹化淳"
TITLE = "密查阉党余孽"
CONTENT = ("着司礼监秉笔太监曹化淳，密查阉党余孽及内外官员暗通款曲、结党营私之事。"
           "凡魏忠贤旧部、内廷外朝勾连之人，逐一密记底册，不得声张，不得惊动。"
           "所获情状，只许密奏御前，不许泄于第二人。期限：三个月内呈送初步底册。")
DECREE = ("朕闻阉党虽诛，余孽未尽，内外尚有暗通款曲者。着曹化淳密查阉党余孽及内外官员"
          "结党营私之事，逐一密记底册，密奏御前，限三月呈送初步底册。")


def main() -> None:
    content = GameContent.load()
    llm = load_llm_config(
        os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    )
    sess = GameSession(DB, llm, content=content, verify_llm=True,
                       start_ym=os.environ.get("MING_SIM_START_YM", "1627.10"))
    sess.begin_turn()
    oid = sess.db.create_secret_order(sess.state, ASSIGNEE, TITLE, CONTENT, ["阉党", "密查"], importance=4)
    print(f"[probe] 密令已下 id={oid} 承办={ASSIGNEE}")
    sess.add_directive(DECREE, notes="密令同发")
    report = sess.resolve_turn(decree=DECREE)
    print("\n========== 月末邸报 ==========\n")
    print(report)
    print("\n========== 密令状态 ==========\n")
    for o in sess.db.list_secret_orders():
        print(f"#{o['id']} status={o['status']} title={o['title']!r}")
        print(f"    result={o.get('result')!r}")
    sess.close()


if __name__ == "__main__":
    main()
