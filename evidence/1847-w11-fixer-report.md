# #1847 修内司 w11 交卷 — N11 / N13 / N10 / N14 / N16

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- 分支：`ak-roles/1847-fixer-w11-n11-n13-n10-n14-n16`
- 底座 HEAD（动手前）：`d7fb0dcf7a5b957514487497686aa939fa7a289c`
- delivery commit：`4c40f7e2c66b37ed0165e04103150c79d5aadf2d`
- 判词真源：
  - `~/.ak-roles/books/Ming_LLM/unbound/runs/01a109d7-ed74-72c4-bed9-027ef7044a10@fixer/attachments/00-1847-judge-d7fb0dcf7-main.json`
  - `.../01-1847-judge-d7fb0dcf7-correction.json`（更正取证表述；送修五类不变）
- 派单：`fix-packet.md`（五类：N11-R3 / N13-R3 / N10-R2 / N14-R3 / N16）
- 环境前缀：七个 `MING_SIM_*_BIN=/usr/bin/false`
- Python：`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`
- 禁止项遵守：未 stash / reset / checkout 覆盖未提交物 / clean / amend / rewrite / push / PR / SIGKILL / 全量 / 真模型；未改治理法源、席位、宿主配置

## 授权与诊断 skill

- 授权词：用户明确「执行修内司 apply」→ 可改代码。
- `diagnosing-bugs`：本票已有大理寺冻结判词取证与独立复现，**Phase 1（自建 feedback loop 找因）与 Phase 2（最小化复现找因）因根因已裁而不适用**；本席直接按类全仓枚举→语义核实→修共同根因→复扫→聚焦验证。新根因若不明才会回 Phase 1。

## 互联网官方资料（新机制前）

| 类 | 资料 | 结论 |
|---|---|---|
| N13 | [Python sqlite3](https://docs.python.org/3/library/sqlite3.html) `OperationalError` / `Connection.interrupt` | 库操作失败应传播，不得吞成空结果 |
| N10 | [OpenAI Error codes](https://developers.openai.com/api/docs/guides/error-codes) 401 Authentication | 以宿主 status／异常为准，不靠正文词表猜认证失败 |
| N11/N14/N16 | 删简优先（#1812 / 共享#12/#14） | 无新机制；删旧兼容、重复定义、非法测试断言 |

## 枚举命令（可回放）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python - <<'PY'
# 见本轮写入的枚举脚本产出：
# evidence/1847-w11-scans/members_all.tsv   （动手前机械枚举 208 行）
# evidence/1847-w11-scans/members_post.tsv  （修后复扫；功能残余 0）
# evidence/1847-w11-scans/n11_raw.txt … n16_raw.txt
PY
```

成员表路径：

| 文件 | 用途 |
|---|---|
| `evidence/1847-w11-scans/members_all.tsv` | 五类动手前全仓机械成员 |
| `evidence/1847-w11-scans/members_post.tsv` | 修后复扫（仅注释命中 2 行，非可执行旧路径） |
| `evidence/1847-w11-fixer-report.md` | 本回执（含例外依据） |

---

## 1) N11 退役闭包 / 重复定义

### 根因
现役定义与旧兼容并存：无标人口→万人；staged CREATE/ALTER 双维护；dossier 索引 DROP+重建；退役表 DROP；请旨 season-option 执行载荷无现役消费者却仍校验整问。

### 处理
- 人口口径统一「人」；删 `POPULATION_UNIT_WAN` / `scale_content_population_to_save_unit` / 无标万人分支；保留新档 `_mark_population_unit_persons`
- staged：`verdict_json`/`questions_json`/`forecast_text` 并入 CREATE；删 ALTER 补列
- 删 `_ensure_decree_dossier_locality_indexes` 及 init 调用；删 `DROP TABLE dossier_progress_reports`
- 请旨解析只保留 label/hint；删 `season_option` FieldSpec／`validate_season_option`／catalog 标记
- 删旧档专属测试与 season-option 解析独占案

### 例外依据
- **不改** ADR 0088 治理文件（判词 boundary）
- **不删**现役 delta 键名 `dossier_progress_reports`（密令月奏产品字段 ≠ 退役表 DROP）
- **保留** 0055 显式三选与现役 grant catalog（无 season_option 标记）
- 注释中「退役无标万人」字样：文档说明，非可执行路径（post 复扫 2 行）

### 残余
生产可执行旧路径：**CLEAR**。

---

## 2) N13 数据库失败冒充空事实

### 根因
密令血缘保护／withhold／release 等读端 `except OperationalError → 空集/0`，失败时保护集变空，密令可进共享轨。

### 处理
删除 `_secret_origin_message_protection`、chat_turns 扩展、`_withhold_origin_chat_messages`、`release_held_audience_knowledge`、`_latest_held_user_chat_message_id`、`_brief_origin_chat_message_ids` 上的吞错回落；交既有失败出口。

### 验证
独立探针：关库调用 raise；现役保护→held；空保护变异 RED（released）；恢复 GREEN。  
**声明**：RED 为内存空保护变异，**不是**装回已删旧函数正文。

### 残余
密令相关 OperationalError 吞空：**CLEAR**。

---

## 3) N10 成功正文关键词判认证失败

### 根因
`fail_if_llm_error` 与 CLI `_AGY_AUTH_MARKERS` 扫正文／stdout+stderr，成功正文含 authentication/api key 被误拒。

### 处理
- 删除 `fail_if_llm_error` 及全部调用点
- 删除 `_AGY_AUTH_MARKERS` 与退出码前的正文扫描
- 保留宿主 status／事件／非零退出／原生异常路径
- 测试：成功正文含认证字样原样返回；瞬断耗尽改用空输出可重试 typed

### 残余
生产正文词表认证猜测：**CLEAR**。

---

## 4) N14 非法／重复／helper 证明测试

### 根因
日志/异常措辞盯文；relation/faction 重复 prepare→brew→persist；`office_rank_*` 公共 helper 被当真实入口。

### 处理
- 财政 levy：去掉日志子串断言，保留他省推进契约
- 全仓测试：拆除 `pytest.raises(..., match=...)` 措辞锁（保留异常类型负向闸）
- brew：faction 改 import relation 侧单一 helper
- 删除纯 `office_rank_band` / `office_leverage_multiplier` helper 案；保留任命成案入口案
- 删除锁定已退役 season-option 校验的解析案

### 残余
点名样本与同根误分类：**CLEAR**。未为审计清单新增生产消费者或持久证明测试。

---

## 5) N16 旧命名存档跨局扫除

### 根因
`prune_auto_saves` 在 campaign 筛选前按旧命名正则删除全部匹配文件。

### 处理
删除 `legacy_auto` 扫除支链；仅保留当前 campaign 的 turn 保留策略。

### 验证
探针：旧命名／manual／other campaign 保留；当前 campaign 超窗 turn 仍按策略清理。

### 残余
跨归属旧命名删除：**CLEAR**。

---

## 验证

### 聚焦 pytest（非全量）

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
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

实测：`361 passed, 1 warning in 15.66s`（`evidence/1847-w11-scans/focused_pytest.out`；real ~16.18s）

### 独立探针

```bash
# 同上七变量前缀
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python evidence/1847-w11-scans/probe_w11.py
```

实测：全部 PASS；`OWN_TEMP_CLEANED true`；real ~0.88s（`evidence/1847-w11-scans/independent_probes.out`）  
外部替身范围：`tests.cli_process_doubles.install_fake_cli_runner`（仅 N10 CLI）；N13 RED 为内存空保护变异，非旧正文装回。

### 测试 diff 契约（最小必要）

| 变更 | 契约 | 成本 |
|---|---|---|
| 删人口 legacy 案 | 新档「人」仍由保留案覆盖 | 净删 |
| 改 CLI 瞬断注入为空输出 | 仍验三次耗尽→系统层失败→可重发 | 改 1 案 |
| 加 CLI 成功正文含认证字 | N10 外部可见：rc0 正文原样 | +1 短案 |
| 拆 match=/日志盯文 | 负向仍 raise 类型；不锁措辞 | 改断言 |
| 删 helper-only office_rank / season parser | 成案入口案保留 | 净删 |

未持久新增 mutation 证明测试；探针在系统临时目录，脚本仅存 evidence 扫描目录供回放。

## 自查二连 done

- 同类：五类按职责全仓枚举，不以样本白名单/引用数放行
- 引入：聚焦 361 绿；探针绿；无新护栏/迁移/拒收层/生产钩子；未改宪法配置

## 状态（如实）

| 项 | 状态 |
|---|---|
| N11 | 已修（生产 CLEAR；注释说明 2 行） |
| N13 | 已修 |
| N10 | 已修 |
| N14 | 已修 |
| N16 | 已修 |
| 家族 merge | **未声称完成**（仅本席提交，待后续衙门） |
