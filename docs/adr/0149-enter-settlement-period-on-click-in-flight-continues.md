# 0149 — 点颁布/退朝即进核账期；未了之事续跑、不打回

Status: accepted（陛下 2026-08-16：「点了以后继续走。不需要打回再点。」）

玩家一点颁布或退朝即入核账期；在飞未落账不打回、不逼再点，办完按既有收夜 / 结算次序自动往下走。未了不等于失败；真失败仍 fail-closed（[ADR 0036](0036-audience-night-restore-resume-at-last-entry.md) 原意不动），失败态全面设计另议。入核账期后皇帝看见什么见 [ADR 0148](0148-settlement-period-shows-month-open-snapshot-not-engine-mid-state.md)。

〔2026-09-09 后出注记：决策票 [#1822](https://github.com/Akagilnc/ming-salvage-sim/issues/1822)——「真失败」的过月侧形态已定：单件模型调用重试耗尽 = 核账期停住不推进、已落的账不动、原地重试只补那一次调用、重开仍同一核账期、不给跳过（[0157](0157-v2-month-waits-for-exhausted-model-call-recovery.md)）；推进后的机械尾（关系酿制 / 结局总评；章节记忆已退役，2026-09-10）是后台任务，不算未了。〕

〔2026-09-09 后出注记：决策票 [#1823](https://github.com/Akagilnc/ming-salvage-sim/issues/1823)——重开落点：核账期（含停住）重开同态；夜未收直接回殿上、卷开在最后一轮；其余本月盘面。续跑入口统一为系统提示行的「重试」，不再分「续跑结算 / 重新推演」两钮。见 [0158](0158-v2-frontend-receives-audience-month-and-recovery.md)。〕
