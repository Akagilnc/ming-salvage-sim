# #1902 修内司 F1–F4 回执（纠举补扫轮）

- 分支：`ak-roles/1902-f1-f4-fix`
- 上一提交：`0e7d35d5cd2a72ddde58834029c40e6a9c60a81f`（点名修理）
- 本轮底座起点：`94f5289f1` 判词 F1–F4（`status=continue`）
- 判词末份：`02-1902-judge-94f5289f1.json` payload F1–F4
- 自验纠正：末判 F3 明确裁 `test_cli_entry_1902` 落库案内重复正向 `validate_all` 与 `test_llm_channel_config` 内部能力集合锁为 **P3 成立须删**；保留独立参数契约 / 闸负向案 ≠ 保留这两处正向重复。上轮回执误标「保留」已纠正。
- 官方先行：
  - [pytest monkeypatch](https://docs.pytest.org/en/stable/how-to/monkeypatch.html)
  - [Python Errors and Exceptions](https://docs.python.org/3/tutorial/errors.html)
  - ADR 0005：宽吞旁路必须 log，不得静默

测试前缀（每条必带）：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

全仓分类表（不得用路径计数冒充分类）：

- `evidence/issue-1902/f1-f4-classification-table.md`
- `evidence/issue-1902/f1-f4-classification-table.json`
- 本轮临时枚举脚本（完整可执行，非永久 CI 扫描器）：`evidence/issue-1902/tmp-scans-1902-round/scan_*.py`

---

## 枚举命令（完整可执行）

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
SCRIPTS=$ROOT/evidence/issue-1902/tmp-scans-1902-round
mkdir -p /tmp/ming1902-f1f4-rescand

# F1：全仓 ExceptHandler + wash 候选（ming_sim + web_app；不按函数名预过滤）
python3 $SCRIPTS/scan_f1_except.py $ROOT
# F1 补：except 未 return 后继续 + draft_action「无」返回点
python3 $SCRIPTS/scan_f1_post_except.py $ROOT

# F2：全仓配置投影命中
python3 $SCRIPTS/scan_f2_config.py $ROOT

# F3：git ls-files 测试路径全集 + 嫌疑旗 / setattr / 能力集合锁 / 散文子串
python3 $SCRIPTS/scan_f3_tests.py $ROOT

# F4：全仓 AST 纯转发候选（单语句 Return/Call 且实参 ⊆ 形参）
python3 $SCRIPTS/scan_f4_forward.py $ROOT
```

实测摘要（本轮）：

| 扫描 | 结果 |
|---|---|
| F1 except_total / wash_candidates | 840 / 373（再按类定义逐条分类；见 JSON） |
| F1 post_except_continue / focus | 494 / 145 |
| F2 config hits | 590 |
| F3 test_paths | 267（逐案分类见表；≠分类完成的替代） |
| F4 pure-forward AST | 49（删别名后；按语义保留/已删） |

---

## F1 现役抽取失败被降格为正常结果 / 统计旁路静默

### 类定义
1. 现役抽取路径 catch 后把异常/非法产物洗成正常成功结果。
2. 确证安全的统计旁路可继续，但不得静默抹去原因。
3. **日志不是继续契约本身**——有 `_log`/`tlog` 不能单独当作「排除出 F1」的理由；须对照既有公开行为契约或类定义外语义。

### 候选成员表（要点；全量表见 classification JSON）

| 成员 | 分类 | 处置 | 理由 |
|---|---|---|---|
| `_stalled_deliberation_push_facts` 外层 catch→`""` | **F1** | 已删（0e7d35d） | 点名；DB 失败洗空事实 |
| `extract_draft_intent` 声明 catch→剥掉成功 | **F1** | 已删 catch，保留 ValueError | 点名 |
| 缺 `pay_order_override.entries`→「无」 | **F1** | 已 `raise ValueError` | 非法产物洗无 |
| `token_stats` `except: pass` | **F1** | 已 `tlog` 后继续 | 点名 P3 |
| 首抽/多旨 LLM except→`_log`→映「无」 | 保留 | 不改 | **既有公开 degrade 契约**（`test_extract_draft_intent_backend_exception_degrades_to_none`）；纠错路上抛。保留依据=行为契约，**不是**「有日志」 |
| `enrich_initiative_effects` except→空效果 | 保留 | 不改 | 文档化非阻断补全（`test_enrich_backend_error_returns_empty_effects`） |
| `breach_plea` 逐项 pass | 保留 | 不改 | 逐项脏隔离 |
| `_run_startup_extraction_catch_up` TicketCancelled | 保留 | 不改 | 取消语义 |
| 其余 373 wash / 145 post-focus | 保留 | 不改 | 解析归一 / 资源收尾 / rejected 记账 / 控制流哨兵等——见 JSON 逐条 `reason` |

### 变异

```text
CURRENT_STALLED: raised RuntimeError: mutated_db_list_failed
RESTORED_WASH_STALLED: returned_normally=True value=''
CURRENT_ILLEGAL_DECL: raised ValueError: 本阶段不能了结事务
```

---

## F2 菜单仍维护第二套有效运行配置

### 类定义
有效 channel/runner/model/timeout/reasoning 只许共核 `llm_config_from_runtime`；入口可留原样存盘值供表单。

### 候选成员表

| 成员 | 分类 | 处置 | 理由 |
|---|---|---|---|
| `api_menu_status` 平行算生效值 | **F2** | 已改吃共核（0e7d35d） | 点名 |
| 分槽 `cli_/api_reasoning_strength` 原样 | 保留 | 保留 | 表单存盘值 |
| POST `normalize_reasoning_strength(request)` | 保留 | 不改 | 入参归一 |
| `cli_model_from_env` | 保留 | 不改 | 共核内部默认解析 |
| web/src 读 API 字段 | 保留 | 不改 | UI 消费共核投影 |
| 其余 590 hits | 保留 | 不改 | 字段名命中≠第二套生效规则；见 JSON |

### 变异（空档 + thinking low + advanced high）

```text
CORE channel='api' strength='high'
MENU_STRENGTH='high' aligned_with_core=True
OLD_PARALLEL_EFFECTIVE=''
fixes_judge_gap=True
```

---

## F3 测试清退

### 类定义
失效 mock 缝、与真实入口重复的内部 helper 证明、呈现散文机械、来源弱化、专用死夹具。保留来源契约与闸类负向案。不整删整补、不另造平行测试。

### 本轮纠正 / 同类清退

| 成员 | 分类 | 处置 | 理由 |
|---|---|---|---|
| `test_cli_blank_pick_on_urgent…` 内 `validate_all` 正向 | **F3 P3** | **删除** | 末判成立；落库案只留 decided+hold |
| `test_cli_blank_pick_on_ordinary…` `validate_all` 拒收 | 保留 | 保留 | 独立入口参数负向契约 |
| `test_cli_reasoning_strength_runners_authoritative_set` | **F3 P3** | **删除** | 末判成立；锁内部 frozenset |
| `test_cli_supports_reasoning_strength_matrix` | 保留 | 保留 | 闸类谓词行为案 |
| `test_1271_…` 三端 `set==CLI_REASONING_STRENGTH_RUNNERS` | **F3** | **删除集合等式** | 同类内部能力集合锁；保留 `grok in` + `reasoning_supported` |
| 死夹具 `_patch_backend` | **F3** | **删除** | 无调用 |
| secret/enrich setattr `_run_backend` | **F3** | **改钉真缝** `_run_json_extractor_for_config` / `_run_backend_for_config` | 避免错缝假绿 |
| `test_office_inference` API 负向 setattr `_run_backend` | 保留 | 不改 | 负向探测真缝 |
| 其余 261 路径 | 保留 | 不改 | 逐案理由见 classification 表 |

### 变异（精确 reason 契约）

```bash
PYTHONPATH=/tmp/ming1902-f1f4-rescand/mut_plugin:$PYTHONPATH \
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
python3 -m pytest -q -p no:cacheprovider -p corrupt_reason \
  --basetemp=/tmp/ming1902-f1f4-rescand/mut-f3 \
  tests/test_on_scene_immediate_write_1839.py::test_kill_lands_status_and_next_materials_show_it
# → 1 failed；assert reason == … 得到 CORRUPTED

# 恢复：
…同七 BIN 前缀… python3 -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/ming1902-f1f4-rescand/mut-f3-restore2 \
  tests/test_on_scene_immediate_write_1839.py::test_kill_lands_status_and_next_materials_show_it \
  tests/test_cli_entry_1902.py::test_cli_blank_pick_on_urgent_reaches_core_hold \
  tests/test_llm_channel_config.py::test_cli_supports_reasoning_strength_matrix \
  tests/test_web_llm_runtime_config.py::test_1271_three_endpoints_grok_reasoning_supported_and_capability_list
# → 13 passed in 0.91s
```

---

## F4 薄入口无语义纯转发

### 类定义
入口层无语义、仅同签名转发的包装。全仓 AST 候选后按语义判断。

### 候选成员表（要点）

| 成员 | 分类 | 处置 | 理由 |
|---|---|---|---|
| `terminal._review`→`review_directives` | **F4** | 已删（0e7d35d） | 点名 |
| `ensure_open_night_for_audience`→`open_night` | **F4** | **删除并内联** callers→`open_night` | 同签名无语义别名 |
| `qualitative_character_attribute`→`qualitative_character_axis` | **F4** | **删除** | 零调用死别名 |
| `WebGame.write_queue/rebuild/find_character` 等 | 保留 | 不改 | 资源/会话适配 |
| `api_state` | 保留 | 不改 | HTTP 路由面本身 |
| 其余 AST 单行候选 | 保留 | 不改 | DB/解析/协议方法有领域语义；见 JSON |

### 探针

```text
qualitative_character_attribute_removed=True
ensure_alias_removed / in_module_dict False
open_night_is_real True
```

---

## 聚焦测试（实测）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/ming1902-f1f4-rescand/focus1 \
  tests/test_cli_entry_1902.py tests/test_cli_play_turn.py tests/test_web_entry_1902.py \
  tests/test_runtime_llm_config.py tests/test_web_llm_runtime_config.py \
  tests/test_cli_backend.py tests/test_faction_denunciation_627.py \
  tests/test_on_scene_immediate_write_1839.py tests/test_draft_admission_resubmit_1769.py \
  tests/test_llm_channel_config.py tests/test_cli_model_choices.py \
  tests/test_pay_order_override_extraction_653.py
```

```text
293 passed in 5.68s
```

召对开夜触及面（F4 内联后）：

```bash
…同七 BIN 前缀…
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/ming1902-f1f4-rescand/focus-audience \
  tests/test_audience_night_498.py tests/test_web_audience_night_498.py \
  tests/test_audience_travel_gating_670.py
```

```text
64 passed in 5.41s
```

未跑全量。

---

## 复扫摘要

| 类 | 结论 |
|---|---|
| F1 | 全仓 except+post-continue+非法产物返回点已枚举分类；点名洗法已清；首抽映「无」按公开 degrade 契约保留（非因日志） |
| F2 | 菜单生效值走共核；全仓投影命中已分类 |
| F3 | 末判两处 P3 正向重复已删；同类内部集合锁与错缝/死夹具已清；267 路径逐案表已存 |
| F4 | 全仓 AST 候选已分类；无语义别名已删 |

## 剩余工作
- 不在本轮：breach_plea 逐项 pass、家族收尾 #1873、全量 suite。
- 无 owner 决策缺口；未改治理文件 / 宿主配置 / 永久扫描机制；临时脚本仅证据目录 + `/tmp`。
