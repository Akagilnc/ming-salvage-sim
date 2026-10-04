# #1843 修内司回执（w5 / F2-R11-r / r14）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`
分支：`ak-roles/issue-1843-w5-r11-f2`
判词真源：本 session `session.jsonl` 末条 user（run `01a10914-924d-782f-befd-de9d9e61b59b@fixer`）；payload 含 `F2-R11-1-r` / `F2-R11-2-r`
基线取证：`fab71100c` 绿 · `de50a1314` 红（台院全量五红；本局**不**复跑全量）
本局 HEAD：见文末 commit（独立 `ak-roles:`，**禁止 amend**）
未 push、未 PR、未 stash、未 SIGKILL、未销毁他人产物；七 `MING_SIM_*_BIN=/usr/bin/false`。

## 与上位「建议全量」的冲突声明（HARD）

台院 `note` 建议修内司本轮最终回执补全量一次。本局派单明确：**只聚焦测试含删除迁移下游**；不全量。上位质量法「全量只在最终待合并状态」——本局非最终待合并状态。**本回执不以全量补验**；聚焦命令与结果见下。

## 顾问

CLI `advisor` / `gstack-advisor` 不可用；未获外部顾问意见。

## 开局 office 裁决（权威）

**保持开局运行态（洗净 seed），改测试咬现役；不复活迁移 / 不新增兼容层。**

依据：

1. `content/characters.json` 相对 `fab71100c`：8 人罢居污染串（`前…罢居…` / `原三边总督，革职候勘`）已拆成 **office=纯职名** + **status/status_reason 承载罢居/革职**；胡廷宴 `三边总督` + `dismissed`。
2. 新鲜 `GameContent.load()` + `GameDB.seed_static_data()` 实测同口径（见 `evidence/1843-w5-r14-seed-office-baseline.tsv`）。
3. 上轮已退役 `_migrate_legacy_office_pollution`；把「罢居」塞回 office 或清空 office 都会复活旧契约。
4. 荐人快照失配的根因是测试在取快照后 `UPDATE office=''`，不是校验核误伤现役职名。

| name | office | status | status_reason（节） |
|---|---|---|---|
| 韩爌 | 内阁首辅 | offstage | 前内阁首辅，罢居蒲州 |
| 钱龙锡 | 礼部尚书 | offstage | 前礼部尚书，罢居松江 |
| 钱谦益 | 礼部右侍郎 | dismissed | 前礼部右侍郎，罢居常熟 |
| 孙承宗 | 蓟辽督师 | offstage | 前蓟辽督师，罢居高阳 |
| 徐光启 | 礼部右少卿 | offstage | 前礼部右少卿，罢居上海 |
| 袁可立 | 登莱巡抚 | offstage | 前登莱巡抚，罢居睢州 |
| 袁崇焕 | 辽东巡抚 | offstage | 前辽东巡抚，罢居东莞 |
| 胡廷宴 | 三边总督 | dismissed | 延绥兵变弹压不力，革职候勘 |

## F2-R11-1-r — 旧迁移删后下游漏清

根因：上轮按名/触及面删迁移，漏掉依赖「开档 migrate / 无 `__fiscal_engine` 旧档 / office 含罢居」的下游用例；开局 office 变化未核。

枚举命令：`evidence/1843-w5-r14-enum-commands.txt`
成员表：`evidence/1843-w5-r14-class-a-members.tsv`（19 行全处置）

| 处置 | 成员 |
|---|---|
| DELETED | `test_unmarked_cutover_save_rejects_and_never_consumes_surcharge`；`_bajiu_names` |
| FIXED | location 旧档在途段；钱谦益/袁崇焕 seed 断言；荐人快照后清 office |
| RETAIN | legacy `__fiscal_engine:0` 现役案；先造态再 list 的荐人夹具；胡廷宴现役钉；tokenizer 字面污染输入；读时 canonicalize 在京 |

订正上轮误保理由：

- 「seed 洗净即下游自动绿」——假。洗净改了开局 office，旧「office 含罢居」断言与「快照后清 office」必红。
- 「只重跑失败文件 / 按名触及面」——假覆盖。删除 migrate 的下游不一定同文件、不一定点名 migrate 符号。
- 「开档未知 location fail-loud 仍属写缝」——假。开档扫已随 `_migrate_character_location_aliases` 退役；现役只在写缝 `set_character_transit` fail-loud（本局一并删开档尾巴）。

## F2-R11-2-r — 参数化 match 产线正文锁

根因：枚举只认字面 `match="…"`，漏 `match=error` / `match=match` 变量绑定。

成员表：`evidence/1843-w5-r14-class-b-members.tsv`

| 处置 | 说明 |
|---|---|
| FIXED×3 | `test_region_loader_rejects_bad_settle_meta_defaults`；`…malformed_settle_shapes`；`…malformed_region_shapes`——去 match 变量，保异常类型 + 参数化负向输入区分 |
| FIXED×3（复扫） | cutover abort 三处 `assert "…" in traceback.txt` 产线正文锁去掉；保 `SettlementAbort` + pack 存在 + traceback 非空 |
| 复扫保留 | content `_meta.notes/postures` 字段契约；测试自注入哨兵消息（boom/crashed/injected 等） |

`git grep`：`pytest.raises(... match=` → **0**；余 `match =` 仅为局部变量名（非 raises）。

## 聚焦测试（完整命令 + 时长；非全量）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_execution_pressure_654.py \
  tests/test_surcharge_causal_chain_650.py \
  tests/test_qa_a3_seed_data.py \
  tests/test_qa_h1_seed_data.py \
  tests/test_recommendations.py \
  tests/test_named_characters_seed_484.py \
  tests/test_office_rank_562.py \
  tests/test_audience_travel_gating_670.py \
  tests/test_fiscal_substrate_bridge.py::test_region_loader_rejects_bad_settle_meta_defaults \
  tests/test_fiscal_substrate_bridge.py::test_region_loader_rejects_bad_plain_settle_meta \
  tests/test_fiscal_substrate_bridge.py::test_standalone_army_pay_funnel_rejects_malformed_settle_shapes \
  tests/test_fiscal_substrate_bridge.py::test_standalone_army_pay_container_total_rejects_malformed_region_shapes \
  tests/test_fiscal_substrate_bridge.py::test_cutover_pay_source_errors_abort_fixed_flows \
  tests/test_fiscal_substrate_bridge.py::test_cutover_outbound_debit_failure_uses_settlement_abort_error_pack \
  tests/test_fiscal_substrate_bridge.py::test_cutover_missing_human_loss_rate_uses_settlement_abort_error_pack
```

输出：`evidence/1843-w5-r14-pytest-focused.txt`

- **176 passed in 3.30s**；`/usr/bin/time -p` → **real 3.66s**
- 另 abort 三案单独复跑：**3 passed in 0.88s**；real 1.23s（日志 `/tmp/1843-r14/focused-abort.txt`）

**未跑全量。** 不以全量绿冒充实核。

## 生产净改

本局**零生产代码改动**（只测 + evidence）。`git diff --numstat de50a1314 -- . ':(exclude)evidence'` → 6 tests paths。

## 自查二连

- 同类型：按已删迁移/污染 seed/手工旧档用例整类枚举，不按五条白名单；参数化 match 与 traceback 产线正文同形一并清；开局 office 裁决写入回执。
- 引入 bug：未复活 migrate；未改 content seed；荐人其它「先造态再 list」案保留；legacy fiscal_engine=0 案保留。

## 法律阻断

无。

## 最终 commit

- 分支：`ak-roles/issue-1843-w5-r11-f2`
- hash：
- 未 push；未合并；未关票。
