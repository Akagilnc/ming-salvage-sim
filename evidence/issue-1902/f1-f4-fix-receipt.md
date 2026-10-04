# #1902 修内司 F1–F4 回执

- 分支：`ak-roles/1902-f1-f4-fix`
- 底座 HEAD：`94f5289f1cbbd6fa553124c15485c593f3bc03ae`
- 判词末份：`02-1902-judge-94f5289f1.json` payload F1–F4（`status=continue`）
- 派单：`01a10888-3c5b-7c73-97dd-729e5c78f7fd@fixer/fix-packet.md`
- 官方先行确认：
  - [pytest monkeypatch](https://docs.pytest.org/en/stable/how-to/monkeypatch.html)（变异用现成 MonkeyPatch，不另造注入机制）
  - [Python Errors and Exceptions](https://docs.python.org/3/tutorial/errors.html) / [Logging HOWTO](https://docs.python.org/3/howto/logging.html)（旁路可继续但须留痕，禁 `except: pass`）
  - ADR 0005：宽吞旁路必须 log，不得静默

测试前缀（每条必带）：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

---

## F1 现役抽取失败被降格为正常结果 / 统计旁路静默

### 类定义（未收窄）
1. 现役抽取路径 catch 后把异常/非法产物洗成正常成功结果（空事实、剥声明后继续、洗成「无」意图）。
2. 确证安全的统计旁路可以继续，但不得静默抹去原因（ADR 0005）。

### 枚举命令

```bash
# AST：except 后 return 空 / assign {} / pass，且无 re-raise；再按抽取/统计函数名过滤
python3 <<'PY'
# 见本轮 /tmp 脚本：walk ming_sim+web_app ExceptHandler
# 谓词：washes∈{pass,return '',return {},assign empty} ∧ ¬raise ∧ (fn~extract|draft_intent|affair_declaration|stalled|token_stats)
PY
rg -n 'except Exception:\n        return ""|_affair_declaration_from_draft_obj|except \(TypeError, ValueError\)' ming_sim/cli_backend.py
rg -n 'except Exception:\n                pass' ming_sim/token_stats.py
rg -n 'pay_order_override.*entries|draft_action.: .无.' ming_sim/cli_backend.py
```

### 候选成员表

| 成员 | 分类 | 处置 | 理由 |
|---|---|---|---|
| `cli_backend._stalled_deliberation_push_facts` 外层 `except Exception: return ""` | **F1** | 删除 catch，库查询失败上抛 | 点名样本；DB 失败洗成空事实后抽取仍正常返回 |
| `extract_draft_intent` 四处 `_affair_declaration_from_draft_obj` catch→`{}`/`无` | **F1** | 去掉 catch，保留原始 ValueError | 点名样本；非法声明被剥掉后仍成功 |
| `extract_draft_intent` 单/多道缺 `pay_order_override.entries`→`无`/invalid_batch | **F1** | `raise ValueError("…entries")` | 同类非法产物洗成无；既有 `test_single_pay_order_capture_rejects_missing_entries` 红证 |
| `token_stats.patched_create/acreate` `except: pass` | **F1** | `tlog(...)` 后继续 | 点名样本；旁路可继续但须留痕 |
| `token_stats._get_client_base_url` / `install` import miss | 保留 | 不改 | 安装/探测软路径，非抽取产物洗正常 |
| `breach_plea` 逐项 `(TypeError,ValueError): pass` | 保留 | 不改 | 逐项脏字段隔离，非整次抽取洗成功 |
| `_run_startup_extraction_catch_up` `TicketCancelled: return` | 保留 | 不改 | 取消语义，非失败洗正常 |
| 首抽 LLM 挂死 `_log` 后映「无」 | 保留 | 不改 | 已有 `_log` 留痕；纠错路仍上抛；非本轮判词非法产物样本 |

### 根因修复
- 库查询与非法声明/缺 entries：失败走既有响亮收口（raise），不再降格。
- 统计旁路：继续返回响应，但 `tlog` 留下异常类型与消息。

### 变异证据（进程内 MonkeyPatch，未落仓）
| 模式 | 结果 |
|---|---|
| 恢复 stalled 空事实洗 | `draft_action=拟旨`，`returned_normally=True` |
| 当前 stalled 上抛 | `RuntimeError('mutated_db_list_failed')` |
| 直接 `declaration_from_payload(close)` | `ValueError('本阶段不能了结事务')` |
| 当前抽取含非法声明 | 同文 ValueError |
| 恢复声明洗 | `draft_action=拟旨` 且声明被剥掉 |

---

## F2 菜单仍维护第二套有效运行配置

### 类定义（未收窄）
有效 channel/runner/model/timeout/reasoning 等只许共核 `llm_config_from_runtime` 一份；入口可保留原样存盘值供表单，不得平行再算「生效值」。

### 枚举命令

```bash
rg -n 'normalize_reasoning_strength|cli_model_from_env|llm_config_from_runtime|channel = str\(runtime' \
  ming_sim/llm_config.py ming_sim/cli_backend.py ming_sim/cli/terminal.py web_app.py web/src
```

### 候选成员表

| 成员 | 分类 | 处置 | 理由 |
|---|---|---|---|
| `web_app.api_menu_status` 内平行算 channel/runner/model/strength | **F2** | 改吃 `llm_config_from_runtime` | 点名样本；空档+thinking low+advanced high 时共核 high、旧菜单空→UI 回落 low |
| `cli_reasoning_strength` / `api_reasoning_strength` 读槽原样 | 保留 | 保留 | 判词允许：原样保存值供表单 |
| `api_get_llm_config` 读活会话 `cfg` + `persisted` 原样 | 保留 | 不改 | 生效值来自会话共核投影，非第二套规则 |
| POST 保存路径 `normalize_reasoning_strength(request…)` | 保留 | 不改 | 入参归一，非从 runtime 再算生效配置 |
| `llm_config_from_runtime` 本体 | 真源 | 不改 | 唯一有效配置权威 |

### 根因修复
`api_menu_status` 有效字段一律取自 `llm_config_from_runtime`；仅 `cli_model_saved` / 分槽 strength 保留盘面原样。

### 变异／对照
空运行档 + `thinking_level=low` + `advanced_model` + `advanced_thinking_level=high`：
- 菜单 `reasoning_strength=high`（与共核对齐）
- 旧平行算法会得到 `""`（`fixes_judge_gap=True`）

---

## F3 测试清退：失效 mock / 重复内部证明 / 散文机械 / 来源弱化 / 死夹具

### 类定义（未收窄）
失效 mock 缝、与真实入口重复的内部 helper 证明、呈现散文机械约束、来源断言弱化、专用死夹具。保留来源契约与闸类负向案。不整删整补、不另造平行测试。

### 枚举命令

```bash
PRED='(^|/)(tests?/|__tests__/|conftest\.py$|test_[^/]+\.py$|[^/]+_test\.py$|[^/]+\.(test|spec)\.(ts|tsx)$)'
git ls-files | rg -i "$PRED" | wc -l   # → 267
# setattr _run_backend（非 for_config）/ 无 fixture 的纯 helper 案 /
# assert "…" in reason|text|roster / 「A in x or x」弱来源 / 锁内部 frozenset
```

### 候选成员表

| 成员 | 分类 | 处置 | 理由 |
|---|---|---|---|
| `test_enrich_trace_records_actual_backend` setattr `_run_backend` + 传 cli `LLMConfig` | **F3 失效 mock** | 删除 | 真缝是 `_run_backend_for_config`→runner；七 BIN 下宿主失败测试仍绿；同文件已有 `_patch_runner` trace 案 |
| `test_fork_predicate_pure…` / `test_veracity_derivation…` | **F3 重复内部** | 删除 | helper 案在真实 fork 读端恒假时仍绿；`test_ac3_veracity_true_and_false_from_fork` 真链报红 |
| `test_kill_lands…` `assert "斩杀" in reason or reason` + 名册散文 | **F3 来源弱化+散文** | 改为精确 reason；用 DB `status!='active'` | 落库理由改 CORRUPTED 旧断言仍绿 |
| `test_cli_entry_1902` 内 `validate_all` 与落库并陈 | P3 | **保留** | 判词：独立入口参数契约，不据此删除 |
| `test_cli_reasoning_strength_runners_authoritative_set` | P3 | **保留** | 判词：闸类/能力集合负向案不可删 |
| `test_office_inference` setattr `_run_backend` + channel=api | 保留 | 不改 | 负向探测「API 通道不得误调 CLI」；真缝正确 |
| 其它无 llm_config 的 enrich setattr `_run_backend` | 保留 | 不改 | 无配置回落真走 `_run_backend` |

### 根因修复
优先删除失效/重复证明；来源案改回结构化精确断言，去散文依赖。

---

## F4 薄入口无语义纯转发包装

### 类定义（未收窄）
入口层无语义、仅同签名转发的包装。

### 枚举命令

```bash
# AST：函数体（去 docstring）仅一条 Return/Call，且实参集合 ⊆ 形参
# 范围：ming_sim/cli/terminal.py + web_app.py（入口面）
```

### 候选成员表

| 成员 | 分类 | 处置 | 理由 |
|---|---|---|---|
| `terminal.play_turn` 内 `_review`→`review_directives` | **F4** | 删除包装，三处直调 | 点名样本；测例已 patch 模块级 `review_directives` |
| `WebGame.write_queue` / `rebuild` / `find_character` 等 | 保留 | 不改 | 资源适配/会话方法，非「入口残留无语义包装」 |
| `_character_power_id` | 保留 | 不改 | 领域解析 helper，非入口薄包装 |

### 根因修复
删 `_review`；`play_turn` 直接调用 `review_directives`。

---

## 聚焦测试

```text
294 passed in 5.56s
（含 cli_backend / cli_entry / cli_play_turn / web_entry / web_llm_runtime_config /
  cli_model_choices / faction_denunciation / on_scene_immediate_write /
  draft_admission_resubmit / llm_channel_config / runtime_llm_config /
  pay_order_override_extraction）
```

另跑抽取触及面：`test_pihong_dossier_1490` + `test_pay_order…` + `test_decree_dossiers_571` + `test_structured_decree_contract_1624` + `test_affairs_1831` → 修 entries 后全绿（此前 1 failed 即 F1 同类）。

未跑全量。

---

## 复扫摘要

| 类 | 复扫结论 |
|---|---|
| F1 | 点名与同类洗法已清；剩余为逐项脏隔离 / 安装软路径 / TicketCancelled（保留理由见表） |
| F2 | 菜单生效值走共核；分槽原样 strength 保留 |
| F3 | 点名失效/重复/弱来源已清；闸类与入口参数案保留 |
| F4 | `_review` 已删；入口面其余单行方法属适配语义，保留 |

## 剩余工作
- 不在本轮：breach_plea 逐项 pass、家族收尾功能接续（#1873）、全量 suite。
- 无 owner 决策缺口；本轮未改治理文件 / 宿主配置 / 永久扫描脚本。
