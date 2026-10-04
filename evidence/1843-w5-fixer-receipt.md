# #1843 修内司回执（w5 / F2-R11 apply 整类）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`  
分支：`ak-roles/issue-1843-w5-r11-f2`（自 `fab71100c` 开分支后施工）  
派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a10914-924d-782f-befd-de9d9e61b59b@fixer/fix-packet.md`  
末判真源：附件 `03-1843-judge-fab71100c.json` **最后一份 payload**（F2-R11-1 / F2-R11-2）  
未 push、未 PR、未 amend、未 stash；未声称合并或关票。

## 顾问审视（动手前）

- CLI `advisor` / `gstack-advisor` 不可用。
- 本进程独立审视落盘：`/tmp/1843-f2-r11/advisor-review.md`
- 网络检索要点：测试调用不能证明生产需要（gh-aw DEADCODE）；旧兼容须连同专属测整足迹删除（refactor-break-compat）；#1812/#1843 不考虑旧存档兼容，保表不保仅为旧档的迁移。

## 未结两类（末判原文边界）

1. **F2-R11-1**「旧结算／simulator 独占支持树与旧档兼容路径漏退役」— 沿历史消费者与现役入口核完整闭包；删独占支持／死树互引／旧档兼容及专属测；保留现役决策存储与 normalize／revise／prewrite 等共享接缝。
2. **F2-R11-2**「非契约文字／内部结构／重复测试未清，并以弱化断言代替行为验证」— 删源码／措辞／helper／重复／弱化前缀；保留结构化负向与输入同值传递；不造证明性测试或扫描机制。

## 机械枚举（命令与成员表指针）

| 用途 | 路径 |
|---|---|
| 枚举命令说明 | `evidence/1843-w5-fixer-enum-commands.txt` |
| 施工前 A 表 | `/tmp/1843-f2-r11/class-a-members.tsv` |
| 施工前 B 表 | `/tmp/1843-f2-r11/class-b-members.tsv` |
| 扩大旧档闭包 | `/tmp/1843-f2-r11/class-a-expanded.json` |
| 复扫 A（逐名） | `evidence/1843-w5-fixer-class-a-members.tsv` |
| 复扫 B 残留 | `evidence/1843-w5-fixer-class-b-rescan.tsv`（**0 行残留**） |
| 变异证据 | `evidence/1843-w5-fixer-mutation.json` |
| 聚焦测试日志 | `evidence/1843-w5-fixer-pytest.log` |

施工前命令：

```bash
MING_SIM_*_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python /tmp/1843-f2-r11/enum_both.py
```

未使用固定种子／引用阈值／历史下界／同文件活代码白名单收窄；判词点名仅为样本。inventory 标明的 `_migrate`／`_backfill`／`_purge` 旧档路径一并追入闭包。

## 逐 finding／class 处置

### F2-R11-1（成立，本局整类清退）

| 成员／闭包 | 处置 | 消费链依据 |
|---|---|---|
| `_migrate_legacy_reaction_severity` + `_migrate_reaction_value` + init 调用 | **删** | 仅旧 severity→direction/intensity；专属测删除 |
| `_migrate_legacy_office_pollution` + seed/init 调用 | **删** | 旧档＋污染串；**seed 先洗净**七人 status/office 后删迁移 |
| `_backfill_person_core_character_static_fields` | **删** | inventory 旧档静态补丁；seed 已含字段 |
| `_migrate_character_identity_seed` | **删** | 旧档 roster/identity；专属测删除 |
| `_backfill_bandit_power_split` | **删** | 旧档流寇分股；专属测删除 |
| `_migrate_character_location_aliases` | **删** | 开档写回旧别名；`admit_audience` 读时 canonicalize 保留 |
| `_purge_fixed_opening_gazette_seed` + `_known_opening_gazette_seed_text` + `content/opening_gazette.md` | **删** | 仅旧档指纹 purge |
| `_month_end_ctx` / `_army_*` / `_1778_*` | **删** | 定义后无外部消费者的死夹具闭包 |
| 上表全部专属旧档／死夹具测试 | **删** | 见复扫 A 表 DELETED_ABSENT |
| `decree_dossier_decisions` 表 | **保留** | 现役写读；纠正 R9「保留 decisions 迁移」扩权 |
| `test_legacy_character_executor_…` | **保留** | 现役 `create_decree_dossier` 写口（名含 legacy 非旧档） |
| 京师别名 admit 测 | **改留** | 去掉 reopen 写回臂，保留读时 canonicalize |

**旧错误分类订正**：r10c 将 `_month_end_ctx`／`_1778_*` 列「服务现役材料目录」类外、将 decisions 旧档迁移当保留——与真实消费链不符，本局按末判纠正。

### F2-R11-2（成立，本局整类清退）

| 成员 | 处置 |
|---|---|
| `test_region_loader…` 起运定额 `startswith("#259")` | **恢复**调用前捕获输入 `==` 输出 |
| `match=` 异常正文措辞（全仓枚举命中的字面量） | **去掉 match=**，保留 `pytest.raises(类型)` |
| 财政日志 `startswith("[province-fiscal]")` 等 | **删措辞断言**，保留 flow/落库结构化结果 |
| `army_pay_morale_delta` 纯公式案、重复常量子集＋无用 game 夹具 | **整测删除** |
| `assert not hasattr(..., "max_tokens")` 等内部属性缺席 | **删除**；保留对外证据块断言 |
| #1471 HUD name/amount 负向 | **保留**（末判 G1 已结清） |

未新增证明性测试、扫描机制、兼容层或护栏。

## 根因消费链（摘要）

旧结算／simulator 消费者退役后，以「表还在／同文件有活代码／测试还在引用／枚举标签」代替真实消费链，导致旧档迁移与死夹具残留；合并轮又把措辞／内部锁与弱化同值断言带回。本局按用途删简：seed 洗净 → 删迁移 → 删专属测；测试侧只咬外部结构化结果与同值传递。

## 聚焦测试（完整命令 + 实测时长）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider --durations=10 \
  tests/test_override_breach_costs_564.py \
  tests/test_structured_decree_contract_1624.py \
  tests/test_pihong_dossier_1490.py \
  tests/test_opening_gazette_delete_1356.py \
  tests/test_person_delta_adapter.py \
  tests/test_audience_night_498.py \
  tests/test_audience_travel_gating_670.py \
  tests/test_bandit_power_model_190.py \
  tests/test_mutiny_progression_316.py \
  tests/test_person_archive_schema.py \
  tests/test_fiscal_substrate_bridge.py \
  tests/test_pay_order_override_653.py \
  tests/test_rescript_draft_656.py \
  tests/test_llm_channel_config.py \
  tests/test_army_salary_44.py \
  tests/test_event_trigger_gate.py \
  tests/test_executor_routing_721.py
```

实测（`evidence/1843-w5-fixer-pytest.log`）：**764 passed, 1 warning in 40.60s**；`/usr/bin/time -p` → **real 41.09s**。  
另补：`tests/test_identity_seed_488.py` + `test_capital_aliases_admit_in_capital` → **11 passed in 0.95s**。  
非全量。

## 变异证据（已有真实入口案；源码已恢复）

见 `evidence/1843-w5-fixer-mutation.json`：

| 步骤 | 结果 |
|---|---|
| B0 同值传递基线 | pass 1.27s |
| B1 生产深合并截断 `#…` 叶为 4 字符 | **fail**（equality 咬住）0.77s |
| B2 恢复 | pass 0.74s |
| A1 `canonicalize_location_region_id` 改为恒等 | **fail**（admit 别名案）0.73s |
| A2 恢复 | pass 0.74s |

## 复扫

- A：已删符号 **leaks=0**（`evidence/1843-w5-fixer-class-a-members.tsv`）
- B：源码锁／字面 match=／`#` 前缀／hasattr 缺席／纯公式 **remaining=0**

## 自查二连

- 同类型：按末判两类全文边界枚举，不拿样本当白名单；订正 r10c 类外与「保留 decisions 迁移」。
- 引入 bug：删 `_migrate_reaction_value` 时曾残留 `@staticmethod` 挂到 `_record_decree_cost`，已摘除并用 override／pay_order 聚焦测验证。

## 剩余范围

- 未跑全量 suite（按派单只跑触及面）。
- docs 历史证据文仍提及已删符号名（非生产路径），未借本局清扫文档史。
- 其它 `_migrate_*`／`ensure_column` 若属 schema 演化而非「仅为旧档数据改写」，本局未整删；复扫 A 以 inventory+判词闭包为准已清零点名旧档迁移。

## 最终 commit

- 分支：`ak-roles/issue-1843-w5-r11-f2`
- hash：`522ded2ef2a4be87fe247bef61e7979ff6465cf3`
- 标题：`ak-roles: fix(#1843) retire F2-R11 old-save trees and non-contract test locks`
- 工作树干净；未 push；未合并；未关票。
