"""第二回合：模拟「曹化淳已得底册37人含近侍但扣报」，验 done 红线。

修复前：sim 会把这种瞒报判 done。修复后应判 active（result 点出扣册未呈）。
复用 secret_test.db（probe1 已建 active 密令 #1）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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
# 把密令 #1 的进展改成「已得底册37人含近侍，但扣报」——这是 bug 复现态
WITHHELD = ("曹化淳已得底册数十页，内列魏忠贤旧部、内外勾连者三十七人，"
            "中有数名现充御前近侍。然化淳以『尚未核实』为辞，迟迟未将底册呈进，"
            "仅密奏一语『近臣亦有涉』，余皆讳莫如深。")
DECREE = "朕已三月未见曹化淳所呈阉党底册，着其即刻将所查情状、人等名册尽数密奏御前，不得再以未核实为辞延宕。"


def main() -> None:
    content = GameContent.load()
    llm = load_llm_config(
        os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    )
    sess = GameSession(DB, llm, content=content, verify_llm=True)
    sess.begin_turn()
    # 强制把 #1 推到瞒报态
    sess.db.update_secret_order_progress(1, WITHHELD)
    print(f"[probe2] 已把密令 #1 进展置为瞒报态")
    sess.add_directive(DECREE, notes="催曹化淳呈册")
    report = sess.resolve_turn(decree=DECREE)
    # 只打密旨动向章 + 状态，邸报全文太长
    print("\n========== 密旨动向章（截取） ==========\n")
    for para in report.split("\n"):
        if "密旨" in para or "曹化淳" in para or "化淳" in para or "底册" in para or "近臣" in para:
            print(para.strip())
    print("\n========== 密令状态 ==========\n")
    for o in sess.db.list_secret_orders():
        print(f"#{o['id']} status={o['status']} title={o['title']!r}")
        print(f"    result={o.get('result')!r}")
    sess.close()


if __name__ == "__main__":
    main()
