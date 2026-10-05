# #1853 修内司回执：J8-R2 + TEST-PARALLEL 两类全仓清退（续）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1853-w5`
- 分支：`ak-roles/1853-j8r2-test-parallel-bbf8f884f`
- 判词真源：`…/01a109ce-2123-793c-9df8-5dda245ee7b5@fixer/attachments/11-1853-judge-bbf8f884f.json` 末 payload
- 票面：#1853 / 总票 #1812「重构验收」
- 前序实现 commit：`7c7eab3993efac9dd3dfb9bf5e27858a13441adb`
- **本轮实现 commitSha：**（见文末）
- 未 amend / push / 开 PR；未改 Soul/宪法；未动宿主/席位配置；**本轮未再 stash**

## 违规 git stash（上轮如实记载；恢复≠未违规）

上轮修内司会话（transcript `e0f770f0-…`）曾禁止仍执行 stash：

1. **违规命令：**
   ```bash
   git stash push -u -m 'temp-check' -- ming_sim web_app.py tests
   ```
2. **恢复命令（随后立即执行，不得当作未违规）：**
   ```bash
   git stash pop
   ```

## 本轮自验缺口与处置

上轮 `ENUM_COMMANDS.md` Python 段仅为占位注释 + `/tmp/1853-fixer-enum` 指针（会话临时物，不可复核）。谓词曾收窄到符号名 `db`/`game_db` 与少数方法名，**漏掉** `except AttributeError` 包住 `db.conn` / 必备方法的兼容分支。

### 补入

- 工作树可执行脚本：
  - `artifacts/1853-fixer-enum/enum_class1_gamedb_capability.py`
  - `artifacts/1853-fixer-enum/enum_class2_test_parallel.py`
- 命令真源：`artifacts/1853-fixer-enum/ENUM_COMMANDS.md`

### 类一遗漏修复（AttributeError 软兼容）

| 成员 | 处置 |
|---|---|
| `ming_sim/knowledge.py` `knowledge_row_visible_to` 两处 `except (AttributeError, …)` 包 `db.conn.execute` | 删软兼容，直调 `db.conn` |
| `ming_sim/knowledge.py` `_household_ledger` 同形 | 删软兼容，直调 |
| `ming_sim/materials.py` `revoke_target_facts` `except (AttributeError, TypeError, ValueError)` | 去掉 `AttributeError`；仅保留业务拒收 `TypeError`/`ValueError`→空 dict |

回归案：`tests/test_j8r2_gamedb_capability_no_attrerror_shim_1853.py`（缺 conn / 缺 resolve 必须响亮 `AttributeError`）。

### 修改后复扫

```text
Class1 IN_CLASS_J8R2 = 0
Class2 COPY_ROLLBACK_LOGIC / RETIRED_LIGHTWEIGHT_TEST = 0；needs_attention = 0
协作替身 fail_chat_turn 等均为记账/抛错注入，无 msgs[:-1] 回滚复制
```

产物：`class1-raw.tsv` / `class1-post.tsv` / `class2-raw.tsv` / `class2-post.tsv` / `gamedb_api_names.txt`

剩余 `ATTRERROR_COMPAT_REVIEW`（非 GameDB 能力缺失）：`db.py` 启始年月解析、案卷 link 字段解析；`llm_model`/`web_app` 给异常盖 `stage`——不属于本类。

## 测试

七变量逐项显式（不可写成大括号折叠）：

```bash
MING_SIM_AGY_BIN=/usr/bin/false \
MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false \
MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false \
MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
python3 -m pytest -p tests.conftest \
  tests/test_j8r2_gamedb_capability_no_attrerror_shim_1853.py \
  tests/test_cli_play_turn.py \
  tests/test_web_chat_serialization_393.py \
  tests/test_menu_lifecycle_drain_396.py \
  tests/test_chat_stream_failpaths_393.py \
  tests/test_transaction_boundary.py \
  tests/test_audience_commit_failure_1853.py \
  tests/test_dossier_links_559.py \
  -q
```

（实测：**104 passed in 2.18s**。输出：`/tmp/1853-fixer-focused-rescan.txt`）

## 未结项

- 本两类复扫 0 剩余。
- 功能接线缺口仍归 #1873；本轮不封驳。
- 未跑全量；未合入目标分支。

## commitSha

（提交后回填）
