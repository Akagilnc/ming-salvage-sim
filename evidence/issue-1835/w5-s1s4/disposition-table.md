# #1835 S1–S4 成员处置表（本局）

枚举命令：`evidence/issue-1835/w5-s1s4/enum-commands.sh`  
施工前扫描：`enum-pre.txt`（注：S1 样本 `issue_summary["rejected"]` 在首笔修复后已不在 post 扫描；见下表「已修」）  
复扫：`enum-post.txt`

## S1 typed 契约消费者仍按旧 dict／旧响应形状

| 成员 | 处置 | 依据 |
|---|---|---|
| `ming_sim/entities/issue/delta_section.py:157` `issue_summary["rejected"]` | **已修** → `issue_summary.rejected.append` | 判词样本；`IssueSectionResult` 为 typed dataclass，禁止 dict 下标 |
| `ming_sim/covert_levy.py:46` `result["applied"]` | **保留** | 普通 dict 收据构造（`canonical_fiscal_result`），非 `SectionResult`／`IssueSectionResult` |
| `ming_sim/covert_progress.py:1810` `result.get("rejected")` | **保留** | 查案 helper 返回的普通 dict 标记，非 typed 段 |

谓词：AST 扫描 `applied/rejected/advances/new_issues/closes/cancels/applied_person_changes` 的下标／`.get`，且接收方名含 summary/section/result/outcome/bundle/issue。

## S2 领域规则及 stages 平行实现

| 成员 | 处置 | 依据 |
|---|---|---|
| `preflight._region_noop_error` 及内部 `city_level×8`／`0–100`／数量下限影子公式 | **已删** | 判词样本；改由真实 `apply_region_deltas` 结果判定材料变化／拒收 |
| `preflight._army_noop_error` 及 `min(12)`／score clamp 影子公式 | **已删** | 同上，改由 `apply_army_deltas` |
| 预检内 loyalty 软钳／latched 影子预判 | **已删** | 写核已含同语义；避免平行权威 |
| cannon_transfer `>=12`／latched 影子 noop | **已删** | 结构非法性（目标／符号）保留；封顶 noop 交写核 |
| `capture_commitment_stages` 独立捕获规则 | **已删** | 改 `stages_list_from_source` = `json.loads(stages_to_json(...))` |
| `stages_to_json` | **保留** | DELTA_SCHEMA:304 严格串行真源 |
| 事件整封拒收、字段白名单、整数类型、`controlled_by` 存在性、jisi 结局轮廓 | **保留** | 判词：保留合法物理规则与整封拒收 |

## S3 被替代兼容路径、无效测试及死夹具

| 成员 | 处置 | 依据 |
|---|---|---|
| `issues._legacy_commitment_stop_gate` | **已删** | 旧 `resolve_condition`→stop 兼容链 |
| `_commitment_stop_gate` 对 legacy 回落 | **已修** | 仅读 typed `stop_condition` JSON |
| tracker：空 resolve 回填 stop 字符串 | **已删** | 写侧兼容链 |
| tracker：`legacy_resolve_commitment_shape` 负向拒收 | **保留** | 合法负向契约（无 commitment_kind 的旧形拒收） |
| `test_legacy_character_resolve_condition_commitment_settles_when_threshold_reached` | **已删** | 专属旧测，保活兼容链 |
| `test_new_issue_whitespace_resolve_condition_falls_back_to_stop_condition` | **已删** | 专属 fallback 旧测 |
| `test_apply_score_extraction_reports_no_legacy_person_response_keys` | **已删** | 失去契约检出能力（无断言） |
| `test_apply_score_extraction_accepts_flat_faction_scalar` | **已删** | 失去所称契约检出能力 |
| `_seed_province_pay_split_scenario` | **已删** | 无人消费死夹具 |
| `_commitment_stop_gate` 现役消费者（situation_drift／commitment_display／issues 内） | **保留** | 现行 typed 停止条件 |
| `test_commitment_stop_gate_resolve_respects_outer_transaction_rollback` | **保留** | typed stop + 事务回滚行为 |
| `test_legacy_resolve_condition_person_commitment_rejects_without_marker` | **保留** | 合法负向契约 |
| `test_commitment_display_348` resolve 断言 | **已改** | 对齐「resolve 串不再冒充 stop_gate」 |

## S4 代码捏造政治收益默认值

| 成员 | 处置 | 依据 |
|---|---|---|
| tracker `resolve_eff = {"metrics": {"民心": 1}}` floor | **已删** | 判词样本；P6／ADR0013 D9 |
| `test_initiative_floor_applies_when_enrich_empty` | **已删** | 保活 floor |
| `test_runtime_cli_initiative_floor_applies_without_backend_env` | **已删** | 保活 floor |
| `enrich_initiative_effects` CLI 补全 | **保留** | ADR0013 D9 允许模型补全；空则空 |
| `test_api_channel_initiative_does_not_use_backend_env_enrich` | **保留／改名** | API 通道不得误触 CLI enrich |
| 测试夹具中显式 `民心: 1` 效果字面量 | **保留** | 模型／声明显式效果，非代码 floor |

## 根因摘要

- **S1**：战略事件缺标签拒收仍用旧 dict 下标写 typed `IssueSectionResult`，运行期 TypeError。
- **S2**：预检复制写核数量／封顶公式；`capture_commitment_stages` 对散文静默 `[]`，与 `stages_to_json` 严格面分叉。
- **S3**：旧档 `resolve_condition` 兼容链与专属测／无断言测／死夹具仍存。
- **S4**：CLI enrich 空结果后代码捏造民心 +1。
