---
name: board-survey
description: 推演官收到 input 后，开始查盘面、对齐实情时使用。必须在写邸报前完成。
---

你处理的是"查盘面、对齐实情"。收到 input 后第一件事就是走这个 skill，不是写字。

适用场景：
- 刚收到 input，需要了解当前国势、钱粮、地方、军队、在办事项。
- 诏书涉及某省/某军，需要查该地区或军队的具体数值。
- 判断候选事件是否触发前，需要核实盘面压力。

使用方式（严格按顺序）：
1. `view_state()` — 国势四量表 + 派系 + 阶级 + 外部势力总览
2. `check_treasury()` — 钱粮收支详情
3. `list_regions()` — 各省危情概览；诏书涉及哪省就 `inspect_region(region_name)` 单独查
4. `list_armies()` — 军队欠饷/补给警讯；涉及哪军就 `inspect_army(army_name)` 单独查
5. `list_issues()` / `inspect_issue(issue_id)` — 在办事项及进度详情
6. `list_external_powers()` — 后金/蒙古/朝鲜/流寇当前态势

边界：
- 盘面查完才动笔写邸报，不要边查边写。
- 不要把查到的数字直接搬进奏章；数字留在档房，叙事写定性判断。
- 查完所有相关数据后，转入写作，最终用 `report-submit` skill 提交。
