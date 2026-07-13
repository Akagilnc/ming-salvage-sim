# 0128 — 执行面唯一 Sandcastle 容器；host 侧只做控制、监控与桥接

- Status: Accepted（2026-07-12，#871 grill）
- Date: 2026-07-11

**决策**：Execution Plane 只指真正运行自主 agent session 的环境；当前唯一执行面是 Sandcastle 容器。host launcher、父监控器（`workerMonitor.dispatchMonitoredCliWorker`）与桥子进程（`hostCliWorkerRunner`）属于控制与观察设施：父监控器持 #684 监控句柄（pid/log/pool/signal、hang-kill），桥子进程只重建 backend、重入 `dispatchWorker`/`dispatchFamilyWorker` 的既有容器执行缝并写 result sidecar；二者都不得直接运行 agent CLI。host 上的 Git、GitHub、构建等确定性动作是外部能力，也不构成第二执行面。新增任何 agent 执行路（含 host 直跑 CLI）必须先过设计闸（grill → ADR），不得在评审/修复 commit 中夹带执行包装层。

**背景**：#684 R2 以 host 桥子进程实现监控句柄，属票面范围外长出（#814 调查坐实，commit 5ce70e31）；grok-build 接通采用容器路线（镜像烤 Linux CLI + auth 副本挂载 + slug 注册，#807 原案），host 直跑变体（feat/807-pi-channel tip `4da2562b`，未进 main）不作默认架构，仅可作单独过闸的临时 spike。owner 2026-07-11 拍板（#814）。
