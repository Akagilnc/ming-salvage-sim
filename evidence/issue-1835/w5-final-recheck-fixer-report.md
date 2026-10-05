# #1835 w5 第三轮最终复检回执（fixer · G1–G5）

- **工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1835-w5`
- **分支**：`ak-roles/issue-1835-w5`
- **基线（复检前 HEAD）**：`80bfdbfa2`
- **判词唯一末份**：`03-1835-judge-a583dd6bd.json` payloads 最末份 G1–G5
- **派单**：`fix-packet.md`
- **上轮问题纠正**：
  1. G2 不得以 army/region 路径判类外；须逐 catch 读 try 体定来源。
  2. G4 不得漏同文件 `ast.Name`/`Attr`；漏计=假证，须改脚本重跑，不得报告附注绕过。
  3. 不得以「可能以后点名」收场；整类处置表写完。

## 枚举命令（纠正后）

```sh
export MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false
export MING_SIM_USER_DATA_DIR=/tmp/1835-w5-final/user-data
export PYTHONPATH=/Users/akagilnc/WorkSpace/Ming_LLM-1835-w5
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python /tmp/1835-w5-final/enum/full_enum.py
```

产出：`evidence/issue-1835/w5-final-recheck/`（`full_enum.py`、`enum-post.txt/json`、处置 TSV、探针、聚焦日志）。

**G4 脚本修正**：`consumer_closure` 改为全仓 AST `Name`/`Attribute`，**同文件调用计入** `prod_refs`/`same_file_refs`；不再用「仅跨文件」伪死。

修后枚举摘要：

| 类 | 计数 |
|---|---|
| G1 | 26 shape hits |
| G2 | washes_reject=48；in_decl_path broad=53；json_loads 其余 |
| G3 | identical_body=4；named_residual=3；policy_shape=24 |
| G4 | dead_no_consumer=0；test_only=0；live=28；unread_run_field=0 |
| G5 | in_pre_settle=0 |

## G1 处置

| 成员 | 处置 | 依据 |
|---|---|---|
| `finalize_persist` | **已净** | 函数体无 `execution_outcome` / halfway / `record_dossier_execution`；探针 PASS |
| `assess_foundation_tier` / ADR0056 / `stop_origin_commitment_ticks` / `apply_persist_revoke_tail` | **合法保留** | boundary：保留名声记账与其它松手；不扩大废止 |
| `HALFWAY_SETBACK_EVENT_ID` | **合法保留** | 承诺反噬等松手引用的公开常量；非撤诺代判 |
| 其余 `cancel_issue` / verdict / tracker 命中 | **类外/合法消费者** | 非「代码代判撤诺世界处置」 |

## G2 完整逐成员处置（broad_except_washes_reject）

全表见 `w5-final-recheck/g2-wash-disposition.tsv`（48 行）。摘要：

| 来源分类 | 数量 | 处置 |
|---|---|---|
| try 仅转换新声明/delta 项字段 → 拒收/`DeclarationDataError` | 45 | **KEEP**：army/region/faction/power/tracker 等 int/strict_int 形状口；**不按路径判类外**，按 try 体数据来源保留 |
| `commit_pending_actions` / `_commit_conversational_draft` `except Exception` | 2 | **KEEP**：非 `Declaration*` 已 `raise`；声明类型错误→failed；来源分流已在位 |
| wash_needs_manual_read 复读后实为字段形状 | 含于上列 | `_normalize_directive_*` / tracker / buildings：try 内无 persist 读写 |

**本轮产品修**：

| 成员 | 原状 | 处置 |
|---|---|---|
| `declaration_dispatch` 入册 `loyalty` | 在场脏值 `int()` 失败→静默 55 | **FIX**：缺席→55；在场脏→`invalid_shape` 拒收 |
| `urge_lever.resolve_host_character` 读 `participant_roster`/`participants`/人设数值 | 持久 JSON/非法 int→`[]`/50 | **FIX**：`ValueError` 响亮（共同来源分流，不新护栏） |

**DECL 路径 broad（非 wash→reject）要点**：

| 成员 | 处置 |
|---|---|
| `stage_punishment` 读 `issues.target_roster` | **KEEP**：腐坏已 `raise ValueError`（不洗声明拒收） |
| `parse_engine_payload_json` / `_dossier_row` JSON | **KEEP**：腐坏响亮 `ValueError` |
| `_parse_json_field` `return text` | **KEEP**：分类器字段非 JSON 串回原文；非持久真源 |
| `seed_guilt` 解析失败→False/'' | **KEEP**：既定「解析失败不造罪」语义（非洗成声明拒收） |
| `_item_savepoint_scope` `BaseException` | **KEEP**：回滚后 re-raise |

## G3 完整分类

全表见 `w5-final-recheck/g3-disposition.tsv`。

| 子集 | 处置 |
|---|---|
| 待落人物预判 / 招安互斥影子 | 上轮已删；本轮 named 无复活 |
| `identity_title_for_allegiance` | **KEEP**：仅 `character/apply.py` 单权威 |
| `surcharge_population_pool_members` | **KEEP**：体在 `displaced_population`；surcharge import |
| `dossier_id_in_origin` vs `parse_dossier_id` | **FIX 合并**：`parse_dossier_id` 允许 `dossier:<id>:…` 后缀；`materials.dossier_id_in_origin` 转调权威 |
| credit `_placed` / run `_stored` | **KEEP**：信用段消费已落结果，非平行政策 |
| identical_body ×4 | **KEEP**：bind_content 模块桩 / store schema / MaterialsRoot 别名 / write-gate `__enter__`——非领域准入平行权威 |

## G4 完整消费者闭包处置

全表见 `w5-final-recheck/g4-disposition.tsv`。

上轮 `dead_no_consumer=21` 为**假证**（漏同文件 AST 消费）。纠正后 **0 假死**。

| 成员 | 处置 | 消费者路径 |
|---|---|---|
| `_choose_assignee` + `_extract_imperative_assignee` + 专属 regex/机关滤 | **删除** | 生产零调用（死链）；非现役 secret_order 结构化入口 |
| `GameDB._is_active_secret_order_assignee` | **删除** | 仅测试直调；测改查 `secret_order_briefs⋈secret_orders` |
| db/materials/month_chain 密令私有助手 | **KEEP** | 同文件实读 + 传递闭包达 `commit_pending`/`month_chain`/`dispatch`（表列路径） |
| `cli/terminal` `_failed_secret_order_ids` 等 | **KEEP** | CLI issue/skip 生产路径 |
| `_extract_result_has_execution_lead` | **KEEP** | `extract_draft_intent_with_roster_heal` |
| `_restore_secret_order_brief_projection_in_tx` | **KEEP** | chat rollback → `_restore_chat_rollback_items_in_tx` |

修后枚举：`dead_no_consumer=0` `test_only=0`。

## G5 处置

| 成员 | 处置 |
|---|---|
| `pre_settle` 内事件终态/硬触发 | **已净** `in_pre_settle=0`；探针确认 |
| `month_chain._consume_event_gates_after_edicts` | **唯一消费点** 保留 |
| `docs/SETTLEMENT_FLOW.md` | 已对齐逐旨后 |
| ADR 历史文中 pre_settle 顺序叙述 | **不改历史 ADR 正文**（非现行流程真源）；现行真源为 SETTLEMENT_FLOW + month_chain |

## 探针与聚焦

七 BIN + `MING_SIM_USER_DATA_DIR=/tmp/1835-w5-final/user-data`：

- 探针：`ALL_OK True` → `w5-final-recheck/probes.txt`
- 聚焦：**701 passed, 1 skipped in 17.72s** → `focused.txt`
- 未跑全量；未新增证明测；变异仅断言死符号缺席/装回会红。

## Advisor 三核对

1. **全部候选有实际来源/消费者依据** — G2 逐 try；G4 AST 同文件+传递闭包；G3 业务权威分类表。
2. **全类扫描不点名替代** — 谓词全仓 production；点名仅作样本。
3. **文档/代码/测一致** — SETTLEMENT_FLOW 与代码一致；专属旧测随删改；密令隔离测改公开 SQL。

## 五类结论

| 类 | 状态 |
|---|---|
| G1 | **依法已净**（合法保留 ADR0056/反噬常量） |
| G2 | **依法已净**（字段形状 KEEP；loyalty 脏值与 urge 持久吞修完；pending Exception 已分流） |
| G3 | **依法已净**（dossier 解析合并；其余非业务平行权威 KEEP） |
| G4 | **依法已净**（假死纠正；真死链与 test_only 删除；承重私有 helper KEEP 附路径） |
| G5 | **依法已净**（无 pre_settle 双跑） |

**合法阻断**：无。功能缺口（上轮删影子招安互斥等）仍按 #1812 可删、不挡本票。

## 施工约束

未 stash/amend/rewrite/push/PR；未改宪法/Soul/席位；证据与 `/tmp/1835-w5-final` 自建；未毁 worker 产出。
