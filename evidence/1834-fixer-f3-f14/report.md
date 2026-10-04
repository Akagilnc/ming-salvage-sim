# #1834 修内司回执：F3 删除侧 KEEP_DELETED 9 纠正（相对 b6cd114f3）

依据：同树核验发现最新成员表 KEEP_DELETED 9 与源码不符。F14 本轮不处理。禁全量 / kill / stash / amend / rewrite / push / PR。未合并，不声称关票。

## 对本局纠正

`b6cd114f3` 表称 KEEP_DELETED **9**，与现行源码/夹具契约不符：

1. **i092** `test_player_payload_1022`：`payload == {…完整夹具…}` 实际已恢复；叠加结构断言与整包 equality 重复。本轮保留最短透明整包相等，删除冗余平行结构断言；表改 **RESTORE**。
2. **i121,124–130** `appDurableWiring` MIDCOURSE / SNAP_CLOSED / SNAP_ATTENDANT：旧表误判为「半程泄漏负向案」。旧源码注释「新月盘面可见半程局势（已非核账）」证明 MIDCOURSE 在结算完后应显示；SNAP_CLOSED 是上月已结快照应可见；SNAP_ATTENDANT 是上月固定夹具递话原样展示。不能以负向 `not.toContain(MIDCOURSE)` 顶替应显示的正向透明输送。本轮逐条核验夹具确经 `settlementBaseState` / `advancedState` / `last_attendant_message` 输入现行行为：补回仍缺的 5 条正向 `toContain`（i121/124/125/126/127）；i128–130 源码已有正向契约，仅表改 **RESTORE**。去掉为顶替被删正向新增的重复结构断言（`wang-settlement-slip` 顶替 MIDCOURSE）。
3. **#1849 注释**：最前仍写「不锁正文 / call-routing only」，但 mock 流字节「臣已入殿」断言已恢复——改为如实说明 mock 流透明输送。其它误称「非法 fixture / 不靠正文子串」的当前解释已删；历史输出文件未改写。

## 范围

- 比对基线：`52809cdf3`
- 删除侧成员：**175** → RESTORE **175** / KEEP_DELETED **0**
- F14：未触

### 原 KEEP_DELETED（9）→ 一律 RESTORE

| i | 位置 | 纠正 |
| --- | --- | --- |
| 092 | `test_player_payload_1022` 整包 `payload == {…}` | 已恢复；删冗余平行结构断言 |
| 121 | dismiss 后 `toContain(MIDCOURSE_ISSUE)` | 新月盘面正向；补回 |
| 124 | 核账期 `toContain(SNAP_CLOSED)` | 上月已结只读正向；补回 |
| 125 | closed_issues 末 `toContain(SNAP_CLOSED)` | 同上；补回 |
| 126 | gazette `toContain(SNAP_ATTENDANT)` | 递话原样；补回 |
| 127 | gazette 同屏 `toContain(SNAP_CLOSED)` | 上月已结同屏；补回 |
| 128 | attendant-only `toContain(SNAP_ATTENDANT)` | 源码已有；表改 RESTORE |
| 129 | 月完后 `toContain(MIDCOURSE_ISSUE)` | 源码已有；表改 RESTORE |
| 130 | 月完后 `toContain(SNAP_CLOSED)` | 源码已有；表改 RESTORE |

## 可复现命令

解释器：`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`
七 BIN（逐个设置）：

```bash
export MING_SIM_AGY_BIN=/usr/bin/false
export MING_SIM_CODEX_BIN=/usr/bin/false
export MING_SIM_CLAUDE_BIN=/usr/bin/false
export MING_SIM_CURSOR_BIN=/usr/bin/false
export MING_SIM_KIMI_BIN=/usr/bin/false
export MING_SIM_GROK_BIN=/usr/bin/false
export MING_SIM_PI_BIN=/usr/bin/false
export PYTHONDONTWRITEBYTECODE=1
```

### 聚焦测试（本轮触及面）

```bash
BASETEMP=$(mktemp -d /tmp/1834-f3-pytest-XXXX)
python -m pytest -q -p no:cacheprovider --basetemp="$BASETEMP" --tb=line \
  tests/test_player_payload_1022.py
# → 4 passed；见 focused-pytest-player-payload.txt
rm -rf "$BASETEMP"

cd web && npx vitest run --environment jsdom src/appDurableWiring.test.tsx
# → 见 focused-vitest-appDurableWiring.txt（56 passed）
```


## 证据文件

| 文件 | 作用 |
| --- | --- |
| `f3_deletion_side_member_table.md` | 175 条手读成员表（KEEP_DELETED→0） |
| `f3_deletion_side_members.jsonl` | 机器可读同表 |
| `focused-pytest-player-payload.txt` | player_payload 聚焦结果 |
| `focused-vitest-appDurableWiring.txt` | appDurableWiring 聚焦结果 |

## 复杂度 / 合法性

- 无新增机制、无生产出口改动；仅测试契约与证据表。
- F14 未碰。自查二连 done。

## 关票声明

分支未合并 → **不声称 #1834 关闭**。
