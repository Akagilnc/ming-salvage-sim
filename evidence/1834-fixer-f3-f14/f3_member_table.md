# F3/F14 full-repo bidirectional member table

## Enum scope (mechanical; reused old script, no new classifier)
```sh
env MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD \
  ../Ming_LLM/.venv/bin/python evidence/1834-fixer-f9-f12-f3/scripts/enum_f3_free_text_asserts.py
```
- Current enum hits: **1923** (tests/ + web/**/*.test.*; SKIP evidence/node_modules).
- Old disposition rows reviewed: **1979** (KEEP 1911 + FIX 68).
- Full-repo no-assert pytest scan: **7** (semantic, not auto-delete).
- F14 stage-label hits in evidence/+scripts/: **26**.
- Purge delete-diff overlay (prior round free-prose dels): **231**.
- Evidence/scripts probes (AST assert + stage check()): **6** (0 prose asserts; structural stage checks only).
- Canonical disposition file: `f3_full_bidirectional_disposition.jsonl` (not delete-diff-only).
- Legacy overlay kept as `f3_bidirectional_disposition.jsonl` (prior purge-diff 251 rows; superseded for scope claims).

## Counts by member_set
- `EMPTY_SHELL_DELETED`: 7
- `FULLREPO_NO_ASSERT_SCAN`: 7
- `LEN_SUBSTITUTE`: 1
- `OLD_FIX_BIDIR`: 68
- `OLD_KEEP_BIDIR`: 1911
- `PURGE_DELETE_DIFF_OVERLAY`: 231
- `RESTORED_LEGAL_CONTRACT`: 12
- `EVIDENCE_SCRIPTS_PROBE`: 6
- `BROKEN_SUBSTITUTE_CLEANUP`: 1

## OLD_KEEP_BIDIR (all KEEP)
All **1911** old KEEP rows: `KEEP_CONFIRMED` / `STILL_PRESENT`.
Basis breakdown:
- `structured_enum_or_identity_field`: 922
- `cli_fixed_option_or_error_identifier`: 406
- `ui_identity_or_fixed_label_or_technical`: 280
- `permission_or_negative_contract`: 161
- `ui_fixed_chrome_p7`: 74
- `verbatim_transmission_equality`: 56
- `structured_enum_identity_transport_or_contract`: 8
- `path_or_directory_structure`: 4

## OLD_FIX_BIDIR
- `KEEP_DELETED_FREE_PROSE`: 66
- `RECLASS_RESTORE_STRUCTURED_FIELD`: 1
- `RECLASS_RESTORE_CALL_INPUT`: 1

### RECLASS_RESTORE (old FIX was misclass)
- `tests/test_due_review_621.py:816` :: `criterion_text_free_equality` → `RECLASS_RESTORE_STRUCTURED_FIELD`
- `tests/test_scene_llm_1836.py:145` :: `hand_round2_free_prose` → `RECLASS_RESTORE_CALL_INPUT`

### KEEP_DELETED_FREE_PROSE from old FIX (correctly remain deleted)
- count: 66
- full rows in `f3_full_bidirectional_disposition.jsonl` member_set=OLD_FIX_BIDIR

## RESTORED_LEGAL_CONTRACT (12)
- `tests/test_scene_llm_1836.py` :: `assert calls == [f"宣{character.name}", "边饷如何？"]` :: `RESTORE_CALL_INPUT` :: present=True
- `tests/test_material_directory_1830.py` :: `assert tools["read_material"](spaced_rel) == "经历正文\n"` :: `RESTORE_DISK_BYTES` :: present=True
- `tests/test_material_directory_1830.py` :: `assert tools["read_material"](gazette_rel) == "本月邸报\n"` :: `RESTORE_DISK_BYTES` :: present=True
- `tests/test_material_directory_1830.py` :: `assert original in tools["read_material"](secret_path)` :: `RESTORE_DISK_BYTES` :: present=True
- `tests/test_due_review_621.py` :: `assert scene["origin_context"] == "三年火器见眉目"` :: `RESTORE_STRUCTURED_FIELD` :: present=True
- `tests/test_due_review_621.py` :: `assert scene["criterion_text"] == "火器见眉目"` :: `RESTORE_STRUCTURED_FIELD` :: present=True
- `web/src/appDurableWiring.test.tsx` :: `expect(masthead).toContain("天启七年九月");` :: `RESTORE_FIXED_UI` :: present=True
- `web/src/components/modals.test.tsx` :: `expect(document.querySelector(".chat-message.thinking span")?.textContent).toBe(` :: `RESTORE_IDENTITY` :: present=True
- `web/src/components/modals.test.tsx` :: `expect(mastSept).toContain("天启七年九月");` :: `RESTORE_FIXED_UI` :: present=True
- `web/src/components/modals.test.tsx` :: `expect(mastDec).toContain("天启七年十二月");` :: `RESTORE_FIXED_UI` :: present=True
- `web/src/components/settlementGazettePanel.test.tsx` :: `expect(host.textContent).toContain("天启七年十月");` :: `RESTORE_FIXED_UI` :: present=True
- `web/src/components/situation.test.tsx` :: `expect(doc!.textContent).toContain("杨嗣昌");` :: `RESTORE_IDENTITY` :: present=True

## EMPTY_SHELL_DELETED (7)
- `tests/test_cli_runner_error_typed_1299.py` :: `test_clichat_normal_reply_still_returns` :: gone=True :: only assert was model reply substring
- `tests/test_decree_commitment_settlement_229.py` :: `test_commitment_progress_contexts_are_structured` :: gone=True :: only asserts were CLI output prose
- `web/src/components/modals.test.tsx` :: `does not treat an ordinary history reduction as a withdrawal` :: gone=True :: no remaining proof after content asserts removed
- `web/src/components/modals.test.tsx` :: `shows the whole chronological night instead of a selected-minister window` :: gone=True :: no remaining proof after content asserts removed
- `web/src/components/situation.test.tsx` :: `detail modal keeps parentheses when bar meanings are present` :: gone=True :: qualitative prose removed; empty shell
- `web/src/staleGuard.test.tsx` :: `未切人时响应正常应用不被守卫误丢` :: gone=True :: fixture reply prose removed; empty shell
- `web/src/staleGuard.test.tsx` :: `未切人时历史正常加载不被误丢` :: gone=True :: fixture history prose removed; empty shell

## FULLREPO_NO_ASSERT_SCAN (semantic; not word-shape delete)
- `tests/test_enrich_list_guards.py::test_inertia_ongoing_non_dict_no_crash` :: `NOT_EMPTY_NO_THROW_CONTRACT` :: no-crash / tolerates input is the stated contract
- `tests/test_fiscal_tick.py::test_fiscal_golden` :: `NOT_EMPTY_HELPER_ASSERT` :: delegates to helper assert (_assert_*)
- `tests/test_fiscal_tick.py::test_fiscal_g9_three_tick_death_spiral` :: `NOT_EMPTY_HELPER_ASSERT` :: delegates to helper assert (_assert_*)
- `tests/test_issue_entities.py::test_apply_score_extraction_accepts_flat_faction_scalar` :: `NOT_EMPTY_NO_THROW_CONTRACT` :: no-crash / tolerates input is the stated contract
- `tests/test_issue_entities.py::test_apply_score_extraction_tolerates_null_field` :: `NOT_EMPTY_NO_THROW_CONTRACT` :: no-crash / tolerates input is the stated contract
- `tests/test_llm_channel_config.py::test_verify_llm_available_api_empty_content_passes` :: `NOT_EMPTY_NO_THROW_CONTRACT` :: smoke: successful return / no raise is the proof
- `tests/test_llm_channel_config.py::test_verify_llm_available_api_empty_content_none_passes` :: `NOT_EMPTY_NO_THROW_CONTRACT` :: smoke: successful return / no raise is the proof


## EVIDENCE_SCRIPTS_PROBE (6)
Reused structural probe script (no new parallel probe). AST found **0** `assert` with free prose; 6 `check("…")` stage labels (F14 surface).
- `evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py:204` OPEN_WORLD
- `evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py:209` OPEN_PUBLIC
- `evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py:220` CALENDAR_ADVANCED_WORLD
- `evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py:225` CALENDAR_ADVANCED_PUBLIC
- `evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py:235` RESTORE_WORLD
- `evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py:240` RESTORE_PUBLIC

## BROKEN_SUBSTITUTE_CLEANUP (1)
- `web/src/appDurableWiring.test.tsx` :: `#1849` :: `REMOVE_BROKEN_DOM_SUBSTITUTE` :: keep call-routing; drop false DOM waits

## REMOVE_LEN_SUBSTITUTE (1)
- `tests/test_audience_restore_505.py` :: `assert len(replies) == 1`

## F14 stage labels (mechanical)
```sh
rg -n '\b(OPEN_|CLOSED_|CALENDAR_ADVANCED_|RESTORE_)(WORLD|PUBLIC)\b' evidence scripts -g '*.py' -g '*.txt' -g '*.md' -g '*.sh'
# exclude: f14_stage_labels.jsonl / f3_*disposition*.jsonl / enum_*.txt / f3_probe_enum.jsonl (self-feedback)
```
- Scoped files: **58**; token hits: **70**; actions: `{'STAGE_LABEL_OK': 44, 'CORRECT_LIVE_LABEL': 14, 'NEW_EVIDENCE_MENTION_CLOSED': 8, 'HISTORICAL_OUTPUT_UNCHANGED': 4}`
- Live script `CLOSED_*`: **0** (must be 0).
- Scope note: `evidence/** + scripts/** ; suffixes .py/.txt/.md/.sh ; exclude disposition/enum/f14 jsonl dumps to avoid self-feedback`

- `evidence/1834-fixer-f3-f14/probe-current.txt:2` :: `OPEN_WORLD` :: `STAGE_LABEL_OK` :: open/restore stage label
- `evidence/1834-fixer-f3-f14/probe-current.txt:3` :: `OPEN_PUBLIC` :: `STAGE_LABEL_OK` :: open/restore stage label
- `evidence/1834-fixer-f3-f14/probe-current.txt:4` :: `CALENDAR_ADVANCED_WORLD` :: `CORRECT_LIVE_LABEL` :: calendar advance only; not affair_status=closed
- `evidence/1834-fixer-f3-f14/probe-current.txt:5` :: `CALENDAR_ADVANCED_PUBLIC` :: `CORRECT_LIVE_LABEL` :: calendar advance only; not affair_status=closed
- `evidence/1834-fixer-f3-f14/probe-current.txt:6` :: `RESTORE_WORLD` :: `STAGE_LABEL_OK` :: open/restore stage label
- `evidence/1834-fixer-f3-f14/probe-current.txt:7` :: `RESTORE_PUBLIC` :: `STAGE_LABEL_OK` :: open/restore stage label
- `evidence/1834-fixer-f9-f12-f3/probe-current.txt:14` :: `OPEN_WORLD` :: `STAGE_LABEL_OK` :: open/restore stage label
- `evidence/1834-fixer-f9-f12-f3/probe-current.txt:15` :: `OPEN_PUBLIC` :: `STAGE_LABEL_OK` :: open/restore stage label
- `evidence/1834-fixer-f9-f12-f3/probe-current.txt:16` :: `CLOSED_WORLD` :: `HISTORICAL_OUTPUT_UNCHANGED` :: do not rewrite; calendar-advance mislabel in old run
- `evidence/1834-fixer-f9-f12-f3/probe-current.txt:17` :: `CLOSED_PUBLIC` :: `HISTORICAL_OUTPUT_UNCHANGED` :: do not rewrite; calendar-advance mislabel in old run
- `evidence/1834-fixer-f9-f12-f3/probe-current.txt:18` :: `RESTORE_WORLD` :: `STAGE_LABEL_OK` :: open/restore stage label
- `evidence/1834-fixer-f9-f12-f3/probe-current.txt:19` :: `RESTORE_PUBLIC` :: `STAGE_LABEL_OK` :: open/restore stage label
- `evidence/1834-fixer-f9-f12-f3/probe.txt:11` :: `OPEN_WORLD` :: `STAGE_LABEL_OK` :: open/restore stage label
- `evidence/1834-fixer-f9-f12-f3/probe.txt:12` :: `OPEN_PUBLIC` :: `STAGE_LABEL_OK` :: open/restore stage label
- `evidence/1834-fixer-f9-f12-f3/probe.txt:13` :: `CLOSED_WORLD` :: `HISTORICAL_OUTPUT_UNCHANGED` :: do not rewrite; calendar-advance mislabel in old run
- `evidence/1834-fixer-f9-f12-f3/probe.txt:14` :: `CLOSED_PUBLIC` :: `HISTORICAL_OUTPUT_UNCHANGED` :: do not rewrite; calendar-advance mislabel in old run
- `evidence/1834-fixer-f9-f12-f3/probe.txt:15` :: `RESTORE_WORLD` :: `STAGE_LABEL_OK` :: open/restore stage label
- `evidence/1834-fixer-f9-f12-f3/probe.txt:16` :: `RESTORE_PUBLIC` :: `STAGE_LABEL_OK` :: open/restore stage label
- `evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py:204` :: `OPEN_WORLD` :: `STAGE_LABEL_OK` :: open/restore stage label
- `evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py:209` :: `OPEN_PUBLIC` :: `STAGE_LABEL_OK` :: open/restore stage label
- `evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py:220` :: `CALENDAR_ADVANCED_WORLD` :: `CORRECT_LIVE_LABEL` :: calendar advance only; not affair_status=closed
- `evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py:225` :: `CALENDAR_ADVANCED_PUBLIC` :: `CORRECT_LIVE_LABEL` :: calendar advance only; not affair_status=closed
- `evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py:235` :: `RESTORE_WORLD` :: `STAGE_LABEL_OK` :: open/restore stage label
- `evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py:240` :: `RESTORE_PUBLIC` :: `STAGE_LABEL_OK` :: open/restore stage label

## Class boundary (judge F3)
Keep: deterministic call inputs, disk fixed bytes, structured identity, fixed UI fields (periodLabel), structured DTO fields.
Delete: generated/fixture free prose locks; empty shells that lost behavioral proof; length/non-empty substitutes.
Do not auto-classify by CJK/word shape; do not claim full-repo from delete-diff alone.
