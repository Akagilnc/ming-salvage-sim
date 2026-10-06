# #1902 修内司 T3 r4：sqlite3.Row id 读取

- 基线：b9f35aab7
- FIX SHA：`ab8c8bc839675a067a2ac70dc2564cc6987d6dba`
- 仅修 legacies_payload 的 `row.get` → `row["id"]`（真实行契约）
- 四个 warning 分支与未知异常上抛保留

## 真实 DB 探针
- NORMAL_OK（Row has_get=False）
- BAD_JSON_OK warnings=2
- NON_OBJ_OK warnings=2
- RUNTIME_PROPAGATED

## 聚焦
25 passed in 3.12s（web_entry + audience_restore）
