# 1834 F21-R / F22-R / F25 成员表

## F21 自由正文保真（续）
| 成员 | 处置 |
|---|---|
| issues.py append_participants role 写入 strip | FIX 保原文 |
| issues.py fiscal create display strip（三处：806/8750/8783） | FIX 保原文 |
| context.py summary→identity strip or 默认 | FIX 保原文（materials 供料经 character_context_with_db） |
| 机器键 / 枚举 / 局部判空 | KEEP |

## F22 退役闭包残留
| 成员 | 处置 |
|---|---|
| record_stream_metrics + agents 未用 import | DELETE |
| _THINKING_STREAM_CHAR_LIMIT | DELETE |
| _assert_utf8 | DELETE |
| minister_speaker_role | DELETE |
| rescript_draft 退役链未用 imports | DELETE |
| action_materialize write_locality 未用 import（消费者改直连 execution_pressure） | FIX import |
| test fixtures _retire/_add/_valid/_legal_item | DELETE |

## F25
| tests/test_cli_play_turn.py 提示词断言 | DELETE；保留 turn/phase 结构化断言 |
