# F3 bidirectional disposition — member table

## Enum commands
```sh
git diff --unified=0 52809cdf3 HEAD -- tests/ web/   # prior purge dels
git diff --unified=0 HEAD -- tests/ web/             # this-round overlay
```

Prior assert deletions: 243; this-round restore hits: 12; missed: 0; keep-deleted: 231; empty-shell deletes: 7.

## RESTORE_THIS_ROUND
- `tests/test_due_review_621.py` :: `assert scene["origin_context"] == "三年火器见眉目"` :: RESTORE_STRUCTURED_FIELD :: due scene structured field
- `tests/test_due_review_621.py` :: `assert scene["criterion_text"] == "火器见眉目"` :: RESTORE_STRUCTURED_FIELD :: due scene structured field
- `tests/test_material_directory_1830.py` :: `assert tools["read_material"](spaced_rel) == "经历正文\n"` :: RESTORE_DISK_BYTES :: write→read_material fixed bytes
- `tests/test_material_directory_1830.py` :: `assert tools["read_material"](gazette_rel) == "本月邸报\n"` :: RESTORE_DISK_BYTES :: write→read_material fixed bytes
- `tests/test_material_directory_1830.py` :: `assert original in tools["read_material"](secret_path)` :: RESTORE_DISK_BYTES :: secret-order CR bytes survive read
- `tests/test_scene_llm_1836.py` :: `assert calls == [f"宣{character.name}", "边饷如何？"]` :: RESTORE_CALL_INPUT :: deterministic agent call input
- `web/src/appDurableWiring.test.tsx` :: `expect(masthead).toContain("天启七年九月");` :: RESTORE_FIXED_UI :: periodLabel positive
- `web/src/components/modals.test.tsx` :: `expect(document.querySelector(".chat-message.thinking span")?.textContent).toBe("洪承畴");` :: RESTORE_IDENTITY :: selected minister identity
- `web/src/components/modals.test.tsx` :: `expect(mastSept).toContain("天启七年九月");` :: RESTORE_FIXED_UI :: periodLabel positive
- `web/src/components/modals.test.tsx` :: `expect(mastDec).toContain("天启七年十二月");` :: RESTORE_FIXED_UI :: periodLabel positive
- `web/src/components/settlementGazettePanel.test.tsx` :: `expect(host.textContent).toContain("天启七年十月");` :: RESTORE_FIXED_UI :: periodLabel positive
- `web/src/components/situation.test.tsx` :: `expect(doc!.textContent).toContain("杨嗣昌");` :: RESTORE_IDENTITY :: memorial author identity

## RESTORE_MISSED (must be empty)
- (none)

## DELETE_EMPTY_SHELL
- `tests/test_cli_runner_error_typed_1299.py` :: `test_clichat_normal_reply_still_returns` :: only assert was model reply substring
- `tests/test_decree_commitment_settlement_229.py` :: `test_commitment_progress_contexts_are_structured` :: only asserts were CLI output prose
- `web/src/components/modals.test.tsx` :: `does not treat an ordinary history reduction as a withdrawal` :: no remaining proof after content asserts removed
- `web/src/components/modals.test.tsx` :: `shows the whole chronological night instead of a selected-minister window` :: no remaining proof after content asserts removed
- `web/src/components/situation.test.tsx` :: `detail modal keeps parentheses when bar meanings are present` :: qualitative prose removed; empty shell
- `web/src/staleGuard.test.tsx` :: `未切人时响应正常应用不被守卫误丢` :: fixture reply prose removed; empty shell
- `web/src/staleGuard.test.tsx` :: `未切人时历史正常加载不被误丢` :: fixture history prose removed; empty shell

## REMOVE_LEN_SUBSTITUTE
- `tests/test_audience_restore_505.py` :: `assert len(replies) == 1` :: REMOVED_THIS_ROUND

## KEEP_DELETED_FREE_PROSE (231)
Not mechanically restored. Full rows in `f3_bidirectional_disposition.jsonl`.

## Class boundary (judge F3)
Keep: deterministic call inputs, disk fixed bytes, structured identity, fixed UI fields (periodLabel), structured DTO fields from fixture.
Delete: generated/fixture free prose locks; empty shells that lost behavioral proof; length/non-empty substitutes.
