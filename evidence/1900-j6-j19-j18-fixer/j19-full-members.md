# J19 全仓成员表（权威）

类定义：拆除按人物 id 静默保留先项；复用 normalize + 一次 merge；空 incoming pop 保留旧名册。

| path | line | disposition | text |
|---|---|---|---|
| `ming_sim/db.py` | 13768 | KEEP_LIVE_NORMALIZE |         base_roster = self._normalize_participant_roster( |
| `ming_sim/db.py` | 14446 | KEEP_LIVE_APPEND |     def append_decree_dossier_participants( |
| `ming_sim/db.py` | 17610 | KEEP_LIVE_SHARED |             incoming["participant_roster"] = self.merge_participant_ro |
| `ming_sim/issues.py` | 6910 | KEEP_LIVE_APPEND |             added = db.append_decree_dossier_participants(dossier_id,  |
| `ming_sim/declaration_dispatch.py` | 1055 | KEEP_LIVE_NORMALIZE |         shaped = db._normalize_participant_roster(list(entries), stric |
| `ming_sim/declaration_dispatch.py` | 1076 | KEEP_LIVE_SHARED |     payload["participant_roster"] = GameDB.merge_participant_roster_en |
| `ming_sim/rescript_draft.py` | 193 | KEEP_LIVE_NORMALIZE | # 机械三档与条目形状唯一真源＝GameDB._normalize_participant_roster（ADR 0053）； |
| `ming_sim/decree_vocabulary.py` | 75 | KEEP_LIVE_NORMALIZE | # GameDB._normalize_participant_roster；此处只登记键名与 capability 派生方式。 |
| `ming_sim/cli_backend.py` | 2073 | KEEP_LIVE_NORMALIZE |     canonical_roster = db._normalize_participant_roster( |

静默 id / 平行 loop 残留：0（见 rescan-final.txt）。
