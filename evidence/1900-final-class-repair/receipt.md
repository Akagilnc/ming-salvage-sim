# #1900 修内司回执：末判 J18/J6 整类处置

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1900-w5`
- 分支：`ak-roles/1900-j18-j6-final-class-repair`（自 `bb448254c` 新开）
- 判词真源：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a108b9-3e6e-7ba3-b4af-52e9a2b219d2@fixer/attachments/02-1900-judge-bb448254c.json` 末份 `continue` payload
- 票面：`gh issue view 1900` / `1812`（updatedAt 2026-10-04 / 2026-10-02）
- 官方现成解法：SQLite JOIN <https://www.sqlite.org/lang_select.html>；pytest monkeypatch 仅作临时边界、不替被测行为作 oracle（pytest docs）
- 禁令遵守：无 stash / amend / rewrite / push / PR；未改 Soul/宪法/外部配置；自建物仅本工作树 `evidence/1900-final-class-repair/` 与系统临时探针（已清）

---

## 1. 未结类别（末判原文边界）

| 类 | 级别 | 类定义（施工边界） |
|---|---|---|
| **J18** | P2 | 退役残留专用资格、护行供料、死 helper 及失效说明；删除手工连接层，复用现役关联槽和数据库原生连接。不恢复专用账本/双载体/聚合口/旧软判实抵，不另造替代机制/未知状态/护栏。 |
| **J6** | P2 | 处置被测路径 stub、内部调用/标记 oracle、非契约文字锁、固定输出伪证及方向化数值断言；复用既有真实入口恢复独立外部契约；保留必要负向；不造平行夹具或生产钩子；合并回带同审同修。不得转记 #1873。 |

点名仅为样本，谓词不收窄。

---

## 2. J18 机械枚举

### 2.1 枚举命令

```bash
rg -n --glob '!evidence/**' --glob '!.baseline/**' \
  'is_grant_allocation_dossier|_write_dossier_payload_key|_GRANT_ESCORT_RELATIONS|护送实况|_reader_may_cite_escort|_escort_identity_lines|grant_route_reader_facts|软判提案|status_ids = \{' \
  ming_sim tests docs --glob '*.py' --glob '*.md'

rg -n --glob 'ming_sim/**/*.py' \
  'JOIN.*decree_dossier|FROM decree_dossier_links|status_ids|by_id.*decree_dossiers'
```

施工前命中（生产残留成员，不含已署退役说明文档）：

| 成员 | 位置 | 处置 | 保留/删除依据 |
|---|---|---|---|
| `_GRANT_ESCORT_RELATIONS` | `ming_sim/db.py:842` | **删** | 仅定义、零引用的死常量 |
| `is_grant_allocation_dossier` | `ming_sim/db.py:845` | **删** | 仅定义、零引用的死 helper |
| `_dossier_payload_dict`（GameDB） | `ming_sim/db.py:12311` | **删** | 仅被死 writer 使用 |
| `_write_dossier_payload_key` | `ming_sim/db.py:12321` | **删** | 死 writer；专用承接已退役 |
| 软判提案失效说明 | `ming_sim/db.py:838` | **改** | 引擎已取中位，删「软判提案落在界内」措辞 |
| `is_secret_order_dossier` 旧护行说明 | `ming_sim/db.py:14673` | **改** | 去掉已撤销「护送实况来源端」专用表述 |
| 手工 `pairs/status_ids/by_id/link_rows` | `ming_sim/db.py:12562–12599` | **改** | 改为 `decree_dossier_links JOIN decree_dossiers` 原生连接 |
| `_escort_identity_lines` 调用 | `ming_sim/materials.py:908` | **删** | 专用护行供料入口 |
| `_covert_participant_names` … `_escort_identity_lines` 链 | `ming_sim/materials.py:914–1115` | **删** | 专用资格 + 假「护送实况：无护」供料整链 |
| `continuing_dossier_facts` 恒假 escorted 字段 | `ming_sim/materials.py:2048–2051` | **删字段** | 开场文本未消费；恒假 = 假实况形状残留 |
| ADR0054 / DELTA_SCHEMA 已署退役段 | docs | **保留** | 现行退役说明，非复活机制 |
| `grant_arrival_bounds` / 核账 escorted=False 中位 | `db.py` 核账路径 | **保留** | 既有引擎核算；功能接续缺口归 #1873，不另造实护机制 |

复扫命令（施工后）：同上谓词；生产 `ming_sim/**/*.py` 对专用供料/死 helper/手工 status_ids 连接 **0 命中**。

### 2.2 探针（七 BIN 前缀）

声明含押解、核账为空后：

```
INPUT_DECLARED_ESCORT=True
RAW_RECONCILIATIONS 0
ARCHIVE_HAS_无护 False
ARCHIVE_HAS_护送实况 False
MATERIAL_HITS []
PROBE_NO_FALSE_无护 True
```

不再输出「护送实况：无护」。

---

## 3. J6 机械枚举

### 3.1 枚举命令

```bash
rg -n 'auto_close|power_band|routed:|_has_meta_flag|OperationalError|seen\.get|assert actual < |assert after < before' \
  tests/test_qa_t1_extraction_dual_source_1353.py \
  tests/test_audience_restore_505.py \
  tests/test_audience_translate_1837.py \
  tests/test_empire_modifier_income_only_341.py \
  tests/test_refugee_loop_652.py \
  tests/test_promulgation_judge_561.py \
  tests/test_faction_leverage_9.py

rg -n --glob 'tests/*.py' \
  'routed:|track_auto_close|seen\.get\(\"write_gate\"\)|_has_meta_flag\(\"__leverage|\"OperationalError\" in|assert actual < 100 and actual|lambda value: f.routed'
```

### 3.2 成员表与处置

| 成员 | 缺陷类 | 处置 | 必要价值 |
|---|---|---|---|
| `test_resolve_turn_write_gate_held_by_caller_no_reenter` auto_close spy | 被测路径 stub / 调用 oracle | **删 spy**；保留 held 闸 + 公开 `ValueError`（至少一条草案） | 负向：外层持闸不得自锁；spy 调用数为 0 无辨别力（末判 9b276f） |
| `test_start_chat_turn_second_turn_reads_agno_v3_runs` OperationalError 文案 | 非契约文字锁 | **删**；保留 `accepted` + `agno_runs_before` 结构化落账 | 结构化案已足够（末判） |
| `test_translation_entry_preserves_unknown_rejection_and_source_cutoff` 固定转译 | 固定输出伪证 | **改**：独立断言 `night_said` 截止；translate_fn 随 prompt 泄漏后轮 | ADR 0155 源轮截止；变异忽略截止 → 红 |
| `test_income_still_modified_by_legacy` 方向断言 | 弱化数值 | **恢复** `actual == apply_legacy_pct(100, net_pct)`（88） | #341 收入公式契约 |
| `test_monthly_recovery_follows_each_month_actual_payment` `after < before` | 弱化数值 | **恢复** `paid × RECOVERY_PERSONS_PER_WAN` 精确人数 | 0087 实抵/实付回流 |
| `test_in_transit_relief_stays_executing_before_gazette` 方向断言 | 弱化数值 | **恢复** 无护中位实抵 + `arrived × 2000` 精确人数（44000） | 0087 实抵回流；错转 1 → 红 |
| `test_promulgation_context_routes_faction_leverage_through_power_band` | 调用 mock oracle | **整删** | 已有 `…_as_qualitative_band` 真实入口 + `power_band(5)` |
| `test_calibrated_save_without_marker_not_re_anchored` `_has_meta_flag` | 私有标记 oracle | **删标记断言**；保留 offset 外部值 | 外部行为= offset 不重锚 |
| `test_old_integer_offset_migrated_to_float` `_has_meta_flag` | 私有标记 oracle | **删标记断言**；保留 offset=75.5 / leverage | 同上 |
| `test_six_sciences_censor_exit_recomputes_its_faction_leverage` | （正向保留） | **保留** | 真实退场+权势；停用回算红（4047a1） |
| `test_startup_catchup_uses_ticketed_gate_not_bare` | 闸对象行为探针 | **保留** | 断言票据缝 `acquire` 契约本身，非内部调用路线伪证 |

复扫：上表缺陷谓词在 `tests/` **0 命中**。

---

## 4. 聚焦测试（七 BIN=/usr/bin/false）

前缀：

```
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

| 集 | 结果 | 墙钟 |
|---|---|---|
| 点名节点 11 项 | 21 passed | real 3.68s |
| 触及文件 11 个 | 226 passed | real 12.02s |
| `tests/test_supervision_625.py` | 7 passed | real 1.80s |

不全量。不为证明新造测试。

---

## 5. 进程内变异（旧逻辑红 → 恢复绿）

| 变异 | 结果 | 恢复 |
|---|---|---|
| `apply_legacy_pct` 收入 +1 | 1 failed（期望 88 得 89） | 生产函数已恢复 |
| 回流后人口错 1 | 1 failed（106001 ≠ 150000−44000） | 1 passed |
| `recompute_faction_leverage` 停用 | 1 failed（50 ≠ 48） | 1 passed |
| `build_night_said_so_far` 忽略截止 | 1 failed（后轮进入 night_said） | 1 passed |

---

## 6. 自查（合法性 / 复杂度）

- 净删约 277 行（9 files, +71/−348）；无新机制、账本、护栏、未知护送状态。
- 连接层改用 SQLite 原生 JOIN，未平行造读口。
- 测试只改既有节点；删 mock/文字锁/伪证；精确数值来自现行公式与实抵口径。
- 功能接续（有护核账等）不在本片补齐，不转记测试质量债为 #1873。
- 合法阻断：无。

---

## 7. Commit

（提交后回填 SHA）
