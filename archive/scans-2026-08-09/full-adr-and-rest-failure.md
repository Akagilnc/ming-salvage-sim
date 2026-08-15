## 违宪扫描结果（限时只读 · 宁缺毋滥）

法源：`~/.claude/CLAUDE.md` SHARED #9/#5 + 对照 `ak-pi-workflow-roles/CLAUDE.md`「法源优先」「失败诚实宪法」。排除已扫五文件；W1/W2 已覆盖的 `session`/`cli_backend`/`audience_*` 不重复列。

---

### (a) `docs/adr/` · 与宪法冲突且无「陛下原话 + decision key」绑定

#### 1. [严重] ADR 0045 明文立「超时上限 + 失败静默降级」

- **位置**：`docs/adr/0045-highlight-judge-is-sole-source-same-backend-postpass.md:5`
- **违反条文**：SHARED #9「严禁 SIGKILL、无脑硬上限墙钟」；失败诚实「真因必须落痕」；法源优先「违反宪法者，须绑陛下原话与 decision key」
- **证据**：
  > 判官设超时上限，超时/失败一律静默降级为无高亮、回话先行展示……（用户 Q3 拍：几秒换零晃，超时即回话先行无高亮）
- **说明**：决策正文本身授权墙钟超时并以「无高亮」洗失败；仅有「用户 Q3 拍」转述，无逐字陛下原话、无 decision key。

#### 2. [中] ADR 0127 仍授权 `reset --hard` / `clean -fd`（且 Status=Proposed）

- **位置**：`docs/adr/0127-no-destroy-worker-scenes.md:11`
- **违反条文**：SHARED #5「`reset --hard` / `git clean` = 永久销毁……执行任一不可逆操作前必须有明确授权词」；法源优先绑定要件
- **证据**：
  > `reset --hard` / `clean -fd` 类清场仅允许出现在 terminal-success 后的显式 GC
- **说明**：相对 0024 已收窄，但仍开不可逆清场例外；全文无陛下原话引文、无 decision key，且尚未 Accepted。

**其余抽检**：ADR 0130 仅在根因叙述里提及「900s hang 守卫」，非本 ADR 决策授权例外——未列入。未再发现其它「明文违宪且无绑定」的 Accepted ADR。

---

### (b) `ming_sim/` 剩余模块 · 吞异常 / 冒用标签 / 不落痕

#### 1. [严重] 拟诏密令证据查询失败被洗成「无证据」

- **位置**：`ming_sim/decree.py:170-171`
- **违反条文**：「返回默认值假装没失败」；「真因必须落痕」
- **证据**：
```python
        except Exception:
            closed_evidence = []
```
- **说明**：`list_secret_orders` 等异常与「确实无办结密令」同形空清单进拟诏 payload，无 log/错误包。

#### 2. [高] 官职 LLM 分类失败被洗成空串→下游「待铨」

- **位置**：`ming_sim/db.py:627-628`（经 `infer_office_type_from_office`）
- **违反条文**：「未识别异常不得冒用具体标签」；「真因必须落痕」
- **证据**：
```python
    except Exception:
        out = ""
    _OFFICE_TYPE_LLM_CACHE[text] = out
```
- **说明**：推理异常与「模型拒答/未知官名」共用 `""`，调用方落到「待铨」，真因不落痕。

#### 3. [中] HITL 最小决策数读配置失败默回 `1`

- **位置**：`ming_sim/simulation.py:37-38`
- **违反条文**：「返回默认值假装没失败」；「真因必须落痕」
- **证据**：
```python
    except Exception:
        return 1
```
- **说明**：配置/导入失败与「玩家设为 1」不可区分，静默改变 simulator 门槛。

#### 4. [中] `save_resolve_context` 的 attempt 推导失败静默回落 `1`

- **位置**：`ming_sim/decree.py:646-647`
- **违反条文**：「真因必须落痕」；「catch 后照常继续视同缺陷，除非…文档化契约」
- **证据**：
```python
    except Exception:
        attempt = 1
```
- **说明**：同文件结算路径 `:1110-1111` 有 `tlog`+真因；此路径无痕，拒收序号可静默错号。

#### 5. [中] CLI 待补提示查询失败→提示整段消失

- **位置**：`ming_sim/cli/terminal.py:333-334`
- **违反条文**：「catch 后照常继续视同缺陷」；「真因必须落痕」
- **证据**：
```python
    except Exception:
        return
```
- **说明**：读待补账失败与「无待补」同为静默 return，玩家看不到【账本待补】与失败。

#### 6. [低] token 用量记录 `except: pass`

- **位置**：`ming_sim/token_stats.py:186-187`（异步 `:199-200` 同形）
- **违反条文**：「except 裸 pass」；「真因必须落痕」
- **证据**：
```python
        except Exception:
            pass
        return resp
```
- **说明**：旁路遥测失败完全无痕；不挡主路径，但属裸吞。

---

**结论**：(a) **2** 条 ADR 绑定缺失违宪；(b) 剩余模块新发现 **6** 条失败诚实点（最重：拟诏证据空清单洗白、官职分类失败冒充待铨）。未声称「零问题」。
