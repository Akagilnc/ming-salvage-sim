# #1968 原生档位事实单（2026-10-24）

施工前读取本机 `claude --help`、`grok --help`、`pi --help`，并查官方文档；游戏不校验档位词，不解析警告，也不补宿主能力。

| 通道 | 实际传入位置 | 查得的原生词 |
| --- | --- | --- |
| claude-cli | `--effort` | low, medium, high, xhigh, max（本机 help） |
| grok | `--reasoning-effort`（help 列 `--effort` 为别名） | 官方 CLI reference 与 settings reference 均未穷举取值；缺口如实保留，不自行定义 |
| pi | `--thinking` | off, minimal, low, medium, high, xhigh, max（本机 help） |
| codex | Pydantic AI `openai_reasoning_effort` → Responses `reasoning.effort` | none, minimal, low, medium, high, xhigh, max（依赖 openai `ReasoningEffort`） |
| api | Pydantic AI `openai_reasoning_effort` → Chat Completions `reasoning_effort` | 同一依赖类型，模型是否支持由 provider 决定 |

来源：
- https://code.claude.com/docs/en/model-config.md#adjust-effort-level
- https://docs.x.ai/build/cli/reference.md （`--effort <LEVEL>`）
- https://docs.x.ai/build/settings/reference.md （`default_reasoning_effort` / `reasoning_effort`，没有列词）
- https://ai.pydantic.dev/models/openai/
- 本机 Pydantic AI 2.57.0 的 `pydantic_ai/models/openai.py`、`pydantic_ai/models/openai_codex.py`，以及依赖的 `openai/types/shared/reasoning_effort.py`。

已知缺口依票面：pi 原生可能只警告并忽略非法档位；游戏照原生继续，不承诺非法值必失败。模型名中的 pi `:<thinking>` 后缀仍原样交宿主；单独填档位时也原样传旗，优先关系由宿主决定。
