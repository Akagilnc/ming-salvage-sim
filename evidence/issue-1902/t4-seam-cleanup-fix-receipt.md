# #1902 修内司 T4 旧接缝收口（终判 01a11209 续）

- 基线：9d1cb9e22
- FIX SHA：`3b5d1808a7b59558fa4449dff235948748cafea0`
- 终判 T4 剩余：启动补跑搬迁后旧测试接缝 + Web 顶层无用导入

## 修复
1. 删除 `web_app.py` 顶层 `catch_up_pending_translations` 导入（源轮重试仍局部 import）。
2. `test_startup_catchup_uses_ticketed_gate_not_bare`：
   - patch `audience_translation.catch_up_pending_translations`（现役共核接缝）
   - stub `list_startup_translation_catch_up` 非空，确保走进补跑
   - 仍断言 ticketed gate 契约与 ticket._done

## 测试
70 passed in 8.93s（七 BIN；含 startup 两案 + web_entry/restore/cli_entry/play_turn）
