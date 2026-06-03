---
name: army-roster
description: 军队数量过多时启用。涉及军队欠饷/补给/士气时先调 query_army_roster 查，不得凭印象推断。
---

调用 `query_army_roster(names=[<军名>, ...])`：
- 空列表返回全部军队名称+欠饷+状态索引
- 传军名列表返回指定军队完整信息

欠饷单位=累计万两整数，非抽象分。
