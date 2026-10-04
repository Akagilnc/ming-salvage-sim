# #1900 J19-R1 — 名单 normalize 未捕获 ValueError → 逐项 invalid_shape

## Finding

交办顶层 / grant 内 `participant_roster` 含非法机械档时，`_attach_commission_staging_fields` 调 `GameDB.merge_participant_roster_entries` 抛未捕获 `ValueError`，整份 `dispatch_declaration` 中止。押解侧已有 `DecreeMaterializationValidationError` 接缝，本缝缺同等 `_reject`。

## Hypotheses（可证伪，rank 后即测）

| rank | hypothesis | prediction | result |
|------|------------|------------|--------|
| H1 | staging attach 调 merge 无 try；call site 无 catch | 栈经 `_attach_commission_staging_fields`→merge；包 `(TypeError, ValueError)→_reject(invalid_shape)` 后四变体逐项拒、同批合法续 | **确认**（栈 + 修复后绿） |
| H2 | escort normalize 同样未捕获 | 仅坏 escort tier 也会 raise | **证伪**：已 `invalid_shape`（押解名单非法…） |
| H3 | 缺 `strict_incoming=True` 才炸 | 加 strict  alone 即停 raise | **证伪**：非法档在非 strict 路径同样 raise；缺的是拒收接缝 |

## 同类接缝扫描（本次 normalize 交办失败入口）

| 入口 | 位置 | 有 escort | 失败行为 |
|------|------|-----------|----------|
| 顶层 `participant_roster` | staging attach → merge | 无/有 | 修前 raise；修后 invalid_shape |
| grant 内 `participant_roster` | 同上 | 无/有 | 同上 |
| escort.escortees 非法档 | `_attach_grant_escort` try/ValueError→DecreeMaterializationValidationError | 有 | 已逐项拒（对照） |
| 同批合法 commission | commissions 循环 continue | — | 修前被整份带走；修后继续写 |
| `db._merge_directive_payload` merge | 界外（finding boundary） | — | 不扩修 |

## 命令成员表

强制前缀：`MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false`

| 步骤 | 命令 | 结果 | 时长 |
|------|------|------|------|
| Phase1 红环（契约断言） | `python3 -m pytest tests/_tmp_j19r1_probe.py -q`（已删） | RED `ValueError: 参与人机械档非法：乱档` | ~0.65s |
| 变体最小化 | 顶层/grant × 有无 escort + escort-only 对照 | 四变体 raise；escort-only 已拒 | ~0.67s |
| 扩展案红 | `… test_escort_route_1900.py::test_commission_malformed_escort_is_rejected_not_dropped` | RED 同症状 | 0.88s |
| 修复后聚焦 | `… tests/test_escort_route_1900.py -q` | 4 passed | 0.67s |
| 变异（去 try/except） | 精确替换 call site → 同单测 | RED 非法档 | 0.91s |
| finally 恢复 | 写回原块 → 同单测 | GREEN | 0.70s |

最低测试成本：单测 `test_commission_malformed_escort_is_rejected_not_dropped` ≈ **0.7–0.9s**（聚焦文件 4 passed ≈ 0.67s）。

## 修复

`declaration_dispatch` commissions 循环：`_attach_commission_staging_fields` 包既有 `(TypeError, ValueError) → _reject(..., "invalid_shape"); continue`。不捕未知异常、不整份吞、不新规则。

## 自查二连

- 同类型：押解侧已拒收；本缝对齐 declaration_from_payload 的 ValueError→invalid_shape。
- 引入 bug：未扩捕 `Exception`；未改 merge/priority；同人主办+协办两条断言仍绿。
