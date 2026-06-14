# 敏感度天花板 ceiling 查表（决定1）— dig（2026-06-14，substrate 最后一格）

> 来源:workflow `wtvac0cjm`(ceiling-sensitivity-table) ——ground+2路设计**跑完且高度收敛**,但 synth 卡死(快1小时未出完整 StructuredOutput);**Claude 从 3 个完成结果(journal)自合成**(synth 那点活)。原始 3 结果存 `/tmp/ceiling_3results.json`。**待用户拍。**

## Ceiling 表（[0,100]，给 naive 动作的墙；命门三级）
| 轴 | base | 命门级 | 史实锚 |
|---|---|---|---|
| 礼法名节·祖制硬核(易储/废嫡/削藩除国/动太庙祖陵/私改科举根本) | **95** | T0 最高墙 | 国本之争15年完败、三王并封数日撤回 |
| 华夷战和(议和/称臣纳贡/弃边) | **85** | T1 | 陈新甲议和泄密弃市(密旨暴露即崩、皇帝无认账选项) |
| 礼法名节·清议名节(夺情起复/南迁去社稷/违清议) | **82** | T1 | 杨嗣昌夺情终任被抨击、南迁无人联署 |
| 既得利益(夺产/夺爵/逼捐/清丈抗免田/裁宗禄) | **72** +目标leverage | T2(命门最低、唯一leverage强调制) | 李国瑞逼捐忧惧死→退银复爵、薛国观助饷代理人赐死 |
| 民本恤民(蠲免/赈灾/招抚) | 40 | 非命门 | 朝堂四层不挡(德政、清议反支持);真代价在阶层民变=外压 |
| 实务事功(练兵/修城/调粮/核饷/营建流程) | 35 | 非命门 | 关宁筑城——能不能颁从不是问题,阻力在财政dynamic臂 |
| 皇权依附(拔孤臣/用厂卫/倚内廷) | 30 | 非命门最低 | 温体仁孤臣执政八年——拆权力网靠顺序耐心非ceiling挡 |

## 目标 tag modifier（加数制，好写 golden）
- **祖制 tag**=合取(动作∈{册封/废后/易储/除国} × office_type∈{后宫/宗藩} × reason_code∉依律集)→**换行路由到 95**(不是加数)。
- **宗室 tag**(faction==宗室):祖制轴+5(95→100顶满)/既得轴加法统加成。宗室双命门(法统T0+既得T2),撞哪条看 axis-tag。
- **勋戚外戚 tag**(office_type==后宫∨爵位正则派生——无干净faction必须硬派生):既得轴+8→85;叠"代理人保险丝"(大臣代行强夺勋戚→暴露反噬,薛国观锚)。
- **高 leverage**(仅既得轴):既得 ceiling=max(72, leverage_target)——lev92南直东林士绅顶85、lev22闲散宗藩塌50。从 classes/powers 结构化 leverage 读,非LLM。

## ⭐ 出路恒可达（硬不变式，已证明无绝对墙）
**命门度挂 `axis-tag(私意 vs 坐实)`、不挂目标身份。** 三步:① 走程序坐实→`reason_code∈{依律/谋逆坐实/贪墨坐实}`(机读枚举非措辞,堵H5);② 轴翻转:`if 依律翻轴: axis="依律处置"`——不论原axis祖制95/既得72+14,**reason_code=依律一律重路由到非命门「依律处置」行(base~35)**（⚠️ 华夷85 除外:议和无罪可坐实=无翻轴路,走外压杠杆出路非翻轴,见 0011-4 D4-4(b) 收口）(换行查非改值,命门tag触发条件含reason_code≠依律→坐实时整体不命中、modifier归零);③ effective ceiling 塌。同一福王:naive私意抄家=既得+宗室≈91 → 查实通寇依律除国=35。**ceiling 表里没有任何命门题永远封死(有罪可坐实者走翻轴、无罪的华夷议和走外压杠杆,两机制覆盖全部命门轴;见 0011-4 D4-4)。** 定逆案262人=走程序把清算做成依律惩逆。

## 命门=合法性 FLOOR（ground 关键洞，补强 dig-8 resolve）
命门 ceiling 不只是 min() cap,是一条**合法性硬底**:`per_layer_resistance = max(α×血债, 命门合法性floor, min(ceiling, dynamic))`。命门题即便各派dynamic低(没人激烈反对),合法性floor仍把阻力托到ceiling——国本之争原型(文官未必个个激烈,祖制底线集体托95,15年颁不动)。**dig-8 resolve 公式据此加 命门合法性floor 臂。**

## 结构化查表(决定1,堵H5)
ceiling key=(axis-tag从DELTA七动作/reason_code结构化派生, leverage段从classes/powers, 命门tag集) 全机读字段、零LLM措辞;翻轴开关=reason_code机读枚举。残留=动作目标name抽取仍过extractor(同dig-6 H5残留,name须命中既有行)。

## 待用户拍
- ceiling 表骨架(三级命门+非命门+目标tag)+ 命门=合法性floor + 出路恒可达(axis-tag翻轴) = 设计。**精确值(95/85/82/72/35/40/30 + modifier量)= 首版,随矩阵α/β playtest调参(镜像spike G1-G22方法学),非现在拍死。**
- modifier 数学:取加数制(设计2,好写golden);设计1乘加制弃。
- **substrate 至此机制+值全齐**(血债dig-4/矩阵dig-5/认同度dig-6/seed dig-7/ceiling dig-9);四层resolve(dig-8)读它们的料都有了。
