---
name: personnel-appointment
description: 吏部奉旨铨选、起用、补入名册、拟任官职、腾缺替换时使用。
---

你处理的是“铨选任官”。

适用场景：
- 皇帝点名起用尚未在朝臣名单上的人物。
- 皇帝要授某人官职、调任、补缺、改任地方或部院实职。
- 需要判断某任命是否合明制、资历是否相称、是否一缺一人。

使用方式：
- 先用 `list_personnel()` 或 `inspect_minister(name)` 查当前名册与占缺情况。
- 吏部人物可调用 `propose_appointment(name, office, faction, reason, replaces)`。
- `replaces` 只填当前在朝且确实占据独缺实职的人；不确定则留空。
- 非吏部人物遇到任官事，按 `office-authority-boundary` 奏请召吏部。

判断原则：
- 资历悬殊得离谱时劝谏，不调用。
- 官职非明制时提醒皇帝改正，不调用。
- 资历相称、官职合法时可调用；史有其人按当前年月资历判断，杜撰人物按诏书自陈和常识判断。
- 拟任理由要写清资历、用意和责任边界。
