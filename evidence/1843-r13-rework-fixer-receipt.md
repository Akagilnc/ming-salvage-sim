# #1843 修内司回执（w5 / T-R13-2 恒空兼容键 + has_work 死键闭包续修）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`
分支：`ak-roles/issue-1843-w5-r13-f2-compat`
commitSha：`ab51424fdb9338b28f002410f461b80117f810b4`
原文：`evidence/1843-r13-rework-packet.json`（完整读取）
前判回执：`evidence/1843-r13-rework-fixer-receipt.md`（1129efc19；误以「非C0写闸」豁免恒空兼容响应与 has_work）
基线 HEAD（本轮动手前）：`184240ff2b88b8730c69908b0e5e92abb3502604`
七 `MING_SIM_*_BIN=/usr/bin/false`。不跑全量。不 amend / stash / reset / clean / push / PR。
禁止改 CLAUDE.md / Soul / 宿主配置席位。

## 纠正前回执边界错误

前份回执「剩余」写：响应面恒空兼容键与 effect has_work 检测器不在本两类施工边界内——**边界过窄，不成立**。
T-R13-2 要求：已退役顶层人事键词汇 + 专属支持闭包；原末判禁止保兼容。
「响应而非写闸」「same_file live」不得当豁免。本轮按真实消费链核销这两类残留。

## 全仓枚举（命令真源）

`evidence/1843-r13-rework-enum-commands.txt`

| 证据 | 路径 |
|---|---|
| 四旧键生产消费者逐名定类表 | `evidence/1843-r13-rework-consumers.tsv` |
| T-R13-1/死键专属测试处置表 | `evidence/1843-r13-rework-class-a-members.tsv` |
| 复扫 JSON | `evidence/1843-r13-rework-rescan.json` |

## 消费链核销结论

### A. 恒空兼容响应键（issues.py 曾 8997-9001）

| 证据 | 结论 |
|---|---|
| `applied_appointments/status/power/office` 恒空 `[]` 后写入 report | 无生产/测试读者（全仓无 `applied.get("appointments"|…)`） |
| 注释自述 Keep response keys for compatibility | 专属兼容层 |
| ADR/迁移清单点名删除恒空兼容键 | 与 T-R13-2 一致 |

**处置：DELETED** 四键 + 四恒空局部变量 + 兼容注释。

### B. has_work / unsupported / 配对死键支持

| 位点 | 处置 |
|---|---|
| `models.py` `_character_status_effect_has_work` / `_character_power_effect_has_work` + `effect_dict_has_work` 两行 | DELETED（仅服务已退役顶层键） |
| `issues.py` `_unsupported_monthly_ongoing_fields` 两旧键 | DELETED |
| `issues.py` `has_office` 的 `character_status_changes` 枝 | DELETED（死键不得消音/充当配对） |
| `has_office` | 现仅 `_nonempty_list(effect.get("人物变更"))` |

### C. 死键专属测试

| 用例 | 处置 |
|---|---|
| `test_military_effect_with_only_legacy_office_changes_warns` | DELETED（整用例仅为死键消音负向闸；现役军令告警仍由 `test_military_initiative_without_army_warns` / `test_move_with_only_army_still_warns` 等承接） |
| `test_normalize_person_changes_ignores_non_item_shapes` 内 appointments/office_changes 断言 | DELETED 两行死键断言；保留「人物变更」非条目形现役契约 |
| 现役军令配对告警用例 | RETAIN（未误删） |

### D. 消费者表原 REVIEW_or_comment → 明确处置（无悬空）

| 位点 | 处置 |
|---|---|
| knowledge.py 英文 prose `appointments` | RETAIN_english_prose_not_c0_key |
| month_chain 局部 `appointments`（案卷 list） | RETAIN_local_var_dossier_list_not_c0 |
| db `apply_character_power_changes` 方法名/reason 串 + issues 调用点 | RETAIN_live_db_shared_applier（同名不同义业务方法，非 C0 顶层键） |
| db 军令 payload / `_commit_office_action` 局部 `office_changes` | RETAIN_dossier_payload_local_not_c0_toplevel |
| 触及代码内旧协议误导注释（models/issues/simulation/decree） | FIXED（不改治理文/宪法） |

**未新增护栏/证明性测试**；未知顶层键拒收真源仍在 `sanitize_delta_shape`（`key not in EMPTY_EXTRACTION`）。

## 复扫结果

- EMPTY 四旧键：**0**
- 专属闸 / 恒空兼容响应 / has_work 死键 helper：**0**
- 死键专属测试名：**0**
- `has_office` 仅认「人物变更」：**true**
- 未知顶层键拒收真源：**present**
- 生产剩余四键字面：全部已定类（RETAIN 同名不同义 / FIXED 注释）；**无未经定类 remaining**

## 聚焦自验（完整命令 + 时长）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_issue_entities.py \
  tests/test_person_delta_adapter.py \
  tests/test_declaration_dispatch_1835.py \
  tests/test_month_chain_1843.py \
  tests/test_effect_origin_558.py \
  tests/test_production_person_key_contract_558.py \
  tests/test_initiative_resolve_pairing.py \
  tests/test_power_section_rejections.py \
  tests/test_decree_commitment_schema_136.py::test_effect_dict_has_work_ignores_empty_or_invalid_payloads \
  tests/test_decree_commitment_schema_136.py::test_effect_dict_has_work_recognizes_schema_effects
```

实测：`227 passed in 4.45s`；`/usr/bin/time -p` → **real 4.94s** user 3.56s sys 1.11s。
日志：`evidence/1843-r13-rework-pytest-focused.txt`。
**未跑全量。**

## 自查二连

- 同类型：按真实消费链扫恒空响应键、has_work、unsupported list、配对死键枝、死键专属测试；不以「非写闸」豁免。
- 引入 bug：未新增护栏/证明性测试；未误删现役军令告警与 db 共享易主方法；未动 CLAUDE/Soul/席位；同名不同义局部名保留。

## 剩余

- T-R13-1 / T-R13-2 两类按原文边界已修净；生产四键字面均已定类。
- 不宣称合并/关票。
