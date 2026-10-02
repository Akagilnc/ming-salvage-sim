# #1900 修内司续修回执

## 结算

- J6 completed：按非契约文字、内部形状、helper 专测及失效行为扫类，不以判词样本为白名单。删除呈现/prompt/source/CSS 锁及失效、遮蔽、重复声明；必要拒收、回滚、重开、降级路径复用现役入口与结构化结果。
- J17 completed：来源负向使用真实合法人物端点；其余输入前提合法时，保留拒收类别、原件、零边写入与合法同批项。未恢复人读原因匹配。
- 保留 `588ccd17aed972b5307890dfee018f0cfb878254` 与继承在制品；本轮 forward commit，不 amend、stash、push。不修改生产行为、Soul、席位表、宿主配置或安装。

## 完整机械枚举与成员表

枚举基线 `f21ce4d05`，覆盖 Git 基线与工作树追踪路径的并集；不是只枚举本轮 diff，更不是只搜中文。Python 用标准库 AST 遍历模块、类和嵌套测试声明；Web 用已有 TypeScript compiler API 遍历 describe/it/test 及 each 链。重复同名声明以 occurrence 区分，不把被遮蔽测试当作有效覆盖。

复现命令：`python3 evidence/1900-test-contract-cleanup/inventory.py.txt`（输出至 `/tmp/1900-continuation-members/`）。完整脚本随卷；逐声明基线/现状行段、内容 SHA256、移除/修改/新增/保留处置在 `all-members.json`；所有变化成员的人读表在 `changed-members.md`。

冻结枚举结果：385 个源文件、248 个含测试声明文件；基线 3368、现状 3023 个声明。保留 2586、修改 414、移除 368、新增名称 23；147 个文件、805 个声明发生变化。声明不是参数展开后的运行 case 数；新增名称包含迁移、重命名和拆合，不代表另造 23 套平行证明。

此表是全仓测试声明超集。保留项按照现行外部字段、原文传递、正式协议和判词明确认可的豁免处理，不把“仍含字符串”当作违法谓词。辅助复扫命令：

```sh
rg -n 'assert .*\.(endswith|startswith)\(|assert .*天启|assert .*崇祯|assert .*MARKER|assert .*sentinel|assert .*getMessage\(|assert .*caplog\.text' tests web/src --glob '*.py' --glob '*.test.ts' --glob '*.test.tsx'
rg -n '_require_active_minister\(' web_app.py
```

另外对全部变化 Python 文件逐 AST Expr 检查非调用的裸读取/列表推导/条件表达式；最终无残余。F841 清理后逐项复核只读调用，删除空测试、无用 summary 查询、失去用途的快照读取；没有把 lint 通过当作行为证明。

## J6 类处置

1. **生成措辞与呈现**：删除财政/军队/人物/关系/受理错误的描述句、摘要数字子串、prompt 词句、日志文字、年月呈现 helper、按钮说明/CSS/source 扫描。保留数值账本、状态、payload、callback、readonly/disabled 以及调用者提供的数据回显。
2. **内部形状与 helper 专测**：删除独立 settlementPresentation、ministerScrollLens、cliRunners、reasoningSupport Web helper 测试；必要契约迁入 MenuPage/ArchiveModal。删除纪年 formatter 专测与只剩复制/私有退役桥的 QA 文案文件；`_require_active_minister` 全仓搜索仅有定义，无生产调用，不能作为现役失败路径。
3. **真实入口迁移**：绑定走 `GameSession.prepare_rescript_prewrite`；高光走 `run_highlight_judge`；非法批红能力走 Web 提交并验 pending/choice/phase2 零调用；identity/person 恢复走 `reload_state_from_db`；固定财政流走 `apply_fixed_period_flows`；API key 拒绝走 `WebGame` 构造并验零 DB 创建；favorite phase 拒绝走 `api_remove_favorite`；closing 走真实开夜与 `WebGame.chat_stream`；问题惯性走 persisted issue 入口。
4. **失效与脆弱夹具**：删除重复遮蔽定义；played-save 依赖改为明确军队初值、真实到期密令、明确 legacy 污染后重开 `GameDB`。不再因 gitignored probe.db 的盘面缺项跳过这三案。非法 seed 在真实新档、同库零写和合法重试上验证，不为每个非法变体重建整档。
5. **保留依据**：判词 note.acceptedExemptions 明确认可调用方原文保真、正式目录、持久化枚举与键、日历标签、注入诊断标记、真实原件身份隐私负向。故原件隐私拒收继续保留；HTTP MIME/SSE、origin/source_id 协议与发行资源协议不按自由措辞处理。Electron medium CSS 是几何输入，不是截图像素锁。具体保留/变化声明均在成员表。

必要价值与成本：复用现有 fixture/入口，断言只落结构化结果或已裁认可的原件保真/隐私；迁移删除对应 helper 案，不叠加平行测试。不增加生产机读码、钩子、兼容层或通用机制。枚举只调用标准库 AST 和项目既有 TypeScript compiler，未自造解析器。

## J17 辨别力与变异真跑

`origin-mutation.log` 保存完整实测输出：

- 停用 `_validated_settlement_origin`，从基线加载的旧两案：`2 passed in 1.31s`，退出 0，证明旧前提被端点拒收遮住。
- 同一停用变异、当前合法端点两案：`2 failed in 0.18s`，退出 1；不再拒收非法来源，直接触发结构化拒收数量断言。
- finally 恢复原逻辑：`2 passed in 0.38s`，退出 0。

`load-phase-mutation.log`：同时停用 phase 写闸与 legacy load migration；现役 favorite 入口和真实重开案 `2 failed in 1.00s`；恢复后 `2 passed in 0.53s`。分别检出未拒绝写请求与污染 status/office 未恢复，不依赖人读错误句。

原件、类别、零副作用和合法批项没有删；真实人物 namespace、真实 pending/能力目录/数据行作为前提，避免用另一个非法条件代替目标失败。

## 验证（非全量）

所有本机 pytest/vitest/typecheck/变异命令均带：

```sh
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false MING_SIM_PI_BIN=/usr/bin/false
```

- Python：对 `git diff --name-only f21ce4d05` 中所有现存测试文件选取 120 文件，`python3 -m pytest <文件表> -q --tb=short -p no:cacheprovider`。`2509 passed in 81.63s`，EXIT 0，墙钟 82.27s。完整命令、实际输出在 `python.log`。随后唯一 Python 改动为删除 unused import，该文件补验 `4 passed in 0.72s`，在 `import-cleanup.log`。
- Web：13 个变化/关联文件，`npx vitest run --environment jsdom <文件表>`；`13 passed`、`254 passed`，EXIT 0，墙钟 4.51s，见 `web.log`。jsdom 仍提示 `Not implemented: navigation to another Document`，没有隐藏或据此改测试。
- TypeScript：`cd web && npx tsc --noEmit`，EXIT 0，见 `typecheck.log`。
- 变化 Python 作用域 Ruff `F401,F821,F811,F841`：`All checks passed!`，见 `lint.log`。全 tests 的附加扫描另有既存 256 告警，并非该聚焦 lint 的通过结论；不以此虚称全仓 lint 绿。
- `git diff --check` 通过。没有跑全量、真实模型或真实宿主验收；CI 的 Python/Web tsc/build 与本轮聚焦 vitest 不混称。

失败诚实：一次 Web 命令漏传 jsdom，114 failed/29 passed，属于错误调用；补正确宿主参数后如上通过。一次探索性迁移误把原件 source_id 套在聚合投影，5 failed/403 passed；真实读取证明 public_events 使用 projection ID，且判词已认可原件隐私负向，因此撤销该推断并保留原负向，未放松为“有数据即通过”。这些失败不属于基础设施失败。

## 范围、大小与未结项

相对 f21ce4d05 的测试 diff：148 文件、1273 insertions、7889 deletions（证据材料另计）；以纯删除为主。大范围来自派单要求继承 105 文件并完成整类扫类，不能拆成逐样本交卷冒称结类；必要迁移与成员账在本卷对应列明。不存在新生产机制。

J6/J17 本轮无未结施工项；保留项按上述裁决依据，不冒充删除。全量 CI、真实模型体验、合并/发版由后续车道/调用者执行，本腿不 push 或开 PR。既存 `.baseline/` 未动、未纳入提交。
