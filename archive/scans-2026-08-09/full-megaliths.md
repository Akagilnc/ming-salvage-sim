## 违宪扫描清单（`db.py` / `issues.py` 抽样）

法源主依 SHARED **#12**（复杂度/作废须删）、**#14**（DRY）。已知「署理字符串 JOIN」不重复。抽样：头尾 + 最大函数 + 重复 SQL/序列化样板。

---

### 1. 高 — 全仓零引用死方法 / 死别名未删
- **file:line**: `ming_sim/db.py:3222`、`11515`、`12620-12621`、`12661`
- **违反**: #12「被改动作废的旧物，随同改动删除」
- **证据**:
```
_primary_source_only_army_pay_container_total → 仅 return _standalone…（refs=1）
_is_audience_chat_shared_channel → 定义后无调用（refs=1）
write/insert_relation_edge_event = record_… → 无 `.()` 调用
read_credit_events_as_edges → 仅包装 credit_events_as_edges（refs=1）
```
- **说明**: 全仓 `*.py` 词引用 ≤1（仅定义）；别名与薄包装同属死面，应删而非留平行名。

---

### 2. 高 — 知识账双表 DELETE 样板 ≥4，helper 已在仍内联
- **file:line**: `ming_sim/db.py:7158/7162`、`7620/7624`、`8208/8212`、`11544/11547`（helper 自身）
- **违反**: #14「同一形状不许两份」；对照已有 `_delete_shared_knowledge_source_ids`（`11535`，仅 `11682` 一处调用）
- **证据**:
```
DELETE FROM character_knowledge_events WHERE source_id = ?
DELETE FROM character_knowledge_sources WHERE source_id = ?
# 成对出现 ×4（含 helper）；另 3 处仍手写 executemany 对
```
- **说明**: 量度 = 成对 SQL ×4；真源 helper 已存在，副本未收敛。

---

### 3. 高 — 单函数超百行（代表例，非穷尽）
- **file:line**: `issues.py:6423`（1116L）、`db.py:724`（1111L）、`issues.py:4502`（807L）、`issues.py:5730`（676L）、`db.py:6150`（292L）
- **违反**: #12「复杂度即成本」
- **证据**:
```
apply_score_extraction     6423-7538 = 1116 行
init_schema                724-1834  = 1111 行
apply_issue_tracker_output 4502-5308 = 807 行
_apply_person_changes      5730-6405 = 676 行
apply_army_deltas          6150-6441 = 292 行
```
- **说明**: GameDB 内 >100 行方法共 **11** 个；上表为量度尖峰，非建议一次拆完。

---

### 4. 中 — `regions.fiscal` JSON 字符串 load/update 未抽 typed 真源（≥6/12）
- **file:line**: load ×12（如 `db.py:2171,2208,2234,…,5877`）；`UPDATE … SET fiscal=? …` ×6（`2180,2298,3685,3707,5747,5900`）
- **违反**: #14；兼「该走 schema/typed accessor 却反复拼 JSON 字符串」
- **证据**:
```
fiscal = json.loads(str(row["fiscal"] or "{}"))   # ×12
UPDATE regions SET fiscal = ?, updated_at = … WHERE id = ?  # ×6
```
- **说明**: 列类型是 TEXT blob；读写样板同构未收敛为单一 `load/save_region_fiscal` 真源。

---

### 5. 中 — `apply_*_deltas` 拒收留痕外壳同构 ≥3
- **file:line**: `db.py:5605-5613`（region）、`6166-6171`（army）、`5284-5289`（power）；另 `missing_ref` 关键字全文件 ×5
- **违反**: #14
- **证据**:
```
SELECT * FROM {table} WHERE id=?
if row is None: changes.append({rejected, category: missing_ref|hallucinated_id, reason, item})
```
- **说明**: 外壳同形 ≥3；字段白名单/校验体不同，但拒收信封可抽而未抽。

---

### 6. 中 — strategic `split_*` 三份同构图
- **file:line**: `issues.py:3653`、`3727`、`3811`
- **违反**: #14
- **证据**:
```
_split_strategic_entity_deltas   # dict → (strategic, other)
_split_strategic_new_armies      # list → (strategic, other)
_split_strategic_person_result…  # list → (strategic, other)
```
- **说明**: 谓词不同、分流骨架相同 ×3；调用点在 `apply_score_extraction` 内再铺开。

---

### 7. 中低 — gate 数值路动态 `f"SELECT {field}"` 六分支（文本路已表驱动）
- **file:line**: `issues.py:2158-2178` vs `2212-2218`
- **违反**: #14；字段虽经 `_gate_sql_field` 白名单，仍是字符串拼列名
- **证据**:
```
# _eval_gate_key: 6× if/elif + f"SELECT {field} FROM …"
# _eval_gate_key_str: 已用 dict 表驱动同一形状
issues 内 f"SELECT {field} …" 计数 = 12
```
- **说明**: 非注入漏洞（有白名单）；违宪点是同构 SQL 装配未并入单一表驱动真源。

---

**未报 / 刻意省略**: 署理 JOIN（已知）；`issues.py` 模块级函数死引用扫描 = 0；仅出现 2 次的内部私有调用不记死码。

**结论**: 有发现，优先死面清理（#1）与已有 helper 未吃干的知识 DELETE 副本（#2）；巨函数与 fiscal/拒收/strategic 同构为下一档复杂度债。后台那次「死方法全仓扫描」后来超时/被中断了（status: error），但同主题的快速扫描已经跑完，结论已写进上一份违宪清单：`db.py` 里 3 个零引用方法 + 2 个死别名；`issues.py` 无死函数。无需再跑一遍。
