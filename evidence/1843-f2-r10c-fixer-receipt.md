# #1843 F2-R10c 回执（证据减重后）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`
分支：`ak-roles/issue-1843-w5-r6-f2`
派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a108b9-e49f-7a41-a7de-d543dc256654@fixer/fix-packet.md`

## 唯一证据（DRY）

| 用途 | 路径 |
|---|---|
| F2-R10-2 逐名 2101 | `evidence/1843-f2-r10c-f2-all-candidates.tsv` |
| F2-R10-1 类外 30 | `evidence/1843-f2-r10c-f1-ooc-members.tsv` |
| 成员索引 | `evidence/1843-f2-r10c-member-table.tsv` |
| 可复制枚举（heredoc 唯一脚本源） | `evidence/1843-f2-r10c-enum-commands.txt` |
| 聚焦测试日志 | `evidence/1843-f2-r10c-pytest.log` |

已删本局冗余：`*-raw/classified/seeds/refined/summary*.json`、`enum_f2_r10_{1,2}.py`（与 TSV/heredoc 重复）。

## 类定义（摘要）

- **F2-R10-1**：旧结算／simulator 独占支持树退役；保留现役 normalize／revise／prewrite／共用存储。
- **F2-R10-2**：全仓非契约源码／措辞锁、helper／内部结构及重复；私有调用本身不非法——契约在外部结构化则 RETAIN（写入口/字段）；只锁 helper 内部则 DELETE。

## sut_private 矛盾 reason 复查

模板「kinds 含 sut_private 却写非生产私有结构锁」已清零。逐名核约后：

- **DELETE=12**（已删测试代码）：`_coerce_new_salary_rate` 纯返回、`_codex_final_text` 形态、`_resolve_cli_bin`/`_BIN_CACHE`/`_login_shell_path` 哨兵纯返回、`_coerce_draft_target_kind` 纯返回。
- **RETAIN**（改写具体入口→字段）：如 `submit_hitl_choices`→`event_triggers.{terminal_state,source,choice_json}`；CLI `_run_*`→argv/env/stdout；`_extract_secret_order`→`excluded_*`/`title` 等。

## 本腿代码

- 删除上述 12 个纯私有 helper 单测（`test_army_salary_44.py` / `test_cli_backend.py` / `test_execution_pressure_654.py`）
- 未新增扫描机制；未 stash／amend／push

## 聚焦测试

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_army_salary_44.py \
  tests/test_cli_backend.py \
  tests/test_execution_pressure_654.py
```

结果：**176 passed in 1.74s**；EXIT 0。日志：`evidence/1843-f2-r10c-pytest.log`。

## 自查二连

- 同类型：废止 raw/classified/py 与 TSV/heredoc 双轨；矛盾 RETAIN 逐名改写或删除，非统一模板。
- 引入 bug：只删纯 helper 结构单测；外部结构化／CLI argv 契约保留；七 BIN 前缀聚焦。
