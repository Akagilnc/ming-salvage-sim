# 玩家过月结算流程

玩家颁诏与退朝共用 `GameSession.resolve_turn → decree.resolve_directives → month_chain.run_player_month_chain`。分段过月的决定见 [ADR 0157](adr/0157-v2-month-waits-for-exhausted-model-call-recovery.md)，步骤及恢复契约以 #1843／#1846／#1847 现行票面为准。

1. 收夜、单写者屏障后，`prepare_resolve_front_half` 提交 `pre_settle` 与本月诏书的 resolve context。`pre_settle` 包含固定财政流水、事件终态、硬立局势与密令到期戳；恢复时不重复执行已提交的前半段。
2. 月链按旨序消费夜里暂存声明；效果经 `declaration_dispatch → issues.apply_score_extraction` 落账，拒收留痕。逐段已落结果供召旨赴京结清及暗渠揭破待办；检举入库后再扫描待办。随后世界段推演、转译和提交。未完成请旨停在批红，答复后续跑而非重落问前效果。
3. 全部逐旨和世界段（含问后）落定后执行整月密报供料；密奏先于披露、执行态先于到期结案。月末漂移按持久态再扫描一次揭破待办，包括无效果月。邸报归档后才判结局和推进月份；无旨月也走同一链，不作快跳。
4. 机械尾关系／派系酿制和结局总评经 `SessionWriteQueue` 在 closed turn 后台执行；未完态持久化，下次过月前屏障等待。史册诏书由 resolve context 读取，非已退役的旧回合抽取表。

每段的提交与续跑状态由 `month_chain.py` 管理；事务、拒收和错误包分别见 `ming_sim/applier.py`、`ming_sim/error_pack.py`。月末效果的字段契约见 [DELTA_SCHEMA.md](DELTA_SCHEMA.md)。不再调用已删除的对话探针驱动或旧结算后半段。
