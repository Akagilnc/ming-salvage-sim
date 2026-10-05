# S2-R3 成员处置表

谓词：战略预检 noop 是否把 TEXT 同值当拒收；power 聚合口径；R1/R2 保留面。

| 成员 | 处置 | 依据 |
|---|---|---|
| `preflight` region 快照 noop | **已改** 跳过 `REGION_TEXT_FIELDS` | R3；同旧 `_region_noop_error` 文本不计 noop |
| `preflight` army 快照 noop | **已改** 跳过 `ARMY_TEXT_FIELDS` | R3；同旧 `_army_noop_error` |
| `preflight` `_reject_landed_or_unchanged` | **保留** landed 非 material + 数值未变 | R2；不另开文本判别层 |
| `preflight` power 逐字段/快照拒 | **已删** → 回跨势力 `any(material)` | 擅自新增；无源，回 e1ffba6ef |
| `preflight` `_power_world_value` + power 快照环 | **已删** | 随 power 口径回退 |
| `apply_army_delta_with_cannon_transfer` 预检写路 | **保留** | R1 |
| `army/issue delta_section` transfer | **保留** | R1 |
| `issue/effects` `apply_army_deltas` | **本局不改** | 非授权面 |
| S1/S3/S4 | **不动** | 授权仅 S2-R3 |

复扫：
- 战略预检无 building 文本 noop 路径（无 BUILDING 战果预检）
- power 文本/数值不再逐字段拒；整批无 material 才拒
- `REGION_TEXT_FIELDS` / `ARMY_TEXT_FIELDS` 成员见 `enum-post.txt`
