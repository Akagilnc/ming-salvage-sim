## 违宪扫描（复杂度）— W1/W2 优先

法源：复杂度上限（函数 >100 行 / 嵌套 >4）、巨模块/god class、≥3 次未抽重复、臆测通用性、该死未死。范围：`ming_sim/`，优先 PR #1020/#1087/#1056 触达面。只读验证；未改文件、无 git 写、无 issue/PR。

---

### P0 — 明确违例

| # | 标题 | file:line | 违反点 | 证据 | 说明 |
|---|------|-----------|--------|------|------|
| 1 | 人事落库巨函数 | `ming_sim/issues.py:5730` `_apply_person_changes` | 单函数超百行 + 嵌套超标 | **674 行**，nest≈**5**；段内 ~88 个 if/elif | W1 人物变更主路径，状态机式分支堆在一函数里，远超最小必需单元。 |
| 2 | 角色见闻组装巨函数 | `ming_sim/knowledge.py:293` `build_character_knowledge` | 单函数超百行 + 嵌套超标 | **307 行**，nest≈**5**；内嵌 `source_projection` 73 行 | #487/#489 见闻底座核心；事件合并、投影、排除逻辑未切开。 |
| 3 | 召对话缝深嵌套 | `ming_sim/session.py:1018` `GameSession.chat` | 嵌套超 4 层 | **179 行**，nest≈**11**（`For@1064`→连续 `If` 至 `@1151`） | W2 召对入口；tool 环（dismiss/summon/directive…）用深 if 链而非策略表。 |
| 4 | 召对会话 god class | `ming_sim/session.py:656` `GameSession` | god class | 类约 **1639 行** / **53** methods（模块 **2295** 行） | 对话、召对夜、见闻、结算旁路同住一壳，W2 改动面被迫穿过巨类。 |
| 5 | 召对夜巨模块 | `ming_sim/audience_night.py`（整文件）+ `:742` `close_night` | 巨模块 + 函数超百行 | 模块 **1257** 行；`close_night` **152** 行 / nest≈4 | #498 起夜账本；开夜/账本/在飞/收夜/告退同文件，收夜路径已越百行。 |

---

### P1 — 交付面相关，严重但部分为既有巨石

| # | 标题 | file:line | 违反点 | 证据 | 说明 |
|---|------|-----------|--------|------|------|
| 6 | DB/issues 巨石（W1 写穿） | `ming_sim/db.py` / `ming_sim/issues.py` | 巨模块 / god class | `db.py` **12687** 行，`GameDB` ~**11993** 行/**341** methods；`issues.py` **7876** 行 | 非 W1/W2 独造，但人物/见闻写读仍穿此二石；同切片再加逻辑会继续胀。 |
| 7 | 见闻投影内重复谓词 | `ming_sim/knowledge.py:345` 一带（`source_projection`） | 重复该抽未抽（同函数内 ≥3） | `source_id.startswith("projection:")` 至少 **3** 处（~518/531/535）；aggregate 前缀判定多段并列 | 同一 source 边界规则散落，改一类前缀易漏改。 |
| 8 | 双倍兼容召唤缝 | `ming_sim/session.py:1028-1045` | 臆测通用性 | `inspect.signature` + 双路 `bind` 兼容「轻量 doubles」 | 为测试/旧双份保公开缝，生产路径不需要这套反射分叉。 |

---

### P2 — 较轻 / 边界

| # | 标题 | file:line | 违反点 | 证据 | 说明 |
|---|------|-----------|--------|------|------|
| 9 | 死别名 API | `ming_sim/qualitative.py:46` `qualitative_character_attribute` | 该死未删 | 全仓仅定义处命中；体=转调 `qualitative_character_axis` | W1 定性层多余同义入口，零调用。 |
| 10 | 特征化组装分散 | `registry.py:226` / `session.py:~1205` / `beat_orchestration.py:95,179` / `tools.py:216` | 重复装配气味（未到机械 3× 同体） | 四处均 `get_character_knowledge` + `render_character_knowledge` / `_characterization` | 未证克隆体，但是同一「见闻→brief」管线多入口，后续易再分叉。 |

---

### 诚实未发现 / 未坐实

- **大块注释死代码**：`audience_*` / `knowledge` / `beat_orchestration` / `qualitative` / `mindreading` 未扫到 ≥3 行注释掉的可执行块。
- **`person_write_inventory.py`**：生产零引用，但有专用测试守门（ADR 0009 写点清单）——更像**有意的静态守卫**，不按「该死未删」定罪。
- **`audience_extraction` / `beat_orchestration` / `mindreading` / `qualitative` 主体**：函数多数 ≤100、嵌套多数 ≤4；相对干净。
- **全仓 ≥3 次同体克隆**：6 分钟内只对 W1/W2 核心做了指纹扫描，**未坐实**跨文件三次以上复制粘贴；见闻 `source_id` 谓词是最硬的重复证据。

---

**底线**：W1/W2 交付面上最硬的复杂度违宪是 `_apply_person_changes`、`build_character_knowledge`、`GameSession.chat` 深嵌套，以及 `audience_night` / `GameSession` 巨石；定性层有一处死别名可删。
