# 临时诊断命令（非永久测试）

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD"
DIAG=$(mktemp -d /tmp/1853-next-diag.XXXXXX)
BT=$(mktemp -d /tmp/1853-next-bt.XXXXXX)
# 写入临时 pytest：owns 写前捕获 / BEGIN 下手抄冲突文档化 /
# stage_pending_action 在 BEGIN|atomic|自有 三种入口
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -p tests.conftest \
  "$DIAG/test_diag_*.py" -q -s -p no:cacheprovider --basetemp="$BT"
rm -rf "$BT" "$DIAG"
```

输出见 `diag_out.txt`。
