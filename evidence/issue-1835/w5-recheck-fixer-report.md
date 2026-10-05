# #1835 w5 复检回执（fixer · G1–G5 第二提交）

- **工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1835-w5`
- **分支**：`ak-roles/issue-1835-w5`
- **基线提交（须整类复检）**：`096e09951`
- **判词**：`03-1835-judge-a583dd6bd.json` payloads **最末份** G1–G5（前份历史仅参考，不宣称仍未结）
- **派单**：`fix-packet.md`
- **主座反馈**：首轮 enum 收窄、G3 平行预判残留、报告误称前份未结、`git diff HEAD^ HEAD --check` 三处空白

## 过程（如实）

1. 重读派单/末份判词/首轮 `w5-current-fixer-report.md` 与 `full_enum.py`。
2. 核实主座三点：`enum_g2` 只扫 `declaration_dispatch.py`；G3 在调用 `allegiance_change_rejection` 后仍留 `_pending_person_changes_block_event_gate` / `amnesty_conflict_power_ids` 对待落项预判；报告把前份 F1 等写成「仍未结」与末份唯一未结冲突。
3. 按段序：`power` → `person_pre` → `issue` → `person_post`。预判影子无法消费 person_post 实际落账结果；boundary 禁止继续给影子补校验 → **删除副本**，事件门只认已落 DB（含 person_pre 评定），招安互斥预判退出。
4. 全仓 tracked 语义枚举（`/tmp/1835-w5-recheck/enum/full_enum.py`，副本进 evidence）后再按消费者来源分类；不把 AST 清单当测试。

## 互联网确认

| 用途 | 来源 | 做法 |
|---|---|---|
| 全仓 AST 函数体/except 枚举 | [Python ast](https://docs.python.org/3/library/ast.html) | `ast.parse` + except 类型 + 消费者闭包 |
| 持久 JSON 响亮失败 | [SQLite / 既有 `GameDB.parse_engine_payload_json`](https://www.sqlite.org/json1.html) | 腐坏 JSON 上抛；声明脏值走 `DeclarationDataError` |

## 全仓机械枚举（复检）

**命令**：

```sh
export MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false
export MING_SIM_USER_DATA_DIR=/tmp/1835-w5-recheck/user-data
export PYTHONPATH=/Users/akagilnc/WorkSpace/Ming_LLM-1835-w5
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python /tmp/1835-w5-recheck/enum/full_enum.py
```

**产出**：`evidence/issue-1835/w5-recheck/enum-post.txt` + 精简 `enum-post.json`（省略全量 `json.loads` 清单，避免伪证堆）+ `full_enum.py`。

谓词覆盖判词类定义全文：全仓 production Python，不按点名路径/符号白名单收窄。

### G1 成员表（复检后）

| 成员 | 处置 |
|---|---|
| `finalize_persist` 代写执行格/半途国势/无差别停局势 | 首轮已删；复检 AST 确认函数体内无 `execution_outcome` / halfway / `record_dossier_execution` |
| `assess_foundation_tier` | **保留**：#626 承诺反噬触发侧重算（boundary：不扩大废止其他松手） |
| `stop_origin_commitment_ticks` / `apply_persist_revoke_tail` / ADR0056 | **保留**：合法名声与停承诺 |
| `GameDB.cancel_issue` 等其它命中 | **类外/合法消费者**：非「代码代判撤诺世界处置」 |

### G2 成员表（声明→prepare/materialize 来源分流）

| 成员 | 处置 |
|---|---|
| assignment 等分派口 `except DeclarationDataError` | **保留**：只收声明类型化错误 |
| `stage_assignment` stages 脏值裸 `ValueError` | **改为** `DecreeMaterializationValidationError`（声明侧） |
| 惩处读 `issues.target_roster` 腐坏 JSON | **响亮 ValueError**（持久），不被声明 except 吞 |
| `decree` 案卷 `payload_json` `json.loads(...or "{}")` | **改为** `GameDB.parse_engine_payload_json` |
| `affair/delta_section` 裸 `ValueError`→拒收 | **改为**只捕 `DeclarationDataError` |
| `_peek_affair_id` 捕 `TypeError/ValueError` | **改为**只捕 `DeclarationDataError`（解析口已类型化） |
| `_dispatch_rushes` 期限/字段 int 转换→拒收 | **合法保留**：声明字段形状，非持久真源 |
| `parse_affair_declaration` 内 `affair_id` 转换→`DeclarationDataError` | **合法保留**：已是来源分流 |
| 仓内其它领域 `except ValueError`→拒收（army/region 等） | **类外**：非「洗成新声明拒收」接缝；本轮不扩改无关写核 |

### G3 成员表（平行权威）

| 成员 | 处置 |
|---|---|
| `preflight._pending_person_changes_block_event_gate` 及 shadow 预加载 | **删除**；tracker/战略预检调用与 `pending_person_changes_for_gates` 参数同步删 |
| `character.delta_section.amnesty_conflict_power_ids` + `SettlementRun` 字段 + power 段消费 | **删除**（段序上无法消费实际落账；禁止补校验） |
| `identity_title_for_allegiance` 多副本 | **合并**为 `character/apply.py` 模块级唯一真源，供准入与写核共用 |
| `allegiance_change_rejection` | **保留**：仅写核调用，不再喂待落预判 |
| 战略结果 SAVEPOINT 内真实 `apply_person_changes` | **保留**：消费权威实现，非平行政策 |
| `_admit_transit_departure` / `_load_pending_gate_valid_regions` | **保留**：写核与战略 preflight 实读 |
| 专属旧测（pending gate / 招安互斥预判） | **删除**（G4 闭包） |
| `test_rejected_bandit_amnesty_does_not_block_*` 等 | **保留**：仍验证拒收易主后顶层 power 可落 |

### G4 成员表

| 成员 | 处置 |
|---|---|
| pending-gate / amnesty 预判及专属旧测 | **删除**（见上） |
| 首轮已删旧密令抽取等 | 复检无生产复活 |
| enum 初报 `dead_no_consumer` 的同文件 secret_order 助手 | **不机械删除**：同文件实读存在；报告注明闭包须含同文件，避免伪证 |

### G5 成员表

| 成员 | 处置 |
|---|---|
| `pre_settle` 内事件终态/硬触发 | 复检 `in_pre_settle=0` |
| `month_chain._consume_event_gates_after_edicts` | **保留唯一消费点** |
| `docs/SETTLEMENT_FLOW.md` | 已对齐逐旨后 |
| `issues._auto_trigger_seed_issues_in_atomic` docstring 仍写 pre_settle | **改正**为月链逐旨后 |

## 逐类根因摘要

1. **G1**：维持首轮删除；复检无代判关案/国势残留。
2. **G2**：声明错误→`DeclarationDataError`；持久 JSON→`parse_engine_payload_json`/响亮 ValueError；不再用广义 ValueError 把两者糊成声明拒收。
3. **G3**：删除两处待落预判影子与名分规则副本；沿段序用已落结果/权威写核。
4. **G4**：随 G3 清退专属旧测与死参数；不误删同文件仍承重助手。
5. **G5**：维持唯一月链消费点；文档/注释对齐。

## 探针与变异

七 BIN + `MING_SIM_USER_DATA_DIR=/tmp/1835-w5-recheck/user-data` + `PYTHONPATH`：

```sh
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python /tmp/1835-w5-recheck/probes/red_green.py
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python /tmp/1835-w5-recheck/mut/mutate_probes.py
```

- 探针：`ALL_OK True`（G1/G2/G3/G5 符号与真实 settle 行为）→ `evidence/issue-1835/w5-recheck/red-green.txt`
- 变异：装回 amnesty 预判 RED（非法易主仍挡 power）；当前 GREEN；G2 wash→`{}` RED / 当前响亮；G5 pre_settle 清洁 → `mutation.txt` **3/3 PASS**

## 聚焦测试

```sh
env MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false \
  MING_SIM_USER_DATA_DIR=/tmp/1835-w5-recheck/user-data \
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q --tb=line -p no:cacheprovider \
  tests/test_breach_plea_623.py tests/test_commitment_backlash_626.py \
  tests/test_cli_backend.py tests/test_declaration_dispatch_1835.py \
  tests/test_due_review_621.py tests/test_credit_events_628.py \
  tests/test_surcharge_causal_chain_650.py tests/test_person_delta_adapter.py \
  tests/test_month_chain_1847.py tests/test_month_chain_1843.py \
  tests/test_authority_ledger_611.py tests/test_rejection_wiring.py \
  tests/test_effect_origin_558.py tests/test_affairs_1831.py \
  tests/test_population_transfers_649.py tests/test_relation_capture_633.py \
  tests/test_event_trigger_gate.py
```

结果：**584 passed, 1 skipped in 15.03s**。未跑全量。

## Advisor 再审（针对本反馈 + 全类）

- [x] 首轮 enum 收窄已纠正为全仓语义枚举
- [x] G3 不是「同 helper 即唯一结果」；已删待落影子
- [x] 报告不以历史 F* 冒充本派单未结
- [x] 空白：本回执无行尾空白；旧 `w5-current-fixer-report` 三处将在本提交一并清
- [x] 不为保功能加层；招安互斥预判功能缺口按 #1812 可删
- [ ] **不宣称整类已净至不可再审**：G2 仓内其它领域广义 catch、G4 同文件私有助手是否另票清退，仍可能被后续复审点名

## 合法保留 / 剩余阻断

- 合法保留：ADR0056、`assess_foundation_tier`（反噬触发）、月链事件消费、写核 `allegiance_change_rejection`、战略 SAVEPOINT 实调 apply、声明字段形状拒收。
- 功能缺口（不挡本票施工）：同批招安与顶层 `power_updates` 不再互斥预判；同批 post_issue 人物变更不再影子挡 event_pool。移交家族/#1873 记账，不在本票恢复旧影子。
- 历史前份 findings（F1/F5/…）：**仅参考**，末份未列入 unresolved，本回执不宣称其仍未结。

## 施工约束遵守

未 amend/stash/push/PR；未改宪法/Soul/席位；只清理本树证据与 `/tmp/1835-w5-recheck` 自建物；未毁 worker 产出。
