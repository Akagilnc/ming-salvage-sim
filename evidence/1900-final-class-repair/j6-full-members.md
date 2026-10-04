# J6 完整候选处置表（复扫后）

谓词：monkeypatch.setattr、call_oracle、marker、fixed_translate、direction、prose/OperationalError、helper 命名；含 web mock 行。
不以点名文件限界。LLM/IO 边界 stub 默认保留（禁止的是顶替被测行为）。

## 须修/须删残留

**0**（night_said 正文锁、apply_legacy_pct/grant_arrival_bounds 实现 oracle、点名 spy/标记伪证均已处置）。

## 处置计数

- KEEP_BOUNDARY_STUB: 308
- KEEP_OTHER: 188
- NEEDS_READ_PROSE: 49
- KEEP_MONTH_TRANSLATE_BOUNDARY: 26
- KEEP_ORDERING_OR_QUAL: 15
- KEEP_NAME_COLLISION: 10
- KEEP_QUALITATIVE_DIRECTION: 10
- KEEP_BOUNDARY: 6
- NEEDS_READ: 3
- KEEP_GATE_CONTRACT: 1
- KEEP_STRUCTURED_CUTOFF: 1
- KEEP_INDEPENDENT_CONST: 1

## Web mock 行合计 145 → KEEP_UI_BOUNDARY

- `web/src/components/modals.test.tsx`: 50
- `web/src/useSettlementFlow.test.tsx`: 25
- `web/src/components/gameMenu.test.tsx`: 18
- `web/src/components/menuPage.test.tsx`: 13
- `web/src/components/decisionModal.test.tsx`: 13
- `web/src/components/drawers.test.tsx`: 6
- `web/node_modules/exponential-backoff/src/backoff.spec.ts`: 5
- `web/node_modules/exponential-backoff/src/delay/always/always.delay.spec.ts`: 4
- `web/src/appDurableWiring.test.tsx`: 3
- `web/node_modules/simple-update-notifier/src/index.spec.ts`: 3
- `web/node_modules/simple-update-notifier/src/getDistVersion.spec.ts`: 2
- `web/node_modules/simple-update-notifier/src/hasNewVersion.spec.ts`: 2
- `web/src/components/settlementGazettePanel.test.tsx`: 1
