# #1853 合法性纠正：临时目录真实入口变异证明（非仓库测试）

禁止在仓库新增证明性测试。证明仅用系统临时目录变异真跑。

```bash
export MING_SIM_AGY_BIN=/usr/bin/false
export MING_SIM_CODEX_BIN=/usr/bin/false
export MING_SIM_CLAUDE_BIN=/usr/bin/false
export MING_SIM_CURSOR_BIN=/usr/bin/false
export MING_SIM_KIMI_BIN=/usr/bin/false
export MING_SIM_GROK_BIN=/usr/bin/false
export MING_SIM_PI_BIN=/usr/bin/false
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD"
# 脚本写在 /tmp（不入仓）；在工作树根执行：
python3 /tmp/1853-legal-correct-diag.py
```

脚本行为：在 `/tmp/1853-legal-correct.*` 复制并还原 `knowledge.py` / `materials.py` 的 AttributeError 软兼容旧逻辑；对真实入口 `knowledge_row_visible_to` / `_household_ledger` / `revoke_target_facts` 做「缺能力必须 AttributeError」判定——旧红 / 新绿。

输出样例见同目录 `legal-correct-diag_out.txt`。
