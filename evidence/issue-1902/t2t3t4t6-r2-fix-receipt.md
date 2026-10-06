# #1902 修内司 T2/T3/T4/T6 续修回执（复裁后）

- 基线 stamp：`3b4f16402`
- FIX SHA：`767fb831261026a0273953fea228c8389d338269`
- 判词续：inspector 复裁 continue（T2 上层词面；T3 legacies 无痕；T4 DRAFT 仍在传输；T6 测试旧依赖）
- **不宣称合并/关票**

## 修复

### T2
删除 `fail_if_llm_error` 及全部调用/导入（llm_model、agents、session、web_app）。
认证故障只留 typed status / transport。探针：COMPLETED 正文含 Authentication required → 原样交付。

### T3
`WebGame.legacies_payload`：`except Exception` → `json.JSONDecodeError` + 非 dict 归 `{}`；未知代码异常上抛。

### T4
`DRAFT_ACTION_TYPES` 迁 `draft_intent`；cli_backend 删除 DIRECTIVE/structured_decree 领域导入与常量；领域校验直读本模块常量。

### T6
- `test_audience_translate_1837` 去 `r.pending_action_id` / `pending_action_failures` 死字段断言，改落库后行为。
- enrich monkeypatch 目标改 `draft_intent`。
- 场景替身 SimpleNamespace 清死字段，保留 answer/court_action。

## 测试
361 passed in 11.34s（七 BIN 前缀）
