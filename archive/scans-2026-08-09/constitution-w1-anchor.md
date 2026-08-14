# W1（#472 / PRD #485 / #487–#494）锚定宪法违宪清单

**扫描基线**：已合 PR [#1020](https://github.com/Akagilnc/ming-salvage-sim/pull/1020)（关闭 #485、#487–#494）；现状以 `main` @ `14367eaf` 为准。  
**法源**：`ak-pi-workflow-roles/CLAUDE.md`「**机器只咬契约，不咬呈现**：对自由文本的正则/措辞/表头机械依赖…视同缺陷；机器要消费的信息必须以键、typed 字段或 schema 提供。」兼对照全局 #13「盯文（对自由文本建机械依赖）」。

---

## 严重

### 1. 近臣回奏：用皇帝自由措辞关键词驱动域路由与来源通道
- **位置**：`ming_sim/intelligence.py:38-54`
- **违反条文**：「对自由文本的…措辞…机械依赖」；「机器要消费的信息必须以键、typed 字段或 schema 提供」
- **证据**：
```38:54:ming_sim/intelligence.py
def _query_domain(query: str) -> str:
    text = str(query or "")
    if any(word in text for word in ("欠饷", "欠薪", "军饷", "饷银")):
        return "arrears"
    ...
def source_kind_for_query(query: str) -> str:
    return "inquiry" if any(word in text for word in ("查访", "密查", "查问", "访查")) else "firsthand"
```
- **说明**：查询域（欠饷/流寇/军情/官缺）与 `inquiry|firsthand` 由自由文本子串命中决定，非 typed 意图字段。

### 2. 近臣回奏：官缺应答靠 query 子串匹配 office_title / 辖区措辞
- **位置**：`ming_sim/intelligence.py:18-29`
- **违反条文**：「对自由文本的…措辞…机械依赖」
- **证据**：
```18:29:ming_sim/intelligence.py
matches = [row for row in rows if str(row["office_title"]) in text]
...
if any(word in text for word in ("督抚", "官缺")):
    vacancies = [row for row in rows if not row.get("holder_name")]
```
- **说明**：选哪条官缺记录、是否回退「全部虚悬」，取决于问句措辞是否包含标题/辖区/「督抚」「官缺」。

### 3. 亲见证人匹配：用 title/body 散文词表代替 domain 契约列
- **位置**：`ming_sim/intelligence.py:124-139`
- **违反条文**：「机器要消费的信息必须以键、typed 字段或 schema 提供」；「对自由文本的…措辞…机械依赖」
- **证据**：
```129:139:ming_sim/intelligence.py
# The ledger predates a dedicated domain column, so
# the durable title/body vocabulary is the compatibility discriminator.
terms = _domain_terms(_query_domain(query))
...
and any(term in f"{item.get('title') or ''}{item.get('body') or ''}" for term in terms)
```
- **说明**：代码自承无 domain 列，改抠见闻标题/正文是否出现「军情」「欠饷」等词，以决定能否升格 firsthand。

### 4. 召对入口：用消息关键词闸门触发回奏持久化
- **位置**：`ming_sim/session.py:1210-1223`
- **违反条文**：「对自由文本的…措辞…机械依赖」
- **证据**：
```1210:1223:ming_sim/session.py
if (
    is_inner_court_attendant(character)
    and any(word in message for word in ("官缺", "巡抚", "总督", "督抚", "欠饷", "军情", "敌情", "流寇", "贼情", "查访"))
):
    self.db.persist_return_report(
        self.state, character.name, message,
```
- **说明**：是否写入 `near_minister` 见闻源，取决于玩家消息是否命中固定词表；注释亦称 “keyword hit”。

### 5. 名册可见性：用人名是否出现在事件 title/body 散文做 ACL
- **位置**：`ming_sim/knowledge.py:162-169`
- **违反条文**：「机器要消费的信息没用 typed 字段/schema 而是抠散文」
- **证据**：
```162:169:ming_sim/knowledge.py
visible_event_text = "\n".join(
    "：".join(str(value) for value in (item.get("title"), item.get("body")) if value)
    ...
)
...
or str(row["name"] or "") in visible_event_text
```
- **说明**：结构化名册行能否越过输出边界，取决于姓名子串是否偶然出现在授权事件散文中。

---

## 高

### 6. 大臣工具：在已渲染呈现行上做子串过滤再返事实
- **位置**：`ming_sim/tools.py:227-233`
- **违反条文**：「对 markdown 呈现做机械解析再驱动逻辑」；「呈现为人服务，随时可重排」
- **证据**：
```227:233:ming_sim/tools.py
def filter_domain(domain: str, query: str = "") -> str:
    rendered = scoped_world(domain)
    needle = str(query or "").strip()
    ...
    lines = [line for line in rendered.splitlines() if needle in line]
```
- **说明**：先取呈现文本，再按行/子串抠选；换行或措辞重排会改变工具返回的“事实集”。

### 7. 官缺视图：用剥离「署理／（署理）」显示缀匹配正职
- **位置**：`ming_sim/db.py:807-811`
- **违反条文**：「对自由文本的…措辞…机械依赖」；「呈现…随时可重排」
- **证据**：
```807:811:ming_sim/db.py
LEFT JOIN characters AS c
  ON c.status = 'active'
 AND (
     replace(replace(c.office, '（署理）', ''), '署理', '') = s.office_title
 )
```
- **说明**：任职关系依赖 `office` 显示字符串的固定缀写法；缀词改写即断匹配（#492 测试亦固化「署理陕西巡抚」等形）。

### 8. 流寇域查询：把显示 kind「内乱」当契约枚举值混入 kinds
- **位置**：`ming_sim/intelligence.py:75-78`
- **违反条文**：「机器要消费的信息必须以键、typed 字段或 schema 提供」
- **证据**：
```75:78:ming_sim/intelligence.py
return _report_text(db.power_report(
    # Content identifies the three rebel powers by id while their
    # display kind is \"内乱\".  power_report accepts either form.
    exclude_self=True, kinds={"bandit", "bandits", "内乱"}, audience=True,
```
- **说明**：注释承认「内乱」是 display kind，却作为机器过滤契约与 `bandit` 并列。

---

## 中（测试盯文 / 呈现硬断言）

### 9. #492 测试：把问句措辞→statement 文案当作契约硬断言
- **位置**：`tests/test_near_minister_reports_492.py:42-55`（及同文件多处 query 措辞用例）
- **违反条文**：锚定「呈现…随时可重排」；全局 #13「盯文」
- **证据**：
```42:55:tests/test_near_minister_reports_492.py
assert title in build_return_report(db, f"{title}可有？")["statement"]
assert build_return_report(db, "两广总督可有？")["statement"] == (
    "近臣暂未查到与所问相符的督抚官缺。"
)
...
assert "陕西巡抚当前虚悬" in statement
```
- **说明**：锁定自由问句命中路径与完整中文答句，固化措辞依赖。

### 10. #487/#494 测试：硬断言呈现表头与档料套话
- **位置**：`tests/test_minister_context.py:283-293`；`tests/test_featured_dossiers_494.py:43-49`
- **违反条文**：「对…表头机械依赖」；全局 #13「盯文」
- **证据**：
```283:285:tests/test_minister_context.py
assert "【人物档料】" in rendered
assert "【派系档料】" in rendered
assert "【党派认同】" in rendered
```
```43:49:tests/test_featured_dossiers_494.py
assert "【派系档料】" in rendered
...
assert "这个党是什么样一伙人" in middle
```
- **说明**：验收绑在 `【…】` 表头与固定叙事套语上，非 typed 字段。

### 11. #491 测试：硬断言定性措辞句（党色/离心/案情分量等）
- **位置**：`tests/test_mindreading_491.py:149-150,185-188`
- **违反条文**：「对自由文本的…措辞…机械依赖」；全局 #13「盯文」
- **证据**：
```185:188:tests/test_mindreading_491.py
assert "名义党派：皇党" in material["党账"]
assert "党色极深" in material["党账"]
assert "离心已显" in material["君臣账"]
assert "合谋" in material["底案"]
```
- **说明**：读心材料侧把定性呈现句当可断言契约；措辞表重排即红。

### 12. 回奏定性输出测试：硬断言「火器：简陋」等呈现标签
- **位置**：`tests/test_minister_context.py:678-683`
- **违反条文**：锚定「呈现…随时可重排」；全局 #13「盯文」
- **证据**：
```678:683:tests/test_minister_context.py
assert "火器：简陋" in fact
assert "炮0门" in fact
assert "补给：尚可" in fact
assert "士气：尚稳" in fact
```
- **说明**：经关键词触发的回奏路径上，断言具体定性标签与标点形态。

---

## 中（生产侧：机器材料以呈现句而非 typed schema 承载）

### 13. 读心 materials：真相投影打成中文散文句再供下游消费
- **位置**：`ming_sim/mindreading.py:155-189`
- **违反条文**：「机器要消费的信息必须以键、typed 字段或 schema 提供。呈现为人服务，随时可重排。」
- **证据**：
```155:189:ming_sim/mindreading.py
party_truth = f"名义党派：{faction}；对本党的认同：{identity_band(identity)}。"
loyalty_truth = f"对君的真心：{qualitative_character_axis('loyalty', loyalty)}。"
...
"党账": party_truth,
...
model_materials = {
    "当轮回话": materials.get("reply_text"),
    "党账": truths.get("党账"),
```
- **说明**：有结构化底账（faction/identity/loyalty），却把机器中间契约写成可重排的呈现句，再原样喂模型；与上条测试盯文同源。

---

**未列入**：纯呈现组装（如 `context.py` 写出 `【人物档料】` 给人/LLM 读、且下游不据此分支）、`recommendations.py` 走 `participant_roster` typed 名册、见闻 `kind`/`source_id` 前缀等契约键消费——未见本路违宪形态。

**结论**：W1 交付面存在多处锚定违宪，集中在 **#492 回奏措辞路由**、**#489 名册散文 ACL**、**tools 呈现行过滤**，以及对应 **盯文测试**。
