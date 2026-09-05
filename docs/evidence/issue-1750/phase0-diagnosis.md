# #1750 阶段 0 诊断（取证 + 接缝盘点）

基线：`origin/main` `2aea4b48d` · 分支 `fix/1750-w`  
QA 证据源：`qa/w11-8010-screenshots`（issuecomment 链；本文件只引指针，不誊原文）  
红线遵守：未执行 `ak-role config`；未读写 `~/.ak-roles/public-cli.json` / `institutional-resolution.json`；未改生产重试/超时/并发参数。

---

## 1. 逐包取证（形态表四行）

pack 身份以 manifest 的 `turn` / `period` / `db_path` / `attempt` 为准，不以 QA 目录昵称归因。

### 1.1 8013 · `turn1_attempt1`（1627-10 盖玺结算）

| 键 | 值 |
|----|----|
| 证据指针 | `qa-evidence/w11-8013-box/{manifest,traceback,resolve_context}.json|txt` · `error-1627-10.png` |
| db_path | `/workspace/Ming_LLM/data/ming_sim_1788597390870392903.db` |
| turn / period / attempt | 1 / 10 / 1 |
| timestamp (UTC) | `2026-09-05T08:45:12.838231+00:00` |
| exception_type / message | `LLMUnavailable` / `通传未达，请稍后再召。` |
| ready_payload_digest | `null`（extractor 未产出 delta） |
| traceback 落点 | `decree._settle_after_narrative` → `simulation.extract_scores_by_modules_with_agno:1936 future.result()` → `run_agent_text` → `llm_model.extract_agent_text` → `LLMUnavailable` |
| resolve_context.extracted | `null`；`narrative=""`（崩在抽取段） |
| 上游状态码 | **未取得**（manifest 仅 type/message；无 `status_code` / provider code 字段） |
| transport attempt | 包级 attempt=1；**不证** OpenAI/SDK 层重试次数（无 per-call attempt 账） |

**判定**：结算 extractor 并行腿 transport/run 失败 → `LLMUnavailable(code 默认路径 llm_run_error)` 落 error pack → 玩家「本月结算失败，可重试」。  
**不得**直接归因 429：本包无上游状态码。429 只可作同服环境关联线索（见 1.3/1.4）。

### 1.2 8013 十一月「通传未达」（issuecomment-5550729656 后续）

| 键 | 值 |
|----|----|
| 证据指针 | `qa-evidence/w11-8013-nov/error-1627-11-tongchuan.png` · `rejections.jsonl` · `w11-8013-pending/api-note.txt` |
| 截图相位 | **召对 UI**（黄立极）；气泡文案「通传未达，请稍后再召。」；问话草稿「拟旨如下：解太仓备用」——**非**盖玺结算失败面板 |
| 匹配 error pack | **无**。api-note 明示：同目录 `turn2_attempt1` 的 `db_path=ming_sim_1788597803068938977.db` 属**边政**档，不是朝堂 `5bf5bb186316`；共享 `error_packs/` 跨 box 串包 |
| api-note 运行侧 | `pending_turn_ids=[]`；`chat_turn_id` 与 history 不一致；`reply_retry=null`；phase=summoning 1627-11 |
| rejections.jsonl turn=2 | (a) `power_changes` / `invalid_enum`；(b) `audience_decree` / **`decree_validation`**：「拨饷旨意缺少结构化字段：amount/target_id」——**独立拒收账** |

**判定（分清；失败诚实）**：

1. **已证**：该次不是 1627-10 结算 extractor 包；无匹配朝堂 November settlement error pack；UI 落在召对面而非结算失败面板。  
2. **未证**：一手证据**不能**把异常类型钉成 `LLMUnavailable` 或任一 transport 状态码——截图只证玩家可见文案，api-note 只证 hang/desync 形；根因/异常类型 **未证**。兼容假说含「召对通道失败且文案与 `CLI_RUNNER_PLAYER_MESSAGE` 同形」，但**不冒用**具体异常标签。  
3. `decree_validation` 是**并行独立**待证分支，**无**证据表明它被包装成通传文案；若校验呈现缺口 → **#1730 通道**，不并入本票 transport 自愈。  
4. → **不在本票阶段 1 修理范围**（结算 extractor 自愈/终失败）。

### 1.3 8012 · #1751 · `turn1_attempt2`（1627-10 结算）

| 键 | 值 |
|----|----|
| 证据指针 | `qa-evidence/w11-8012-settle/{manifest,traceback,resolve_context,delta}.*` · `w11-429/8012-429-excerpt.txt` |
| db_path | `/workspace/Ming_LLM/data/ming_sim_1788597803068938977.db` |
| turn / period / attempt | 1 / 10 / **2** |
| timestamp (UTC) | `2026-09-05T08:51:38.419157+00:00` |
| exception | 同 1.1：`LLMUnavailable` / 通传未达；traceback 同 extractor 并行 `future.result` 链 |
| attempt=2 含义 | error_pack `_next_attempt` 由**同 turn 既有目录 max+1** 推导——证「本 turn 第二次写包」，**不证** transport 层第二次自动重试 |
| 同期 429 日志 | `08:50:18` 起 extractor 并发；`token_concurrency_rate_limit_exceeded` 与 `model_concurrency_rate_limit_exceeded`（DeepSeek-V4-Flash concurrency limit **80**） |
| 时间关联 | 429 日志 ~08:50:18–08:50:25；pack 时间 08:51:38——**同窗关联线索成立**，但 pack 自身仍无 status_code，归因口径 =「环境 429 并发压力 × 扇出」候选，非单包铁证 |

**判定**：与 8013 同族——extractor 并行腿 `LLMUnavailable` 终失败；玩家面「重新推演」灰 + 已进十一月属 #1751 恢复/相位义务（本票阶段 0 只取证，不修 8012 UI）。

### 1.4 8010 · #1752 · `turn3_attempt1`（1627-12 批红后结算）

| 键 | 值 |
|----|----|
| 证据指针 | `qa-evidence/w11-8010-dec/{manifest,traceback,delta,8010-log-excerpt}.*` |
| db_path | `/workspace/Ming_LLM/data/ming_sim_1788596745846434942.db` |
| turn / period / attempt | 3 / 12 / 1 |
| timestamp (UTC) | `2026-09-05T09:00:27.757435+00:00` |
| exception | 同族 `LLMUnavailable` / 通传未达；traceback 同 extractor 链 |
| 日志 | `08:58:49`「并发抽取 **6** 腿」；随即 `Rate limit error … 429 … token_concurrency_rate_limit_exceeded`；其后部分腿仍完成（relations/personnel/military/issues 有完成行） |
| 上游状态码落包 | **无**（manifest 仍无 status_code） |

**判定**：同族 extractor 终失败；日志级 429 与 6 腿扇出同秒关联强，但仍不得把无状态码的 pack 直接标成「因 429」。摘录未显示最终失败腿的 ERROR 收束行——完整 server log 不在本证据树。

### 1.5 四行总表

| 行 | pack 身份 | 类别判定 | 上游状态码 | 备注 |
|----|-----------|----------|------------|------|
| 8013 t1a1 | turn=1 period=10 db=…3903 attempt=1 | extractor transport/run → LLMUnavailable | 未取得 | 本票原始形态 |
| 8013 十一月 | **无匹配结算 pack** | 非结算面板；**异常类型未证**（兼容召对失败同文案）；另有独立 decree_validation 账 | n/a | → 不修；validation → #1730 |
| 8012 t1a2 | turn=1 period=10 db=…8977 attempt=2 | 同族 extractor LLMUnavailable | 未取得（日志有 429） | attempt 是写包序号 |
| 8010 t3a1 | turn=3 period=12 db=…4942 attempt=1 | 同族 extractor LLMUnavailable | 未取得（日志有 429） | 6 腿扇出同秒 429 |

---

## 2. 接缝盘点

### 2.1 链路（现行代码）

```
盖玺 / issue/stream
  → session.resolve_turn
  → decree.resolve_directives
  → pre_settle（atomic；turn_phase=settling；ready=0 占位）     … ADR 0008 前半段
  → simulate_season_with_payload                                   … LLM 叙事
  → extract_scores_by_modules_with_agno (parallel=True)            … 本票刀口
       ThreadPoolExecutor(max_workers=leg_count)
       leg_count = len(EXTRACTION_MODULES) + (1 if side_leg else 0)
       EXTRACTION_MODULES = 5（internal / military_external / issues /
                              personnel_secret / relations）
       side_leg = 票拟 companion（ADR 0093 / #656）→ 日志「6 腿」
       每腿：create_score_extractor_module_agent
            → run_agent_text → agent.run → extract_agent_text
  → 任一腿异常：write_error_pack + SettlementAbort(stage=extract)
  → web：stream event:error / 非流式 HTTP 409 detail=abort message
  → state_payload.settlement_recovery{ready_replay,error_pack_path,message}
  → 前端「可重试 / 重新推演｜续跑结算」面板（#1620 typed）
```

### 2.2 错误分类 →「可重试」

| 层 | 现行行为 | 与「可重试」关系 |
|----|----------|------------------|
| `extract_agent_text` | run status ERROR → `LLMUnavailable(CLI_RUNNER_PLAYER_MESSAGE, code=llm_run_error)`；**丢弃**上游 HTTP status（agno 已吞成 Unknown model error 字符串） | 玩家文案可重试口吻；**无** typed 429/timeout 分类进 pack |
| `llm_unavailable_from_error` | 能从 OpenAI 异常提 `status_code` / timeout / connection | **结算 extractor 路径未走此翻译**（失败多在 extract_agent_text） |
| `write_error_pack` manifest | type + message + attempt(写包序号) | **无** status_code / provider_code / transport_attempt |
| `SettlementAbort` | 进度已保存可重试；ready=0 → 重新推演；ready=1 → 续跑 | 面板「可重试」成立；**不是** transport 预算内自愈 |

### 2.3 extractor 是否已在 #1465 预算内

| 项 | 事实 |
|----|------|
| #1465 状态 | OPEN；本票 blocked_by；阶段 1 未放行 |
| OpenAI 适配 `max_retries` | `create_chat_model` 硬编码 **`max_retries=1`**（SDK 层，非 #1465 统一预算真源） |
| extractor 私有重试 | **无**（仅 issues 结局标签局部重试 `event_outcome_retry_limit`，与 transport 无关） |
| 统一默认重试 2、每 attempt 独立超时、idle 为主 | **未落地**；extractor 一腿失败即整月 `SettlementAbort` |
| 结论 | **不在** #1465 统一预算内；现状 = 单次（+ SDK 1）后 fail-closed 到玩家面板 |

### 2.4 ADR 0093 扇出数 vs 端点并发额度（只写事实，不处方）

| 事实 | 值 |
|------|----|
| 结算 phase2 extractor 模块数 | **5**（`EXTRACTION_MODULES`） |
| 加票拟 side_leg 后并发腿 | **6**（8010 日志「并发抽取 6 腿」实证） |
| DeepSeek-V4-Flash 端点并发上限（QA 日志原文） | **80**（`model_concurrency_rate_limit_exceeded`） |
| QA 三车道 | 8010/8012/8013 同服同模型共享该额度 |
| 关系 | 单局 6 腿 ≪ 80；**多局并行 + 召对/其它 API 同窗**时总和可触 80。阶段 0 只记录该乘积关系；限扇出/排队若需要 → 归 #1465 预算/并发设计，**本票不授权** |

### 2.5 0148 / 0008 恢复接缝（与红灯对应）

| 接缝 | 现行 |
|------|------|
| 月初快照 | 点即入 `accept_settlement_period`；`settling`/`awaiting_decision` 下 `exit_settlement_display_on_failure` **不清**快照 |
| D6 未 ready 重推演 | `clear_for_resimulation` 降级 extracted；`resolve_turn` fallthrough 重跑 sim/extract；pre_settle 因 settling 守门不二跑 |
| D3 ready 重放 | `resolve_settling_recovery` 直入 apply；**不**重跑 sim/extract（既有 `tests/test_settlement_recovery_projection_1620.py` 真 HTTP 绿） |

---

## 3. 阶段 0 红灯位置

文件：`tests/test_settlement_extractor_transport_1750.py`  
入口：沿 #1468 `tracer_client` 真 HTTP；LLM transport 边界替身（`run_agent_text` / extractor 腿）。  
标记：`xfail(strict=True, reason="待 #1465")` 用于现行应红项；**不改生产**使灯绿。

| 红灯 | 期望 | 现行预期色 |
|------|------|------------|
| 自愈回路 | 一腿预算内可重试失败 → 月+1、无失败面板 | 红（无统一预算自愈） |
| 终失败回路 | 超预算持续失败 → 保留原月；错误含上游状态/类别/attempt；系统人话 | 保月/人话/pack.attempt 绿；上游 status/code 未进既有 `_llm_error_detail` 玩家面 → xfail（不新造 manifest schema） |
| 恢复 D6 | 未 ready 后重新推演不重跑 pre_settle | 基线可绿（既有 0008 守门） |
| 恢复 D3 | ready 后重放不重跑 LLM | 既有 1620 绿；本文件薄钉 |
| 0148 呈现 | 自愈中与终失败后 api_state 为月初快照 | 终失败 settling 下近绿；自愈中随自愈红 |

---

## 4. 扫描范围 / 命中 / 留存理由（回执用）

| 类 | 扫描范围 | 命中 | 留存理由 |
|----|----------|------|----------|
| QA pack | `qa/w11-8010-screenshots:qa-evidence/w11-{8013-box,8013-nov,8013-pending,8012-settle,8010-dec,429}/**` | 四行身份 + 十一月分清 | 票面逐包取证义务 |
| 生产接缝 | `ming_sim/{simulation,llm_model,error_pack,decree,session,exceptions}.py` · `web_app.state_payload` · `web/src/main.tsx` 恢复钮 | 扇出 5+1、max_retries=1、pack 无 status | 阶段 1 真源边界 |
| 既有 tracer | `tests/test_month_loop_tracer_1468.py` · `test_settlement_recovery_projection_1620.py` · `test_parallel_extractors.py` · `test_enter_settlement_period_1235.py` | 复用入口/恢复/快照 | 不平行造第二套 tracer |
| 法源 | ADR 0008/0148/0149/0093/0005 · #1465 owner 令 | blocked_by 与验收映射 | 阶段 0 不越权改生产 |

**阶段 1 仍 blocked_by #1465**：统一重试/超时/分类/pack 字段落地后，本票红灯转绿；不先于 #1465 实施任何重试或限扇出。
