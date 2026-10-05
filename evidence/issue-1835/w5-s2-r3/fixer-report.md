# #1835-w5 S2-R3 修内司回执

## 本局交付

分支：`ak-roles/issue-1835-w5-s1s4-fixer`  
票：#1835；**仅 S2-R3**（S1/S3/S4 不动；R1/R2 保留）。  
基线：`a16d5804e`（R1/R2 已成；R3 未结）。  
**不宣称 merge／关票。**

## 复核指出的 P1（R3）

| ID | 症状 | 根因 | 处置 |
|---|---|---|---|
| R3 | `jisi_lubian` 同值文本+数值实变被整封拒：`region_delta={military_pressure:35,controlled_by:当前ming}` 或 `army_delta={station:当前驻地,manpower:-10}`；旧 e1ffba6ef `triggered=True`，a16d5804e `False` | 新快照对 `REGION_TEXT_FIELDS`/`ARMY_TEXT_FIELDS` 同值也判 noop；旧 `_region_noop_error`/`_army_noop_error` 文本一律不判 noop | 快照只收数值；文本跳过；仍复用 landed 按目标/字段 |
| power | a16d5804e 逐势力/字段快照拒 | 擅自新增，无法源 | 回 e1ffba6ef 跨势力 `any(material)` 聚合 |

## 删简

- `preflight.py`：`a16d5804e` 1044 行 → 现 1022 行（**−22**）
- vs a16d5804e diffstat：`+24 / −46`（去掉 power 快照环 + `_power_world_value`；文本跳过为条件收窄）

## 枚举成员（noop 文本豁免）

见 `enum-post.txt`：

- `REGION_TEXT_FIELDS`：`natural_disaster, human_disaster, status, controlled_by`
- `ARMY_TEXT_FIELDS`：`station, station_region, commander, controller, troop_type, status, owner_power`
- `POWER_TEXT_FIELDS`：仅信息；power 已非逐字段拒

## 回归测试

文件：`tests/test_mutiny_noop_whitelist_319.py`

1. R1 `test_strategic_event_cannon_transfer_preflight_reuses_transfer_write_path` — 保留  
2. R2 `test_latched_loyalty_cap_mixed_manpower_preflight_rejects_whole_envelope` — 保留  
3. **R3** `test_strategic_same_value_text_with_numeric_change_preflight_allows` — 同案覆盖 region `controlled_by` + army `station` 同值文本与压力/兵力实变

## 聚焦测试（实测）

```
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  MING_SIM_USER_DATA_DIR=<tmp>/user PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=. python -B -m pytest -q -p no:cacheprovider --basetemp=<tmp>/pytest \
  tests/test_mutiny_noop_whitelist_319.py
```

结果：`28 passed in 1.04s`（见 `focused-tests.txt`）。未跑全量、未打真模型。

## 变异（装回 a16d5804e 文本进快照口径）

```
env MING_SIM_*_BIN=/usr/bin/false \
  PYTHONPATH=. python -B evidence/issue-1835/w5-s2/run_mutation_probes.py
```

| 探针 | 结果 |
|---|---|
| R1 当前 | `triggered=True src=2 dst=3` |
| R2 当前 | `triggered=False loyalty=80 manpower=10000 pressure=20` |
| R3 当前文本不计 noop | `triggered=True pressure=55 manpower=9990` |
| R1 装回 `apply_army_deltas` | `triggered=False`（红） |
| R2 装回整类 `any(material)` | `triggered=True … pressure=55`（红） |
| R3 装回 a16d5804e 文本同值计 noop | `triggered=False pressure=20 manpower=10000`（红） |

## 自查二连

- 同类型：战略预检 region/army 文本豁免已对齐旧 noop；power 回聚合；building 无战略预检文本 noop 面。  
- 引入 bug：R1 transfer 写路未动；R2 数值混合 noop 仍拒；快照不再吞文本同值。

## 剩余

- 仅 S2-R3；S1/S3/S4 本局未动。  
- 未 push、未开 PR、未 stash、未 amend。
