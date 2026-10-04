# #1900 修内司回执：末复检（报告格式 + 枚举可复现 + 触及面验证）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1900-w5`
- 分支：`ak-roles/1900-j18-j6-final-class-repair`
- 判词真源：`~/.ak-roles/.../02-1900-judge-bb448254c.json` **末份** continue（payloads[2]）
- 禁令：无 stash / amend / rewrite / push / PR；未改 Soul/宪法/外部配置
- 本提交：仅自建报告格式（trailing WS / EOF / 枚举命令补回 / 计数与 SHA 记录）；无新功能施工

## 1. 两类别实际处置

| 类 | 级别 | 实际处置 |
|---|---|---|
| **J18** | P2 | 专用账本/双载体/护送实况假断复扫：**生产路径 0 命中**（仅退役说明与史档）。成员表维持 KEEP_LIVE* / KEEP_LIVE_OR_INCIDENTAL / KEEP_RETIREMENT_NOTE；无新残留施工。 |
| **J6** | P2 | 权威表 `j6-full-disposition.json` 618 行、`j6-web-members.json` 145 行均为 `audited=true` 且 **PENDING_*=0**（含自有 web 129 + EXCLUDE_THIRD_PARTY 16）。类修已落：注入 match 措辞锁、power_band oracle、罐头子串、子代理 FIX（smoke/rescript/useSettlementFlow）。本复检未发现新残留，不虚构额外清零动作。 |

## 2. 枚举命令（完整机械候选，可复现）

完整 AST+rg 命令真源：[`enum-cmd.txt`](enum-cmd.txt)（一次性调查脚本，**非**生产通用扫描机制）。

### J18
```bash
# AST：ming_sim/**/*.py + web_app.py 上凡 def/assign 体命中
# escort|护送|护行|暗护|押解|grant_arrival|reconciliation|双载体|专用…|payload_declares|…
# 产出：j18-ast-candidates.json → 裁决 j18-full-members.{md,json}
# 完整 heredoc 见 enum-cmd.txt

rg -n --glob '!evidence/**' --glob '!.baseline/**' \
  'escort_pending_targets|escort_sources|dossier_escort_outcomes|_resolve_covert|_grant_escort_presence|clamp_grant_arrival|_escort_identity|_reader_may_cite|grant_route_reader|is_grant_allocation_dossier|_write_dossier_payload_key|_GRANT_ESCORT_RELATIONS|护送实况|list_open_grant_reconciliations|软判提案|软判读账' \
  ming_sim web_app.py tests docs --glob '*.py' --glob '*.md'
```

### J6
```bash
# AST：tests/**/*.py 每个 test_* 扫 monkeypatch.setattr / call_oracle / marker /
# direction / OperationalError|中文 in / translate_fn=lambda / helper 命名
# + 细粒度 stub:target / fixed_translate / retire_prove（见 enum-cmd.txt 第二段 heredoc）
# 原始候选：j6-ast-candidates.json
# 权威处置：j6-full-disposition.json / j6-web-members.json

rg -n --glob 'tests/**/*.py' \
  'apply_legacy_pct\(|grant_arrival_bounds\(|_has_meta_flag\(|routed:|track_auto_close|seen\.get\("write_gate"\)|assert any\(.*第一问|assert all\(.*后轮问|internal.*=.*substrate_hub|直到补齐.*=.*in|pytest\.raises\([^)]*match\s*=|== power_band\('

rg -n --glob 'web/src/**/*.{ts,tsx}' 'vi\.spyOn|toHaveBeenCalled|mockImplementation'
# node_modules 命中仅作 EXCLUDE_THIRD_PARTY，不算自有测试处置
```

## 3. 成员表与处置（复检）

- Python 618：[`j6-full-members.md`](j6-full-members.md) / [`j6-full-disposition.json`](j6-full-disposition.json)；**PENDING_*=0**，全部 `audited=true`
- Web 145（含 16 第三方排除）：[`j6-web-members.json`](j6-web-members.json)；自有 129 已审；**PENDING_*=0**，全部 `audited=true`
- J18：[`j18-full-members.md`](j18-full-members.md)

裁决判据（逐项）：stub 是否替被测行为；断言是否外部契约结构化可见；是否生成文/helper/内部路径机械依赖；必要负向复用真实入口。

## 4. 代码侧类修（施工 SHA，不按样本限界）

施工提交（本复检不新增功能码）：`14c66675e0feb37186c3f22cb8b8ba7471afd95f`

| 修法 | 范围 |
|---|---|
| 删 `match=` 注入/诊断措辞锁 | 27+ 文件；保留异常类型与 DB/状态副作用 |
| `power_band` oracle → 定性字面量 | `test_promulgation_judge_561.py` |
| 罐头回话子串 → 全文相等 | `test_cli_runner_error_typed_1299.py` |
| verify_llm smoke「输出 ok」锁 | `test_llm_channel_config.py` → tag/config/渠道路由 |
| rescript `title in msg` | `test_rescript_draft_656.py` → `options_len`/`options_type` |
| useSettlementFlow 仅 call-count | `useSettlementFlow.test.tsx` → MechanicalTailFailure + error_pack_path |

## 5. 聚焦测试（七 BIN=/usr/bin/false；仅最后改动触及面）

前缀：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

（结果与墙钟由本复检实跑回填于下节。）

### 5.1 Python smoke + rescript
```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
python3 -m pytest \
  tests/test_llm_channel_config.py \
  tests/test_rescript_draft_656.py \
  -q --tb=line
```

### 5.2 Web useSettlementFlow
```bash
cd web && MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
npm test -- --run src/useSettlementFlow.test.tsx
```

## 6. 必要成本 / 契约

- 无新生产机制、无新通用扫描器入库（枚举脚本仅 evidence 一次性命令文本）。
- 测试只复用既有入口与结构化契约；不为证明新造测试。
- 最小必要成本：报告格式修复 + 触及面聚焦验证；施工体以 `14c66675e` 为准。

## 7. 自查二连

- 同类型：报告曾丢 AST 枚举、只留 match/powerband 样本 → 已补回完整机械候选命令；trailing WS / EOF blank 已清。
- 引入 bug：本提交不改生产/测试代码；聚焦触及面实跑绿（见下）。
- 权威表 PENDING=0、web 全审属复检读表结论，非本提交新裁决。

## 8. SHA

- 施工 SHA：`14c66675e0feb37186c3f22cb8b8ba7471afd95f`
- 本报告提交 SHA：见 stdout / `git rev-parse HEAD`（提交后）

## 9. 本复检实跑结果

### Python smoke + rescript
```
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
python3 -m pytest tests/test_llm_channel_config.py tests/test_rescript_draft_656.py -q --tb=line
# → 122 passed in 2.41s；墙钟 real 3.02s（user 1.63 / sys 0.30）
```

### Web useSettlementFlow
```
cd web && MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
npm test -- --run src/useSettlementFlow.test.tsx
# → Test Files 1 passed；Tests 14 passed；vitest Duration 3.51s；墙钟 real 4.81s（user 0.96 / sys 0.19）
```

不全量。不为证明新造测试。
