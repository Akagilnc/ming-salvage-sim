# AGENTS.md — orchestrator

**三句话（宪法最重要的部分，动手前先背，每刀之前先自检）：**

> 一、runner 数 exit code——进程死活，不读任何字。
> 二、runner 读 reviewer 自报的 open-count——说几条就是几条：0 收敛，>0 环继续（fix→fresh 复审固定交替，轮到谁由拓扑写死）。
> 三、runner 转决策门——只转运 worker 自己按的门，转运不裁决。
> 三件之外，runner 零判断权。

任何对 runner 代码的 finding / 修法，落笔前先对三句自检：是否让 runner 干了三件事之外的事？是 → 该 finding/修法本身违宪。全文与推论（决策门准入原则、按角色真源分治、kill-axis、别一边拆一边建）见本目录 [`CLAUDE.md`](CLAUDE.md) 铁律 0 与 ADR 0131。
