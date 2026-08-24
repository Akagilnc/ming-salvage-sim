# #657 票面修正案 r11（2026-08-24 票庭 r11 apply；judge `01a03409-6797…` converged）

> 本文件为 GitHub issue #657 庭裁修正案 r11 的仓内审计副本（apply 腿 run 结算载体）。票面正文以 https://github.com/Akagilnc/ming-salvage-sim/issues/657 为准。均为票面文本级修复、零范围变更、**零产品代码**。
>
> **继承**：r10 全文（plan `01a03400-ed8b…@fixer`；judge `01a033fb-f0dc…`）——CAS 短 atomic 完整复核 + 严格 rowcount；reconcile 零改动；discover/start/join/persist 事务外；删 r9 可选收窄；独立连接提交可见；CAS 后再崩；atomic 三边界。
>
> **本 r11 唯一差分**（judge `01a03403-88bf…` remaining class「#505 不回归验收夹带源码路径断言」）：替换 R10-F2.6h″ **第12–15条**及对应 AC / What-to-build 测试措辞——**废止**「断言 reconcile 源码路径无 scaffold 特判分支」；将第12与第15合并为**同库三轮一次真实 reconcile** 行为矩阵。R10-F2.6s CAS 协议伪码与规则表、断点表、生产语义 **一字不重开**。

法源：CLAUDE.md P1/P5/P6/P7；Accepted ADR 0035/0036/0037/0093（及 r10 已引 0055/0070/0079/0092 继承适用）；#505；#647。  
前案：r10（`01a03400-ed8b-7ae4-af2b-4f87e01a6027@fixer`）；r11 plan（`01a03406-cbfe-74a2-b4dc-4b25c48a6ad0@fixer`）；converged judge（`01a03409-6797-7b1c-a2d6-9b93d9d36487@judge`）。

---

## 0. 范围 / 保留 / 废止

### 0.1 r11 本轮唯一施工面（class boundary · 票面文本）

| 项 | 口径 |
|---|---|
| **只改** | R10-F2.6h″ **第12–15条**措辞；对应 AC / What-to-build 中 #505 不回归与进程恢复夹具的**测试叙述** |
| **不改** | R10-F2.6s CAS 协议伪码与规则表；R10-F2.6g″ 断点表；reconcile/reopen 生产语义；新鲜垫位 atomic；authorization；七类 ABI 其余 |
| **禁增** | 源码字符串/路径/分支名扫描；`inspect`/`getsource`；文件路径断言；新 reopen API；reconcile 特判；恢复表/第二 registry/第二 chat_turn |

### 0.2 相对 r10 必废（本 class 根因）

- R10-F2.6h″ 第15条句尾：「断言 reconcile 源码路径无 scaffold 特判分支」——**整句删除**。  
  理由：违反本单「禁止以源码字符串/路径断言代替行为验证」；该断言无独立行为价值；r10 已令 reconcile **零改动**，行为矩阵已覆盖无问话→failed / 有问话→interrupted。
- 第12条与第15条各自完整建库+真实 reconcile 启动链的**重复夹具成本**——合并为**同一聚焦同库夹具**（共享建库/状态；独立连接观察与 CAS 后再崩可挂同一库，避免重复启动链）。

### 0.3 r10 已结清保留（CAS 协议 · 不重开）

r10 相对 r9 已废并保留如下，**r11 一字不重开**：

- **废止**：r9-F2.6s「reconcile **可选收窄**：跳过被未消费空 origin TAG_ENTER 引用的无问话 scaffold 使其保持 generating」；CAS 事务前只读谓词当真理；「CAS 与 join 同事务」「CAS 不 commit 就 start」。
- **保留**：R9-F2.6t 新鲜垫位 atomic 三步；R9-F2.6r′ 复用分支骨架；R9-F2.0 authorization；C1；七类 ABI 其余；#505 `reconcile_interrupted_chat_turns` / `reopen_interrupted_chat_turn_for_retry` 语义与实现；禁恢复表/第二 registry/第二 chat_turn/新 reopen API 族。

### 0.4 r10 CAS 施工面（继承 · 实现轮依据）

| 项 | 口径 |
|---|---|
| **只改（实现轮）** | scaffold CAS 协议；断点表中与 CAS 事务边界相关句；进程重入与 #505 不回归验收 |
| **不改** | 新鲜垫位 atomic 三步；复用分支骨架；authorization；C1；七类 ABI 其余；reconcile/reopen 生产语义 |
| **禁增** | 恢复表、第二 registry、第二 chat_turn、reconcile 特判跳过 scaffold、新 reopen API 族 |

---

## 1. 根因

### 1.1 r11（验收夹具一类 · 本轮）

| 问 | 答 |
|---|---|
| 真实失败 | r10 第15条在行为矩阵后仍要求「断言 reconcile 源码路径无 scaffold 特判分支」，把实现形态（路径/字符串）当成验收，抵触本单行为验证令；且第12与第15各起一套 reconcile 建库，测试成本无必要翻倍。 |
| 不变式 owner | **同库真实 DB 状态**：一次真实 `reconcile_interrupted_chat_turns` 后，summon scaffold / 不相关无问话轮 / 有问话轮 分别为 `failed`/`failed`/`interrupted`；随后仅对 scaffold 走 `ensure_*` CAS→仅它变 `generating`；有问话轮走既有 `reopen_interrupted_chat_turn_for_retry`，问话与账不删、不相关轮仍 `failed`。 |
| 为何不新造 | 不改生产码；不扫源码；复用既有 #505 行为断言风格（`tests/test_audience_restore_505.py`：真实 DB 状态、消息与账，不依赖路径）；夹具合并只减重复启动，不减故障缝覆盖。 |

### 1.2 r10（CAS 一类 · 继承）

| 问 | 答 |
|---|---|
| 真实失败 | 复用路径要以严格 CAS 把 reconcile 后的 `failed` scaffold 拨回 `generating`。r9 同时允许改 reconcile 跳过 scaffold（过度且违 #505）；且 CAS 的 ledger/chat_turn/night 一致性只前读、UPDATE 不在短 atomic 内完整复核+提交，写事务可跨入锁外 join，独立连接在 join 前未必见已提交状态。 |
| 不变式 owner | **同一 chat_turn 行** + **同一空 origin TAG_ENTER 行**；状态只在既有 `chat_turns.status` 上、于**一次短 `atomic(db)` 内**复核全部谓词后 CAS；`atomic` 退出＝提交；discover/start/join **必须在该事务外**。reconcile 对无问话→failed、有问话→interrupted 的 #505 语义 **零改动**。 |
| 为何不新造 | 复用 `ming_sim.applier.atomic`（最外层退出真 commit）；复用既有 status 列；不建恢复表/第二 registry/第二 chat_turn；不调用、不扩展 `reopen_interrupted_chat_turn_for_retry`（其谓词仅 interrupted）。 |

现码锚点（施工对照 · HEAD `dadb0fbf`）：

- `ming_sim/applier.py` `atomic`：最外层退出真 commit；异常 rollback；嵌套不提前提交
- `ming_sim/audience_night.py` `attach_minister`：enter→create_chat_turn→回绑已 `with atomic(db):`（新鲜垫位对照）
- `GameDB.reconcile_interrupted_chat_turns`：有 `user_message_id`→`interrupted`；无→`failed`；永不删账
- `GameDB.reopen_interrupted_chat_turn_for_retry`：仅 `interrupted→generating` + 自 commit；**不匹配**无问话 scaffold
- 启动链：`web_app` `__init__` / `_rebuild_session` 先 `reconcile_interrupted_chat_turns()`
- `tests/test_audience_restore_505.py`：以状态/行数断言，无源码路径

---

## 2. R10-F2.6s scaffold 可重入 CAS（**r10 原文 · r11 不改**）

**选定做法（判词唯一路径 · 最小）**：复用路径对 `failed` scaffold 做 **一次短 `atomic(db)` 内完整复核 + 严格 CAS + 退出即提交**；**不**改 reconcile；**不**新建 reopen API；**不**恢复表；**不**第二 chat_turn。

### 2.1 调用位置（编排边界）

```
# ① 内、持 write_gate：
#   - 新鲜垫位：R9-F2.6t 自己的 atomic（三步）——不改
#   - 空垫位复用：先读 origin 命中空行，再：
ensure_summon_scaffold_reenterable(db, chat_turn_id, entry_id, origin, night_id)
#   ↑ 函数返回时 CAS（若发生）**必须已提交**
#   然后才允许（均在 CAS 事务外）：
discover_open_enter_tasks(..., chat_turn_id)
session._scene_registry.start_open_enter(..., chat_turn_id=chat_turn_id)
# ② 锁外 join；③ persist 原 entry_id
# 硬禁：discover / start / join / generator / persist 进入 ensure_* 的 atomic 内
```

### 2.2 严格协议（伪码 · 施工必遵）

```
ensure_summon_scaffold_reenterable(db, chat_turn_id, entry_id, origin, expected_night_id):
  """空垫位复用唯一状态入口。失败一律 raise（响亮）；禁止静默新建第二轮。"""
  from ming_sim.applier import atomic

  with atomic(db):   # 短事务：期内复核 + 可选 CAS；退出 = 一次真 commit
      # —— 以下全部在同一 atomic 内重新 SELECT，禁止信任事务前快照 ——

      ct = SELECT id, status, user_message_id, minister_message_id, night_id
           FROM chat_turns WHERE id = ?  -- chat_turn_id
      if ct is None:
          raise  # 响亮失败

      le = SELECT id, body, origin_ref, origin_chat_turn_id, night_id, tags...
           FROM story_ledger_entries WHERE id = ?  -- entry_id
      if le is None:
          raise

      # 事务内完整谓词（全部满足才允许 no-op 或 CAS）
      assert le.origin_ref == origin
      assert TAG_ENTER ∈ le.tags          # 与 discover 同族判定
      assert le.body.strip() == ""        # 未消费
      assert int(le.origin_chat_turn_id) == int(chat_turn_id)
      assert int(ct.night_id) == int(le.night_id) == int(expected_night_id)
      assert ct.user_message_id IS NULL
      assert ct.minister_message_id IS NULL OR ct.minister_message_id == 0

      if ct.status == 'generating':
          return  # 同进程、reconcile 未跑；谓词已在事务内复核；无写

      if ct.status == 'failed':
          cur = UPDATE chat_turns
                SET status = 'generating'
              WHERE id = ?
                AND status = 'failed'
                AND user_message_id IS NULL
                AND (minister_message_id IS NULL OR minister_message_id = 0)
              -- 绑定 chat_turn_id
          if cur.rowcount != 1:
              raise  # 竞态 / 谓词漂移 → 响亮失败，不得新建第二轮
          return

      if ct.status == 'interrupted':
          # interrupted 语义上必有 user_message；无问话 scaffold 不应落入
          raise  # 响亮失败；不得调用 reopen_interrupted_chat_turn_for_retry

      # active / undone / 其它终态
      raise

  # atomic 正常退出 ⇒ 已 commit
  # 调用方此后的 discover/start/join 所见必为已提交状态
```

### 2.3 钉死规则表

| 规则 | 口径 |
|---|---|
| **唯一 CAS 路径** | `failed → generating`，且仅当事务内全部 chat_turn + ledger + night 谓词成立 |
| **事务边界** | 复核 SELECT + CAS UPDATE **同属一个** `with atomic(db):`；退出即提交；异常全回滚 |
| **rowcount** | `!= 1` → raise；禁止当成功；禁止回退新建 chat_turn / DELETE 空垫位再 INSERT |
| **generating no-op** | 仍须在同一 atomic 内跑完全部谓词复核；只是不写 status |
| **reconcile** | **零改动**。无问话在飞 scaffold 启动后仍标 `failed`；有问话仍标 `interrupted`。**删除** r9「可选跳过 scaffold」全文，无二选一、无并存等价路径 |
| **不调用** | `reopen_interrupted_chat_turn_for_retry`（谓词不匹配 scaffold） |
| **不修改** | reconcile 有问话→interrupted；reopen 仅 interrupted→generating；#505 恢复提示链 |
| **事务外** | `discover_open_enter_tasks` / `start_open_enter` / join / generator / `persist_chat_turn_scene` **禁止**进入该 atomic |
| **硬禁** | 因 failed 而 `create_chat_turn` 第二轮；换 entry_id；新 registry/恢复表；把 CAS 写拖到 join；信任事务前只读快照做 CAS |

### 2.4 与新鲜垫位 atomic 的关系

| 路径 | 事务 | 内容 |
|---|---|---|
| 新鲜垫位 | R9-F2.6t 自己的 `atomic` | INSERT 空 TAG_ENTER + create_chat_turn + 回绑 origin |
| 空垫位复用 | R10-F2.6s **另一**短 `atomic` | 仅复核 + 可选 status CAS；**不**再 INSERT |
| 二者 | 均在 write_gate 内、均在 discover/start **之前**结束并提交 | 不得合并成跨 join 的长事务 |

---

## 3. R10-F2.6g″ 断点表（**r10 原文 · r11 不改**）

| 断点 | 行为 |
|---|---|
| ③ 后、① 前 crash | choice 已 decided；重试新鲜 ①（R9-F2.6t atomic 三步） |
| **① 新鲜 atomic 内任一步** | 全回滚；零孤儿；重试走新鲜路径 |
| **① 新鲜 atomic 提交后、② 前（进程级）** | DB：空 TAG_ENTER+已绑 origin + scaffold（generating）。重启 → **未改动的** reconcile → 无问话 → **failed**。重试：C1 跳过已应用；按 origin 命中空行 → **R10-F2.6s 短 atomic 内复核+CAS** failed→generating（退出已提交）→ 同 ledger id + 同 chat_turn id → **事务外** discover/start；不增行；③ 写原行 |
| **CAS atomic 内崩溃** | 回滚；status 仍 failed；空垫位仍在；重试再走完整 ensure_* |
| **CAS 成功提交后、start 前再 crash** | DB 已是 generating + 空 TAG_ENTER；再启动 → reconcile **再**标 failed → 再 CAS → 不增行 |
| ② 中 / ② 后 ③ 前 | 空行未消费；复用+CAS（若需）再 join；以最终非空 body 为准 |
| persist 成功后 | consumed；重试 skip |
| 已在场夜 | 仍落/复用该 origin 的 TAG_ENTER |

**删除**任何「reconcile 跳过 scaffold 故保持 generating、可不走 CAS」的断点叙述。

---

## 4. R11-F2.6h″ 验收增量（**替换** r10 h″ 第12–15；11/13/14/16/17 原样继承）

11. **atomic 三边界 fault-inject**（r10/r9-F2.6t 保留）：事务内崩溃均零孤儿；提交后复用原 id  
12+15. **同库三轮行为矩阵 + 真实进程恢复链（合并夹具 · 本 r11）**  
    单一聚焦同库夹具，一次建库放入三者（均 `generating` 在飞）：  

    | 行 | 构造 |
    |---|---|
    | **S** summon scaffold | 空 origin TAG_ENTER 已绑 + 无 `user_message_id` / 无 minister 消息（R10-F2.6t 提交后形态） |
    | **U** 不相关无问话轮 | 非本 origin 空垫位；普通 generating 且无 `user_message_id`（#505 orphan 同类） |
    | **Q** 有问话在飞轮 | `user_message_id` 已链、回话未落（#505 半途 kill 同类） |

    **步骤（单次真实 reconcile，禁止只 `del registry` 冒充）**：  
    1. 真正调用 `reconcile_interrupted_chat_turns()`（或等价 `__init__` / `_rebuild_session`）  
    2. 断言状态：**S=`failed`，U=`failed`，Q=`interrupted`**；ledger 行数/id 相对 reconcile 前不删账  
    3. **仅**对 S 调用 `ensure_summon_scaffold_reenterable`（R10-F2.6s）→ 断言 **仅 S=`generating`**；U 仍 `failed`；Q 仍 `interrupted`；同 origin ledger 行数=1、id 不变；chat_turns 不增  
    4. 对 Q 走既有 `reopen_interrupted_chat_turn_for_retry` → Q→`generating`；问话消息行仍在；账不删；**U 仍 `failed`**（不被 scaffold CAS、不被 reopen 误拨）  
    5. S 路径继续：**事务外** discover/start；最终非空 body；phase2 可过（与 r10 条12 原验收终点对齐）  

    **硬禁（验收层）**：`inspect`/`getsource`、文件路径、源码子串、分支名/「特判」字符串扫描；不得以源码形态代替上表状态与行数断言。  

13. **CAS 后再崩**（r10 保留；**可与 12+15 共享建库/S 行状态**，在 ensure 提交后、start 前再 reconcile+重试 → 仍同 id、不增行、可完成；不必另起全链）  
14. **CAS 短事务已提交可观察**（r10 保留；**挂同一夹具**）：`ensure_*` 返回后、**join 之前**，用 **独立 SQLite 连接**（非同一 `db.conn`）读 S：`status=='generating'` 且 `user_message_id IS NULL`  
16. 空冲突非成功（r8-12 保留）  
17. 保留 r7 条 1–10  

**明确删除**：r10 第15条「断言 reconcile 源码路径无 scaffold 特判分支」及任何等价源码路径/字符串断言。

**保留的故障缝（不因合并而删）**：独立连接可见性（14）、事务内回滚边界（11）、CAS 后再崩（13）——三者验证不同缝，仅共享建库/状态以控成本。

---

## 5. AC / What to build（票面同步用 · 有效文本）

### 5.1 AC 差分（召见 CAS / #505 · 增补；冲突以本节为准）

- [ ] **召见进程重入**：① 后真实 `reconcile_interrupted_chat_turns`（**不**收窄、scaffold→failed）→ **单短 `atomic` 内**完整复核 chat_turn+ledger+night 谓词并 CAS `failed→generating`（退出即提交，`rowcount!=1` 响亮失败）→ **事务外** discover/start/join → 同 id 完成 persist；CAS 后再崩仍可无限重入不增行；空 body≠consumed；无第二 chat_turn/恢复表/第二 registry  
- [ ] **CAS 提交可观察**：ensure_* 返回后、join 前，独立连接读到 `generating` 且无 user_message  
- [ ] **#505 不回归（r11）**：与 scaffold **同库**并行放置不相关无问话轮 + 有问话轮；**一次**真实 reconcile 后三者为 `failed`/`failed`/`interrupted`；仅 scaffold 经 ensure→`generating`；有问话轮经既有 reopen 且问话与账保留；不相关轮始终 `failed`。**禁止**源码路径/字符串/分支扫描。不改 reconcile/reopen 语义  

**删除票面/方案中一切**：

- 「断言 reconcile 源码路径无 scaffold 特判分支」及 `getsource`/路径扫描验收  
- 「reconcile 可选跳过 scaffold」「与 CAS 二选一或并存」

### 5.2 What to build 差分句（崩溃重入状态机 · 增补）

> **崩溃重入状态机**：进程启动必经未改动的 `reconcile_interrupted_chat_turns`；无问话 summon scaffold → `failed`。复用路径在 **一次短 `atomic(db)` 内**重新复核（无 user/minister 消息 + 被未消费空 origin TAG_ENTER 引用 + night 一致）后 CAS 回 `generating`，退出即提交；`discover`/`start`/`join` 仅在事务外。禁止改 reconcile 跳过 scaffold；禁止新建 chat_turn/恢复表/第二 registry；CAS 后 start 前再崩仍不增行。验收含：独立连接观察已提交 CAS；**同库三轮行为矩阵**（scaffold / 不相关无问话 / 有问话）一次真实 reconcile + ensure/reopen 分路断言；**不以源码路径或字符串扫描代替状态与行数断言**。

---

## 6. OOS

- 重开 R10-F2.6s CAS 协议、改 reconcile/reopen、改新鲜垫位 atomic  
- 恢复表 / 第二 registry / 第二 chat_turn / 源码扫描护栏  
- r10 已闭 authorization、双闭集、duty、grant 等  
- 修订 ADR 0036/0037 本文  
- 御笔手敕、M12、扩 RESCRIPT routable、dossier 第二幂等索引  
- 实现 coding（另开轮严格按 r10 CAS + r11 验收）

---

## 7. 复杂度账 / 前科

| 类别 | 项 |
|---|---|
| **复用** | r10 全量 CAS/断点/独立连接/CAS 后再崩；#505 既有行为断言风格；同库三行一次 reconcile |
| **新增（闭集）** | 无生产机制；仅验收叙述：合并夹具步骤 1–5 |
| **删除** | 「源码路径无 scaffold 特判分支」断言；第12与第15重复建库启动链；r9 reconcile 可选收窄（r10 已删，r11 确认） |
| **前科** | 不得回潮源码路径/getsource 验收；不得为省事删 11/13/14 故障缝；不得改 reconcile 跳过 scaffold；不得放松 #505 状态断言换绿灯；不得用 `reopen_interrupted` 吃无问话 scaffold；不得无事务伪 CAS；禁恢复表/第二轮 chat_turn |

---

## 8. 范围声明（apply 结算）

- 仅 `docs/issue-657-ticket-amendment-r11.md`＋ GitHub issue #657 正文 What to build / AC 对应句同步。  
- **Parent / Blocked by / 标签不动**。  
- **零产品代码、零测试改动**；实现另开 coding 轮。  
- 冲突处以本节 r11（含继承之 r10 CAS）为准。
