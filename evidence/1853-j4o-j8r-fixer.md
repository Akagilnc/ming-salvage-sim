# #1853 修内司交卷补正：实际事务提交权单一权威 + 必备DB能力兼容残余清退

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1853-w5`
- 分支：`ak-roles/issue-1853-policy-cleanup`
- 上轮交卷：`0efc2b9a330e8852d917876eb8953f7886e60146`（枚举收窄；本轮复核补正）
- **本轮交卷 commit：** `6284e0179af08a3ff4bf4c57c05601e457cafd82`
- 判词真源：`fix-packet.md`；冻结末份 `attachments/10-1853-judge-d81e9db05.json` payload 末份（J4-O / J8-R）
- **未合入目标分支；不 push / 不开 PR；不 amend / 不 stash**

## 上轮后台任务被杀（如实）

| 项 | 事实 |
|---|---|
| 终端 | `terminals/9621.txt` pid **16125**；聚焦 pytest 已跑出约半程点号后停住 |
| 时长 | `running_for_ms≈104274`（~104s）；`exit_code: unknown` |
| 终止方式 | 同会话 `terminals/9622.txt` 显式执行 **`kill 16125`**（默认信号 **SIGTERM**，**不是** `kill -9` / SIGKILL），随后 `pkill -f 'pytest -p tests.conftest tests/test_transaction_boundary…'` |
| 原因 | 操作方判断套件疑似挂起，改跑三则嫌疑单测；**不是**无脑墙钟超时杀进程，也不是 SIGKILL |
| 后续 | 9622 三则单测亦 `exit_code: unknown`（约 34s），未完结 |

## 两类根因与本轮补正

### J4-O 实际事务提交权单一权威

上轮已使 `atomic` 在借用外层 BEGIN 时不抢 COMMIT。本轮另核：借用外层且 `_atomic_rollback_only` 时，旧措辞「事务已整体回滚」与实码（不 rollback）不符 → **如实改措辞**（仅本层开事务时才称已回滚）。

### J8-R 必备DB能力兼容残余清退

上轮回执类二只点名六文件，并把 `materials`/`knowledge` 等**凭文件名**剔出。按类定义全文 + 召对失败重试真实调用链（`decree_forecast`/`session` → `materials` → `knowledge`；`declaration_dispatch`/`urge_lever`/`action_materialize`/`audience_night`），漏项整类修净：直调必备 GameDB 接口；保留业务空态与结算/菜单初始化清理。

---

## 全仓机械枚举（定义全文；完整命令与可核表）

命令与原始命中、成员分类表真源：

- `evidence/1853-j4o-j8r-enum/ENUM_COMMANDS.md`
- `evidence/1853-j4o-j8r-enum/class1-raw.txt` / `class1-members.tsv`
- `evidence/1853-j4o-j8r-enum/class2-raw.txt` / `class2-members.tsv`
- `evidence/1853-j4o-j8r-enum/sql-raw.txt` / `sql-cross-file-dups.tsv`
- 临时诊断输出：`evidence/1853-j4o-j8r-enum/diag_out.txt` + `DIAG_COMMANDS.md`

### 类一谓词（不得收窄为仅 atomic/owns/commit）

`commit` / `rollback` / `BEGIN` / `SAVEPOINT|RELEASE|ROLLBACK TO` / `owns_transaction|connection_owns_transaction` / `in_transaction` / `_commit_suspended|_atomic_depth|_atomic_rollback_only|started_here` / `with atomic(|def atomic`

本轮分类摘要（见 tsv）：权威实现落 `applier.py`；写前归属调用点引用公共真源；其余生产事务位点服从该权威；测试/工具标注。

### 类二谓词（hasattr/getattr/callable + 重复 SQL）

全仓 `hasattr(` / `getattr(` / `callable(` 机械枚举后按语义分类。属类 = 召对/失败呈现/重试真实调用链上「必备 GameDB 能力存在性 → 空结果/跳过」替身分支。

**不属类依据（按职责，非凭文件名）：**

| 命中面 | 依据 |
|---|---|
| `month_chain` hasattr(conn)/快照 | 过月结算供料/快照，非失败呈现/重试接缝 |
| `web_app` month_open_snapshot / candidate.db.conn / restorable / close_night 无 db | 结算或菜单初始化清理（J8-R 明示保留） |
| `agents` agno / `flows` / `db` 内部 / `cli_backend` / `mechanical_tail` / `recommendations` | 非本接缝 |
| `decree_forecast` owner_or_db 形参 | owner vs db 分流，非缺能力→空投影 |
| `store` affair/textual hasattr | store 可缺业务态 |
| 结果/行/exc getattr·hasattr | 非 DB 能力替身 |
| 测试命中 | TEST_annotate |

修后复扫：`IN_CLASS_J8R` 剩余 **0**。

### 属类成员处置（本轮补清）

| 成员 | 处置 |
|---|---|
| `applier.atomic` 借用外层 + rollback-only 异常文案 | **修正**如实措辞 |
| `audience_night._should_commit` getattr(conn,None) | **删** → `db.conn` |
| `declaration_dispatch` hasattr get_secret_order | **删** → 直调 |
| `action_materialize.character_person_names` hasattr conn | **删**（保留 `db is None` 业务空集） |
| `session` 任命 noop / officeholder getattr conn | **删** → `db.conn` |
| `urge_lever` hasattr get_decree_dossier ×2 | **删** → 直调 |
| `materials` / `knowledge` 全链必备 conn 与 GameDB 方法 hasattr | **删** → 直调；保留无夜/空名册/无 store 等业务态 |
| `evidence/1853-retry-cleanup.md`「用户裁定」 | 上轮已改历史派单说明 |

---

## 真实入口临时诊断（七 BIN=false；非永久测试）

完整命令见 `evidence/1853-j4o-j8r-enum/DIAG_COMMANDS.md`；输出见 `diag_out.txt`。

入口：`game` fixture → `create_test_secret_order` → `stage_pending_action(新建)` → `{close_false\|BEGIN\|outer atomic\|none}` → `commit_pending_actions` → `rollback`。

| 模式 | 当前（新绿） | 旧变异（atomic 深度1 总 commit） |
|---|---|---|
| close_false | err=None；rollback 后 old=active, new_n=1, pa=pending | OperationalError no such savepoint；半提交痕迹 |
| begin | 同上绿 | 同上红 |
| atomic / none | 正常提交 | （对照） |

措辞：`FALSE_CLAIM_ROLLED_BACK=False`；`HONEST_BORROW_WORDING=True`。

J8：旧 hasattr 空列表 vs 当前缺 conn `AttributeError` 响亮失败。`METHODS_RESTORED=true`；临时用例与 basetemp 已删。

---

## 测试证据（七 BIN=false；未跑全量）

前缀：
```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false
```

### Python 聚焦（分批；避免上轮整包挂起误杀）

| 批次 | 文件 | 结果 | 墙钟 |
|---|---|---|---|
| A | transaction_boundary, audience_commit_failure_1853, secret_order_isolation_883, audience_translate_1837, web_audience_night_498, dossier_links_559, urge_lever_624 | **120 passed** | 6.91s（real 7.44s） |
| B1 | test_cli_play_turn | **19 passed** | 0.91s |
| B2 | test_menu_lifecycle_drain_396 | **18 passed** | 0.71s |
| B3 | test_material_directory_1830 | **8 passed** | 0.93s |
| B4 | test_web_chat_serialization_393 + test_character_knowledge_489 + test_world_materials_1834 | **72 passed** | 4.63s |

合计聚焦 **237 passed**。临时 basetemp 均已删。

契约/成本：materials/knowledge/cli/session 直调必备接口；夹具沿用现役 GameDB；不新增永久证明测试；不削弱负向。

### Vitest（触及面；已知 #1873）

```text
vitest run src/components/modals.test.tsx src/appDurableWiring.test.tsx \
  -t 'system-layer reply retry|重试后的记录连续读失败' --environment jsdom --no-cache
→ 1 failed | 1 passed | 114 skipped；唯一失败仍为 appDurableWiring:717 连续读失败（#1873）
墙钟 real 2.47s
```

未跑全量。未调真实模型。

## 合法性与复杂度

- 授权：fix-packet 两类未结（J4-O / J8-R）；按类定义全文机械枚举，判词点名非白名单。
- 不新增事务框架/恢复账本/护栏/永久证明测试；临时诊断已清理。
- 复杂度：删调用链替身与双路径；atomic 措辞与行为对齐（减虚假断言）。
- 自查二连：同类型（借用外层抢提交；召对失败重试链 hasattr 含 materials/knowledge）整类扫；引入面未放宽负向追绿。
- 阻断：无前置缺失；已知 vitest 连续读失败仍归 #1873。
