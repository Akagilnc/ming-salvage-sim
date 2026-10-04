# #1902 F1–F4 分类表（精简·成员粒度）

- 底座判词：`02-1902-judge-94f5289f1.json` payload F1–F4（`status=continue`）
- 本表只保留**必要候选**与可核保留依据；无嫌疑压缩面见各节「压缩保留」
- **禁止口径**：「非本轮 F3 点名…」已废；flags 未命中 ≠ 自动合法
- 枚举命令只写回执 markdown，**扫描器不入库**（本轮仅 `/tmp/ming1902-f1f4-round2/`）

## 摘要（如实，非结清替代）

| 类 | 本轮处置 | 压缩保留面 |
|---|---|---|
| F1 | 继续清：投影伪造 kind、关联确认洗空、密令供给非 dict 洗 `{}`、token 装补丁静默、补 `DOSSIER_LINK_TYPES` 导入 | 公开 degrade 契约（首抽映「无」、enrich 空效果）、逐项脏隔离、取消语义 |
| F2 | 菜单生效值已走共核（上轮）；本轮复核无第二套生效规则 | 表单存盘槽、POST 入参归一、共核内部默认 |
| F3 | 删内部能力集合锁 / 死夹具 / 重复 key 集合；跨文件共享 stream helper 保留 | P4 隔离负向、来源透传、闸类负向、approx 呈现契约 |
| F4 | 删 `_transaction_categories` 别名、死方法 `read_credit_events_as_edges` | 会话/写闸 façade、供料具名读缝、HTTP 路由面 |

---

## F1 现役抽取失败 / 非法产物洗成正常结果

### 类定义（全文）
1. catch 后把异常/非法产物洗成正常成功  
2. **不经 except** 的非法产物 return 降级  
3. 错误来源造假（如伪造 kind/reason）  
4. 失败继续契约须逐项对照既有公开行为；统计旁路可继续但不得静默  

### 必要候选（成员）

| 成员 | 分类 | 处置 | 可核依据 |
|---|---|---|---|
| `_stalled_deliberation_push_facts` 外层 catch→`""` | F1 | 上轮已删外层洗空 | 现仅逐行脏 skip |
| `extract_draft_intent` 非法事务声明剥掉成功 | F1 | 上轮已 `raise` | 纠错路上抛 |
| 缺 `pay_order_override.entries`→「无」 | F1 | 上轮已 `raise ValueError` | 非法产物不洗「无」 |
| `token_stats` `except: pass` | F1 | 上轮已 `tlog`；本轮装补丁 import 失败亦 `tlog` | ADR 0005 |
| `project_draft_extract…` `ValueError→pre_kind="ordinary"` | F1 | **本轮删伪造**，分类失败上抛 | 探针：变异 classify 现 raise；旧洗返回 special_decree |
| `confirm_dossier_links` except→`[]` | F1 | **本轮 re-raise**；非法非对象/`confirmed_links` 非列表 raise | 探针：boom→`RuntimeError` |
| `_extract_secret_order` 确认 future except→剥光关联当成功 | F1 | **本轮改 `extract_failed`** | 既有 land_or_recover 收口 |
| `month_chain` 非 dict supply→`{}` | F1 | **本轮 abort + invalid** | 既有 `_abort_month_call` |
| `DOSSIER_LINK_TYPES` 未导入导致确认路径 NameError | F1 邻接 | **本轮补 import** | 常量本就引用；否则确认缝假崩 |
| 首抽/多旨 LLM except→映「无」 | 保留 | 不改 | `test_extract_draft_intent_backend_exception_degrades_to_none`（公开 degrade） |
| `enrich_initiative_effects` except→空效果 | 保留 | 不改 | `test_enrich_backend_error_returns_empty_effects` |
| `breach_plea` 逐项 pass | 保留 | 不改 | 逐项脏隔离（非整批成功洗） |
| `_run_startup_extraction_catch_up` TicketCancelled | 保留 | 不改 | 取消语义 |

### 压缩保留
解析归一 / 资源收尾 / rejected 记账 / 控制流哨兵：未再逐条扩写。本轮未把「有 `_log`」单独当排除理由。

---

## F2 有效运行配置只许共核

### 类定义
有效 channel/runner/model/timeout/reasoning 只许 `llm_config_from_runtime`；入口可留原样存盘值供表单。

| 成员 | 分类 | 处置 | 可核依据 |
|---|---|---|---|
| `api_menu_status` 平行算生效值 | F2 | 上轮已改吃共核 | `MENU_USES_CORE=True`；`cfg.reasoning_strength` |
| 分槽 `cli_/api_reasoning_strength` 原样 | 保留 | 保留 | 表单存盘值，非第二生效规则 |
| POST `normalize_reasoning_strength(request)` | 保留 | 不改 | 入参归一 |
| `cli_model_from_env` / 共核内部默认 | 保留 | 不改 | 共核内部 |
| web/src 读 API 字段 | 保留 | 不改 | UI 消费共核投影 |

### 压缩保留
字段名命中 ≠ 第二套生效规则；本轮源码复读未见菜单外平行 effective 计算器。

---

## F3 测试清退（全定义）

### 类定义
失效 mock、重复内部/失效证明、**任何**散文机械约束、来源弱化、专用死夹具。保留来源契约与闸类负向。不整删整补、不另造平行测试。  
**flags 未命中不得自动合法。**

### 本轮处置成员

| 成员 | 分类 | 处置 | 可核依据 |
|---|---|---|---|
| `test_cli_entry_1902` 落库案正向 `validate_all` | F3 | 上轮已删 | 保留 ordinary 拒收负向 |
| `test_cli_reasoning_strength_runners_authoritative_set` | F3 | 上轮已删 | 保留 matrix 闸谓词 |
| `test_web_llm… set==CLI_REASONING_STRENGTH_RUNNERS` | F3 | 上轮已删 | 保留 grok∈ + supported |
| `test_cli_backend` `_patch_backend` 死夹具 / 错缝 | F3 | 上轮已改钉真缝 | — |
| `test_faction_denunciation` helper 重复案 | F3 | 上轮已删 | 真 fork 案保留 |
| `test_on_scene…` 放松 reason | F3 | 上轮已精确 `==` | 变异 CORRUPTED→红 |
| `test_public_cli_support…` frozenset/字面序锁 | F3 | **本轮改行为闸** | 不锁内部集合 |
| `test_cli_model_choices` 字面七名/序锁 | F3 | **本轮改结构+现役∈** | 同上 |
| `web/src/cliRunners.test.ts` 完整名单钉 | F3 | **本轮改唯一性/结构** | vitest 3 passed |
| `test_world_materials…` denunciation key 集合 | F3 | **本轮删冗余 set** | 保留 `== build_…` |
| `test_cli_play_turn._cli_schedule_pending_noop` | F3 | **本轮删死夹具** | 零引用 |
| `test_month_loop_tracer` 无调用月链/COURT_BREAK 夹具 | F3 | **本轮删死夹具** | 保留跨文件共享 `_post_issue_stream` 等 |

### 压缩保留（去非法缩窄后重判）

| 面 | 保留理由（可核） |
|---|---|
| `assert "欠饷约N万两" in army_detail` / payload | #305/#321 **approx 呈现契约**（结构化 arrears_text），非 LLM 自由文盯文 |
| `province_pay_arrears` 等列名不得进出口 | **P4/隔离负向**：内部列名泄漏哨兵；非「未点名故保留」 |
| `in` 命中结构化 reason/stage/error_pack | 来源透传或闸负向 |
| setattr `_run_backend` / `for_config` | 负向或真缝注入；非错缝假绿 |
| 无嫌疑旗的行为/类型/夹具模块 | 未发现失效 mock／重复内部／死证明；**不是**「无旗=合法」的自动放行，而是本轮语义复读未见成员 |

### 未扩删说明（诚实）
`ministerScrollLens` / `audience_scroll` 等仍有对话全文 `.toEqual`；本轮未整片改写（风险大、且部分承接账本往返）。**不声称 F3 散文面全仓已零**；若下轮以「呈现散文机械」单独立法，应优先这些文件。

---

## F4 无语义纯转发

### 类定义
入口层无语义、仅同签名转发的包装。须逐项语义，不得套「资源适配」糊弄。

| 成员 | 分类 | 处置 | 可核依据 |
|---|---|---|---|
| `terminal._review`→`review_directives` | F4 | 上轮已删 | — |
| `ensure_open_night_for_audience` | F4 | 上轮已内联 `open_night` | `hasattr=False` |
| `qualitative_character_attribute` | F4 | 上轮已删 | `hasattr=False` |
| `structured_decree._transaction_categories` | F4 | **本轮内联** `duty_route_categories` | 别名已除 |
| `GameDB.read_credit_events_as_edges` | F4 | **本轮删**（零调用死转发） | `hasattr=False` |
| `GameSession._character` | 保留 | 不改 | `web_app` 召对读人物 façade（非零调用空壳） |
| `WebGame.find_character` / write_queue adapter | 保留 | 不改 | 会话/写闸协议对象；含 coerce 者非纯转发 |
| `investigation_tip_records`→`_tip_records` | 保留 | 不改 | 4a 供料具名读缝（month_chain 消费） |
| `api_state` / HTTP 路由 | 保留 | 不改 | 路由面本身 |

### 压缩保留
AST 单行 Return(Call) 中：DB 查询封装、协议方法、带 docstring 的领域具名缝——保留并写清语义；本轮不把「资源适配」当万能理由。
