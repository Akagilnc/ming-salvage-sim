# M0 状态完整性内审结论（#73 收口）

Status: Proposed（内审结论 doc。**线上对抗验证（2026-06-15，6 红队 + 综合裁决）复核 = close_conditional**：Q4 真 done；Q1/Q3 有代码实证缺口；关 #73 会清空 M0 milestone + 孤儿化 C4/C5——故 **#73 宜保持 open 作 rollout 伞、勿直接关**。**Q3 契约裁断已拍（用户 2026-06-15）= fail-loud**（见残留 4）→ **M0 设计面 100% 冻结、无设计残留**，剩纯编码 rollout。待用户拍 rollout 优先级。）

`#73`（M0 总控内审）要求产「一份短文档或 ADR，回答 5 个契约问题」，并冻结「LLM 输出 → extractor → 事件触发 → apply/settlement → DB 落库 → 下回合读取」这条链路的 fail-loud / 事务 / 状态契约。

**本 doc 即该内审的结论**。结论是：**#73 的 5 个问题在 issue 创建（2026-06-08）之后，已被 ADR 0005 / 0008 / 0009 + `trigger_gate` 实装逐条答完**——`#73` body 的「架构内审候选清单」自己已标注 C2=问题 1/4、C1=问题 2。故本 doc **不产新决策**，只做两件事：① 把 5 问映射到已冻结的真源（带 file:line 证据）；② 列出真正的残留（纯 M1 编码，非设计）。

## 5 问 → 已冻结答案（证据）

| #73 问题 | 答案真源 | 证据 |
|---|---|---|
| **Q1** 哪些错误必须 raise/rollback；哪些 warning 但要 surface | **ADR 0008 决定 1 + 5**（承 ADR 0005 fail-loud 分流）：LLM 脏数据（幻觉 id/枚举非法/引用不存在实体）= 逐项拒收留痕、坏项不带走整批；代码异常（KeyError/schema 漂移）= **上抛绝不吞**。拒收落结构化行（turn/section/item/原因/类别/source），DB 为分析真源，按 `source` gate 玩家可见性 | `applier.py:240` `RejectionCollector`；`decree.py:932/1104` 接线；ADR 0008 决定 1/5 |
| **Q2** 人物 4 key 是否合并为单一 `人物变更` + alias 怎么留 | **ADR 0003（决策）+ ADR 0009（实现契约）**：合并为单 key `人物变更`、每项显式 `动作` ∈ 7 枚举（任命/罢黜/调任/处置/易主/册封/行止），单管线按动作分发、未知动作响亮拒收；旧 4 key 留作 alias 兼容层 | `simulation.py:28/425`（新 key 优先 + legacy alias）；`issues.py:2165`（新>旧 fallback）；ADR 0009 accepted（PR #94） |
| **Q3** `trigger_gate` 如何接入历史事件 + 缺字段 fail-loud | **已实装**：历史事件（`trigger_year>0`）进候选池须**双门**——时间窗 `_event_window_open` + 结构化前提门 `_gate_passed`（条件 dict，支持数值比较 + 文本相等）。#12 毛文龙误触发已 S3 修 | `issues.py:155`（时间窗）/`:278`（`_gate_passed`）/`:317`（gather 双门） |
| **Q4** apply 是 validate-all-then-mutate 还是事务包裹 rollback | **ADR 0008 决定 2/3**：**事务包裹**（`atomic_and_reload` 整包推进回合的写路径，全有或全无）+ 前置 `validate_delta_shape` 防畸形入库。明文「否决 validate-all 不上事务（挡格式错挡不住写一半真异常）」。#3 已 CLOSED | `decree.py:941`（atomic_and_reload）；`issues.py:2164`（validate_delta_shape）；ADR 0008 决定 2/3 |
| **Q5** #14/#13/#12/#3 修复顺序 + PR 切片 | **#73 候选清单推荐顺序 + ADR 0008 实施波次**：C2 契约（ADR 0008）→ C1 旗舰 adapter（ADR 0009，载体 #13）→ C4 与财政线对齐 → C5 web 记账；ADR 0008 波次 = PR1 ✅ / PR2（#91）/ 后续 sections | ADR 0008 实施波次；#73 候选清单推荐顺序 |

## 真正的残留 = M1 编码（非设计）

#73 的**设计交付物**（内审契约 doc）= 本结论，已完成。真正未完的是 **ADR 0008/0009 契约的分波 rollout**——纯编码，按 [[design-vs-coding-session-split]] 应 spawn 隔壁 coding session：

1. **ADR 0008 PR2（#91，OPEN）** — 2 个整段吞（power×2）+ 4 个裸奔段迁入 adapter 契约 + provenance 字段灌注。
2. **ADR 0008 后续 sections** — 其余 section 迁契约；尤其 **#14 A 类「畸形→continue 丢弃」**（`simulation.py:750`/`795`/`844`/`468` 的 `_clean_*` / `_ongoing_effects_to_economy`，delta `int()` 失败凭空丢笔）；**legacy 路（simulator / driver）未接 `RejectionCollector`**（`applier.py:240` 现仅 `settle_with_delta` 路接入）。
3. **C1 人事 applier 实现（#13 载体 / #97 追踪）** — ADR 0009 契约 → 代码；含 **C3** `db.py` `_commit_office_action` 分层倒置搬家（ADR 0009 决定 6 已在契约层判死 lazy import）。
4. **✅ Q3 第二半契约已冻结（用户 2026-06-15 拍 = fail-loud）→ 转编码** — 「`trigger_gate` 缺字段/字段写错时如何 fail-loud」。对抗验证已**代码实证**：坏/拼错的 gate 条件现在**静默当「条件不满足」**，既不 raise 也不 log——`issues.py:194`（未知 metric_key → `return None`）→ `:302`（`val is None → return False`）；`:298`（坏比较语法 regex 不匹配 → `return False`）；`models.py:131` `trigger_gate: Dict[str,str]` 纯 dataclass、content 加载期零 schema 校验。**这违 ADR 0005「schema 不符=必须响亮、绝不吞」**。**裁断（已拍）：坏/拼错的 gate 条件 = fail-loud**（未知 metric_key / 非法表引用 / 坏比较语法 → 报错或拒收留痕，符 ADR 0005）；**保留区分**：合法但「条件未满足」仍正常 `return False`（不报错）——只对**畸形**条件响亮。**实装是 bug、归 #12 编码修**（契约见 #12 评论）。M0 设计层至此无残留。

5. **Q1 契约对真 apply 路失明（编码 rollout，已实证活着）** — `flows.py:291-296` `_apply_economy_list`：非法 account（`not in 国库/内库`）/ 坏 int 全 `continue` 静默丢、零拒收留痕（docstring 明写「退化为常规扣账」）；`issues.py` world_advance 纯透传无 apply 无 reject。ADR 0008 实施波次已把 flows 列「候选 4 后续」，故属已知编码 rollout——但验证确认此刻是**活的静默丢**，rollout 时优先。

## Consequences

- **M0 的设计/契约面 100% 已冻结**（ADR 0005/0008/0009 + trigger_gate 接入 + Q3 fail-loud 裁断已拍）——**无任何待决策设计残留**。
- 推进财政基座 port（#65/#66）所依赖的「M0→M1 重构完成」前置，**设计部分已全部就绪**；主卡点纯转为 M1 rollout 编码（#91/#14/#13/#97/#12 + flows economy 静默丢）的执行，由编码 session 按用户优先级推进。
- **#73 保持 open 作 rollout 伞**：关闭会清空 M0 milestone（#73 是该 milestone 唯一 open issue）并孤儿化 C4（flows.py golden 测试）/C5（web TestClient 测试）——二者无独立 tracking issue，C4 原计划吸收方 #66 已 CLOSED 未捎带。关 #73 前须先为 C4/C5 建 tracker 或显式 defer 留痕。
- 本 doc 无新契约 → 不引入「与 0008/0009 平行的第二套契约」（避免 over-build）；唯一新增 = Q3 裁断点的标注（待拍）。
