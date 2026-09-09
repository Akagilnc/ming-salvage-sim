# 0148 — 核账期可见面 = 月初快照 + 核账叙事，相位驱动

Status: accepted（陛下 2026-08-16 拍：mock 四版比选取「丙」；月初真源三路比较已定案）

核账期内皇帝看见月初快照与核账叙事，不看引擎半程状态；该呈现由持久回合相位驱动、跨刷新一致；月初呈现真源已定为最小新增投影（路③），非既有活值/热备/流水，且非结算/恢复权威。固定财政等前半段先提交、月份推进在管线末（[ADR 0008](0008-settlement-applier-contract-and-transaction-boundary.md)），撞上亲裁暂停时检查点会泄漏到呈现层（QA #1201 钱已动、月未过；#1203 整屏锁跟会话忙碌、刷新即消失）——取月初口径与核账叙事，消除半程不自洽。核账期仍封无关写入口，但允许提交当前 pending 批红并继续既有结算（批红即推进本月，字面总封会死锁）。不改 0008 的 phase / 事务 / 恢复，只约束中间态对皇帝的可见性；入口起算与未了续跑见 [ADR 0149](0149-enter-settlement-period-on-click-in-flight-continues.md)。

〔2026-09-09 后出注记：决策票 [#1822](https://github.com/Akagilnc/ming-salvage-sim/issues/1822)——过月改为逐段落账后本 ADR 不变：核账期仍只呈现月初快照与核账叙事，逐段到账不对皇帝呈现（推演文流式呈现与否归 #1823）；单件模型调用重试耗尽时核账期停住、系统提示行告知可重试，见 [0157](0157-v2-month-waits-for-exhausted-model-call-recovery.md) 过月形状段。〕

〔2026-09-09 后出注记：决策票 [#1823](https://github.com/Akagilnc/ming-salvage-sim/issues/1823)——核账期主面 = 本月推演卷（推演文流式、段落定即存、刷新从账本读回；不流推敲、无进度条），四键 / 递话条 / 封面口径不变；停住时系统提示行 + 「重试」在卷末；推进后卷即邸报第一页、不另呈。见 [0158](0158-v2-frontend-receives-audience-month-and-recovery.md)。〕
