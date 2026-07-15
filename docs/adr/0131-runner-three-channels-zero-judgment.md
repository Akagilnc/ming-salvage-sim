> **修订预告（2026-07-15）**：本 ADR 之〔通道(b) open-count 关环 → 判词三态；completion 条款 → 「干净退出 + 合法 sidecar」唯一结论〕经 #919（Accepted，见 ADR 0132）拍定修订，随对应切片落地生效；落地前按现文执行，评审时勿以现文否决 #919 已拍方向。

Status: Proposed

# 0131: runner 三通道零判断权

## 决定

Runner 是交通警察，只准处理三种交通信号：进程的 exit code、reviewer 明确自报的 open-count（0 关环，>0 按 #869 fixed topology 继续）、worker 自己按下的 decision gate；三者之外零判断权，且从不读取报告、findings、格式、测试、commit、HEAD、diff、PR 或其他完成证据。专业判断与外部副作用核验属于对应 worker/Action，准确目标拓扑只读 live #869；可执行钉由 #869 Testing Decisions 对应的实施票落地，不属于本 ADR。

## 取代

本决定只取代 ADR 0050、0062、0129、#598、#875 与旧 README 中那些让 Runner 校验卷面、派生或对账 count、依据 commit/HEAD/证据重试或裁决、替 worker 合成 decision/failure 的条款；其余专业契约继续保留，进程崩溃的机械重试与 worker 自验仍在各自所有者内。

## 后果

Runner 侧格式/schema 法庭、count 对账、commit/HEAD/diff/PR 检查与完成证据 gate 均必须删除；操作真源为 `orchestrator/CLAUDE.md` 的“铁律 0”，专业交卷契约归 ADR 0130，finding 搬运归 ADR 0129，交付拓扑归 #869。
