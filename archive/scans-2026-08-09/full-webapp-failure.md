# `web_app.py` 失败诚实违宪清单

**法源**：`ak-pi-workflow-roles/CLAUDE.md`「失败诚实宪法」——「接住可以，洗白不行」；「未识别异常不得冒用具体标签」；「真因必须落痕」；「catch 后照常继续视同缺陷，除非『此失败下继续』是文档化契约」。  
**排除**：`web_app.py:2062-2076` 读心两处（已知，不列）。

---

## 1. [严重] LLM 配置提交：非 LLM 异常冒用 `llm_error`

**位置**：`web_app.py:4058-4061`（配合 `407-414`）  
**违反条文**：「未识别异常不得冒用具体标签」；写库失败被洗白  
**证据**：
```python
except LLMUnavailable as e:
    raise HTTPException(..., detail=_llm_error_detail(e)) from None
except Exception as e:  # noqa: BLE001
    raise HTTPException(..., detail=_llm_error_detail(e)) from None
# _llm_error_detail: "code": getattr(exc, "code", "llm_error")
```
**说明**：`commit_llm_config` 在 `_serialized_web_write` 内写盘；SQLite/锁/状态错误也会被打成 `llm_error`，写库失败伪装成 LLM 故障。

---

## 2. [高] SSE 召对流：读心外层再吞，流仍 `done`→`end`

**位置**：`web_app.py:2311-2324`  
**违反条文**：「catch 后照常继续视同缺陷…」；「真因必须落痕」；SSE 静默降级  
**证据**：
```python
try:
    mind_payload = self._trail_mindreading_after_reply(...)
except Exception:
    mind_payload = None
if mind_payload:
    ev_queue.put({"type": "mindreading", ...})
...
ev_queue.put({"type": "end"})
```
**说明**：独立于内层 `2062`：外层不绑 `exc`、不投 `error`、不留痕，客户端只见正常收束；读心失败在 SSE 面上被洗成「没这件事」。

---

## 3. [高] `active_db.txt` 读失败 → 空串，静默改走别的主库路径

**位置**：`web_app.py:2463-2467`（同形 `2494-2498`）  
**违反条文**：「返回默认值假装没失败」；「真因必须落痕」  
**证据**：
```python
try:
    with open(active_file, "r", encoding="utf-8") as f:
        return f.read().strip()
except Exception:
    return ""
```
**说明**：文件存在但 IO/权限失败时与「无 active 配置」同归一，`_get_main_db_path` 落到 env/默认库，主库切换失败被洗成「用默认路径」。

---

## 4. [高] drain 关库/归档：close 与 `shutil.move` 失败裸吞

**位置**：`web_app.py:2571-2605`  
**违反条文**：「except 裸 pass」；「真因必须落痕」；写库/归档失败洗白  
**证据**：
```python
except Exception:
    close_failed = True
...
except Exception:
    pass  # move 主库
...
except Exception:
    pass  # move -shm
```
**说明**：`close` 失败静默跳过归档；`move` 失败 `pass` 且无日志，new_game detach 路径可丢归档/半归档而无响亮痕迹。

---

## 5. [中] 帝国修正 JSON 坏 → `{}`，当无修正继续渲染

**位置**：`web_app.py:1194-1201`  
**违反条文**：「返回默认值假装没失败」  
**证据**：
```python
try:
    eff = json.loads(str(row["modifiers"] or "{}"))
except Exception:
    eff = {}
try:
    clear_gate = json.loads(str(row["clear_gate"] or "{}"))
except Exception:
    clear_gate = {}
```
**说明**：坏账与「空 modifiers/gate」同形，状态栏继续展示，损坏被洗成「无效果/无门」。

---

## 6. [中] 流式召对：回滚/`fail_chat_turn` 二次失败裸 `pass`

**位置**：`web_app.py:2286-2290`（同形 `2251-2254`、`2332-2336`）  
**违反条文**：「真因必须落痕」；「except 裸 pass」  
**证据**：
```python
try:
    with write_gate:
        self._fail_chat_turn_and_reload(...)
except Exception:
    pass
```
**说明**：注释只辩护「必须吞以免消费者挂死」，未要求留痕；回滚写库失败的真因丢失，轮次可能卡在非终态而对外只见原错误。

---

**结论**：排除已知读心两点后，本文件另见 **6** 条；最重为 LLM 提交路径把写库异常冒充 `llm_error`，以及 SSE 读心外层静默与主库路径/归档写失败洗白。
