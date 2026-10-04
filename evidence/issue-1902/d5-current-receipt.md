# #1902 D5 全类清退回执（提交前最终自验，未提交）

基准 HEAD：`59d4f8b18663199c3cf89618872f13399226aae6`（工作树有未提交 diff；本回执不 commit / stash / amend / push / PR）。

原判：`/Users/akagilnc/.ak-roles/books/Ming_LLM/unbound/runs/01a10801-ef07-7a2d-8851-ab4324f97e3e@fixer/attachments/00-1902-judge-59d4f8b18.json`
原派单：`/Users/akagilnc/.ak-roles/books/Ming_LLM/unbound/runs/01a10801-ef07-7a2d-8851-ab4324f97e3e@fixer/fix-packet.md`

官方测试生态先行确认：
- pytest anatomy：测可观察行为，不测实现细节
  https://docs.pytest.org/en/stable/explanation/anatomy.html
- Testing Library：优先按角色/结构观察，避免对脆弱自由文本建机械依赖
  https://testing-library.com/docs/queries/about

## 类定义谓词（判词两条 D5 + 现行票面，**未收窄**）

### D5-A 非法文本／信号约束
1. 呈现文本上扫描机器字段名或词黑名单。
2. 整段呈现文本相等／不等作契约（含 `text != raw`、detail/report 差分）。
3. 呈现文数字集合／正则抽数（`_ints` / `findall\d+`）。
4. formatter 固定措辞或 helper 生成物嵌入呈现（「城防炮N门」、`*_description/label in detail`、非模型输入缝的 `arrears_text in detail`）。
5. 诊断 tlog／实现信号条数或异常类名筛选（含 `assert msgs`、条数、`JSONDecodeError in str(m)`）。
6. 无契约价值的弱自由文本约束及专用夹具。

**合法保留（禁止把「helper源标签在呈现文」泛化成例外）**：
- 闸类隔离；结构化 ABI 键缺席；账本结构化流水。
- **实际模型调用输入来源**／原始输出透传。
- 菜单／按钮／设置页等固定界面文案（非叙事生成物）。

### D5-B 失效／重复／内部退役证明
1. routes/OpenAPI/`_registered` 注册表退役证明。
2. 与真实 HTTP 负向案同根重复。
3. 路径写错致变异仍绿。
4. 只建数据自证、未走旁路的伪「无旁路」证明。
5. 与既有结构化真实行为案重复的平行证明。

### 禁止项
不新造平行证明／永久扫描机制／生产护栏；不整删整补功能；不为删除的证明另造测试；不 commit/stash/amend/push/PR。

## 枚举所用确切命令（全仓，非仅关键词计数）

### 1) 全集路径（265）

```bash
PRED='(^|/)(tests?/|__tests__/|conftest\.py$|test_[^/]+\.py$|[^/]+_test\.py$|[^/]+\.(test|spec)\.(ts|tsx|js|jsx|mjs|cjs)$|fixtures?/)'
git ls-files | rg -i "$PRED" | sort -u | tee /tmp/d5-audit-1902/enum/universe265.txt | wc -l
# → 265
```

### 2) 临时 AST 全量断言／expect 倾倒（不入仓；人工判别候选）

```bash
python3 <<'PY'
"""Temporary full assert/expect enumerator — /tmp only. No repo landing."""
# 对 universe265 每路径：ast.walk 收集 Assert 节点；TS/JS 收集 expect( 行；
# 另宽扫 free_text_cands（assert…in / != / == / tlog / msgs / openapi / routes /
# _ints / findall / textContent / detail|report|roster|summary|label 等），
# 写出 /tmp/d5-audit-1902/enum/ast-asserts.json + all-asserts-flat.json
# + spotlight-residual.json（人工再判）
PY
# 实测摘要：
# paths=265 assert_nodes=12747
# paths_with_asserts=221 paths_with_expects=26
# paths_with_free_text_cands=235
# paths_with_msgs_assign=1（tests/test_cli_backend.py；非 D5 诊断 msgs 契约）
# spotlight_residual_candidates=1
#   tests/test_region_cannon_delta.py:49 断言消息字符串含「城防炮」——人工判为
#   clamp/region_log 行为说明，非整段呈现措辞锁；保留。
```

### 3) 全文 rg 复扫（确切命令；未收窄到机器字段黑名单 alone）

```bash
rg -n '城防炮|城防大炮|population_wan_kou_label|city_defense_description|_ints\(|findall\(r.["'"'"']\\d' tests/ web/src/
rg -n 'text\s*!=\s*raw|assert msgs|len\(msgs\)|surfaced\s*=|JSONDecodeError in' tests/ web/src/
rg -n 'app\.routes|openapi\(\)\["paths"\]|_registered\(|registered_paths\s*=' tests/ web/src/
rg -n 'arrears_text in |_description in |_label in ' tests/ web/src/
rg -n 'setattr\(issues,\s*"tlog"|msgs\s*=\s*\[\]' tests/test_fiscal_levy_effect.py
rg -n 'assert msgs|_capture_tlog|tlog' tests/test_db_broad_except_surface.py
```

**rg 实测人工判别**：
| 命令族 | 命中 | 判别 |
|---|---|---|
| formatter/抽数词 | 注释／schema 字段「城防炮」／commitment 标题夹具；无 `*_label/description in detail`、无 `_ints` | **无 D5-A 残留契约** |
| `text!=raw` / `assert msgs` / surfaced / JSONDecodeError | **0** | 已清 |
| routes/OpenAPI/`_registered` 活跃断言 | 仅注释提及 | **无活跃表证** |
| `arrears_text in` / `_description in` / `_label in` | **0** | 已清 |
| fiscal_levy `tlog` | 剩 1 处 HEAD 原有 `incomplete_first_pass` silent（非本轮 msgs→静默换形的四处） | 见下 |
| broad_except | 仅 docstring「不锁 tlog」 | `assert msgs` 已删 |

完整路径分类见 `evidence/issue-1902/D5-members.md`（265 行全覆盖）。

## 提交前自验补刀（本轮相对上一工作树回执）

| 路径 | 测试函数／范围 | 处置 | 依据 |
|---|---|---|---|
| `tests/test_db_broad_except_surface.py` | 四案 | **改** | `assert msgs` + `_capture_tlog` = D5-A§5 诊断信号；**不得**以「可观测回退」洗白。去掉非法信号证明与专用 helper；保留损坏 JSON 回退真实结果（`options==[]` / `choice is None` / `simulator_payload=={}` / 国库回到 baseline） |
| `tests/test_fiscal_levy_effect.py` | 四处 msgs→静默换形 | **删静默 monkeypatch** | 死夹具不得换形保留；monkeypatch 无其它用途则去参数。四处：`malformed_region_fiscal` / `bad_settle_shape` / `bad_region_redistribute` / `bad_share_meta` |
| `tests/test_fiscal_levy_effect.py` | `incomplete_first_pass…` | **维持 HEAD 原 silent** | 非 msgs 换形产物；仍仅静默 tlog，行为断言独立 |

上一轮处置（删文件／`_ints`／HTTP 负向等）维持，见下表与成员表。

## 本轮处置成员表（精确到测试函数／文件；含上轮+自验）

| 路径 | 测试函数／范围 | 处置 | 依据 |
|---|---|---|---|
| `tests/test_region_citydefense_display.py` | 全文件 | **删文件** | 锁「城防炮11/37门」+`city_defense_description in detail`=formatter；专用夹具随删；不变形再造 |
| `tests/test_web_issue_condition_display.py` | 全文件 | **删文件** | `text!=raw`+人物子串弱断言无结构化契约；夹具 `_h` 随删 |
| `tests/test_commitment_display_348.py` | `TestTimed*` / `TestPassive*` / `TestNonTimed*` 中 `_ints` 案；集成案的 `_ints` 断言 | **删类** | 呈现数字集合同属 formatter/机械依赖；保留 `commitment_timed_bar_value` / `commitment_progress_payload` 结构化 |
| `tests/test_decree_dossiers_571.py` | `test_final_decree_edit_path_removed_no_bypass` | **删** | 只 `add_directive` 后读自己写的数据，无旁路；HTTP 负向已在 `web_audience_night_498` |
| `tests/test_army_display_173.py` | `test_army_public_exits_approx_arrears_and_hide_split_accounts` | **改** | 去掉 `arrears_text in detail`（helper 嵌入呈现）；保留军牌 ABI 键缺席 + `arrears_text` 结构化变化 |
| `tests/test_army_firearms.py` | `test_army_public_exits_surface_firearm_and_cannon` | **删** | 与既有 `apply`/`create` 火器结构化案重复，不新造 |
| `tests/test_population_unit_648.py` | `test_new_save_region_detail_sub_wan_population_label`；`test_legacy_region_detail_population_untouched` | **删** | helper 标签嵌入 / 「N万人」盯文；DB 刻度案仍在 |
| `tests/test_fiscal_levy_effect.py` | 四处死 msgs／静默 | **删** | 见上 |
| `tests/test_fiscal_substrate_bridge.py` | summary 三断言；tlog 条数案 | **删断言／已删案** | summary 标签嵌入+机器键缺席=formatter；保留 `army_logs` |
| `tests/test_region_cannon_delta.py` | `test_cannon_has_chinese_display_label` | **删** | 专用 `REGION_FIELD_LABELS==城防炮` formatter 常量证明 |
| `tests/test_identity_seed_488.py` | `test_identity_and_seed_guilt_never_enter_minister_context` | **微改** | 去「95」数字盯文；保留 character_context 机器字段隔离闸 |
| `tests/test_db_broad_except_surface.py` | 四案 | **改** | 见上 |
| `tests/test_web_entry_1902.py` | 注册表退役案 | **维持删** | 真实 HTTP 负向承担 |
| `tests/test_qa_d1_decree_normalize_1274.py` | 注册表/常量盯文 | **维持删** | 同上 |
| `tests/test_web_audience_night_498.py` | ASGI 退役表面两案 | **维持 HTTP** | 保留 404/405；变异咬合见下 |
| `tests/test_player_army_projection_321.py` | `_assert_chain_embeds_situation` | **保留** | sit→report/materials=**实际模型调用输入来源**，非 formatter 自证 |
| `web/src/components/situation.test.tsx` | StateModal 奏疏案 | **维持** | 已去 `progress:7`/`progress_band` 黑名单 |

## Web 生成物／textContent 全类扫 — 保留依据（逐文件）

| 路径 | 保留依据 |
|---|---|
| `web/src/appDurableWiring.test.tsx` | 路由调用序列、alert/message 来源透传、按钮/aria 铬字；非叙事 formatter |
| `web/src/buildResources.test.ts` | 构建资源存在性 |
| `web/src/chatFailures.test.ts` | 失败路径结构／调用 |
| `web/src/cliRunners.test.ts` | runner 选项结构化 value/label 真源 |
| `web/src/components/cliRunnerDropdown.consistency.test.tsx` | 设置页固定界面文案一致性 |
| `web/src/components/decisionModal.test.tsx` | 批红 UI 结构标签／选项来源 |
| `web/src/components/drawers.test.tsx` | 名册/地点结构化字段进 DOM（非自由叙事锁） |
| `web/src/components/electronLayout.medium.test.tsx` | 布局度量键 |
| `web/src/components/gameMenu.test.tsx` | 设置页 Base URL / CLI Runner 固定界面 |
| `web/src/components/map.test.tsx` | **P4 负向闸**：驻军表不得直显 mutiny/士气/欠饷定性；region 名优先于 theater label |
| `web/src/components/menuPage.test.tsx` | 菜单/覆盖确认等固定界面文案 |
| `web/src/components/modals.test.tsx` | 召对按钮铬字、原始 LLM 输出透传、会话隔离负向 |
| `web/src/components/settlementFaces.test.tsx` | HUD 导航/aria、王承恩条常量（界面固定话语） |
| `web/src/components/settlementGazettePanel.test.tsx` | 邸报面板结构 |
| `web/src/components/situation.test.tsx` | 奏疏正文==来源；已去机器字段黑名单 |
| `web/src/decisionRouting.test.tsx` | 路由行为 |
| `web/src/escClose.test.tsx` | Esc 关闭交互 |
| `web/src/mindreading.test.ts` | 结构化透镜 |
| `web/src/mindreadingDelivery.test.tsx` | 递话隔离负向（角色串） |
| `web/src/ministerScrollLens.test.ts` | 透镜结构（上轮已清赴京等盯文） |
| `web/src/reasoningSupport.test.ts` | 推理档支持矩阵 |
| `web/src/settleStream.test.ts` | SSE/流式行为 |
| `web/src/settlementPresentation.test.ts` | face 可达性结构化矩阵（无固定叙事句） |
| `web/src/staleGuard.test.tsx` | 陈旧守卫 |
| `web/src/useDurableProjection.test.tsx` | 投影 hook |
| `web/src/useSettlementFlow.test.tsx` | 结算流 URL/阶段 |

未把「一切 UI toContain」扩成必删；只清叙事生成物／机器字段／formatter 同型。无「helper源标签泛化例外」。

## 仍存在、已记保留（非清退对象；逐条依据）

- `#321` `sit[*] in report/materials` — **实际模型调用输入来源**。
- `character_context` 中 `identity`/`seed_guilt` 键名隔离闸 — 闸类，非呈现扫文。
- Web P4：map 驻军表不得直显定性军心/士气/欠饷。
- 大量结构化 `key not in payload` ABI（非呈现扫文）。
- `test_db_broad_except_surface` — **仅**损坏 JSON 回退结果；**不再** `assert msgs`。
- `test_region_cannon_delta` 断言消息含「城防炮」字样 — 行为说明，非呈现措辞锁。
- `test_fiscal_levy_effect::incomplete_first_pass` HEAD 原 silent tlog — 非 msgs 换形；行为断言独立。

## 临时变异（真实入口；独立进程插件；不改生产／不新增永久测试）

插件（仅 `/tmp`）：`/tmp/d5-audit-1902/mut/restore_patch_directive.py`
作用：`pytest_configure` 将 `PATCH /api/directives/{directive_id}` 插到路由表前端并返回 200。

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false

# 未变异（绿）
/usr/bin/time -p python3 -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/d5-audit-1902/bt-control \
  tests/test_web_audience_night_498.py::test_asgi_dossiered_directive_has_no_retired_review_surface
# → 1 passed in 1.04s；real 1.60

# 变异（红）：PYTHONPATH 加载临时插件
/usr/bin/time -p env PYTHONPATH=/tmp/d5-audit-1902/mut:$PYTHONPATH \
  python3 -m pytest -q -p no:cacheprovider -p restore_patch_directive \
  --basetemp=/tmp/d5-audit-1902/bt-mut \
  tests/test_web_audience_night_498.py::test_asgi_dossiered_directive_has_no_retired_review_surface
# → FAILED：assert 200 in (404, 405)；1 failed in 0.21s；real 1.04
```

结论：保留案 `test_asgi_dossiered_directive_has_no_retired_review_surface` 经真实 HTTP 入口咬合；临时恢复旧 PATCH 可达即红，未变异绿。生产未改。

## 验证（七个 `MING_SIM_*_BIN=/usr/bin/false` 完整前缀；只聚焦）

前缀（每条命令均带）：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

```text
python3 -m pytest -q -p no:cacheprovider --basetemp=$AUDIT/bt-focus \
  tests/test_army_display_173.py tests/test_army_firearms.py \
  tests/test_commitment_display_348.py tests/test_population_unit_648.py \
  tests/test_decree_dossiers_571.py tests/test_region_cannon_delta.py \
  tests/test_identity_seed_488.py tests/test_fiscal_levy_effect.py \
  tests/test_web_entry_1902.py tests/test_qa_d1_decree_normalize_1274.py \
  tests/test_player_army_projection_321.py \
  tests/test_db_broad_except_surface.py \
  tests/test_web_audience_night_498.py::test_asgi_dossiered_directive_has_no_retired_review_surface \
  tests/test_web_audience_night_498.py::test_legacy_pending_only_advances_to_durable_dossier_without_review_api \
  tests/test_fiscal_substrate_bridge.py::test_apply_fixed_period_flows_malformed_fiscal_json_isolated \
  tests/test_fiscal_substrate_bridge.py::test_substrate_malformed_settle_shape_isolated_by_fixed_flows \
  tests/test_fiscal_substrate_bridge.py::test_apply_fixed_period_flows_malformed_fiscal_scalar_isolated \
  tests/test_fiscal_substrate_bridge.py::test_substrate_corrupt_stock_isolated
# → 263 passed, 1 skipped in 7.17s；real 7.54

python3 -m pytest -q -p no:cacheprovider --basetemp=$AUDIT/bt-fiscal \
  tests/test_fiscal_substrate_bridge.py::test_province_pay_shortfall_reduces_pure_province_army_morale \
  tests/test_fiscal_substrate_bridge.py::test_turn_army_summary_keeps_real_morale_changes_when_log_cap_fills
# → 2 passed in 1.08s；real 1.43

cd web && npx vitest run --environment jsdom \
  src/components/situation.test.tsx src/components/map.test.tsx
# → 13 passed；Duration 1.46s；real 2.53
```

`git diff --check`：已修 `evidence/issue-1902/D5-members.md` 末尾空行；检查无输出。

## 变更路径一览

```
tests/test_army_display_173.py
tests/test_army_firearms.py
tests/test_commitment_display_348.py
tests/test_decree_dossiers_571.py
tests/test_db_broad_except_surface.py   # 本轮自验：去 assert msgs
tests/test_fiscal_levy_effect.py        # 本轮自验：删四处静默换形
tests/test_fiscal_substrate_bridge.py
tests/test_identity_seed_488.py
tests/test_population_unit_648.py
tests/test_qa_d1_decree_normalize_1274.py
tests/test_region_cannon_delta.py
tests/test_region_citydefense_display.py   # deleted
tests/test_web_audience_night_498.py
tests/test_web_entry_1902.py
tests/test_web_issue_condition_display.py  # deleted
tests/test_player_army_projection_321.py
web/src/components/situation.test.tsx
evidence/issue-1902/D5-members.md
evidence/issue-1902/d5-current-receipt.md
```

## 主修内司复验

完整七 BIN 前缀执行 `python3 -m pytest -q -p no:cacheprovider tests/test_army_display_173.py tests/test_db_broad_except_surface.py tests/test_web_audience_night_498.py::test_asgi_dossiered_directive_has_no_retired_review_surface`：`12 passed in 1.06s`。
`git diff --check` 无输出；`test ! -e /tmp/d5-audit-1902` 输出 `d5-audit-1902_removed=True`。

## 清理证据（自建物）

回执写入后执行：

```bash
rm -rf /tmp/d5-audit-1902
test ! -e /tmp/d5-audit-1902 && echo 'd5-audit-1902_removed=True'
```

（清理结果见交卷输出；未碰非自建 `/tmp` 物。）

## 未结项

- 修内司检查后独立提交；提交 SHA 由终局回执记录。
- 未跑全量 pytest／未 push／未开 PR。
- 未新增永久扫描机制；临时 AST／变异插件仅 `/tmp`，清理后不入仓。
