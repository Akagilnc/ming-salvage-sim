#1835 续修：cutover 旧路 + S3 helper-only

## 旧档财政／人口（含 cutover）
谓词：`is_army_pay_source_cutover_enabled` 生产分流、cutover-off 写路、旧迁移、死壳。
命令：`rg is_army_pay_source_cutover_enabled ming_sim tests`
修复：方法恒 True；删 cutover-off owner/arrears 标量旁路；conservation/settle 恒走双累加器；migrate noop；economy 恒 reconcile；flows 缺基座 fail-loud；删 POPULATION_UNIT_WAN/scale/_content_population/_HUANG_TIAN/_FIXED_FLOW；删 pre_s6/v8 旧迁移案与 _disable helper。
原生：无标 reopen → cutover True；army_delta.arrears+4 写入 central 累加器。

## S3
删除：qa_d1 helper-only is_non_person + DEFAULT_TIME_OF_DAY 锁；army_display helper 对照 arrears_text；player_army six_tier helper 表；population unmarked 纯 property 案。
