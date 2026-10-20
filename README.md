# 残明朱批：崇祯

![残明朱批：崇祯主页](docs/screenshots/home.png)

你是崇祯。

你知道十七年后北京城破，知道煤山那棵树在等你，也知道大明不是死于某一个敌人，而是死于国库空虚、辽东失血、流民四起、党争内耗、官僚敷衍、军队欠饷和一次次“朕已知悉”之后的无力。

但这一次，朕已知悉不能只是四个字。

你可以召见大臣，追问户部银子去了哪里，追问兵部边军为什么又欠饷，追问司礼监宫里谁在递话，追问锦衣卫地方官到底有没有瞒灾。你可以下旨、任免、追责、赈灾、练兵、加税、清丈、议和、开战。大臣会给你建议，也会推诿、隐瞒、站队、阳奉阴违。

你以为自己写下的是圣旨。真正落到地方时，可能已经变成另一件事。

这不是一款“选择 A/B/C”的历史问答游戏，而是一场围绕晚明国家机器的对话式政略模拟：你说什么、信谁、逼谁、放过谁，都会变成下一月的财政、军情、民变和朝局。

这里没有开局送神兵，没有天降忠臣，没有科技树一键升级，也没有一键中兴。你能依靠的只有奏报、大臣嘴里的半真半假、账本上的银子、欠饷的边军、动乱的地方，以及自己的判断：怎么借力打力，怎么拆东墙补西墙，怎么把一句话说成一道能落地的旨。

## 本分支是什么

本仓库基于 [wangwei-ying3/ming-salvage-sim](https://github.com/wangwei-ying3/ming-salvage-sim) 继续开发，方向是一个更重视后果落地与状态可信的晚明皇帝模拟器。

> **AI 负责奏对、推演和人心；引擎负责账本、状态和后果。**

当前仍是实验分支。重写后的游戏只有 `ming/` 一套：前端 → 召对／过月使用者 → 中间层 → 实体与事件账本。旧实现与迁移过程查 git 历史；历史文档不代表当前已迁入的玩法。

## 安装与启动

需要 Python 3.14、Node.js 20+，以及 OpenAI 兼容 API 或本机已安装且已登录的 Claude CLI。

```bash
git clone https://github.com/Akagilnc/ming-salvage-sim.git Ming_LLM
cd Ming_LLM
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
./start.sh
```

`start.sh` 安装 Python 依赖、构建前端、启动本地浏览器入口。可用 `--port 8010` 指定端口，已有前端构建时可加 `--no-build`。手动等价入口：

```bash
(cd web && npm ci && npm run build)
python -m ming.desktop
# 原生桌面窗口：python -m ming.desktop --desktop
# 开发数据目录：python -m ming.desktop --directory /tmp/ming-dev
```

启动先到主菜单：新开一局、继续（最新存档）、读取存档、设置。每局一个 SQLite 文件，每次落账自动保存，没有存档位或另存。默认存档与模型设置在 `~/.ming/saves/`。

API 地址、key、模型或 Claude CLI 后端在主菜单设置中填写。网页／桌面设置不从 `.env` 读取；`.env.example` 仅说明命令行开发入口的可选环境变量。CLI 使用本机的 `claude`，四工具经原生 MCP、戏文经 `stream-json` 交付，不修改宿主配置或替用户登录；进程自然结束，不强杀。关窗正常退出会先等在飞工作，浏览器断线不打断已接受的说话动作。

## 怎么玩

从御案进入召对，直接说话、宣人、追问或下旨。皇帝吩咐的事由领旨人拟成正式圣旨念出，认可才成旨，没表态即默拒。

退朝后后台转译整夜，已经发生的实况落账，旨意留待过月处理。过月有待批项时在奏折匣中批红；结果由邸报呈上。错误提示附本局 `.errors.log` 路径，待重试的动作从原处继续。

重开未收夜的存档会续到最后一轮；已收夜缺转译结果的夜补转，已落不重落。

## 命令行开发入口

开局导入与对账不调用模型：

```bash
python -m ming new --directory saves
python -m ming read --db saves/<新局文件>.sqlite --identity audit
python -m ming read --db saves/<新局文件>.sqlite --identity audit --replay
```

`new` 输出新局路径；继续操作使用该路径。默认读取皇帝材料，`audit` 用于内部对账，`--replay` 从事件重放读取。

召对使用支持原生文本和工具的 Pydantic AI 模型；OpenAI 兼容端点用自己的 `OPENAI_BASE_URL`、`OPENAI_API_KEY` 环境变量。仅支持 Chat Completions 的端点选 `openai-chat:` 前缀（`openai:` 默认走 Responses）。也可选 `--scene-model claude-cli`。转译默认沿用已登录的 `claude -p`，可用逐次参数换成 API 模型，不改宿主配置：

```bash
python -m ming audience --db saves/<新局文件>.sqlite \
  --scene-model openai-chat:<模型名> --translation-model openai-chat:<模型名>
```

stdin/stdout 为逐行 JSON。进入时输出夜 id；输入示例：

```json
{"action":"say","words":"宣杨嗣昌。"}
{"action":"dismiss"}
{"action":"open"}
{"action":"drain"}
{"action":"state"}
{"action":"month"}
{"action":"choose","petition":"<奏疏 id>","option":0}
```

`say` 返回原样带标记的戏文及夜状态。`dismiss` 请求收夜；若仍有回话在生成，先完成并落账最后一轮，再记收夜。打字退朝由场景模型调退朝工具走同一路径。收夜后后台转译整夜一次，退朝不等；`open` 续未收夜或开新夜。`drain` 等在飞回话与所有已收夜的转译；EOF 也先排空再关档，不自动收夜。

夜的 `result` 为 `null`、`translated` 或 `unhandled`，状态只读账本。「接不住」不含字段诊断，调用／传输／代码异常仍抛出。

`month` 立即返回，`month_running` 表示后台仍在执行；`state` 可查看日期、奏折匣 `petitions` 与原始 `month_error`。选项下标从 0 起；夜里出现的奏疏也可用 `choose` 批。`drain`／EOF 等候后台工作。重开后再次过月，只补账本里缺的产物；没有另立进度文件。

单次开发调用也可用：

```bash
python -m ming month --db saves/<新局文件>.sqlite \
  --model openai-chat:<模型名> --translation-model openai-chat:<模型名>
python -m ming choose --db saves/<新局文件>.sqlite \
  --petition <奏疏id> --option 0 --model openai-chat:<模型名> \
  --translation-model openai-chat:<模型名>
```

错误与模型原文写在存档旁的同名 `.errors.log`（Python 标准日志）。API 的 5xx／超时按 #1846 共三次、间隔五秒，429 不自动重试；夜里预推只试一次，失败由过月补跑。声明校验仍由 Pydantic AI 单层回喂；CLI 的不可分类错误保留原文，不猜 HTTP 状态。

## 开发检查

```bash
ruff check --ignore-noqa .
lint-imports
pyright
# 聚焦示例；全量执行时点见 CLAUDE.md「测试分级」
python -m pytest tests/test_web.py -q
(cd web && npm ci && npm run build)
```

CI 命令以 [ci.yml](.github/workflows/ci.yml) 为准。P8、禁正则、禁裸 noqa 和 Python 单文件行数检查覆盖全仓，pyright strict 与分层检查限定游戏包。

## 目录与文档

```text
.
├── launcher.py              # 桌面 Web 窗口入口
├── ming/                    # 使用者、中间层、账本与包内服务
├── tests/                   # 游戏契约测试与录制样本
├── content/                 # 开局素材与提示词；未使用的数据保留待迁入
├── web/                     # 网页界面
├── docs/                    # 设定、架构、ADR 与历史开发资料
├── scripts/                 # 构建与素材工具
└── requirements.txt         # Python 依赖
```

- [账本与落账](docs/adr/0159-ledger-entities-events-and-landing.md)
- [召对北极星](docs/AUDIENCE_NORTH_STAR.md)
- [领域词表](CONTEXT.md)
- [开发规则](CLAUDE.md)
- [历史 TODO / TOFIX](TODOS.md)

## 打包发行（桌面包 · 自部署）

群友各自跑实例，LLM 后端在游戏内设置。PyInstaller 冻结后端、前端与 content，pywebview 渲染原生窗口。

```bash
pip install -r requirements.txt -r requirements-release.txt  # Python 3.14 venv
# Windows 打包另装：pip install -r requirements-release-windows.txt

scripts/build_release.sh        # macOS / Linux
scripts\build_release.bat       # Windows

# macOS   → dist/Ming_LLM-macos.zip   → Ming_LLM.app
# Linux   → dist/Ming_LLM-linux.zip   → Ming_LLM + _internal/
# Windows → dist/Ming_LLM-windows.zip → Ming_LLM.exe + _internal\
```

脚本先构建前端，再走 `Ming_LLM.spec`，最后打 zip。`web/dist` 被 `.gitignore` 排除，不先 build 会缺前端。spec 在前端未构建、`content/buildings.json` 带金手指或有未提交改动时响亮中止。

解压后启动应用，自动开 webview 原生窗口；`MING_DEBUG=1` 开 devtools。默认数据位置与后端设置见「安装与启动」。

金手指建筑（皇家天佑金矿／大明中央银行／帝国航空）只活在开发工作区，发行包不带。

## 许可与致谢

本仓库继承上游 [wangwei-ying3/ming-salvage-sim](https://github.com/wangwei-ying3/ming-salvage-sim) 的 **GPLv3** 许可。发行包按 GPLv3 附源码指向：<https://github.com/Akagilnc/ming-salvage-sim>。

感谢原项目提供的晚明皇帝模拟器框架、内容基础和玩法方向。本仓库继续探索状态可信、结构化落库和长期跑局稳定性。
