# #1835 S1–S4 成员处置表（全类复扫，本局）

枚举：`evidence/issue-1835/w5-s1s4/enum-commands.sh` → `full_enum.py`  
谓词：类定义全文；**不以变量名 hint / 七键白名单 / 点名符号 / 单文件收窄候选**。  
施工前：`enum-pre.json` / `enum-pre.txt`  
复扫：`enum-post.json` / `enum-post.txt`

---

## S1 typed 契约消费者迁约

**类定义**：清理仍按旧 dict／旧响应形状消费 typed 段的路径；直接用现有契约；不补 dict 兼容层。

**谓词**：
1. 枚举全部 typed 结果生产者（`SectionResult` / `IssueSectionResult` / `FiscalSectionResult` / `SettlementOutcome` / `DeclarationDispatchResult` 等构造或返回注解）。
2. 消费者闭包：函数内由生产者／`settle_delta`／`dispatch_declaration`／`apply_issue_tracker_output` 绑定的名字，及其段属性上的 `[]` / `.get` / `.items` / `.keys` / `.values` / `.pop`。
3. 旧响应字段键访问（`*_rejections`、退役键等）全列，不按基名过滤，逐条判定。

### 生产者（post：67）

全部为合法 typed 构造／返回；**保留**。清单见 `enum-post.txt`「S1 typed producers」。

### 数据流 dict 形消费者（post：31）

| 成员 | 处置 | 依据 |
|---|---|---|
| `entities/issue/delta_section.py:157` `issue_summary["rejected"]`（上轮样本） | **已修**（825a372e5）→ `.rejected.append` | 判词样本；typed `IssueSectionResult` |
| `delta_section.py:74` `extras.items()`（`extras`←`_resolve_strategic_events` → `Dict[str, SectionResult]`） | **保留** | 迭代段名字典，不是对 `SectionResult` 做 dict 下标 |
| `tests/test_fiscal_*` / `test_pay_order_*` 对 `FiscalTickResult.new_st`／`breakdown` 下标 | **保留** | `settle_tick` 返回财政 tick 结果，字段本是 dict；非 settlement `SectionResult` 旧响应 |
| `covert_levy` / `covert_progress` 普通 dict `applied`/`rejected` | **保留** | 非 typed 段（pre 宽扫误报已由数据流谓词剔除） |

### 旧响应字段访问（post：62）

| 形态 | 处置 | 依据 |
|---|---|---|
| `run.current_extracted.get("economy_moves"|…)` 等声明输入读 | **保留** | 声明 dict 真源，非 typed 结果消费 |
| `effect.get("new_armies"|…)` 局势效果 dict | **保留** | 效果载荷 |
| `SettlementOutcome.sections()` 内 `flat["fiscal_*"]` | **保留** | 合法 typed 投影构造 |
| 测试对声明／效果 dict 的同名键 | **保留** | 输入契约 |

**S1 结论**：typed 结果上的旧 dict 写下标已清；复扫无存活违规消费者。

---

## S2 领域规则及 stages 平行实现

**类定义**：删预检影子数量公式与独立 stages 捕获；复用写核与 `stages_to_json` 严格串行；保留合法物理规则与事件整封拒收。

**谓词**：全仓 `quantity_clamp_cap` / `admission` / `stages_parse_validate` 函数与行级 `max(0,min(`；相同函数体平行组；stages 行命中。

### 数量／钳制／封顶（post rule_members 含写核与行）

| 成员 | 处置 | 依据 |
|---|---|---|
| `preflight._region_noop_error` / `_army_noop_error` 内影子 `city_level×8`／`min(12)`／score clamp（上轮） | **已删**（825a372e5） | 改由 `apply_region_deltas`／`apply_army_deltas` 结果判定 |
| `preflight.py` 行级 `max(0,min(` | **无**（post 复扫 0 命中） | 影子公式退出 |
| `db.apply_region_deltas` / `apply_army_deltas` / `apply_power_deltas` / `apply_region_cannon` 等 clamp | **保留** | 领域写核真源 |
| `content.load_army_content` firearm/cannon clamp | **保留** | 载入物理边界，非预检影子 |
| `army_pay` / `flows` / `models.metrics` / `situation_drift` bar 等 | **保留** | 各自合法物理／月漂移规则，非预检平行权威 |
| identical_body_groups | **0** | 无同体平行副本待合并 |

### stages 解析校验

| 成员 | 处置 | 依据 |
|---|---|---|
| `capture_commitment_stages` | **已删** | 散文静默 `[]` 与严格面分叉 |
| `stages_list_from_source` = `json.loads(stages_to_json(...))` | **保留** | 单一严格串行真源（DELTA_SCHEMA:304） |
| `stages_to_json` 及 db/urge/action_materialize 消费者 | **保留** | 同真源调用 |
| `normalize_commitment_stages` 等辅助 | **保留** | 被 `stages_to_json` 复用，非第二解析器 |

### 事件整封拒收（删影子后复核）

| 证据 | 结果 |
|---|---|
| 真实入口 `dispatch_month_segment`：哗变军 loyalty 贴 cap 的战略信封 | loyalty/pressure 不变，`triggered=False`（见 `mutation-probes.txt` `S2_EVENT_WHOLE_PACKAGE_REJECT`） |
| 聚焦 `tests/test_mutiny_noop_whitelist_319.py` | 含整封拒收案，随聚焦组通过 |

**S2 结论**：预检影子与独立 capture 已退；写核 clamp 保留；整封拒收仍成立。

---

## S3 被替代兼容路径、无效测试及死夹具

**类定义**：按实际消费者清旧停止条件兼容链、专属测／说明、失去检出能力测、无人消费夹具；保留 typed stop 与合法负向契约。

**谓词**：`resolve_condition`／`stop_condition`／stop_gate 触点（含 docs）；弱断言／无断言且涉 legacy／score_extraction 的测；测试私有 helper 零 Load 引用。

### 旧停止条件兼容

| 成员 | 处置 | 依据 |
|---|---|---|
| `issues._legacy_commitment_stop_gate` | **已删**（825a372e5） | 旧 resolve→stop |
| tracker 空 resolve 回填 stop | **已删** | 写侧兼容 |
| `db._is_commitment_stop_condition` + `advance_issue` 中 `or _is_commitment…(resolve_condition)` | **本局已删** | advance 满值时仍把 loyalty 散文当 stop；现仅 `commitment_kind`／typed `stop_condition` |
| `_commitment_stop_gate` 只读 `stop_condition` JSON | **保留** | 现行 typed stop |
| `commitment_condition_role` + tracker `legacy_resolve_commitment_shape` 负向拒收 | **保留** | 合法负向：无 `commitment_kind` 的旧形拒收 |
| `_has_stop_condition` | **保留** | 结构化 stop 在场判定；明确 legacy 散文→False |

### 专属测试／说明

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_legacy_character_resolve_condition_commitment_settles_when_threshold_reached` | **已删** | 保活兼容链 |
| `test_new_issue_whitespace_resolve_condition_falls_back_to_stop_condition` | **已删** | 同上 |
| `docs/test-cleanup-audit-1185.md` 对上列及 floor／flat_faction 仍标 keep | **本局已改 retired** | 专属说明退出 |
| `docs/DELTA_SCHEMA.md` `resolve_condition`「兼容字段」 | **本局已改** | 标明不得冒充 stop |
| `test_legacy_resolve_condition_person_commitment_rejects_without_marker` | **保留** | 合法负向契约 |
| `test_commitment_stop_gate_resolve_respects_outer_transaction_rollback` | **保留** | typed stop + 事务 |

### 失去检出能力测试

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_apply_score_extraction_reports_no_legacy_person_response_keys` | **已删** | 无实质断言 |
| `test_apply_score_extraction_accepts_flat_faction_scalar` | **已删** | 失去所称契约检出 |
| post `weak_or_lost_tests` 2 条（llm_channel legacy_env / power fail_loud） | **保留** | 非本类迁约测；`pytest.raises` 形，非 score_extraction 死测 |

### 无人消费夹具

| 成员 | 处置 | 依据 |
|---|---|---|
| `_seed_province_pay_split_scenario` | **已删** | 判词样本死夹具 |
| post `unused_fixtures` 57 条（多为 `__iter__`／pytest hook／方法名零 Load） | **保留** | 非「被替代兼容」死夹具；字符串／fixture 注入引用，AST Load=0≠无人消费 |

**S3 结论**：旧 resolve→stop 生产链（含 advance_issue）已退；负向契约与 typed stop 保留；审计说明已对齐。

---

## S4 代码捏造政治收益默认值

**类定义**：删代码捏造的政治收益默认／兜底及保活测；模型给空即空；不限「民心」字面。

**谓词**：政治度量键（民心／皇威／士气／军心／官声等）+ floor／兜底／enrich 空／默认奖励语言；函数级同语义。

| 成员 | 处置 | 依据 |
|---|---|---|
| tracker `resolve_eff = {"metrics": {"民心": 1}}` floor | **已删**（825a372e5） | P6／ADR0013 D9 |
| `test_initiative_floor_*` 两案 | **已删** | 保活 floor |
| `enrich_initiative_effects` CLI 补全 | **保留** | D9 允许模型补全；空则空 |
| `test_api_channel_initiative_does_not_use_backend_env_enrich` | **保留** | API 不得误触 CLI enrich |
| 测试夹具显式 `民心: 1` 效果 | **保留** | 声明确效果，非代码 floor |
| `event_to_issue` 按 kind 的预设 ongoing metrics | **保留** | 世界事件引擎内容默认，非「模型 enrich 空→代码捏造」 |
| `BACKLASH_NAMED_METRICS` | **保留** | ADR 背刺代价常量，非空回报 floor |
| `math.floor`／折发 floor／军心 dead-band 等 | **保留** | 非政治收益默认 |

**S4 结论**：空 enrich 不再落民心+1；复扫无生产 floor。

---

## 根因摘要

- **S1**：战略事件缺结局标签拒收曾用 dict 下标写 typed 结果 → TypeError。
- **S2**：预检复制写核公式；`capture_commitment_stages` 散文静默 `[]`。
- **S3**：旧 resolve→stop（含 `advance_issue`）与专属测／失效测／死夹具／过期说明。
- **S4**：CLI enrich 空后代码捏造民心+1。
