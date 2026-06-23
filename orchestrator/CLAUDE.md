# orchestrator

做任何技术决策之前，先看我们用的这个 Sandcastle 有没有（先翻它的文档 / GitHub issues），如果没有，网上搜索有没有现成的轮子可以用。

**除了编排器开发阶段**：任何启动（dogfood / 实跑）**严禁修改编排器代码，或任何影响编排器正常流程的 fix / 补丁 / `sh` 注入**。dogfood 的意义就是测**真实编排器在真实输入上的行为**；任何一次性过滤 / 补丁 / 注入都让这次跑失去意义、还会把真实输入里的问题糊过去。要排除或调整输入（比如某个 issue 不该进本轮），改 **tracker**（摘 sub-issue / 撤 label / 改依赖），不碰编排器、不在启动脚本里塞过滤。

**严禁在 `sc.run()` 用 `prompt` 参数传指令。** 容器要做什么，由它的 **soul + 镜像里的 `CLAUDE.md ## Skill routing`** 自己 `invoke` 对应 skill（`/tdd`、`/ak-cross-m-review`、`gstack-ship` …）；运行参数（diff 范围 / scenario / squad / focus / snapshot）一律经**落盘文件**传，不写进 prompt。理由：`prompt` 参数是「把 method 手搓进 prompt」这个反模式的**唯一入口**——本仓三道 cmr 闸（step 4/5/6）全栽在「prompt 里手搓 review-only / no-loop」而不是 `invoke /ak-cross-m-review`。**堵死 `prompt` 参数 = 让手搓在 API 层就不可能**；runner 退回纯调度（派容器 + 落参数文件），所有 method/纪律住在 versioned skill 里。注意 **Claude 与 Codex invoke skill 的机制不同**（Claude=`Skill` tool；Codex=它自己的 skill 加载），由 soul/镜像处理，runner 不感知。
