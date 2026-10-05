# #1843 修内司回执（w5 / F2-R13 acceptance fix — 全仓枚举补强）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`
分支：`ak-roles/issue-1843-w5-r13-f2-compat`
commitSha：`3f039f1136203f314bacaa7b56c9ff0c12560fb6`
冻结判词：`05-1843-judge-7402d3b80.json` 末份（F2-R13-1 / F2-R13-2）
派单定位：`evidence/1843-w5-r13-fixer-receipt.md` 所指判词/fix-packet；本轮针对验收「A1–A4 固定名样本 / B1 未覆盖全文类定义」补强。
基线：`b7f2e5ec1`（上轮 acceptance）之上新提交；未 amend / stash / push / PR。
七 `MING_SIM_*_BIN=/usr/bin/false`。不跑全量。不宣称合并/关票。
禁止改 CLAUDE.md / Soul / 宿主配置。

## 验收缺口与本轮处置

上轮 `evidence/1843-w5-r13-enum-commands.txt` 的 A1–A4 仅固定名字样本，B1 未覆盖全部 test 函数与全部 assert，不能覆盖类定义全文；用户明确禁止收窄。本轮：

1. **全仓语法/宽关键词枚举**（临时 `/tmp` AST，不加生产扫描机制）：
   - 命令真源：`evidence/1843-w5-r13-enum-commands.txt`（完整可运行 heredoc）
   - 谓词覆盖末判 instruction 全文（旧 regime/旧顶层协议/专属闸/报告映射/夹具/孤儿存储；非契约措辞/内部形状/重复/helper/失效）
   - 覆盖全部 `git ls-files` 跟踪代码与资产（跳过 evidence/）；历史种子来自 `evidence/1843-w5-fixer-deleted-defs-ae4a2a3e6-HEAD.json` + 判词追种子
2. **逐名处置表**（禁止笼统「结构化/状态契约」批标；禁止引用计数/固定白名单作豁免）：
   - `evidence/1843-w5-r13b-class-a-candidates.tsv`（7483 候选）
   - `evidence/1843-w5-r13-class-a-members.tsv` / `…-r13b-class-a-members.tsv`（逐名 disposition）
   - `evidence/1843-w5-r13b-class-b-test-fns.tsv`（全部 2806 test 函数逐名）
   - `evidence/1843-w5-r13b-class-b-asserts.tsv`（全部 12786+ assert 逐位置）
   - `evidence/1843-w5-r13-class-b-members.tsv` = 函数表 ∪ assert 表
   - `evidence/1843-w5-r13b-members-deleted-and-shape-flagged.tsv`（DELETED + shape 旗标摘要）
3. **同类漏网删修**（宽扫发现，非按上轮符号收窄）：
   - `tests/test_execution_pressure_654.py`：删 `idx_decree_dossiers_*` 索引名形状锁整段；改 `test_region_id_column_present_for_dossier_write_path` 只钉 `region_id` 列；唯一/幂等由 `test_national_creates_one_row_idempotent` 承担
   - `tests/test_person_archive_schema.py`：删 `idx_person_logs_turn` 名存在断言；持久由 `test_person_logs_accepts_audit_rows_for_existing_characters` 承担
4. **不收窄类定义**：不把「台院收紧定义」列为剩余项；定义已完整明确。

## F2-R13-1 闭包结论（消费链）

| 处置 | 说明 |
|---|---|
| DELETED（上轮+本轮核销） | 财政双路径旗标壳与标记读写；legacy 预算枝；旧人事顶层翻译/专属闸/报告映射；save_meta 孤儿存储；专属双路径夹具与矩阵 |
| DELETED（历史 defs=0） | deleted-defs 种子在当前树无定义的条目，记入成员表为已闭合 |
| RETAIN | substrate hub / army_pay 物理核；`population_unit` 恒「人」；C0/`ITEM_FIELD_ALIASES`/`beyond_intent`；`normalize_person_changes(人物变更)`；帝国修正 clear_gate humanize（`web_app._humanize_legacy_gate`，非人事 legacy_gate）；Agno blob；声明侧非空旧键拒收；死键不得消音的负向案 |

## F2-R13-2 闭包结论

| 处置 | 说明 |
|---|---|
| DELETED（上轮） | 常熟措辞、关宁固定句、idx_ledger 名锁、同案重复 rejected×4、HUD 词扫 |
| DELETED（本轮同类） | `idx_decree_dossiers_*` 三断言；`idx_person_logs_turn`；原 `test_region_id_column_and_composite_indexes` |
| RETAIN | 输入保真（夹具原文读回同值）；真实拒收/异常/持久态；结构键集与写口必需列；各独立输入案的单条 rejected（非同案重复） |

## 复扫

`evidence/1843-w5-r13-class-rescan.tsv`：
- `assert idx_*` 名存在 → **0**
- 旗标壳/ `__fiscal_engine` / `_mark_population_unit` 可执行路径 → **0**（仅 db.py:80 退役注释）
- web `_legacy_gate_*` → 帝国修正呈现，RETAIN

## 聚焦测试（完整命令 + 文件名单 + 时长）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_execution_pressure_654.py \
  tests/test_person_archive_schema.py \
  tests/test_qa_e1_numeric_presentation.py \
  tests/test_fiscal_substrate_bridge.py \
  tests/test_pay_order_override_653.py \
  tests/test_mutiny_latch_315.py \
  tests/test_mutiny_noop_whitelist_319.py \
  tests/test_mutiny_third_strike_318.py \
  tests/test_mutiny_progression_316.py \
  tests/test_mutiny_redemption_317.py \
  tests/test_player_army_projection_321.py \
  tests/test_effect_origin_558.py \
  tests/test_person_delta_adapter.py \
  tests/test_population_unit_648.py \
  tests/test_qa_a3_seed_data.py \
  tests/test_army_card_status_1501.py \
  tests/test_rescript_draft_656.py
```

实测：`532 passed in 16.66s`；`/usr/bin/time -p` → **real 17.08s** user 8.41s sys 5.69s。
日志：`evidence/1843-w5-r13-pytest-focused.log`。
**未跑全量。**

### 质量成本

| 项 | 成本 |
|---|---|
| 枚举墙钟 | ~8s（AST+宽关键词，/tmp） |
| 处置表生成 | ~1s |
| 聚焦 pytest | real 17.08s / 532 passed |
| 生产代码改动 | **0**（仅两测试文件删索引名锁） |
| 新增证明性测试 | **0** |
| 全量 suite | 未跑（非最终待合并） |

## 自查二连

- 同类型：索引名形状锁按已删 `idx_ledger` 同类整扫删除；枚举覆盖全部 test 函数与全部 assert，不再用固定名样本冒充类边界。
- 引入 bug：未动宪法/Soul/席位；未删 hub 物理核、键集、输入保真、负向拒收；未恢复 HUD 词扫。

## 剩余项

- 无「定义待收紧」项。
- 不宣称合并/关票。
