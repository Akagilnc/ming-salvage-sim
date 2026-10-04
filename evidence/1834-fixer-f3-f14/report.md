# #1834 修内司回执：F3 删除侧返修（rejudge）

依据：`evidence/1834-fixer-f3-f14/rejudge-deletion-side.json`（本 session 自建授权材料，随回执保留）。
F14 本轮不处理。禁全量 / kill / stash / amend / rewrite / push / PR。未合并，不声称关票。

## 对本局纠正

前轮只对「当前仍在的断言」做 KEEP，对「已删除断言」批量标 `KEEP_DELETED_FREE_PROSE`。
判词：样本非白名单；须逐条读旧/现源码与夹具来源，独立固定输入透明输送一律恢复；裸 `read_material` 空壳恢复或删除。

## 范围

- 比对基线：`52809cdf3` → 施工前 HEAD
- 删除侧 assert/expect 全集：**175** 条
- 处置：**175 RESTORE**（夹具/mock/声明种子 / 磁盘原文 / 独立输入搬运 / 否定夹具）
- 裸 `read_material`：**22** 处 —— 20 REACHABILITY + 2 PATH_CONFINEMENT（非删断言留下的空壳；点名空壳已恢复内容断言）

点名复核样本（已恢复）：
- `tests/test_on_scene_immediate_write_1839.py` — `arm_injury` / `death_rumour in read_material`
- `tests/test_gazette_author_1862.py` — `_PUBLIC_FACT` / `_PLAIN_DOSSIER_FACT` / `_PRIVATE_KEEP` / `_REPORT`
- `tests/test_public_projection_consistency_1830.py` — `original in disk/direct/api`
- `tests/test_month_chain_1847.py` — `fact_body in carrier`
- `tests/test_audience_translate_1837_reopen.py` — `query in read_material`

## 证据

| 文件 | 作用 |
| --- | --- |
| `rejudge-deletion-side.json` | 最新判词原文 |
| `f3_deletion_side_member_table.md` | 175 条成员表（来源+语义处置） |
| `f3_deletion_side_members.jsonl` | 机器可读成员 |
| `f3_bare_read_material_disposition.jsonl` | 裸 read_material 逐条 |
| `mutation-red.txt` / `mutation-green.txt` | 恒空串变异红 / 正常绿 |
| `focused-pytest.txt` / `focused-vitest.txt` | 聚焦验证 |

## 复杂度 / 合法性

- 无新增机制、平行测试、生产出口、分类脚本。
- 仅恢复既有契约断言；自查二连 done。

## 关票声明

分支未合并 → **不声称 #1834 关闭**。
