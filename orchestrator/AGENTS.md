# AGENTS.md — orchestrator

**三句话（宪法最重要的部分，动手前先背，每刀之前先自检）：**

> 一、runner 数 exit code——进程死活，不读任何字。
> 二、runner 读 judge 自报 status——`converged|continue|escalate`（#925 / ADR 0131 channel (b)）；拓扑写死边，不读 open-count 当主通道。
> 三、runner 转决策门——只转运 worker 自己按的门，转运不裁决。
> 三件之外，runner 零判断权。**没有例外**——git/host 真源例外已废止（owner 2026-07-13）：coder/ship 说 OK 就是 OK，自证归 worker soul。

**建闸双门槛（与三句话同位阶）**：新增任何防御/校验/机制前先过两问——①合宪吗（不建庭、不读卷、不替按门）②值得吗（场景发生过吗、概率×后果 vs 投入；下游智慧体环兜底是默认答案）。runner 的失败模式选「便宜地错、下游自愈」。

任何对 runner 代码的 finding / 修法，落笔前先对三句自检：是否让 runner 干了三件事之外的事？是 → 该 finding/修法本身违宪。全文与推论（决策门准入原则、按角色真源分治、kill-axis、别一边拆一边建）见本目录 [`CLAUDE.md`](CLAUDE.md) 铁律 0 与 ADR 0131。
