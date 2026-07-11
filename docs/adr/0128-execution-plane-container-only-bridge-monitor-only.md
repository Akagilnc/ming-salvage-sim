# 0128 — 执行面唯一 Sandcastle 容器；host 侧只做监控与桥接

- Status: Proposed
- Date: 2026-07-11

**决策**：编排器 worker 的 agent runtime 唯一 = Sandcastle 容器；host 侧两件既有部件只服务于此、不得直接运行 agent CLI——父监控器（`workerMonitor.dispatchMonitoredCliWorker`）持 #684 监控句柄（pid/log/pool/signal、hang-kill），桥子进程（`hostCliWorkerRunner`）只重建 backend、重入 `dispatchWorker`/`dispatchFamilyWorker` 的既有容器执行缝并写 result sidecar。新增任何 agent 执行路（含 host 直跑 CLI）必须先过设计闸（grill → ADR），不得在评审/修复 commit 中夹带执行包装层。

**背景**：#684 R2 以 host 桥子进程实现监控句柄，属票面范围外长出（#814 调查坐实，commit 5ce70e31）；grok-build 接通采用容器路线（镜像烤 Linux CLI + auth 副本挂载 + slug 注册，#807 原案），host 直跑变体（feat/807-pi-channel tip `4da2562b`，未进 main）不作默认架构，仅可作单独过闸的临时 spike。owner 2026-07-11 拍板（#814）。
