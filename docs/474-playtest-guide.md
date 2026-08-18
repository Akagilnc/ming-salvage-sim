# #474 试玩指引（旨意承诺与执行建制 · #570 族尾）

**核对日期：随 #570 HEAD 点核（本地日期 Asia/Tokyo）**

## 本指引是什么 / 不是什么

- **#474 族对象**：案卷 / 颁布关 / 批红三选 / 破格 / 中旨代价 / 执行格 / 月度进展 / 对账 / 认账。  
  呈现层 4.5 节奏与卷轴见 [`4.5-playtest-guide.md`](4.5-playtest-guide.md)——**两文互链，不吸并**。
- **已知债 = 现象 + 归属 issue**。不得加状态列、优先级、排期、勾选框。
- 本片闸级脚本与确定性夹具见下方「闸级命令」；引擎缺陷只记债，不在试玩指引里顺手改。

## 怎么用

1. 开一局 web 主路径：夜内下旨 → 收夜成案卷 → 月末过颁布关 → 打回则批红三选。
2. 按下方 beat 分母逐条比：预期机制长什么样 ↔ 现游戏长什么样。
3. 不符时先查「已知债」；未覆盖 → 记真问题（带案卷 id / 截图），勿把已知债误诊成新回归。
4. 对照真源：
   - ADR 0055 / 0056 / 0052 / 0066
   - #564 Implementation Decisions（代价轨机器契约）
   - 族尾 DoD：[`474-family-dod-570.md`](474-family-dod-570.md)
   - 0055 回注点核：[`570-adr0055-backref-checklist.md`](570-adr0055-backref-checklist.md)

---

## 逐条对照（#474 机制面）

格式：**预期 ↔ 现游戏 ↔ 若不符**。

### 1. 破格授阁臣

| 维 | 内容 |
| --- | --- |
| 预期 | 越级授阁臣必出现阻力之一：廷推卡/科参（颁布格打回＋`blocked_layer`∈{cabinet_drafting,palace_rescript,six_offices}）或辞让（强颁后执行格∈{degraded,failed}）。只读结构化格，不解析叙事。 |
| 现游戏 | 任免案卷进颁布判官；破格标 `break_rank` 确定性写入 payload；判决/执行格落 DB。闸：`scripts/family_tail_acceptance_570.py`。 |
| 若不符 | 闸红 → 记债（判官口径 / 执行格）；本片不改引擎。 |

### 2. 白身破格授巡抚

| 维 | 内容 |
| --- | --- |
| 预期 | 打回，**或**强颁且代价三笔按 #564 落齐（皇威扣流水、typed signed satisfaction direction×intensity、中旨标记；零反应不入清单）。 |
| 现游戏 | 白身→巡抚 `break_rank.is_break_rank=true`；强颁走 `apply_dossier_promulgation(..., force_promulgated)`＋`decree_cost_events`。 |
| 若不符 | 顺颁且零代价 → 闸红记债。 |

### 3. 中旨强授 / 批红三选

| 维 | 内容 |
| --- | --- |
| 预期 | 打回→批红三选（强颁/收回/留中）；预先中旨 mode=中旨入判；「中旨亦不可颁」禁用强颁。 |
| 现游戏 | #563 批红页 + #564 代价；S10 路径由族尾闸复验。 |
| 若不符 | 选项缺失/代价漏笔 → 归 #563/#564 债。 |

### 4. 中旨螺旋（验收证据，非生产机制）

| 维 | 内容 |
| --- | --- |
| 预期 | 同盘面配对：强颁流水 3 次 vs 0；判官顶回倾向前者可观察更强（精确双侧配对符号检验 α=0.05）。**不得**在生产码加中旨阈值/计数闸/棘轮。 |
| 现游戏 | 判官输入 `promulgation_history` 已含批红强颁标记；闸：`scripts/midzhi_spiral_judge_gate_570.py`。 |
| 若不符 | 闸红 → 记债（判官对历史标记不敏感）；禁止用生产棘轮「修」闸。 |

### 5. 月中 restore

| 维 | 内容 |
| --- | --- |
| 预期 | 案卷（状态机+两格+判据快照）/ 月度进展档 / 中旨与破格标 / 参与人名单 四面无损接续。名单＝案卷参与人（0053）。 |
| 现游戏 | `db.backup_to` 热备；确定性夹具 `tests/test_family_tail_restore_570.py`。 |
| 若不符 | 缺面 → 记债，不扩片修其它 restore。 |

### 6. P4 新数据面

| 维 | 内容 |
| --- | --- |
| 预期 | 卷轴/判官清单/批红页/起居注/认账 brief 等确定性面不露系统枚举与人物轴裸数；邸报/密奏/召对回话 LLM 面同。 |
| 现游戏 | 确定性：`tests/test_p4_guard_new_surfaces_547.py`（本族夹具扩写）；LLM 面：族尾闸级脚本扫真实渲染产物。 |
| 若不符 | 人物/国势裸分 → #347；案卷系统词裸露 → 记本族债。 |

---

## 闸级命令与证据路径

```bash
# 验收锚（破格阁臣 / 白身巡抚 / 中旨路径 / P4 LLM 面扫）
# 形制四参：--runner/--model/--samples/--output；本片证据跑次用 claude（codex 额度耗尽）。
MING_SIM_TRACE_PATH=/tmp/issue-570-acceptance-trace.jsonl \
  python scripts/family_tail_acceptance_570.py \
    --runner claude --model claude-opus-4-6 --samples 1 \
    --output docs/evidence/issue-570-acceptance-anchors.json

# 中旨螺旋对照（默认 samples=12，下限 6）
MING_SIM_TRACE_PATH=/tmp/issue-570-spiral-trace.jsonl \
  python scripts/midzhi_spiral_judge_gate_570.py \
    --runner claude --model claude-opus-4-6 --samples 12 \
    --output docs/evidence/issue-570-midzhi-spiral.json
```

退出码即闸。证据 JSON 含 method / summary / limitations / raw trace。

确定性夹具：

```bash
python -m pytest tests/test_family_tail_restore_570.py tests/test_p4_guard_new_surfaces_547.py -q
```

---

## 已知债清单（试玩者读物）

> 每条：现象 + 归属。无状态/排期/勾选。交付前当场核实现象仍复现；核不出则删。

### 1. 国势/地区抽象分回流面仍裸露

- **现象**：HUD / 地图 / 效果句 / CLI / 扮演 context 仍见民心·皇威等 0–100 裸分或 `民心+N` 增量。
- **归属**：#347
- **证据**：见 [`4.5-playtest-guide.md`](4.5-playtest-guide.md) 债 1–6 与 [`347-score-seam-enumeration.md`](347-score-seam-enumeration.md)。

### 2. 中旨螺旋是验收证据不是生产机制

- **现象**：生产路径**没有**「中旨次数阈值自动顶回」；顶回强弱完全依赖判官读 `promulgation_history`。试玩若期望「第三次必卡」会落空。
- **归属**：PRD #556 OOS「中旨闸量化」（显式不在本族）
- **证据**：Court pin P-4；`scripts/midzhi_spiral_judge_gate_570.py` 文档串。

### 3. 中旨螺旋闸级对照当前未达 α=0.05

- **现象**：`scripts/midzhi_spiral_judge_gate_570.py` 在 live 模型上跑配对符号检验——边际行政中旨时 discordant 过少；略加强程序绕开措辞后两端同向饱和（12/12 均打回），`p_value_two_sided=1.0`，闸退出码 1。方向/机制未造生产棘轮。
- **归属**：#570（本族尾闸红；判官对 `promulgation_history` 强颁标记的可观察敏感性不足，属验收债，不在本片改 prompt/引擎）
- **证据**：`docs/evidence/issue-570-midzhi-spiral.json` → `summary`（`hist3_rejections`/`hist0_rejections`/`p_value_two_sided`/`passed`）。

---

## 相关入口

- 4.5 呈现试玩指引：[`4.5-playtest-guide.md`](4.5-playtest-guide.md)
- 全族 DoD 点检：[`474-family-dod-570.md`](474-family-dod-570.md)
- 0055 回注点核：[`570-adr0055-backref-checklist.md`](570-adr0055-backref-checklist.md)
- ADR 0055 / 0056 / 0052 / 0066
