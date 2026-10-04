# J19 全仓成员表（权威）

类定义：拆除按人物 id 静默保留先项；复用 normalize + 一次 merge；规范化为空的 incoming 不覆盖旧名册。

| path | line | disposition | why | text |
|---|---|---|---|---|
| `ming_sim/db.py` | 17614 | KEEP_LIVE_SHARED | 调用共享 merge，不按 character_id 静默裁剪 | `incoming["participant_roster"] = self.merge_participant_roster_entries(` |
| `ming_sim/db.py` | 20897 | KEEP_LIVE_SHARED | 共享 equality-append 合并真源 | `def merge_participant_roster_entries(` |
| `ming_sim/declaration_dispatch.py` | 1076 | KEEP_LIVE_SHARED | 调用共享 merge，不按 character_id 静默裁剪 | `payload["participant_roster"] = GameDB.merge_participant_roster_entries(` |
| `ming_sim/declaration_dispatch.py` | 1118 | KEEP_LIVE_SHARED | 调用共享 merge，不按 character_id 静默裁剪 | `payload["participant_roster"] = GameDB.merge_participant_roster_entries(` |
| `ming_sim/cli_backend.py` | 2073 | KEEP_LIVE_NORMALIZE | ADR 0053 名单规范化真源 | `canonical_roster = db._normalize_participant_roster(` |
| `tests/test_secret_dossier_participants_1252.py` | 66 | KEEP_LIVE_APPEND | 持久化案卷追加接缝（同人异档显式处理） | `db.append_decree_dossier_participants(dossier_id, [{` |
| `tests/test_secret_dossier_participants_1252.py` | 142 | KEEP_LIVE_APPEND | 持久化案卷追加接缝（同人异档显式处理） | `db.append_decree_dossier_participants(did, [{` |
| `tests/test_secret_dossier_participants_1252.py` | 185 | KEEP_LIVE_APPEND | 持久化案卷追加接缝（同人异档显式处理） | `db.append_decree_dossier_participants(dossier_id, [{` |
| `tests/test_secret_dossier_participants_1252.py` | 193 | KEEP_LIVE_APPEND | 持久化案卷追加接缝（同人异档显式处理） | `db.append_decree_dossier_participants(plain_id, [{` |
| `tests/test_secret_dossier_participants_1252.py` | 252 | KEEP_LIVE_APPEND | 持久化案卷追加接缝（同人异档显式处理） | `db.append_decree_dossier_participants(dossier_id, [{` |
| `ming_sim/rescript_draft.py` | 193 | KEEP_LIVE_NORMALIZE | ADR 0053 名单规范化真源 | `# 机械三档与条目形状唯一真源＝GameDB._normalize_participant_roster（ADR 0053）；` |
| `ming_sim/rescript_draft.py` | 700 | KEEP_LIVE_NORMALIZE | ADR 0053 名单规范化真源 | `"""票拟参与名单归一：形状真源＝GameDB._normalize_participant_roster（ADR 0053）。` |
| `ming_sim/rescript_draft.py` | 707 | KEEP_LIVE_NORMALIZE | ADR 0053 名单规范化真源 | `return GameDB._normalize_participant_roster(value, strict_structured=True)` |
| `tests/test_character_knowledge_489.py` | 712 | KEEP_LIVE_APPEND | 持久化案卷追加接缝（同人异档显式处理） | `db.append_decree_dossier_participants(dossier_id, [{` |
| `tests/test_character_knowledge_489.py` | 1329 | KEEP_LIVE_APPEND | 持久化案卷追加接缝（同人异档显式处理） | `db.append_decree_dossier_participants(` |
| `ming_sim/decree_vocabulary.py` | 75 | KEEP_LIVE_NORMALIZE | ADR 0053 名单规范化真源 | `# GameDB._normalize_participant_roster；此处只登记键名与 capability 派生方式。` |
| `ming_sim/declaration_dispatch.py` | 1055 | KEEP_LIVE_NORMALIZE | ADR 0053 名单规范化真源 | `shaped = db._normalize_participant_roster(list(entries), strict_structured=True)` |
| `tests/test_decree_dossiers_571.py` | 82 | KEEP_LIVE_APPEND | 持久化案卷追加接缝（同人异档显式处理） | `db.append_decree_dossier_participants(dossier_id, [{` |
| `tests/test_decree_dossiers_571.py` | 117 | KEEP_LIVE_APPEND | 持久化案卷追加接缝（同人异档显式处理） | `db.append_decree_dossier_participants(dossier_id, invalid[1:])` |
| `tests/test_decree_dossiers_571.py` | 129 | KEEP_LIVE_APPEND | 持久化案卷追加接缝（同人异档显式处理） | `db.append_decree_dossier_participants(` |
| `tests/test_decree_dossiers_571.py` | 133 | KEEP_LIVE_APPEND | 持久化案卷追加接缝（同人异档显式处理） | `db.append_decree_dossier_participants(` |
| `tests/test_decree_dossiers_571.py` | 153 | KEEP_LIVE_APPEND | 持久化案卷追加接缝（同人异档显式处理） | `assert db.append_decree_dossier_participants(dossier_id, [original]) == []` |
| `tests/test_decree_dossiers_571.py` | 155 | KEEP_LIVE_APPEND | 持久化案卷追加接缝（同人异档显式处理） | `db.append_decree_dossier_participants(` |
| `tests/test_decree_dossiers_571.py` | 159 | KEEP_LIVE_APPEND | 持久化案卷追加接缝（同人异档显式处理） | `db.append_decree_dossier_participants(` |
| `ming_sim/issues.py` | 6910 | KEEP_LIVE_APPEND | 持久化案卷追加接缝（同人异档显式处理） | `added = db.append_decree_dossier_participants(dossier_id, [{` |
| `ming_sim/db.py` | 13768 | KEEP_LIVE_NORMALIZE | ADR 0053 名单规范化真源 | `base_roster = self._normalize_participant_roster(` |
| `ming_sim/db.py` | 13784 | KEEP_LIVE_NORMALIZE | ADR 0053 名单规范化真源 | `base_roster = self._normalize_participant_roster(` |
| `ming_sim/db.py` | 13858 | KEEP_LIVE_NORMALIZE | ADR 0053 名单规范化真源 | `roster = self._normalize_participant_roster(` |
| `ming_sim/db.py` | 14160 | KEEP_LIVE_NORMALIZE | ADR 0053 名单规范化真源 | `roster = self._normalize_participant_roster(roster_source, strict_structured=Tru` |
| `ming_sim/db.py` | 14216 | KEEP_LIVE_NORMALIZE | ADR 0053 名单规范化真源 | `roster = self._normalize_participant_roster(roster, strict_structured=True)` |
| `ming_sim/db.py` | 14446 | KEEP_LIVE_APPEND | 持久化案卷追加接缝（同人异档显式处理） | `def append_decree_dossier_participants(` |
| `ming_sim/db.py` | 14461 | KEEP_LIVE_NORMALIZE | ADR 0053 名单规范化真源 | `existing = self._normalize_participant_roster(` |
| `ming_sim/db.py` | 14464 | KEEP_LIVE_NORMALIZE | ADR 0053 名单规范化真源 | `additions = self._normalize_participant_roster(participants, strict_structured=T` |
| `ming_sim/db.py` | 17608 | KEEP_LIVE_NORMALIZE | ADR 0053 名单规范化真源 | `new_roster = self._normalize_participant_roster(` |
| `ming_sim/db.py` | 20149 | KEEP_LIVE_NORMALIZE | ADR 0053 名单规范化真源 | `participant_roster = self._normalize_participant_roster(participants)` |
| `ming_sim/db.py` | 20860 | KEEP_LIVE_NORMALIZE | ADR 0053 名单规范化真源 | `def _normalize_participant_roster(` |
| `ming_sim/db.py` | 20907 | KEEP_LIVE_APPEND | 持久化案卷追加接缝（同人异档显式处理） | ```append_decree_dossier_participants``。` |
| `ming_sim/db.py` | 20909 | KEEP_LIVE_NORMALIZE | ADR 0053 名单规范化真源 | `base = GameDB._normalize_participant_roster(list(existing or []))` |
| `ming_sim/db.py` | 20910 | KEEP_LIVE_NORMALIZE | ADR 0053 名单规范化真源 | `add = GameDB._normalize_participant_roster(` |

静默 id 残留：0。

本轮 FIX：`_merge_directive_payload` 先 normalize 新名单一次；空则 pop；非空再 merge(old, new_roster)。
