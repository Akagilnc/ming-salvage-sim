# J20 成员表：呈现标题被用作持久事件身份

## 类定义（末份判词）
生产中以自由标题推断事件身份的路径；只保该旧行为的测试、失效说明。保留合法结构化身份通道。

## 枚举命令
- `rg -n -e 'title_to_ids|unique exact title|以快照唯一标题|binds on a unique exact title' ming_sim tests docs --glob '!evidence/**'`
- `rg -n -e 'bind_decisions_to_candidate_events' ming_sim tests --glob '*.py'`
- `rg -n -e 'test_candidate_binding|title.*candidate|裁断.*candidate' tests --glob '*.py'`

## 成员与语义核验
| 路径 | 角色 | 处置 |
|---|---|---|
| ming_sim/settlement_payload.py:185–216 title_to_ids + 缺id标题补绑 | 生产违法依赖 | 删除标题补绑，仅保留候选内显式 event_id 与合法 dossier: |
| ming_sim/settlement_payload.py:160–175 docstring 标题捞回说明 | 失效说明 | 改为仅结构化通道 |
| tests/test_decision_event_binding_389.py 参数化含无 id 靠标题得 candidate | 只保旧行为 | 删除标题补绑期望；保留显式合法 id / 解绑结构案 |
| tests/test_pihong_dossier_1490.py 对 bind_decisions_to_candidate_events 的 dossier: 保留案 | 合法结构化 | 保留 |
| ming_sim/session.py / decree.py 调用 bind_decisions_to_candidate_events | 入口接线 | 保留调用；行为随函数删简 |
| docs/adr/0115… 绑定由构造保证，非由文本捞回 | 法源 | 不改 ADR；实现对齐 |
