# F3 rejudge：仍净删 17 条 assert/expect 处置表

基线：`52809cdf3`。工作树复核时点：本提交。判定口径：**同测试函数内**原样断言；禁止以另一测试同字符串 / 整文件 presence 冒充 RESTORE。

枚举命令：`git diff 52809cdf3 --unified=0 -- tests web`（含未提交工作树），匹配 `\bassert\b|\bexpect\(`。

复扫结果：**same-file NET DELETED = 0**（17/17 均在原函数恢复）。

| # | 旧位置 | 旧函数 | 断言摘要 | 处置 | 新位置 |
| --- | --- | --- | --- | --- | --- |
| 01 | `tests/test_audience_translate_1837.py:739` | `test_translate_call_failure_is_not_empty_success_dispatch` | `result.answer == "臣在。"` | RESTORE | 同函数 L733 |
| 02 | `tests/test_faction_brew_637.py:140` | `test_both_endpoints_different_factions_both_selected` | 阉党 `朝局如常。` | RESTORE | 同函数 L142 |
| 03 | `tests/test_month_call_recovery_1846.py:295` | `test_world_translate_exhaustion_keeps_text_resume_retries_translate_only` | `world_text_ready is True` | RESTORE | 同函数 L297 |
| 04 | `tests/test_month_translate_1840.py:213` | `test_world_segment_translates_once_and_persists_repeated_subject_facts_in_order` | army_facts `军队先记一事/再记一事` | RESTORE | 同函数 L215 |
| 05 | `web/src/appDurableWiring.test.tsx:255` | `密令召见…(#1849)` | `toContain("臣已入殿")`（finishStream 前 delta） | RESTORE | 同函数 L256（finishStream 前）；L257 后探针仍在 |
| 06 | `web/src/components/drawers.test.tsx:163` | `keeps world facts and never renders situation three-key strings` | `toContain("登莱兵与水师")` | RESTORE | 同函数 L163；已撤 fractional 他测误挂 |
| 07 | `web/src/components/drawers.test.tsx:166` | 同上 | `not.toContain("欠饷约60万两，数月军饷")` | RESTORE | 同函数 L166；不得以 #1501 他测同串冒充 |
| 08 | `web/src/components/drawers.test.tsx:167` | 同上 | `not.toContain("士气：尚稳")` | RESTORE | 同函数 L167；已撤 #1501 误挂 |
| 09 | `web/src/components/map.test.tsx:155` | `驻军表兵力全数呈现且月饷带万，表头仅世界事实列` | `not.toContain("欠饷不足十万两，约两月军饷")` | RESTORE | 同函数 L155；已撤 population 他测误挂 |
| 10 | `web/src/components/modals.test.tsx:694` | `retires the whole old-night snapshot…` | `旧轮迟到递话` | RESTORE | 同函数 L696 |
| 11 | `web/src/components/modals.test.tsx:1292` | `半轮 replyRetry：…` | `密令：整饬边备` | RESTORE | 同函数 L1296；非 chronological night:~1035 |
| 12 | `web/src/components/modals.test.tsx:1293` | `半轮 replyRetry：…` | `臣领旨` | RESTORE | 同函数 L1297 |
| 13 | `web/src/components/modals.test.tsx:1304` | `切回有记录大臣：语义轮完整…` | `密令：整饬边备` | RESTORE | 同函数 L1308 |
| 14 | `web/src/components/modals.test.tsx:1305` | `切回有记录大臣：语义轮完整…` | `臣领旨` | RESTORE | 同函数 L1309 |
| 15 | `web/src/components/modals.test.tsx:1306` | `切回有记录大臣：语义轮完整…` | `神色凝重` | RESTORE | 同函数 L1310 |
| 16 | `web/src/mindreadingDelivery.test.tsx:179` | `accepted 后 provider failure…` | `rows() user:保留问话` | RESTORE | 同函数 L180；已撤误插入 `rows()` 映射体 |
| 17 | `web/src/mindreadingDelivery.test.tsx:180` | `accepted 后 provider failure…` | `rows() minister:保留答复` | RESTORE | 同函数 L181 |

机器可读：`rejudge-17-disposition.jsonl`。判词原文：`rejudge-remaining-17.json`。

成员表 175 条已按同函数新行更正相关条目（尤其 156–160 不再写「他测 ~1035」）。F14 未改。
