---
name: board-query
description: 推演官/档房书办查盘面当前数值时使用——涵盖国势、钱粮、省份、军队、外部势力、朝臣、局势、派系/阶级。写任何数值前必须先查。
---

你处理的是"查盘面、核实数值"。写叙事或填 delta 前必须先查，不凭印象。

## 可用查询工具

| 工具 | 用途 |
|------|------|
| `view_state()` | 国势四量表（国库/内库/民心/皇威）+ 派系/阶级/外部势力总览 |
| `check_treasury()` | 钱粮收支详情：月入月出、欠饷合计、赤字 |
| `list_regions()` | 各省概览（公支/动荡/腐败警讯） |
| `inspect_region(region)` | 指定省份完整数值；region 传省名（"陕西"）或 id（"shaanxi"）均可 |
| `list_armies()` | 军队欠饷/补给警讯一览 |
| `inspect_army(army)` | 指定军队完整数值；army 传军名（"关宁铁骑"）或 id 均可 |
| `list_external_powers()` | 后金/蒙古/朝鲜/流寇当前态势总览 |
| `inspect_external_power(power)` | 指定外部势力完整数值；power 传名称或 id 均可 |
| `list_issues()` | 在办局势（bar_value/惯性/触发条件）概览 |
| `inspect_issue(issue_id)` | 指定局势详情（bar_value/inertia/resolve_condition/fail_condition） |
| `get_active_ministers()` | 在朝朝臣名单及官职（人事变更前必查） |
| `get_faction_class_state()` | 各派系/阶级当前满意度基准 |

## 使用规则

- **省份**：写 region_delta 前先 `inspect_region`，核边界（0~100），超出截到边界。
- **军队**：写 army_delta 前先 `inspect_army`，核 morale/arrears/supply。
- **外部势力**：写 external_power_updates 前先 `inspect_external_power`。
- **人事**：写 office_changes / character_status_changes 前先 `get_active_ministers` 确认 active 且官职正确。
- **局势**：写 issue_advances / close_issues 前先 `inspect_issue` 查 bar_value 和结案条件。
- **派系/阶级**：写 faction_delta / class_delta 前先 `get_faction_class_state` 查基准。
- **钱粮**：写 fiscal_changes / economy_moves 前先 `check_treasury`。
- **世界总览**：不确定当前国势时先 `view_state`。

## 边界

- 每写一个涉及盘面数值的字段前都要查，不要攒到最后一起查。
- 查完后转入写作，不要把原始数字搬进叙事——数字留档房，叙事写定性判断。
- 推演官查完后转 `report-submit` skill 提交奏章。
- 档房书办查完后转 `extraction-submit` skill 提交结算 JSON。
