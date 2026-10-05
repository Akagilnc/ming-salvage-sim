# #1900 修内司回执（rescan：完整类定义枚举 + 补修）

## HEAD
- 施工前：`bbd34c025d085581986004dd58f241302bba1baf`
- 分支：`ak-roles/1900-j20-j19-j6-fixer-ee023324b`
- 触发：上轮成员表枚举锁定判词点名措辞，未覆盖类定义全文；用户明确不得收窄。

## 完整成员表路径
| 类 | 机械候选 | 语义成员表 |
|---|---|---|
| J20 | `j20-enum-raw.txt` / `j20-deep.txt` / `j20-verify.txt` / `j20-enum-cmds.txt` | `j20-members.md` |
| J19 | `j19-enum-raw.txt` / `j19-deep.txt` / `j19-verify.txt` | `j19-members.md` |
| J6／J17 | `j6-ast-candidates.jsonl`（15111）+ `j6-text-assert-raw.txt` + `j6-mock-retire-raw.txt` + `j6-focus-*.jsonl` | `j6-full-members.md` + 逐条 `j6-full-disposition.jsonl` |
| 命令真源 | `enum-cmd.txt` / `j6_full_enum.py` | |

## 本轮代码变更
### J20
- 生产标题补绑已在上轮删除；本轮全仓复核无回归。
- 清除 `session.prepare_rescript_prewrite` 失效说明「以候选快照重绑」。
- Web `decisionRouting` 的 `title: string` 为形状校验，非身份推断 → KEEP。

### J19
- 核实交办顶层/grant/`_attach_commission_escort` 均已 `strict_incoming=True`。
- **补修**：`GameDB._merge_directive_payload` 改草新名单 → `strict_structured=True` + `strict_incoming=True`。
- 函数默认宽松与 `create_issue` 非交办路径：组别例外见成员表（不恢复 id 先赢）。

### J6（含 J17）
- **held 闸**：去掉 `resolve_directives` 替身；改 `canned_full_settlement` 合法 LLM 缝前置，真实经过月链后落持闸分支。
- **盯文**：清除 travel_gating / secret_order_566 / month_call_recovery / material_directory / chat_stream_failpaths / cli_backend / surcharge 的注入异常措辞锁；保留类型 + 外部结果。
- 上轮已清项（rejection_wiring 退役提案、month_chain_1843、relation J17 甲乙等）维持；disposition 表标注 FIX_APPLIED / KEEP。

## 聚焦测试
七 BIN=`/usr/bin/false`。`focused-tests.log` → **161 passed in 7.16s**。

## 变异
见 `mutations.log` / `mutations-summary.txt`：
- J17 停用来源闸：2 failed；恢复 2 passed
- held：resolve 后武装 save boom → 1 failed（ARMED_RESOLVE_CALLS=1）；恢复 1 passed
- J20 恢复标题绑：2 failed；恢复 5 passed
- J19：strict 字符串 → ValueError；loose → 知情

## 如实剩余
- J20：生产自由标题身份推断路径 **无**；呈现/诊断用 title **KEEP**
- J19：交办/改草严格入口已齐；`merge` 默认与 `create_issue` 非交办宽松为**已核组别例外**
- J6：机械宇宙 15111 条均有 disposition；`FIX_NEEDED=0`。KEEP 组别见 jsonl。未宣称全仓无任何字符串断言——结构化字段/typed 错误包/LLM 边界/Web 回调等按契约保留
- J21/#1873 登记、未知委派人护栏：**非本席**
- 未全量、未 push/PR、未 amend/stash、未改配置

## 自查二连
- 同类型：枚举谓词覆盖类定义全文；未以点名样本收窄；成员表对候选有处置或可核组别例外
- 引入：held 改为真实月链 canned，未吞被测持闸；未加生产钩子；数值契约未放松
EOF
