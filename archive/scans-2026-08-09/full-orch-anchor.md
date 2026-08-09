抽查完毕。编排器本体在 `orchestrator/src/`（编译为 `dist/*.js`）；根下 `.mjs` 启动脚本无相关命中。

---

# 编排器违宪扫描 · LLM/角色自由文本驱动分支

**法源**：`orchestrator/CLAUDE.md` 铁律 0「从不读字」+ ADR 0131 三通道；兼 ADR 0141（腿散文合法、禁腿级 admissibility 拒收）、ADR 0142（自由文本零解析）、ADR 0062。  
**范围**：`orchestrator/` 编排器本体（`src/` ↔ `dist/*.js`）；只读。  
**口径**：宁缺毋滥——仅列「对角色/LLM（或等价自由文本）抠正则/措辞并改编排命运」的硬证。

---

## P0

### 1. 开场寒暄正则拒收腿卷面（语义拒收超出 exit/非空形状）

- **位置**：`orchestrator/src/legPaper.ts:45-72`、`:84-91`（消费：`successfulLegsFromTransports` → CMR panel 在场名单）
- **违反条文**：ADR 0141「腿级 admissibility 拒收……废除」「内容 shape 不是闸」；「进度散文＝无卷」已删却又回潮；0142「不得用关键词、正则……从自由散文抠语义」
- **证据**：
```
const OPENING_LINE_RE =
  /^(?:我要开始|开始审|好的[，,]?\s*(?:我(?:来|要)?)?开始|I'll start\b|...)/i;
...
if (isOpeningLineOnlyStdout(input.stdout)) return false; // exit 0 也当 absent
```
- **说明**：exit 0 + 非空 stdout 本应算合法卷面；却用中英寒暄措辞把腿标成 absent，改写 `successfulLegs`，属对角色 stdout 的语义拒收。

---

### 2. Runner 用人答自由文本子串映射「继续修」意图

- **位置**：`orchestrator/src/runner.ts:687-694`（调用：`:873-874`、`:1109` → `continue_fixing` 修复边）
- **违反条文**：铁律 0「从不读字」；0131「三者之外零判断权」；「机器要消费的信息必须以键、typed 字段提供」（答案本可有 `intent`，却抠 `answer` 散文）
- **证据**：
```
function answerMapsToContinueFixing(answer: EscalationAnswerEvent): boolean {
  const text = answer.answer.trim().toLowerCase();
  return (
    text.includes("continue") ||
    text.includes("继续修") || ...
  );
}
```
- **说明**：`EscalationAnswerEvent.answer` 是自由字符串；用「continue / 继续修」等措辞决定是否进修复环，未走独立 typed intent。

---

## P1

### 3. Worker failure `reason` 散文关键词分流 stop 族

- **位置**：`orchestrator/src/family/verifyCmr.ts:1037-1100`、`:1212-1226`；同类：`runner.ts:1485-1504`
- **违反条文**：0142「关键词……抠语义」；0131 Runner/编排「不读字」却用 reason 文案改 `StopSummary.reason`（`provider_degraded` / `cmr_failed` / `verify_failed` / contract drift）
- **证据**：
```
!/\b(provider|auth|authentication|quota|rate limit|transport)\b/i.test(input.reason)
...
/\b(MODULE_NOT_FOUND|Cannot find module|dependency|build|test|toolchain)\b/i.test(...)
```
- **说明**：失败原因若是自由措辞（含 worker/infra 叙述），靠词表改终态标签与 repairHint 族；应用 typed failure class，而非扫 prose。

---

### 4. 无 typed `Output.object` 时从 stdout `<cmr>` 标签解判词命运

- **位置**：`orchestrator/src/family/realFamilyBackend.ts:3855-3876`、`:4359-4365`、`:4197-4248`；抽取：`lastTaggedJson.ts:22-43`
- **违反条文**：0131 Completion「合法 sidecar / typed 收据」；0142「结构化事实只走显式结构化契约」——却用 stdout 定界标签当契约
- **证据**：
```
} else {
  outcome = classifyCmrCargoOnly(parseCmrStdoutCargo(stdout)); // <cmr>…</cmr>
}
// classifyCmrCargoOnly → decodeJudgeVerdict → status continue|converged|escalate
```
- **说明**：注释称 cargo-only，但仍 `decodeJudgeVerdict`；缺 typed envelope 时，呈现层标签 JSON 仍可驱动判词三态路由。

---

## P2（边界，宁缺仍录一条）

### 5. 线上 bot 评论「正文长度≥20」当 finding 计数

- **位置**：`orchestrator/src/botPolling.ts:578-581`（汇入 `totalFindingCount`）
- **违反条文**：0142 精神——用自由文本长度启发代替 typed finding 信号；锚定「机器咬呈现」
- **证据**：
```
const body = (c.body ?? "").trim();
if (body.length === 0) continue;
if (body.length >= 20) count += 1;
```
- **说明**：把 bot 散文体长当「有 finding」；措辞/篇幅一变计数即漂。轻于 P0（非角色 LLM 腿），但仍是散文启发驱动环。

---

## 未记（有意放过）

- Zod/`decodeJudgeVerdict` 对 **typed 信封** 的形状校验（含非空 `fixPacketBody`）——契约形状，非抠散文语义。
- `BOT_RETRIGGER_REQUIRED_LINES` 识别人工协议口令——固定控制面正文，非角色自由卷面。
- `launch-362.mjs` / durable-bin 脚本——无角色输出语义分支。

**结论**：硬违宪至少 2 条 P0（`legPaper` 开场拒收、`runner` 人答措辞映射）+ 2 条 P1（reason 词表分流、stdout `<cmr>` 解判词）。
