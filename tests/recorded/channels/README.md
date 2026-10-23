# #1964 原生通道录件

源卷归档：`~/WorkSpace/vault/ak-cc-wiki/raw/ming-llm-runner/2026-10-23/1964-channels/`。

这里的 gzip 文件只压缩原始响应字节；解压后与源文件逐字节相同。没有重序列化、筛事件、删思考块、改正文或替换工具 ID。归档中的 `codex-fixture-provenance.json`、`pi-fixture-provenance.json` 记录源路径、字节数和 SHA256；哈希仅供核对来源，不用于测试约束生成内容。录件内的临时路径按原样保留；测试不打开那些路径或外部归档目录。

| 文件名（省略压缩后缀） | Codex：`codex-183740/<调用>/response.sse` | Pi：`pi-184816/<调用>/stdout.jsonl` |
| --- | --- | --- |
| scene-tool | 001-scene | — |
| scene | 003-scene | 001-scene |
| NightDeclaration | 004-NightDeclaration | 002-NightDeclaration |
| read-records | 005-simulation | — |
| simulation | 006-simulation | 003-simulation |
| Declaration | 007-Declaration | 004-Declaration |
| urgent | 024-urgent | 005-urgent |
| impeachment | 025-impeachment | 006-impeachment |
| gazette | 019-gazette | 013-gazette |

- Codex 使用现有订阅 HTTP 通道，模型 `gpt-6.1-sol`；保存的是响应 SSE，不是 `codex exec` 的另一套 JSON 事件。
- Pi 1.4.0 使用 `openai-codex/gpt-6.1-sol`，保存整次 CLI 调用的 stdout。上述两次游戏都从真实 HTTP 入口完成召对、退朝转译及十月至十一月的推进。
- `pi/empty.jsonl.gz` 来自另一次原生 CLI 探针 `pi-empty.jsonl`：显式请求空响应，宿主退出码 0，助手 `stopReason=stop`，正文为空，`agent_settled.aborted=false`。它不是游戏中自然发生的空流。命令和输入在归档回执中。
- 按现有 agent 名选回放，不扫描提示词。每个阶段保留一份完整响应；奏疏阶段复用一份录件，只验证通道与落账，不以它裁定其他派系的生成质量。Codex 的工具回包继续走真实应用工具；进程替身继续经实际 MCP 端点调用工具。
- 既有网页场景测试继续走 `/actions`，现在退朝并断言结构化夜结果 `translated`；没有对录件正文、措辞或条数新增断言。真实宿主验收只在归档，pytest 不调用宿主或真实模型。

## 尚未覆盖

Grok 槽位信任登记会写宿主配置，尚待授权，因此没有 Grok 原生录件。Pi 语义失败事件也尚无原生样本；该负向案保留原替身，不冒称原样回放。Claude 不在本轮真跑范围。此次录件替换不能代替真实过期凭证刷新、Grok 中途重试验收或新 HEAD 的庭审。
