# #1843 F2-R10c 证据补齐腿施工回执（禁止 amend）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`
分支：`ak-roles/issue-1843-w5-r6-f2`
底座（本补齐提交前）：`5c57bef54a0a9f39595c63bd55bbdd2ea7f51048`
派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a108b9-e49f-7a41-a7de-d543dc256654@fixer/fix-packet.md`
判词末 payload：同目录 `attachments/02-1843-judge-4d25772ae.json` → `payloads[-1]`（status=continue；F2-R10-1 / F2-R10-2 送修；G1 已结）

## 纠正 r10b 回执

| 问题 | 纠正 |
|---|---|
| 「全仓…91条」「18个…」聚合冒充逐名 | 废止聚合行；`1843-f2-r10c-f2-all-candidates.tsv` 2101 行 + `1843-f2-r10c-f1-ooc-members.tsv` 30 行逐名 |
| 命令只引 `/tmp/1843-f2-r10b/*.py` 无脚本正文 | `1843-f2-r10c-enum-commands.txt` 含完整 heredoc；脚本全文亦冻于 `evidence/1843-f2-r10c-enum_f2_r10_{1,2}.py` |
| 「高信号强 DELETE=0」冒充全类结清 | 明确：高信号只是先验已删样本子集；本腿对 **全部 2101** 候选逐名给 disposition/kind/具体 reason |
| 91 identity 统一 `public_seam` | 逐条分类为 `object_identity_public_seam` / `reload_preserve_identity_seam` / `false_positive_identity_flag` 等，reason 含具体断言片段 |
| `git log -S` 只有 Initial ⇒ 不属类 | `faction_metrics`：查实 Initial（de0d7ad41）当时亦仅声明+赋值、无任何读取方；现役读 `content.factions` |
| 机械 DELETE 未删且未披露 | 11 个仍在场零引用 helper 并入类外表，逐名写真实用途；**不借本类清扫**一般死 helper |

## 两类完整定义

### F2-R10-1
沿历史已退役旧结算／simulator 消费者向下核独占支持树：资产、加载绑定、夹具、互引死树、保护失效行为的测试。保留现役 normalize／revise／prewrite／共用存储。不以零引用或样本当边界。

### F2-R10-2
全仓（含 web）删除非契约源码／措辞锁、helper／内部结构案及重复案；复用真实入口→外部结构化；保留必要结构化负向与确定性 HUD。不得另造扫描机制／证明测。**定义覆盖全部候选，不是「高信号」子集。**

## 枚举与逐名表路径

- 命令（含完整脚本 heredoc）：`evidence/1843-f2-r10c-enum-commands.txt`
- 冻结脚本：`evidence/1843-f2-r10c-enum_f2_r10_1.py`、`evidence/1843-f2-r10c-enum_f2_r10_2.py`
- F2-R10-2 全候选逐名：`evidence/1843-f2-r10c-f2-all-candidates.tsv`（2101）
- 原始机械 JSON：`evidence/1843-f2-r10c-f2-candidates-raw.json`
- F2-R10-1 类外逐名：`evidence/1843-f2-r10c-f1-ooc-members.tsv`（30）
- 成员索引表：`evidence/1843-f2-r10c-member-table.tsv`
- 摘要：`evidence/1843-f2-r10c-f2-summary.json`

### F2-R10-2 逐名 disposition 摘要（非结案替代；真源=TSV）

- RETAIN=2101；本腿新 DELETE=0（非法锁已在 `40df97af9` / `5c57bef54` 删除）
- kind 分布真源见 summary JSON；每行 reason 含具体 helper 名或断言片段
- **「高信号强 DELETE=0」≠ 全类结清**；全类结清依据是 2101 行 TSV 已逐名核完且复扫无非法锁

### F2-R10-1 类外 30 名（真源=OOC TSV）

含：`faction_metrics`（Initial 亦无读取方）+ 原 18 零引用 + 上轮机械误标仍在场 11 helper。每行有 purpose / hist_check / basis。

## 本腿代码变更

- `tests/legacy_staging_helpers.py`：去掉 EOF 多余空行（修 `git diff HEAD~2 HEAD --check`）
- 仅新增/更新 `evidence/1843-f2-r10c-*`；**无新功能删除**（复查未发现新的非法锁）
- 未新增测试；未新增仓内生产扫描机制；未 stash／amend／push／PR／改配置

## 复扫

```bash
rg -n 'inspect\.(getsource|getsourcelines)' tests web --glob '*.py' --glob '*.ts' --glob '*.tsx'
rg -n '定性说法|定性表述' tests --glob '*.py'
rg -n 'is not original_|shadow_tlog|RESCRIPT_ROUTABLE|NATIONAL_FANOUT' tests --glob '*.py'
rg -n -w '_CANNED|_module_of|_drive_resolve_directives|_canned_settle|_canned_monthly_settlement|_stage_punishment|_close_night_dossier|_stage_yuan_appointment_summon|_close_office_to_dossier|_yuan_row' tests ming_sim --glob '*.py'
git diff HEAD~2 HEAD --check
```

## 聚焦测试（触及面；非全量；无 --deselect）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider --durations=10 \
  tests/test_relation_capture_633.py \
  tests/test_pre_settle_transaction.py \
  tests/test_opening_gazette_delete_1356.py \
  tests/test_secret_order_monthly_progress_566.py \
  tests/test_state_reload.py \
  tests/test_rescript_draft_656.py \
  tests/test_advance_paths_atomic.py \
  tests/test_fiscal_substrate_bridge.py \
  tests/test_pay_order_override_653.py \
  tests/test_qa_e1_numeric_presentation.py
```

结果：**350 passed, 1 skipped in 17.31s**；EXIT 0。日志：`evidence/1843-f2-r10c-pytest.log`。

## 自查二连

- 同类型：废止聚合冒充逐名；枚举命令含完整脚本；2101+30 逐名表可持久复核；faction_metrics 查 Initial 消费者；纠正「高信号 DELETE=0=全类结清」。
- 引入 bug：本腿只修 EOF + 证据；聚焦测试前缀七项 BIN；未 stash／amend／push／开 PR。
