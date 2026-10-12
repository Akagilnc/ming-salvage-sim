# 玩家过月结算流程

Web 颁诏与退朝共用 `GameSession.resolve_turn → decree.resolve_directives → month_chain.run_player_month_chain`。分段过月的决定见 [ADR 0157](adr/0157-v2-month-waits-for-exhausted-model-call-recovery.md)，步骤及恢复契约以 #1861／#1843／#1846／#1847／#1862／#1845 现行票面为准；下列是当前实现的调用顺序。

1. Web 入核账期取得月初展示快照，在写闸外等待召对转译并收夜；转译／预推及未完机械尾接回既有写队列屏障。`prepare_resolve_front_half` 将 `pre_settle` 与本月诏书的 resolve context 同事务提交：暂存动作落库、固定财政流水、在途抵达、密令到期戳。恢复读取已提交的前半段，不重复扣账。
2. 月链先消费已答批红，再按旨序核算：夜里已有声明直接消费，未预推的旨经 `decree_forecast` 同口补跑。效果经 `declaration_dispatch → settlement.settle_delta` 落账，段序见 `settlement/registry.py`，拒收以 `RejectedItem` 留痕。逐段已落结果供召旨赴京结清及暗渠揭破待办；检举入库后再扫描待办。逐旨后由 `_consume_event_gates_after_edicts` 消费世界事件判门，再推演、转译和提交世界段的问前部分。
3. 拟批红奏疏并汇入同一案头；有未答请旨或打回项则停在批红，不推进月份。每道请旨的每个票拟选项分别预推一份，暂存不落账，不枚举答复组合。皇帝答一道即取用该道结果续推并落声明，不等其他请旨；各道续推可并行，未答项保持待裁。选中项仍在跑则接着等；预推失败按未预推现跑，现跑失败走原月链恢复。已落的问前和问后效果不重落；新请旨仍回同一案头。全部批红和效果落定后，整月密报供料依次办理密奏、披露、执行态和到期结案，再做月末漂移及持久态揭破待办扫描，包括无效果月。
4. 邸报作者一次产标题与正文并归档，随后才判结局、推进月份。同一推进事务标记 closed turn 的机械尾待办；关系／派系酿制和结局总评经 `SessionWriteQueue` 后台执行，未完态持久化，重开续接、下次过月前等待。无旨月走相同主链。史册诏书读 resolve context。

每段的提交与续跑状态由 `month_chain.py` 管理；事务、拒收见 `ming_sim/applier.py`，错误包见 `ming_sim/error_pack.py`，效果字段见 [DELTA_SCHEMA.md](DELTA_SCHEMA.md)。逐旨预推、世界段及邸报作者按各自可见范围读取 `materials.py` 的目录，API 工具和宿主 CLI 工作目录读同一棵材料树。

请旨机标用于逐旨及世界段的暂停与结构化交接，不从邸报正文抽决策块。核账递话与入口关闭理由（含待批期）是界面固定提示，不是人物对话。

模型耗尽与代码异常由月链持久失败状态保留真因；已接通的过月调用恢复在界面原位给提示与重试入口，不重落已提交的段。夜里预推重试尚无 Web 请求入口：现有重试回到过月入口，仍会被有效预推失败挡住；`retry_failed_decree_forecast` 保留待接，缺口及接线归属见 [#1873 评论 6105940701](https://github.com/Akagilnc/ming-salvage-sim/issues/1873#issuecomment-6105940701)。后台机械尾失败留在自己的未完态，不冒充月链调用失败。
