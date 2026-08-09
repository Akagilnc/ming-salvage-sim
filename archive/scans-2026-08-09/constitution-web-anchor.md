**法源**：ADR 0142（LLM 自由文本零解析）+ 盯文条（「关键词/正则从自由散文抠语义」；「文本一变机器就错＝盯文」）。范围：`web/src/**/*.ts(x)`。

---

## 违宪清单

### 1. 官职字符串正则排品级
- **位置**：`web/src/components/modals.tsx:1036-1044`
- **违反**：0142「不得用…正则…抠取…结构化事实」；盯文「文本一变机器就错」
- **证据**：
```ts
if (/首辅/.test(office)) return 1;
if (/次辅/.test(office)) return 2;
// ...
if (/都御史|巡抚|总督/.test(office)) return 6;
```
- **说明**：朝班排序应吃 typed 品级/席位字段，却从 `office` 文案正则猜层级。

### 2. 从官职文案抠「无实职」并驱动过滤
- **位置**：`web/src/components/modals.tsx:1051-1057`
- **违反**：0142「关键词/正则…抠语义」；「该由后端给 typed 字段」
- **证据**：
```ts
&& !/前|罢|致仕/.test(m.office || "")  // 无实职不排朝班
.sort((a, b) => officeRank(a.office || "") - officeRank(b.office || ""));
```
- **说明**：已有 `status`/`office_type`，仍用「前|罢|致仕」子串当分支条件。

### 3. 从 `office` 逗号分项抠固定职名排席位
- **位置**：`web/src/components/drawers.tsx:30-47`
- **违反**：0142「规则从…抠结构化事实」；盯文机械依赖
- **证据**：
```ts
// 固定职位 → 固定槽位（由 office 文字推导…）
const parts = (office || "").split(",").map((s) => s.trim());
const fs = FIXED_SLOTS.find((f) => parts.includes(f.role));
```
- **说明**：朝班坐标依赖硬编码「首辅/六部尚书」字面与 office 文本切分，非 typed `court_slot`/`role_id`。

### 4. 用邸报/摘要自由文本前缀驱动 UI 分支
- **位置**：`web/src/main.tsx:279-281`
- **违反**：盯文「自由文本随便改、机器永不错判＝合法」；0142 精神（文本当类型）
- **证据**：
```ts
const summary = (state.previous_summary || "").trim();
if (!summary) return;
if (summary.startsWith("登基伊始")) return;
```
- **说明**：是否弹邸报靠 `previous_summary` 文案前缀；应靠 turn/哨兵 typed 字段。

### 5. 按「：」切段落把摘要当表头表体
- **位置**：`web/src/components/modals.tsx:449-456`
- **违反**：用户条「对文案表头硬编码依赖」；盯文机械依赖
- **证据**：
```ts
const idx = line.indexOf("：");
if (idx <= 0) return null;
return { label: line.slice(0, idx), value: line.slice(idx + 1) };
```
- **说明**：`PreviousSummary` 假定后端行格式为「标签：值」；措辞一变表结构崩（虽当前主路径多走 `StateModal` 原文展示，代码仍在库内）。

### 6. 硬编码警讯表头 + 合计句正则拆段
- **位置**：`web/src/format.ts:154-161`、`257-264`
- **违反**：0142「正则…从自由散文抠」；「文案表头硬编码依赖」
- **证据**：
```ts
splitReportItems(text, "地区警讯：");
cleaned.match(/(两京十三省账面[月]税合计[^。]+|建档兵力合计[^。]+)。?$/);
```
- **说明**：前端契约钉死「地区警讯：/军队警讯：」与合计句式；应吃 items/total 结构化字段（现为导出助手，仍属违宪存量）。

### 7. 用地名里的 `" / "` 抠短名
- **位置**：`web/src/components/map.tsx:696`、`709`、`743`
- **违反**：盯文「文本一变机器就错」；「该由后端给 typed 字段」
- **证据**：
```ts
{group.name.split(" / ")[0]}
{region.name.split(" / ")[0]}
```
- **说明**：展示名依赖 seed「中文 / 英文」拼接约定，缺 `short_name`/`label_zh` 就静默错切。

### 8. `office_type` 子串模糊归部（次级）
- **位置**：`web/src/components/drawers.tsx:536-545`
- **违反**：0142「规则…抠」弱形态（子串匹配当分类）
- **证据**：
```ts
const matched = offices.find((o) => (m.office_type || "").includes(o));
const key = matched || "其他";
```
- **说明**：部院分组应用精确枚举/主键，`includes` 会误归类变体文案。

---

## 刻意不报（合宪/非本罪）

- `stripOrganicMarkdown`：CONTEXT/ADR 0045 明示显示剥离，非语义抠事实。
- 搜索框 `name.includes(q)`、SSE `event:/data:`：本地 UX / 传输协议，非 LLM 散文类型判断。
- `EN_FIELD_CN` 等：typed key → 展示文案映射，合法。

**结论**：至少 8 处盯文/0142 形态；最重的是 **官职正则排班（#1–#3）** 与 **摘要文本当哨兵/表结构（#4–#6）**。
