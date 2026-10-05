# J20 成员表：自由标题推断事件身份（完整类定义）

## 类定义
删除生产中以自由标题推断事件身份的路径及只保该旧行为的测试、失效说明；保留合法结构化身份通道。不另造身份补救、护栏或替代机制。

## 枚举命令（不得收窄为旧符号）
见 `j20-enum-raw.txt`、`j20-deep.txt`、`j20-verify.txt`、`j20-enum-cmds.txt`：
- 生产：title/name 邻近 event_id 绑定/查询；`bind_decisions_to_candidate_events`；`event_by_id`/`gather_candidate_events` 身份轴；候选 title 等值门；SQL/查找 by title
- 测试/文档：只保标题补绑的期望与失效说明
- Web：`decisionRouting` 等对 title 的用法

## 机械候选全列表
- 原始命中：`j20-enum-raw.txt`（330 行）、`j20-deep.txt`、`j20-verify.txt`

## 语义处置（每类候选均有）

| 候选/组别 | 语义 | 处置 |
|---|---|---|
| `settlement_payload.bind_decisions_to_candidate_events` 原 title_to_ids 补绑 | 生产违法依赖 | **已删**（上轮）；本轮确认无回归 |
| 同函数 docstring「以快照唯一标题」 | 失效说明 | **已改**为仅结构化通道 |
| `session.prepare_rescript_prewrite`「以候选快照重绑」注释 | 失效说明误导 | **本轮改**为显式 id / 合法 dossier: |
| `tests/test_decision_event_binding_389` 无 id 靠标题得 candidate | 只保旧行为 | **已改**为结构化通道（无 id→解绑） |
| `tests/test_pihong_dossier_1490` dossier: 保留 | 合法结构化 | **KEEP** |
| `session`/`decree` 调用 bind | 入口接线 | **KEEP**（行为随删简） |
| `issues`/`materials`/`knowledge` 经 `event_by_id`/`gather_candidate_events` 用 **id** | 合法结构化 | **KEEP** |
| `issues` 诊断串嵌入 `event_title` | 呈现/诊断，非身份推断 | **KEEP**（组别例外：不写回 event_id） |
| `db` JOIN `e.title AS event_title` | 读侧展示列 | **KEEP** |
| `web/src/decisionRouting.ts` `typeof title === "string"` | 形状校验字段存在，提交身份靠 decision_key | **KEEP**（非 title→id） |
| ADR 0115 文本捞回禁令 | 法源 | **KEEP**（不改 ADR） |

## 剩余
- 生产标题补绑路径：**无**
- 只保旧行为的测试：**无**
