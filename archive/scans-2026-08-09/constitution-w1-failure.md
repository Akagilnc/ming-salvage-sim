# W1（#472 / PRD #485 / #487–#494）失败诚实宪法 · 违宪扫描

**法源**：`ak-pi-workflow-roles/CLAUDE.md`「失败诚实宪法」——「接住可以，洗白不行：未识别异常不得冒用具体标签；真因必须落痕；catch 后照常继续视同缺陷，除非『此失败下继续』是文档化契约。」

**扫描基线**：`origin/main` @ `14367eaff9026f19f0495d24075423e092094f40`  
**交付 PR**：[#1020](https://github.com/Akagilnc/ming-salvage-sim/pull/1020)（关闭 #485、#487–#494）  
**范围**：该 PR 交付、现仍在 main 上的角色视角/见闻/读心/回奏相关实现（含后续在同一表面上的编排接线）。

---

## 1. [严重] 见闻排密 JSON 损坏时当空排除表继续可见

**位置**：`ming_sim/knowledge.py:56-57`、`ming_sim/knowledge.py:69-70`（配合 `ming_sim/participant_roster.py:12-13`）

**违反条文**：「catch 后照常继续视同缺陷」；「真因必须落痕」；「except … 返回默认值假装没失败」

**证据**：
```56:57:ming_sim/knowledge.py
    except (TypeError, ValueError, KeyError, IndexError):
        excluded_names = []
```
```69:70:ming_sim/knowledge.py
        except (TypeError, ValueError):
            targets = {}
```
```12:13:ming_sim/participant_roster.py
    except (TypeError, ValueError):
        return set()
```

**说明**：`excluded_names` / `excluded_targets` / `participant_roster` 解析失败后一律当成「无排除 / 无花名册约束」继续做可见性判定；在 `knowledge_row_visible_to` 里空花名册会跳过参与者闸。损坏数据被洗成「可看」，无原异常落痕，亦无文档化「损坏即公开」契约。

---

## 2. [严重] 读心失败吞掉真因，仅打笼统 `failed`；终态写入失败裸 `pass`

**位置**：`web_app.py:2062-2065`、`web_app.py:2075-2076`（对照 `ming_sim/audience_pipeline.py:53`「失败上抛」）

**违反条文**：「真因必须落痕」；「未识别异常不得冒用具体标签」；「except 裸 pass」

**证据**：
```2062:2065:web_app.py
            except Exception:
                # 读心失败：回话已 done，不回滚。落终态 failed 让重开轮询能终止。
                result = None
                terminal_status = "failed"
```
```2075:2076:web_app.py
                except Exception:
                    pass
```

**说明**：下层 `run_mindreading_for_turn` 约定失败上抛；编排层用裸 `Exception` 接住后不记录 `type`/`message`/stack，一律标成已知态 `failed`。随后 `set_mindreading_status` 再失败时裸 `pass`——连「失败已记录」这一层痕迹也可消失。接住回话不回滚可以；把未识别异常洗成无因 `failed`、再把落态失败洗没，不行。

---

## 3. [高] `seed_guilt` 解析失败冒充「底案未见坐实之事」

**位置**：`ming_sim/mindreading.py:87-90`（上游同形：`ming_sim/session.py:611-615`）

**违反条文**：「未识别异常不得冒用具体标签」；「返回默认值假装没失败」

**证据**：
```87:90:ming_sim/mindreading.py
    except (TypeError, ValueError):
        guilt = {}
    if not isinstance(guilt, Mapping):
        return "底案未见坐实之事。"
```

**说明**：JSON/类型损坏与「无罪底案」共用同一叙事标签；读心材料拿到的是具体清白语义，而非「底账不可读」。session 重载人物时同样把坏 `seed_guilt` 洗成 `{}`，无落痕。

---

## 4. [高] 近臣见闻/回奏路径：任意异常冒用三类具体失败文案，且不落真因

**位置**：`ming_sim/session.py:1206-1209`、`1225-1226`、`1229-1230`

**违反条文**：「未识别异常不得冒用具体标签」；「真因必须落痕」

**证据**：
```1206:1209:ming_sim/session.py
        except Exception:
            # Legacy projection trouble may fall back to ordinary chat, but it
            # must be visible rather than silently authorising a factual reply.
            return "【近臣回奏暂不可用：见闻记录读取失败；不得据此臆答事实。】\n\n" + message
```
```1225:1226:ming_sim/session.py
            except Exception:
                return "【近臣回奏暂不可用：查访未能持久留档；不得据此臆答事实。】\n\n" + message
```
```1229:1230:ming_sim/session.py
        except Exception:
            return "【近臣回奏暂不可用：见闻投影失败；不得据此臆答事实。】\n\n" + message
```

**说明**：对玩家可见的「不得臆答」横幅属于接住；但 `except Exception` 把未知故障分别贴成「见闻记录读取失败 / 查访未能持久留档 / 见闻投影失败」三类已知标签，且无原始异常落痕——接住有了，诚实标签与真因没有。

---

## 5. [中] 精度因子非法时冒用精度档「模糊」

**位置**：`ming_sim/mindreading.py:63-64`、`69`

**违反条文**：「未识别异常不得冒用具体标签」；「返回默认值假装没失败」

**证据**：
```63:69:ming_sim/mindreading.py
    except (TypeError, ValueError):
        score = 0.0
    if score >= 0.75:
        return "清晰"
    if score >= 0.4:
        return "隐约"
    return "模糊"
```

**说明**：`float` 转换失败被当成 score `0.0`，再输出情报精度词「模糊」。调用方/下游看到的是合法精度档，不是「因子无效」。

---

## 扫描附注（非违宪项 / 未列入）

- W1 核心模块 `intelligence.py` / `recommendations.py` 主体以响亮 `ValueError` 或空结果表达「不适用」，未见重试循环掩盖持续性失败。
- `generate_mindreading_payload` 空模型输出显式 `LLMUnavailable("模型返回空文本")`——属识别后的具体类别，不按本条计。
- `qualitative_band` 缺测值回落中档有注释说明呈现契约，未按「异常洗白」计。
- `session._audience_prompt_for_message` 内 `audience_scene_recap` 的 `except → recap=""`（约 L1239）属 #507 连场接线，不计入 W1 本清单。

**结论**：W1 角色视角交付面上发现 **5** 条失败诚实违宪（按严重度上列为 1→5）；最重的是见闻排密损坏被洗成「可见」，以及读心失败无真因 + 终态写入裸 `pass`。
