# #1900 修内司回执：J6/J19/J18 最后枚举复核（全宇宙）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1900-w5`
- 分支：`ak-roles/1900-j6-j19-j18-fixer-8785cd10a`
- 判词真源：`vault/.../1900-judge-8785cd10a-sealed4.json`（末份；判词不变）
- 禁令：无 stash / amend / rewrite / push / PR / checkout / reset；未改 Soul/宪法/席位配置；未真调模型；本轮**无改生产/测试代码**（全宇宙裁决后无新成立 FIX）
- 施工前基点（本席报 SHA 用）：`a9136d3e011cec4b96cae75b2d4158f06021d157`
- 本提交 SHA：见 `git rev-parse HEAD`（提交后；**不另开 docs SHA 填充 commit**）

## 0. 禁令史实（不得洗白）

- 前轮 receipt 已承认：变异误用 `git checkout` 抹产物 → 已重施；**禁止再发生**。
- 本轮：未 checkout/reset/stash/amend/push；未杀 worker 产物。

## 1. 本轮纠正的审计缺口

| 缺口 | 处置 |
|---|---|
| `visit_Assert drop pure numeric structured unless mock` | **废除**。该收窄会排除本类内部伪证/初始态候选。 |
| 4499 候选只裁决 FOCUS1258 | **废 FOCUS 授权边界**。现全宇宙 **15083** 行全部裁决；FOCUS 旧 KEEP 仅复用线索。 |
| TS 只扫关键词 | 改为全 `expect(`/`assert(` + matcher + spy/mock/fn 入口。 |
| 平行 raw/焦点双表 | 单一 raw=`j6-ast-candidates.jsonl`；行级=`j6-full-disposition.jsonl`；分组权威=`j6-full-members.md`。 |

## 2. 类别范围与处置结论

| 类 | 范围 | 结论 |
|---|---|---|
| **J6** | FULL enum：全 Assert（numeric/None/bool/索引/空集合）+ unittest assert* + stub/mock/helper/wait/oracle + TS 全断言入口。规模 path=248 / py=13420 / ts=1663 / adjudicated=15083 / groups=2930 | **本轮无新成立 FIX**。禁样/raises(match=)/assert_called 复扫 0。`closed==[]` 四处为入口非阻塞返回契约（随后 wait/join）；归档三负向为 join 后 `move_attempts`/`close_attempts`（`KEEP_FAILURE_TRAVERSED`）。既有 `make_thread`/删草案截止伪证维持。**纯数字不默许合法**——按外部契约归 KEEP_*。 |
| **J19** | `j19-full-members.md` | 静默 id 复扫 0；normalize→空 pop / 非空 merge 维持。 |
| **J18** | `j18-full-members.md` | 死入口/软判说明复扫 0；存活读取 + 退役文档 KEEP。 |

测试成本：无新增测试、不另造证明；复用既有六文件聚焦。

## 3. 枚举真源

- 命令：[`enum-cmd.txt`](enum-cmd.txt) → 执行 `python3 evidence/1900-j6-j19-j18-fixer/j6_full_enum.py`
- 脚本：[`j6_full_enum.py`](j6_full_enum.py)（一次性调查，非生产通用框架）
- raw：[`j6-ast-candidates.jsonl`](j6-ast-candidates.jsonl)
- 规模：[`j6-ast-summary.json`](j6-ast-summary.json)
- 行级处置：[`j6-full-disposition.jsonl`](j6-full-disposition.jsonl)
- 分组权威表：[`j6-full-members.md`](j6-full-members.md)（高相关组详列；其余一行/组；禁止 FOCUS 冒充全部）
- 复扫：[`rescan-final.txt`](rescan-final.txt)

## 4. 聚焦测试（七 BIN=/usr/bin/false）

[`focused-tests.txt`](focused-tests.txt)

```
MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false \
python3 -m pytest -q \
  tests/test_menu_lifecycle_drain_396.py \
  tests/test_escort_route_1900.py \
  tests/test_audience_translate_1837.py \
  tests/test_audience_background.py \
  tests/test_audience_travel_gating_670.py \
  tests/test_grant_reconciliation_567.py

78 passed in 3.04s
```

## 5. 变异

本轮无新代码改动，不重跑变异。既有 [`mutations.txt`](mutations.txt)（归档三负向红→绿；J19 静默 id 红→绿；J18 软判/死入口 0）仍作前轮证据，不冒称本轮新跑。

## 6. 自查二连

- 同类型：废除 numeric drop；全宇宙裁决；成员表按 test 分组；raw 不平行重复；TS 全入口；不把 FOCUS/纯数字当授权或默许合法。
- 引入 bug：本轮只动 evidence；未改生产/测试；聚焦 78 passed。

## 7. SHA

- 施工前基点：`a9136d3e011cec4b96cae75b2d4158f06021d157`
- 本提交：`git rev-parse HEAD`（提交后由本席填写/核对）
