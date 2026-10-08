# #1797 阶段 0 诊断（卷面盘点 + 真实复放 + 现行为固定）

基线：分支 `fix/issue-1797-w1` · 诊断起点 `1fc47a1f1`（= main 无施工）  
红线：不改 ming_sim/web 生产、不改 transport 分类、不改 provider/默认模型、不改 `runtime_llm.json`；复放临时参数，跑完配置原样。  
模型硬限（owner 2026-09-08）：`deepseek/deepseek-v4-flash-0731`，**不准改默认模型**。  
复放通道：本机 `hermes proxy start --provider nous` → `http://127.0.0.1:8645/v1`（任意 bearer，凭据在 hermes 内；本文无 key）。

证据源：
- Issue #1797 评论 + 冻结副本 `/Users/akagilnc/WorkSpace/vault/ak-cc-wiki/raw/ming-llm-runner/2026-09-08/1797-evidence/`（`llm_dump_extracts/INDEX.md` 11 分片、error pack、log-excerpt）
- 复放原始行：`docs/evidence/issue-1797/replay-raw.jsonl`（脱敏；无 Authorization）
- 现行为固定测试：`tests/test_settlement_extractor_transport_1750.py::test_extractor_empty_terminal_exhausted_pins_current_behavior`

---

## 1. 卷面盘点（QA 已证）

| 项 | 事实 |
|----|------|
| 场景 | 新开局 1627-10 亲裁两道后 phase2 续跑；日志「并发抽取 6 腿」 |
| 模型 | `deepseek/deepseek-v4-flash-0731` via Nous Hermes |
| 失败腿 | `extractor/internal`（system 57086 / user 354）×3 settle1 全空；`rescript-draft`（system 5273 / user 4183）×3 全空；retry 再同症（internal 第 5 次才 146 字空壳 JSON） |
| 成功腿 | personnel_secret / military_external / relations / issues 有字（2–80s） |
| dump 形态 | assistant 角色存在，正文 `''`（0 字）；非解析失败、非半截 |
| 错误包 | `LLMUnavailable: LLM 调用失败（已尝试 3 次）：empty output`（manifest attempt 写包序号） |
| 57KB system 全文 | 只在 QA 箱 `llm_dump_2517790.log`；本机分片未带全文，**不得臆造** |

指针：vault `1797-evidence/llm_dump_extracts/` · `turn1_attempt1-manifest.json` · `log-excerpt.txt`。

---

## 2. 代码接缝盘点（读码，main 形）

### 2.1 空输出 → 可重试 → 耗尽

| 接缝 | 位置 | 现行行为 |
|------|------|----------|
| 终包取文 | `ming_sim/agents.py` `run_agent_text` → `_after_stream` | 只收 `RunOutput`/`RunCompletedEvent`；`text = extract_agent_text(output)`；`if not text` → `empty_output_failure()` |
| 取文权威 | `ming_sim/llm_model.py` `extract_agent_text` | **只读** `run_output.content`（None→`""`）；**不读** reasoning 类字段 |
| 空输出分类 | `ming_sim/llm_transport.py` `empty_output_failure` | `retryable=True` · `code=llm_empty_output` · `provider_message="empty output"` |
| 重试预算 | `TransportPolicy.max_attempts` 默认 **3**（`TRANSPORT_DEFAULT_MAX_ATTEMPTS`） | 可重试耗尽 → `transport_failure_unavailable(..., exhausted=True)` → 文案「已尝试 N 次：empty output」 |
| dump | `agents._dump_llm_messages` | 只写 `message.content` 字数/正文；**reasoning 字段不落 dump** → QA dump「0 字」**不能证伪**「上游有 reasoning」 |
| 空转活动 | `is_stream_activity_event` | reasoning 增量算活动（刷新 idle），**仍不进终文** |

### 2.2 请求构造路径

| 身份 | 工厂 | temperature / top_p | thinking 意图 | force_json | system 来源 |
|------|------|---------------------|---------------|------------|-------------|
| extractor/*（含 internal、relations） | `create_score_extractor_module_agent` | 0.1 / 0.7 | `enable_thinking=False` | `True` → `extra_body.response_format=json_object` | `game_world` + `build_simulator_context(payload)` + `score_extractor_shared` + supplemental + module prompt |
| 票拟 `rescript-draft` | `create_rescript_draft_agent` | 0.4 / 0.9 | 同上 | 同上 | `game_world` + `rescript_draft` + 层 A/结构化旨意契约 |
| 角色模型槽 | `_llm_for_role(..., "extractor")` | — | — | — | 与 extractor 同 runtime 模型 |

`create_chat_model` 默认 `extra_body = provider_extra_body(base_url)`：

```
is_deepseek_base_url = "deepseek.com" in base_url
→ deepseek 官方：{"thinking": {"type": "disabled"}}
→ Nous（inference-api.nousresearch.com / hermes proxy）：**None**
```

因此 QA 现场 Nous + `deepseek/deepseek-v4-flash-0731` 路径上：**生产并未下发 thinking/reasoning 关闭**；`enable_thinking=False` 对非 dashscope/minimax/deepseek.com base_url **不产生 extra_body 键**。  
`force_json_output` 只并入 `response_format=json_object`。

Nous 模型目录（proxy `/v1/models`，本机复放时读到）对 `deepseek/deepseek-v4-flash-0731` 原文要点：
- *Thinking is on by default and can be disabled; control depth with the `reasoning` parameter.*
- `reasoning.default_enabled: true` · `mandatory: false` · efforts `max|high|low`

### 2.3 失败两腿 vs 成功腿（relations）逐项差异表

| 维 | extractor/internal（败） | rescript-draft（败） | relations（成） |
|----|--------------------------|----------------------|-----------------|
| 调用工厂 | score extractor module | rescript draft agent | **同** score extractor module |
| temperature | 0.1 | **0.4** | 0.1 |
| top_p | 0.7 | **0.9** | 0.7 |
| enable_thinking 入参 | False | False | False |
| force_json_output | True | True | True |
| 生产 extra_body（Nous） | `{response_format: json_object}` only | 同左 | 同左 |
| max_tokens | **未设** | **未设** | **未设** |
| system 体量（QA dump） | **57086** | 5273 | （dump 未单列；user 199 字、完成 96 字/30.8s） |
| user 体量（QA） | 354 | **4183** | 199 |
| user 形状 | `module=internal` + allowed_fields 内政财政 | turn/gazette/issues/targets 大 JSON | `module=relations` + 短 instruction |
| 并行位置 | 6 腿 fan-out 之一 | 同波 companion 腿 | 同波 |
| dump 终文 | 0 字 ×3 | 0 字 ×3（+retry×3） | 有字 |

**同构点**：三腿共用 extractor 模型槽、Nous base_url、json_object、未关 reasoning。  
**分异点**：system/user 体量与 prompt 内容；rescript 温度更高；internal system 独大（57KB）。  
**不得**仅凭体量差异断言根因——须复放字段级证据（下节）。

---

## 3. 真实复放

### 3.1 预算与花费

| 项 | 值 |
|----|----|
| 计划形状 | internal / rescript-draft / relations × (stream=False, stream=True) = 6 |
| 对照追加 | ① `thinking:{type:disabled}`（deepseek.com 同形，证 Nous 是否认）② `reasoning:{enabled:false}` ③ `reasoning:{effort:none}` |
| **实际真实调用** | **9**（= 硬顶；每形状主复放 ≤3，对照占用 leftover） |
| 模型 | 全程 `deepseek/deepseek-v4-flash-0731`（未换模） |
| 上游费用合计 | `upstream_inference_cost` 求和 ≈ **$0.0422**（proxy `usage.cost_details`；另有 proxy 标 `cost=5e-05` 行项未计入上游和） |
| 配置残留 | 复放不写 `runtime_llm.json`；工作树无运行时配置改动 |

### 3.2 主 6 次（生产同形 extra_body：仅 json_object）

| # | shape | stream | finish_reason | content_len | reasoning 类 | reasoning_tokens | wall_s | upstream $ |
|---|-------|--------|---------------|-------------|--------------|------------------|--------|------------|
| 1 | internal | F | stop | 221 | message.reasoning 3496 字 + reasoning_details | 1506 | 34.8 | 0.00280 |
| 2 | internal | T | stop | 220 | delta.reasoning 累计 1321 | 525 | 7.8 | 0.00150 |
| 3 | rescript-draft | F | stop | 727 | reasoning 14415 字 | 7482 | 77.0 | 0.01196 |
| 4 | rescript-draft | T | stop | 1208 | reasoning delta 11663 | 6536 | 70.4 | 0.00949 |
| 5 | relations | F | stop | 29 | reasoning 184 字 | 76 | 2.6 | 0.00028 |
| 6 | relations | T | stop | 12 | reasoning delta 2107 | 950 | 9.1 | 0.00139 |

原始片段（脱敏；完整行见 `replay-raw.jsonl`）：

```
#1 internal nostream: finish=stop content_len=221
  field:reasoning preview: "我们被要求输出 JSON object，只包含 module_allowed_fields…"
  usage.completion_tokens_details.reasoning_tokens=1506

#2 internal stream: finish=stop content_len=220 reasoning_delta_len=1321
  other_delta_keys={"reasoning": 525, "reasoning_details": 525}

#5 relations nostream: finish=stop content_len=29 reasoning_len=184 reasoning_tokens=76
```

**说明**：本机无 QA 57KB system 全文；internal 用 ~56k CJK 占位逼近体量。relations/rescript user 取 vault 分片或同形压缩。复放**未**复现 QA 的 content 全空，但**稳定**观察到 reasoning 与 content 分槽。

### 3.3 对照 3 次（关闭推理参数）

| # | extra_body | content_len | reasoning_len | reasoning_tokens | 结论 |
|---|------------|-------------|---------------|------------------|------|
| 7 | `thinking:{type:disabled}` + json_object | 22 | **5387** | **2648** | **Nous 上 deepseek.com 同形 thinking.disabled 无效**（仍深思） |
| 8 | `reasoning:{enabled:false}` + json_object | 11 | **0** | **0** | **有效关闭** |
| 9 | `reasoning:{effort:none}` + json_object | 11 | **0** | **0** | **有效关闭** |

---

## 4. 假说表

| # | 假说 | 预测 | 复放结果 | 判定 |
|---|------|------|----------|------|
| ① | 输出进 reasoning 字段而 content 空 | 响应有 reasoning_* / reasoning_tokens，content 空或 0 字 | 生产同形 6 次：**reasoning 字段与 reasoning_tokens 稳定非空**；content **本次非空**（未复现 QA 全空）。dump 只记 content → QA「0 字」与「上游仅 reasoning」**相容但未在本机复现空 content**。`thinking.disabled` 对 Nous **无效**；`reasoning.enabled=false` **有效** | **部分成立**：分槽与默认开思考已证；「空 content + 有 reasoning」的 QA 特例 **仍不可判为已复现**（差：QA 全量 system 原文或 provider 原始 HTTP 体） |
| ② | finish_reason=length / 上游截断（57KB system） | finish_reason=length 或 content 截断 | internal ~25k prompt tokens，finish_reason 均为 **`stop`**；content 完整 JSON 形 | **证伪**（在本机占位 57k system 下）；QA 真 system 未到手，**对 QA 原文截断仍不可判** |
| ③ | 流式终包 content 空而 chunks 有字 | stream 累计 content>0 但终包空，或仅 reasoning chunk | stream 三次：content 累计均 >0，finish=stop；有 reasoning delta，**非**「有 chunk 无终文」 | **证伪**（本机）；与 #1465 ②「终包 content ≡ 非流式」既裁一致 |
| ④ | 请求形状（json/max_tokens/temperature/extra_body）触发空回 | 某键组合才空 | 未授权加烧专测；卷面三腿 **同** json_object、**同** 未设 max_tokens、**同** 未关 reasoning；仅温度/体量不同而 QA 成败分叉 | **不可判**（还差：控制变量单键复放或 QA 成功腿完整 dump 对照）；**未**另开调用 |
| ⑤ | 并发限流下上游空 200 | 6 腿同秒空回 | 未授权并发预算；log-excerpt 无 429 行（对比 #1750 有明确 429）。本复放串行 | **不可判**（还差：同模型并发压测授权 + 上游 status 入 pack） |

---

## 5. 根因判定

**已证（代码 + 复放）**

1. 终文权威**只读 content**；reasoning 仅可刷新 idle，**不**进 `extract_agent_text` / dump。  
2. Nous + `deepseek-v4-flash-0731` **默认开思考**；生产 `provider_extra_body` 因 base_url 不含 `deepseek.com` **不下发关闭**。  
3. 关闭正确参数是 **`reasoning: {enabled: false}`**（或 `effort: none`），不是 deepseek 官方的 `thinking: {type: disabled}`（在 Nous 上无效）。  
4. 空 content 耗尽 3 次 → `llm_empty_output` → 错误包 + 月不进（现行为固定测试已钉）。

**未证 / 仍不可判**

- QA 当次 content 全空是否等于「reasoning 有字、content 空」——dump 无 reasoning 列，本机未复现空 content。  
- 57KB 真 system 是否触发截断。  
- 并发/限流是否参与（⑤）。

**最小表述**：  
优先根因候选 = **Nous 默认 reasoning 开启 × 生产未对 Nous 关闭 reasoning × 运输层只认 content**（与 #1459 怪癖外置方向同族；本票不实施）。  
空回的充分触发条件（为何 internal/rescript 空而 relations 有字）**仍不可判**，候选含 prompt 体量/内容与偶发上游行为，需 QA 原文 system 或更多授权复放。

---

## 6. 现行为固定测试

| 项 | 值 |
|----|----|
| 文件 | `tests/test_settlement_extractor_transport_1750.py` |
| 用例 | `test_extractor_empty_terminal_exhausted_pins_current_behavior` |
| 入口 | 真 HTTP `POST /api/decree/issue/stream`（复用 #1468 `tracer_client` + 既有 extract 接线） |
| 替身 | `_TransportAgent(always_empty_terminal=True)` 于 **internal**：活动 chunk + 终包 `content=""` |
| 断言（现行，非 xfail） | `calls >= 3`；SSE `code=llm_empty_output` 且 `provider_message=empty output`；`settlement_recovery.error_pack_path` + `ready_replay is False`；manifest `exception_type=LLMUnavailable` + `attempt>=1`；**月不进**（不锁 exception_message/玩家 message 措辞） |
| 不碰 | `test_extractor_empty_terminal_retries`（空后成功）原样 |

聚焦命令与结果：

```
.venv/bin/python -m pytest \
  tests/test_settlement_extractor_transport_1750.py::test_extractor_empty_terminal_exhausted_pins_current_behavior \
  tests/test_settlement_extractor_transport_1750.py::test_extractor_empty_terminal_retries \
  -q --tb=short
→ 2 passed in 1.07s
```

---

## 7. 最小复现命令（诊断复放）

```bash
# 1) 代理（另终端）
hermes proxy start --provider nous --host 127.0.0.1 --port 8645

# 2) 单次探活（任意 bearer；勿把真 key 写入文件）
curl -sS http://127.0.0.1:8645/v1/models -H 'Authorization: Bearer unused' | head

# 3) 原始结果已落盘（本轮 9 行）
#    docs/evidence/issue-1797/replay-raw.jsonl
# 复放脚本为一次性探针，不入库；需要时按 phase0 表用 OpenAI SDK 指向 base_url=http://127.0.0.1:8645/v1
# model=deepseek/deepseek-v4-flash-0731，extra_body 与上表一致。
```

---

## 8. 修法候选（**只登记，不实施**）

| 候选 | 归属 | 说明 | 风险/依赖 |
|------|------|------|-----------|
| A. Nous/聚合器 base_url 下对 deepseek-v4 下发 `reasoning:{enabled:false}`（extractor/rescript 等 `enable_thinking=False` 路径） | provider 配置 / #1459 怪癖外置 | 复放 #8/#9 已证有效；与 deepseek.com 的 `thinking.disabled` **不是**同一键 | 须纳入 quirks 真源，禁止再硬编码第二套；owner 拍是否默认关 |
| B. transport / `extract_agent_text` 在 content 空时回退读 reasoning（或合并） | transport 分类/取文 | 可能「救回」空 content；但 reasoning 常为思维链非 JSON，易污染 extractor | 与 ADR 0005 响亮失败张力；需契约 |
| C. dump 增记 reasoning 长度/有无（仍不落全文密钥） | 可观察性 | 让下一张 QA 空回可直接判 ① | 低风险 |
| D. 空输出是否可重试 / 预算 | transport 策略 | 现行 3 次 empty 已响亮；改分类属 #1465 族，本票不改 | — |
| E. 属上游环境（偶发空 200） | 上游 | 本机未复现空 content；并发未测 | 需 ⑤ 授权 |
| F. 缩小 internal system / 拆 payload | 输入/产品 | 体量差是卷面事实，非已证根因 | 大改，非本票 |

**分叉留 owner**：A vs B 优先；A 更贴复放证据且不动「空=失败」宪法。#1459 OPEN，怪癖外置落地前不宜在 `.py` 再堆模型名特判。

---

## 9. 扫描范围 / 未改生产

| 类 | 范围 | 结果 |
|----|------|------|
| QA 卷面 | vault `1797-evidence/**` | 11 dump 分片 + manifest + log |
| 接缝 | `llm_transport.py` / `agents.py` `_after_stream` / `llm_model.extract_agent_text` / `llm_config.provider_extra_body` / extractor+rescript 工厂 | 只读 |
| 复放 | hermes nous proxy · 9 次 chat.completions | 原始 jsonl |
| 测试 | 上记 1 条固定 + 既有 empty-retry 回归 | 绿 |
| 生产 | ming_sim / web / .github / docs/adr / runtime_llm | **零改动** |

---

## 10. 关联

#1793（父）· #1465（transport 预算，② 终包≡非流式已成立）· #1750/#1755（阶段 0 形状先例）· #1459（怪癖外置 OPEN）· #1792
