# J19 成员表 — 普通押解与既有参与人接缝（静默优先级）

枚举命令见 [`enum-cmd.txt`](enum-cmd.txt)；机器表 [`j19-full-members.json`](j19-full-members.json)。

类定义（判词）：拆除按人物 id 静默保留先项的平行优先级；复用既有参与人规范化与写入语义；不新造冲突裁决。

| 路径 | 行 | 处置 | 依据 |
|---|---|---|---|
| `ming_sim/declaration_dispatch.py` | 1112 | **FIX** | 调用 `_merge_participant_rosters` |
| `ming_sim/declaration_dispatch.py` | 1134–1151 | **FIX_DELETE** | 按 `character_id` 静默 `continue` 的平行合并 |
| `ming_sim/declaration_dispatch.py` | 1072–1078 | **KEEP_LIVE** | 押解侧既有 equality 追加（`entry not in merged`）——复用此语义 |
| `ming_sim/db.py` | 14446–14476 | **KEEP_LIVE** | `append_decree_dossier_participants`：同人同条 skip、同人异档 raise |
| `ming_sim/db.py` | 20864–20898 | **KEEP_LIVE** | `_normalize_participant_roster`：整条 equality 去重，不按 id 静默丢 |

谓词命中仅上列 FIX 四处（同函数）；`by_character` 在 append 写口属现役冲突 raise 语义，非静默保留先项。
