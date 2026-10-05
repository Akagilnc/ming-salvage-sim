# S2 成员处置表（R1/R2 复扫）

谓词：战略预检军队写路；整类 `any(material)`／`not any(material)`；`cannon_transfer` 相关入口。

| 成员 | 处置 | 依据 |
|---|---|---|
| `preflight._strategic_event_result_preflight_error` 军队 `apply_army_deltas({raw})` | **已修** → `apply_army_delta_with_cannon_transfer` | R1：转移键非法拒收 |
| `preflight` region/army 写后整类 `not any(material)` | **已删** | R2：放宽为全类 no-op 才拒 |
| `preflight` power 整类 `not any(material)` | **已改** 逐势力 snapshot+landed | 同根 |
| `preflight` new_armies 整批 `not any(material)` | **已改** 逐项 | 同根 |
| `preflight._reject_landed_or_unchanged` | **新增** | 复用写核 landed + 写后世界值；按目标/字段报 noop |
| `army.delta_section.apply_army_delta_with_cannon_transfer` | **保留** | 真写路 |
| `issue.delta_section` 战略物化 transfer | **保留** | 已同口径 |
| `issue.effects` `apply_army_deltas` ×2 | **保留／本局不改** | 非战略预检授权面 |
| `db.apply_*` clamp | **保留** | 写核 |

复扫断言：
- `preflight.py` 无 `apply_army_deltas(` 调用
- `preflight.py` 无 region/army `region_results`/`army_results` 整类 `not any(material)`
- transfer 调用点：`army/delta_section`、`issue/delta_section`、`preflight`
