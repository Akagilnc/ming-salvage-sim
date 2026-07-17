Status: Accepted（2026-07-17：本地双镜头收敛 + owner 范围澄清 + 线上 bot 一轮定界处置后并入）

# 0139: Family correctness 使用增量 checkpoint

## 决定

Family Integrated Correctness 从 shared-tail 单点改为按批触发的 checkpoint：每当一批 child 完成集成并通过 parent Verification，即以新 parent HEAD 启动一次 checkpoint；在飞 child 不等待、合批进入下一 checkpoint；最终顺序仍为 completeness → correctness。
每轮 checkpoint 都是 full-strength 全量审——范围恒为 parent-base…target 全家族 diff，不因轮次降低镜头、模型或强度；**「增量」指触发节奏与判官持久庭记忆（既判例随卷、复报须新证），不指审查范围**（owner 2026-07-17 澄清拍定：「per slice 也是全量，只是有记忆而已，resume 而已」）。
Checkpoint 与 `lastCorrectnessConvergedHead`（记忆/节奏锚点，非范围界）只归现有 Family Flow / Integrated Correctness Action；Runner 不持评审锁，不读取、不解释 `lastCorrectnessConvergedHead`，不据此准入或停车（Runner 既有的机械性 head 搬运不在此列——bot 复审勘正，措辞对齐 #961 票面原文）。
