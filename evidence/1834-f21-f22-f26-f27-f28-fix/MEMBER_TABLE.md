#1834 本轮五类成员表

## F21 自由正文保真未贯穿持久写入链
| 成员 | 处置 | 依据 |
|---|---|---|
| `credit_events._narrative_context` | FIX | 共享搬运接缝：判空用 `.strip()` 副本，返回原文；写入链（fulfillment/disposition/urge context）保真 |
| 其它 assign_return 候选（tenure/account/enum/config/path/VERSION…） | KEEP | 机器键/枚举/配置，非自由正文持久写入 |
| 核销 `f16_disposition_member_locs.tsv` credit_events.py:98 = machine_key_enum_normalize | CORRECT→FIX | 误作机器键；现为 free-prose haul |

## F22 退役排序闭包
| 成员 | 处置 |
|---|---|
| `COMMAND_POWER_RANK` / `command_power_rank` | DELETE |
| `tests/test_execution_tenure_613.py` | DELETE |
| `normalize_appointment_tenure` + `supervision` 消费 | KEEP |
| `appointment_tenure_from` / `APPOINTMENT_TENURES` | KEEP |

## F26 成功正文词表归因
| 成员 | 处置 |
|---|---|
| `fail_if_llm_error` + markers | DELETE |
| 调用点 llm_model / session | DELETE 调用 |
| `_AGY_AUTH_MARKERS` + 消费 | DELETE |
| `test_run_agy_auth_race_*` | DELETE |
| transport 耗尽案 auth 注入 | REWRITE→空输出结构化 |
| ERROR status / 退出码 / 空输出 / 原生异常 | KEEP |

## F27 stderr/横幅猜正文
| 成员 | 处置 |
|---|---|
| codex `(stdout+stderr).split("OpenAI Codex v")` | DELETE |
| `test_run_codex_stdout_empty_fallback` | DELETE |
| stdout / final_text 结构化终包 | KEEP |
| 核销「banner split without strip」KEEP | CORRECT→DELETE |

## F28 purpose 散文派生处分
| 成员 | 处置 |
|---|---|
| `_grace_purpose` 词表链及 grant 收集/叙事 | DELETE |
| grant_grace 写边分支 | DELETE |
| 准宽限专属测试段 | DELETE |
| cancels→reject_grace/reject_remonstrance | KEEP |
| fulfillment / disposition / write_credit_event | KEEP |
