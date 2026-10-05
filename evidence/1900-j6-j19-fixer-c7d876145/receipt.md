# #1900 修内司回执 — J6 / J19（base c7d876145）

## 授权与跳过说明
- 末份判词（`06-1900-judge-c7d876145.json` 末 payload）未结仅 J6、J19。
- 根因判词已有取证与变异记录；本轮明确**无须猜诊断**（diagnosing-bugs Phase 3 猜因跳过，依据已有判词）。
- 官方能力已查：pytest `ExceptionInfo` / `.args` / `__cause__`；Python exception chaining。

## 分支 / 提交
- 工作分支：`ak-roles/1900-j6-j19-fixer-c7d876145`（自 c7d876145 新开）
- commitSha：见本轮 git 查询（提交后填入报告）

## J6
- 枚举：`j6_enum_fault_fidelity.py` → `j6-raises-raw.jsonl` / `j6-fidelity-candidates.jsonl` / `j6-members.md`
- 改动：三处最短负向案恢复原故障对象／诊断保真（非措辞锁）
- 聚焦：`focused-tests-final.log` — 53 passed in ~2.8s
- 变异：`run_mutations.py` → `mutations.log` / `mutations-summary.txt`
  - strong+wrong-primary：3 red
  - restore：3 green
  - weak+wrong-primary：3 false-green（证明旧弱断言假绿）
  - sources restored + final：3 green

## J19
- 枚举：`j19-ast.jsonl` / `j19-members.md` / `j19-rescan.txt`
- 改动：删除 `merge_participant_roster_entries` 的 `strict_incoming` 宽松开关及三处 kwargs；incoming 恒严格；保留 `_normalize_participant_roster` 通用能力与 equality 合并
- 纠正：旧证据「供非交办旧读缝」消费者不存在；冻结 evidence 不改写

## 未结（如实）
- J21 押解核账缺口登记：给事中／票庭，非本席补机制
- 不声称已 merge / 关票
