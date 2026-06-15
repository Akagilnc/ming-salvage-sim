# M0 状态完整性内审结论（#73 收口）

Status: Proposed（内审结论 doc。**cmr 复核（2026-06-15，Claude+codex；gemini 配额降级『本轮缺 gemini』）= close_conditional**：Q4 真 done；Q1/Q3 有代码实证缺口、且部分实装未完（见下）；关 #73 会清空 M0 milestone + 孤儿化 C4/C5——故 **#73 宜保持 open 作 rollout 伞、勿直接关**。**Q3 契约裁断已拍（用户 2026-06-15）= fail-loud**（见残留 4）→ **M0 的契约/设计裁断已全部冻结**，剩纯编码 rollout（含 #12 的 gate 数据 authoring + metric_key 校验）。待用户拍 rollout 优先级。）

`#73`（M0 总控内审）要求产「一份短文档或 ADR，回答 5 个契约问题」，并冻结「LLM 输出 → extractor → 事件触发 → apply/settlement → DB 落库 → 下回合读取」这条链路的 fail-loud / 事务 / 状态契约。

**本 doc 即该内审的结论**。结论是：**#73 的 5 个问题在 issue 创建（2026-06-08）之后，其契约/设计裁断已被 ADR 0005 / 0008 / 0009 + `trigger_gate` 机制逐条覆盖**（部分已实装完成、部分仍待编码 rollout——下表逐条标）——`#73` body 的「架构内审候选清单」自己已标注 C2=问题 1/4、C1=问题 2。故本 doc **不产新契约**，只做两件事：① 把 5 问映射到真源（带 file:line 证据，并区分「设计冻结」vs「实装未完」）；② 列出真正的残留（纯 M1 编码，非设计）。

## 5 问 → 已冻结答案（证据）

| #73 问题 | 答案真源 | 证据 |
|---|---|---|
| **Q1** 哪些错误必须 raise/rollback；哪些 warning 但要 surface | **ADR 0008 决定 1 + 5**（承 ADR 0005 fail-loud 分流）：LLM 脏数据（幻觉 id/枚举非法/引用不存在实体）= 逐项拒收留痕、坏项不带走整批；代码异常（KeyError/schema 漂移）= **上抛绝不吞**。拒收落结构化行（turn/section/item/原因/类别/source），DB 为分析真源，按 `source` gate 玩家可见性 | `applier.py:240` `RejectionCollector`；`decree.py:932/1104` 接线；ADR 0008 决定 1/5 |
| **Q2** 人物 4 key 是否合并为单一 `人物变更` + alias 怎么留 | **ADR 0003（决策）+ ADR 0009（实现契约）**：合并为单 key `人物变更`、每项显式 `动作` ∈ 7 枚举（任命/罢黜/调任/处置/易主/册封/行止），单管线按动作分发、未知动作响亮拒收；旧 4 key 留作 alias 兼容层 | `simulation.py:28/432`（新 key 优先 + legacy alias）；`issues.py:2165`（新>旧 fallback）；ADR 0009 accepted（PR #94） |
| **Q3** `trigger_gate` 如何接入历史事件 + 缺字段 fail-loud | **机制 plumbing 已实装、Mao 真修 + fail-loud 缺口未完**：历史事件（`trigger_year>0`）进候选池须**双门**——时间窗 `_event_window_open` + 结构化前提门 `_gate_passed`。但 ⚠️ `mao_wenlong` 本身**没有 trigger_gate**（只 trigger_year/month + 人读 precondition）→ #12 的 Mao 真修（给事件 author gate + 状态前提）**未做、#12 仍 OPEN**；缺字段 fail-loud 见残留 4 | `issues.py:155`/`:278`/`:317`（双门 plumbing）；`content/events.json` mao 无 trigger_gate |
| **Q4** apply 是 validate-all-then-mutate 还是事务包裹 rollback | **ADR 0008 决定 2/3**：**事务包裹**（`atomic_and_reload` 整包推进回合的写路径，全有或全无）+ 前置 `validate_delta_shape` 防畸形入库。明文「否决 validate-all 不上事务（挡格式错挡不住写一半真异常）」。#3 已 CLOSED | `decree.py:941`（atomic_and_reload）；`issues.py:2164`（validate_delta_shape）；ADR 0008 决定 2/3 |
| **Q5** #14/#13/#12/#3 修复顺序 + PR 切片 | **方向有、落地优先级未定（待用户拍）**：#73 候选清单序 C2（ADR 0008）→ C1（ADR 0009，载体 #13）→ C4 → C5 + ADR 0008 波次 PR1 ✅/PR2（#91）/后续。⚠️ 此为架构候选粒度，**未给 `#14/#13/#12/#3` 逐 bug 的成文 PR 切片、#12 未列入序**——rollout 优先级仍待用户拍（见 Consequences） | ADR 0008 实施波次；#73 候选清单 |

## 真正的残留 = M1 编码（非设计）

#73 的**设计交付物**（内审契约 doc）= 本结论，已完成。真正未完的是 **ADR 0008/0009 契约的分波 rollout**——纯编码，按 [[design-vs-coding-session-split]] 应 spawn 隔壁 coding session：

1. **ADR 0008 PR2（#91，OPEN）** — 2 个整段吞（power×2）+ 4 个裸奔段迁入 adapter 契约 + provenance 字段灌注。
2. **ADR 0008 后续 sections** — 其余 section 迁契约；**#14 A 类「畸形→continue 丢弃」的真活点** = `simulation.py:468`（`_ongoing_effects_to_economy` 坏 int→continue）+ economy 路（`_clean_economy_moves` `simulation.py:735/750` + `flows.py:291` `_apply_economy_list`，非法 account/坏 int→continue 零留痕）。⚠️ 原列的 `simulation.py:795/844`（`_clean_fiscal_*`）**已于 cmr S3 改为坏串透传给 applier 拒收、不再静默丢，已剔除**。另 **legacy 路（simulator/driver）未接 `RejectionCollector`**（`applier.py:240` 现仅 `settle_with_delta` 路接入）。
3. **C1 人事 applier 实现（#13 载体 / #97 追踪）** — ADR 0009 契约 → 代码；含 **C3** `db.py` `_commit_office_action` 分层倒置搬家（ADR 0009 决定 6 已在契约层判死 lazy import）。
4. **✅ Q3 第二半契约已冻结（用户 2026-06-15 拍 = fail-loud）→ 转编码** — 「`trigger_gate` 缺字段/字段写错时如何 fail-loud」。对抗验证已**代码实证**：坏/拼错的 gate 条件现在**静默当「条件不满足」**，既不 raise 也不 log——`issues.py:194`（未知 metric_key → `return None`）→ `:302`（`val is None → return False`）。**load 期已有部分校验**（`content.py:106` 验比较式语法 `^(>=|<=|>|<|==)\s*-?\d+$`、坏语法 `raise SystemExit`——故「坏比较语法」这一类**已 fail-loud**，修正初稿「零 schema 校验」之误）；剩缺口：① **未知/拼错 metric_key 不校验**（load 不查 key、eval 期 `:194/:302` 静默坍缩成 `return False`）；② **文本相等 gate load/runtime 不一致**（`_gate_passed` runtime 支持 `==文本`，但 `content.py:106` 只放行数值比较式、文本 gate 会被 load 拒）。**裁断（已拍）：畸形 gate 条件 = fail-loud**（未知 metric_key / 非法表引用 / 坏比较语法均报错或拒收，符 ADR 0005）；**保留区分**：合法但「条件未满足」仍正常 `return False`、只对畸形响亮。**trigger_gate 错属静态 content schema 错**（非 ADR 0008「LLM 脏数据 vs 代码异常」二分）→ fail-loud 由 ADR 0005 直接覆盖、宜走 **load-time 校验**（content.py，已部分）、**不走 `RejectionCollector`**（那条是 LLM-delta 专用）。落实属编码、归 #12（补 metric_key load 校验 + 修 eval 期 None 坍缩 + 决文本相等 load/runtime 取舍）；契约见 #12 评论。

5. **Q1 契约对真 apply 路失明（编码 rollout，已实证活着）** — `flows.py:291-296` `_apply_economy_list`：非法 account（`not in 国库/内库`）/ 坏 int 全 `continue` 静默丢、零拒收留痕（docstring 明写「退化为常规扣账」）；`issues.py` world_advance 纯透传无 apply 无 reject。ADR 0008 实施波次已把 flows 列「候选 4 后续」，故属已知编码 rollout——但验证确认此刻是**活的静默丢**，rollout 时优先。

## Consequences

- **M0 的契约/设计裁断已全部冻结**（ADR 0005/0008/0009 + trigger_gate 机制 + Q3 fail-loud 裁断已拍）——**无待决策的设计残留**。但「设计冻结」≠「实装完成」：Q3 的 Mao gate authoring + metric_key 校验、Q1 的 economy 静默丢，均属未完的编码 rollout。
- 推进财政基座 port（#65/#66）所依赖的「M0→M1 重构完成」前置，**设计部分已全部就绪**；主卡点纯转为 M1 rollout 编码（#91/#14/#13/#97/#12 + flows economy 静默丢）的执行，由编码 session 按用户优先级推进。
- **#73 保持 open 作 rollout 伞**：关闭会清空 M0 milestone（#73 是该 milestone 唯一 open issue）并孤儿化 C4（flows.py golden 测试）/C5（web TestClient 测试）——二者无独立 tracking issue，C4 原计划吸收方 #66 已 CLOSED 未捎带。关 #73 前须先为 C4/C5 建 tracker 或显式 defer 留痕。
- 本 doc 无新契约 → 不引入「与 0008/0009 平行的第二套契约」（避免 over-build）；唯一新增 = Q3 裁断（已拍 = fail-loud）+ trigger_gate 错的归类说明（残留 4）。
