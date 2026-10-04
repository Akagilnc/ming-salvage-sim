# #1834 修内司回执：F3 / F14（判词 768cb88e1）

依据：fix-packet + 判词 `00-1834-judge-768cb88e1.json`；全局 #13 / 质量法；P7 射程（固定界面字段合法）。
禁止 amend/rewrite/push/PR/stash。**未合并，不声称关票。**

## 未结两类（判词边界全文，样本非白名单）

1. **F3**：正文断言清理误删合法契约，并留下无效测试。双向复核本轮全部测试处置。
2. **F14**：探针阶段标签冒称事务已关闭。纠正现行脚本标签与证据解释；不改写历史执行输出。

## 互联网现成方式（动手前）

查 pytest 官方 assert 文档与 bytes 相等实践：确定性夹具字节用 `assert actual == expected`；空测无断言不算测试。本次优先恢复/删除既有契约，不新造平行机制或证明性测试。

## F3 枚举命令

```sh
git diff --unified=0 52809cdf3 HEAD -- tests/ web/   # 本轮 purge 相对基线的断言删除全集
git diff --unified=0 HEAD -- tests/ web/             # 本提交工作树叠加（恢复/删空壳）
```

成员表真源：

- `f3_bidirectional_disposition.jsonl`（逐条）
- `f3_member_table.md`（分类表）

| 处置 | 数量 | 说明 |
| --- | --- | --- |
| RESTORE_THIS_ROUND | 12 | 调用输入 / 磁盘固定原文 / 身份 / periodLabel / 结构化 DTO 字段 |
| KEEP_DELETED_FREE_PROSE | 231 | 生成/夹具自由正文锁，不机械恢复 |
| DELETE_EMPTY_SHELL | 7 | 删失去所称行为证明的空壳用例 |
| REMOVE_LEN_SUBSTITUTE | 1 | 去掉 `len(replies)==1` 长度替代 |
| RESTORE_MISSED | 0 | 复扫无漏恢复 |
| EMPTY_SHELL_RESCAN | 0 | 触及面复扫无残留空壳 |

### RESTORE（合法契约）

- `tests/test_scene_llm_1836.py`：`calls == [宣…, "边饷如何？"]`（确定性调用输入）
- `tests/test_material_directory_1830.py`：写入→`read_material` 字节相等；密令 `original in read`（磁盘固定原文 / CR）
- `tests/test_due_review_621.py`：`origin_context` / `criterion_text` 结构化字段回读
- `web/.../modals.test.tsx`：thinking 行身份「洪承畴」；报头 `periodLabel` 正向月
- `web/.../settlementGazettePanel.test.tsx` / `appDurableWiring.test.tsx`：`periodLabel` 正向月
- `web/.../situation.test.tsx`：上疏人身份「杨嗣昌」

### DELETE_EMPTY_SHELL

- `test_clichat_normal_reply_still_returns`
- `test_commitment_progress_contexts_are_structured`
- `modals`: ordinary history reduction / whole chronological night
- `situation`: detail modal parentheses
- `staleGuard`: 未切人时响应/历史正常应用（仅余空壳）

未恢复生成散文；未加长度/非空替代；未新造平行测试或生产机制。

## F14 标签纠正

- 脚本 `evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py`：原 `CLOSED_*` 实为只推进日历、**未** `declare_closed`。
- 现行标签改为 `CALENDAR_ADVANCED_WORLD` / `CALENDAR_ADVANCED_PUBLIC`；文档注明不得读作 `affair_status=closed`。
- **不改写**历史文件 `evidence/1834-fixer-f9-f12-f3/probe-current.txt` 中的旧 `CLOSED_*` 执行输出；解释以本回执与新 `probe-current.txt` 为准。
- 生产关闭读取有效性维持前判；本片不新增关闭机制。

## 聚焦测试（七 BIN；非全量）

```sh
env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD \
  ../Ming_LLM/.venv/bin/python -m pytest -q \
    tests/test_scene_llm_1836.py \
    tests/test_material_directory_1830.py \
    tests/test_due_review_621.py \
    tests/test_audience_restore_505.py \
    tests/test_cli_runner_error_typed_1299.py \
    tests/test_decree_commitment_settlement_229.py \
    -p no:cacheprovider --basetemp=/tmp/1834-fixer-f3-f14-mut/pytest-focus
```

结果（`focused-pytest.txt`）：**95 passed**，pytest **6.56s**，wall **real 7.25s**。

Web vitest：本机无 `web/node_modules`，未跑。

## 临时变异红绿（不改仓库；证毕清理 /tmp）

插件：`/tmp/1834-fixer-f3-f14-mut/audit_mutation.py`（证据见 `mutation-proof.txt`）。

| 案 | 变异 | 结果 | 时长 |
| --- | --- | --- | --- |
| scene 调用输入 | `AUDIT_MODE=wrong_player_input` | **1 failed**（`边饷错了？`≠`边饷如何？`） | real 1.28s |
| scene 基线 | 无变异 | **1 passed** | real 1.22s |
| material 读取 | `AUDIT_MODE=empty_read_material` | **1 failed**（`'' != 经历正文`） | real 1.43s |
| material 基线 | 无变异 | **1 passed** | real 1.12s |

## 探针复跑

`probe-current.txt`：`OPEN_*` / `CALENDAR_ADVANCED_*` / `RESTORE_*`；ALL_GREEN；real **2.82s**。无 `CLOSED_*` 新标签。

## 复杂度 / 合法性

- 无新增来源账、摘要、模型调用、输出擦洗、生产出口。
- 邻票 #1873 不施工。
- 自查二连 done。

## 剩余范围

- #1873 邻票文字事实来源缺口。
- 同进程顺序污染（前轮已记）— 另票。
- Web vitest 需 `web/node_modules`。
- 分支未合并 → **不声称 #1834 关闭**。
- 御史台：本轮触及此前 P1 生产修复之后的 P2/P3 证据面；台院条件仍依判词。
