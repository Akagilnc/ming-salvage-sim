# #1847 修内司 w9 证据报告（N11-R2 / N11-X1 / N13-R2）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- 分支：`ak-roles/1847-fixer-w8-n11-n13-n14-n15`
- 底座 HEAD（动手前）：`4cc4a3ab7dd3d2fbed05eb1121829ee3ce9fcc19`
- 判词真源：`evidence/1847-w9-verdict.json`（本席纳入证据；三项未结＝本轮类边界）
- 派单：`/Users/akagilnc/.ak-roles/books/Ming_LLM/1847/runs/01a10961-35dc-7c45-8677-7d901ddff7b7@fixer/fix-packet.md`
- 病史：`evidence/1847-w8-report.md`（仅病史；**不以扫描分类视作结清事实**）
- 环境前缀：七个 `MING_SIM_*_BIN=/usr/bin/false`
- 禁止项遵守：未 stash / amend / rewrite / push / PR / SIGKILL / 全量 / 真模型；未改宪法、Soul、席位、宿主配置；临时物仅 `/tmp/1847-w9-scratch`（已删）

## 法源先读

| 法源 | 要点 |
|---|---|
| 陛下 2026-09-28 口谕（ADR 0108 / 0152 引） | 不考虑旧存档兼容；相关兼容实现及专属测试不属合法交付 |
| ADR 0108 | 当前格式内无损恢复 ≠ 升级旧档；不新增旧档识别／拒收 |
| ADR 0152 | 旧存档兼容不在架构保留理由内 |
| ADR 0088 | 无标旧档一律「万人」legacy 读写（与 09-28 口谕**相抵**→上呈，不自判拆除） |
| 失败诚实宪法 + 共享 #9/#12 | 接住可以，洗白不行；真因落痕；删优先于加护栏 |
| 官方文档 | PEP 3134（`raise ... from` / `__cause__`）；`traceback.TracebackException.from_exception(..., compact=True)` 沿 cause 链；`format_exception_only` **不**走 `__cause__` |

## 本轮类边界（仅判词三项未结）

1. **N11-R2** — 按「是否只服务旧存档」逐个核（含函数内分支、ensure 补列、数据指纹），不得按引用次数放行
2. **N11-X1** — 撤扫描硬接线／新增护栏／并行分支；自扫 wired/shim；合法测试读口不用生产引用洗白
3. **N13-R2** — `LLMUnavailable` 保留结构化 `provider_message`，再追加因果链；不造字段／监管／证明性测试

N14 / N15 本轮判词已结清，不重开。

---

## N13-R2 失败传播

### 修法

`ming_sim/llm_transport.py` `classify_transport_failure` 的 `LLMUnavailable` 分支：

- **保留** `error.provider_message`（缺省回落 `error.message`）为 base
- **若有** `__cause__`：对 cause 做既有 `_exception_text_with_causes` 行走，拼 `"{base} | caused by: {cause_text}"`
- **不再**用 `_exception_text_with_causes(error)` 整体替换（该路径取 `str(error)`＝人读 message，会洗掉 provider 原文）

收尾 `raise cleanup_err from body_err` 与既有 `provider_message` / `trace.error` 出口未改。

### 临时入口变异红绿（真实入口，非证明性测试）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
# 1) 临时装回「pmsg = _exception_text_with_causes(error)」→ 探针须红
# 2) 恢复修法 → 探针须绿
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w9-scans/probe_n13_provider_cause.py
```

| 步 | 实测 |
|---|---|
| 变异红 | `provider_message='LLM失败(人读) \| caused by: inner'`；断言 `PROVIDER_BODY_xyz` 失败；exit=1 |
| 恢复绿 | `provider_message='PROVIDER_BODY_xyz \| caused by: inner'`；`N13_PROVIDER_CAUSE_PROBE PASS` |
| 收尾双因复扫 | `evidence/1847-w8-scans/probe_n13_dual_cause.py` 仍 PASS（RuntimeError+idle 链未回归） |

产物：`evidence/1847-w9-scans/n13_provider_cause.out`、`n13_dual_cause_recheck.out`

---

## N11-X1 扫描硬接线／护栏自扫

### 枚举命令

```bash
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w9-scans/scan_n11x1_wired.py
```

### 成员表（真实行为核对后）

| 成员 | 上轮处置 | 本轮处置 | 依据 |
|---|---|---|---|
| `drain_and_close` 内 `if not q.is_sealed(): raise RuntimeError(...)` | 接线生产消费者 | **DELETE_GUARD** | seal 后同线程不可能失败；纯为洗白 `is_sealed` |
| `is_sealed` | 同上 | **KEEP_TEST_READ** | `test_menu_lifecycle_drain_396` / `test_new_game_write_path_1749` 合法读口；不需生产引用 |
| `settle_ming_province_substrate_ticks` 双分支调 `settle_province_tick` | 接线生产 | **REVERTED** | 恢复一律 `_settle_province_tick_from_fiscal`；复杂度净减 |
| `settle_province_tick` | 曾 TEST_ONLY | **KEEP_TEST_OR_SHARED** | 测试与单省桥合法入口；不以生产引用洗白 |
| `run_month_end_relation_brew` | 删生产、测试局部改挂 Leg | **PROD_DELETED_TEST_LOCAL_OK** | 生产符号已删；测试局部 helper 合法，非新增生产机制 |

扫描 PASS：`evidence/1847-w9-scans/n11x1_wired.tsv`

---

## N11-R2 旧档专属性全仓扫描

### 谓词（覆盖类定义全文；非引用计数）

对生产代码中「旧档／旧存档／仅保旧／旧兼容／无标旧／老档／指纹 purge／DROP 旧列」等**实际行为**逐个核：是否只服务旧存档。保留新档建表、新档写入、现役共享消费者。法源冲突上呈不猜。

### 枚举命令

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w9-scans/classify_n11_old_archive.py
# 标记位点复扫（非结清事实，仅索引）
# → evidence/1847-w9-scans/n11_old_archive_markers.tsv
```

### 成员分类（行为核对后逐类交付；扫描分类≠结清）

完整表：`evidence/1847-w9-scans/n11_old_archive_members.tsv`

#### DELETE_DONE（本轮已删）

| 成员 | 理由 |
|---|---|
| `_known_opening_gazette_seed_text` + `_purge_fixed_opening_gazette_seed` + 开库调用 | 仅旧档精确 DELETE 已知 seed；新档 `seed_opening_gazette` 已不写该文 |
| `content/opening_gazette.md` | 仅作 purge 指纹源 |
| `tests/test_opening_gazette_delete_1356.py` | 独占直调 purge／指纹 |
| `create_decree_dossiers_from_directive` 载荷 `source_chat_turn_id` 回落 | 注释自述「仅保旧档兼容」；现只认 pending 列 |
| `_drop_maintenance_column` + 开库调用 | 仅当旧档仍有 `maintenance_per_turn` 时 DROP；新档 CREATE 本无该列 |
| `test_drop_maintenance_column_*` / `test_existing_save_drops_*` | 独占旧档 DROP 证明；同文件现役 schema 契约案保留 |

#### KEEP（共享／测试读口／内容同步；非旧格式迁移）

| 成员 | 理由 |
|---|---|
| `seed_opening_gazette` | 新档公共见闻事件 |
| `settle_province_tick` / `is_sealed` | 见 N11-X1 |
| `_migrate_character_identity_seed` / `_backfill_bandit_power_split` | 现体＝`INSERT OR IGNORE` 内容名册同步；旧改写已退役 |
| `_backfill_healed_participant_refs` | 现役纠错轮参与人修补 |
| `normalize_appointment_tenure` 缺省真除 | 亦服务现役缺备／非法值 |
| `decree_text` 与 `payload.text` 双读 | `decree_text` 仍由现役成案写入 |

#### ESCALATE（法源冲突或边界不清，上呈不猜）

| 成员 | 冲突／疑点 |
|---|---|
| `population_unit` / `scale_content_population_to_save_unit` / 「万人」legacy | **ADR 0088 明文要求**无标＝万人 legacy；**09-28 / ADR 0108 禁旧档兼容**。两法源相抵，不自拆 |
| `ensure_column` 大段「旧档补列」注释块 | 列已在 CREATE 时 ensure 只服务旧打开；但与「当前格式中途加列后的恢复」是否同一物，上呈后再定是否整段拆除 |
| `init_fiscal_config` `_FISCAL_MIGRATIONS`／老档升版 | 旧 schema_version 差量迁移；亦绑财政 key 演进，不自猜整段删除 |
| `_calibrate_faction_offsets` 老档反推分支 | 与新档校准交织，需立法裁断后再拆 |

**报告不把「HAS_PROD_REFS / KEEP」扫描桶当作结清。** 上列 ESCALATE 仍为未结旧档专属风险面。

---

## 聚焦测试（七 false；非全量；非真模型）

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q \
  tests/test_cli_backend.py \
  tests/test_month_chain_1847.py \
  tests/test_scene_llm_1836.py \
  tests/test_audience_translate_1837.py \
  tests/test_cli_transport_1465.py \
  tests/test_run_agent_text_transport_1465.py \
  tests/test_army_maintenance_retire_173.py \
  tests/test_menu_lifecycle_drain_396.py \
  tests/test_new_game_write_path_1749.py \
  tests/test_fiscal_substrate_bridge.py \
  tests/test_relation_brew_636.py \
  tests/test_faction_brew_637.py
```

实测：`391 passed, 1 warning in 24.97s`（见 `evidence/1847-w9-scans/focused_pytest.out`）

残迹 grep：`_purge_fixed_opening_gazette_seed` / `_known_opening_gazette_seed_text` / `_drop_maintenance_column` / `write queue seal failed` / `opening_gazette.md` → **NONE**（生产+tests+content）

---

## 未结范围（如实；不宣告 converged / 合并 / 关票）

| 项 | 状态 |
|---|---|
| N13-R2 | 本轮修法 + 变异红绿已交付；待大理寺复审 |
| N11-X1 | 点名护栏/分支已撤；wired 自扫三项 PASS；待复审 |
| N11-R2 点名样本 + 同类 purge/DROP/回落 | 已删；待复审 |
| N11-R2 ESCALATE：人口万人 legacy（ADR 0088 vs 09-28） | **上呈** |
| N11-R2 ESCALATE：ensure_column 旧档补列整段 | **上呈** |
| N11-R2 ESCALATE：fiscal schema 老档升版 | **上呈** |
| N11-R2 ESCALATE：faction offset 老档反推 | **上呈** |
| N14 / N15 | 上轮判词已结清；本轮未重开 |

## 自查二连

- 同类型：旧档专属按行为删（指纹／purge／DROP／回落），未再为扫描加生产引用
- 引入 bug：N13 变异装回旧逻辑确认红、恢复后绿；收尾双因探针未回归；聚焦 391 绿
- 未新增证明性测试／监管字段／平行诊断层
