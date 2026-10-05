# 1834 F21/F22 修内司回执（全仓枚举纠正轮）

HEAD_BASE: `3cb37697d87e5b8a2be2b83c8a3025232eb2ff5e`
BRANCH: `ak-roles/1834-f21-f22-ebcd2d1a1`
HEAD_AFTER: `66b88fa77f5158c8f015d97480803e798283dd3e`

## 本轮纠正（对复核 / 必须修类）

1. **F22 枚举仍缩在 ChatTurnResult matrix + format + expanded named set** → 改为一次性全仓：Python `FunctionDef`/`ClassDef`/`dataclass` 字段 + TS `export`/`type`，及其全仓引用（`scripts/enum_f22_full_defs_refs.py`，标准库 AST 临时用，非永久分类层）。
2. **ENUM_CMDS CMD139/148/153 自然语言伪命令** → 废止；改为可执行 `enum_cmds.sh` + `ENUM_CMDS.txt` 实命令；产物在 `enum_out/`。
3. **零真实消费者完整清单** → `enum_out/f22_zero_consumer_candidates.{md,jsonl}` + 逐条处置 `f22_zero_disposition.tsv` 入 `MEMBER_TABLE.md`；不按名字筛 selected set、不缩到单一 dataclass。
4. **EN_VALUE_CN 假借非自由正文绕开 F22** → 追职责后 **DELETE**（零消费者旧枚举表）。
5. **F21** → 自由字段 candidate 全表追数据流（输入/写入/读取/物化/供料/前端显示）；确认 station/highlights FIX 仍在；materials spoken/前端 trim 判空赋原文；禁止 AST 自动 KEEP。

## 根因（不变）

- **F21**：人读自由字段曾被 strip 改写；须沿真实数据流保原文。
- **F22**：退役零消费者专属结构残留；公开现役 API 零 Python 调用属常态，不得误删。

## 生产改动（本轮增量）

| 类 | 增量 |
|---|---|
| F21 | 无新增 FIX；三站点+供料/前端数据流确认；132 freeish 候选完整入表 |
| F22 | DELETE 零消费者退役结构：`EN_VALUE_CN`、`Suggestion`、`ExtractionPendingStatus`、`PromulgationHealEvidence`、`run_audience_turn_translation`、`stage_referral_candidate`、`stage_revoke_authority_candidate`、action_clusters/decree/covert/context/content/qualitative/report/materials/llm_contract/applier/db 私有零调用、`WebGame.apply_llm_config`/`_open_night_court_break` 等；公开 `api_*`/GameDB 公开方法/实体 store/CliChat 流式面 **KEEP** |

## 枚举计数（可复现）

```
F21: all_crop_write_shapes=1721 freeish_name_candidates=132
F22: def_count=3652 zero_abs=54 zero_prod_test_only=70 corpus_files=422
```

命令：`bash evidence/1834-f21-f22-fix/enum_cmds.sh`

## 真实入口旧红新绿

当前保原文站点 intact（`mutation_real_entry.out`）：`current_green=true`；伪变异仍撤销见 `MUTATION_FAKE_REVOKED.txt`。

## 聚焦测试

七前缀：`MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false`

- Python：`323 passed, 1 warning in 9.63s`（real 10.05s）→ `pytest-focus.out`
- Web：`Test Files 5 passed；Tests 158 passed；Duration 3.93s`（real 4.05s）→ `vitest-focus.out`

## 准确剩余 scope（不冒充全清）

- 枚举后仍存在的零消费者公开 API / GameDB 公开读面 / 实体 store / 探针脚本：已逐条 KEEP（见成员表）；无退役职责证据不泛删。
- 冻结 evidence 内旧符号叙述：不改写。
- 本票其它未结类 / 接线票（#1861/#1840/#1843 等）：不在本回执范围。

## Advisor

- 未改治理/Soul/配置；未 stash/amend/push/PR/kill。
- 未新建永久分类层或永久证明测试（仅 evidence 下一次性 AST 脚本）。
- 自查二连：同类型（全仓零消费清单 vs 具名集缩边界；公开 API KEEP vs 专属死码 DELETE）；引入（删透传/死类型不影响 answer/court_action 与 materials 供料）。
