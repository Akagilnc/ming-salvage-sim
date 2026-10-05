# #1843 修内司回执（w5 / T-R13-1 + T-R13-2 rework）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`
分支：`ak-roles/issue-1843-w5-r13-f2-compat`
commitSha：`1129efc192fe50e9551043de7587f99cca75b8e7`
原文：`evidence/1843-r13-rework-packet.json`（完整读取，未以摘要替代）
前判回执（**错误宣称闭包，本轮纠正**）：`evidence/1843-w5-r13-fixer-receipt.md`
基线 HEAD（动手前）：`d417046212e9ba8c41d888f255065cbea40a49d5`
七 `MING_SIM_*_BIN=/usr/bin/false`。不跑全量。不 amend / stash / reset / clean / push / PR。
禁止改 CLAUDE.md / Soul / 宿主配置席位。

## 纠正前回执 completed 结论

前份 `evidence/1843-w5-r13-fixer-receipt.md` 写「F2-R13-1 / F2-R13-2 闭包」不成立：
- T-R13-1：机械改写的旧协议专属测试（含重复键空真）仍在
- T-R13-2：C0 `EMPTY_EXTRACTION` 仍保留四旧顶层人事键，并新增无测试专属拒收闸
本轮只闭合这两类；**不宣称合并/关票**。

## 全仓枚举（命令真源）

`evidence/1843-r13-rework-enum-commands.txt`

| 证据 | 路径 |
|---|---|
| 四旧键生产消费者逐行表 | `evidence/1843-r13-rework-consumers.tsv` |
| T-R13-1 类成员处置表 | `evidence/1843-r13-rework-class-a-members.tsv` |
| 复扫 JSON | `evidence/1843-r13-rework-rescan.json` |

### T-R13-2 根因与消费者结论

四旧键（`appointments` / `character_status_changes` / `character_power_changes` / `office_changes`）在 C0 声明形状上**无现役读消费者**：
- 写落账只经 `人物变更` / `normalize_person_changes`
- `sanitize_delta_shape` 以 `EMPTY_EXTRACTION` 为未知顶层键拒收真源（`ming_sim/issues.py`）
- 专属闸仅为旧键仍在 EMPTY 时的第二份同构物

非 C0 声明形状、本轮不删：
- `apply_score_extraction` 返回面恒空兼容键（响应形，非声明形）
- `db.apply_character_power_changes` / dossier payload `office_changes` 局部名
- issue effect `has_work` / monthly unsupported 检测器（非声明写闸）

### T-R13-2 处置

| 项 | 处置 |
|---|---|
| `EMPTY_EXTRACTION` 四旧键 | DELETED |
| `declaration_dispatch` 专属拒收循环 | DELETED |
| `issues._apply_issue_entities` 专属 ValueError | DELETED |
| 未知顶层键拒收真源 | RETAIN（既有） |
| 新增护栏/证明性测试 | 0 |

### T-R13-1 处置

| 用例 | 处置 |
|---|---|
| `test_issue_unified_person_change_shadows_legacy_person_effects` | DELETED（重复键空真 + 退役遮蔽协议） |
| `test_apply_score_extraction_new_person_changes_shadow_legacy_person_keys` | DELETED（退役遮蔽协议） |
| `test_legacy_issue_status_change_uses_person_transition_matrix` | RENAMED → `test_issue_entities_rejects_dead_to_dismissed_transition`（结案非法迁移独立契约） |
| `test_legacy_issue_status_change_does_not_use_month_end_active_gate` | RENAMED → `test_issue_entities_allows_imprisoned_to_dead_disposal`（在押→赐死独立契约） |
| `test_normalize_person_changes_ignores_non_item_shapes` | RETAIN（normalize 忽略非规范形，非遮蔽协议） |
| `test_military_effect_with_only_legacy_office_changes_warns` | RETAIN（死键不得消音配对告警负向闸） |

## 复扫结果

- `EMPTY_EXTRACTION` 四旧键：**0**
- 专属拒收文案 / 专属循环：**0**
- tests 内新建 dict 重复键（人物变更）：**0**
- 未知顶层键拒收真源仍在：`issues.py` `key not in EMPTY_EXTRACTION`

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
  tests/test_power_section_rejections.py
```

实测：`205 passed in 4.19s`；`/usr/bin/time -p` → **real 4.70s** user 3.22s sys 1.01s。
日志：`evidence/1843-r13-rework-pytest-focused.txt`。
**未跑全量。**

## 自查二连

- 同类型：按类全仓枚举旧协议机械改写测试与四旧键声明形存活物，不只点名处；根因删 EMPTY 键，专属闸随同删除。
- 引入 bug：未新增护栏/证明性测试；未误删负向闸与独立现役契约（改名保留）；未动 CLAUDE/Soul/席位。

## 剩余

- 两类已按原文边界处置；响应面恒空兼容键与 effect has_work 检测器不在本两类施工边界内。
- 不宣称合并/关票。
