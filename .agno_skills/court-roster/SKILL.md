---
name: court-roster
description: 人物数量过多时启用。涉及任何人物官职/状态/任事处时先调 query_court_roster 查，不得凭历史印象推断。
---

调用 `query_court_roster(names=[<姓名>, ...])`：
- 空列表返回全部人物姓名+状态索引
- 传姓名列表返回指定人物完整信息

名册标了"下狱/罢黜/已故"→按该状态回奏，不得说他还在原职。
