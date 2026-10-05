# #1835 w5-current 修内司回执（fixer · G1–G5）

- **工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1835-w5`
- **分支**：`ak-roles/issue-1835-w5`
- **判词**：`03-1835-judge-a583dd6bd.json` payloads **最末份**（前份仅参考）
- **派单**：`fix-packet.md` → 未结五类 G1–G5
- **诊断法**：`~/.agents/skills/diagnosing-bugs/SKILL.md`（先秒级红-capable，再假说）
- **法规**：未新增证明测试；用既有行为测试 + `/tmp` 真实入口探针红绿 + 进程内旧逻辑变异。理由：共享硬规则禁止为本票新写证明性测试；探针与变异均落系统临时目录，不进仓测套。

## 互联网确认（动手前，不新造机制）

| 用途 | 来源 | 采用的现成做法 |
|---|---|---|
| 全仓重复函数体枚举 | [Python `ast` 文档](https://docs.python.org/3/library/ast.html)；[SO: identical ASTs](https://stackoverflow.com/questions/59142740/do-identical-abstract-syntax-trees-guarantee-the-same-behaviour)；[SO: hash function body](https://stackoverflow.com/questions/49998161/how-can-i-hash-the-body-of-a-python-function) | `ast.parse` → 规范化 docstring/名 → `ast.dump(..., annotate_fields=False)` → sha256 分组 |
| 持久 JSON 响亮失败 | [SQLite JSON1](https://www.sqlite.org/json1.html)；[Transaction](https://www.sqlite.org/lang_transaction.html) | 腐坏 JSON 不得静默成空；复用既有 `GameDB.parse_engine_payload_json`；事务失败须上抛而非洗成声明拒收 |

未引入 pydry 等新依赖；枚举脚本仅 `/tmp` + 本回执附件副本。

## Phase 1–2：红-capable 入口（diagnosing-bugs）

命令（七 BIN 前缀 + 临时 USER_DATA_DIR）：

```sh
export MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false
export MING_SIM_USER_DATA_DIR=/tmp/1835-w5-current/user-data
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python /tmp/1835-w5-current/probes/red_capable.py
```

**修前 RED**（`evidence/issue-1835/w5-current/red-before.txt`，elapsed ~秒级）：

- G1：`execution_outcome=failed`、`dossier_status=closed`、`minxin_delta=-3`、`situation_status=dropped` → 四 RED 全亮
- G2：腐坏 `payload_json='['` → 正常返回 + `washed_invalid_shape` → 两 RED 全亮
- G5：`pre_settle` 内仍调 `apply_event_terminal_states`/`auto_trigger_seed_issues` → `RED_dual_path`

**可证伪假说（3–5）与验证**

| # | 假说 | 验证 | 结果 |
|---|---|---|---|
| H1 | `finalize_persist` 仍代写执行格/半途国势/无差别停局势 | 探针 G1 + 读 `breach_plea.finalize_persist` | **成立**（修前）；删 `_apply_halfway_national_setback`、停 tick 过滤 never/非承诺 |
| H2 | `finalize_persist` 未传 `close_target=False`，0056 默认关案 | 变异强制 `close_target=True`→closed；传 False→executing | **成立** |
| H3 | 新声明路径把持久 JSON 故障洗成 `invalid_shape` | 腐坏 pending payload + `dispatch_declaration` | **成立**；改 `DeclarationDataError` 分流 + `parse_engine_payload_json` |
| H4 | 人物易主准入多处平行政策 | AST/对照 preflight·delta·apply | **成立**；提 `allegiance_change_rejection` 唯一权威 |
| H5 | `pre_settle` 复活逐旨前事件消费，与月链双路径 | AST 扫 `decree.pre_settle` + docs L5 | **成立**；删调用、同步 docs |

**修后 GREEN**（`red-after.txt`，0.627s）：G1–G5 全部 `RED_*=false`；G2 响亮 `ValueError: pending_actions.payload_json 腐坏 JSON`；皇威 -5 为合法 ADR0056（民心 0）。

## 全仓机械枚举

**命令**：`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python /tmp/1835-w5-current/enum/full_enum.py`
**产出**：`evidence/issue-1835/w5-current/enum-post.txt` + `enum-post.json` + `full_enum.py`（副本）

谓词覆盖判词类定义全文（非点名样本）：AST 函数体哈希、rg 形状、消费者闭包。

### G1 成员表（修后残留扫描）

| 成员 | 处置 |
|---|---|
| `_apply_halfway_national_setback` | **删除**（修前成员） |
| `finalize_persist` 代写 `execution_outcome` / 分档分支 | **删除**；只留 0056+停承诺 |
| `assess_foundation_tier` | **保留**：#626 承诺反噬触发侧重算（「不扩大废止其他松手机制」） |
| `stop_origin_commitment_ticks` / `apply_persist_revoke_tail` | **保留并收窄**：只停带 `commitment_kind` 且非 `cancellable=never` |
| `tracker`→`finalize_persist` 两 call site | **保留**：合法坚持撤入口 |
| ADR0056 `breach_decree_dossier` | **保留**；`close_target=False` |

### G2 成员表

| 成员 | 处置 |
|---|---|
| `declaration_dispatch` assignment `except (…ValueError)` 洗声明 | **改为**只捕 `DeclarationDataError` |
| `action_materialize` / `_pending_action_payload` `json.loads(...or "{}")` | **改为** `GameDB.parse_engine_payload_json` |
| `_dispatch_promises` 两处 raw loads | **同上** |
| `_peek_affair_id` / 催办期限 TypeError→invalid_shape | **保留**：声明形状错误（非持久真源） |
| 仓内其它 `json.loads`（db dossier 等） | **类外/非新声明拒收口**：本类边界=「洗成新声明拒收」；未扩改无关读路 |

### G3 成员表

| 成员 | 处置 |
|---|---|
| preflight / character delta / apply 平行易主政策 | **合并**→`allegiance_change_rejection` |
| `surcharge._surcharge_population_pool_members` 与 `displaced_population` 同体 | **删除副本**，import 权威 |
| `credit_event._placed` 与 `run._stored` | **删除副本**，reuse `_stored` |
| `due_review`/`credit_events` 独立 dossier 正则 | **删除**，reuse `breach_plea.parse_dossier_id` |
| `parse_backing_dossier_id` / `_item_dossier_id` | **保留**：异语义（backing 响亮 / 多键抽取） |
| agents/context `bind_content`、store `__init__` 等同体 | **类外保留**：非领域准入/业务规则平行权威 |

### G4 成员表（消费者闭包后 defs=0）

已删：`_extract_secret_order` + 三专属旧测；decree 五旧私有根；`_apply_authority_change_item`；flows 三省函数；`_capture_one_interaction`；`_target_active_officeholder`；`target_progress_units`；`current_audience_scene`；`issue_applied_person_changes`；`victory_status_of`；`SettlementRun.person_changes` 字段 / `stamped_by_origin` / `rejected_origin_ids` 字段；character `phase` 死参。

**保留**：`secret_order_can_land`（`declaration_dispatch` 现役消费者）；公开领域能力未接线者未机械删除。
注：枚举里 `person_changes`/`stamped_by_origin` 的 Name 命中是局部变量/其它 API 键名，非 `SettlementRun` 死字段。

### G5 成员表

| 成员 | 处置 |
|---|---|
| `decree.pre_settle` 内 `apply_event_terminal_states` / `auto_trigger_seed_issues` | **删除调用** |
| `month_chain._consume_event_gates_after_edicts` | **保留唯一消费点** |
| `docs/SETTLEMENT_FLOW.md` L5 | **同步**为逐旨后唯一消费 |
| `pre_settle` docstring | **同步**去掉「auto_trigger 硬立」误述 |
| 合法非人事件运算 / seed 硬触发本体 | **保留**（只搬家接点） |

## 逐类根因处置摘要

1. **G1**：删代码分档代判与半途国势；0056 名声保留；关案权还模型；never 局势不停。
2. **G2**：新声明 vs 持久故障按既有类型化错误分流；腐坏 payload 响亮 ValueError。
3. **G3**：人物准入单权威；人口池/段合并/dossier 解析删合副本；不新框架。
4. **G4**：按闭包删旧机制与专属旧测；保留 `secret_order_can_land`。
5. **G5**：撤逐旨前双跑；归世界段接缝；文档对齐。

## 旧逻辑变异（进程内，不改工作树持久态）

`/tmp/1835-w5-current/mut/mutate_probes.py` → `evidence/issue-1835/w5-current/mutation.txt`：**6/6 PASS**

- G1 force `close_target=True` → closed RED；当前 → executing GREEN
- G2 当前 raise GREEN；except→`{}` 变异 RED
- G5 当前 pre_settle 无事件调用 GREEN；注入双调用 RED

## 聚焦测试

```sh
env MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false \
  MING_SIM_USER_DATA_DIR=/tmp/1835-w5-current/user-data \
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q --tb=line \
  tests/test_breach_plea_623.py tests/test_commitment_backlash_626.py \
  tests/test_cli_backend.py tests/test_declaration_dispatch_1835.py \
  tests/test_due_review_621.py tests/test_credit_events_628.py \
  tests/test_surcharge_causal_chain_650.py tests/test_person_delta_adapter.py \
  tests/test_month_chain_1847.py tests/test_month_chain_1843.py \
  tests/test_authority_ledger_611.py tests/test_rejection_wiring.py \
  tests/test_effect_origin_558.py tests/test_affairs_1831.py \
  tests/test_population_transfers_649.py tests/test_relation_capture_633.py
```

日志：`evidence/issue-1835/w5-current/focused.txt`
结果（实查）：**451 passed, 1 skipped in 10.51s**（wall ~11.0s）。未跑全量。

过程如实：曾 collection ERROR（残留 `@parametrize context_mode`）→ 删除；曾 1 failed（AC2 仍期望全国余波 count=1）→ 按批准边界改断言为 0，**未恢复旧行为**。

## 施工后质量/合法性复检

- 探针 G1–G5 GREEN；变异 6/6；聚焦绿。
- 未恢复静默默认；未扩大松手；未新机制/政策表。
- 未改仓级宪法 CLAUDE.md / Soul；未 stash/amend/push/PR。

## 未结 / 缺口 / 红灯（如实）

- 本回执覆盖判词末份 **G1–G5**。前份 findings（F1/F5/…）**仅历史参考**，末份未列为未结，此处不宣称其仍未结。
- 首轮提交 `096e09951` 经主座核查后需整类复检；见 `evidence/issue-1835/w5-recheck-fixer-report.md`。
- 家族复杂度/全量 CI/真宿主验收留家族收尾（#1812）。

## Advisor 自查

- [x] 先红入口再假说再改
- [x] 整类枚举 + 复扫 + 保留项说明
- [x] 共同根因删合，不点名补丁式放过
- [x] 七 BIN 前缀；临时 USER_DATA_DIR；只聚焦
- [x] 不为保绿恢复旧行为
- [x] 报告含命令、成员表、变异、耗时、未结项
- [x] 互联网来源已记
