# #1853 fixer enum（SQL-FAILURE / RETIRED-SCENE / TEST-LIFECYCLE）

## Class1 SQL-FAILURE-AS-EMPTY

谓词（判词定义全文，未收窄）：
- 全仓 tracked 生产 Python（排除 archive/tests/scripts/artifacts）
- AST：`try` 体含 `execute|executemany|executescript|fetchone|fetchall|fetchmany`
- handler 捕获 sqlite/宽 Exception 且 **不** re-raise、**不** logger.exception/error
- 且返回/赋值为空业务态（None/False/0/''/[]/{} 或 名 out 空图）

```bash
python3 -c 'see this directory script inline in fixer run; TSV: class1-sql-failure-as-empty-post.tsv'
```

修后期望：`IN_CLASS=0`。EXCLUDED=有 raise 或 log；SWALLOW_OTHER=非空业务态处置（如 typed refusal）。

## Class2 RETIRED-SCENE-COMMANDS

谓词：
- 词表符号 `STAY_ATTEND_COMMANDS|AMBIGUOUS_CLOSE_COMMANDS|CMD_STAY_ATTEND|CMD_AMBIGUOUS_CLOSE|TAG_STAY_ATTEND`
- 写缝/短路 `stay_attend_in_audience|_ensure_close_night_confirm_cue`
- 剧情原句 `留下听着|今日就到这里吧`
- 扫描 `.py/.ts/.tsx`，排除 archive/docs/evidence/artifacts

修后期望：生产与 tests 零命中；保留 `COURT_BREAK_COMMANDS` / `CMD_CLOSE_NIGHT` / 宣召。

## Class3 TEST-LIFECYCLE-COPY

谓词：
- `tests/**/*.py` AST 类同时实现 `create_chat_turn` + `persist_minister_reply` + `list_in_flight_chat_turns`
- COPY：在飞筛选复制 status/generating 规则，或 persist 内维护 status 状态机
- KEEP：固定返回 / 纯调用记录（如 `_RecordingDB`）

修后期望：COPY=0；`_RecordingDB` KEEP。
