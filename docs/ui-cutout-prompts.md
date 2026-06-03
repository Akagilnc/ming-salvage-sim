# UI 切图生图提示词（图生图 / 抠图）

把参考稿 `web/public/ui-reference-11236.jpg` 里的关键 HUD 元素切出，叠层用。
**不切底部大地图**，只切界面控件。

> **背景：一律纯白**。此生图模型不支持透明背景，所有图出**纯白底**，元素居中。
> 出图后我用 rembg 把纯白抠成透明，落到 `web/public/ui/rembg/`（文件名见各条）。

> **设计改动（相对参考图）**：
> - 拟诏印 → 改成**玉玺**（青白玉螭龙纽宝玺），不要印泥红章。
> - 奏疏（铜印+奏折）→ 改成**圣旨卷轴**（明黄绫圣旨）。
> - **底部案板单独出一张**，不要和上层元素混在一张里。

---

## 推荐：两张出（风格零漂移）

源图都用整张 `ui-reference-11236.jpg`，强度低 → 照抄源图色调，风格统一。出完我用 PIL 按实测坐标切成独立 PNG。

### A 图：上层全部元素（**完全没有案板**）`hud-overlay-full.png`
- 源图 `ui-reference-11236.jpg`，强度 `0.3`，**纯白背景**，尺寸 2560×1440
- 关键：**底部那条木案板彻底删掉**，案上的道具全部脱离案板、各自独立摆在纯白背景上，彼此留空隙，方便单独抠图。
```
保留画面中所有上层界面控件——顶部资源横轴卷轴、朝堂红印按钮、后宫玉牌、长期目标卷标、菜单木牌、左侧局势进度宣纸面板，以及下方一排独立道具：圣旨明黄绫卷轴、邸报卷轴、密令折册、史册线装书、青白玉螭龙纽玉玺与木座；完整保留它们的形状与做旧质感。把原来的铜印奏折改画成一卷明黄绫圣旨；把右下角的红印泥大印改画成一方青白玉雕螭龙纽玉玺，温润玉质不要红漆。**底部那条深色木案板/桌板必须完全删除，不要任何桌面或托底**，下排每件道具各自独立摆放、互不相连、之间留出空隙。把中间整张大地图、海洋、陆地、地名全部抹除。**整张背景换成纯白色**，所有元素摆在纯白背景上。明末古风中式游戏 UI，做旧宣纸与大漆木质，金线描边，手绘工笔，高细节，4k
```
负向：
```
地图, 地形, 海洋, 海岸线, 山脉, 省份, 木案板, 桌板, 桌面, 托底, 案几, 阴影投影, 印泥红章, 改变布局, 重排控件, 道具粘连, 彩色背景, 渐变背景, 杂乱背景, 多余文字, 模糊, 低分辨率, jpeg噪点, 水印
```

### B 图：案板单出 `bottom-desk.png`
- 源图 `ui-reference-11236.jpg`，强度 `0.4`，**纯白背景**，横构图 2048×512
```
只保留画面底部那条深色花梨木御案桌板，两端圆角，浓郁木纹漆光；把案板上的所有物件（圣旨、邸报、密令、史册、玉玺）和上方地图全部抹除，只剩一条空木案板，略带俯视角，大漆帝王案几，整张背景换成纯白色
```
负向：
```
桌上物件, 卷轴, 书册, 印章, 地图, 彩色背景, 渐变背景, 杂乱背景, 多余文字, 模糊, 低分辨率, jpeg噪点, 水印
```

---

## 备选：逐元素单出

若两张出抠不干净，按下表逐个出。每条统一加风格尾巴与负向词。

**通用负向词**：
> 地图, 地形, 海洋, 海岸线, 山脉, 省份, 彩色背景, 渐变背景, 杂乱背景, 背景阴影, 多余文字, 重复文字, 模糊, 低分辨率, jpeg噪点, 水印

**统一风格尾巴**：
> ，明末古风中式游戏 UI 素材，做旧宣纸与大漆木质，金线描边，手绘工笔，单个元素，居中，**纯白色背景**，高细节，4k

---

## 顶部 HUD

### 资源横轴 `hud-scroll-full.png`
裁切参考：顶部 y 0–115，整条宽
```
一条横置的长卷轴横幅，象牙色做旧宣纸面，两端铜质卷轴杆，左端一枚小红印，卷面四角金色云纹，卷面留白可写字，单条横置 UI 资源栏
```

### 朝堂按钮 `nav-court-large.png`
```
一枚圆形深红大漆木质印章按钮，圆面阳刻「朝堂」二字，外裹方形青铜灰雕花底座，四角云雷纹，圆盘面有漆光
```

### 后宫按钮 `nav-harem-large.png`
```
一块竖立的淡青玉牌挂坠，牌面阴刻「后宫」二字，顶部圆弧花瓣形带铜环，金边玉质，宫廷令牌
```

### 长期目标标签 `nav-goal-large.png`
```
一卷小号做旧纸卷标签，两端铜质卷杆，右侧垂一缕红流苏绳结，卷面象牙色留白，横置迷你手卷牌
```

### 菜单按钮（三横）`nav-menu-large.png`
```
一块做旧方形宣纸瓦片，粗糙金棕色描边，纸面三道粗黑毛笔横线（汉堡菜单），做旧纸质
```

---

## 左侧面板

### 局势进度面板 `side-situation-panel.png`
裁切参考：左侧 x 0–360，y 175–840
```
一叠层叠的做旧宣纸，竖向面板状，纸边毛糙破损，纸面淡淡的红印章与细进度条线，左侧一根深色挂绳系小玉珠，残破卷宗册页
```

---

## 底部御案与道具（不含地图）

### 御案木条 `bottom-desk.png`
裁切参考：横构图 2048×512
```
一条长形深色花梨木御案桌板，两端圆角，浓郁木纹漆光，单条横向案板，略带俯视角，大漆帝王案几，案上不放任何物件
```

### 圣旨卷轴 `memorial-seal-docs.png`
```
一卷半展开的明黄色绫缎圣旨，两端镶玉轴头，卷面织金云龙纹，竖排黑色小楷诏文与一枚朱红玉玺印，皇帝圣旨手卷
```

### 邸报卷轴 `report-scroll-doc.png`
```
一卷摊开的做旧纸手卷，两端铜质卷杆，竖排黑色毛笔小楷，一缕红流苏绳与一枚方形玉挂牌阴刻印文
```

### 密令折册 `secret-document.png`
```
一本折叠的米色纸册，竖向缠一条红色封带，封带上一枚黑色圆形「密」字印，细金绳系扎，密旨折册
```

### 史册（大明会典）`history-book.png`
```
一册传统中式线装古书，做旧深蓝封皮，封面贴象牙色书签题「大明会典」，竹丝订线书脊，深色绳结带流苏，古旧典册
```

### 玉玺 `edict-seal-large.png`
```
一方青白玉雕的传国玉玺，方形玺身温润玉质带天然玉纹，顶部螭龙纽（盘龙钮），置于一座精雕深色木质蟠龙印座上，垂一缕红编织流苏，玉质宝玺，不要红漆不要印泥
```

---

## 新稿切图（基于 `web/public/最新ui.jpg`）

> 源图换成 `最新ui.jpg`，其余出图参数同上（强度 0.3，纯白背景，4k）。

### HUD 顶栏 `hud-top-bar-new.png`
裁切参考：顶部整条 y0–60，全宽
```
A single horizontal UI bar for a Chinese Ming dynasty strategy game. Dark lacquered wood texture background with gold border trim. Contains status readouts from left to right: year/month date "1628年3月", treasury "国库 0万两 ↓-54万", internal treasury "内库 0万两 ↓-22万", popular sentiment "民心 53", imperial authority "皇威 0". Each stat has small icon and numeric value in red/gold Chinese text. Right side has tab buttons: "朝堂" "后宫" "长期目标" "三案单" — paper/silk scroll tabs with brushwork text, active tab slightly raised. Top edge subtle red ribbon trim. Flat UI, no 3D, game HUD style. Pure white background, centered, isolated element.
```
负向：
```
地图, 地形, 彩色背景, 渐变背景, 底部桌案, 道具, 立体阴影, 模糊, 水印
```

### 局势进度面板 `side-situation-panel-new.png`
裁切参考：左上角面板，约 x0–300 y60–320
```
A semi-transparent parchment-style UI panel for a Ming dynasty strategy game. Aged yellowed paper texture with dark ink border, slight scroll curl at edges. Title row "局势进度" in seal script with small red wax stamp chop icon. Below: one status entry highlighted in red-orange "已崩坏" with subtext "辽东索饷" and penalty stats. Two further plain rows "户部亏空 28" and "陕西流盗起 40" with right-aligned numbers. Narrow portrait-proportioned panel. Pure white background, isolated element, no map behind it.
```
负向：
```
地图, 地形, 彩色背景, 渐变背景, 桌案, 道具, 模糊, 水印
```

### 底部案板（空，不含道具）`bottom-desk-new.png`
裁切参考：底部横条 y约1100–1440，全宽；只要案板本身，道具全移除
```
A single empty imperial desk surface, wide horizontal strip, slight overhead angle. Deep dark huanghuali rosewood grain with glossy lacquer sheen, two rounded ends. No objects on the surface — completely bare. Slight specular highlight along top edge. Pure white background above and below the desk strip. Wide landscape crop 4:1 ratio. Ming dynasty imperial furniture, painterly illustration style, high detail.
```
负向：
```
卷轴, 书册, 折册, 玉玺, 印章, 道具, 地图, 地形, 彩色背景, 渐变背景, 模糊, 水印
```

### 底部案头四道具（不含案板）`desk-items-new.png`
裁切参考：底部横条 y约1100–1440，全宽；只要道具，不要案板木条
```
Four individual prop items floating on pure white background, no desk surface, no table, no wood beneath them. From left to right: (1) a rolled paper scroll "奏疏" — aged rice paper partially unrolled, ink brushwork text, bronze end caps; (2) a folded map document "邸报" — worn parchment folded in quarters, red cord tie, faded ink; (3) an official edict document "密令" — cream paper booklet with red wax seal and red ribbon wrap; (4) a thick bound history book "史策" — dark blue cloth cover, ivory title label, stitched binding. Each item rendered in painterly Ming dynasty illustration style, aged paper and silk textures, soft drop shadow beneath each item. Items evenly spaced in a horizontal row. Pure white background, isolated props only.
```
负向：
```
桌面, 案板, 木纹桌板, 地图, 地形, 玉玺, 彩色背景, 渐变背景, 阴影投在桌上, 模糊, 水印
```

### 玉玺按钮 `edict-seal-new.png`
裁切参考：右下角，约 x2050–2560 y940–1440
```
An imperial jade seal UI button for a Chinese Ming dynasty strategy game. Red carved wooden stand base with ornate dragon relief carvings, vermillion lacquer finish with gold accent trim. On top sits a large green nephrite jade seal block with dragon knob handle. Beside: a red silk label reading "拟招 结束回合" in gold brushwork text. Rich painterly illustration, dramatic lighting, jewel-like jade translucency. Pure white background, isolated element, no desk surface, no map.
```
负向：
```
地图, 地形, 桌案底板, 彩色背景, 渐变背景, 印泥红章, 模糊, 水印
```

---

## 切图清单（对照表）

| 元素 | 文件名 | 裁切区域（2560×1440 参考图） |
|---|---|---|
| 资源横轴 | `hud-scroll-full.png` | 顶部整条 y0–115 |
| 朝堂 | `nav-court-large.png` | x1480 附近 |
| 后宫 | `nav-harem-large.png` | x1620 附近 |
| 长期目标 | `nav-goal-large.png` | x1780 附近 |
| 菜单 | `nav-menu-large.png` | 右上角 |
| 局势面板 | `side-situation-panel.png` | x0–360 y175–840 |
| 御案（**单出 B 图**） | `bottom-desk.png` | 底部横条，空案板 |
| 圣旨卷轴 | `memorial-seal-docs.png` | 御案上 x470–760 |
| 邸报 | `report-scroll-doc.png` | 御案上 x800–1140 |
| 密令 | `secret-document.png` | 御案上 x1235–1430 |
| 史册 | `history-book.png` | 御案上 x1555–1820 |
| 玉玺 | `edict-seal-large.png` | 右下 x2105–2480 |

> 生图走中转网关有已知 400 bug，绕法见 `portrait-gen` skill。批量跑可复用 `scripts/gen_portraits.py` 思路。
