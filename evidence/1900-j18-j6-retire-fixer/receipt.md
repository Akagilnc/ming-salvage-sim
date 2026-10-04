# #1900 修内司施工回执（证据纠正轮：J18 复扫 + J6 语义处置）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1900-w5`
分支：`ak-roles/1900-j18-retire-revoked-mechanisms`
既存 `?? .baseline/` 未动；无 stash / amend / rewrite / push / PR。

未结类别以末份判词 continue payload 为准：J18（P1）、J6（P2）。
本轮针对复核：假枚举命令、/tmp 脚本不可核、2886 机器 retain、无信号当免责。

---

## 1. J18

### 复扫

见 `j18-behavior-rescan.txt`：生产+测试对已撤销符号空；仅 `DELTA_SCHEMA` 退役标题。

### 实况 / 奏报职责

`materials.grant_route_reader_facts` / `_escort_identity_lines` 仍按身份区分实况读者与奏报原文；`escorted` 本切片恒假（专用账本已退役，非另造替代机制）。沿已署票面：原则保留，专用账本配套已去。有护核账接续归 #1873 / 家族收尾。

---

## 2. J6 证据纠正 + 语义删修

### 可重跑机械命令（本工作树证据目录）

见 `j6-enum-cmd.txt`：

- `j6_enumerate_universe.py` → `j6-universe.jsonl`
- `j6_flag_structural_candidates.py` → `j6-structural-candidates.jsonl`

脚本冻结于证据目录，**不作生产机制**。

### 测试路径

核实仅 `tests/` + `web/src/**/*.test.*`；无 `web/tests`、scripts、根目录、ming_sim/tests 测试根。

### 语义处置

完整成员表（简洁一份）：`j6-class-members.jsonl`  
每条含 `entry` / `result` / `mock_boundary` / `reason`。  
**已移除** `j6-all-members-disposition.json`（机器 stamp retain）。

本轮代码删修（样本非白名单）：helper 专测 / 调用 mock / 内部 oracle → 真入口或删除；详见 class-members。

### 诚实边界

结构候选仍有一批（见 structural-candidates-summary）；**不**把候选或全集 stamp 成 retain，**不**宣称开放=0 / J6 结清。枚举≠语义处置。不以范围大申报 unfinished；本轮已对读源确认的类成员整类删修。

---

## 3. 聚焦测试

七变量均 `/usr/bin/false`。见 `focused-evidence-fix.log`。

未跑全量。

---

## 4. 自查（质量顾问）

- 机器枚举 ≠ 语义处置；无信号 ≠ 不属类；unit ≠ helper 豁免。
- 保留项均写可核入口/结果/mock 边界。
- J18 实况/奏报原则与退役配套已分清。
- 未 stash/amend/rewrite/push/PR；`.baseline/` 未动。
- 自查二连 done。

## 5. 未结项（如实）

- 不自行宣布 merge / 关票 / converged / J6 结清。
- 结构候选继续按全文类定义语义处置。
- 有护核账与暗护玩法接续仍归家族收尾 / #1873。
