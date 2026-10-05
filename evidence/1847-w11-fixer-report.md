# #1847 修内司 w11 纠正交卷 — N11 / N13 / N10 / N14 / N16

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- 分支：`ak-roles/1847-fixer-w11-n11-n13-n10-n14-n16`
- 底座 HEAD：`d7fb0dcf7a5b957514487497686aa939fa7a289c`
- 上一轮 delivery：`4c40f7e2c66b37ed0165e04103150c79d5aadf2d`（本轮纠正，不 amend）
- 判词真源：
  - `~/.ak-roles/books/Ming_LLM/unbound/runs/01a109d7-ed74-72c4-bed9-027ef7044a10@fixer/attachments/00-1847-judge-d7fb0dcf7-main.json`
  - `.../01-1847-judge-d7fb0dcf7-correction.json`
- 派单：同 run `fix-packet.md`
- 环境前缀：七个 `MING_SIM_*_BIN=/usr/bin/false`
- Python：`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`
- 禁止项：未 stash / amend / push / PR / 全量 / 真模型；未改治理法源

## 上一轮 CLEAR 撤回（必须）

| 问题 | 处置 |
|---|---|
| `git diff --check d7fb0dcf7..HEAD` 实际 exit 2 | 本轮修报告尾空格、TSV CRLF、两测试 EOF 空行；复检须 exit 0 |
| 回执枚举命令为空 Python 注释 | 改为可回放 `evidence/1847-w11-scans/enum_commands.sh` + 成员表含 disposition/legal_basis |
| 以 regex 未命中宣告 CLEAR | 撤回；按类全仓枚举后逐成员处置；post 功能 MEMBER=0 才写 CLEAR |
| relation/faction 仅互 import 测试 helper | 撤回「已消平行流程」；改为经 `mechanical_tail._run_relation_brew` |
| 新增认证词 CLI 证明案 | 删除 `test_run_agy_success_body_with_auth_words_is_not_rejected`；复用既有运输契约 |
| 持久 `probe_w11.py` | 删除；探针只在系统临时目录生成/运行/清理 |
| N13 空保护手写变异冒充旧逻辑 | 撤回；改为 `git show` 装回原生产函数 + `Connection.interrupt` 真入口 |

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

### 各类扫描边界与例外

#### N11 — 旧档专属兼容 / CREATE+ALTER 重复 / 重建索引
- 枚举：人口无标万人符号与分流；`ensure_column`/ALTER/CREATE INDEX/退役表 DROP；`season_option` 执行规范
- 已修：无标万人分支与 `POPULATION_UNIT_WAN` 等；staged 字段并入 CREATE；dossier 索引重建与退役表 DROP 删除；season-option 执行规范删除
- 合法保留：新档 `population_unit=人` 标记 API；CREATE 侧现役索引；0055 显式三选与现役 grant catalog；注释中「退役无标万人」说明（非可执行路径）
- 不改：ADR 0088 治理文件（判词 boundary）
- 现役 delta 键名 `dossier_progress_reports`（密令月奏产品字段）≠ 退役表 DROP，保留

#### N13 — 数据库异常吞空（密令读端）
- 枚举：全仓 `except OperationalError`；并对照底座五函数密令读端是否仍吞空
- 生产 `ming_sim/db.py`：底座 7 处 → 现 0 处；密令五函数均为 `FIXED_REMOVED_SWALLOW`
- 合法保留：`ming_sim/issues.py` trigger_gate 两处 `OperationalError`→字段 typo 译 `ValueError` 否则原样上抛（非空事实回落）
- 测试内 `raises(OperationalError)` 注入：KEEP_TEST_INJECTION

#### N10 — 正文语义故障猜测
- 枚举：`fail_if_llm_error` / `_AGY_AUTH_MARKERS` / authentication|api key 词表扫描点
- 已修：删除 `fail_if_llm_error` 与 CLI 正文认证词表；保留宿主退出码/空输出/原生异常
- 合法保留：cli_backend 文档串提及 `Authentication required` 作为「勿把机器文本当大臣正文」说明（非扫描实现）
- 删除本轮新增认证词 CLI 证明案；运输契约案（空输出可重试 typed）保留，未改合法断言迎合实现以外的必要注入替换说明见 diff

#### N14 — 非法盯文 / helper-only / 重复流程
- 枚举：`pytest.raises(..., match=)`；财政日志子串；`office_rank_*` helper-only；relation/faction prepare→brew→persist 平行流
- 已修：拆 match=/日志盯文；删 helper-only office_rank 案；`run_month_end_relation_brew` 改为调用 `mechanical_tail._run_relation_brew`（注入 brew_fn 于 `_brew_fn_for_session` 缝；不新增生产消费者）；faction 共用该适配器
- 合法保留：异常**类型**负向闸；任命成案入口案；`mechanical_tail._run_relation_brew` 生产入口本身

#### N16 — 跨局旧命名扫除
- 枚举：`legacy_auto` / `prune_auto_saves`
- 已修：删除 `legacy_auto` 扫除支链
- 合法保留：当前 campaign 的 turn 保留策略

### 复扫
`members_post.tsv`：功能 MEMBER 残余 **0**（CLEAR）。不以「公共名未命中」代替成员表。

---

## 本轮代码纠正

1. `tests/test_relation_brew_636.py`：适配器改走 `_run_relation_brew`
2. `tests/test_cli_backend.py`：删除新增认证词 CLI 证明案
3. EOF：`test_population_unit_648.py` / `test_refugee_loop_652.py` 去掉多余空行
4. 删除持久 `evidence/1847-w11-scans/probe_w11.py`
5. 证据改 LF TSV + 可回放枚举命令

## 独立探针（系统临时目录；脚本已清理）

命令要点见 `evidence/1847-w11-scans/probe_command.txt`；输出 `independent_probes.out`。

### N13 边界（准确）
- 变异：`git show d7fb0dcf7:ming_sim/db.py` 取出原 `_secret_origin_message_protection`（76 行，含 `except OperationalError`）内存装回
- 触发：仅在 protection 调用期间 `Connection.set_progress_handler(prog,1)` + `Connection.interrupt()`；protection 返回后解除，避免误杀后续 held SELECT
- 入口：真实 `release_held_audience_knowledge`
- OLD RED：`released=1` / `reply_status=released` / `shared=2` / `error=null`
- NEW GREEN：`error=OperationalError:interrupted` / `released=null`
- NEW normal：`released=0` / `reply_status=held` / `shared=0`
- 非手写空保护 lambda；非装回后永久替换生产

其他类秒级：N11 无标不再回落万人；N10 `extract_agent_text` 含认证字样原样；N16 旧命名/他局保留；N14 适配器含 `_run_relation_brew`。real ~1.04s。

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

实测：`360 passed, 1 warning in 16.12s`（real ~16.72s；较上轮少 1 案＝删除认证词证明案）

## 自查二连 done

- 同类：五类全仓枚举 + 成员处置/合法保留依据；CLEAR 以 post MEMBER=0 为准
- 引入：聚焦 360 绿；N13 旧红新绿；无新持久证明测试/生产消费者；diff-check 复检

## 状态

| 项 | 状态 |
|---|---|
| N11 | 已修；注释说明非可执行 |
| N13 | 已修；原生产装回+interrupt 证明 |
| N10 | 已修；新证明案已删 |
| N14 | 已修；经 mechanical_tail 入口 |
| N16 | 已修 |
| 上轮 CLEAR | 已按上表撤回不实表述 |
| 家族 merge | 未声称完成 |
