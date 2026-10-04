# J6 处置说明（续轮：151 候选语义闭环）

## 类定义（未收窄）

非契约内部证明、mock 替代被测行为、helper 专测、退役行为、非契约文字锁、内部 oracle、调用 mock；必要闸负向保留真实入口+实际结果；原文无损契约 ≠ 拼装材料措辞锁。

## 证据分层

| 文件 | 含义 |
|---|---|
| `j6_enumerate_universe.py` + `j6-universe.jsonl` | 全仓测试声明全集（机械） |
| `j6_flag_structural_candidates.py` + `j6-structural-candidates.jsonl` | 结构信号**候选** |
| `j6-candidate-disposition.jsonl` | **当前 151 候选**语义处置（权威） |
| `j6-class-members.jsonl` | 含判词样本 + 本轮 delete/migrate 史 + 候选处置 |
| `j6-expanded-assert-calls-disposition.jsonl` | 扩扫 assert-calls 相关形式 |

禁止把 structural-candidates 或 universe 当作 retain 结论。

## 复扫计数

- universe：2879
- structural candidates：151（private_helper 92 / web_calls 55 / meta 3 / text_lock 1）
- disposition coverage：151/151
- 本轮删除后候选由 161→151

## 核验

```sh
python3 evidence/1900-j18-j6-retire-fixer/j6_enumerate_universe.py
python3 evidence/1900-j18-j6-retire-fixer/j6_flag_structural_candidates.py
python3 -c "import json; rows=[json.loads(l) for l in open('evidence/1900-j18-j6-retire-fixer/j6-candidate-disposition.jsonl')]; print(len(rows), set(r['action'] for r in rows))"
```
