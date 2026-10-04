# #1900 修内司回执：末判 J18/J6 整类全仓扫与处置

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1900-w5`
- 分支：`ak-roles/1900-j18-j6-final-class-repair`（自 `bb448254c`）
- 判词真源：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a108b9-3e6e-7ba3-b4af-52e9a2b219d2@fixer/attachments/02-1900-judge-bb448254c.json` **末份** `continue` payload
- 票面：`gh issue view 1900` / `1812`（updatedAt 2026-10-04 / 2026-10-02）
- 官方现成解法：SQLite JOIN <https://www.sqlite.org/lang_select.html>；pytest monkeypatch 仅作临时边界（pytest docs）
- 禁令：无 stash / amend / rewrite / push / PR；未改 Soul/宪法/外部配置；自建物仅本目录与系统临时探针

**本轮纠正**：上一份回执以点名文件/点名符号收窄枚举，不能宣称整类结清。本轮按完整类形状做 AST+rg 全仓候选，成员表见独立文件；违法的 `night_said` 正文锁与实现函数 oracle 已改回独立常量/结构化落账。

---

## 1. 未结类别（末判施工边界，谓词不收窄）

| 类 | 级别 | 类定义 |
|---|---|---|
| **J18** | P2 | 退役残留专用资格、护行供料、死 helper、失效说明；删手工连接层，复用关联槽+原生 JOIN。不恢复专用账本/双载体/聚合口/旧软判实抵，不另造替代机制。 |
| **J6** | P2 | 被测路径 stub、调用/标记 oracle、非契约文字锁、固定输出伪证、方向化数值断言、重复退役证明；复用真实入口与独立外部契约；不造平行夹具/生产钩子。 |

点名与 `10e64fbef…HEAD` 182 文件仅为索引，不排除全仓同类。

---

## 2. J18 全仓枚举（完整类形状）

### 2.1 命令

```bash
# AST：ming_sim/**/*.py + web_app.py 上凡 def/assign 体命中
# escort|护送|护行|暗护|押解|grant_arrival|reconciliation|双载体|专用…|payload_declares|…
# 产出：j18-full-members.md / j18-full-members.json（AST 全仓）

rg -n --glob '!evidence/**' --glob '!.baseline/**' \
  'escort_pending_targets|escort_sources|dossier_escort_outcomes|_resolve_covert|_grant_escort_presence|clamp_grant_arrival|_escort_identity|_reader_may_cite|grant_route_reader|is_grant_allocation_dossier|_write_dossier_payload_key|_GRANT_ESCORT_RELATIONS|护送实况|list_open_grant_reconciliations|软判提案|软判读账' \
  ming_sim web_app.py tests docs --glob '*.py' --glob '*.md'
```

完整成员表（复扫后）：[`j18-full-members.md`](j18-full-members.md) / [`j18-full-members.json`](j18-full-members.json)

### 2.2 处置摘要（不得只报「点名 0 命中」）

| 处置 | 计数 | 说明 |
|---|---:|---|
| KEEP_LIVE_ENGINE | 16 | `grant_arrival_bounds` / `payload_declares_escort` / `dossier_declares_escort` / `_attach_commission_escort` / 核账 targets·record·list·merge 等——现役押解随拨银与无护核账（#1900/#1812；有护接续 #1873） |
| KEEP_LIVE_OR_INCIDENTAL | 27 | 声明入口、参与人投影、预推「自带押解」标记、schema 形字段等；非专用双载体/账本 |
| KEEP_RETIREMENT_NOTE | 1 | 生产内退役注释（非复活处方） |
| DELETE_DEAD | 0（复扫） | 本轮已删 `list_open_grant_reconciliations`（零引用 + 失效「软判读账打折」说明） |

撤销机制符号（`escort_pending_targets` / `escort_sources` / `dossier_escort_outcomes` / `_resolve_covert*` / `_grant_escort_presence` / `clamp_grant_arrival*` / `_escort_identity*` / `护送实况` 假供料 / 死 helper 等）在 **ming_sim + web_app + tests** 复扫：**0 存活实现命中**（文档/历史 evidence 中的退役说明与旧盘点保留，不作现行处方）。

手工 `status_ids/by_id` 连接：监督在场路径已为 `decree_dossier_links JOIN decree_dossiers`（`db.py` record_monthly_supervision_presence）。

**不宣称「整类字面 0 候选」**——现役引擎契约仍在成员表中，逐项有外部依据；缺陷残留 DELETE 项为 0。

### 2.3 假「无护」供料探针（七 BIN）

```
INPUT_DECLARED_ESCORT=True
RAW_RECONCILIATIONS 0
ARCHIVE_HAS_无护 False
ARCHIVE_HAS_护送实况 False
PROBE_NO_FALSE_无护 True
```

日志：`j18-feed-probe.log`

---

## 3. J6 全仓枚举（完整类形状，含 web）

### 3.1 命令

```bash
# AST：tests/**/*.py 每个 test_* 扫 monkeypatch.setattr / call_oracle / marker /
# direction compare / OperationalError|中文 in / translate_fn=lambda / helper 命名
# + web **/*.{ts,tsx} vi.spyOn|toHaveBeenCalled|mockImplementation

# 另 rg 全 tests：
rg -n --glob 'tests/**/*.py' 'apply_legacy_pct\(|grant_arrival_bounds\(|_has_meta_flag\(|routed:|track_auto_close|seen\.get\("write_gate"\)|assert any\(.*第一问|assert all\(.*后轮问'
rg -n --glob 'web/**/*.{ts,tsx}' 'vi\.spyOn|toHaveBeenCalled|mockImplementation'
```

候选与处置：[`j6-full-members.md`](j6-full-members.md) / [`j6-full-disposition.json`](j6-full-disposition.json) / [`j6-web-members.json`](j6-web-members.json)

AST 规模（本轮）：Python 焦点候选约 618；Web mock 行约 145。

### 3.2 语义处置原则（非「筛已知字串归零」）

| 桶 | 处置 | 外部依据 / 反例 |
|---|---|---|
| LLM/IO/会话边界 stub | **KEEP_BOUNDARY_STUB** | 共享硬规允许边界替身；反例＝stub 掉被测生产路径（如 power_band / recompute / auto_close spy）——本轮该类已无存活 |
| 票据闸 acquire | **KEEP_GATE_CONTRACT** | `test_startup_catchup_uses_ticketed_gate_not_bare` 断言契约本身 |
| 月/召对 translate 边界 | **KEEP_MONTH_TRANSLATE_BOUNDARY** | 替身在模型边界；截止案已改为结构化落账辨别 |
| 派系 leverage 方向比较 | **KEEP_QUALITATIVE_DIRECTION** | 定性联动，非金额/人数契约 |
| 序关系/生命周期方向 | **KEEP_ORDERING_OR_QUAL** | 如 idx 先后、mid>before |
| OperationalError raises | **KEEP**（读后） | `pytest.raises(OperationalError)` 测异常传播，非诊断 message 子串锁 |
| 中文 `in` 断言 | **KEEP**（读后抽样） | 多为结构化字段/种子 meta/人物名；末判点名的 OperationalError 文案锁已不在断言体 |
| Web vi.fn/spyOn | **KEEP_UI_BOUNDARY** | 组件渲染边界；非本票被测业务路径 stub 类 |
| helper 命名碰撞 | **KEEP_NAME_COLLISION** | 如 `test_oracle_independent_of_shared_haircut_helper` 测独立 oracle 抗变异，非 helper 专测 |
| 章节记忆/路由退役 | **KEEP** | 断言表不存在/路由不在 OpenAPI——外部可见表面，非 hasattr 死 API 伪证 |

### 3.3 本轮对先前违法改动的纠正

| 项 | 问题 | 改法 |
|---|---|---|
| `test_translation_entry_…_source_cutoff` | 直接锁 `night_said` 正文（第一问/后轮问） | 删正文锁；ADR0155 用 `until_chat_turn_id` + 泄漏→结构化 `scene_facts` 落账标记 |
| `test_income_still_modified_by_legacy` | `db.apply_legacy_pct` 作期望 | 独立常量：`net_pct == -12` → 实入 `88` |
| `test_in_transit_relief_…` | `grant_arrival_bounds` 作期望 | 北极星独立常量：面额 40 → 无护中位 `22` × `RECOVERY_PERSONS_PER_WAN` |
| `test_month_chain_lands_specialized_facts_…` | 同上实现函数 oracle | 面额 100 → 中位 `55` |
| `test_fixed_flows_substrate_hub_books_…` / skip display | `apply_legacy_pct` oracle | `-12%` 下 `12→11,3→3,4→4`；`7→6` |

复扫：`apply_legacy_pct(` / `grant_arrival_bounds(` / `_has_meta_flag` / `routed:` / night_said 正文锁 在 tests **0 命中**。

末判点名伪证（auto_close spy / power_band routed / 私有标记断言）维持已删；正向六科退场案保留。

---

## 4. 聚焦验证（七 BIN=/usr/bin/false；不全量）

```
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

| 集 | 结果 | 墙钟 |
|---|---|---|
| 点名/触及节点（含 escort、income、refugee、month_chain、substrate 两案、六科、promulgation…） | **58 passed** | real 5.09s |
| 触及文件套件 12 文件 | **186 passed** | real 10.65s |

日志：`focused-named.log` / `focused-files.log`。不为证明新造测试。

---

## 5. 进程内变异（旧逻辑红 → 恢复绿）

| 变异 | 变异结果 | 恢复 |
|---|---|---|
| `GameDB.apply_legacy_pct` +1 | 1 failed（89≠88） | 1 passed；staticmethod descriptor 已恢复；`apply_legacy_pct(100,-12)==88` |
| `grant_arrival_bounds` 中位 +1 | 1 failed（23≠22） | 1 passed |
| `recompute_faction_leverage` noop | 1 failed（50≠48） | 1 passed |
| `build_night_said_so_far` 忽略截止 | 1 failed（落账含「后轮泄漏」） | 1 passed |

日志：`mutations.log`。

---

## 6. 自查

- J18：删死读口；假「护送实况：无护」供料不复现；不恢复专用账本/双载体；核账仍无护口径（#1873）。
- J6：去掉 night_said 正文锁与实现函数 oracle；精确期望来自开局 legacy / 北极星比例 / 公开常量；无平行夹具、无生产测试钩子。
- 合法阻断：无。
- **剩余**：成员表中 KEEP_* 项——均为现役外部契约或边界替身，附依据；缺陷类 DELETE/FIX 残留 0。不以「候选总数归零」冒称结清。

---

## 7. Commits（本轮起）

- 先前：`39c7c9309` 窄枚举施工（已由本轮纠正 oracle/枚举义务）
- 本轮 SHA：（提交后回填）
