# #484 R4 史实依据草稿

供 owner 逐字段亲核；这里只记录本轮六名新增/改动人物的字段依据。`office_type` 取仓库 `content/offices.json` 的 `allowed_types`，`location` 取 `content/regions.json` 的 `id`，不是自由文本。人物画像字段若没有本轮现有史料直接支持，明确标为“推断——待 owner 拍”，不伪装成史实定论。

| 人物 | 字段 | 本轮值 | 出处/判断 |
|---|---|---|---|
| 郭允厚 | `faction` | 阉党 | 推断——待 owner 拍：按其逆案/依附内廷的档案口径归类。 |
| 郭允厚 | `aliases` | 郭允厚、郭尚书、郭户部 | 推断——待 owner 拍：由本名、现职称谓生成可检索别名。 |
| 郭允厚 | `personal_skills` | 部务守成、钱粮案牍、依附内廷 | 推断——待 owner 拍：由户部尚书现职与档案叙述归纳。 |
| 郭允厚 | `identity` | 45 | 推断——待 owner 拍：人物画像先验，不是史料量化值。 |
| 郭允厚 | `debut_month` | 0（null/不限月） | 推断——待 owner 拍：仅锁定登场年，现有来源未给到本月。 |
| 郭允厚 | `seed_guilt.crime` | 交结近侍又次等 | 《明史》卷306相关逆案条目；原档案罪名保留，未改写史料措辞。 |
| 郭允厚 | `seed_guilt.severity` | 中 | ADR 0011-4 罪谱只有 `无/轻/中/重`；“交结近侍又次等”不是枚举字面值，按“次等”落现有中档。该映射待 owner 结合逆案分等复核。 |
| 李从心 | `faction` | 阉党 | 推断——待 owner 拍：按其逆案/依附内廷的档案口径归类。 |
| 李从心 | `aliases` | 李从心、李尚书、李总河、工部尚书、总理河道 | 推断——待 owner 拍：由本名、复合现职和常用职称生成可检索别名。 |
| 李从心 | `personal_skills` | 河道治理、漕运工程 | 推断——待 owner 拍：由总理河道现职归纳。 |
| 李从心 | `identity` | 42 | 推断——待 owner 拍：人物画像先验，不是史料量化值。 |
| 李从心 | `debut_month` | 0（null/不限月） | 推断——待 owner 拍：仅锁定登场年，现有来源未给到本月。 |
| 李从心 | `office` / `office_type` | 工部尚书，总理河道，兼都察院右副都御史 / 工部 | 本轮未改；保留 R2 的复合现职及 `offices.json` 可识别的工部口径。 |
| 李从心 | `seed_guilt.crime` | 交结近侍又次等 | 《明史》卷306相关逆案条目；原档案罪名保留。 |
| 李从心 | `seed_guilt.severity` | 中 | 同郭允厚：依 ADR 0011-4 的 `无/轻/中/重` 现有语义归一；映射待 owner 复核。 |
| 胡廷宴 | `faction` | 阉党 | 推断——待 owner 拍：按其逆案罪名与开局档案口径归类。 |
| 胡廷宴 | `aliases` | 胡廷宴、胡巡抚 | 推断——待 owner 拍：由本名与现职称谓生成可检索别名。 |
| 胡廷宴 | `personal_skills` | 陕西赈济、巡抚地方、边镇调度 | 推断——待 owner 拍：由陕西巡抚现职归纳。 |
| 胡廷宴 | `identity` | 50 | 推断——待 owner 拍：人物画像先验，不是史料量化值。 |
| 胡廷宴 | `debut_month` | 0（null/不限月） | 推断——待 owner 拍：开局 active，不使用伪精确月份。 |
| 胡廷宴 | `office` / `office_type` / `status` | 陕西巡抚 / 地方 / active | `office_type` 按 `content/offices.json` 的 allowed_types 归一；现有材料只支持其开局陕西巡抚口径，本轮不追加未核的前任职衔。 |
| 胡廷宴 | `seed_guilt.crime` | 请建魏忠贤生祠 | R2 已采用的逆案史实依据；罪名字面保留。 |
| 胡廷宴 | `seed_guilt.severity` | 轻 | ADR 0011-4 只接受 `无/轻/中/重`；原“轻等”归 `轻`，待 owner 复核具体逆案分等。 |
| 张缙彦 | `faction` | 皇党 | 推断——待 owner 拍：开局人物画像归类，不等同于史料中的固定党籍。 |
| 张缙彦 | `aliases` | 张缙彦、张坦公、张举人 | 推断——待 owner 拍：本名、字“坦公”与早年身份称谓的检索别名。 |
| 张缙彦 | `personal_skills` | 经学应试、经世议论、地方治理 | 推断——待 owner 拍：由进士出身及清涧知县登场职能归纳。 |
| 张缙彦 | `identity` | 70 | 推断——待 owner 拍：人物画像先验，不是史料量化值。 |
| 张缙彦 | `debut_month` | 0（null/不限月） | 推断——待 owner 拍：来源只支持 1631 年，不支持具体月份。 |
| 张缙彦 | `office` / `office_type` | 清涧知县 / 地方 | 1631 年中进士后初任清涧知县：[张缙彦资料](https://zh.wikipedia.org/wiki/張縉彥)；`知县` 按 `content/offices.json` 的地方类归类。 |
| 张缙彦 | `status` / `debut_year` | offstage / 1631 | 同上；1627.10 尚未中进士，档案存登场时职衔而非早年举人身份。 |
| 汤若望 | `faction` | 西学 | 推断——待 owner 拍：按其传教士、历算与西学档案口径归类。 |
| 汤若望 | `aliases` | 汤若望、汤先生、亚当 | 推断——待 owner 拍：本名、尊称及 Adam Schall 的常用中文称谓。 |
| 汤若望 | `personal_skills` | 天文历算、火器铸造、西洋测量 | 推断——待 owner 拍：由现有中国新闻网、故宫博物院资料及人物工作口径归纳。 |
| 汤若望 | `identity` | 66 | 推断——待 owner 拍：人物画像先验，不是史料量化值。 |
| 汤若望 | `debut_month` | 4 | 中国新闻网资料、故宫博物院资料支持其 1630 年入历局；按“邓玉函于 1630-04 去世后获荐”的史实顺序取 4 月，月份仍待 owner 拍。 |
| 汤若望 | `office` / `office_type` | 钦天监历局修历 / 礼部 | 1630 年徐光启荐入北京钦天监历局参与修历：[中国新闻网资料](https://www.chinanews.com.cn/cul/2010/12-29/3799256.shtml)、[故宫博物院《西洋新法历书》](https://www.dpm.org.cn/ancient/yuanmingqing/144006.html)；现有 office 枚举无“历局”，按历局所属礼部系统取 `礼部`，职衔为保守业务口径。 |
| 汤若望 | `status` / `debut_year` / `location` | offstage / 1630 / beizhili | 1630 年由西安调北京入历局；`beizhili` 是 `content/regions.json` 中合法京畿 region id。 |
| 李之藻 | `faction` | 西学 | 推断——待 owner 拍：按其历法、西学与历局工作口径归类。 |
| 李之藻 | `aliases` | 李之藻、李我存、李先生 | 推断——待 owner 拍：本名、字“我存”与常用尊称的检索别名。 |
| 李之藻 | `personal_skills` | 西学译述、历法算学、水利舆地 | 推断——待 owner 拍：由现有李之藻资料及历局工作口径归纳。 |
| 李之藻 | `identity` | 72 | 推断——待 owner 拍：人物画像先验，不是史料量化值。 |
| 李之藻 | `debut_month` | 0（null/不限月） | 中国哲学书电子化计划及李之藻资料支持 1629 年起复修历，但未给可靠月份，故不填 1。 |
| 李之藻 | `office` / `office_type` | 历局修历起复 / 礼部 | 1629 年起复负责修订历法：[李之藻资料](https://zh.wikipedia.org/wiki/%E6%9D%8E%E4%B9%8B藻)、[中国哲学书电子化计划](https://ctext.org/datawiki.pl?if=gb&remap=gb&res=213600)；“历局”无独立 office_type，按礼部系统取 `礼部`，避免把旧 `工部` 粗类带入。 |
| 李之藻 | `status` / `debut_year` / `location` | offstage / 1629 / beizhili | 1623 去职、1629 起复修历；起复地点按北京历局取合法 `beizhili`。 |

## 合同依据

- `docs/adr/0011-4-ceiling-and-seed-roster.md`：seed guilt 的 `severity` 罪谱采用 `无/轻/中/重`，并以重/中/轻分层。
- `content/offices.json`：`allowed_types` 与职名词干分类；`知县` 属 `地方`，历局修历暂无专门类型，保守落礼部系统。
- `content/regions.json`：陕西=`shaanxi`，京畿/京师=`beizhili`。

## 待核标记

- “交结近侍又次等”归 `中` 是按现有四档语义做的保守归一，不把逆案原始六等直接伪装成 schema 原生枚举；请 owner 结合《明史》卷306/逆案分等决定是否改为其他现有档。
- “钦天监历局修历”“历局修历起复”是为了表达登场时工作口径的保守档案职衔，不声称是正式品秩；若 owner 有更精确的历局职名，应只改 `office`，保留 `office_type`/年份/region 合同。
