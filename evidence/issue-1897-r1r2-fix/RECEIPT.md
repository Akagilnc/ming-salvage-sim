# #1897 R1/R2 修内司回执

- 分支：`ak-roles/issue-1897-r1-r2-fix`
- 判词：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a107cd-efa4-7e4e-a948-3dc08952f664@fixer/attachments/00-1897-judge-e37942414.json`
- 未 push / 未开 PR / 未 amend / 未 stash

## 本轮证据修正（不改生产）

- 删除入库 `candidates-ast.txt`（全仓非成员 AST dump + 尾空白）；枚举命令改写 `/tmp/1897-r1r2-candidates-ast.txt`
- 成员表纠错：`list_due_grant_report_dossiers_for_scan`、`GameDB.rush_secret_order`、`normalize_audience_entry_kind`；补齐 2959d228d 全部 [:N] 裁剪 + breach_plea `add not in prev` R2
- 聚焦结果沿用已实跑 `focused-pytest.txt`（本轮不重跑）

## 自查二连

- 同类型：符号逐一核存在；处置表含第一 commit 全员
- 引入 bug：只改证据；未加机制/护栏/证明性测试
