# 技术栈与合法代码形状

Status: accepted（2026-10-18 owner 定；2026-10-30 补记）

重写选 Python 一栈（owner `55904b0a-9689-44a0-9258-0f8d58674e8c`：「A 吧。我对微软的东西没什么好感」），代码只许三种形状。逐字抄自 #1943 条款 3；读表写法以 ADR 0160 为准。

- 账本：eventsourcing（SQLite 后端，一局一个文件）；写法只许 `Aggregate`＋`@event` 一种，可读材料由投影产出。引入目的：旨意落账只有一种写法——往对应的实体上记一个事件，不再每种旨意各写一套落库代码。每个实体、每件事务各一个 Aggregate；开局导入是建实体，不是游戏事件。
- 转译：Pydantic AI，声明以 `output_type` 定义；接 OpenAI 兼容端点或命令行宿主（官方 `Model` 子类适配）；用尽抛出的异常只在一处接住，落成「转译失败」事实。
- 约束：ruff 设稳定规则 PLR0915／PLR0913／PLR0912／PLR0911（语句 200、参数 5、分支 12、return 6）与 `TID251` 禁正则模块。局部变量 15 用 PLR0914，须显式开启 preview。单文件 1000 行不设 ruff 规则（ruff 无此项），由 CI 一条行数计数咬，超限失败。import-linter（`protected` 合约：账本只被中间层导入；分层合约）、pyright；CI 禁裸 `# noqa` 与 per-file-ignores 豁免。合法代码形状只有三种：事件／聚合、声明 schema、带 `output_type` 的模型调用；三种之外的代码须说明为什么存在，说不出即删。
- 使用者层不引工作流框架；流程走到哪一步也是账本里的事实。
- 打包沿用 PyInstaller＋pywebview。
