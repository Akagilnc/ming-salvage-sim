# 施工前顾问审视

## 授权
- 任务包明示「执行 apply」+ 末份判词送修 J20/J19/J6（含J17回退）→ 授权成立。
- 不送：J18（已结清）、J21/#1873 登记、正确性C3 未知委派人功能补校验（#1812 后置）。

## 最简路径（删简优先，不造通用件）
1. J20：删除 `bind_decisions_to_candidate_events` 中 title→event_id 补绑；仅保留候选内显式 id / 合法 dossier: 通道；同步退役只保标题绑的测试与说明。
2. J19：新交办名单 merge 走既有 `strict_structured=True`；清除字符串/缺 tier→知情 默认；保留完整条目 equality 合并；不恢复 id 先赢。
3. J6：清退役提案夹具、盯文、前置遮蔽伪证；复用既有入口修正负向辨别力；J17 恢复真人物+同批合法项。

## 官方检索结论
- SQLite：勿用 DISTINCT/first-wins 吞不同完整行（sqlite.org/lang_select.html）。
- pytest：断言结构化结果，避免 match/子串盯文（docs.pytest.org assert）；monkeypatch 不得吞被测行为。
