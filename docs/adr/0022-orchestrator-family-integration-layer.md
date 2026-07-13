# 家族集成层：现成子片 + distinct branch + parent base

Status: Accepted（2026-06-21；grill-with-docs 收敛 + 设计 cmr 5 轮 + 线上 bot 收敛 → PR #290 合入 main。）

## Current authority

- #869 单一拥有现行 issue→merge 交付拓扑，包括 family 的准确接力顺序。
- ADR 0131 单一拥有 Runner 三通道与零判断权。
- ADR 0127 单一拥有 worker scene 的保留、恢复与窄删除规则。

本 ADR 只保留 family 的结构决定。旧版 S0–S8、整波 barrier、Runner ledger/HEAD reconcile、issue-body YAML 解析、线上评审边界与其他步骤细节均已废止，不得作为实现依据。

## Background

父 issue 的子片已经由外部设计流程创建为 GitHub native sub-issues，并以显式 `blocked_by` 表达依赖。编排器不负责重新分解 epic，也不让 LLM 猜测第二套依赖图。并发工作的安全边界是一个 parent base 和每个 child 各自独立的 branch / worktree。

## Decision

1. **只调度现成子片。** Family Admission Action 在首次启动与每次 re-entry 读取 live native membership、状态、标签和依赖，完成过滤与 cycle 处置并产出可运行集合和依赖交通事实；Generic Runner 只消费这些事实做调度，不重复抓取或分类。当前只支持一层 family；仍有 sub-issues 的 child 不作为可运行叶子，递归 family 留待后续设计。
2. **一个父现场、每子片一个独立现场。** Parent base 是唯一家族整合面；每个可运行 child 从当时的 parent base 切出 distinct branch / worktree。直接输入一个叶子 issue 时仍走 single，不虚构 parent base。
3. **增量合入而非整波 barrier。** 已完成 child 可独立进入 family integration；不等待同批 parked 或仍在运行的 child。合并、冲突处理、外部效果核验与 crash reconciliation 由 Family Integration Merge Action 自己拥有；准确调用顺序、父分支 Verification 与恢复接力只读 #869。
4. **依赖与局部暂停是交通状态。** Live `blocked_by` 决定哪些 child 可被放行。一个 child 的 decision gate 只阻塞自己、依赖它的下游与 final barrier；不影响独立 child。父分支 Verification 红灯时的暂停与恢复语义只读 #869，Runner 不读取验证内容。
5. **zero-runnable 不等于自动终局。** 从未建立 family scene 且没有 durable obligation 时可 quiet success；已有 scene 时，是否仍有待合入、park、shared-tail 或 cleanup 义务由 Canonical Delivery Flow 与 Lineage 保存的流程位置决定，不能因本轮没有新 child 就丢失。
6. **membership removal 是窄取消。** 未合 child 从 native sub-issues 移除后停止未来调度；若其 Worker Invocation 仍在运行，不杀进程、不删 worktree。实例不再运行后，由 Closure / Reclamation 只删除目标 worktree，保留 branch、Lineage / ledger、日志与 telemetry / 统计，不要求 success 或 normal exit，也不撤销已合代码。
7. **closed 不等于销毁。** Closed child 退出 runnable set 并满足 issue 依赖，但其现场在父流程 terminal-success 与显式 cleanup 前保留；reopen + ready 可复用原 request / scene。Closed 只表达 issue 工作流状态，不证明某个 commit 已在 parent base；代码可用性由专业 Action / worker 验证，Runner 不做 commit / HEAD 对账。
8. **Lineage 保存历史，不给 Runner 判卷。** Child 的完成、合入、park、关闭、移除与恢复位置可持久化供续跑和统计；具体 schema、Git reconciliation 与外部事实由 Lineage 和对应 Action 拥有。Runner 不读取 ledger 内容来判断专业工作是否完成。
9. **CMR module context 属于专业评审。** module scope 与 cross-module defer 由 reviewer / skill 读取和裁决；Runner 不解析 issue-body YAML、不声明 undeveloped module、不分类 finding。

## Considered Options

- **编排器自行分解父 issue**：否决。切片与依赖已经由设计流程发布，重复推断会制造第二真源。
- **整波完成后再统一合并**：否决。无关的慢任务或 parked child 会阻塞已完成子片及其下游。
- **Runner 读取 Git / ledger 做恢复裁决**：否决。Git 与外部效果 reconciliation 属于专业 Action，Runner 无权比较 HEAD、commit 或 schema。
- **关闭或移除即清空现场**：否决。普通 close / retry / resume / relay 必须保留现场；只有明确 membership removal 允许 ADR 0127 定义的窄删除。

## Consequences

- Family 与 single 复用同一 Canonical Delivery Flow 和 Action catalog；family 只增加 parent/child 交通状态与增量整合面。
- Distinct child branch / worktree 和唯一 parent base 是必须保留的隔离边界。
- Exact flow、review/fix matrix、shared tail 与 online review 不在本 ADR 复制，全部只读 #869。
- 生产 Runner 不因 issue 文本、ledger 形状、Git 状态或 worker 报告格式终止流程。
