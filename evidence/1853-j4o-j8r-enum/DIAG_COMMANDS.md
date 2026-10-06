# 临时变异诊断（可核；非永久测试）

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD"
DIAG=$(mktemp -d /tmp/1853-j4o-j8r-diag.XXXXXX)
BT=$(mktemp -d /tmp/1853-j4o-j8r-bt.XXXXXX)
# 将临时 test_diag_j4o_j8r.py 写入 $DIAG（与本回执同逻辑：真实 game fixture 入口；
# close_secret_order(commit=False)|BEGIN → commit_pending_actions → rollback；
# 内存变异 atomic 深度1 总 commit 复现旧红；措辞与 materials hasattr 空结果对照）
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -p tests.conftest \
  "$DIAG/test_diag_j4o_j8r.py" -q -s -p no:cacheprovider --basetemp="$BT"
rm -f "$DIAG/test_diag_j4o_j8r.py"; rm -rf "$BT"
```

本轮产物：`evidence/1853-j4o-j8r-enum/diag_out.txt`（DIAG=/tmp/1853-j4o-j8r-diag.H5f7i1）
