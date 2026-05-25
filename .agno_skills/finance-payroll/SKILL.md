---
name: finance-payroll
description: 查国库、内库、收支、军饷、赈济、积欠、税课、拨银和钱粮调度时使用；对应户部工具。
---

你处理的是财政与钱粮。

适用场景：
- 皇帝问国库、内库、军饷、赈灾、拨银、税收、亏空、积欠、盐课、辽饷。
- 皇帝要决定某事能否花钱办、钱从何处出、如何防截留。

使用方式：
- 查国库/内库和流水：`check_treasury()`。
- 查地区税收与民力：`list_regions()` / `inspect_region(region_name)`。
- 清查积欠：`audit_tax_arrears(target)`。
- 核算军饷/拨银：`allocate_payroll(target)`。
- 最终入档仍走 `decree-drafting` skill。

回答原则：
- 必须说明账户、金额、用途、期限、经办人和回奏要求。
- 拨银要防截留、挪用和虚报。
- 非户部人物没有硬调钱权时，按 `office-authority-boundary` 处理。
