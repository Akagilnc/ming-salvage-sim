# #1847 修内司 w11 纠正交卷 — N11 / N13 / N10 / N14 / N16

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- 分支：`ak-roles/1847-fixer-w11-n11-n13-n10-n14-n16`
- 底座 HEAD：`d7fb0dcf7a5b957514487497686aa939fa7a289c`
- 上一轮纠正：`98c5bfb22540122ab1cbace4f948458393d5681a`
- 本轮 N14 复检纠正 commit：见交卷 SHA（不 amend）
- 判词真源：
  - `~/.ak-roles/books/Ming_LLM/unbound/runs/01a109d7-ed74-72c4-bed9-027ef7044a10@fixer/attachments/00-1847-judge-d7fb0dcf7-main.json`
  - `.../01-1847-judge-d7fb0dcf7-correction.json`
- 派单：同 run `fix-packet.md`
- 环境前缀：七个 `MING_SIM_*_BIN=/usr/bin/false`
- Python：`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`
- 禁止项：未 stash / amend / push / PR / 全量 / 真模型；未改治理法源

## 本轮复检成立违例（N14）

上一轮把 `run_month_end_relation_brew` 扩成约 55 行适配器：替换被测 `MonthEndRelationBrewLeg` 为 `_CapturingLeg`、捕获生产已抛的 `LLMUnavailable`/`LLMContractError`/`ValueError` 并返回内部 `leg.report`、甚至自撰 `selected/brewed/degraded` 空结果——把生产真实失败洗白为旧 helper 契约。

### 处置
- 删除 CapturingLeg / 异常洗白 / 空 report 发明
- helper 只替换外部 brew 输入（`_brew_fn_for_session`），真实 `SessionWriteQueue` + 真实 leg + `mechanical_tail._run_relation_brew`
- helper 返回 `None`；用例对 DB 结果或生产异常类型断言
- 负向闸保留（缺 LLM / 程序错 / DB 失败 / 契约错降级后上抛），改为生产契约
- `test_mechanical_tail_1845` 两处 recording stub 的虚构 report dict → `return None`
- 不为清单新增生产消费者或测试钩子；不新增第二机制

## 枚举命令（可回放）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
bash evidence/1847-w11-scans/enum_commands.sh
# 原始输出：evidence/1847-w11-scans/enum_commands.out
# 成员表：evidence/1847-w11-scans/members_all.tsv
# 复扫：evidence/1847-w11-scans/members_post.tsv
```

### N14 成员处置（本轮补）

| 成员 | disposition | legal_basis |
|---|---|---|
| `run_month_end_relation_brew`（test helper） | FIXED_BREW_FN_ONLY_NO_REPORT_WASH | 只换 `_brew_fn_for_session`；真 queue/leg；不返回 report |
| `_CapturingLeg` + except wash + invented empty report | FIXED_REMOVED_ADAPTER_WASH | 已删；禁止 mock 被测行为 / 放松断言 |
| faction 用例 import 同 helper | FIXED_ASSERT_DB_OR_EXC_TYPE | 断言 DB / 异常类型，不读内部 report |
| mechanical_tail recording stub 虚构 report dict | FIXED_RETURN_NONE | 对齐生产 `_run_relation_brew -> None` |
| `mechanical_tail._run_relation_brew` | KEEP_PROD_ENTRY | 判词点名现役入口 |
| match=/日志盯文 / office_rank helper-only / 认证词证明案 | 上轮 FIXED_* 保留 | 本轮未重开 |

### 复扫
post 功能 MEMBER 残余 **0**（按成员表；含 CapturingLeg / leg.report / report[selected\|brewed\|degraded] / invented empty report / exception-wash）。**不以 regex 未命中单独宣称 CLEAR**——CLEAR 依据 = 成员表逐成员处置后 functional hit=0。

N11/N13/N10/N16：本轮未改生产；上轮处置与合法保留依据仍见 `members_all.tsv`。

## 聚焦测试

```bash
# 七变量前缀同上
BASETEMP=$(mktemp -d /tmp/1847-w11-pytest-XXXXXX)
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q \
  -p no:cacheprovider --basetemp="$BASETEMP" \
  tests/test_month_chain_1847.py \
  tests/test_secret_order_isolation_883.py \
  tests/test_population_unit_648.py \
  tests/test_population_transfers_649.py \
  tests/test_run_agent_text_transport_1465.py \
  tests/test_cli_transport_1465.py \
  tests/test_cli_backend.py \
  tests/test_office_rank_562.py \
  tests/test_relation_brew_636.py \
  tests/test_faction_brew_637.py \
  tests/test_fiscal_levy_effect.py \
  tests/test_advance_paths_atomic.py \
  tests/test_rescript_choices_563.py \
  tests/test_pihong_dossier_1490.py \
  tests/test_refugee_loop_652.py \
  tests/test_surcharge_causal_chain_650.py
```

实测：`360 passed, 1 warning in 13.93s`（real ~14.42s）

附加 brew+tail：`tests/test_relation_brew_636.py tests/test_faction_brew_637.py tests/test_mechanical_tail_1845.py` → `51 passed in 1.46s`（real ~1.87s）

`git diff --check`（底座..工作区触及文件）：exit 0

## 自查二连 done

- 同类：N14 全仓洗白/report/CapturingLeg/invented-report 枚举；逐成员 disposition；helper 复杂度 31 行、0 内部 class、0 except wash
- 引入：聚焦 360 绿；brew+tail 51 绿；无新生产消费者/钩子；diff-check 绿

## 状态

| 项 | 状态 |
|---|---|
| N11 | 上轮已修；本轮未改生产 |
| N13 | 上轮已修；本轮未改生产 |
| N10 | 上轮已修；本轮未改生产 |
| N14 | 本轮删 report 洗白适配；生产入口契约 |
| N16 | 上轮已修；本轮未改生产 |
| 家族 merge | 未声称完成 |
