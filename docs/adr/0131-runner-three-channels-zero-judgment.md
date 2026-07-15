> **修订（2026-07-15，#925 落地）**：通道(b) 由 open-count 关环改为判词三态
> `converged | continue | escalate`（ADR 0132）。禁双轨：一台判官机多处开庭，
> 不得并行保留 open-count 机械关环。completion 条款中「干净退出 + 合法 sidecar」
> 的最终统一仍随 #928 落地；落地前其余既有完成信号路径按现文。
>
> **修订（2026-07-15，#930 落地）**：family 后段 completeness / correctness 双闸
> 同样只消费判词三态（两庭一机）；family 路径上的 open-count 第二台数数机删除。

Status: Proposed

# 0131: runner 三通道零判断权

## 决定

Runner 是交通警察，只准处理三种交通信号：

1. 进程的 exit code
2. **判词三态** `converged | continue | escalate`（#925 / ADR 0132；取代原
   reviewer 自报 open-count 关环——`0` 关环 / `>0` 继续 的机械读数）
3. worker 自己按下的 decision gate

三者之外零判断权，且从不读取报告、findings 散文、格式、测试、commit、HEAD、
diff、PR 或其他完成证据。专业判断与外部副作用核验属于对应 worker/Action，
准确目标拓扑只读 live #869；可执行钉由 #869 Testing Decisions 对应的实施票
落地，不属于本 ADR。

判词来自持久 verify 判官工位（S3/S6 等同机）；runner 仅读枚举态与 schema
固定字段做拓扑，不解析 prose 过滤 findings。

## 取代

本决定只取代 ADR 0050、0062、0129、#598、#875 与旧 README 中那些让 Runner
校验卷面、派生或对账 count、依据 commit/HEAD/证据重试或裁决、替 worker 合成
decision/failure 的条款；其余专业契约继续保留，进程崩溃的机械重试与 worker
自验仍在各自所有者内。

原通道(b)「open-count 关环」表述废止——不得与判词三态双轨并存。

## 后果

Runner 侧格式/schema 法庭、count 对账、commit/HEAD/diff/PR 检查与完成证据
gate 均必须删除；操作真源为 `orchestrator/CLAUDE.md` 的“铁律 0”，专业交卷
契约归 ADR 0130，finding 搬运归 ADR 0129，交付拓扑归 #869，判官工位归
ADR 0132 / #925。
