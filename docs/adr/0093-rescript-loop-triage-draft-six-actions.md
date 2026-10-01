# 0093: 急务由人物票拟，批语原样传递；发回改票次月再呈

Status: Accepted（#1816／#1847 后出修订独立署庭：给事中 run `01a0f8a1-6cf4-7ee1-8010-8ba63c7f09a8`、审刑院 run `01a0f8a9-e0a8-78e3-8291-62b017f5019c`；原决定 PR #663，2026-07-07）

急务由真实在职的首辅或司礼监掌印按人物立场判断、择序，内阁附事实与拟旨成奏折，皇帝批语原样交续推转译；代码代选分拣人、固定 3–5 条、六动作机器及急务／请旨的第二效果写口由此取代，因为批红是奏折与批语，不是代码代人物下决定（源卷 `a45c2e6b-8c9a-4f56-85fb-73324ee40299.jsonl`，assistant `ab4bb0af-6442-4c60-b0f1-ed3a44b91c9c` 第 4 项，owner `9adcea7c-11e1-4f53-917e-14955207d1aa`：「直接传话不行？」；源卷 `a59eafbe-ffb1-4d1c-9cf5-c001af65c0ac.jsonl`，assistant `967d8113-6049-4615-bc8d-5c23402b916b` 第二项，owner `61e2960d-f239-4614-8e1c-336dbccd9cea`：「批红是奏折，召对才是实时」）。票拟依赖世界段落账后的材料，旧 extractor 并行决定不再适用；模型可交空集，有合法分拣人不得由代码先判无急务跳过，双缺位无可署名者不空跑，但全量邸报、其他待裁及待改原案不因此消失。

发回不阻塞当月整批，修订奏折自次月再呈，双缺位原案搁置、补任再呈而不造代理人（源卷 `a59eafbe-ffb1-4d1c-9cf5-c001af65c0ac.jsonl`，assistant `43754feb-bf9d-4a51-8c2e-b0c4ccbdd270` 问重拟何时回来及何处呈现，owner `fc46c74b-01ca-4bd0-9554-8e035caad1d4`：「发回改票。就是下个月才看得见了。」；源卷 `a45c2e6b-8c9a-4f56-85fb-73324ee40299.jsonl`，assistant `04f23ca6-0f32-4e73-acbc-210cc18d32fd` 问跨月双缺位，owner `d5405bb6-6f96-4274-919f-502515537437` 选「搁着，有人上任再呈（推荐）」）。同案头不混同效果写口：[0055](0055-promulgation-gate-at-settlement-effects-follow-verdict.md) 法定三选、颁布资格及结构化判后物化保持；[0152](0152-independent-manual-draft-entry-collapses-to-audience.md) 御笔另旨·中旨与无人站台原案强推保持，原案及 `decision_key` 不变，不恢复独立手拟入口。

执行契约与验收唯一见 [#1847](https://github.com/Akagilnc/ming-salvage-sim/issues/1847)；主链接 #1843、呈现 #1826、恢复 #1846，按 [0157](0157-v2-month-waits-for-exhausted-model-call-recovery.md)／[0158](0158-v2-frontend-receives-audience-month-and-recovery.md) 交接。运行时实施与验证由 #1847 施工回执承接，不以文档修订代实施证据。
