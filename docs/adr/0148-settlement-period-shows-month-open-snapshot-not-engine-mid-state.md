# 0148 — 核账期可见面 = 月初快照 + 核账叙事，相位驱动

Status: proposed（陛下 2026-08-16 拍：mock 四版比选取「丙」；月初真源三路比较已定案）

核账期内皇帝看见月初快照与核账叙事，不看引擎半程状态；该呈现由持久回合相位驱动、跨刷新一致。固定财政等前半段先提交、月份推进在管线末（[ADR 0008](0008-settlement-applier-contract-and-transaction-boundary.md)），撞上亲裁暂停时检查点会泄漏到呈现层（QA #1201 钱已动、月未过；#1203 整屏锁跟会话忙碌、刷新即消失）——取月初口径与核账叙事，消除半程不自洽。不改 0008 的 phase / 事务 / 恢复，只约束中间态对皇帝的可见性；入口起算与未了续跑见 [ADR 0149](0149-enter-settlement-period-on-click-in-flight-continues.md)。
