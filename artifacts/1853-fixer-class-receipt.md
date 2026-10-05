# #1853 修内司回执：J8-R2 + TEST-PARALLEL 两类全仓清退（续）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1853-w5`
- 分支：`ak-roles/1853-j8r2-test-parallel-bbf8f884f`
- 判词真源：`…/01a109ce-2123-793c-9df8-5dda245ee7b5@fixer/attachments/11-1853-judge-bbf8f884f.json` 末 payload
- 票面：#1853 / 总票 #1812「重构验收」
- 前序实现 commit：`7c7eab3993efac9dd3dfb9bf5e27858a13441adb`
- 能力清退实现 commit：`bc86a83c4f50f874bc4104025273652b062fe1ab`
- **本轮合法性纠正 commitSha：**（见本提交后 `git rev-parse HEAD`；不另开纯 hash 戳提交）
- 未 amend / push / 开 PR；未改 Soul/宪法；未动宿主/席位配置；**本轮未 stash**

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

### 合法性纠正（本轮；质量法）

上一轮在实现 commit `bc86a83c4` **违规新增**仓库证明性测试：

- 已删：`tests/test_j8r2_gamedb_capability_no_attrerror_shim_1853.py`
- 违反：本票质量法「不为证明修复造测试」及末判禁止新增证明测试
- **不换形再造**（不以其它文件名/夹具形态把同一证明测搬回 `tests/`）

证明方式改为**系统临时目录真实入口变异真跑**（旧逻辑红 / 新逻辑绿），命令与输出留在工作树证据，不进 `tests/`：

- 配方：`artifacts/1853-fixer-enum/LEGAL_CORRECT_DIAG.md`
- 本次 stdout：`artifacts/1853-fixer-enum/legal-correct-diag_out.txt`
- 实测：`VERDICT=PASS old_red/new_green`（`NEW_LOGIC=GREEN`；`OLD_LOGIC=RED`；户部 reader-site flip-conn 亦旧红新绿）

## 修改后复扫（合法性纠正后重跑；全仓无自缩窄）

```text
Class1 files_scanned=361；IN_CLASS_J8R2=0
Class2 test_files_scanned=235；COPY_ROLLBACK_LOGIC=0；RETIRED_LIGHTWEIGHT_TEST=0；needs_attention=0
证明测文件名在 class1/class2 TSV 残余命中=0
协作替身 fail_chat_turn 等均为记账/抛错注入，无 msgs[:-1] 回滚复制
```

ENUM 复核（对照末判两类定义全文，**未**收窄到符号名 `db` / 生产目录 / 少数方法样本）：

- 脚本仍全仓 `*.py` / `tests/**/*.py` AST 枚举（仅跳过 `.venv`/`node_modules`/`archive` 等非源）
- Class1：`hasattr`/`getattr`/`callable`/`except AttributeError` 全收集；`IN_CLASS_J8R2` 含任意 GameDB 别名接收者 + try 体触及 `conn`/GameDB API 的 AttributeError 兼容
- Class2：持久化/回滚方法集与退役标记全表，不限 `fail_chat_turn`/`append` 前几项样本

产物：`class1-raw.tsv` / `class1-post.tsv` / `class2-raw.tsv` / `class2-post.tsv` / `gamedb_api_names.txt`

剩余 `ATTRERROR_COMPAT_REVIEW`（非 GameDB 能力缺失）：`db.py` 启始年月解析、案卷 link 字段解析；`llm_model`/`web_app` 给异常盖 `stage`——不属于本类。

## 测试

七变量逐项显式（不可写成大括号折叠）；**不含**已删证明测；不全量：

```bash
MING_SIM_AGY_BIN=/usr/bin/false \
MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false \
MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false \
MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
python3 -m pytest -p tests.conftest \
  tests/test_cli_play_turn.py \
  tests/test_web_chat_serialization_393.py \
  tests/test_menu_lifecycle_drain_396.py \
  tests/test_chat_stream_failpaths_393.py \
  tests/test_transaction_boundary.py \
  tests/test_audience_commit_failure_1853.py \
  tests/test_dossier_links_559.py \
  -q
```

实测：**101 passed, 1 warning in 2.26s**；`FOCUSED_EXIT=0`；basetemp 仅 `/tmp/1853-fixer-focused-legal-bt.*`，跑完已删。输出：`/tmp/1853-fixer-focused-legal.txt`。

## 两类结算

| 类 | 边界 | 结算 |
|---|---|---|
| J8-R2（Class1） | 成功构造 GameDB 后必备能力 AttributeError/软探测兼容 | `IN_CLASS_J8R2=0`；knowledge/materials 软兼容已清；证明测已删，改临时变异证明 |
| TEST-PARALLEL（Class2） | 测试复制持久化/回滚或续养退役轻量专属测 | `COPY_ROLLBACK_LOGIC=0`；`RETIRED_LIGHTWEIGHT_TEST=0`；`needs_attention=0` |

## 未结项

- 本两类复扫 0 剩余。
- 功能接线缺口仍归 #1873；本轮不封驳。
- 未跑全量；未合入目标分支。

## commitSha

见本合法性纠正提交（删除证明测 + 更新本回执/ENUM 复扫产物）；不另开纯 hash 戳提交。
