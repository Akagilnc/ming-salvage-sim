# orchestrator

做任何技术决策之前，先看我们用的这个 Sandcastle 有没有（先翻它的文档 / GitHub issues），如果没有，网上搜索有没有现成的轮子可以用。

**除了编排器开发阶段**：任何启动（dogfood / 实跑）**严禁修改编排器代码，或任何影响编排器正常流程的 fix / 补丁 / `sh` 注入**。dogfood 的意义就是测**真实编排器在真实输入上的行为**；任何一次性过滤 / 补丁 / 注入都让这次跑失去意义、还会把真实输入里的问题糊过去。要排除或调整输入（比如某个 issue 不该进本轮），改 **tracker**（摘 sub-issue / 撤 label / 改依赖），不碰编排器、不在启动脚本里塞过滤。

**worker 真源边界：issue = 需求真源，worktree = 代码真源，image/soul/skill = 流程真源，runner = 调度真源。** runner 只负责切/挂 worktree、注入 `ORCHESTRATOR_ISSUE_NUMBER` / `ISSUE_NUMBER` / `ORCHESTRATOR_REPO` / `ORCHESTRATOR_SOUL` / 可用 auth、落必要运行参数文件（如 `.cmr-focus.md` / `.ship-focus.md`），然后读结构化终态。worker 必须用 `gh`  live fetch issue body + comments；临时离线先重试，auth 失败就 escalate 要人登录，禁止把旧 snapshot / 旧 prompt / 本地猜测当需求真源。worktree 已经挂进容器，worker 只看当前 worktree；runner 不把 issue 正文、wiki 摘抄、方法步骤塞进 prompt。

**`sc.run()` 严禁用 `prompt` 参数；传指令只准用 `promptFile`。** `prompt`（inline 字符串）是「临时把 method 手搓进调用点」的唯一入口——堵死它 = 手搓在 API 层就不可能。指令一律走 **`promptFile`**（指向一个**版本化、可评审**的 `.md` 文件）。而且 `promptFile` 的**内容必须 thin**：只准「读 baked soul / 触发对应 skill（`/tdd`、`/ak-cross-m-review`、`gstack-ship` …）+ 指向落盘运行参数文件 + 输出契约」，**绝不写 method**。怎么 review / 怎么 fix / 怎么收敛 / Claude 和 Codex 如何 invoke skill，全住在 versioned soul / skill / 镜像里；runner 不感知、不每轮换 prompt。理由实证：本仓三道 cmr 闸（step 4/5/6）全栽在「promptFile 里手搓 review-only / no-loop」而不是让 `invoke /ak-cross-m-review` 跑它自己的 loop。runner 退回纯调度（派容器 + 落参数文件 + 读终态 verdict），method/纪律全在 skill。**如果 promptFile 开始长成 mini-wiki，就是回归。**

**容器内（`sc.run`）产生的 commit 自动冠 `sandcastle:` 前缀**，由烤进镜像的 `image/hooks/commit-msg`（经 `git config --global core.hooksPath`）确定性强制——不靠 soul / promptFile 指示（那样会漏：gstack-ship 自己的 commit 绕过 soul）。用途：`git log --grep '^sandcastle:'` 框出某次 family run 的全部机器产出。可与模型层 `claude:` / `codex:` 前缀叠（`sandcastle: claude: …`，`sandcastle:` 在最前）。
