# #1902 修内司 S1–S3 回执

- 分支：`ak-roles/1902-s123-fixer-6850e0b5f`
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5`
- 底座 HEAD（开工）：`6850e0b5ff7f6f1c7e155b6002334f43d57c4cfb`
- 判词真源：附件 `05-1902-judge-6850e0b5f.json` → `outcome.payloads[-1]`（status=continue；findings S1/S2/S3）
- 派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a109b6-e895-77f7-818f-eecda14836ac@fixer/fix-packet.md`
- 官方生态：[pytest monkeypatch](https://docs.pytest.org/en/stable/how-to/monkeypatch.html) 临时插件做秒级变异；SSE 真源复用 `tests/sse_helpers.py`；不新增永久扫描器/生产钩子/平行夹具
- 枚举：`s123-s1-enum.json` / `s123-s2-enum.json` / `s123-s3-enum.txt`；复扫 `s123-rescan.out`
- 聚焦：`s123-focus-pytest.txt`（316 passed in 6.54s；real 7.06）
- 变异：`s123-mutations.out` / `s123-mutations-http.out`
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

## 末判三类完整定义（逐字自 payloads[-1].fix.classes）

1. **S1：退役实现清退**  
   direction：依实际生产消费者清退无用途旧根、独占子树与专属测试；保留现役共享能力，不恢复手拟新旨入口。  
   law：#1902；#1812验收第1项；硬规12、14。

2. **S2：真实行为测试归位**  
   direction：按独立外部行为契约核对剩余内部证明，复用已有真实入口 tracer 承载必要拒收及持久结果，删除内部形状和重复证明；不得删除负向契约或mock替代被测编排。  
   law：硬规13；《测试对行为负责》。

3. **S3：解析单源**  
   direction：消费者复用已有 SSE、数值取值实现，删除同构副本；保留原有输入、协议和外部结果契约。  
   law：硬规12、14；#1812验收第1项。

边界：不新增护栏、兼容层、永久扫描器、生产测试钩子或逐finding平行夹具；不改治理、宿主或席位配置；本轮不索全量。

---

## 扫描命令与谓词（可重放；临时 AST，未入库永久扫描器）

### S1 谓词

非测试生产 AST 引用为 0 的旧根（入口/传输退役理解链、恢复产文、旧前缀、伪工具拆包、夜庭短路、暂存任命判定），并沿 call-graph 扩展其独占子树；专属测试随根删除。保留 `secret_order_can_land` / `landing_gaps` / `CliChat` / `_fake_completion` / 现役 `resubmit→heal→extract`。

```bash
# AST 全仓 defs + 生产引用计数 → evidence/issue-1902/s123-s1-enum.json
# 复扫：evidence/issue-1902/s123-rescan.out（DEAD 符号 prod/test refs=0，仅注释残留 _extract_secret_order）
```

### S2 谓词

`test_*` 调用 `validate_all` / `map_rescript_option_or_choice` 且无真实编排（`submit_hitl_choices` / `_post_resolve` / ASGITransport / `_adjudicate_cli_decisions`）者列为候选；逐项按「提交路径拒收/批语落库」vs「领域首写/输入适配独立契约」分类。→ `s123-s2-enum.json`

### S3 谓词

测试侧本地 `event:`/`data:` 拆包循环；生产侧 `_runtime_float` 与 `_slot_number` 同构浮点取值。权威：`tests/sse_helpers.py`、`ming_sim/llm_config._slot_number`。→ `s123-s3-enum.txt`

---

## 完整成员表

### S1 — 退役实现清退

| 成员 | 处置 | 依据 |
|---|---|---|
| `_extract_secret_order` + 独占子树（`assemble_secret_order_content`、`confirm_dossier_links`、`_choose_assignee`、`_split_audience_context`、`_secret_metadata_from_command`、拼装/上下文/名册确认 helpers） | **删除** | 生产引用 0；现役密令走 `audience_translate→declaration_dispatch` |
| `compose_decree_validation_recovery` / `compose_secret_order_landing_recovery` / `_compose_inworld_fact_report` / `_secret_landing_gap_feature` / `_SECRET_LANDING_GAP_LABELS` | **删除** | 生产引用 0 |
| `_DRAFT_PREFIXES` / `_SECRET_PREFIXES` / `_matched_prefix` / `_secret_prefix_needs_recent_context` / `_SECRET_CONFIRM_ATOM_RE` | **删除** | 旧前缀分派无消费者 |
| `_cli_prompt` / `_cli_stream_safe_prefix` / `_cli_recommendation_call` / `_CLI_RECOMMENDATION_*` | **删除** | 伪工具拆包根；`CliChat.invoke` 已直走 `_messages_to_prompt`+`_fake_completion` |
| `_target_active_officeholder` / `_open_night_court_break` / `_is_active_secret_order_assignee` | **删除** | 生产引用 0 |
| `secret_order_can_land` / `secret_order_landing_gaps` / `CliChat` / `_fake_completion` / `extract_draft_intent*` | **保留** | 现役生产消费者 |
| `tests/test_cli_backend.py` 三处 `_extract_secret_order` 专属案 + `_so_json` | **删除** | 专属测试 |
| `test_secret_order_isolation_883` 对已删 helper 的断言 | **改外部 SQL** | 保留「undo 后承办人无 active 密令」外部结果 |

### S2 — 真实行为测试归位

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_657_default_hold_preserves_red_pen_note` | **迁真 submit** | 复用 `_real_submit_session`；断言落库 note/hold |
| `test_657_appointment_name_target_id_conflict_batch_reject` | **迁真 HTTP** | `_post_resolve` + `event: error` + pending/零写 |
| `test_657_punishment_name_target_id_conflict_zero_writes` | **删 helper 前缀、钉 SSE error** | 已有 HTTP；去掉 mapper-only 重复；补 `event: error` |
| `test_mapper_rejects_contradictory_locality_scope_without_overwrite` | **迁真 submit** | `StructuredDecreeCombinationError` 经 `submit_hitl_choices`；合法案亦经 submit 落 decided |
| `test_adjudication_blank_on_ordinary_decision_reprompts` 等 CLI 输入案 | **保留** | 入口输入适配独立接缝（上判已驳回误删） |
| `test_657_five_actions_domain_writes` / `abi_mapper_matrix` / `prewrite_failure` / `658_*` / midzhi 领域落库等 | **保留** | 领域首写/apply/prewrite 独立契约（boundary 明示不因含 helper 删除） |

### S3 — 解析单源

| 成员 | 处置 | 依据 |
|---|---|---|
| `tests/test_audience_scroll_539.py` 两处 inline SSE 拆包 | **改 `parse_sse_event_pairs`** | 删副本 |
| `tests/test_qa_b3_409_ux.py::_consume_resolve_sse` | **改 `parse_sse_event_pairs`** | 删副本 |
| `tests/test_player_payload_1022.py::_serialized_terminal_event` | **改 `parse_sse_event_pairs`** | 删副本 |
| `ming_sim/llm_config._runtime_float` | **删除**；调用改 `_slot_number` | DRY |
| `web_app` 对 `_runtime_float` 的读档投影 | **改 `_slot_number`** | 同真源 |
| `tests/sse_helpers.py` / `_slot_number` | **保留权威** | — |

---

## 逐 finding 处置

| id | 根因 | 处置 |
|---|---|---|
| S1 | 被替代旧实现与专属测试仍占维护面 | 按生产消费者删净旧根+独占子树+专属测；现役共享保留 |
| S2 | helper-only validate/mapper 绕过真实提交，禁用 submit 仍绿 | 点名三案+同类 HTTP 拒收改走真实 tracer；领域首写保留 |
| S3 | SSE/浮点解析多份 | 消费者改权威实现；删 `_runtime_float` |

---

## 变异证明（临时插件，不入库）

参照 [pytest monkeypatch](https://docs.pytest.org/en/stable/how-to/monkeypatch.html)。

1. **S2 disable_submit_validate**：`GameSession.submit_hitl_choices`→恒接受  
   - 修后：default_hold note / locality / ordinary 拒收 / appointment+punishment（`event: error`）报红；恢复后全绿。
2. **S3 break_sse**：`parse_sse_event_pairs`→`[]`  
   - scroll / resolve SSE 案红；恢复绿。
3. **S3 slot_number 临时恒 1.0**：`llm_config_from_runtime` timeout 变 1.0；恢复后 99.0。
4. **S1**：删除后 `hasattr(_extract_secret_order)=False`；`CliChat`/`secret_order_can_land` 仍在。

---

## 聚焦测试

```
316 passed in 6.54s
real 7.06
```

命令见 `s123-focus-pytest.txt`。未跑全量、未真调模型。

---

## 自查二连

- **合法性**：未改 CLAUDE.md/AGENTS.md/CONTEXT.md/ADR；未恢复手拟入口；未增护栏/扫描器/生产钩子。
- **质量**：S2 负向保留并经真实入口；S3 删副本不削弱断言。
- **复杂度**：净删 cli_backend ~730 行死根 + 浮点副本；测试侧以迁真/删专属为主，无逐 finding 平行夹具。
- **复扫**：`s123-rescan.out` — S1 DEAD 无功能残留；S3 inline unpack / `_runtime_float` 零命中。

---

## 例外 / 上呈

无缺 owner 决定项。剩余 validate_all/map 无 orch 成员均已按 boundary 记为领域首写或 CLI 输入独立契约，不整删。
