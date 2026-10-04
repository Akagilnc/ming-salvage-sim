# #1847 修内司续修回执（封驳：终态被废回归）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- 分支：`ak-roles/1847-fixer-n6-n10`
- 封驳原文：`~/.ak-roles/books/Ming_LLM/1847/runs/01a107da-59c6-7b5b-b3b8-68a89d0be974@fixer/session/session.jsonl` 最新 user JSON（status continue，line 71）
- fix-packet / 宪法仍适用；**不宣称** converged / merge / 全量绿；**不自行交卷**
- 保留最新判词 accepted：密令排除精确注册表命中、office_rank/ministerFilters 结构字段、prior: 继承理由=0；**不恢复**被删措辞分类机制

## 逐项法源核对（本轮 contested）

| 改动 | 真实字段契约 | 类定义原句 | 处置 |
|---|---|---|---|
| `issues._declared_emperor_ending` 末行 `return None` | `EMPTY_EXTRACTION.emperor_fate` / `docs/DELTA_SCHEMA.md`：非空声明（含「被废」「暴毙」）原样为终态号；`simulation.py:181` 同文 | **不属** N10「自由措辞决定业务准入或结构分类」——token 是 extractor 结构化字段值，不是散文推断；ADR 0142 不授权丢弃已声明终态。亦**不属** N6 运输删改。 | **撤回越权**：恢复 `return {"status": token, "summary": ""}` 原样透传；不新增中文词表 |
| `session.register_unlisted_person_record` 未知派系 `return None` | `faction` 为入册/声明结构化字段；空缺默「中立」=只判空 | N10「自由措辞决定业务准入或结构分类」成立于**静默改写→中立**；判词 boundary「不新增护栏」→ `return None` 属新增拒收护栏，越权 | **撤拒收**：未知非空原样透传；空缺仍默认中立 |
| `session.canonical_new_appointment_person_fields` 未知→中立（同形） | 任命 payload `faction` 同为结构化字段；`test_executor_routing_721` 原契约误认归一 | 同上 N10 原句；与 register 同形 | **停改写**：未知原样透传；空缺默认中立；契约测改为 `test_unknown_appointee_keeps_declared_faction` |
| `context.match_minister_from_text` 子串→全等 | 入口=`summon_character(name_or_text)` / `recognize_xuan_command` 片段；名册身份匹配 | N10「自由措辞决定业务准入或结构分类」：散文子串含姓名即准入召见 | **保留**精确身份（名/官/office_type/faction/aliases 全等） |
| `decree.build_promulgation_judge_context` LIKE→精确官名 | 守门人候选：`office` 注册表身份 + `office_type='六科'` 封闭枚举 | N10 同句：`LIKE '%首辅%'` 等自由官衔措辞决定守门人准入 | **保留** `IN ('内阁首辅','司礼监掌印太监') OR office_type='六科'` |
| `flows._apply_economy_list` purpose | `move.purpose`∈`ECONOMY_PURPOSES` 封闭枚举；支出空缺默认「其它」 | N10：非法 purpose 经 `purpose or 「其它」` 静默改写=措辞→结构分类；boundary 不新增 invalid_enum 拒收护栏 | **保留**停改写；空缺支出仍默认「其它」；非法保持 None 不拒整项 |
| `issues.py` 其余（pairing 词表、direction 同义、outcome alias、欠饷前缀、cancellable 同义等） | 见既有 fn-contract 表；非本封驳点名撤回项 | N6「原文运输删改」/ N10「自由措辞决定业务准入或结构分类」；accepted 已核密令/结构字段路径 | **保留**；不恢复非法措辞分类 |

## 被删/放宽测试核对（不新增证明性测试）

| 测试 | 处置 | 理由 |
|---|---|---|
| `test_initiative_resolve_pairing.py` 18 个 pairing 告警案 → 留 `test_pairing_warnings_key_stays_empty_on_resolve` | 删机制对应测 | N10：标题/tag 子串→告警准入已删；结果键仍空列表。非放松过绿 |
| `test_office_rank_562` pollution/stem reanchor/history title 三测 → 改结构字段/形式分隔断言 | 随机制删改编 | N10：官职措辞解析/旧档词干迁移已删；保留形式分隔与 status 枚举读档 |
| `test_person_delta_adapter` legacy office pollution / displace transit 四测 | 删 | N10：旧档官职污染迁移与顶缺词表死缝已删 |
| `test_faction_leverage_9.test_displaced_minister_faction_leverage_recomputed` | 删 | 同根顶缺/displace 死缝删除后无行为面 |
| `test_section_fiscal_rejections.test_chinese_direction_alias_*` | 接受→拒收 | N10：方向中文同义改写已删；测试跟封闭枚举契约，非 mock 转绿 |
| `test_appointment_tenure_607` 小改 | 保留触及 | 与 office 形式身份对齐 |
| `test_initiative` hasattr 证明测（上轮） | 已删 | 判词禁新增证明性测试；改由 mutation probes |
| `test_unknown_appointee_normalizes_unrecognized_faction` → `test_unknown_appointee_keeps_declared_faction` | **本轮改断言** | 测试向 N10 spec：结构化派系原样透传，不再期望静默「中立」 |

**本轮未新增**证明性/hasattr/探针测试。

## 实测（每次完整七变量 false 前缀）

环境前缀见 `evidence/1847-continue-env-prefix.txt`。

1. `pytest tests/test_month_chain_1847.py -q` → **41 passed** in 7.65s（wall real 8.07s）→ `evidence/1847-continue-month-chain-pytest.txt`
2. 触及面聚焦：
   `tests/test_executor_routing_721.py`
   `tests/test_initiative_resolve_pairing.py`
   `tests/test_office_rank_562.py`
   `tests/test_person_delta_adapter.py`
   `tests/test_new_issues_section_rejections.py`
   `tests/test_economy_section_rejections.py`
   `tests/test_section_fiscal_rejections.py`
   `tests/test_covert_levy_651.py`
   `tests/test_intrigue_concealment_1896.py`
   `tests/test_secret_order_payoff_1504.py`
   `tests/test_appointment_tenure_607.py`
   `tests/test_faction_leverage_9.py`
   → **373 passed, 1 skipped** in 6.38s（wall real 6.80s）→ `evidence/1847-continue-focused-pytest.txt`

**未跑全量**；不声称未跑范围全绿。

## 自查二连 done

- 同类型：终态结构化透传 vs 散文分类混淆；未知派系静默改写同形（register + appointment）；不恢复措辞分类
- 引入 bug：撤 `return None` 拒收以免 declaration_dispatch 误报「已在册」；不 amend/stash/push；`?? node_modules/` 不动
