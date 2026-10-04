# #1897 R1/R2 修内司回执（最终自验轮）

- 施工分支：`ak-roles/issue-1897-r1-r2-fix`
- 判词：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a107cd-efa4-7e4e-a948-3dc08952f664@fixer/attachments/00-1897-judge-e37942414.json`（R1/R2）
- 未 push / 未开 PR / 未 amend / 未 stash

## 根因

上轮谓词曾收窄为 `[:N]`；续修清 strip / strip-判空覆盖 / 固定文案拼装后，证据误写不存在的 `scripts_or_inline_ast_enum.py`，且枚举范围只写 ming_sim。本轮纠正为全仓 `git ls-files` 可执行 AST，并补清残留类成员。

## 处置

- 生产简化（行为不变）：`audience_translate` 一行 join；`breach_plea` reason 统一追加；`urge_lever` 删冗余 note 赋值
- 补清：`month_chain._answer_from_row` label/hint/note/context strip；`session` deliberate title/body strip
- 证据：`candidates-ast.txt` + `members-exceptions.txt`；删重复 old.txt/new.txt

## 聚焦测试

见 `focused-pytest.txt`（命令与结果以该文件为准；七前缀 BIN=false）。

## 变异 / 观察

见 `mutation-observe.txt`：
- HELPER_ONLY：本轮实跑 `/tmp/1897-r1r2-final/observe_helpers.py`
- REAL_ENTRY：指针 `/tmp/1897-observe.PDMSvU/…`（本轮未重跑，不冒称）

## 自查二连

- 同类型：全仓候选→语义授权；链上成员补清；例外可核指针
- 引入 bug：未增长度护栏/证明性测试；urge outcome 决策未改；#1873 未碰
