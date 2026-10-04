# #1900 修内司施工回执（宽谓词 J6 续轮）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1900-w5`
分支：`ak-roles/1900-j18-retire-revoked-mechanisms`
既存 `?? .baseline/` 未动；无 stash / amend / rewrite / push / PR。

未结类别以末份判词 continue payload 为准：J18（P1）、J6（P2）。本轮主攻 J6 自限谓词与类成员修净。

---

## 1. J6（宽谓词 + 语义成员）

### 谓词纠正

`j6_flag_structural_candidates.py` 已去掉自限过滤：
- 不再要求中文≥10 + 措辞/wording/label/材料/邸报
- 不再因 list_/apply_/status_code 等结果 token 跳过 helper/mock
- web 不再要求 toHaveBeenCalled 且无 fireEvent

宽谓词覆盖：文本比对/计数、mock/patch/spy、helper/private、公式/oracle、退役标记、web mock/text/count。

### 可重跑命令

```sh
python3 evidence/1900-j18-j6-retire-fixer/j6_enumerate_universe.py
python3 evidence/1900-j18-j6-retire-fixer/j6_flag_structural_candidates.py
```

### 计数（复扫后）

- universe：见 `j6-universe-summary.json`（约 2868）
- 宽结构候选：见 `j6-structural-candidates-summary.json`（约 2609；有信号≠属类）
- **宽候选处置**：`j6-wide-candidate-disposition.jsonl`（全覆盖，含 disposition_basis）
- **语义成员表**：`j6-semantic-members.jsonl` + `j6-class-members-wide-round.jsonl` + `j6-clear-residuals.jsonl`
- 摘要：`j6-wide-disposition-summary.json` / `j6-disposition.md`

### 本轮已落地代码处置（确认类成员）

| action | 项 |
|---|---|
| delete | `test_promulgation_judge_561` 七个 `scripts.promulgation_gate_561` 私有 helper 专测；legacy 引擎专测（pay_order / surcharge；clear-residuals 另列 fiscal dual-track） |
| migrate | error_pack：去掉 `match=atomic`，改断完整五件包缺席；mirror 升结构化字段并引 ADR 0008；path 契约引决定 7；promulgation 去掉 `power_band` oracle→定性带；faction_leverage 去掉 `_set_meta_flag`；transit 删除 `_oracle_n` 公式；全仓注入型/`回滚` 等 `match=` 措辞锁；若干 call_count→公开结果（month_chain/rescript/decree） |
| retain（有 spec） | error_pack 路径/镜像（ADR 0008 决定 5/7）；LLM 边界零调用+字节/选数结果；回调序契约等 |

### 诚实边界（不夸张结类）

- 宽候选全量已处置，但 `wide_flag_no_high_confidence_member_rule` 的 retain **不是**「不属类」证明。
- 高置信 in-tree outstanding（calls-only/材料规则误报）已人工改判；若复读宽命中段仍可能发现新成员。
- **不自行宣布 J6 converged / 类净。**

---

## 2. 聚焦测试

七变量均 `/usr/bin/false`。

- `focused-wide-round4.log`：**1271 passed, 1 skipped**
- `focused-wide-round5.log`：**375 passed**（agent 删改触及面）

未跑全量。

---

## 3. 自查

- 机器枚举 ≠ 语义处置；无高置信规则 ≠ 不属类。
- 点名样例：error_pack atomic/路径/mirror 已按 ADR 与实结果处理，非 public 名豁免。
- 未 stash/amend/rewrite/push/PR；`.baseline/` 未动。
- 自查二连 done。

## 4. 合法阻断

无。工作量不是合法阻断。不把下一庭当兜底；本回执如实列出宽命中 retain 的非免责性。
不自行宣布 merge / 关票 / converged。
