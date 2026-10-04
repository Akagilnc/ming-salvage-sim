# #1897 R1 补清回执（R2 已结清，本轮不改）

- 分支：`ak-roles/issue-1897-r1-r2-fix`
- 判词：`~/.ak-roles/books/Ming_LLM/1897/runs/01a107cd-efa4-7e4e-a948-3dc08952f664@fixer/attachments/00-1897-judge-e37942414.json`
- 用户本轮：R2 结清；R1 遗漏 `db.py` pay_order_override `decree_text[:240]`、grant `note…[:240]`（text=案卷正文须取证）；同类案卷自由字段转运落库扫净；只删简化
- 未 push / 未开 PR / 未 amend / 未 stash

## 取证（text / decree_text）

- `_create_grant_fiscal_item(..., text=)` ← `create_decree_dossier` 成案 `text`（≈14303）与顺颁 `str(row["decree_text"])`（≈15567）
- `_apply_pay_order_override_effect` ← `row["decree_text"]` → `materialize_pay_order_decree(..., reason=)` → `record_fiscal_config_change`

## 本轮生产删裁剪

见 `members-exceptions.txt` §D；含财政写口（create/change/tombstone）与拨饷 economy / 军令 army 共享写口，不按财政字段名排除。

## 枚举

```bash
# 见 enumeration.txt；本轮实跑写出：
# /tmp/1897-r1r2-candidates-ast.txt
# py_hits=6685 non_py=18（修前全仓）；postfix slices → /tmp/1897-r1-postfix-slices.txt
```

## 聚焦测试

见 `focused-pytest.txt`（本轮重跑；七 BIN=/usr/bin/false；含触及面 pay_order / grant fiscal）。

## 自查二连

- 同类型：全仓 [:N] 案卷自由字段转运落库已扫；成员/例外可核；R2 未动
- 引入 bug：只删 [:N]，无新机制/护栏/证明性测试；未补 #1873；未改配置
