# #1902 修内司 T3/T5/T6 续修回执 r3

- 基线：e6c660a99
- 判词：inspector 复裁 continue（T3 无痕 JSON；T5 空转译空跑；T6 旧流式入口）
- **不宣称合并/关票**

## T3
legacies_payload：JSONDecodeError / 非 dict 归 {} **且** logger.warning 带 legacy_id 与真因；RuntimeError 仍上抛。

## T5
test_translate_empty_success… 改走 `_scene_turn` 真建轮+落回话+调度；断言 pending 零增量且 `get_story_extract_status==done`（与失败 pending 可区分）。

## T6
删除 `run_agent_stream_text`、独占 `_THINKING_STREAM_CHAR_LIMIT`、`record_stream_metrics` 及三则专属测试；现役流式仍走 `run_agent_text` transport / scene transport。

## 测试
201 passed in 6.17s（七 BIN）
