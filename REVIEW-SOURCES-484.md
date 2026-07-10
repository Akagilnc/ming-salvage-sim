# #484 R3 史实依据草稿

供 owner 逐字段亲核；这里只记录本轮六名新增/改动人物的字段依据。`office_type` 取仓库 `content/offices.json` 的 `allowed_types`，`location` 取 `content/regions.json` 的 `id`，不是自由文本。

| 人物 | 字段 | 本轮值 | 出处/判断 |
|---|---|---|---|
| 郭允厚 | `seed_guilt.crime` | 交结近侍又次等 | 《明史》卷306相关逆案条目；原档案罪名保留，未改写史料措辞。 |
| 郭允厚 | `seed_guilt.severity` | 中 | ADR 0011-4 罪谱只有 `无/轻/中/重`；“交结近侍又次等”不是枚举字面值，按“次等”落现有中档。该映射待 owner 结合逆案分等复核。 |
| 李从心 | `office` / `office_type` | 工部尚书，总理河道，兼都察院右副都御史 / 工部 | 本轮未改；保留 R2 的复合现职及 `offices.json` 可识别的工部口径。 |
| 李从心 | `seed_guilt.crime` | 交结近侍又次等 | 《明史》卷306相关逆案条目；原档案罪名保留。 |
| 李从心 | `seed_guilt.severity` | 中 | 同郭允厚：依 ADR 0011-4 的 `无/轻/中/重` 现有语义归一；映射待 owner 复核。 |
| 胡廷宴 | `office` / `office_type` / `status` | 陕西巡抚 / 督抚 / active | 本轮未改，沿用 R2 已收敛档案；现有材料只支持其开局陕西巡抚口径，本轮不追加未核的前任职衔。 |
| 胡廷宴 | `seed_guilt.crime` | 请建魏忠贤生祠 | R2 已采用的逆案史实依据；罪名字面保留。 |
| 胡廷宴 | `seed_guilt.severity` | 轻 | ADR 0011-4 只接受 `无/轻/中/重`；原“轻等”归 `轻`，待 owner 复核具体逆案分等。 |
| 张缙彦 | `office` / `office_type` | 清涧知县 / 地方 | 1631 年中进士后初任清涧知县：[张缙彦资料](https://zh.wikipedia.org/wiki/%E5%BC%B5%E7%B8%89%E5彦)；`知县` 按 `content/offices.json` 的地方类归类。 |
| 张缙彦 | `status` / `debut_year` | offstage / 1631 | 同上；1627.10 尚未中进士，档案存登场时职衔而非早年举人身份。 |
| 汤若望 | `office` / `office_type` | 钦天监历局修历 / 礼部 | 1630 年徐光启荐入北京钦天监历局参与修历：[中国新闻网资料](https://www.chinanews.com.cn/cul/2010/12-29/3799256.shtml)、[故宫博物院《西洋新法历书》](https://www.dpm.org.cn/ancient/yuanmingqing/144006.html)；现有 office 枚举无“历局”，按历局所属礼部系统取 `礼部`，职衔为保守业务口径。 |
| 汤若望 | `status` / `debut_year` / `location` | offstage / 1630 / beizhili | 1630 年由西安调北京入历局；`beizhili` 是 `content/regions.json` 中合法京畿 region id。 |
| 李之藻 | `office` / `office_type` | 历局修历起复 / 礼部 | 1629 年起复负责修订历法：[李之藻资料](https://zh.wikipedia.org/wiki/%E6%9D%8E%E4%B9%8B藻)、[中国哲学书电子化计划](https://ctext.org/datawiki.pl?if=gb&remap=gb&res=213600)；“历局”无独立 office_type，按礼部系统取 `礼部`，避免把旧 `工部` 粗类带入。 |
| 李之藻 | `status` / `debut_year` / `location` | offstage / 1629 / beizhili | 1623 去职、1629 起复修历；起复地点按北京历局取合法 `beizhili`。 |

## 合同依据

- `docs/adr/0011-4-ceiling-and-seed-roster.md`：seed guilt 的 `severity` 罪谱采用 `无/轻/中/重`，并以重/中/轻分层。
- `content/offices.json`：`allowed_types` 与职名词干分类；`知县` 属 `地方`，历局修历暂无专门类型，保守落礼部系统。
- `content/regions.json`：陕西=`shaanxi`，京畿/京师=`beizhili`。

## 待核标记

- “交结近侍又次等”归 `中` 是按现有四档语义做的保守归一，不把逆案原始六等直接伪装成 schema 原生枚举；请 owner 结合《明史》卷306/逆案分等决定是否改为其他现有档。
- “钦天监历局修历”“历局修历起复”是为了表达登场时工作口径的保守档案职衔，不声称是正式品秩；若 owner 有更精确的历局职名，应只改 `office`，保留 `office_type`/年份/region 合同。
