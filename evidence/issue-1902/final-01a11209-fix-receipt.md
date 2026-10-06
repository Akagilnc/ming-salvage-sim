# #1902 修内司对照终判 01a11209 交卷

- FIX SHA：`aa58a82c29aadef0a26d235adc25d16304f8e17c`
- 终判真源：`~/.ak-roles/books/Ming_LLM/1902/runs/01a11209-c090-7524-9191-3436b624c3af@judge/current.json` submission.latest.accepted
- 未结类：**仅 T1、T2、T4、T6**（T3 不送修；T5 处方撤销）
- 工作树相对家族曾用 01a107df 误派，本回执按终判复核全量修改
- **不宣称合并/关票**；未 amend/stash/push

七 BIN 前缀全程。

---

## 终判四类

### T1 强杀（测试执行路径）
- 谓词：subprocess.*(timeout=) / kill / SIGKILL / terminate(force=True)
- 处置：`tests/test_pihong_dossier_1490.py` 去 timeout（commit 27e877bcb）
- 复扫：授权内 actionable **0**
- 例外：SIGTERM 自终；terminate 缺口 wait 报告；替身 kill 定义

### T2 自由文本控制／交付
- 谓词：异常词面正则控恢复、交付 strip、共享 prose 故障分类
- 处置：
  - `UnknownParticipantRefError` 结构化名册故障；heal 只认 isinstance（draft_intent）
  - CLI 交付保留 primary/final_text 原文，strip 仅空判定
  - 删除 `fail_if_llm_error` 词表（属同类「正文控故障」）
- 复扫：无 PARTICIPANT 正则；无 fail_if 生产调用；交付不 strip 改写

### T4 共享职责归属
- 谓词：领域编排在传输层；启动恢复生命周期在入口副本
- 处置：
  - 领域 extract/heal/resubmit/enrich/DRAFT_ACTION → `ming_sim/draft_intent.py`；cli_backend 不保留
  - `GameSession.reconcile_crashed_audience_turns`
  - **本轮补**：`list_startup_translation_catch_up` + `run_startup_translation_catch_up` 共核；Web 仅票据/线程适配；CLI 对账后同步调共核补跑
- 复扫：cli_backend 无领域 def；启动补跑真源在 session

### T6 无产者旧结果契约
- 谓词：ChatTurnResult 无产者字段 + 死消费者 + 被替代独占入口
- 处置：
  - ChatTurnResult 仅 answer/court_action/pending_audience_translation
  - 清 Web `_chat_payload` / CLI 死投影；测试改现役缝
  - 删 `run_agent_stream_text` 孤岛及专属测（被 scene/run_agent_text transport 替代）
- 复扫：三字段；无 stream 入口引用

---

## 终判未覆盖／已撤销类上的改动（如实列）

终判明文：**T3 不送修；T5 处方撤销**。下列改动发生在误跟 01a107df／后续 inspector 材料期间，**不属终判未结类**，保留现状并说明依据：

| commit | 改动 | 依据／为何不回滚 |
|---|---|---|
| 767fb8312 等 | `legacies_payload` JSONDecodeError + warning 留痕；Row id 读取 | 终判 T3「本轮无新增未结」；属失败诚实加固，非终判未结类，未扩大 catch 框架 |
| e75c51282 | `test_translate_empty_success` 改走 `_scene_turn` 真路径 | 终判 **T5 处方撤销**；此改是修空跑测，保留急务两案与公开契约，不恢复「重复证明删除」处方 |
| e75c51282 | 删 run_agent_stream_text | 可归 **T6**（被替代旧入口/独占证明），与终判 T6 边界相容，非 T5 |

未按已撤销 T5 处方删除急务两案或 salary/highlight 负向闸。

---

## 聚焦测试

```
239 passed in 10.23s
```
（cli_backend/transport/entry/play_turn/web_entry/restore/draft_admission/structured_decree/translate/issue_entities/chat_stream）

## 质量
未改治理文件/席位；无新监督层/兼容转发/证明测；未 stash/push/PR。
