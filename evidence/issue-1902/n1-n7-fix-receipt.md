# #1902 修内司 N1–N7 回执

- 分支：`ak-roles/1902-n1-n7-fixer-ccbdf378a`
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5`
- 底座 HEAD（开工）：`ccbdf378a`
- 判词真源：末份 `03-1902-judge-ccbdf378a.json` payload（N1–N7）
- 枚举原始输出：`evidence/issue-1902/n1-n7-enum.out`

七 BIN 前缀（下文一律完整写出）：

```bash
with_bins() {
  env \
    MING_SIM_AGY_BIN=/usr/bin/false \
    MING_SIM_CODEX_BIN=/usr/bin/false \
    MING_SIM_CLAUDE_BIN=/usr/bin/false \
    MING_SIM_CURSOR_BIN=/usr/bin/false \
    MING_SIM_KIMI_BIN=/usr/bin/false \
    MING_SIM_GROK_BIN=/usr/bin/false \
    MING_SIM_PI_BIN=/usr/bin/false \
    PYTHONDONTWRITEBYTECODE=1 \
    "$@"
}
```

临时目录（系统临时；探针/变异）：`/tmp/ming1902-n1n7-mutate/`

---

## 假设与范围（施工前）

| 类 | 假设 | 范围 |
|---|---|---|
| N1 | 单旨抽取把解析失败/缺键/非法枚举洗成 `draft_action=无`，补交只报泛化句 | `extract_draft_intent` 单旨路径 + `resubmit_draft_admission_payload`；合法「无」仍走补交消费句 |
| N2 | Web `build_llm_config` / 菜单保存自造生效 `LLMConfig` | 编辑优先级留入口；生效规则只走 `llm_config_from_runtime` |
| N3 | Web 殿上恢复自查夜/轮/筛选 | 中断集合改 `session.pending_audience_reply_retries`；保留 post_reply / 非殿上适配 |
| N4 | 入口对恒有收夜接口的 GameSession 做 getattr 降级 | 删 terminal/web 缺方法降级；不另造资格检查 |
| N5 | 共享抽取残留多旨/补充/候选死模式 | 删模式本体；保留单旨补交；清只服务死模式的测试 |
| N6 | 必要结构/来源契约弱化；措辞/内部证明残留 | 恢复必要契约；删非法证明；不新增证明测试 |
| N7 | 无关 1901 卷宗硬换行被改 | 相对底座 `10e64fbef` 撤销该差分 |

---

## 枚举命令（全仓可重放）

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
cd "$ROOT"
with_bins python3 evidence/issue-1902/n1-n7-enum.out  # 本回合已写入同形 JSON；重跑用回执内嵌脚本
```

本回合实际执行的枚举脚本全文见 git 历史中本文件提交时的 `n1-n7-enum.out` 生成命令（`python3 <<'PY' …`，输出 tee 到 `evidence/issue-1902/n1-n7-enum.out`）。谓词按票面类定义：

- **N1**：拟旨意图解析失败/缺键/非法枚举被洗成合法「无」；补交泛化句掩盖真因
- **N2**：入口自造生效运行配置（共同生效规则副本），相对 `llm_config_from_runtime`
- **N3**：恢复集合身份/筛选不在会话共核
- **N4**：入口 `getattr` 缺方法降级到同步收夜/`auto_close`
- **N5**：共享抽取不可达旧模式（`draft_count>1` / 补充 / 候选 / 成品旨稿批抽）
- **N6**：必要结构及来源契约弱化；非契约诊断措辞；内部/无依据证明
- **N7**：非本票职责的历史卷宗格式差分

---

## 成员表（修复 / 保留及理由）

### N1 现役补交仍抹平非法产物的失败原因

| 成员 | 处置 | 理由 |
|---|---|---|
| `extract_draft_intent` 单旨：`_loads_lenient`→缺键/`or "无"`/非法枚举→`draft_action=无` | **修** | 解析失败/缺键/非法枚举改 `ValueError` 真因；合法「无」仍短路返回 |
| 首抽 LLM `Exception`→空 raw 洗「无」 | **保留（改形）** | 首抽挂死仍公开 degrade 为合法「无」；与非法产物分离 |
| `resubmit_draft_admission_payload` 泛化句 | **保留（收窄承接）** | 仅承接模型明确合法「无」；非法产物不再落到此句 |
| 多旨 `invalid_batch` 响亮上抛（既结 F1） | **保留** | 本轮 N5 退役多旨后随模式删除 |

### N2 有效运行配置仍有 Web 副本

| 成员 | 处置 | 理由 |
|---|---|---|
| `WebGame.build_llm_config` 自造 `LLMConfig(...)` | **修** | 编辑优先级收成 runtime 后走 `_llm_config_from_runtime` |
| `_menu_save_cli_llm` / `api_menu_save_llm` 自造生效配置 | **修** | 表单值→runtime→共核投影；探针 `projection_calls=1` |
| `/api/menu/status` 共核投影 | **保留** | 既结 F2 |
| `_advanced_llm_config_for_verify` | **保留** | 从已生效配置切片 advanced 烟测，非第二套生效规则 |
| CLI 闸脚本 `LLMConfig(...)` | **保留** | 非 Web/运行档生效路径 |

### N3 恢复集合的身份和筛选规则未完全共核

| 成员 | 处置 | 理由 |
|---|---|---|
| `WebGame.reply_retries(殿上)` 自查夜/轮/筛选中断集 | **修** | 中断集改 `session.pending_audience_reply_retries()` |
| 同函数 post_reply 叠加 | **保留** | boundary：Web post_reply 适配 |
| 非殿上 `interrupted_reply_retries(minister)` | **保留** | boundary：非殿上请求适配 |
| CLI `pending_audience_reply_retries` | **保留** | 既结共核消费者 |

### N4 入口保留只服务残缺替身的旧生命周期降级

| 成员 | 处置 | 理由 |
|---|---|---|
| `terminal.py` retry/court_break：`getattr(schedule/close)`→`auto_close` | **修** | 直调 `schedule_close_night_after_chat_if_needed` |
| `web_app.py` retry / stream close：`getattr` 降级 | **修** | 直调 session 收夜方法 |
| `_auto_close_open_night_gate_free`（过月屏障） | **保留** | 非缺方法替身；颁诏/advance 真路径 |
| 测试 `_RetrySession` 补齐同形方法 | **修（测试）** | 不把生产降级加回 |

### N5 共享抽取能力仍携带不可达旧模式

| 成员 | 处置 | 理由 |
|---|---|---|
| `extract_draft_intent` `draft_count>1` 整支 | **删** | 无生产消费者 |
| 补充/合并/候选指认（`has_pending_draft`/`existing_*`） | **删** | 无生产消费者 |
| 单旨 + `correction_feedback` + heal/resubmit | **保留** | 现役补交必要承接 |
| `**_retired_mode_kwargs` 忽略 | **保留（薄）** | 不另造拒收机制 |
| 只服务多旨的测试（batch/multi pay_order/batch combo） | **删** | 死夹具 |
| `test_658_…` 多旨段 | **改单旨** | 保留御笔绑定真实入口契约 |

### N6 测试清退仍混淆必要契约与呈现／内部证明

| 成员 | 处置 | 理由 |
|---|---|---|
| `test_malformed_dossier_origin…` JSON 字串搜 category | **修** | 钉 `economy_moves_rejections[0]["category"]` |
| `test_error_pack` 只查 `!=500` | **修** | 恢复 `stage`/`error_pack_path`/`turn` |
| chat stream `provider_message` 只查非空 | **修** | 钉横幅进 `provider_message`、不进 message |
| due_review `origin or criterion` | **修** | 二者均须在 opening |
| `useSettlementFlow` 删 pollError 留痕 | **修** | 恢复 `console.warn` 带原 Error |
| 不足额/应拨/实拨词面锁 | **删** | 非契约措辞 |
| `test_config_constants_single_source_in_models` identity | **删** | 内部证明 |
| modals「不代笔」负向词面 / placeholder 字数下界 | **删** | 非法呈现证明；UI 引导正向保留 |

### N7 夹带其他票历史卷宗格式改动

| 成员 | 处置 | 理由 |
|---|---|---|
| `docs/evidence/issue-1901-w4-1838-merge.md` 删硬换行空格 | **撤销** | 相对 `10e64fbef` 无差分；不恢复尾随空白门槛 |

---

## 原类复扫结果

| 类 | 复扫 | 结果 |
|---|---|---|
| N1 | 洗「无」模式 / 补交泛化 | 非法三因分句；合法「无」仍泛化消费句；变异 RED→GREEN |
| N2 | 菜单 POST 投影计数 | `projection_calls=1` status=200 |
| N3 | 殿上 reply_retries | 走 `pending_audience_reply_retries`；getattr 降级 0 |
| N4 | `getattr(.*close_night\|schedule_close)` in entry | **0 命中** |
| N5 | 生产 `draft_count>1`/`成品旨稿` | 仅注释残留；测试 `draft_count=2` **0** |
| N6 | 点名弱化/非法证明 flag | 七文件 bad flags **全空** |
| N7 | `git diff 10e64fbef -- docs/evidence/issue-1901-w4-1838-merge.md` | **空** |

---

## 修复证明（变异）

```text
N1 MUTATION RED: 三非法产物均 → ValueError:结算补交重写未返回拟旨意图  (~0.41s)
N1 RESTORE GREEN: 无法解析 / 缺键 / 枚举非法 三分句；合法无 → 未返回拟旨意图  (~0.40s)
N2 PROJECTION: status 200 projection_calls 1  (~0.85s)
```

---

## 聚焦测试

```bash
with_bins env PYTHONPATH=. python3 -m pytest -q -p no:cacheprovider \
  tests/test_draft_admission_resubmit_1769.py \
  tests/test_decree_dossiers_571.py \
  tests/test_pay_order_override_extraction_653.py \
  tests/test_error_pack.py \
  tests/test_chat_stream_failpaths_393.py \
  tests/test_due_review_621.py \
  tests/test_llm_channel_config.py \
  tests/test_web_llm_runtime_config.py \
  tests/test_cli_entry_1902.py \
  tests/test_web_entry_1902.py \
  tests/test_audience_restore_505.py \
  tests/test_structured_decree_contract_1624.py \
  tests/test_pihong_dossier_1490.py::test_658_typed_target_and_backing_reject_bad_shapes \
  tests/test_rescript_option_field_heal_1746.py::test_first_draw_parse_failure_heals_then_degrades
# → 331 passed in 12.19s

cd web && with_bins npm test -- src/useSettlementFlow.test.tsx src/components/modals.test.tsx
# → 76 passed in 1.09s
```

测试改动契约：复用/收紧既有入口案；删死模式与内部证明；**不为 finding 新增证明测试**。

---

## 未结项

- `_advanced_llm_config_for_verify` 仍直接 `LLMConfig(...)`：本席判为已生效配置的 advanced 烟测切片，非菜单/启动生效规则副本；若大理寺认定同属 N2 类，再收进共核。
- 过月 `_auto_close_open_night_gate_free` 保留（非 N4 缺方法替身）。
- 功能缺口/家族复杂度比较仍归 #1812/#1873，本票不设。

自查二连 done。
