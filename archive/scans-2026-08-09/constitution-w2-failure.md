扫描范围：PRD #497 十片（#498–#507/#499/#502–#504）经家族 PR #1087 合入 `main` 的交付面；条文取自 `ak-pi-workflow-roles/CLAUDE.md`「失败诚实宪法」。

---

# W2 失败诚实宪法 · 违宪清单

**法源**：「接住可以，洗白不行」；「未识别异常不得冒用具体标签」；「真因必须落痕」；「catch 后照常继续视同缺陷，除非『此失败下继续』是文档化契约」；以及本路主题所列形态（裸 pass / 默认值假装没失败 / 重试掩盖持续失败）。

**基线**：`main` @ PR #1087 交付文件族（`audience_*` / `web_app.py` / `cli_backend.py` / `session.py` / `web/src/useDurableProjection.ts` / `web/src/api.ts` 等）。

---

## 1. [严重] 确认意图抽取失败被标成「无」，下游按未表态→颁诏默认同意

**位置**：`ming_sim/cli_backend.py:1251-1257`  
**违反条文**：「未识别异常不得冒用具体标签」；「返回默认值假装没失败」  
**证据**：
```python
except Exception as exc:  # 抽取失败不阻断对话；当未表态，暂存留到颁诏(算同意)
    _log(f"确认意图抽取失败：{exc}")
obj = _loads_lenient(raw) or {}
v = str(obj.get("确认") or "无").strip()
return v if v in {"应允", "拒绝", "无"} else "无"
```
**说明**：抽取异常与「皇帝未表态」共用标签「无」。失败路径落入确认状态机后，会按未表态留到颁诏默认同意。同文件多道准驳失败已改走「含糊」（约 L1291-1293），单道确认仍把失败洗成「无」。有 `_log` 但对外语义已冒用具体标签。

---

## 2. [严重] 读心失败：异常未绑定、真因不落痕；终态写入再失败则裸 pass

**位置**：`web_app.py:2062-2076`（`_trail_mindreading_after_reply`）  
**违反条文**：「真因必须落痕」；「except 裸 pass」  
**证据**：
```python
except Exception:
    # 读心失败：回话已 done，不回滚。落终态 failed 让重开轮询能终止。
    result = None
    terminal_status = "failed"
...
try:
    with self._runtime_write_gate():
        self.db.set_mindreading_status(chat_turn_id, terminal_status)
except Exception:
    pass
```
**说明**：接住后只标 `failed`，异常对象未绑定、无错误包/日志。若 `set_mindreading_status` 再失败则 `pass`，轮询侧可既无记录又无终态，失败被洗白。接住本身可（回话不回滚有注释），洗白在真因与二次失败路径。

---

## 3. [严重] 在场名单查询失败被洗成 `[]` 后继续叙事抽取

**位置**：`ming_sim/audience_extraction.py:206-218`（`run_extraction_for_turn`）  
**违反条文**：「catch 后照常继续视同缺陷，除非…文档化契约」；「返回默认值假装没失败」  
**证据**：
```python
try:
    present_names = sorted(persons_present_tonight(db, int(night_id)))
except Exception:
    present_names = []
...
facts = extract_story_facts(..., present_names=present_names or [], ...)
```
**说明**：`persons_present_tonight` 失败被当成「无人在场」喂给抽取员并继续落账路径。未见「在场查询失败则按空名单继续」的契约文档；与同模块抽取/落账失败写错误包+pending 的响亮路径不对称。

---

## 4. [严重] `trail_extraction_after_reply` 外层异常丢真因；标待补失败则裸 pass 后返 `None`

**位置**：`ming_sim/audience_extraction.py:327-335`  
**违反条文**：「真因必须落痕」；「except 裸 pass」；「返回默认值假装没失败」  
**证据**：
```python
except Exception:
    # run_extraction_for_turn 契约从不抛；到此=查询等意外。不静默：标待补候补跑。
    try:
        with write_gate:
            if hasattr(db, "mark_story_extraction_pending"):
                db.mark_story_extraction_pending(int(chat_turn_id))
    except Exception:
        pass
    return None
```
**说明**：外层 `except Exception` 未绑定 `exc`，无错误包（对比 `_pending_with_pack`）。注释称「不静默」，但标待补再失败则完全静默并以 `None` 返回；调用方（Web/CLI 尾随）看不到失败语义。

---

## 5. [高] #504 密令喂料：开夜 id 查询失败静默回落 turn 域；SQL 失败返空串继续

**位置**：`ming_sim/session.py:211-214`、`244-245`（`_recent_audience_context_for_secret_order`）  
**违反条文**：「catch 后照常继续视同缺陷…」；「返回默认值假装没失败」；「真因必须落痕」  
**证据**：
```python
try:
    night_id = int(night_getter() or 0)
except Exception:
    night_id = 0
...
except Exception:
    return ""
```
**说明**：函数注释要求「按当前开着的夜取回」、防同回合上一夜串味。`night_getter` 失败 → `night_id=0` → 走 turn 域取回，失败被洗成「无开夜旧路径」。查询异常返 `""` 无落痕，密令确认仍带着空上下文继续。

---

## 6. [高] 连场 scene recap 失败洗成空串；同函数见闻失败则响亮提示

**位置**：`ming_sim/session.py:1236-1240`（`_audience_prompt_for_message`）  
**违反条文**：「catch 后照常继续视同缺陷…」；对照同函数见闻路径的诚实接住  
**证据**：
```python
try:
    from ming_sim.audience_night import audience_scene_recap
    recap = audience_scene_recap(self.db, character.name)
except Exception:
    recap = ""
```
**说明**：同函数见闻读失败会注入「【近臣回奏暂不可用：…】」（约 L1206-1230）。recap 失败则 `""`，组装侧等同「今夜无殿上先闻」，#507 连场输入静默塌缩，无契约声明「recap 失败当无回顾」。

---

## 7. [高] 持久投影密令刷新失败被空 `catch` 吞掉

**位置**：`web/src/useDurableProjection.ts:35-45`  
**违反条文**：「catch 后照常继续视同缺陷…」；「except 裸 pass」  
**证据**：
```typescript
api<{ orders: SecretOrder[] }>("/api/secret_orders")
  .then(({ orders }) => { /* apply… */ })
  .catch(() => {});
```
**说明**：`/api/secret_orders` 失败无提示、无状态；随后仍 `await api("/api/game/state")` 并落 UI。玩家可见「局态已刷新、密令可能仍是旧的/空的」且无失败信号。属 #499 交付面。

---

## 8. [中高] 读心轮询对取数失败无限 `continue`，掩盖持续性失败

**位置**：`web/src/api.ts:184-187`（`pollMindreadingUntilReady`）  
**违反条文**：「重试循环掩盖持续性失败」；「真因必须落痕」  
**证据**：
```typescript
try {
  data = await fetchMindreading(ministerName, chatTurnId);
} catch {
  continue;  // 瞬断重试，不中断轮询（不计入终止条件）
}
```
**说明**：持续 4xx/5xx/网络失败时循环只 sleep+重试，错误不累计、不暴露、不终止；仅靠 `shouldContinue`（离面板等）结束。注释按「瞬断」写，实现对持续性失败无上限、无落痕。

---

## 9. [中] 密令/任免会话动作抽取失败对外仍返回动作「无」

**位置**：`ming_sim/cli_backend.py:912-927`（`extract_minister_actions`）；`1175-1184`（`extract_appointment_action`）  
**违反条文**：「未识别异常不得冒用具体标签」  
**证据**：
```python
except Exception as exc:  # 抽取失败不阻断对话
    _log(f"大臣动作抽取失败：{exc}")
obj = _loads_lenient(raw) or {}
...
_action = _raw_action if _raw_action in {"无", ...} else "无"
return {"secret_action": _action, ...}
```
**说明**：docstring 写明「失败返回『无』动作」——「继续」有注释，但「无」仍是业务语义标签，与抽取器故障共用。真因仅在 `_log`；对确认/暂存管线仍像「本轮无此意图」。#504 接缝相关。

---

## 10. [中] CLI 动作意图 future 失败返 `[]` 且无落痕

**位置**：`ming_sim/session.py:949-952`（`_finish_cli_action_intent`）  
**违反条文**：「真因必须落痕」；「返回默认值假装没失败」  
**证据**：
```python
try:
    result = future.result()
except Exception:
    return []
```
**说明**：注释写 Failure → `[]`（零写入）——继续有文档化倾向，但异常未记录。调用方无法区分「分类器判空」与「分类器崩溃」；W2 交付面 `session.py` 上的 P5 并行分类接缝。

---

## 附：同文件对照（未列入，非违宪或契约已钉）

- `run_extraction_for_turn` / `_pending_with_pack`：抽取/落账失败写错误包 + pending —— 接住且留痕。
- `drain_pending_before_close`：待补 fail-closed —— 诚实中止。
- `_audience_prompt_for_message` 见闻三处失败注入「暂不可用」—— 接住可。
- `extract_directive_confirmation` 失败返「含糊」—— 拒绝把失败洗成「无」。
- `open_night` savepoint `except` 后 `raise` —— 非洗白。

---

**结论**：在 W2/`main` 交付面上发现 **10** 条失败诚实违宪点；最重的是确认意图失败冒充「无」并通向默认同意，以及读心/抽取/在场查询的静默降级。未发现「零问题」。
