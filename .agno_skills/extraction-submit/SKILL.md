---
name: extraction-submit
description: 档房书办所有章节扫完、delta 算好后，调 submit_extraction 提交结算 JSON 时使用。
---

你处理的是"提交结算 JSON"。所有章节扫完、数值核对完毕后走这个 skill。

适用场景：
- 已逐章扫完邸报（拆章→判主题→查盘面→落字段→合并→新立/结案→人事）。
- 16 个顶层字段已全部填好（无内容的填 {} 或 []）。
- 准备把 JSON 交给程序落库。

使用方式：
- 调用 `submit_extraction(json_str=<严格 JSON 字符串>)`。
- json_str 必须是合法 JSON，不含 Markdown 代码块包裹（不要 ```json ... ```）。
- 16 个字段必须全部出现：metric_delta / economy_moves / faction_delta / class_delta /
  region_delta / army_delta / external_power_updates / world_advance / issue_advances /
  new_issues / cancels / close_issues / fiscal_changes / appointments /
  character_status_changes / office_changes。
- 只能调用一次；调用后本月结算即结束。

边界：
- 没扫完的章节不要提交；先把「人事除目」「待办未解」也扫完再调。
- submit_extraction 的说明里有完整字段约束、档位标准和骨架示例，以该说明为准。
- 不要在普通文本里输出 JSON 后再调 submit_extraction；JSON 必须通过 json_str 参数传入。
