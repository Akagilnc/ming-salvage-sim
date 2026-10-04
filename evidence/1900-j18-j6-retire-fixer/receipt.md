# #1900 修内司施工回执（J18 + J6）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1900-w5`  
分支：`ak-roles/1900-j18-retire-revoked-mechanisms`  
底座 HEAD（施工前）：`27cf62a320277e1167b1448070a1d9ebfb678143`  
ADR 设计记录提交：`a10edb6db5a3fa1af8010f0d26d0a85133e56b3b`  
既存 `?? .baseline/` 未动；无 stash / amend / rewrite / push / PR。

未结类别以末份判词 `01-1900-judge-27cf62a32.json` 的 continue payload 为准：J18（P1）、J6（P2）。

---

## 0. ADR adrLanding（独立设计记录）

按末份 `fix.classes[J18].adrLanding`：两份已署修订稿原路径落仓，决策正文保持已署版本，仅将「待重新过庭」更新为已署并引用：

- 给事中 `01a107bc-4cbd-717a-86b8-40d8dc328fa6`
- 符宝郎 `01a107cb-0111-7757-87d5-78c1adb9513b`

提交：`ak-roles: docs: land #1900 sealed ADR 0054/0058 design records` → `a10edb6db`。

---

## 1. J18「现行票面已撤销的专用机制仍未退役」

### 类定义（票面 + 末份判词，未收窄）

撤去本切片为旧处方新造的：

1. 暗护双载体承接（`escort_pending_targets` / `escort_sources`）
2. 专用实况账本（`dossier_escort_outcomes`）
3. 配对聚合读口（`list_escort_link_pairs`）
4. 入口专用资格校验（`_covert_pending_targets` / `_is_staged_grant_commission` 等）
5. 及其配套：记录 / 核算 / 供料 / 重开撤回 / 旧入口 / 兼容路径 / 旧实现专测 / 失效说明

不另造替代机制；不恢复旧软判实抵；不宣布取消暗护或沿途损耗玩法（缺口记 #1873）。

### 枚举命令

见 `j18-enum-cmd.txt`；原始命中 `j18-enum-raw.txt`；成员表 `j18-members.md` / `j18-members.json`（施工前 263 hits / 14 files）。

### 逐成员语义处置（按文件）

| 范围 | 处置 |
|---|---|
| `ming_sim/db.py` 表 `dossier_escort_outcomes` + 索引 | 删除建表 |
| `record_dossier_escort_result` / `_insert_escort_outcome` / `list_dossier_escort_outcomes` / `list_escort_outcomes_for_source` / `_coerce_escort_outcome_row` / `_escort_source_relation` / `_grant_escort_presence` | 删除 |
| `_same_night_grant_commission` / `_is_staged_grant_commission` / `_carry_pending_covert_escort_targets` / `_resolve_covert_escort_carry` / `escort_source_dossiers_of` / `list_covert_escorts_aimed_at_pending` | 删除 |
| `list_escort_link_pairs` / `escort_route_ledger_*` | 删除；稽核在场改直接读 `decree_dossier_links` |
| 快照白名单 `dossier_escort_outcomes` | 删除；保留通用 `decree_dossier_links` |
| `list_monthly_grant_reconciliation_targets` | 删专用实况依赖；本切片 `escorted` 恒 False（缺口 #1873） |
| 成案调用点 `_carry_*` / `_resolve_*` | 删除 |
| `declaration_dispatch`：`escort_links`/`escort_results` section、`_covert_pending_targets`、专用分派、bind helper | 删除 |
| `audience_translate` / `month_translate` C0 形状与规则 | 删除已撤销节与暗护指向；保留 `grant.escort` 普通押解 |
| `materials` / `month_chain` / `decree_forecast` 配套读口 | 删专用账本/双载体依赖 |
| `docs/DELTA_SCHEMA.md` | 失效说明改为「已退役」条，不再写作现行契约 |
| `tests/test_escort_route_1900.py` | 仅保留普通 `grant.escort` 现役契约 4 案；专用承接/聚合/实况专测删除 |
| `tests/test_grant_reconciliation_567.py` | 去掉 `record_dossier_escort_result`；核账断言改无护口径 |

保留（非本类撤销对象）：`grant.escort`→`participant_roster`；通用 `decree_dossier_links` / 密令载荷 `dossier_links`。

### 复扫

生产+测试对专用符号复扫：空（`J18_PRODUCTION_TESTS_CLEAN`）。  
`docs/DELTA_SCHEMA.md` 仅保留「已退役」标题提及（失效说明）。见 `j18-rescan.txt`。

### 例外

- 沿途损耗引擎口 `record_monthly_grant_reconciliations` / `grant_arrival_bounds` 仍在；本切片无护口径，有护接续留家族收尾 / #1873。
- 暗护玩法未宣布取消；专用机制已删，功能缺口记 #1873。

---

## 2. J6「非契约内部证明及 mock 替代被测行为仍未清净」

### 类定义（未收窄）

非契约内部证明、mock 替代被测行为、helper 专测、退役行为、非契约文字锁、内部 oracle、调用 mock；必要闸负向不可盲删；删除不必要证明；必要失败路径复用已有真实入口与实际结果。

### 枚举命令

见 `j6-enum-cmd.txt`；原始命中 `j6-enum-raw.txt`（188 hits / 47 files）。

### 本轮语义处置（点名样本 + 同形）

| 成员 | 处置 |
|---|---|
| `test_six_sciences_seed_608` mock `recompute_faction_leverage` 只断言 calls | 改为真实 `set_character_status` → `faction_leverage` 下降；登场案改 `faction_leverage` 上升 |
| `test_promulgation_judge_561` mock `power_band` 断言 `routed:42` | 删除 mock；断言 `power_band(42)` 外部定性 |
| `test_faction_leverage_9` `_has_meta_flag` 私有迁移标记 | 改为再开档后 offset 外部保持 |
| 同文件 `_faction_office_weight_sum` / `_member_office_weight` 内部 oracle | 改为 `faction_leverage` / offset / baseline 外部结果 |
| `test_office_rank_562` `_has_meta_flag` + 权重和内部式 | 改为 leverage 外部可观察结果 |

### 复扫（点名同形）

`j6-rescan-named-shapes.txt`：无 `recompute` mock、`routed:`、`_has_meta_flag`、`_faction_office_weight_sum` 生产断言残留。

### 枚举超集中声明为保留（附依据）的类别

下列命中落在类定义反例之外或属必要边界，本轮不盲删：

| 形状 | 依据 |
|---|---|
| 构造/开档零 LLM：`assert calls == []`（`test_web_llm_runtime_config` 等） | mock 的是外部模型边界，不是被测业务回算；外部可见「零调用」 |
| 写闸 / 事务 callback 顺序录调用 | 闸类契约负向与顺序；硬规允许保留 |
| 运输重试计数 / 耗尽路径 | 外部失败路径契约 |
| `month_chain._load_chain` 状态字段 | 链状态外部投影；非 helper 专测替代真实入口 |
| Web `_settlement_entry_inflight` 等 | UI 入口行为；必要负向 |

若后续庭审认定其中仍属 J6，按同法继续语义处置，不以本回执宣告全仓一切 `calls.append` 绝迹。

### 变异证明（旧逻辑红 / 恢复绿）

命令与时长见：

- `j6-mutation-red.log`：恢复 mock 吞掉 `recompute` → `assert 28 < 28` FAILED，exit 1，~1.02s
- `j6-mutation-green.log`：恢复现行实现 → 1 passed，~1.01s

---

## 3. 聚焦测试

前缀七变量均 `/usr/bin/false`。

```sh
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
python3 -m pytest \
  tests/test_escort_route_1900.py \
  tests/test_grant_reconciliation_567.py \
  tests/test_six_sciences_seed_608.py \
  tests/test_promulgation_judge_561.py \
  tests/test_faction_leverage_9.py \
  tests/test_office_rank_562.py \
  tests/test_relation_capture_633.py \
  tests/test_web_court_visibility.py \
  -q --tb=line -p no:cacheprovider
```

结果：`119 passed in 5.08s`（`focused-after-fix.log`，real ~5.37s）。  
J6 权重迁移后再跑相关 4 文件：`76 passed in 3.89s`（`j6-after-weight-migrate.log`）。

未跑全量。

---

## 4. 净增减（相对 ADR 提交 `a10edb6db`）

施工 diff（未含 ADR 设计记录）：约 **+154 / −2271**（`git diff --stat`）。  
生产 `ming_sim` 明显删简（`db.py` −532、`declaration_dispatch.py` −318 等）。

---

## 5. 未结项（如实）

- 不自行宣布 merge / 关票。
- J18：专用机制生产+测试复扫已空；功能接续（有护核账 / 暗护玩法）留家族收尾与 #1873。
- J6：点名与同形内部 oracle/mock 已处置并复扫；枚举超集中「外部边界 calls」类按上表保留依据交代，未宣称全仓一切调用录制绝迹。
- `git diff --check`：见 `diff-check.txt`（施工前曾报 escort 测试 EOF；已修）。
