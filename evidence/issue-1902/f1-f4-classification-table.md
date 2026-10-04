# #1902 F1–F4 分类表（精简·成员粒度·round3）

- 底座判词：`02-1902-judge-94f5289f1.json` payload F1–F4（`status=continue`）
- 本表只保留**必要候选**与可核保留依据；启发式计数 ≠ 结清
- **禁止口径**：「非本轮 F3 点名…」已废；flags 未命中 ≠ 自动合法
- 枚举命令只写回执 markdown，**扫描器不入库**（本轮仅 `/tmp/ming1902-f1f4-round3/`）

## 摘要（如实）

| 类 | 本轮处置 | 压缩保留面 |
|---|---|---|
| F1 | 逐项审验抽取缝：确认条目非法 raise；多旨非法批次 raise；token base_url / enrich 规范化补 log；补 `ThreadPoolExecutor` 导入 | 首抽 LLM 失败→「无」（owner 注释可核）；enrich 空效果公开测；breach 逐项；TicketCancelled |
| F2 | 复读：`api_menu_status` 只吃 `llm_config_from_runtime` | 表单分槽原样、POST 入参归一、共核内部默认 |
| F3 | scroll/lens 对话全文 pin→结构契约；28 确认死夹具删；pi `-p\|\|--print` 来源弱化收紧 | 来源透传（live==closed / join==story / restore）、闸负向、P4 隔离、approx 呈现 |
| F4 | 再删 3：死别名 `_primary_source_only…`、死查询 `list_recent_issue_advances`、死转发 `validate_delta_shape` | 会话/写闸 façade、供料具名读缝、HTTP 路由、带 coerce 的封装 |

---

## F1 现役抽取失败 / 非法产物洗成正常结果

### 类定义（全文）
1. catch 后把异常/非法产物洗成正常成功  
2. **不经 except** 的非法产物 return 降级  
3. 错误来源造假（如伪造 kind/reason）  
4. 失败继续契约须逐项对照既有公开行为；统计旁路可继续但不得静默  

### 本轮处置成员

| 成员 | 分类 | 处置 | 可核依据 |
|---|---|---|---|
| `confirm_dossier_links` 条目非 dict / target 非 int →`[]` | F1#2 | **raise ValueError** | 探针 `CONFIRM_MALFORMED_RAISE` |
| `confirm_dossier_links` `relation∉DOSSIER_LINK_TYPES` →`[]` | F1#2 | **raise ValueError** | 探针 `CONFIRM_BAD_REL_RAISE` |
| `confirm_dossier_links` except→`[]` | F1 | 上轮已 re-raise | — |
| multi `extract_draft_intent` `invalid_batch`→`draft_action=无` | F1#2/#3 | **raise ValueError**；与 LLM soft-fail 分离 | 探针 `MULTI_WRONG_COUNT_RAISE`；软失败仍 `MULTI_SOFT_DEGRADE 无` |
| multi classify `ValueError`→invalid→无 | F1#3 | **re-raise**（对齐单旨/project） | 同左 |
| `_get_client_base_url` `except→""` 静默 | F1#4 | **tlog 后 return ""** | ADR 0005 |
| `enrich_initiative_effects` `_canonical` 静默 except | F1#4 | **`_log` 后 fallback** | ADR 0005 |
| `ThreadPoolExecutor` 未导入 | F1 邻接 | **补 import** | 确认 future 路径可构造 |
| `project_draft_extract` ValueError→ordinary | F1 | 上轮已删 | — |
| `_extract_secret_order` 确认失败剥光 | F1 | 上轮已 `extract_failed` | — |
| `month_chain` 非 dict supply→`{}` | F1 | 上轮 abort | — |
| 缺 `pay_order_override.entries`→「无」 | F1 | 上轮 raise | `test_single_pay_order_capture_rejects_missing_entries` |

### 保留（可核，非套话）

| 成员 | 保留依据 |
|---|---|
| 首抽 / 多旨 LLM `Exception`→`draft_action=无` | 源码注释 owner：「纠错重试路上 LLM 挂死响亮上抛；首抽仍吞掉以免挡对话」；纠错路径仍 raise；**不**引用已失踪的假测试名 |
| `enrich_initiative_effects` LLM except→空效果 | `test_enrich_backend_error_returns_empty_effects` |
| acting_appointment→`无` | `test_draft_extraction_does_not_capture_acting_appointment` |
| `breach_plea` 逐项 pass | ADR 0005/0015 逐项脏隔离；非整批成功洗；入口 `test_regret_via_extraction_true_entry_zero_damage` |
| `_run_startup_extraction_catch_up` TicketCancelled | 取消语义；ADR 0036；`test_startup_catchup_uses_ticketed_gate_not_bare` |
| `token_stats` 装补丁 import 失败 / record_usage 失败 | 已 `tlog`；F1#4 允许旁路继续 |

### 压缩保留
解析归一 / 资源收尾 / rejected 记账 / 控制流哨兵：启发式仍有大量 except→pass/return，本轮**逐项语义**后未再发现抽取缝非法洗产物；不得以候选计数代替结清。

---

## F2 有效运行配置只许共核

### 类定义
有效 channel/runner/model/timeout/reasoning 只许 `llm_config_from_runtime`；入口可留原样存盘值供表单。

| 成员 | 分类 | 处置 | 可核依据 |
|---|---|---|---|
| `api_menu_status` | F2 | 维持共核 | `MENU_CALLS_CORE True`；`"reasoning_strength": cfg.reasoning_strength` |
| 分槽 `cli_/api_reasoning_strength` 原样 | 保留 | 表单存盘 | 非第二生效规则 |
| POST `normalize_reasoning_strength` | 保留 | 入参归一 | — |

---

## F3 测试清退（全定义）

### 类定义
失效 mock、重复内部/失效证明、**任何**散文机械约束、来源弱化、专用死夹具。保留来源契约与闸类负向。不整删整补、不另造平行测试。  
**flags 未命中不得自动合法。参数字面串 ≠ 散文 pin。**

### 本轮处置成员（scroll/lens + 死夹具 + 来源弱化）

| 成员 | 分类 | 处置 | 可核依据 |
|---|---|---|---|
| `ministerScrollLens.test.ts` `map(content).toEqual` 全文 | F3 散文 | **改 `lensShape`（role/speaker/beat/turn）** | vitest 该文件绿；fixture 正文仅输入 |
| `modals.test.tsx` ScrollMessages / ChatModal / archive 对话 `toContain`/`textContent===` | F3 散文 | **改 turn-id / role / speaker 结构**；废 #1511 lens 错缝评语 | vitest 绿；P6 markdown 透传保留 |
| `appDurableWiring.test.tsx` 召对卷正文 pin | F3 散文 | **改 aside/turn 结构** | vitest 绿；SSE 结构化 error 保留 |
| `test_audience_scroll_539` 对话 content 列表 | F3 散文 | **改 (role,speaker[,turn])**；保留 `join==story` / live==closed / projection | pytest 绿 |
| 28 确认零引用死夹具（见回执枚举） | F3 死夹具 | **删 def** | 删前 `rg` 零调用；非 fixture |
| `test_run_pi_flags…` `"-p" or "--print"` | F3 来源弱化 | **收紧 `"-p" in cmd`** | pi 现役 argv 真源 |

### 保留（可核）

| 面 | 保留理由 |
|---|---|
| live==closed content 对等 / `join(segments)==story` / restore·projection content | **来源透传契约** |
| P6 markdown 原文、`detail.message`、typed question 透传 | LLM/错误源不篡改 |
| `欠饷约N万两` approx / 内部分账列名不得进出口 | 呈现契约 / P4 隔离负向 |
| 闸类负向（不得闪回个人史、unnamed speaker 不能 finish） | 闸负向 |
| audience_night_498 / restore_505 / mindreadingDelivery 内容相等 | 写→读源透传或 gate sentinel |

### 诚实边界
全仓 ~249 测试文件启发式成员极多；本轮对 **scroll/lens 全文 pin + 确认死夹具 + 触及面来源弱化** 做完语义清扫，并对受众相关文件 spot-check。不得把「路径表」说成「每一 assert 已逐条改写」。

---

## F4 无语义纯转发

### 类定义
入口层无语义、仅同签名转发的包装。须逐项语义，不得套「资源适配」糊弄。

| 成员 | 分类 | 处置 | 可核依据 |
|---|---|---|---|
| `GameDB._primary_source_only_army_pay_container_total` | F4 | **删**（0 调用死别名） | `hasattr=False` |
| `GameDB.list_recent_issue_advances` | F4 | **删**（0 调用死查询） | `hasattr=False` |
| `validate_delta_shape` + `decree` 未用 import | F4 | **删**；现役=`sanitize_delta_shape` | `hasattr=False` |
| 上轮已除：`_review` / `ensure_open_night…` / `qualitative_character_attribute` / `_transaction_categories` / `read_credit_events_as_edges` | F4 | 维持 | — |
| `GameSession._character` / write_queue / `investigation_tip_records` / HTTP `api_state` | 保留 | 具名 façade / 供料缝 / 路由面 | 有真实消费者 |

### 压缩保留
AST Return(Call) 启发式仍多（DB 查询、协议方法、coerce、工厂）；本轮语义后**未再发现**零调用纯别名。
