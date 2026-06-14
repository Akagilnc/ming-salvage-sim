# 个人认同度层（人≠党）— 深挖 ledger（2026-06-14，承 #112 / dig-5 flag）

> 全量在 task 输出：`/private/tmp/claude-501/.../tasks/wc1f9keyd.output`（4-agent：1 ground定逆案六等 + 2 design + 1 synth；首跑因 schema 属性名西里尔字母 400，修后重跑）。**设计累积，待用户拍①后定稿。**

## identity = 第五个 per-人值，只缩"同党反应"
- `characters` 加 `identity INTEGER DEFAULT 50` [0,100]——答"此人多真是其挂名 faction 的核心"。**与 faction(名义)/seed-guilt(罪)/#89 loyalty 全正交**。
- **只干一件事**：缩 dig-4「同类防备底(kinship 臂)」的乘数 k_id=clamp(identity/100,0,1)。**direct 血债臂签名物理不接 identity**。
- 不做 per-轴 identity(那是矩阵的活)；一个标量缩整体 kinship。

## 两旋钮分离（核心）
- **失称度**(罪罚相称，来自 seed-guilt)→ direct 血债(对被办者派、不可逆 floor)。
- **认同度**(identity，来自逆案六等)→ kinship 强度(可归零)。
- 四象限：①核心死党(高罪高认同)=血债低(法办)但全党炸 ②边缘投机(低罪低认同)=血债≈0+kinship≈0=全党无感(北极星复现) ③低认同高罪=direct足但kinship低 ④高认同低罪=direct小但kinship高。
- 数值例(同抄阉党sev70/走程序leg10%/dig-4 direct+7)：崔呈秀(id95)→kinship≈2+direct7=全党炸；建祠知县(id15)→kinship=0=乐见顶包。

## 叛变（复用 faction 字段，零新机制）
- 低认同(0-40)可反正；高认同核心(崔呈秀)不可叛。identity 一列兼"认同度+叛变倾向(反比)"。
- 触发=纯裁判软判(无硬阈值)。落库(P1，走 ADR0009 person delta)：改 `characters.faction` + 新增 `defected_from` 列 + identity 重置新派低值(≈30)。
- 涌现：善待低认同阉党边缘人→反正→带内情成办崔呈秀的刀(北极星"过去布局决定余地")。

## P4 / seed
- 玩家不见 identity 数；读"魏珰死党/五虎"vs"貌合神离/随班建祠自保"+旁观反应强度(全党炸vs松口气)+迷雾(传闻会骗、坐实经厂卫/苦主)。
- seed 从《钦定逆案》六等映射：首逆90-100/爪牙80-95/真党非中枢50-70/边缘从过20-40/挂名被裹挟5-20/投机墙头草5-15。温体仁/周延儒=5-15(史上后来主政也按"认同真伪"给低)。content.py int_field 链 + 老档 ensure_column DEFAULT 50。

## 对抗自检（全过）
不破矩阵(per-人缩kinship非细分42格)/不破血债(direct臂不接identity)/不破seed-guilt(正交)；非新轴=dig-4 kinship 的精度补丁；gaming洞(无脑清边缘=direct血债主刹车+无政治收益；逼反水=软判+无数值面板双收窄)。

## ⚠️ 两个必须明说
1. **要动 dig-4 一处**：去掉 kinship 臂 `max(1,…)` 下界让其可归零——动了已收敛 dig-4「同类防备底单调棘轮」语义，**必回 dig-4 走一轮评审，不默默改**(centrifuge_log amount CHECK≥0 与单调语义 0-vs-1 边界)。**= 待用户拍①。**
2. **实现端缺口**：db.py 现无 `UPDATE characters SET faction=?` 写路径(faction 仅 INSERT 时写)；叛变落库须补此口径。设计先钉，实现按 DoD 点检。

## 边界（最小版 vs #89）
本层只碰：identity+defected_from 两新列 + faction 既有列(补UPDATE) + dig-4 kinship 一行 + season_simulator 话术。**留 #89**：loyalty/ability/integrity/courage 接机制、identity 动态漂移、叛变硬概率/关系图、后期新罪更新 identity。越此即停手归 #89。

## ✅ 用户拍板（2026-06-14，认同度层定稿）
- **1（真决定）✅ 拍：同党反应真归零** = 去掉 dig-4 kinship 的 max(1) 下界(乐见顶包成立)。**已落 dig-4 公式(line 26)，标明随血债 sub-ADR 一起走 CMR 重确认**。
- **2–5 ✅ 拍接受最小默认**：k_id 先线性(playtest 再调) / identity 暂兼"叛变倾向"先简化 / 262人 seed "六等骨架+争议从轻(认同度从低)" / 反水者新派低认同≈20(中立派 kinship 本就一盘散沙)。
- **认同度层定稿**（待整体随血债 sub-ADR + dig-4 改动一起走评审）。
