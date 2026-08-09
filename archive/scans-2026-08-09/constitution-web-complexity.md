## 违宪扫描 · 复杂度（只读，~6min）

法源按你列的量度：单组件/函数 >200 行、嵌套 >4、巨 props 透传、≥3 次重复未抽、speculative generality、死代码。范围：`web/src` TS/TSX；召对/角色视角优先。  
注：无文件名含 `dossier` / `perspective` / `chip`；命中集中在 `main` / `drawers` / `modals` / `hud` / `useAudienceChat`。

| 严重度 | 标题 | file:line | 违反点 | 证据 | 说明 |
|---|---|---|---|---|---|
| P0 | `App` 上帝组件 | `web/src/main.tsx:24` | 单函数超 200 行 + 嵌套超 4 | **1337 行**（L24–1360）；brace nest **6**；indent peak **8**；`useState`×**53** | 召对/抽屉/诏书全堆一函数，状态与透传源点 |
| P0 | 召对巨 props 透传 | `web/src/components/modals.tsx:501` ← `main.tsx:1202` | 巨 props 对象层层透传 | **`ChatModal` 27 props**（含 10+ handler）；App 逐字段灌入 | 召对 UI 无本地容器/上下文，接口面过宽 |
| P1 | 拟诏巨 props 透传 | `web/src/components/modals.tsx:772` ← `main.tsx:1247` | 巨 props 透传 | **`EdictModal` 23 props**；函数 **219 行**；indent nest **11** | 与 Chat 同构：状态机留在 App |
| P1 | 朝班名片巨函数 | `web/src/components/drawers.tsx:7` | 超 200 行 + 嵌套超 4 | **`MinisterCardList` 263 行**；brace nest **9**；indent **9**（峰 ~L204） | 排位/拖拽/网格/朝班两套渲染揉一体 |
| P1 | 抽屉搜索列表未抽 | `web/src/components/drawers.tsx:272+` | ≥3 次重复未抽 | `const [q, setQ]` ×**7**；`right-drawer-search-input` ×**7**；`Army`/`Region` 列表+详情骨架同构 | 五+抽屉复制 search→filter→list→detail |
| P1 | 朝堂/后宫壳重复 | `drawers.tsx:583` / `:645` | ≥3 次级重复（近复制） | 精确相同 strip 行 **41**/58 vs 55；scrim+aside+segmented+search+`MinisterCardList` | 两抽屉应共一壳，仅 group/标题/prefix 不同 |
| P1 | 肖像 URL 三处复制 | `drawers.tsx:188`、`:221`；`modals.tsx:560` | ≥3 次重复未抽 | `custom:` + `/portraits/custom/...` + `portraitPrefix` 块 ×**3** | 角色视角共用逻辑未下沉 helper |
| P1 | HUD 旧导航死代码 | `web/src/components/hud.tsx:167`、`:374`、`:631` | 死代码 | `RightNavBar`(~55行)、`TopStatusBar`(~45)、`BottomCommandBar`(~59) **全仓零引用**（main 已内联 HUD） | W1/W2 改版遗留，约 160 行可删 |
| P2 | 地图上帝组件 | `web/src/components/map.tsx:51` | 超 200 行 + 嵌套超 4 | **`GrandMap` 706 行**；brace nest **7**；indent **14** | 非召对核心，但同属 W UI 交付面 |
| P2 | `ChatModal` 自身过长 | `web/src/components/modals.tsx:501` | 超 200 行 + 嵌套超 4 | **270 行**；indent nest **10**（峰 ~L673） | 失败恢复/流式/密令/composer 未拆子组件 |
| P2 | 七路抽屉布尔状态 | `web/src/main.tsx:43-49` | speculative / 未收敛抽象 | 7×`*DrawerOpen` + 同类 `set*`（main 内相关命中 ~28） | 互斥抽屉本可用单一 `activeDrawer` |
| P2 | 死导出 + 空 props | `hud.tsx:80`；`drawers.tsx:584` | 死代码 / speculative | `defaultCourtPct` **零引用**；`CourtDrawer` 的 `state: _state` **故意丢弃仍必传**（`main.tsx:1123`） | 假依赖扩面，无行为 |

### 未发现（本范围内）
- 大段注释掉的代码块（≥8 行连续 `//` / 非文档 `/* */`）：**无**
- 文件名含 dossier/perspective/chip 的组件：**无**（角色视角走 `Minister*` / `ChatModal` / drawers）

### 一句总判
最大违宪面是 **`App` 上帝组件 + 召对/拟诏巨 props 透传**；次之是 **`MinisterCardList` 与抽屉样板重复**；再加 **HUD 旧栏死代码** 可直接砍。
