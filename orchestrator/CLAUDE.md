# orchestrator

做任何技术决策之前，先看我们用的这个 Sandcastle 有没有（先翻它的文档 / GitHub issues），如果没有，网上搜索有没有现成的轮子可以用。

**除了编排器开发阶段**：任何启动（dogfood / 实跑）**严禁修改编排器代码，或任何影响编排器正常流程的 fix / 补丁 / `sh` 注入**。dogfood 的意义就是测**真实编排器在真实输入上的行为**；任何一次性过滤 / 补丁 / 注入都让这次跑失去意义、还会把真实输入里的问题糊过去。要排除或调整输入（比如某个 issue 不该进本轮），改 **tracker**（摘 sub-issue / 撤 label / 改依赖），不碰编排器、不在启动脚本里塞过滤。

**`sc.run()` 严禁用 `prompt` 参数；传指令只准用 `promptFile`。** `prompt`（inline 字符串）是「临时把 method 手搓进调用点」的唯一入口——堵死它 = 手搓在 API 层就不可能。指令一律走 **`promptFile`**（指向一个**版本化、可评审**的 `.md` 文件）。而且 `promptFile` 的**内容必须 thin**：只准「**触发 + `invoke` 对应 skill（`/tdd`、`/ak-cross-m-review`、`gstack-ship` …）+ 指向落盘的运行参数文件**」，**绝不写 method**（怎么 review / 怎么 fix / 收敛 drift 全住在 versioned skill 里）。运行参数（diff 范围 / scenario / squad / focus / snapshot）经**落盘文件**传，不写进 promptFile 正文。理由实证：本仓三道 cmr 闸（step 4/5/6）全栽在「promptFile 里手搓 review-only / no-loop」而不是让 `invoke /ak-cross-m-review` 跑它自己的 loop。runner 退回纯调度（派容器 + 落参数文件 + 读 skill 的 `CMR-VERDICT`），method/纪律全在 skill。注意 **Claude 与 Codex invoke skill 的机制不同**（Claude=`Skill` tool；Codex=它自己的 skill 加载），由 soul/镜像处理，runner 不感知。

**所有经 Sandcastle（`sc.run`）在容器里产生的 commit，统一冠 `sandcastle:` 前缀**（置于最前，如 `sandcastle: feat(transit): #346 …`）。理由：一眼区分**编排器容器产出**的 commit vs **人 / 主 session 手驱动**的 commit——`git log --grep '^sandcastle:'` 即可框出某次 family run 的全部机器产出，审计 / 回溯 / 清理都靠它。落地：各 worker 的 **soul / `promptFile`**（coder / coder-fix / merger / ship）指示容器内 agent commit 时带此前缀；容器内 agent 是 Claude 还是 Codex 不影响——前缀标的是「来自沙堡容器」，不是哪个模型（模型层 `claude:` / `codex:` 前缀是仓库另一套约定，二者可叠：`sandcastle: claude: …`，但 `sandcastle:` 必在最前）。
