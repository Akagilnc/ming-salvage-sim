# #1853 修内司下一轮回执：T1 提交权手抄归并 + T2 必备能力直调

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1853-w5`
- 分支：`ak-roles/issue-1853-policy-cleanup`
- 封驳原文真源：pi session `.../01a10964-3d95-702e-b546-d696495ead65@fixer/session/session.jsonl` 最新 user 消息（line=43，`status=continue`，findings T1/T2 全文）
- 判词/票面：`fix-packet.md` + `attachments/10-1853-judge-d81e9db05.json`（末份）
- 基线（本轮施工前 HEAD）：`372bb253d796a5757dd894afcd1c210e4fe49e9c`
- **本轮实现 commit：** `3cc8901fbc615d22b3acbf71faa1d162905b70d5`
- **回执文档 HEAD：**
- 未合入目标分支；不 push / 不开 PR；不 amend / 不 stash；未调交卷工具

## 封驳原文要点（不得以摘要当判词；此处仅索引）

完整 JSON 见 session line=43。两类未结边界原文：

1. **实际事务提交权单一权威**：全仓生产代码中判定「本调用方是否有权真提交」的所有谓词和写口；手抄 `_commit_suspended`/`_atomic_depth` 组合均在类内；归并到 `connection_owns_transaction` / `GameDB.owns_transaction`，不造新函数。
2. **必备DB能力兼容残余清退**：必备 GameDB 属性/方法的 hasattr/getattr/callable，缺失即跳过；含无条件 affairs/textual_facts；不能凭文件职责排除；真实业务空态须逐点证据。

## 上轮虚假服从标签之纠正

上轮 `evidence/1853-j4o-j8r-enum/class1-members.tsv` 把手抄 `pause_depth_flags` 标成「服从权威」而未逐点核语义；`class2-members.tsv` 凭「过月结算职责」把 month_chain 等剔出本类。本轮按封驳边界重枚举，见：

- `evidence/1853-next-enum/ENUM_COMMANDS.md`
- `evidence/1853-next-enum/class1-raw.txt` / `class1-members.tsv`
- `evidence/1853-next-enum/class2-raw.txt` / `class2-members.tsv`
- 临时诊断：`diag_out.txt` + `DIAG_COMMANDS.md`

### 类一复扫摘要

| class | 计数 | 含义 |
|---|---|---|
| AUTHORITY_predicate/impl/call/delegate | 19 | applier 真源 + GameDB 委托 + atomic 实现 |
| IMPORT | 10 | 导入权威符号 |
| PROD_uses_authority | 87 | 生产写口写前捕获或直调权威 |
| COMMENT_only | 3 | 注释提及 |
| **PROD_HAND_COPY_REMAINING** | **0** | 手抄提交判据已清 |

### 类二复扫摘要

| class | 计数 |
|---|---|
| NOT_CAPABILITY_SHIM | 542 |
| **IN_CLASS_J8R_REMAINING** | **0** |

## T1 处置（逐点语义）

写后不能直接调用 `owns_transaction()`（自身 DML 使 `in_transaction=True` → 权威恒 False）。统一为 **写前捕获**（与 affair/textual_fact store 同形）：

```text
owns = db.owns_transaction()  # 或 connection_owns_transaction(conn)
# … DML …
if owns:
    conn.commit()
```

### 封驳点名样本 → 处置

| 位点 | 旧语义 | 新语义 |
|---|---|---|
| db.py ~20 处手抄 not suspended∧depth==0 或仅 depth / 仅 suspended | 互不一致；BEGIN 下 depth-only 会抢提交 | 写前 `owns_transaction()`；`_commit_dossier_write(commit, *, owns_transaction=)` |
| decree.py:927/989 | 仅看 depth | `not db.owns_transaction()` / `db.owns_transaction()` |
| audience_translation / session / audience_night._should_commit | 手抄组合 | `_should_commit`→`connection_owns_transaction`；各写口写前缓存 |
| covert_progress ×3、flows 财政 atomic 入口、month_chain reload、backup_to、applier runtime callback | 手抄 flags | 归并权威 |
| applier atomic / _SuspendableConnection | 权威实现 | **保留**（非手抄副本） |

### `_should_commit` 例外说明（封驳要求）

旧注释称「in_transaction 恒 False」与实测相反（写后恒 True）。已消除另写判据：改为权威函数 + 写前捕获，不再维持手抄组合。

## T2 处置

| 成员 | 处置 | 业务空态保留依据 |
|---|---|---|
| month_chain conn / list_pending_decisions / get_month_open_snapshot / get_decree_dossier | 直调 | 查询空表/无 settled 行 → 空列表（表存在、方法必备） |
| mechanical_tail.list_turn_reports；_resolve_context_turns | 直调 | 无月链表行 → `[]` |
| web_app capture/clear_month_open_snapshot / conn / restorable probe | 直调；保留 `db is None`/`state is None` | 无 game/session 时跳过（初始化/替身空态，非缺方法） |
| db.require_backing_dossier_id get_decree_dossier | 直调 | 案卷不存在 → ValueError（既有） |
| materials affairs.affair_id_for_issue/get/list_open；textual_facts | 直调 | 无挂靠 issue → 0；无 open affair → `[]`；KeyError 跳过单 id |
| cli_backend / recommendations / decree.input_brief | 直调；保留 `db is None` | 无 db 的草稿路径；list_open 空 → `""` |
| flows finally hasattr scratch attrs | **保留** | 可选运行时划痕属性清理，非必备接口缺失→空结果 |

## 真实入口临时诊断（七 BIN=false；非永久测试）

命令见 `evidence/1853-next-enum/DIAG_COMMANDS.md`；输出 `diag_out.txt`。

| 诊断 | 结果 |
|---|---|
| 写前捕获 vs BEGIN 下手抄冲突 | `DIAG_T1_OK`；文档化 hand=True 而 owns=False |
| `stage_pending_action` + outer BEGIN → rollback | 暂存被擦除，未抢提交 |
| `stage_pending_action` + outer atomic 异常 | 随外层回滚 |
| 自有连接 stage | 正常落盘 |
| 必备方法直调 | `DIAG_T2_OK METHODS_PRESENT=true`；缺方法 AttributeError |

临时文件仅 `/tmp/1853-next-*`，已删。

## 聚焦测试（七 BIN=false；未跑全量）

```bash
MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false \
python -m pytest -p tests.conftest \
  tests/test_transaction_boundary.py \
  tests/test_audience_commit_failure_1853.py \
  tests/test_advance_paths_atomic.py \
  tests/test_pre_settle_transaction.py \
  tests/test_month_open_snapshot_1234.py \
  tests/test_world_materials_1834.py -q
```

实测：**81 passed, 1 skipped**（约 5.3s）。

## 自查二连

1. **同类型**：全仓复扫手抄 flags → 0；必备能力 hasattr/getattr 缺失跳过 → 0；tsv 不再用「服从/非本接缝」虚标。
2. **引入 bug**：写后改调 owns 已避免（一律写前捕获）；backup_to 在未提交脏写时改为响亮拒绝（调用方须先 commit/rollback）；reload 在外层 BEGIN 下亦拒绝（较旧 depth-only 更严、与权威一致）。
