# #1902 修内司 S1–S3 回执（自查纠正）

- 分支：`ak-roles/1902-s123-fixer-6850e0b5f`
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5`
- 底座 HEAD（开工）：`6850e0b5ff7f6f1c7e155b6002334f43d57c4cfb`
- 上一交卷：`0e45e5d22966d32b48e6cced2a12b618c121c846`（谓词收窄，本轮纠正）
- 判词真源：附件 `05-1902-judge-6850e0b5f.json` → `outcome.payloads[-1]`（status=continue；S1/S2/S3）
- 派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a109b6-e895-77f7-818f-eecda14836ac@fixer/fix-packet.md`
- **不宣称已合并 / 总票完成**

七 BIN 前缀（显式展开）：

```bash
env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=. \
  python3 -m pytest ...
```

---

## 上轮收窄与本轮纠正

| 问题 | 纠正 |
|---|---|
| S2 谓词仅 `validate_all/map` 且无 orch | 全仓 `tests/*.py` 枚举 focus 符号全集，再逐项语义分类；**禁止** mapper/apply/prewrite 统称「领域首写」豁免 |
| S1 仅点名旧理解链扩展 | `git ls-files *.py` 全集 AST defs + 生产 Load/Attribute；样本+模式扩展；框架入口（FastAPI `@app.get`）单独核对 |
| S3 仅样本 SSE / `_runtime_float` | 全仓 `event:`/`data:` 同构拆包 + float 同构 coerce；权威外零 inline 副本 |
| 枚举命令仅注释 | 临时 AST 全文见 `s123-scan-s{1,2,3}.ast.py.txt`；下方可重放命令 |
| 变异冒称 hasattr 为行为证明 | hasattr **仅** S1 删除观察；行为变异为 submit/SSE/slot 真入口红绿 |

---

## 末判三类定义（逐字）

1. **S1：退役实现清退** — 依实际生产消费者清退无用途旧根、独占子树与专属测试；保留现役共享能力，不恢复手拟新旨入口。
2. **S2：真实行为测试归位** — 按独立外部行为契约核对剩余内部证明，复用已有真实入口 tracer 承载必要拒收及持久结果，删除内部形状和重复证明；不得删除负向契约或 mock 替代被测编排。
3. **S3：解析单源** — 消费者复用已有 SSE、数值取值实现，删除同构副本；保留原有输入、协议和外部结果契约。

---

## 可重放枚举命令（临时 AST，未入库永久扫描器）

扫描脚本全文：`evidence/issue-1902/s123-scan-s1.ast.py.txt` / `s123-scan-s2.ast.py.txt` / `s123-scan-s3.ast.py.txt`（`.txt` 后缀，非 importable 模块）。

```bash
# 在仓根执行；脚本可先复制到 /tmp
cp evidence/issue-1902/s123-scan-s1.ast.py.txt /tmp/scan_s1.py
cp evidence/issue-1902/s123-scan-s2.ast.py.txt /tmp/scan_s2.py
cp evidence/issue-1902/s123-scan-s3.ast.py.txt /tmp/scan_s3.py
python3 /tmp/scan_s1.py | tee evidence/issue-1902/s123-s1-rescan-summary.txt
# → /tmp/ming1902-s123-resc/s1-raw.json → 复制为 s123-s1-enum.json
python3 /tmp/scan_s2.py | tee evidence/issue-1902/s123-s2-rescan-summary.txt
# → s2-focus.json → s123-s2-enum.json
python3 /tmp/scan_s3.py | tee evidence/issue-1902/s123-s3-enum.txt
```

### 谓词（覆盖类定义全文，未收窄）

- **S1**：tracked `*.py` 生产 FunctionDef/ClassDef；非测试 Load/Attribute refs==0 且（判词样本名 ∪ 理解链/恢复/前缀/伪工具名模式）→ 死根候选；沿独占测删除；FastAPI 装饰器入口不算 AST Load，须人工核 `@app.*`；KEEP_SHARED 点名现役。
- **S2**：tracked `tests/*.py` 中 `test_*` 体引用 `validate_all|map_rescript_option_or_choice|map_rescript_option|RescriptAdjudication|StructuredDecreeCombinationError`；orch=`submit_hitl_choices|_post_resolve|ASGITransport|_adjudicate_cli_decisions|AsyncClient|TestClient|_real_submit_session|resolve_and_submit|_submit_hitl`；**每行必填**契约/生产入口/外部结果/既有 tracer/是否重复；不得因含 helper 删，不得因 apply/prewrite 笼统留。
- **S3**：非 `tests/sse_helpers.py` 的 `startswith("event:")`/`data:` 同构拆包；生产侧小 float coerce / `_runtime_float`；权威=`parse_sse_event_pairs`/`parse_sse_events` + `llm_config._slot_number`。

---

## S1 完整成员表（语义核对，非零命中计数）

| 成员 | 可核契约 | 真实生产入口 | 外部结果 | 处置 |
|---|---|---|---|---|
| `_extract_secret_order`+独占子树（上轮已删） | 旧密令理解 | 无 | — | **已删**（复扫 defs 缺席） |
| `compose_*_recovery` / 旧前缀 / `_cli_prompt` / `_cli_recommendation_*` / `_target_active_officeholder` / `_open_night_court_break` / `_is_active_secret_order_assignee` | 旧恢复/前缀/夜庭 | 无 | — | **已删** |
| `upsert_secret_order` | 按大臣最新 active 改密令 | 生产 refs=0（现役 `create`/`update_secret_order_by_id`） | — | **本轮删** + 专属 `test_upsert_*` |
| `attach_secret_oral_pin` | 口谕 pin 附加载荷 | 全仓零调用 | — | **本轮删** |
| `api_secret_orders` | 玩家密令列表 | `@app.get("/api/secret_orders")` 框架入口 | HTTP JSON orders | **保留**（AST 假死） |
| `secret_order_can_land` / `landing_gaps` / `CliChat` / `_fake_completion` / `extract_draft_intent*` / `resubmit→heal→extract` | 现役共享 | 有生产消费者 | — | **保留** |
| `update_secret_order_by_id` + 其测试 | 精确 id 更新 | declaration/会话更新 | DB 要旨 | **保留** |
| `upsert_secret_order_brief` 等密令 DB/月链族 | 现役密令账 | 有 prod refs | — | **保留** |

ZERO_PROD_REF 中大量 FastAPI handler / dunder / 仅测试调用的公开 API：**不**按死根删——须有「无框架/无字符串分派消费者」才删。本轮仅处置确认死根 `upsert_secret_order`、`attach_secret_oral_pin`。

---

## S2 完整成员表（逐项契约；禁止笼统「领域首写」）

扫描后 **11** 行 focus；**9 ORCH / 2 NO_ORCH**。另：上轮/本轮迁真后已不再出现在 no_orch 列表的成员亦记入处置。

| 成员 | 可核契约 | 真实生产入口 | 外部结果 | 既有 tracer | 重复？ | 处置 |
|---|---|---|---|---|---|---|
| `test_657_default_hold_preserves_red_pen_note` | 默认 hold 保 note | `submit_hitl_choices` | decided+note | `_real_submit_session` | 否 | **ORCH 保留** |
| `test_657_*_conflict_*` / locality mapper | 身份/辖域冲突整批拒 | HTTP `_post_resolve` / submit | SSE error / ValueError+零写 | 同文件 HTTP | — | **ORCH 保留**（上轮已迁） |
| `test_657_five_actions_domain_writes` | 五动作领域写 | — | — | `test_657_s10_http_five_actions_*` | **是** | **本轮删** |
| `test_657_p6_*` | 廷议 title/body 原文；title>80 拒 | `_submit_hitl` | issues/dossier 原文；pending | `_submit_hitl` | 否 | **迁真**；mapper 返回形状断言删；`normalize_rescript_layer_a_option` 缺键拒=**票拟输入接缝保留** |
| `test_657_record_event_*` | event ledger 抛错整批回滚 | `_submit_hitl` | pending 零 decided | `_submit_hitl` | 否 | **迁真** |
| `test_657_prewrite_failure_*` | prewrite 失败零写 | `_submit_hitl`+`run_prewrite_llms` 注入 | pending | `_submit_hitl` | 否 | **迁真** |
| `test_657_follow_draft_ignores_client_field_overlay` | 目录权威抗 overlay | `_submit_hitl` | dossier target=shaanxi | `_submit_hitl` | 否 | **迁真** |
| `test_657_midzhi_persists_*` | midzhi decision_key+label | `_submit_hitl` | payload/decree_text | `_submit_hitl` | 否 | **迁真** |
| `test_657_midzhi_verdict_no_party_satisfaction` | midzhi 判不写派系满意度 | submit 种案 + `apply_dossier_verdicts` | satisfaction 不变、parties=[] | submit + apply_dossier | 否 | **迁真种案**；判决腿=**独立判决写接缝保留** |
| `test_1682_late_grants_*` | 内库自动闭案/国库待审；失败回滚 | `_submit_hitl` | grant 分流；回滚零写 | `_submit_hitl` | 否 | **迁真**（phase2 消费 pending 属编排，不钉 apply 旁路形状） |
| `test_657_abi_mapper_matrix_a1_a12` | A1–A12 判后世界事实 | `_apply_mapped_choice`→`_submit_hitl` | initiative/army/流水等 | `_submit_hitl` | 部分 map 正负断言仍直调 map | **apply 链迁真**；残留 `map_rescript_*` 正/负=**map 类型输入拒收/适配**（与 submit 内同一 map；**非** apply 豁免）。不整删矩阵。 |
| `test_658_deliberate_*` / `_658_plant_*` / candidates | 廷议 backed/stalled/非法站台 | `_submit_hitl` | endorsement/issue/零写 | `_submit_hitl` | 否 | **迁真** |
| `test_658_stage_rejects_bad_backing_*` | stage 首写拒坏 backing | `stage_punishment_candidate` | pending/案卷/信用零写 | 直调 stage | 否 | **保留**（末判明示 stage 首写例）；backing 经 submit 种 |
| `test_financial_decision_uses_stored_option_*` | 目录金额权威抗客户端 | `submit_hitl_choices`；坏 amount→`parse_decision_blocks` | grant 内库/30 | `_real_submit_session` | 否 | **迁真**；非 int 参数=**parse 输入接缝** |
| `test_rescript_follow_draft_nails_drafted_roster` | 票拟名单钉主办 | `submit_hitl_choices` | roster 落库 | `_real_submit_session` | 否 | **迁真** |
| `test_657_applied_revise_refresh_*` | 已应用 revise 的 GET/空 POST | `_get_state`/`_post_resolve` | resume_phase2、清锚 | HTTP | validate+apply **仅种 fixture**（全 submit 会清 choice，无法再现中段态） | **保留**；契约在 HTTP 腿，非 validate 形状 |
| `test_adjudication_blank_*` / CLI blank pick | CLI 输入适配 vs 核拒收 | `_adjudicate_cli_decisions` / submit | reprompt / ValueError | 同文件 | 否 | **保留**（上判已驳误删） |
| `test_validate_all_unknown_roster_name_*` | 名册未知→建档零行 | `create_decree_dossiers` | COUNT 不变 | 直调 create | 扫描假阳性（名含 validate_all） | **保留**；契约非 validate_all |
| `test_shared_validate_rejects_region_id_*` | assemble typed 洞 | `assemble_structured_decree` | `StructuredDecreeCombinationError` | 直调 assemble | 否 | **保留**；**非** HITL validate 编排 |

---

## S3 完整成员表

| 成员 | 处置 | 依据 |
|---|---|---|
| `tests/sse_helpers.py` `parse_sse_events` / `parse_sse_event_pairs` | **权威保留** | — |
| scroll/qa_b3/player_payload 旧 inline 拆包 | **上轮已改权威** | 复扫 inline=∅ |
| `test_court_break_player_lock_1727._parse_sse_chunk` / `test_web_audience_night_498._parse_sse` | **薄包装保留** | 仅转发 `parse_sse_events`，非同构实现 |
| `_runtime_float` | **上轮已删**；调用改 `_slot_number` | 复扫 defs 缺席 |
| `distance._number` / `issues._as_float` / `flows._as_*` / `db._coerce_pay_source_float` 等 | **保留** | 职责=图代价/财政响亮拒收等，**非** runtime slot 默认回落同构 |

---

## 变异证明（临时插件，不入库）

方法：[pytest monkeypatch](https://docs.pytest.org/en/stable/how-to/monkeypatch.html) 进程内插件。证据：`s123-mutations.out`。

| 模式 | 入口 | 结果 | 性质 |
|---|---|---|---|
| `GameSession.submit_hitl_choices`→恒接受 | default_hold / follow_draft overlay / midzhi persists / ordinary 空 pick | **4 failed** | **行为变异红** |
| 恢复原方法 | 同上 | **4 passed** | 恢复绿 |
| `parse_sse_*`→`[]` | scroll×2 + player_payload SSE | **4 failed** | **行为变异红** |
| 恢复 | 同上 | **4 passed** | 恢复绿 |
| `_slot_number`→恒 1.0 | `cli_idle_timeout_seconds({"cli":{"timeout_seconds":99}})` | 99→1.0→99 | **真入口秒级** |
| `hasattr(upsert/attach/extract)` | — | False | **仅删除观察**，不冒称行为证明 |
| `hasattr(can_land/CliChat/update_by_id)` | — | True | 删除观察·保留侧 |

---

## 聚焦测试

`evidence/issue-1902/s123-focus-pytest.txt`：

```
374 passed in 33.56s
```

未跑全量、未真调模型。

---

## 自查二连

- **合法性**：未改 CLAUDE.md/AGENTS.md/CONTEXT.md/ADR；未恢复手拟入口；未增护栏/永久扫描器/生产钩子；扫描脚本以 `.ast.py.txt` 证据形态存放。
- **质量**：S2 负向经真实 submit/HTTP；删五动作 helper 重复；不整删 stage/assemble/create_decree 独立接缝；S3 无同构 SSE 残留；数值同构仅 `_slot_number` 职责。
- **复杂度**：净删 upsert/attach + 重复五动作案；批红测以迁真为主。

---

## 例外 / 上呈

无缺 owner 决定项。`api_secret_orders` 框架入口假死已说明。abi 矩阵内残留直调 `map_rescript_*` 归类型输入适配，apply 落库已走 submit。
