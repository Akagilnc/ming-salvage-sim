# #1902 修内司 K1 回执（退役身份兼容路径）

- 判词续：inspector continue，K1 only
- 基线：`5e9275280`
- **不宣称合并/关票**；未 amend/stash/push

## 类：退役身份兼容路径搬而未删

- **谓词**：被取代的旧身份／跨身份转交／兼容路径在搬迁后仍保留；读写契约已排除的旧 owner 分支。
- **枚举**：`rg -n 'owner\s*!=\s*target|owner_last|present_as|真实 owner|按 owner 撤' ming_sim web_app.py`
- **成员（修前）**：
  - `GameSession.undo_last_audience_chat` 殿上→具名 owner 转交／递归
  - `GameSession.can_undo_last_audience_chat` 殿上 list_hall 特判（旧拼朝臣轮遗迹，现与 `can_undo_last_chat_turn(殿上)` 同形冗余）
  - `WebGame.undo_last_chat` requested/present_as 呈现分流

## 修复

删除上述三处；撤回资格统一 `can_undo_last_chat_turn(minister_name)`；undo 直接按请求名取末轮；Web 只按 core.minister_name 投影。

## 复扫

生产无 owner!=target／owner_last／present_as；仅删除说明注释。

## 测试

```
171 passed in 8.84s
```
（inspector 同款聚焦文件）
