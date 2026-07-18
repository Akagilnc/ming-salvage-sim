# Pytest fixture 选用约定

- `read_game`：只用于不改变 DB、state、content 的纯读盘面测试。它按测试 session
  只创建一次真实生产开局盘面，并启用 SQLite `query_only`，误写会立即失败。
- `game`：凡写库、改变 state/content、验证事务或要求用例级隔离，均使用这个
  function-scope fixture；它始终走真实 `GameDB → seed_static_data → load_state`
  生产入口，不 mock 被测系统。
- `saved_game`：仅用于确实依赖玩过存档运行时历史、且尚未 deterministic 化的测试。

不能为了迁移 fixture 改弱断言。拿不准是否纯读时，保留 `game`。
