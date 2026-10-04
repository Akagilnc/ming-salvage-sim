# J6 — `pytest.raises(..., match=...)` disposition (#1900)

Scan scope: `tests/**/*.py` (Python), all lines with `pytest.raises` and `match=` on the same line.

## Universe counts

| Metric | Count |
|--------|------:|
| **Live `match=` sites** (current worktree) | 57 |
| **Prior migrated** (brew tests; `match=` already dropped) | 7 |
| **Disposition rows** (`j6-exception-match-disposition.jsonl`) | 66 |

### Classification (live + prior)

| Classification | Count | Meaning |
|----------------|------:|---------|
| `injected` | 56 | Fixture / monkeypatch sentinel (`boom`, `inject`, `模拟`, `LLM down`, …) |
| `ambiguous` | 8 | Production-like Chinese or informal locks without `ming_sim` raise literal |
| `production_wording` | 0 live (2 migrated this pass) | Substring of real `ming_sim` RuntimeError text |

### Recommended action

| Action | Count |
|--------|------:|
| `retain` | 55 live |
| `migrate` (drop `match=`, keep exc type + result asserts) | 9 total (2 applied now + 7 brew prior) |

## Production wording hits (migrated)

| File | Test | Line | `match` | Notes |
|------|------|-----:|---------|-------|
| `tests/test_transaction_boundary.py` | `test_backup_to_inside_atomic_fails_loud` | 322 | `atomic` | `db.backup_to` guard: `backup_to 在 atomic 事务内禁止…` |
| `tests/test_transaction_boundary.py` | `test_connection_rollback_attempts_all_runtime_callbacks` | 345 | `runtime rollback callback` | `runtime rollback callback failed (…)` in `ming_sim/applier.py` |

## Ambiguous Chinese / DB phrasing (prior migrate)

| File | Tests | `match` patterns |
|------|-------|------------------|
| `tests/test_relation_brew_636.py` | 5 fail-loud boundary tests | `认领库不可写`, `落定库不可写`, `pending 库不可写`, `酿制手程序错误` |
| `tests/test_faction_brew_637.py` | 2 fail-loud boundary tests | `派系认领库不可写`, `派系落定库不可写` |

No `ming_sim` raise uses these exact strings; tests inject them on doubles. `match=` removed earlier; type + DB/pending asserts retained.

## Live retain highlights (production-adjacent but injected)

- **Rollback / settlement probes**: `chain persistence failed`, `transient settlement crash`, `rollback probe`, `crash after flush`, `outer rollback` — all raised inside test hooks, not `ming_sim`.
- **Menu / IO doubles**: `close failed`, `locked` — thrown by `SimpleNamespace` / `os.remove` patches.
- **SQLite probe**: `BEGIN` — substring of `simulated BEGIN failure` only (`test_begin_failure_at_entry_restores_flags`).
- **Section rejection simulators**: `模拟 insert_issue`, `模拟 close_issue`, etc. — explicit `模拟` prefix.

## Files edited this pass

- `tests/test_transaction_boundary.py` — dropped `match=` on 2 production-wording guards.
- `evidence/1900-j18-j6-retire-fixer/j6-exception-match-disposition.jsonl`
- `evidence/1900-j18-j6-retire-fixer/j6-exception-match-summary.md`

## Verification

```sh
python3 -m pytest tests/test_transaction_boundary.py::test_backup_to_inside_atomic_fails_loud \
  tests/test_transaction_boundary.py::test_connection_rollback_attempts_all_runtime_callbacks -q
```
