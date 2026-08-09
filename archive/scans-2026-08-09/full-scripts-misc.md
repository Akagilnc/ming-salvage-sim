## 违宪扫描清单（6 分钟 · 补漏）

已知 `scripts/` 11+2 probe 与 `spike_settle_tick.py` 不重复。`web/electron/` 未见合格项。

---

### P1 · 生产地图驻军用自由文本子串匹配
- **位置**: `web_app.py:1104-1122`
- **违反**: SHARED #13「盯文（对自由文本建机械依赖）」；CLAUDE「接口层（确定性↔LLM，别让 LLM 自己数数）」
- **证据**:
```python
return any(word in text for word in mapping.get(theater_id, ()))
# text = f"{army['id']} {army['name']} {army['station']} {army['theater']}"
# mapping: "辽东"/"宁锦"/"关宁"…
```
- **说明**: 战区归属靠中文名/驻地散文子串，文案一改地图就错位。

---

### P1 · 读心失败后又吞终态落库失败
- **位置**: `web_app.py:2062-2076`
- **违反**: 结算/运行时「响亮」失败纪律；SHARED #15「一切以用户体验优先」
- **证据**:
```python
except Exception:
    result = None
    terminal_status = "failed"
...
except Exception:
    pass  # set_mindreading_status 失败被吃掉
```
- **说明**: 读心已失败却可能写不进 `failed`，重开轮询可挂死且无声。

---

### P2 · CLI 自动玩家盯文驱动（补漏轴：盯文，非 probe 名录）
- **位置**: `scripts/play_as_emperor.py:200-214`、`426-433`
- **违反**: SHARED #13「盯文（对自由文本建机械依赖）」
- **证据**:
```python
PROMPT_PATTERNS = ["召见谁？输入编号或姓名", "朕问：", "诏书草案> ", ...]
pending_ids = re.findall(r"\[待核定\]\s*#(\d+)", cli_chunk)
if "暂无草案" not in cli_chunk ...
```
- **说明**: 用 CLI 提示原文/正则当状态机，文案改动即整条自动化断。

---

### P2 · 遗产 modifiers JSON 坏了静默变空效果
- **位置**: `web_app.py:1194-1201`
- **违反**: 坏数据应响亮/可观测，非静默降级（对照 settle「shape 垃圾 → 响亮中止」精神）
- **证据**:
```python
except Exception:
    eff = {}
except Exception:
    clear_gate = {}
```
- **说明**: 库内坏 JSON 变成「无修正/无消除条件」，皇帝侧看到假空盘。

---

### P2 · 根目录临时备忘未清（已跟踪）
- **位置**: `NEXT_ORDER.md:1`
- **违反**: SHARED #12「被改动作废的旧物，随同改动删除」；CLAUDE「别另建 md 工作清单」
- **证据**:
```markdown
# 下一步执行顺序（临时备忘 · 2026-07-08 凌晨更新）
```
- **说明**: 自标「临时备忘」、内容已过期，仍占仓库根。

---

### P2 · 根目录史实草稿 / 巨图杂物未清
- **位置**: `REVIEW-SOURCES-484.md:1-3`；`主页1.png`（约 6.7MB，已跟踪）
- **违反**: SHARED #12「复杂度即成本…废旧物随同删除」
- **证据**: 标题「#484 R6 史实依据草稿」；根上单文件 `主页1.png` 非发布入口引用资产
- **说明**: 切片草稿与未归位素材仍堆在根目录。

---

### P3 · probe 产物目录已进 git
- **位置**: `scripts/runs/`（9 个已跟踪：`*_probe_result.json` + bench `*.log.stdout`）
- **违反**: SHARED #12「废旧物随同删除」；原型/探针「答案落档、原型删」
- **证据**: `dalinghe_defection_probe_result.json` 等与 bench stdout 同在 `git ls-files`
- **说明**: 一次性跑批输出未毕业、也未从版本库清掉。

---

### P3 · 一次性 SQL 补丁脚本仍留 scripts/
- **位置**: `scripts/huangtaiji_rename_qing.sql:1-4`
- **违反**: SHARED #12「废旧物随同删除」
- **证据**:
```sql
-- 此 SQL 给旧存档手动补一次；...
-- 正常程序启动会通过 GameDB.ensure_schema 幂等补列，不需要反复执行本脚本。
```
- **说明**: 自承已被 `ensure_schema` 取代的一次性补丁，仍占 scripts。

---

### 未列（故意）
- 已知 11×`*_probe.py` + `play_as_emperor`/`decree_bench`（作 probe 名录）+ `spike_settle_tick.py`
- `launcher.py`/`steam.cjs` 多数 `catch` 有 warn/回退路径，未达「吞失败」门槛
- `temp_todo.md` 已在 `.gitignore`（本地脏文件，非跟踪违宪项）
