Status: Proposed

# 0130: 评审交卷契约——看见的都写行，fixer 首务验真翻状态，一切评审模式统一

## 决定

评审腿的交付标准从「挖到可钉死的发现即可收工」改为**穷尽本轮可见面**：一轮内把看见的**所有发现**（不限严重度——严重度是行属性，不是入库门槛）逐条写入 findings 状态库（ADR 0129）后才算交付完成；不分「已演练/未演练」档。每个 review Action 按其 versioned review authority 自己标记 blocking 与 non-blocking terminal；后者不进修复环，也不计入 reviewer 自报的 open-count。具体等级与 terminal 口径归该 authority，不复制 CMR 模式矩阵到 Runner 或本 ADR。评审腿退出前必须自报阻塞未决数；typed open-count / findings 写入由 Action 当场纠错并按 #899 structured retry，耗尽时当前 Action 非零退出。格式或写入失败不得变成 decision gate；只有 worker 成功提交的真实专业、设计或范围决策请求才走 decision gate。Runner 不增设“卷面不可用”第四通道。**fixer 的第一个任务是对 blocking open 行逐条实证真伪**：真→修 + 同类横扫后翻 fixed，伪→翻 refuted + 证据留言，由下轮 fresh 复审员验证后终翻。本契约适用**一切评审模式**（家族 completeness / correctness、per-slice、doc 模式），契约真源就是本 ADR；各评审 Action 由各自 versioned role / skill 消费，per-slice 不因此调用 `ak-cross-m-review`，Runner 只保留指针、不复写第二份。

### 信封字段级驳回词表（#921 落地；#919 / ADR 0132）

- **信封交通信号**（coder / coderFix / familyCoderFix 完成收据）：canonical 唯一 `refused*`——`status: "refused"` + `refusedFindingIdentityKeys` + 可选 `cargoPointer`。`refuted*` 等自造拼法负向拒收；禁兼容双字段。
- **findings 状态库终翻**（本 ADR 上文 fixer 首务）：伪→翻 **`refuted`**——这是状态库行状态，不是信封字段名。两层词表不得混写、不得互为别名。
- **四理由**（违宪 / 过度防御 / 事实不成立 / 越权加戏）在判官处置表侧校验；coder 驳回收据信封只校验交通态与 identity keys，cargo 正文 opaque（判官复裁时读）。实现真源：`orchestrator/src/stationReceiptContracts.ts`。

## 根因（实证数据与出处：#860 正文与 grill 评论、#861 裁决串；EXAM-818 对照见 #856）

21+ 轮 CMR 的串行不来自指令或计时器（prompt 无塑形语言；唯一的钟是 900s 无输出 hang 守卫；CMR worker spec 无 maxIter/timeout）——来自交卷契约缺口：报 1 条与报 5 条同为合法交付，腿在凑够 2-3 个演练钉死的类后自主收卷，剩余面留给下一轮整轮开销。修复侧横扫教义（EXAM-818，6→1）已消灭同类复发；本决定把同一哲学对称到发现侧。残余轮次=递进暴露（修复后才可见的洞），不可消灭、不作为本契约失败判据。

## 边界与保留（r1 评审修订）

- 「不分档」只治发现入库，不减复审员**行为演练**义务（反模式 #15 原样有效）：演练义务在 fixer 侧追加（首务实证），非从复审员侧扣除。
- 「找全→修全→验清 2-3 轮」的地板预期只 scope 到**代码评审**；doc 模式的收敛画像由 ②-⑤ 纪律（账本/膨胀线/轮次 10 检查点）治理，不由地板治理。
- fresh 全量复审、#597 无轮上限与复审员自升级出口、doc 模式防加性跑飞纪律，全部原样保留（吐全指「发现」不指「建议加字」）。
- 验收：#786 遥测 review_round 计数为**前置依赖**（未落地前以手数为准），基线=2026-07-12 夜（completeness 12 轮 / correctness 10+ 轮）。
