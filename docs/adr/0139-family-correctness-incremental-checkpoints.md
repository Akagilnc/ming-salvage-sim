Status: Proposed

# 0139: Family correctness 使用增量 checkpoint

## 决定

Family Integrated Correctness 从 shared-tail 单点改为 durable parent-base 增量 checkpoint；在飞期间完成的 child 合批进入下一 checkpoint，最终顺序仍为 completeness → correctness。
Checkpoint 与 `lastCorrectnessConvergedHead` 只归现有 Family Flow / Integrated Correctness Action；Runner 不持评审锁、不读取或比较 HEAD。
