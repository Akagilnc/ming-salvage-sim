# #1835-w5 S2 修内司回执（R1/R2）

## 本局交付

分支：`ak-roles/issue-1835-w5-s1s4-fixer`  
票：#1835；**仅 S2**（S1/S3/S4 不动）。  
基线：`06b167f9b`（上轮宣称整封拒收成立过强）。  
**不宣称 merge／关票。**

## 复核指出的 P1 回归

| ID | 症状 | 根因 | 处置 |
|---|---|---|---|
| R1 | 合法战略 `army_delta` 含 `随军大炮:-3,cannon_transfer_to:B` 被整封拒 | 预检把完整 `raw_changes` 送 `db.apply_army_deltas`；该核不认转移键 → `invalid_enum` | 预检改走真写路 `apply_army_delta_with_cannon_transfer`（与 `army/delta_section`／`issue/delta_section` 同口径） |
| R2 | latched 军 loyalty 贴 cap 的 +5 与 manpower−100 同项 + 地区压力+35 → `triggered=True` pressure55 军9900 | 删影子后改用整类 `any(material)`，任一字段 silent noop 被兄弟实变盖过 | 按目标/字段：写核 landed 非 material，或声明字段写后世界值未变 → 拒整封；不恢复影子公式 |

## 授权范围同类扫净

| 成员 | 处置 | 依据 |
|---|---|---|
| `preflight` 军队预检 `apply_army_deltas` | **已改** → `apply_army_delta_with_cannon_transfer` | R1；复扫 preflight 无 `apply_army_deltas(` |
| `preflight` region/army/power 整类 `not any(material)` | **已删**；改为逐目标 `_reject_landed_or_unchanged` | R2 |
| `preflight` new_armies 整批 `not any(material)` | **已改** 逐项 material | 同根「一 noop 盖过」 |
| `army/delta_section.apply_army_delta_with_cannon_transfer` | **保留** | 真写路 |
| `issue/delta_section` 战略物化 transfer | **保留** | 已同口径 |
| `issue/effects.py` 两处 `apply_army_deltas` | **保留／不扩** | 局势效果路，非本局授权之战略预检 S2；若日后要收 transfer 另开授权 |
| `db.apply_army_deltas` clamp | **保留** | 写核真源；预检只读其结果／落库后世界值 |

## 回归测试（真实 `dispatch_month_segment`）

文件：`tests/test_mutiny_noop_whitelist_319.py`

1. `test_strategic_event_cannon_transfer_preflight_reuses_transfer_write_path` — R1  
2. `test_latched_loyalty_cap_mixed_manpower_preflight_rejects_whole_envelope` — R2  

## 聚焦测试

```
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  MING_SIM_USER_DATA_DIR=<tmp>/user PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -B -m pytest -q -p no:cacheprovider --basetemp=<tmp>/pytest \
  tests/test_mutiny_noop_whitelist_319.py
```

结果：`27 passed in 1.23s`（见 `focused-tests.txt`）。未跑全量、未打真模型。

## 变异（装回 06b167f9b 口径）

```
env MING_SIM_*_BIN=/usr/bin/false \
  .venv/bin/python -B evidence/issue-1835/w5-s2/run_mutation_probes.py
```

| 探针 | 结果 |
|---|---|
| R1 当前 transfer 写路 | `triggered=True src=2 dst=3` |
| R2 当前按字段拒 | `triggered=False loyalty=80 manpower=10000 pressure=20` |
| R1 装回 `apply_army_deltas` | `triggered=False src=5 dst=0`（红） |
| R2 装回整类 `any(material)` | `triggered=True loyalty=80 manpower=9900 pressure=55`（红；与用户复核例一致） |

## T-1 过强主张撤回

撤回 `evidence/issue-1835/w5-s1s4` 中「S2 事件整封拒收仍成立」之过强读法：`S2_EVENT_WHOLE_PACKAGE_REJECT` 仅覆盖 **loyalty 单字段** 贴 cap 信封，**不得**主张已覆盖 (a) 同项混合 noop+实变 (b) 合法 `cannon_transfer_to` 预检写路。本局以 R1/R2 两条真实入口测 + 装回红绿补证据。

## 自查二连

- 同类型：战略预检军队写路与 noop 聚合已按同类扫；effects 路未授权不猜修。  
- 引入 bug：transfer 懒 import 避环；power 缺行不预读未知列；savepoint 仍包住预检写。

## 剩余

- 仅 S2；S1/S3/S4 本局未动。  
- `issue/effects` 若需 transfer 同口径 → 另授权。  
- 未 push、未开 PR、未 stash、未 amend。
