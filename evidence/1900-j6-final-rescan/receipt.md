# #1900 修内司回执 — J6 final rescan

## 授权
- 用户本席劳务：仅未结 J6 apply；末份判词 `07-1900-judge-23ea8ed38.json`
- 不猜新设计；不改宿主配置席位；不 stash/amend/rewrite/push/PR

## 施工前自审
- 类边界按末份：`清理盯文与内部证明时，遗漏或弱化了必要失败行为、原故障来源及实际结果的辨别力`
- 不得以扩大 raises 关键词数量／点名白名单归零代替语义处置
- 官方能力先查：pytest ExceptionInfo / 对象身份（docs.pytest.org）；不新增生产钩子

## 分支 / commit
- 分支：`ak-roles/1900-j6-final-rescan-23ea8ed38`
- commitSha：`7ed27ea11dc23550d1bcdbc2a99e634713565f71`

## 枚举
- 命令：`python3 evidence/1900-j6-final-rescan/j6_enum.py`
- 谓词：WEAK_DIAG | HELPER_WEAK_RAISE | MOCK_CALL_ORACLE | PRIVATE_MARKER | JUDGE_SAMPLE | SECONDARY/ASYNC raises 复扫
- 扫描测试文件 248；命中 99；core=25
- 成员表：`j6-members.md`；候选：`j6-candidates.jsonl`；处置：`j6-disposition.jsonl`

## 本轮语义处置（施工）
1. **FIX** `test_run_backend_for_config_traces_on_backend_error`：`trace.error == str(injected)` + 异常对象身份
2. **FIX** `test_worker_postprocess_exception_emits_error_end`：SSE `message == str(postprocess_error)`（Thread+Event 等实际 worker）
3. **DELETE** `test_seed_founding_write_does_not_swallow_execute_error_with_bad_rollback`（FakeDB helper 伪证；非必要闸负向）
4. **FIX** `test_mechanical_tail_missing_llm_config_surfaces_retry`：绑定真实首故障「结局总评缺少模型配置」（本案带 ending_outcome）

其余成员逐项 KEEP（见处置表；含 PRIVATE_MARKER 误伤、结构化主契约辅 message、调用即外部契约等保留依据）。

## 聚焦测试
........                                                                 [100%]
8 passed in 1.07s
real 1.51
user 1.16
sys 0.26

## 变异
cli_trace_error: RED_OK
cli_trace_error: GREEN_OK
sse_postprocess_message: RED_OK
sse_postprocess_message: GREEN_OK
mechanical_tail_error: RED_OK
mechanical_tail_error: GREEN_OK
all_ok=True
方法：只替换生产失败分支上的诊断赋值（`error = str(exc)` / SSE message / mechanical_tail error）；强断言红；恢复绿。不新造证明测试。

## 原范围复扫
- 判词三样本已处置；上轮误留 seed KEEP_NO_SWALLOW_SEAM 已删除
- 不复制旧分类误判；处置按「可见诊断是否绑定原故障来源」

## 未结（如实）
- 本席不声称 J6 已由大理寺结清；交卷待庭审
- 不声称已 merge / 关票
- J21 等其它类别本轮未授权重开
