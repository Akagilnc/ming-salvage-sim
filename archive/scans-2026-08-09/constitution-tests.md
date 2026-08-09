## 违宪扫描结果（W1/W2 测试 + probe）

法源：`ak-pi-workflow-roles/CLAUDE.md`（Probe lifecycle / 锚定宪法 / 失败诚实）+ `~/.claude/CLAUDE.md` §13「盯文」。  
范围说明：`ming_sim/tests/` 不存在，相关用例在仓库根 `tests/`；`orchestrator/test/` 无 W1/W2 召对/角色视角测试；**未发现** `toMatchSnapshot` / `toMatchInlineSnapshot`。

---

### 1. 临时 probe 未删未毕业（密令）
- **位置**：`scripts/secret_order_probe.py:1`、`scripts/secret_order_probe2.py:1`
- **违反**：Probe lifecycle — *「temporary evidence… delete it or graduate… then delete the scratch copy」*
- **证据**：
```text
"""一回合密令推演探针：…验 done 红线修复…
"""第二回合：…复用 secret_test.db（probe1 已建 active 密令 #1）。
```
- **说明**：W2 密令证据脚本仍常驻 `scripts/`，未见毕业进回归后删除 scratch。

### 2. 根目录 throwaway spike 未清理
- **位置**：`spike_settle_tick.py:1`
- **违反**：Probe lifecycle — *「After its evidence purpose is disposed, either delete it or graduate」*
- **证据**：
```text
一次性 spike v3(非引擎,throwaway)——r12 返工:
```
- **说明**：文件自评 throwaway，仍留在仓库根。

### 3. 其它未毕业 scratch probe 集群
- **位置**：`scripts/agy_turn_probe.py:1`、`scripts/cli_tools_probe.py:1`、`scripts/direct_decree_probe.py:1`、`scripts/memory_*_probe.py`、`scripts/*_defection|_expedition|_dispatch|_flow_probe.py`（共 11 个）
- **违反**：Probe lifecycle — *「Do not keep duplicate permanent shapes of the same probe behavior」*
- **证据**：
```text
"""探针：用本地 CLI 后端…验证全结算链。
"""探针：验证「独立进程重建 context → 大臣只读工具输出正确」
```
- **说明**：六月起的探针脚本与结果 JSON 仍在；行为若已有正式测试，scratch 应删。

### 4. dossier 表头/措辞硬断言（#494）
- **位置**：`tests/test_featured_dossiers_494.py:29-33`、`:43`、`:49-53`
- **违反**：锚定宪法 — *「对自由文本的正则/措辞/表头机械依赖…视同缺陷」*；§13 *「盯文…直接删」*
- **证据**：
```python
assert all("身份：" in minister_dossier(character) for character in ministers)
assert all("动机：" in minister_dossier(character) for character in ministers)
assert "【派系档料】" in rendered
assert "这个党是什么样一伙人" in middle
```
- **说明**：把呈现表头与中文措辞锁进回归，重排文案即红。

### 5. 读心材料定性文案硬断言（#491）
- **位置**：`tests/test_mindreading_491.py:149-150`、`:185-188`
- **违反**：锚定宪法 — *「机器只咬契约，不咬呈现」*；§13 *「盯文」*
- **证据**：
```python
assert "工心计" in material["底案"]
assert "案情分量：无" in material["底案"]
assert "名义党派：皇党" in material["党账"]
assert "党色极深" in material["党账"]
```
- **说明**：应用 typed 档位/枚举断言，却咬死呈现句。

### 6. 近臣回奏 statement 自由文本硬断言（#492）
- **位置**：`tests/test_near_minister_reports_492.py:44-55`、`:75-76`
- **违反**：锚定宪法 — *「对自由文本的…措辞…机械依赖」*
- **证据**：
```python
assert build_return_report(...)["statement"] == (
    "近臣暂未查到与所问相符的督抚官缺。"
)
assert "陕西巡抚当前虚悬" in statement
assert "12000" in arrears["statement"]
```
- **说明**：契约应是 `source_kind`/空缺集合等字段，不是整句中文。

### 7. SSE/API 错误与诏文用中文子串当契约（#498）
- **位置**：`tests/test_web_audience_night_498.py:276`、`:340`、`:367`
- **违反**：锚定宪法 — *「机器要消费的信息必须以键、typed 字段或 schema 提供」*
- **证据**：
```python
assert "在飞" in (issue_events[-1].get("data") or "")
assert "结算" in (...) or "亲裁" in (...)
assert ... and "诏" in resp.json()["decree"]
```
- **说明**：事件已有 `event=="error"`/`status_code`，又用呈现措辞当机器契约。

### 8. chip 文案整表锁死（#527 / ADR 0042）
- **位置**：`tests/test_suggestions_chips_527.py:9-18`
- **违反**：锚定宪法测试延伸 / §13 *「盯文」*
- **证据**：
```python
_PREFIX_ONLY = [
    {"label": "拟旨", "text": "拟旨如下：", "prefix": True},
    {"label": "下密令", "text": "密令如下：", "prefix": True},
]
assert items == _PREFIX_ONLY
```
- **说明**：应断言 `prefix` 结构/条数，却锁死 label/text 呈现。

### 9. 前端呈现层文案硬断言（抽屉定性，P4/W1 呈现）
- **位置**：`web/src/components/drawers.test.tsx:62-65`、`:90-91`
- **违反**：锚定宪法 — *「呈现为人服务，随时可重排」*；无 snapshot，但效果等同锁死呈现
- **证据**：
```tsx
expect(host.textContent).toContain("欠饷约60万两");
expect(host.textContent).toContain("忠诚尚稳");
expect(host.textContent).not.toContain("忠诚73");
```
- **说明**：定性翻译措辞一改测试即红；应用「无裸数值 / 有近似档」类契约。

### 10. 召对 modal 失败/重试文案硬断言（#505 相关）
- **位置**：`web/src/components/modals.test.tsx:364`、`:398-399`
- **违反**：锚定宪法 — *「不咬呈现」*
- **证据**：
```tsx
expect(...textContent).toContain("密令未能正式落库");
expect(note?.textContent).toContain("重新生成回话");
expect(note?.textContent).toContain("剿抚孰先？");
```
- **说明**：可用 `data-testid`/failure `kind` 断言，却咬中文 copy。

### 11. 测试 fixture 吞掉 close 失败
- **位置**：`tests/test_web_audience_night_498.py:113-116`；同形：`tests/test_audience_restore_505.py:484-487`、`tests/test_beat_orchestration_503.py:282-285`
- **违反**：失败诚实宪法 — *「catch 后照常继续视同缺陷，除非『此失败下继续』是文档化契约」*
- **证据**：
```python
try:
    game.session.close()
except Exception:
    pass
```
- **说明**：teardown 静默吞任意异常，close 真失败不落痕、测试仍绿。

### 12. 角色视角世界呈现句硬断言（#489）
- **位置**：`tests/test_character_knowledge_489.py:612-613`、`:625`
- **违反**：锚定宪法 / §13 *「盯文」*
- **证据**：
```python
assert "167万两" in view["world"]["treasury"]
assert "民心低迷" in view["world"]["treasury"]
assert view["world"]["public"] == "登基伊始，朝廷暂无前回合奏报。"
```
- **说明**：视角视图的呈现散文被当 schema 断言。

---

**未发现**：W1/W2 相关测试中的 `toMatchSnapshot` 呈现锁；`orchestrator/test/` 内无 audience/dossier/perspective/chip 相关违宪项。
