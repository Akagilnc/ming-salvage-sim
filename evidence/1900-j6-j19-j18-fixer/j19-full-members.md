# J19 全仓成员表（权威）

类定义：拆除按人物 id 静默保留先项；复用 normalize/append 现役语义。

| path | line | disposition | why | text |
|---|---|---|---|---|
| `ming_sim/declaration_dispatch.py` | 1055 | KEEP_LIVE_NORMALIZE | 权威 normalize | shaped = db._normalize_participant_roster(list(entries), strict_struct |
| `ming_sim/declaration_dispatch.py` | 1076 | KEEP_LIVE_SHARED | 现役 normalize+equality 单缝 | payload["participant_roster"] = GameDB.merge_participant_roster_entrie |
| `ming_sim/issues.py` | 6910 | KEEP_LIVE_APPEND | 持久化追加（同人异档 raise） | added = db.append_decree_dossier_participants(dossier_id, [{ |
| `ming_sim/db.py` | 13768 | KEEP_LIVE_NORMALIZE | 权威 normalize | base_roster = self._normalize_participant_roster( |
| `ming_sim/db.py` | 14446 | KEEP_LIVE_APPEND | 持久化追加（同人异档 raise） | def append_decree_dossier_participants( |
| `ming_sim/db.py` | 17611 | KEEP_LIVE_SHARED | 现役 normalize+equality 单缝 | incoming["participant_roster"] = self.merge_participant_roster_entries |
| `ming_sim/decree_vocabulary.py` | 75 | KEEP_LIVE_NORMALIZE | 权威 normalize | # GameDB._normalize_participant_roster；此处只登记键名与 capability 派生方式。 |
| `ming_sim/rescript_draft.py` | 193 | KEEP_LIVE_NORMALIZE | 权威 normalize | # 机械三档与条目形状唯一真源＝GameDB._normalize_participant_roster（ADR 0053）； |
| `ming_sim/cli_backend.py` | 2073 | KEEP_LIVE_NORMALIZE | 权威 normalize | canonical_roster = db._normalize_participant_roster( |
| `tests/test_decree_dossiers_571.py` | 82 | KEEP_LIVE_APPEND | 持久化追加（同人异档 raise） | db.append_decree_dossier_participants(dossier_id, [{ |
| `tests/test_character_knowledge_489.py` | 712 | KEEP_LIVE_APPEND | 持久化追加（同人异档 raise） | db.append_decree_dossier_participants(dossier_id, [{ |
| `tests/test_secret_dossier_participants_1252.py` | 66 | KEEP_LIVE_APPEND | 持久化追加（同人异档 raise） | db.append_decree_dossier_participants(dossier_id, [{ |