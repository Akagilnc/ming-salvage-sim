---
name: extraction-query
description: 档房书办逐章扫邸报、写数值 delta 前，查地区/军队/外部势力/朝臣/局势/派系阶级当前值时使用。
---

你处理的是"查盘面当前值，核边界，算 delta"。写任何数值前必须先查，不凭印象。

适用场景：
- 写 region_delta 前，需要知道某省当前 public_support/unrest/corruption 等值。
- 写 army_delta 前，需要知道某军当前 morale/arrears/supply 等值。
- 写 external_power_updates 前，需要知道后金/蒙古等当前 leverage/military_strength 等值。
- 写 office_changes / character_status_changes 前，需要核查朝臣是否 active、当前官职。
- 写 issue_advances 前，需要查该局势当前 bar_value/inertia/resolve_condition/fail_condition。
- 写 faction_delta / class_delta 前，需要查当前满意度基准。

使用方式：
- 地区当前值：`get_region(region_id)` — region_id 从 input region_ids 选
- 军队当前值：`get_army(army_id)` — army_id 从 input army_ids 选
- 外部势力当前值：`get_external_power(power_id)` — 如 houjin/mongol/korea/bandits
- 在朝朝臣名单：`get_active_ministers()` — 核查人事变更前必查
- 局势详情：`get_issue_detail(issue_id)` — 写 issue_advances/close_issues 前查
- 派系/阶级当前满意度：`get_faction_class_state()`

边界：
- 每写一个涉及盘面数值的字段前都要查，不要攒到最后一起查。
- 核边界：算出 delta 后确认加上当前值不会越过 0~100；越界截到边界。
- 查完写完后转 `extraction-submit` skill 提交 JSON。
