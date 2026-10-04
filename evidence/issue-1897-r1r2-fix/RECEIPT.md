# #1897 R1/R2 修内司回执

- 施工分支：`ak-roles/issue-1897-r1-r2-fix`
- 施工前 HEAD：`2959d228db978697f95b5860fdb703c6d16d653b`（上轮只清 [:N]）
- 判词：`attachments/00-1897-judge-e37942414.json`（R1/R2）
- 未 push / 未开 PR / 未 amend / 未 stash

## 根因

上轮枚举谓词收窄为 `[:N]`，未覆盖 R1「规范化与改写」全文（strip / strip-判空换缺省 / 固定文案拼装）与 R2 空白原文身份覆盖。

## 处置

删除票面链上对自由正文的 strip 写回、strip-判空覆盖、固定文案追加；保留结构化 outcome / id / JSON 包络 / 校验 bool 例外。详见 `enumeration.txt`。

## 聚焦测试

见 `focused-pytest.txt`：**1 failed, 342 passed in 8.93s**（wall real 9.44s）。
失败同 #1873 名册 ValueError，本轮不修。

## 变异观察

见 `mutation-observe.txt`：实际 `git checkout 2959d228d -- <files>` 装回旧逻辑后观察，再从 `/tmp` 备份恢复。

| 案 | OLD | NEW |
|---|---|---|
| NORMALIZE criterion/origin | equal=False（strip 掉空白） | equal=True |
| URGE_NOTE | note_equal=False fixed_suffix=True | note_equal=True fixed_suffix=False；outcome 仍可变为 transformed |
| BREACH_REASON 空白原文 | replaced_only=True | starts_with_ws=True；追加新理由、不整段替换 |
| CLOSE_TEXT 空白 result | ws_result_kept=False | True |
| SETTLE_ORIGIN | 空白被 strip | 原样嵌入 note |

## 自查二连

- 同类型：strip / strip-判空换缺省 / 固定拼装 / 空白身份覆盖 — 链上成员已按枚举表清完
- 引入 bug：未新增机制/护栏/证明性测试；urge 只停 note 文案、保留 outcome；#1873 未碰
