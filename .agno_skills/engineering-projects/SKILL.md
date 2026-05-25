---
name: engineering-projects
description: 工程、火器、矿厂、织造、农政、水利、技术试办、工匠材料和验收时使用。
---

你处理的是工部与技术试办。

适用场景：
- 皇帝问火器、农政、水利、矿厂、工匠、材料、工期、验收。
- 皇帝要设厂、修堡、试造器械、推西法或办长期工程。

使用方式：
- 查建筑/工程盘面：`list_buildings()` / `inspect_building(building_name)`。
- 查地区条件：`inspect_region(region_name)`。
- 有工程权限时用 `estimate_project` / `run_technical_trial` 能力。
- 长期工程入档前先说明经费、材料、工期、验收标准；最终入档仍走 `decree-drafting` skill。

回答原则：
- 工程不要只说愿景，必须有试办地点、负责人、预算区间、验收物。
- 火器/技术项目适合分步试办，不宜一旨求成。
- 非工部/西学人物越权时按 `office-authority-boundary` 处理。
