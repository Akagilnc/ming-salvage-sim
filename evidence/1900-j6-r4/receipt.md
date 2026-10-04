# #1900 修内司回执：J6-r4（修理 diff 断言类扫）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1900-w5`
- 分支：`ak-roles/1900-j18-j6-final-class-repair`
- 判词：本 session 用户消息（J6-r4；J18 已成立不再修）
- 禁令：无 stash / amend / rewrite / push / PR；未改生产机制 / Soul / 宪法 / 外部配置；未造平行测试或生产钩子
- 基数：`bb448254c` .. 工作树（含本提交）

## 1. 任务范围

对修理 diff **所有新增/改写断言**做机械枚举 → 语义归类 → 整类清掉新引入的非契约文字锁 / 恒真占位。J18 不施工。

## 2. 机械枚举命令

完整可复现命令：[`enum-cmd.txt`](enum-cmd.txt)

```bash
git diff --name-only bb448254c -- tests/ web/src/

# -U0 hunk 扫 +assert / +pytest.raises / +expect(.（见 enum-cmd.txt heredoc）
# 产出：enum-added-asserts.json（修理 diff 快照 85 行）
# 裁决表：j6-r4-members.{md,json}（87 行 = 快照 + 本轮 FIX 新增）
```

实际枚举：Python/Web 触及 40 文件；修理 diff 新增/改写断言快照 **85**；处置表 **87**（含本轮改写新增 2）。

## 3. 完整成员表

权威表：[`j6-r4-members.md`](j6-r4-members.md) / [`j6-r4-members.json`](j6-r4-members.json)

### 计数

```
KEEP_RAISES_TYPE: 55
KEEP_INDEPENDENT_CONST: 12
FIX_DELETE: 7
KEEP_ROUTE_CONFIG: 3
FIX_REWRITE: 2
KEEP_STREAM_EVENT: 1
KEEP_CUTOFF_ORDER: 1
KEEP_CUTOFF_MARKER: 1
KEEP_PASSTHROUGH: 1
KEEP_NARRATIVE_PASSTHROUGH: 1
KEEP_ROUTE_KEY: 1
KEEP_ERROR_PACK_PATH: 1
KEEP_POLL_STOP: 1
```

裁决判据：不默认合法；字符串日志 ≠ 结构化 token；恒真/键存在/软下界占位删或改独立准确期望；有效负向与变异已证契约保留。

## 4. 逐 finding 处置

| finding | 处置 | 依据 |
|---|---|---|
| `test_rescript_draft_656` empty/non-list：`options_len=0` / `options_type=str…` | **FIX_DELETE** | 日志字符串 token 锁；保留 drafts 断言 + `assert logs` |
| `test_decree_commitment_settlement_229`：`paid_total>=0` / `"remaining_arrears" in` | **FIX_DELETE** | 恒真/键存在占位；保留 `months_elapsed==1` |
| `test_llm_channel_config`：`captured/seen prompt` 非空 | **FIX_DELETE** | 非空占位；保留路由契约（`model`+`prompt` 键 / `config is cfg` / `tag==verify` / 非 CliChat） |
| `test_fiscal_substrate_bridge`：`len(colliding)>=2` | **FIX_REWRITE** → `==2` | 软下界占位 → 准确期望 |
| 同文件：`expected is not None` 双分支 | **FIX_REWRITE** → `net_pct==0` + `expected=7` | 本案夹具净修正为 0；独立常量 |
| 55× `pytest.raises(..., match=)` → 仅类型 | **KEEP_RAISES_TYPE** | 已删措辞锁；异常类型+副作用仍有效 |
| 独立常量数值（empire/fiscal/refugee/grant 中位等） | **KEEP_INDEPENDENT_CONST** | 替方向比较/实现 oracle |
| CLI 罐头全文相等 / narrative→resolution_summary | **KEEP_*_PASSTHROUGH** | 输入/透传契约，非日志措辞锁 |
| cutoff LEAK_MARKER / stream accepted / error_pack_path | **KEEP_*** | 结构化可见契约 |

残余扫描：PRESENT/NEW 行中 log-token / `>=0` / 键存在占位 / prompt 非空 = **0**。

## 5. 聚焦测试（七 BIN=/usr/bin/false；不全量）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
python3 -m pytest \
  tests/test_rescript_draft_656.py \
  tests/test_decree_commitment_settlement_229.py \
  tests/test_llm_channel_config.py \
  tests/test_fiscal_substrate_bridge.py::test_substrate_hub_display_name_collision_books_user_fiscal_exact \
  -q --tb=line
```

实际输出（[`focused-python.log`](focused-python.log)）：

```
155 passed in 3.05s
real 3.57
user 2.51
sys 0.55
```

## 6. 测试必要价值

- 删掉的断言：不咬契约（日志格式 / 恒真 / 非空），留着只制造假绿。
- 保留：条目消失后的 drafts 形状、`assert logs` 响亮、months_elapsed、渠道路由键/tag/非 CliChat、碰撞行数与实入额、异常类型负向。
- 无新造测试；无生产钩子；不改生产机制。

## 7. 自查二连

- 同类型：不只改样本三文件；财政软下界/分支占位同扫同修；成员表覆盖修理 diff 全量 85+。
- 引入 bug：财政曾误钉 `net_pct==-12`（本案夹具实为 0）→ 已改为 `==0`/`expected=7` 并实跑绿。

## 8. SHA

- 本提交 SHA：`8e26da68bc96cb992cc84a430ab168fcd0a9f6a6`
