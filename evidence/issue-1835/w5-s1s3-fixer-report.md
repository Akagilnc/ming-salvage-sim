# #1835-w5 S1/S2/S3 修内司施工报告

- **工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1835-w5`
- **分支**：`ak-roles/issue-1835-w5-s1s3-fixer`（动手前自 `ak-roles/issue-1835-w5-s1s4-fixer` HEAD 新开）
- **基线 HEAD（施工前）**：`356eb5f128518ba39936bf9d4ab07fa6f65a2ac7`
- **派单**：`01a10a10-85d2-7837-a403-5700d62a6461@fixer/fix-packet.md`
- **冻结判词**：`attachments/05-1835-judge-356eb5f12.json`（**payloads 末份**唯一界定未结类；前份仅参考）
- **未结类（末份原文）**：S1 canonical 拒收迁约；S2 领域准入平行权威；S3 退役协议附属物／错约说明／重复测试
- **不宣称 merge／关票**

## 互联网确认（动手前，不自造机制）

| 用途 | 来源 | 采用的现成做法 |
|---|---|---|
| 删平行领域校验 | [DRY Best Practices](https://bestpractice.unisbadri.com/en/engineering_principles/dry/)；[StackExchange: validation duplication](https://softwareengineering.stackexchange.com/questions/461291/avoiding-validation-logic-duplication-across-app-layers) | 业务规则只留一处权威；预检删副本，复用写核拒收 |
| 失败通道单形 | [dry-python returns Result](https://github.com/dry-python/returns) 思路；仓内既有 `RejectedItem` | 失败只走 typed 拒收，不并行 dict 失败回声 |
| AST 全仓枚举 | [Python `ast`](https://docs.python.org/3/library/ast.html) | 函数体源片段 + 关键字谓词，不点名白名单收窄类边界 |

## 红-capable（diagnosing-bugs）

七变量前缀 + `MING_SIM_USER_DATA_DIR=/tmp/1835-w5-s1s3/user-data`，探针脚本见临时目录；结果附件：

- 修前：`evidence/issue-1835/w5-s1s3-red-before.json` — `S1_RED/S2_RED/S3_RED` 皆 true  
  - S2 样本：写核 `pay_source_region`→`nanzhili`、拒收 0；战略预检同载荷报「非法军队字段：pay_source_region」
- 修后：`evidence/issue-1835/w5-s1s3-red-after.json` — 三类 GREEN；预检与写核对齐（`S2_preflight_error=""`）

## 枚举谓词（覆盖类定义全文，非点名样本）

### S1：canonical 拒收生产与消费迁约未完
- 同函数内既产 `RejectedItem` 又产／回声 `rejected: True` dict
- 消费端同时扫 `RejectedItem` 与 applied dict 的 `rejected`／`invalid`
- 保留：`invalid_enum` 停续语义（月链仍 raise + `secret_orders_supply_invalid`）

### S2：领域准入仍有平行权威
- 预检在调用领域写核前重复字段白名单／整数／势力／炮转移准入
- 与写核结果分歧即成员；事件整封归属（写核拒收→整封失败、noop）与领域准入分开

### S3：退役协议附属物、错约说明及重复测试
- 退役元数据特免（`_module_rejections`）
- 现行说明仍要求 reason 战役名锚点（与显式 `event_id` 契约抵触）
- helper-only／无独立必要价值的迁约测试（真实入口负向案已承接者）

枚举命令：`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python` 跑临时 `enum` 脚本（产物拷贝入仓）。  
附件：`w5-s1s3-enum-pre.txt`／`w5-s1s3-enum-post.txt`

## 成员表与处置

### S1

| 成员 | 处置 | 依据 |
|---|---|---|
| `covert_progress._apply_investigation_selection` dict 回声 | **改为**返回 `RejectedItem` | 判词正确性 C4；canonical 单通道 |
| `apply_monthly_covert_actual_progress` 双写 applied+rejections | **删除** dict 回声分支；只 append RejectedItem | 同上 |
| `month_chain` Phase-3 双形扫描 | **删除** applied `.get("rejected")` 扩展；只认 `RejectedItem.category==invalid_enum` 停续 | 保留 #1846 停续 |
| `due_review` 本地 `{"rejected": True}` 待办结果 | **保留** | 非结算 dual-shape；无 RejectedItem 双扫消费者 |
| `power/delta_section` `positive_ms_rejected` 局部 bool | **保留** | 非 dict 失败回声；随即产 RejectedItem |

### S2

| 成员 | 处置 | 依据 |
|---|---|---|
| 战略预检字段白名单（非法地区／军队字段） | **删除** | 写核权威；pay_source 分歧样本根因 |
| `_int_delta_error` 整数平行准入 | **删除** | 复用写核拒收 |
| `controlled_by` → `powers WHERE id` 平行准入 | **删除** | 复用写核拒收 |
| `cannon_transfer_to` 预检预判 | **删除** | 复用 `apply_army_delta_with_cannon_transfer` |
| 实体缺失早拒 | **删除早拒**；缺行时不组快照，交写核 | 不清平行准入 |
| 写核拒收→整封失败 | **保留** | 事件整封归属 |
| noop 快照／`_reject_landed_or_unchanged` | **保留** | 整封「须有真实变化」；文本仍不计 noop（R3） |
| `_jisi_outcome_profile_error` | **保留** | 结局标签与战果矛盾＝信封规则，非领域准入副本 |

### S3

| 成员 | 处置 | 依据 |
|---|---|---|
| `sanitize_delta_shape` `_module_rejections` 特免 | **删除**；与未知顶层字段同形拒收 | 完整性 C2 |
| `docs/DELTA_SCHEMA.md` reason 战役名锚点说明／示例缺 `event_id` | **对齐**显式 `event_id` 契约 | 正确性 C3；`month_translate`／`_effect_event_ids` |
| `test_retired_legacy_person_keys_normalize_to_nothing_in_the_person_stream` | **删除** | helper-only；真实入口案 `test_retired_legacy_person_keys_are_rejected_per_section_not_silently_dropped` 已承接 |
| `test_invalid_investigation_declaration_is_rejected_not_zero_effort` | **迁约**断言到 `rejections`/`RejectedItem` | 保留负向契约，不盯旧 dict 回声 |
| 复扫命中的注释行／「不得靠 reason 战役名」负向说明 | **保留** | 非特免、非错约；谓词假阳性 |

## 复扫

- S1 可行动残留：**0**；保留 4（due_review×3 + power 局部 bool）有依据  
- S2 残留：**0**  
- S3 残留：**2**（注释提及键名；已对齐文档中的负向「不得靠 reason 战役名」句）— 非未结缺口  

## 聚焦测试（实测）

```sh
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  MING_SIM_TRACE=0 PYTHONDONTWRITEBYTECODE=1 \
  MING_SIM_USER_DATA_DIR=/tmp/1835-w5-s1s3/pytest-user \
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/1835-w5-s1s3/pytest \
  tests/test_secret_order_payoff_1504.py \
  tests/test_month_chain_1847.py \
  tests/test_mutiny_noop_whitelist_319.py \
  tests/test_person_delta_adapter.py \
  tests/test_event_trigger_gate.py \
  tests/test_enrich_list_guards.py \
  tests/test_declaration_dispatch_1835.py \
  tests/test_rejection_wiring.py
```

结果：`426 passed, 1 skipped in 9.18s`（见 `w5-s1s3-focused-tests.txt`）。未跑全量、未打真模型。

## 测试变更契约／成本

| 项 | 说明 |
|---|---|
| 契约 | 查案无效只出现在 `RejectedItem`；月链仍 `invalid_enum`→停续；战略预检不再平行拒写核会收的字段；未知顶层含退役 `_module_rejections` 一律拒收；DELTA_SCHEMA 要求显式 `event_id` |
| 净增减 | 生产约 −70 行量级（预检删准入）；删 1 helper-only 测；1 案迁约断言 |
| 时长 | 聚焦约 9.2s |

## 合法性自查

- 未新增兼容桥／政策表／预演框架／护栏／恢复机制／证明性测试  
- 未 amend／stash／push／开 PR；未改治理规则或席位宿主配置  
- 自建物仅工作树 `evidence/issue-1835/w5-s1s3-*` 与 `/tmp/1835-w5-s1s3/`  
- 功能缺口（判词正确性 C1/C2 炮转移嵌套／撤销 ID）仍按 #1812 留 #1873，本局不猜补  

## 未结／阻断

- 本局授权 S1/S2/S3 施工面：复扫无行动残留  
- 不以 commit 冒称已 merge／关票  
- #1873 功能登记调用方补记（本报告不声称已登记）  
