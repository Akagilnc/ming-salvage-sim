# #1902 D5 枚举命令与成员表

基线：`0ca77fecc` → `HEAD`。授权范围：该区间全部测试删改（Python `tests/` + Web `*.test|spec.*`）。

## 命令

七项 BIN 前缀（凡跑测试）：

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false
```

```bash
python3 evidence/issue-1902/enumerate_d5.py
node evidence/issue-1902/enumerate_d5_web.cjs
python3 evidence/issue-1902/classify_d5.py
```

## 成员表路径

| 产物 | 路径 |
|---|---|
| Python 全员 | `evidence/issue-1902/d5-python-members.json` |
| Web 全员 | `evidence/issue-1902/d5-web-members.json` |
| 分类全表 | `evidence/issue-1902/D5-member-table.json` |
| 分类摘要 | `evidence/issue-1902/d5-classification-summary.json` |

## 谓词（全文，未收窄）

- Python：`git diff --name-only 0ca77fecc -- tests` 内每个 `test_*` 函数，相对基线为新增／删除，或独立断言集合／`pytest.raises|warns` 异常上下文集合变化 → 成员。
- Web：同上区间 `web` 下 `*.(test|spec).[cm]?[jt]sx?` 的 `it`/`test` 块，相对基线删除或 `expect` 断言集合变化（含新增）→ 成员。
- 分类按独立契约：来源／持久化／真实入口选择／场景供料消费；合法措辞锁清退与退役 helper 证明维持；案例点名不作白名单。
