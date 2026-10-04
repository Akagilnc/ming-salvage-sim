# J6 成员表 — 盯文、内部伪证及未经过失败行为的初始状态证明

枚举命令见 [`enum-cmd.txt`](enum-cmd.txt)；机器表 [`j6-full-members.json`](j6-full-members.json)。

类定义（判词）：清除盯文、内部伪证及未经过失败行为的初始状态证明；失败路径须实际经过；必要拒收负向保留。

| 路径 | 行 | 种类 | 处置 | 依据 |
|---|---|---|---|---|
| `tests/test_audience_translate_1837.py` | 269–276 | PROSE_IN_PROMPT / LEAK_VIA_PROSE | **FIX** | 机械搜「后轮问/后轮答」制造泄漏标记；改搜结构化 `[chat_turn_id={later}]` |
| `tests/test_audience_translate_1837.py` | 319 | 外部结构化断言 | **KEEP** | 断言落库 `scene_facts` 无泄漏标记 body，属外部可见结果 |
| `tests/test_audience_background.py` | 256,261 | DRAFT_TEXT_ABSENCE | **FIX** | 以草案正文不出现当隐私哨兵；改断言结构化 `draft-{id}` 未入 opening/目录 |
| `tests/test_menu_lifecycle_drain_396.py` | 89 | ARCHIVE_FAIL_NO_WORKER_PROOF | **FIX** | 失败案未证明 move 曾执行；补 move 尝试证据 + wait |
| `tests/test_menu_lifecycle_drain_396.py` | 161 | ARCHIVE_FAIL_NO_WORKER_PROOF | **FIX** | 同上，WAL 失败回滚须见主库/WAL move 尝试 |
| `tests/test_menu_lifecycle_drain_396.py` | 199 | ARCHIVE_FAIL_NO_CLOSE_PROOF | **FIX** | `moves==[]` 在未跑 worker 时亦真；补 close 尝试证据 |
| `tests/test_menu_lifecycle_drain_396.py` | 122 | ARCHIVE_SUCCESS | **KEEP** | 成功案已 wait_until saves，有外部归档结果 |
| `tests/test_cli_backend.py` | 514,657 | argv/config token | **KEEP_CONFIG** | 非叙事盯文；CLI 配置开关 argv 契约 |
| `tests/test_audience_travel_gating_670.py` | 147–148,176–177,708–709 | 禁喷固定承旨句 | **KEEP_ANTI_TEMPLATE** | 负向禁模板句（P7），非自由叙事伪证 |
| `tests/test_army_card_status_1501.py` | 173 | DB status 值不泄漏 | **KEEP_NONLEAK** | 已先断言无 `status` 键；比较 DB 种子值不进载荷字段，非锁叙事措辞 |

点名样本非白名单；上表为谓词命中后的全量处置。
