# #1900 修内司回执 — J6 N2 rescan (a7646b02e)

## 分支 / commit
- 分支：`ak-roles/1900-j6-n2-rescan-a7646b02e`
- commitSha：`80f05b1c1384c8fd1f38c9298b05b38cad2ed25c`

## 授权
- 仅未结 J6 apply；判词 `1900-judge-a7646b02e.json`
- 不猜新设计；不改宿主配置席位；不 stash/amend/rewrite/push/PR

## 类边界（全文，未收窄）
必要失败行为、原故障来源与实际结果的证明遗漏，以及修理新增的非契约文字锁。

## 方向
区分诊断来源保真与固定字句；不能只凭无关诊断替换报红就结清修法。
复用或修改既有最短真实行为案；删除非契约措辞锁；不得以非空/状态断言替代必要结果；
不机械要求所有异常案检查身份；不另造生产机制/钩子/平行证明。

## 枚举
- 命令：`python3 evidence/1900-j6-n2-rescan/j6_enum.py`
- 谓词形状：S_ERR_EXIT | S_HTTP_DIAG | S_PROD_WORDING | S_NONEMPTY（覆盖边界全文）
- 成员表：`j6-members.md`；摘要：`j6-enum-summary.json`

## 处置
1. **FIX** `test_spawn_pending_write_thread_start_failure_releases_ownership`
   - 补 error→end；`message == str(start_error)`；保留 pending 释放
2. **FIX** `test_real_no_edict_entries_roll_back_every_external_state_after_fiscal_write`
   - web：`detail.message == str(fiscal_fault)`；cli：异常对象身份；保留回滚
3. **FIX** `test_mechanical_tail_missing_llm_config_surfaces_retry`
   - 删除生产中文等值锁；包装真实缺配置路径；绑定 `str(captured)` + LLMUnavailable/stage/code；保留失败+重试
4. **KEEP** `test_hot_replace_http_failure_keeps_old_state_and_writes_usable`
   - 契约=旧局可写/turn 保真；诊断面非本案必要结果

前份 CLI trace／SSE／seed helper 处置维持，不据此另开。

## 聚焦测试
6 passed in 1.07s（含三样本 + postprocess error 案 + brew failure 案）
见 `focused-tests.log`

## 变异（装回旧逻辑/无关诊断 → 红；同义生产文案 → 绿；恢复 → 绿）
- mut1_swallow_start: RED_OK / restore GREEN_OK
- mut2_unrelated_http: RED_OK / restore GREEN_OK
- mut3_synonym_prod_msg: GREEN_OK（来源保真，非措辞锁）
- mut4_unrelated_store: RED_OK / restore GREEN_OK
- all_ok=True
见 `mutations-summary.txt` / `mutations.txt`

## 未结（如实）
- 本席不声称大理寺已结清 J6；交卷待庭审
- 不声称已 merge / 关票
