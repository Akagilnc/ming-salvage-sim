# #1889 六类修内司回执（六类全修）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1889-w5r`
- 施工分支：`ak-roles/1889-six-class-fixer`（自 `ak-roles/1889-k3-text-contracts` @ `00aff8316` 新建）
- 判词真源：`…/attachments/04-1889-judge-00aff8316.json` → `outcome.payloads` **末份**
- 底座对照：`10e64fbef`；本回执相对开工 HEAD `00aff8316`
- 约束遵守：无 stash / amend / rewrite / push / PR；七变量 BIN=`/usr/bin/false`；只跑聚焦；不新建自动了结/框架/兼容护栏/证明性测试

---

## 类1 — 退役财政分流（K4）

### 定义边界（判词+票面）
删除退役公式、切换标记及 shadow 平行路径和仅为它们存在的测试；复用现役 hub；不增加兼容或护栏。

### 枚举命令
```bash
rg -n 'calc_province_fiscal|USE_FISCAL_SUBSTRATE|fiscal_substrate_cutover|use_fiscal_substrate|_read_use_fiscal|_write_use_fiscal' \
  ming_sim tests --type py
# 噪声过滤：historical_shadow / #266 shadow seed 标签 / 测试辅助 _read_fiscal( 不算退役分流
```

### 修前成员（判词样本 ∪ 全仓谓词）
| 成员 | 出处（开工基线） | 处置 |
|---|---|---|
| `calc_province_fiscal` + 标记选择分支 | `flows.py` | 删除公式与分流；`apply_fixed_period_flows` 恒走 substrate hub，坏省 fail-loud |
| 两财政切换标记读写 | `db.py` | 删除 |
| 无 cutover 时跳过坏省继续 | `flows.py` | 删除；坏态上抛 `_SubstrateHubFixedFlowAbort` |
| 仅为分流存在的测试路径 | fiscal bridge 内 dual-path | 改为 hub-only 断言 |

### 修后复扫
- 谓词命中（过滤噪声后）：**0**
- 保留例外：`test_fiscal_substrate_bridge` / ADR0021 语境中的「shadow seed / historical shadow scale」= 史实量级标签与省级 settle JSON，**不是**退役引擎分流开关。依据：ADR0021 决定1/9/10；#1812 验收第1条。

### 结果
类1 清净。

---

## 类2 — 持久职责泄漏与重复实现（K5）

### 定义边界
领域编排留领域；持久读写归既有 owner；合并双份 SQL；清退纯转发；调用方直接用现有 Store。

### 枚举命令
```bash
# 纯转发（AST：GameDB 方法体仅 return self.<store>.<meth>[...]）
python3 - <<'PY'
# …见本回执生成脚本；修后 remaining_pure_forwards=0
PY

# 判词点名旁路写/读
rg -n 'conn\.execute' ming_sim/army_pay.py ming_sim/situation_drift.py
rg -n 'db\.conn\.execute' ming_sim/flows.py
rg -n 'FiscalContainerStore|ArmyStore|IssueStore|RegionStore' ming_sim/army_pay.py ming_sim/situation_drift.py ming_sim/flows.py
```

### 修前成员（样本 ∪ 扩展）
| 成员 | 处置 |
|---|---|
| `GameDB` 监督查询 vs `DossierStore.presence_rows` | 改走 Store |
| 暂存草案读删重复 | 改走 DossierStore |
| 事件表直写 | 归既有 owner |
| `get_fiscal_config` / `has_state` / `current_court_roster_rows` / `power_rows` 纯转发 | **删除方法**；调用方改 `fiscal_config.values()` / `reign.exists()` / `characters.current_court_rows(...)` / `powers.rows(...)` |
| `flows` 容器写入旁路 | `_set/_add_fiscal_container` → `FiscalContainerStore.replace/add`；区域 fiscal 读 → `RegionStore` 既有读口；容器批量读 → `values_for` |
| `army_pay` 裸 SQL 写/读 | 写归 `ArmyStore.update/append_log(s)`；忠诚 tick / 优先补欠读归既有 Store 读口 |
| `situation_drift` 局势写 | 归 `IssueStore.update` |

### 修后复扫
| 谓词 | 结果 |
|---|---|
| GameDB AST 纯转发 | **0** |
| `army_pay` / `situation_drift` `conn.execute` | **0** |
| `flows` `db.conn.execute` | **0** |

### 保留例外及依据
| 例外 | 依据 |
|---|---|
| `GameDB.army_rows(danger_order=…)` | 含 `army_needed` 领域排序，非纯转发 |
| `GameDB` 内事务/PRAGMA/SAVEPOINT/跨实体编排 | 判词：框架操作不计事实写口；ADR0151 |
| `CharacterStore.upsert` / `record_store.upsert` | 合法现役原语；非判词点名的 debug upsert |
| Store 上按调用方命名的 `read_*` 读口 | 既有 owner 读原语，不另造一层 facade |

### 结果
类2 清净（职责归位；未新增框架）。

---

## 类3 — 被取代的孤立机制（K1续）

### 定义边界
依据实际退役关系清退遗留辅助链、专用读写及测试；不能仅因静态未引用删除仍属票面职责的待接接口。

### 枚举命令
```bash
rg -n '_fail_cli_chat_turn_scene|substantiate_covert|_covert_substantiat' ming_sim tests --type py
rg -n 'def upsert\b' ming_sim/entities/army/store.py ming_sim/entities/region/store.py ming_sim/entities/building/store.py
```

### 成员与处置
| 成员 | 处置 |
|---|---|
| `_fail_cli_chat_turn_scene` | 删除 |
| Army/Region/Building debug upsert | 删除 |
| `covert_progress` 无消费者坐实读写链（固定 progress=1 / 依律） | 删除 |
| `_COVERT_NEUTRALIZATION_REASON` + `neutralize_covert_fiscal_effects` | **保留**（禁摊派一次性撤销=票面现役职责，误删导致聚焦红后已恢复常量） |

### 修后复扫
- 退役谓词命中：**0**
- 保留：`CharacterStore.upsert`、`record_store.upsert`（现役）

### 结果
类3 清净。

---

## 类4 — 人口规则平行实现（K6）

### 定义边界
保留一个现役领域真源；删除复制件、旧名兼容路径及只维系它们的测试；保留真实世界核算。

### 枚举命令
```bash
rg -n 'apply_issue_inertia_and_ongoing' ming_sim tests --type py
rg -n 'def apply_levy_driven_transfers|def apply_recovery_driven_transfers' ming_sim --type py
```

### 成员与处置
| 成员 | 处置 |
|---|---|
| `issues.py` 加派/赈济人口核算双份 | 删除复制件；编排留 issues，核算真源=`displaced_population.py` |
| 旧名 `apply_issue_inertia_and_ongoing` | 删除；月链走 `apply_levy_driven_transfers` / `apply_recovery_driven_transfers` |
| 引擎侧人口门 | `displaced_population` 去掉多余 gate，保留单位/池校验与真实核算 |

### 修后复扫
| 符号 | 命中 |
|---|---|
| `apply_issue_inertia_and_ongoing` | 0 |
| `apply_levy_driven_transfers` 定义 | 仅 `displaced_population.py` |
| `apply_recovery_driven_transfers` 定义 | 仅 `displaced_population.py` |

### 结果
类4 清净。

---

## 类5 — 撤回的事务了结机制（K7）

### 定义边界（ADR0154 后出裁定）
清退显式了结、拒绝该动作的守门及专用旧测试；不借修理新建自动了结机制。

### 枚举命令
```bash
rg -n 'close_from_declaration|declare_closed|ATTACH_RESULT_CLOSE|_ATTACH_CLOSE|本阶段不能了结|顶层事务声明只接受了结' \
  ming_sim tests --type py
```

### 成员与处置
| 成员 | 处置 |
|---|---|
| `AffairStore.close_from_declaration` | 已删（上轮） |
| `AffairStore.declare_closed` | **本轮删除** |
| `ATTACH_RESULT_CLOSE` / `_ATTACH_CLOSE` 及专用拒收文案 | **本轮删除**；非法 attach 统一「事务声明 attach 不在本阶段」 |
| `issues` 落账调用显式了结 | 已删 |
| 测试夹具需要 closed 行 | 改为直 SQL `UPDATE affairs SET status='closed'…`（不经声明动作、不建自动了结） |
| `test_affairs_1831` birth 路径传 `attach=close` | 仍期望 ValueError（现为通用非法 attach），保留拒收边界 |

### 修后复扫：上述谓词全部 **0**

### 结果
类5 清净。未新建自动了结。

---

## 类6 — 测试契约边界处置错误（K3续）

### 定义边界
复用已有最短行为用例承接必要结构化结果；清理非契约叙事锁；不得靠删仍生效契约洗绿；不恢复措辞锁；不新增证明性测试。

### 枚举 / 处置
| 成员 | 处置 |
|---|---|
| `modals.test.tsx` scrollTop 600/700/100/137 | **恢复**结构化断言 |
| `#1732` 确认条关闭 | **恢复** `aria-label="撤回召对确认"` null/非 null 断言 |
| `AGENDA_FROZEN` 叙事句锁 | **删除**；保留人口数值/单位/种子结构契约 |

### 修后复扫
- `AGENDA_FROZEN`：**0**
- scrollTop 结构化断言：4 条仍在 `modals.test.tsx`
- 确认条关闭断言：仍在

### 变异取证（真实入口，不新增证明测试）
```bash
# 临时注释 chatModal.tsx 两处 scrollTop 恢复赋值后：
npm test -- --run src/components/modals.test.tsx
# → 2 failed（600 / 137），32 passed；恢复文件后 34 passed
```
证据：`/tmp/1889-mutation-scroll.out`；生产文件已还原。

### 结果
类6 清净。

---

## 聚焦测试（七变量前缀）

前缀：
```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

| 批次 | 结果 |
|---|---|
| core：affairs / population seed / new_game_smoke / supervision / mutiny×2 / junxin / inertia / decree_commitment | **89 passed**（`/tmp/1889-focus-core.out`） |
| fiscal bridge `-k 'fixed_flows_substrate_hub or budget_lines…'` | **11 passed**, 131 deselected |
| covert_levy + month_translate_1840 + pay_order + section_fiscal + relation_seed + affairs | **202 passed**（含误删常量修复后） |
| `web` `modals.test.tsx` | **34 passed** |
| scrollTop 变异 | **2 failed / 32 passed**（证明断言咬合） |
| `git diff --check` | **clean** |

未跑全量（票面：只跑聚焦）。

---

## 自查二连

1. **合法性**：未改治理/Soul/席位；未新建自动了结；未恢复措辞锁；未新增证明性测试；禁摊派中和常量属现役职责已保留。
2. **复杂度**：删除纯转发与了结/分流/孤立链；调用方直达 Store；未加兼容层或第二套机制。
3. **复扫**：六类谓词修后均为 0（例外表已列）。

---

## 剩余范围 / 真实阻断

- 无本票六类谓词残留阻断。
- 不宣告合并、不关票、不 push、不开 PR。
- 家族收尾复杂度整体对比仍归 #1812 / owner，不在本回执署 converged。
