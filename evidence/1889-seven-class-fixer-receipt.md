# #1889 七类修内司回执（末判 6b513b99f · 全仓完整类枚举整改）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1889-w5r`
- 施工分支：`ak-roles/1889-seven-class-fixer`
- 判词真源：`…/attachments/05-1889-judge-6b513b99f.json` → `outcome.payloads` **末份**
- 本轮相对开工：`c47db4675`（其上已清转发壳；本轮扩完整类枚举谓词）
- 约束：无 amend / rebase / stash / push / PR；七变量 BIN=`/usr/bin/false`；只跑聚焦；不新建证明测试/护栏/兼容/功能补齐；不改治理/Soul/宿主/SDK/席位；不碰既存存档

---

## 授权未结类（末判原文类名）

K4 / K1 / K5 / K8 / K9 / K3 / K7

---

## 可复跑枚举（工作树内完整谓词脚本）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1889-w5r
python3 evidence/1889-seven-class-enumerate.py
```

完整输出：`/tmp/1889-seven-enum-final.out`。

### 本轮相对前版的枚举缺口整改

| 缺口（用户指摘） | 整改 |
|---|---|
| K5 `k5_hits` 仅 `store_root`、SQL 按 file 分桶 | **全仓生产 Python** SQL（含 root/`scripts/`/`web_app.py`/`spike`）；**全局签名分桶**（`dup_sql_same` / `dup_sql_cross`） |
| GameDB 薄壳硬编码两样本方法 | 实际薄转发：`XxxStore(...).meth` / Store+commit / `return self.OTHER`；**排除** `self._conn.execute` 真源与非持久别名 |
| K1_PAT 仅 blob/bare 样本 | 扩 compat/legacy_path/fallback_path/alias_source/deprecated + orphan 存储兼容方法候选；dispose 区分现役遗产·alias·brief·agno_runs |
| K3_PAT 仅 ISE/负断言 | 保留文本种子；**Python AST**（Assert/Compare/`match=`）+ **TS/TSX expect** 全测试面；NON_MEMBER/KEEP/DELETE 各带语义依据，禁止批量 KEEP 默认 |

全仓含义：生产面不因文件前缀排除 root/scripts；tests/web 进 K3；evidence/docs/enumerate 脚本标 NON_MEMBER。

### 修后复扫摘要

| 处置 | 条数 |
|---|---|
| NON_MEMBER（宽扫非成员+依据） | 4672 |
| KEEP（31 种 distinct basis） | 289 |
| DELETE_DONE（修前成员已清） | 29 |
| DELETE_REVOKED_K3 | 2 |
| LIVE 生产 DELETE 残差 | **0** |

成员车道（DELETE*/KEEP）按类：K1=26、K3=159、K4=2、K5=51、K7=1、K8=59、K9=22。

K5 覆盖非 entities 生产路径 9（`db.py`/`issues.py`/`flows.py`/`breach_plea.py`/scripts gate 等）；K3 TS hits=483。

生产残差谓词（`ming_sim/` + `web_app.py`，独立复扫）：

| 谓词 | 命中 |
|---|---|
| `scale_tian_fu\|read_scale_tian_fu` | 0 |
| `callable(_commit) and not callable(_conn)` | 0 |
| `default_terminal_reason` | 0 |
| `def append_chat_message\|def clear_month_open_snapshot` | 0 |
| `read_ack_due_commitment_issue\|read_get_secret_order` | 0 |
| `Close only by explicit declaration\|close_from_declaration` | 0 |
| `_decode_agno_runs\|merge_runs_table_with_legacy` | 0 |
| tests `Internal Server Error` 负锁 | 0 |

---

## 逐类结果

### K4 — 退役财政标量路径

**处置**：维持已清；`DELETE_DONE`×2；KEEP 现役 dynamic / section_fiscal 旁路。LIVE DELETE=0。未新增税改机制。

### K1 — 被取代来源 / 旧存储兼容

**处置**：宽扫扩至 compat/legacy_path/orphan 存储候选；dispose 显式 KEEP 现役 `legacy_modifiers`/alias fold/brief/`agno_runs`/保密负向。blob/accept-both 仍为 `DELETE_DONE`。未删 SDK/既存存档。

### K5 — 同一持久规则双份权威 / 转发壳

**类定义**：收拢重复规则；删除被替代入口及转发壳；不改事务边界、不把批量写退化成逐项提交。

**本轮枚举**：
- 全仓 SQL 全局分桶；每组附 `|| BASIS:`（lifecycle/status/field/schema_probe/script_fixture/cross_authority…），**无**「近重复即 KEEP」默认句。
- 薄转发：GameDB→Store 标 `gamedb_facade_pending` **KEEP**（票面待接领域职责/现役调用入口；对比已删 `append_chat_message`/`read_ack_*`）。
- Store 内 `return self._conn.execute` **不**标转发壳（真源）。
- metrics 共享 `_METRIC_UPSERT_SQL`、pending_decisions 单一 `_delete_*` helper 已在代码侧；枚举记 KEEP 依据。
- `save_pending_*` / `executemany` 边界未改。

**未结（诚实）**：GameDB 薄 Store 转发与 module Store one-liner 仍为待接搬迁面，本轮不泛删现役 facade（避免另造入口/破坏消费者）。

### K8 — 宽松排除解码

**处置**：维持严格 `_load_list` / `_load_targets`；LIVE 宽松 wash=0。既有装回变异证明见前轮 `/tmp/1889-k8-mutation.out`（本轮无再生产改动，未重装）。

### K9 — 未授权护栏 + 提交判别

**处置**：`default_terminal_reason` 与 callable 判别均为 `DELETE_DONE`；无复活 GameDB 提交壳。

### K3 — 自由诊断措辞负断言

**处置**：全仓 Py AST + TS expect 候选入表；ISE 负锁 LIVE=0；结构化/`match=`/machine id/输入保真 KEEP 各带依据；标题/散文形多数 NON_MEMBER（**非**批量 KEEP）。既有上游诊断变异见 `/tmp/1889-k3-mutation.out`。

### K7 — 撤回机制过期说明

**处置**：docstring 过期句 `DELETE_DONE`；scripts 枚举谓词源标 NON_MEMBER（非生产机制）。

---

## 聚焦测试

环境前缀：七个 `MING_SIM_*_BIN=/usr/bin/false`。

```bash
../Ming_LLM/.venv/bin/python -B -m pytest -q -p no:cacheprovider --tb=line \
  tests/test_section_fiscal_rejections.py \
  tests/test_audience_restore_505.py \
  tests/test_chat_stream_failpaths_393.py \
  tests/test_event_trigger_gate.py::test_load_event_requires_latest_or_open_window \
  tests/test_event_trigger_gate.py::test_load_event_rejects_non_boolean_open_window \
  tests/test_character_knowledge_489.py \
  tests/test_affairs_1831.py \
  tests/test_rescript_draft_656.py::test_clear_pending_decisions_keeps_rescript_drafts \
  tests/test_promulgation_seam_560.py \
  tests/test_new_game_smoke.py
```

**实测**：`148 passed in 7.23s`。完整输出：`/tmp/1889-seven-focused.out`。

本轮无新增证明性用例；无生产代码删改（残差已在前轮清零，本轮为枚举/处置完整化）。

---

## Advisor 自查（修改前 + 最终）· 自查二连 done

**修改前**：
- K5 仅 entities + 按 file 分桶 + GameDB 两方法白名单 → **完整类枚举收窄**。
- K1 仅 blob/bare 样本；K3 文本段偏负锁，未证明 TS/全断言覆盖。
- K5 dup_sql 批量 KEEP 默认句。

**最终**：
- 枚举脚本覆盖全仓生产 SQL、跨文件规则、实际薄转发、扩 K1、Py+TS K3；disposition 每条有依据；KEEP basis distinct=31；LIVE DELETE=0。
- 不泛删不同生命周期 SQL / 现役恢复 / 保密负向 / 输入保真 / SDK；不新增生产机制。
- 未改治理宪法 / Soul / 宿主 / SDK / 席位 / 既存存档。
- 未 amend / stash / push / 开 PR。

**Standards（轻量）**：证据脚本落 `evidence/`；TSV `git diff --check` 干净；无生产旁路新层。  
**Spec**：对齐末判七类 required + 用户「完整类枚举」指摘；未结 GameDB facade 待接已显式 KEEP 依据。

---

## 证据路径

| 文件 | 用途 |
|---|---|
| `evidence/1889-seven-class-enumerate.py` | 完整可复跑枚举+处置谓词脚本 |
| `evidence/1889-seven-class-member-disposition.tsv` | 全员处置（含 NON_MEMBER 依据） |
| `evidence/1889-seven-class-enum.tsv` | 成员车道（DELETE*/KEEP） |
| `evidence/1889-seven-class-enum-raw.tsv` | 宽谓词原始扫 |
| `evidence/1889-seven-class-fixer-receipt.md` | 本回执 |
| `/tmp/1889-seven-focused.out` | 聚焦测完整输出 |
| `/tmp/1889-seven-enum-final.out` | 最终枚举复跑输出 |
| `/tmp/1889-k8-mutation.out` | K8 装回旧逻辑（前轮） |
| `/tmp/1889-k3-mutation.out` | K3 上游诊断变异（前轮） |
