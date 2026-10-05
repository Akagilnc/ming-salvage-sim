# #1847 修内司 w12 纠正交卷 — N11（人口单位旧档判别器退役闭包）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- 分支：`ak-roles/1847-fixer-w11-n11-n13-n10-n14-n16`
- 底座 HEAD（开工）：`82e1da7ae`（`ak-roles: fix #1847 N14 drop CapturingLeg report wash`）
- 本轮纠正 commit：`8dda7b2edc9ba4679ce52725cac4ea9fb12dc64f`（不 amend）
- 判词真源：
  - `~/.ak-roles/books/Ming_LLM/1847/runs/01a109d7-ed74-72c4-bed9-027ef7044a10@fixer/attachments/00-1847-judge-d7fb0dcf7-main.json`
  - `.../01-1847-judge-d7fb0dcf7-correction.json`
  - 原冻结主判词 `conflicts.populationAuthority`：人口无标→万人是旧档兼容；ADR0088 中该旧档例外被后出高位 owner 禁令取代，本票删除其实现及专属测试合法；**不修改治理文件 / 不迁旧档 / 不加识别·拒收层 / 不删现有存档**。
  - owner 口谕：「我早就说过无数次了！不考虑旧存档兼容，以前不，现在不，以后也不，除非哪天我明确说要考虑才开始考虑」
- 环境前缀：七个 `MING_SIM_*_BIN=/usr/bin/false`
- Python：`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`
- 禁止项：未 stash / amend / push / PR / 全量 / 真模型；未改 ADR/治理法源；未重开 N10/N13/N14/N16

## 根因

旧档人口单位判别器（无标→万人 / `save_meta.population_unit` 分流）已退役，但残留：

1. **无消费者写端**：`_mark_population_unit_persons` seed 写 `save_meta population_unit=人`；`population_unit` property 恒返「人」且**不读** `save_meta` → 写端无生产读者。
2. **整表无读者**：`save_meta` 全仓仅服务该写标 → 随删（停 CREATE；旧档内残留表不迁移、不 DROP）。
3. **恒定回显**：`flows.py` / `issues.py` applied 记录回显 `db.population_unit`（恒「人」），无单位分流消费者。
4. **专属测试**锁标与回显；**现役契约** `docs/DELTA_SCHEMA.md` / `constants.py` 仍写新档人/legacy 万、legacy 拒收、随存档换算。

## 枚举命令（可回放）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
bash evidence/1847-w12-scans/enum_commands.sh
# 预扫：evidence/1847-w12-scans/enum_pre.out
# 复扫：evidence/1847-w12-scans/enum_post.out
# 成员：evidence/1847-w12-scans/members_pre.tsv / members_post.tsv
```

### 成员处置摘要

| 成员 | disposition | legal_basis |
|---|---|---|
| `db.py` `POPULATION_UNIT_*` / `_mark_*` / `population_unit` / seed 调用 | FIX_REMOVE | 无消费者写端/空壳 API |
| `db.py` `CREATE TABLE save_meta` | FIX_REMOVE_TABLE | 仅服务人口标；无生产读者 → 整表随删（停 CREATE） |
| `flows.py` / `issues.py` applied `population_unit` 回显 | FIX_REMOVE_ECHO | 恒定回显无分流消费者 |
| `docs/DELTA_SCHEMA.md` 双口径/legacy 拒收句 | FIX_SYNC_PERSONS | 现役产出契约同步人数口径；不新加拒收 |
| `constants.py` 「随存档 population_unit 换算」 | FIX_SYNC_PERSONS | 现役人数契约 |
| `test_new_save_persistent_population_unit_marker` | FIX_REMOVE_TEST | 专属锁标 |
| `test_new_save_unit_is_persons` | FIX_REMOVE_TEST | 专属锁回显 |
| `test_refugee_loop_652` 无用 import | FIX_REMOVE_IMPORT | 死导入 |
| `content/regions.json` `meta.population_unit=人` | KEEP_CONTENT_META | content 人数刻度注释；非 DB 判别器 |
| `docs/adr/0088-*.md` | KEEP_ADR_UNTOUCHED | `conflicts.populationAuthority`：不改治理文件 |
| evidence/CHANGELOG/历史 docs | KEEP_HISTORICAL | 非现役契约 |
| 「无标记/无标签/无标题」误命中 | KEEP_UNRELATED | 非人口单位 |

### 复扫

- 生产+测试 `.py` 功能命中（write/echo/API/专属断言）**= 0**
- `docs/DELTA_SCHEMA.md` / `constants.py` 双口径句 **= 0**
- 合法保留：content meta、ADR0088、历史证据

CLEAR 依据 = 成员表逐成员处置后 functional hit=0（不以 regex 未命中单独宣称）。

## 修复要点

- 删除人口单位常量/key/property/mark 写端与 seed 调用；停建 `save_meta`
- 删除 transfers / bandit absorptions applied 回显字段
- 同步 DELTA_SCHEMA 与 constants 为现役「人」口径（保留 `substrate_hub` 既有门，不另加拒收）
- 清退专属标/回显测试与死 import；复用既有人数 seed / 守恒案，不造证明案
- **未改** ADR0088；**未删**现有存档文件；未重开 N10/N13/N14/N16

## 聚焦测试

```bash
# 七变量前缀同上
BASETEMP=$(mktemp -d /tmp/1847-w12-pytest-XXXXXX)
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q \
  -p no:cacheprovider --basetemp="$BASETEMP" \
  tests/test_population_unit_648.py \
  tests/test_population_transfers_649.py \
  tests/test_refugee_loop_652.py \
  tests/test_surcharge_causal_chain_650.py \
  tests/test_population_transfers_662.py
```

实测：`52 passed in 1.77s`（real ~2.25s）→ `evidence/1847-w12-scans/focused-pytest.out`

`git diff --check`（触及文件）：exit 0

## 自查二连 done

- 同类：N11 全仓 write/echo/API/专属测试/现役契约枚举；逐成员 disposition；ADR 未触；content meta 合法保留
- 引入：聚焦 52 绿；无新机制/拒收/迁移/消费者/证明测试；diff-check 绿；旧档文件未删

## 剩余范围

| 项 | 状态 |
|---|---|
| N11 | 本轮闭包：无消费者写端/回显/专属测试/现役契约已清 |
| N13 / N10 / N14 / N16 | 上轮已获复核；本轮未改 |
| 家族 merge | 未声称完成 |
| ADR0088 历史条文 | 保留原文（治理文件不改）；实现侧已按口谕退役 |
